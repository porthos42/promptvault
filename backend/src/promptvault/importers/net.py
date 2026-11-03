"""SSRF-safe HTTP fetching for the URL importers. The only module that does network I/O.

Policy, enforced on the first request and on every redirect hop:

- only http and https, no userinfo in the URL, ports 80 and 443 only;
- the host is resolved (A and AAAA) and the fetch is refused when ANY address is not globally
  routable (loopback, private, link-local incl. cloud metadata, CGNAT, multicast, reserved,
  IPv4-mapped / compatible / 6to4 / NAT64 forms of those, ...). Odd IPv4 literals (decimal, octal,
  hex, short forms) are parsed here instead of being left to the resolver;
- the connection is pinned to the validated address (TLS still uses the host name for SNI and
  certificate checks), so DNS rebinding between check and connect cannot help;
- redirects are followed by hand: at most 3 hops, each re-validated, no https -> http downgrade;
- the body is streamed under a hard byte cap that also bounds decompressed size, with connect and
  total time limits, a content-type allowlist, no cookies and a fixed User-Agent.

`PV_IMPORT_ALLOW_PRIVATE_HOSTS` (host names, IPs or CIDRs, empty by default) is the opt-in escape
hatch: an entry matches exactly (no subdomain wildcards) and an allowed host may use any port.

Everything that touches the outside world is injectable (resolver, transport, clock), so tests
never use the network.
"""

from __future__ import annotations

import http.client
import ipaddress
import socket
import ssl
import threading
import time
import zlib
from collections import OrderedDict
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol
from urllib.parse import urljoin, urlsplit

from promptvault import __version__
from promptvault.services.errors import DomainError, ValidationFailed

USER_AGENT = f"PromptVault-Importer/{__version__} (+https://github.com/porthos42/promptvault)"
ALLOWED_PORTS = frozenset({80, 443})
MAX_REDIRECTS = 3
CONNECT_TIMEOUT = 10.0
CACHE_TTL = 300.0
CACHE_MAX_ENTRIES = 64
CACHE_MAX_BYTES = 16 * 1024 * 1024
BEARER_HOSTS = frozenset({"api.github.com", "raw.githubusercontent.com"})
REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
_CHUNK = 64 * 1024

IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address
IPNetwork = ipaddress.IPv4Network | ipaddress.IPv6Network


class FetchError(DomainError):
    """The remote side failed or misbehaved (not a policy refusal)."""

    status_code = 502
    title = "Fetch failed"


class BlockedURL(ValidationFailed):
    """The URL breaks the fetch policy (scheme, port, non-public address, ...)."""

    title = "URL blocked"


# --- address policy -------------------------------------------------------------------------

_NAT64 = ipaddress.ip_network("64:ff9b::/96")
_IPV4_COMPAT = ipaddress.ip_network("::/96")


def _v4(a: int, b: int, c: int, d: int, prefix: int) -> ipaddress.IPv4Network:
    return ipaddress.IPv4Network(((a << 24) | (b << 16) | (c << 8) | d, prefix))


_EXTRA_BLOCKED: tuple[IPNetwork, ...] = (
    _v4(0, 0, 0, 0, 8),  # "this" network
    _v4(100, 64, 0, 0, 10),  # CGNAT
    _v4(169, 254, 0, 0, 16),  # link-local, cloud metadata
    _v4(192, 0, 0, 0, 24),  # IETF protocol assignments
    _v4(198, 18, 0, 0, 15),  # benchmarking
    _v4(224, 0, 0, 0, 4),  # multicast
    _v4(240, 0, 0, 0, 4),  # reserved, incl. broadcast
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
    ipaddress.ip_network("ff00::/8"),
)


def parse_ip_literal(host: str) -> IPAddress | None:
    """An IP address if `host` is a literal in any notation (including legacy IPv4 forms such
    as `2130706433`, `0x7f.1` or `017700000001`); None for ordinary names.

    Raises BlockedURL for hosts that look numeric but are not valid addresses, so they are
    never passed on to a resolver that might be more lenient than we are."""
    text = host.strip("[]")
    try:
        return ipaddress.ip_address(text)
    except ValueError:
        pass
    if ":" in text:
        raise BlockedURL("blocked: malformed IPv6 address")
    parts = text.rstrip(".").split(".")
    last = parts[-1].lower()
    numeric = last.isdigit() or (
        last.startswith("0x") and all(c in "0123456789abcdef" for c in last[2:])
    )
    if not numeric or not 1 <= len(parts) <= 4:
        if numeric:  # all-numeric last label but wrong shape, e.g. 1.2.3.4.5
            raise BlockedURL("blocked: malformed numeric host")
        return None
    values: list[int] = []
    for part in parts:
        try:
            if part.lower().startswith("0x"):
                values.append(int(part[2:] or "0", 16))
            elif len(part) > 1 and part.startswith("0"):
                values.append(int(part, 8))
            else:
                values.append(int(part, 10))
        except ValueError as exc:
            raise BlockedURL("blocked: malformed numeric host") from exc
    # inet_aton rules: the last part fills the remaining bytes.
    head, tail = values[:-1], values[-1]
    if any(v > 255 for v in head) or tail >= 256 ** (4 - len(head)):
        raise BlockedURL("blocked: malformed numeric host")
    number = tail
    for i, v in enumerate(head):
        number += v << (8 * (3 - i))
    return ipaddress.IPv4Address(number)


def is_public(ip: IPAddress) -> bool:
    """True only for globally routable unicast addresses."""
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped is not None:
            return is_public(ip.ipv4_mapped)
        if ip in _NAT64:
            return is_public(ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF))
        if ip.sixtofour is not None:
            return is_public(ip.sixtofour)
        if ip.teredo is not None:
            return False
        if ip in _IPV4_COMPAT:  # deprecated IPv4-compatible form, also ::, ::1
            return False
    if any(ip in net for net in _EXTRA_BLOCKED if net.version == ip.version):
        return False
    return bool(ip.is_global)


@dataclass(frozen=True)
class AllowList:
    """Private hosts the operator opted in to: exact host names, IPs and CIDRs."""

    hosts: frozenset[str] = frozenset()
    networks: tuple[IPNetwork, ...] = ()

    @classmethod
    def parse(cls, raw: str | None) -> AllowList:
        hosts: set[str] = set()
        nets: list[IPNetwork] = []
        for item in (raw or "").replace(";", ",").split(","):
            item = item.strip().lower().rstrip(".")
            if not item:
                continue
            try:
                nets.append(ipaddress.ip_network(item, strict=False))
            except ValueError:
                hosts.add(item)
        return cls(frozenset(hosts), tuple(nets))

    def permits_host(self, host: str) -> bool:
        return host in self.hosts

    def permits_ip(self, ip: IPAddress) -> bool:
        return any(ip in n for n in self.networks if n.version == ip.version)


# --- configuration, transport protocol ------------------------------------------------------


@dataclass(frozen=True)
class NetConfig:
    """Fetch limits plus the importer limits that travel with them (see Settings)."""

    timeout: float = 30.0  # total, per request
    connect_timeout: float = CONNECT_TIMEOUT
    max_bytes: int = 5 * 1024 * 1024  # per response, after decompression
    allow: AllowList = field(default_factory=AllowList)
    github_token: str | None = None
    github_max_files: int = 200
    max_rows: int = 2000

    @classmethod
    def from_settings(cls, s: Any) -> NetConfig:
        token = s.github_token.get_secret_value() if s.github_token is not None else None
        return cls(
            timeout=float(s.import_fetch_timeout),
            max_bytes=int(s.import_fetch_max_bytes),
            allow=AllowList.parse(s.import_allow_private_hosts),
            github_token=token or None,
            github_max_files=int(s.import_github_max_files),
            max_rows=int(s.import_max_rows),
        )


@dataclass(frozen=True)
class Request:
    """What a transport must do: connect to one of `ips` (already validated) and send a GET."""

    scheme: str
    host: str  # for the Host header, SNI and certificate verification
    port: int
    ips: tuple[str, ...]
    target: str  # path and query
    headers: Mapping[str, str]
    connect_timeout: float
    deadline: float  # time.monotonic() value after which reads must fail


class RawResponse(Protocol):
    @property
    def status(self) -> int: ...

    @property
    def headers(self) -> Mapping[str, str]: ...  # lower-case names

    def read(self, size: int) -> bytes: ...
    def close(self) -> None: ...


Transport = Callable[[Request], RawResponse]
Resolver = Callable[[str, int], list[str]]


def system_resolver(host: str, port: int) -> list[str]:
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise FetchError(f"Could not resolve host '{host}'") from exc
    return list(dict.fromkeys(str(info[4][0]).split("%")[0] for info in infos))


def _connect(req: Request) -> socket.socket:
    last: Exception | None = None
    for ip in req.ips:
        try:
            return socket.create_connection((ip, req.port), timeout=req.connect_timeout)
        except OSError as exc:
            last = exc
    raise FetchError(f"Could not connect to '{req.host}'") from last


class _PinnedHTTP(http.client.HTTPConnection):
    def __init__(self, req: Request) -> None:
        super().__init__(req.host, req.port, timeout=req.connect_timeout)
        self._req = req

    def connect(self) -> None:
        self.sock = _connect(self._req)


class _PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(self, req: Request) -> None:
        super().__init__(
            req.host, req.port, timeout=req.connect_timeout, context=ssl.create_default_context()
        )
        self._req = req

    def connect(self) -> None:
        sock = _connect(self._req)
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)  # type: ignore[attr-defined]


class _HttpResponse:
    def __init__(
        self, conn: http.client.HTTPConnection, resp: http.client.HTTPResponse, deadline: float
    ):
        self._conn, self._resp, self._deadline = conn, resp, deadline
        self.status = resp.status
        self.headers = {k.lower(): v for k, v in resp.getheaders()}

    def read(self, size: int) -> bytes:
        remaining = self._deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError
        if self._conn.sock is not None:
            self._conn.sock.settimeout(remaining)
        return self._resp.read(size)

    def close(self) -> None:
        self._conn.close()


def http_transport(req: Request) -> RawResponse:
    """The real transport: stdlib http.client over a socket pinned to the validated address."""
    conn: http.client.HTTPConnection = (
        _PinnedHTTPS(req) if req.scheme == "https" else _PinnedHTTP(req)
    )
    try:
        conn.request("GET", req.target, headers=dict(req.headers))
        resp = conn.getresponse()
    except FetchError:
        conn.close()
        raise
    except (OSError, http.client.HTTPException) as exc:  # includes ssl errors and timeouts
        conn.close()
        raise FetchError(f"Request to '{req.host}' failed: {type(exc).__name__}") from exc
    return _HttpResponse(conn, resp, req.deadline)


# --- results and cache ----------------------------------------------------------------------


@dataclass(frozen=True)
class Fetched:
    url: str  # final URL after redirects
    status: int
    headers: Mapping[str, str]
    body: bytes

    @property
    def content_type(self) -> str:
        return self.headers.get("content-type", "").split(";")[0].strip().lower()

    @property
    def charset(self) -> str | None:
        for part in self.headers.get("content-type", "").split(";")[1:]:
            key, _, value = part.partition("=")
            if key.strip().lower() == "charset" and value.strip():
                return value.strip().strip("\"'").lower()
        return None

    def text(self) -> str:
        """Body as text: declared charset if usable, else UTF-8 (BOM tolerated)."""
        for enc in (self.charset, "utf-8-sig"):
            if not enc:
                continue
            try:
                return self.body.decode(enc)
            except (UnicodeDecodeError, LookupError):
                continue
        return self.body.decode("utf-8", errors="replace")


class _Cache:
    """Small TTL cache so preview followed by commit does not fetch twice."""

    def __init__(self, clock: Callable[[], float]) -> None:
        self._clock = clock
        self._items: OrderedDict[tuple[str, ...], tuple[float, Fetched]] = OrderedDict()
        self._bytes = 0
        self._lock = threading.Lock()

    def get(self, key: tuple[str, ...]) -> Fetched | None:
        with self._lock:
            entry = self._items.get(key)
            if entry is None:
                return None
            if self._clock() - entry[0] > CACHE_TTL:
                self._drop(key)
                return None
            return entry[1]

    def put(self, key: tuple[str, ...], value: Fetched) -> None:
        if len(value.body) > CACHE_MAX_BYTES // 4:
            return
        with self._lock:
            if key in self._items:
                self._drop(key)
            self._items[key] = (self._clock(), value)
            self._bytes += len(value.body)
            while len(self._items) > CACHE_MAX_ENTRIES or self._bytes > CACHE_MAX_BYTES:
                self._drop(next(iter(self._items)))

    def _drop(self, key: tuple[str, ...]) -> None:
        _, value = self._items.pop(key)
        self._bytes -= len(value.body)

    def clear(self) -> None:
        with self._lock:
            self._items.clear()
            self._bytes = 0


# --- the fetcher ----------------------------------------------------------------------------


class Fetcher:
    def __init__(
        self,
        config: NetConfig | None = None,
        *,
        resolver: Resolver = system_resolver,
        transport: Transport = http_transport,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.config = config or NetConfig()
        self._resolver = resolver
        self._transport = transport
        self._clock = clock
        self._cache = _Cache(clock)

    def clear_cache(self) -> None:
        self._cache.clear()

    # -- policy

    def check_url(self, url: str) -> tuple[str, str, int, tuple[str, ...], str]:
        """Validate `url` and resolve it. Returns (scheme, host, port, addresses, target)."""
        try:
            parts = urlsplit(url.strip())
            port = parts.port
        except ValueError as exc:
            raise BlockedURL("blocked: not a valid URL") from exc
        scheme = parts.scheme.lower()
        if scheme not in ("http", "https"):
            raise BlockedURL("blocked: only http and https URLs are allowed")
        if parts.username is not None or parts.password is not None or "@" in parts.netloc:
            raise BlockedURL("blocked: URLs with credentials are not allowed")
        host = (parts.hostname or "").lower().rstrip(".")
        if not host:
            raise BlockedURL("blocked: URL has no host")
        if any(c.isspace() or ord(c) < 32 for c in url):
            raise BlockedURL("blocked: not a valid URL")
        allow = self.config.allow
        port = port or (443 if scheme == "https" else 80)
        host_allowed = allow.permits_host(host)
        if port not in ALLOWED_PORTS and not host_allowed:
            raise BlockedURL(f"blocked: port {port} is not allowed (only 80 and 443)")

        literal = parse_ip_literal(host)
        if literal is not None:
            addresses = [str(literal)]
        elif host == "localhost" or host.endswith(".localhost"):
            if not host_allowed:
                raise BlockedURL("blocked: host resolves to a non-public address")
            addresses = self._resolver(host, port)
        else:
            addresses = self._resolver(host, port)
        if not addresses:
            raise FetchError(f"Could not resolve host '{host}'")
        for text in addresses:
            ip = ipaddress.ip_address(text)
            if not (is_public(ip) or host_allowed or allow.permits_ip(ip)):
                raise BlockedURL(
                    "blocked: host resolves to a non-public address "
                    "(see PV_IMPORT_ALLOW_PRIVATE_HOSTS to allow an intranet host)"
                )
        target = parts.path or "/"
        if parts.query:
            target += "?" + parts.query
        return scheme, host, port, tuple(addresses), target

    # -- fetching

    def get(
        self,
        url: str,
        *,
        accept: str = "*/*",
        allowed_types: tuple[str, ...] | None = None,
        bearer: str | None = None,
        max_bytes: int | None = None,
        use_cache: bool = True,
        raise_for_status: bool = True,
    ) -> Fetched:
        """GET `url` under the policy above. `allowed_types` entries are exact media types or
        prefixes ending in `/` (for example `text/`). `bearer` is only sent to the GitHub hosts."""
        cap = max_bytes or self.config.max_bytes
        key = (url, accept, str(cap))
        if use_cache:
            hit = self._cache.get(key)
            if hit is not None:
                return hit
        deadline = self._clock() + self.config.timeout
        current = url
        first_scheme = urlsplit(url.strip()).scheme.lower()
        for hop in range(MAX_REDIRECTS + 1):
            scheme, host, port, addresses, target = self.check_url(current)
            if first_scheme == "https" and scheme != "https":
                raise BlockedURL("blocked: redirect from https to http")
            headers = {
                "User-Agent": USER_AGENT,
                "Accept": accept,
                "Accept-Encoding": "gzip",
                "Connection": "close",
            }
            if bearer and host in BEARER_HOSTS and scheme == "https":
                headers["Authorization"] = f"Bearer {bearer}"
            request = Request(
                scheme,
                host,
                port,
                addresses,
                target,
                headers,
                min(self.config.connect_timeout, self.config.timeout),
                deadline,
            )
            raw = self._open(request)
            try:
                if raw.status in REDIRECT_STATUSES and raw.headers.get("location"):
                    if hop == MAX_REDIRECTS:
                        raise FetchError(f"Too many redirects (limit {MAX_REDIRECTS})")
                    current = urljoin(current, raw.headers["location"])
                    first_scheme = scheme
                    continue
                body = self._read_body(raw, cap, allowed_types, deadline, ok=raw.status < 400)
                result = Fetched(current, raw.status, dict(raw.headers), body)
            finally:
                raw.close()
            if raise_for_status and result.status >= 400:
                raise FetchError(f"The server answered {result.status} for {_shown(current)}")
            if use_cache and result.status == 200:
                self._cache.put(key, result)
            return result
        raise FetchError(f"Too many redirects (limit {MAX_REDIRECTS})")  # pragma: no cover

    def _open(self, request: Request) -> RawResponse:
        try:
            return self._transport(request)
        except (DomainError, ValueError):
            raise
        except TimeoutError as exc:
            raise FetchError("The request timed out") from exc
        except OSError as exc:
            raise FetchError(f"Request to '{request.host}' failed: {type(exc).__name__}") from exc

    def _read_body(
        self,
        raw: RawResponse,
        cap: int,
        allowed_types: tuple[str, ...] | None,
        deadline: float,
        *,
        ok: bool,
    ) -> bytes:
        headers = raw.headers
        if ok and allowed_types is not None:
            ctype = (
                headers.get("content-type", "").split(";")[0].strip().lower()
                or "application/octet-stream"
            )
            if not any(
                ctype == t or (t.endswith("/") and ctype.startswith(t)) for t in allowed_types
            ):
                raise FetchError(f"Unsupported content type '{ctype}'")
        declared = headers.get("content-length", "")
        if declared.isdigit() and int(declared) > cap and not headers.get("content-encoding"):
            raise FetchError(f"Response is larger than {cap} bytes")
        encoding = headers.get("content-encoding", "").strip().lower()
        if encoding not in ("", "identity", "gzip", "x-gzip"):
            raise FetchError(f"Unsupported content encoding '{encoding}'")
        inflater = zlib.decompressobj(16 + zlib.MAX_WBITS) if encoding.endswith("gzip") else None
        out = bytearray()
        try:
            while True:
                if self._clock() > deadline:
                    raise TimeoutError
                chunk = raw.read(_CHUNK)
                if not chunk:
                    break
                if inflater is None:
                    out += chunk
                    if len(out) > cap:
                        raise FetchError(f"Response is larger than {cap} bytes")
                    continue
                pending = chunk
                while pending:  # bounded output per step: a gzip bomb cannot expand at once
                    out += inflater.decompress(pending, cap + 1 - len(out))
                    if len(out) > cap:
                        raise FetchError(f"Response is larger than {cap} bytes (decompressed)")
                    pending = inflater.unconsumed_tail
            if inflater is not None:
                out += inflater.flush(cap + 1 - len(out))
                if len(out) > cap:
                    raise FetchError(f"Response is larger than {cap} bytes (decompressed)")
        except TimeoutError as exc:
            raise FetchError("The request timed out") from exc
        except zlib.error as exc:
            raise FetchError("The response could not be decompressed") from exc
        except (OSError, http.client.HTTPException) as exc:
            raise FetchError(f"Reading the response failed: {type(exc).__name__}") from exc
        return bytes(out)


def _shown(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.hostname}{parts.path}"


# --- process-wide fetcher ---------------------------------------------------------------------

_fetcher: Fetcher | None = None
_override: Fetcher | None = None
_lock = threading.Lock()


def configure(settings: Any) -> None:
    """Build the process-wide fetcher from Settings (called when the app or CLI starts)."""
    global _fetcher
    with _lock:
        _fetcher = Fetcher(NetConfig.from_settings(settings))


def set_fetcher(fetcher: Fetcher | None) -> None:
    """Install a fetcher that wins over the configured one (tests); None removes it."""
    global _override
    with _lock:
        _override = fetcher


def get_fetcher() -> Fetcher:
    global _fetcher
    with _lock:
        if _override is not None:
            return _override
        if _fetcher is None:
            from promptvault.config import get_settings

            _fetcher = Fetcher(NetConfig.from_settings(get_settings()))
        return _fetcher
