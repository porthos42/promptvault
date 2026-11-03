"""SSRF guard and fetch limits of importers/net.py. Resolver, transport and clock are fakes."""

from __future__ import annotations

import gzip
import http.server
import threading
from collections.abc import Iterator

import pytest
from tests.net_helpers import (
    LOOPBACK,
    METADATA,
    PRIVATE_10,
    PUBLIC,
    PUBLIC_B,
    Net,
    Reply,
    ip4,
    make_net,
)

from promptvault.importers import net
from promptvault.services.errors import ValidationFailed

AT = chr(64)

# (label, host as it appears in a URL)
BLOCKED_HOSTS = [
    ("loopback", ip4(127, 0, 0, 1)),
    ("loopback range", ip4(127, 8, 8, 8)),
    ("this network", ip4(0, 0, 0, 0)),
    ("private 10/8", ip4(10, 0, 0, 5)),
    ("private 172.16/12 low", ip4(172, 16, 0, 1)),
    ("private 172.16/12 high", ip4(172, 31, 255, 254)),
    ("private 192.168/16", ip4(192, 168, 1, 1)),
    ("cloud metadata", METADATA),
    ("link-local", ip4(169, 254, 0, 10)),
    ("CGNAT low", ip4(100, 64, 0, 1)),
    ("CGNAT high", ip4(100, 127, 255, 254)),
    ("multicast", ip4(224, 0, 0, 1)),
    ("reserved", ip4(240, 0, 0, 1)),
    ("broadcast", ip4(255, 255, 255, 255)),
    ("IETF assignments", ip4(192, 0, 0, 8)),
    ("IPv6 loopback", "[::1]"),
    ("IPv6 unspecified", "[::]"),
    ("IPv6 unique local", "[fc00::1]"),
    ("IPv6 unique local fd", "[fd12:3456::1]"),
    ("IPv6 link-local", "[fe80::1]"),
    ("IPv6 multicast", "[ff02::1]"),
    ("IPv4-mapped loopback", "[::ffff:7f00:1]"),
    ("IPv4-mapped metadata", "[::ffff:a9fe:a9fe]"),
    ("IPv4-compatible loopback", "[::7f00:1]"),
    ("NAT64 of loopback", "[64:ff9b::7f00:1]"),
    ("6to4 of loopback", "[2002:7f00:1::1]"),
    ("teredo", "[2001:0:4136:e378:8000:63bf:3fff:fdd2]"),
    ("hex IPv4", "0x7f.1"),
    ("hex IPv4 single number", "0x7f000001"),
    ("decimal IPv4", "2130706433"),
    ("octal IPv4 single number", "017700000001"),
    ("octal dotted", "0177.0.0.1"),
    ("short form", "127.1"),
    ("short form 3 parts", "10.1.1"),
    ("localhost", "localhost"),
    ("localhost trailing dot", "localhost."),
    ("subdomain of localhost", "app.localhost"),
]


def check(n: Net, url: str) -> None:
    n.fetcher.check_url(url)


@pytest.mark.parametrize(("label", "host"), BLOCKED_HOSTS, ids=[b[0] for b in BLOCKED_HOSTS])
@pytest.mark.parametrize("scheme", ["http", "https"])
def test_non_public_literals_and_names_are_blocked(label: str, host: str, scheme: str) -> None:
    n = make_net(table={"localhost": [LOOPBACK], "app.localhost": [LOOPBACK]})
    with pytest.raises(net.BlockedURL):
        check(n, f"{scheme}://{host}/x")


@pytest.mark.parametrize(
    "host",
    [
        ip4(93, 184, 216, 34),
        "example.com",
        "[2606:4700::1111]",
        "[::ffff:5db8:d822]",
        "[64:ff9b::808:808]",
    ],
)
def test_public_hosts_pass(host: str) -> None:
    n = make_net()
    scheme, h, port, addresses, target = n.fetcher.check_url(f"https://{host}/a/b?q=1")
    assert (scheme, port, target) == ("https", 443, "/a/b?q=1")
    assert addresses


def test_name_resolving_to_private_is_blocked_and_message_does_not_leak() -> None:
    n = make_net(table={"evil.example": [PRIVATE_10]})
    with pytest.raises(net.BlockedURL) as exc:
        check(n, "https://evil.example/")
    assert "non-public" in exc.value.detail and PRIVATE_10 not in exc.value.detail


def test_any_private_address_among_several_blocks() -> None:
    n = make_net(table={"mixed.example": [PUBLIC, LOOPBACK]})
    with pytest.raises(net.BlockedURL):
        check(n, "https://mixed.example/")
    n = make_net(table={"v6.example": [PUBLIC, "fe80::1"]})
    with pytest.raises(net.BlockedURL):
        check(n, "https://v6.example/")


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "gopher://example.com/",
        "ftp://example.com/x",
        "javascript:alert(1)",
        "data:text/plain,hi",
        "example.com/path",
        "//example.com/path",
        "",
        "http://",
        "http:///path",
        "http://[::1/",
        "http://example.com:99999/",
        "http://user@example.com/",
        "http://user:pw@example.com/",
        "http://example.com@evil.example/",
        "https://example.com/a b",
        "http://" + ip4(1, 2, 3, 4) + ".5/",
    ],
)
def test_bad_urls_are_blocked(url: str) -> None:
    with pytest.raises(ValidationFailed):
        check(make_net(), url)


@pytest.mark.parametrize("port", [8080, 22, 6379, 8443, 81])
def test_only_ports_80_and_443(port: int) -> None:
    with pytest.raises(net.BlockedURL) as exc:
        check(make_net(), f"http://example.com:{port}/")
    assert "port" in exc.value.detail


def test_explicit_default_ports_pass() -> None:
    check(make_net(), "http://example.com:80/")
    check(make_net(), "https://example.com:443/")


# --- allow-list (the escape hatch) -----------------------------------------------------------


def allow(raw: str, table: dict[str, list[str]] | None = None) -> Net:
    return make_net(net.NetConfig(allow=net.AllowList.parse(raw)), table)


def test_allow_list_is_empty_by_default() -> None:
    assert net.NetConfig().allow == net.AllowList()
    assert net.AllowList.parse(None) == net.AllowList()
    assert net.AllowList.parse(" , ;") == net.AllowList()


def test_allow_list_host_is_exact_and_lifts_the_port_rule() -> None:
    n = allow(
        "wiki.corp",
        {
            "wiki.corp": [PRIVATE_10],
            "other.corp": [PRIVATE_10],
            "sub.wiki.corp": [PRIVATE_10],
            "wiki.corp.evil.example": [PRIVATE_10],
        },
    )
    n.fetcher.check_url("http://wiki.corp:8080/page")
    with pytest.raises(net.BlockedURL):
        check(n, "http://other.corp/")
    with pytest.raises(net.BlockedURL):
        check(n, "http://sub.wiki.corp/")  # no subdomain wildcard
    with pytest.raises(net.BlockedURL):
        check(n, "http://wiki.corp.evil.example/")  # resolves private, not the allowed name


def test_allow_list_cidr_and_ip() -> None:
    n = allow(
        f"{ip4(10, 1, 0, 0)}/16, {ip4(192, 168, 7, 7)}",
        {"nas.lan": [ip4(10, 1, 9, 9)], "bad.lan": [ip4(10, 2, 0, 1)]},
    )
    n.fetcher.check_url("http://nas.lan/x")
    n.fetcher.check_url(f"http://{ip4(10, 1, 200, 1)}/x")
    n.fetcher.check_url(f"http://{ip4(192, 168, 7, 7)}/x")
    with pytest.raises(net.BlockedURL):
        check(n, "http://bad.lan/")
    with pytest.raises(net.BlockedURL):
        check(n, f"http://{ip4(192, 168, 7, 8)}/x")
    with pytest.raises(net.BlockedURL):  # metadata stays blocked
        check(n, f"http://{METADATA}/latest")


def test_allow_list_does_not_make_other_checks_weaker() -> None:
    n = allow("wiki.corp", {"wiki.corp": [PRIVATE_10]})
    with pytest.raises(net.BlockedURL):
        check(n, "file://wiki.corp/x")
    with pytest.raises(net.BlockedURL):
        check(n, "http://u@wiki.corp/")


# --- redirects, pinning ----------------------------------------------------------------------


def test_connection_is_pinned_to_the_validated_address() -> None:
    n = make_net(table={"rebind.example": [[PUBLIC], [LOOPBACK]]})
    n.transport.add("https://rebind.example/doc", "hello")
    assert n.fetcher.get("https://rebind.example/doc").body == b"hello"
    assert n.transport.requests[0].ips == (PUBLIC,)
    assert n.transport.requests[0].host == "rebind.example"  # Host header / SNI keep the name
    assert n.resolver.calls == ["rebind.example"]  # resolved once per hop, never again


def test_redirects_are_followed_and_revalidated() -> None:
    n = make_net(table={"b.example": [PUBLIC_B]})
    n.transport.redirect("https://a.example/start", "https://b.example/mid")
    n.transport.redirect("https://b.example/mid", "/end")  # relative
    n.transport.add("https://b.example/end", "done")
    got = n.fetcher.get("https://a.example/start")
    assert got.body == b"done" and got.url == "https://b.example/end"
    assert n.transport.requests[1].ips == (PUBLIC_B,)


@pytest.mark.parametrize(
    "target",
    [f"http://{LOOPBACK}/admin", f"https://{METADATA}/latest", "https://intranet.example/"],
)
def test_redirect_to_private_address_is_blocked(target: str) -> None:
    n = make_net(table={"intranet.example": [PRIVATE_10]})
    n.transport.redirect("https://a.example/start", target)
    n.transport.add(target, "secret")
    with pytest.raises(net.BlockedURL):
        n.fetcher.get("https://a.example/start")
    assert len(n.transport.requests) == 1  # the private hop was never requested


def test_redirect_to_bad_scheme_is_blocked() -> None:
    n = make_net()
    n.transport.redirect("https://a.example/start", "file:///etc/passwd")
    with pytest.raises(net.BlockedURL):
        n.fetcher.get("https://a.example/start")


def test_three_redirects_are_fine_a_fourth_is_not() -> None:
    n = make_net()
    for i in range(4):
        n.transport.redirect(f"https://a.example/{i}", f"https://a.example/{i + 1}")
    n.transport.add("https://a.example/3", "ok")
    assert n.fetcher.get("https://a.example/0").body == b"ok"
    n.transport.redirect("https://a.example/3", "https://a.example/4")
    n.transport.add("https://a.example/4", "too far")
    with pytest.raises(net.FetchError, match="redirects"):
        n.fetcher.get("https://a.example/0", use_cache=False)


def test_redirect_loop_stops() -> None:
    n = make_net()
    n.transport.redirect("https://a.example/x", "https://a.example/y")
    n.transport.redirect("https://a.example/y", "https://a.example/x")
    with pytest.raises(net.FetchError, match="redirects"):
        n.fetcher.get("https://a.example/x")
    assert len(n.transport.requests) == 4


def test_https_to_http_downgrade_is_blocked() -> None:
    n = make_net()
    n.transport.redirect("https://a.example/x", "http://a.example/y")
    n.transport.add("http://a.example/y", "plain")
    with pytest.raises(net.BlockedURL, match="https to http"):
        n.fetcher.get("https://a.example/x")
    n2 = make_net()  # http -> https upgrade and http -> http are fine
    n2.transport.redirect("http://a.example/x", "https://a.example/y")
    n2.transport.add("https://a.example/y", "secure")
    assert n2.fetcher.get("http://a.example/x").body == b"secure"


# --- headers: user agent, no cookies, bearer token --------------------------------------------


def test_fixed_user_agent_and_no_cookies() -> None:
    n = make_net()
    n.transport.add("https://a.example/x", "hi", headers={"set-cookie": "sid=1"})
    n.fetcher.get("https://a.example/x", use_cache=False)
    n.fetcher.get("https://a.example/x", use_cache=False)
    for req in n.transport.requests:
        assert req.headers["User-Agent"] == net.USER_AGENT
        assert not any(k.lower() in ("cookie", "authorization") for k in req.headers)


def test_bearer_token_goes_only_to_github_hosts() -> None:
    n = make_net(table={"api.github.com": [PUBLIC], "raw.githubusercontent.com": [PUBLIC]})
    n.transport.add("https://api.github.com/repos/o/r", "{}")
    n.transport.add("https://raw.githubusercontent.com/o/r/main/a.md", "x")
    n.transport.add("https://example.com/x", "x")
    n.transport.redirect("https://api.github.com/loop", "https://example.com/x")
    for url in (
        "https://api.github.com/repos/o/r",
        "https://raw.githubusercontent.com/o/r/main/a.md",
        "https://example.com/x",
        "https://api.github.com/loop",
    ):
        n.fetcher.get(url, bearer="SECRET", use_cache=False)
    sent = [(r.host, r.headers.get("Authorization")) for r in n.transport.requests]
    assert sent == [
        ("api.github.com", "Bearer SECRET"),
        ("raw.githubusercontent.com", "Bearer SECRET"),
        ("example.com", None),
        ("api.github.com", "Bearer SECRET"),
        ("example.com", None),  # dropped after the redirect to another host
    ]


def test_token_is_never_sent_over_plain_http() -> None:
    n = make_net()
    n.transport.add("http://api.github.com/x", "x")
    n.fetcher.get("http://api.github.com/x", bearer="SECRET")
    assert "Authorization" not in n.transport.requests[0].headers


# --- limits ----------------------------------------------------------------------------------


def limited(**kw: float | int) -> Net:
    return make_net(net.NetConfig(**kw))  # type: ignore[arg-type]


def test_oversize_declared_length_is_refused_before_reading() -> None:
    n = limited(max_bytes=1000)
    n.transport.add("https://a.example/x", b"x" * 10, headers={"content-length": "5000"})
    with pytest.raises(net.FetchError, match="larger than 1000"):
        n.fetcher.get("https://a.example/x")


def test_oversize_streamed_body_is_cut_off() -> None:
    n = limited(max_bytes=1000)
    n.transport.add("https://a.example/x", b"x" * 5000, chunk=100)
    with pytest.raises(net.FetchError, match="larger than 1000"):
        n.fetcher.get("https://a.example/x")


def test_body_at_the_cap_is_fine() -> None:
    n = limited(max_bytes=1000)
    n.transport.add("https://a.example/x", b"x" * 1000)
    assert len(n.fetcher.get("https://a.example/x").body) == 1000


def test_gzip_bomb_is_stopped_by_the_decompressed_cap() -> None:
    n = limited(max_bytes=100_000)
    bomb = gzip.compress(b"\0" * 50_000_000)
    assert len(bomb) < 100_000  # small on the wire, huge when inflated
    n.transport.add("https://a.example/x", bomb, headers={"content-encoding": "gzip"})
    with pytest.raises(net.FetchError, match="decompressed"):
        n.fetcher.get("https://a.example/x")


def test_gzip_body_is_decoded() -> None:
    n = limited()
    n.transport.add(
        "https://a.example/x",
        gzip.compress(b"hello gzip"),
        headers={"content-encoding": "gzip"},
        chunk=7,
    )
    assert n.fetcher.get("https://a.example/x").body == b"hello gzip"


def test_corrupt_gzip_and_unknown_encoding() -> None:
    n = limited()
    n.transport.add("https://a.example/x", b"not gzip", headers={"content-encoding": "gzip"})
    with pytest.raises(net.FetchError, match="decompressed"):
        n.fetcher.get("https://a.example/x")
    n.transport.add("https://a.example/y", b"x", headers={"content-encoding": "br"})
    with pytest.raises(net.FetchError, match="encoding"):
        n.fetcher.get("https://a.example/y")


def test_slow_response_times_out() -> None:
    n = limited(timeout=10.0)
    n.transport.add("https://a.example/x", b"x" * 500, chunk=10, cost=1.0)  # 50 reads of 1 s
    with pytest.raises(net.FetchError, match="timed out"):
        n.fetcher.get("https://a.example/x")


def test_transport_timeouts_become_fetch_errors() -> None:
    n = limited()

    def boom(req: net.Request) -> Reply:
        raise TimeoutError

    n.transport.routes["https://a.example/x"] = boom  # type: ignore[assignment]
    # the callable route raises inside __call__, which is what a real transport does
    with pytest.raises(net.FetchError, match="timed out"):
        n.fetcher.get("https://a.example/x")


def test_content_type_allowlist() -> None:
    n = make_net()
    n.transport.add("https://a.example/x", b"\x00\x01", headers={"content-type": "application/pdf"})
    with pytest.raises(net.FetchError, match="content type 'application/pdf'"):
        n.fetcher.get("https://a.example/x", allowed_types=("text/", "application/json"))
    assert n.fetcher.get("https://a.example/x", allowed_types=("application/pdf",)).body
    n.transport.add(
        "https://a.example/j", "{}", headers={"content-type": "Application/JSON; charset=utf-8"}
    )
    assert (
        n.fetcher.get("https://a.example/j", allowed_types=("application/json",)).content_type
        == "application/json"
    )
    n.transport.add("https://a.example/none", b"abc")  # no content-type at all
    n.transport.routes["https://a.example/none"].headers.clear()  # type: ignore[union-attr]
    with pytest.raises(net.FetchError, match="octet-stream"):
        n.fetcher.get("https://a.example/none", allowed_types=("text/",))


def test_error_statuses() -> None:
    n = make_net()
    n.transport.add("https://a.example/gone", "no", status=404)
    with pytest.raises(net.FetchError, match="404"):
        n.fetcher.get("https://a.example/gone")
    got = n.fetcher.get("https://a.example/gone", raise_for_status=False)
    assert got.status == 404 and got.body == b"no"


def test_error_message_does_not_include_query_string() -> None:
    n = make_net()
    n.transport.add("https://a.example/p?token=hunter2", "no", status=500)
    with pytest.raises(net.FetchError) as exc:
        n.fetcher.get("https://a.example/p?token=hunter2")
    assert "hunter2" not in exc.value.detail


def test_cache_serves_preview_then_commit_with_one_fetch() -> None:
    n = make_net()
    n.transport.add("https://a.example/x", "v1")
    assert n.fetcher.get("https://a.example/x").body == b"v1"
    n.transport.add("https://a.example/x", "v2")
    assert n.fetcher.get("https://a.example/x").body == b"v1"  # cached
    assert len(n.transport.requests) == 1
    n.clock.advance(net.CACHE_TTL + 1)
    assert n.fetcher.get("https://a.example/x").body == b"v2"  # expired
    n.fetcher.clear_cache()
    n.fetcher.get("https://a.example/x")
    assert len(n.transport.requests) == 3


def test_cache_is_bounded_and_skips_errors() -> None:
    n = make_net()
    for i in range(net.CACHE_MAX_ENTRIES + 10):
        n.transport.add(f"https://a.example/{i}", "x")
        n.fetcher.get(f"https://a.example/{i}")
    assert len(n.fetcher._cache._items) <= net.CACHE_MAX_ENTRIES
    n.transport.add("https://a.example/bad", "x", status=500)
    n.fetcher.get("https://a.example/bad", raise_for_status=False)
    n.fetcher.get("https://a.example/bad", raise_for_status=False)
    assert n.transport.urls().count("https://a.example/bad") == 2


def test_fetched_text_decoding() -> None:
    f = net.Fetched(
        "u", 200, {"content-type": "text/html; charset=iso-8859-1"}, "caf\u00e9".encode("latin-1")
    )
    assert f.text() == "caf\u00e9" and f.charset == "iso-8859-1"
    g = net.Fetched("u", 200, {"content-type": "text/plain; charset=bogus"}, b"\xef\xbb\xbfhi")
    assert g.text() == "hi"
    h = net.Fetched("u", 200, {}, b"bad \xff byte")
    assert "bad" in h.text()


def test_settings_build_the_config() -> None:
    from promptvault.config import Settings

    s = Settings(
        _env_file=None,
        github_token="s3cr3t-value",
        import_allow_private_hosts="a.corp",
        import_fetch_timeout=5,
        import_fetch_max_bytes=99,
        import_github_max_files=7,
    )  # type: ignore[arg-type,call-arg]
    cfg = net.NetConfig.from_settings(s)
    assert (cfg.github_token, cfg.timeout, cfg.max_bytes, cfg.github_max_files) == (
        "s3cr3t-value",
        5.0,
        99,
        7,
    )
    assert cfg.allow.hosts == frozenset({"a.corp"})
    assert "s3cr3t" not in repr(s)  # SecretStr keeps the token out of logs
    assert net.NetConfig.from_settings(Settings(_env_file=None)).github_token is None  # type: ignore[call-arg]


# --- the real transport, against a loopback server (no outside network) ------------------------


class _Handler(http.server.BaseHTTPRequestHandler):
    seen: list[str] = []

    def do_GET(self) -> None:
        _Handler.seen.append(self.headers.get("Host", ""))
        body = b"pinned ok"
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: object) -> None:  # silence
        pass


@pytest.fixture
def loopback_server() -> Iterator[int]:
    server = http.server.ThreadingHTTPServer((LOOPBACK, 0), _Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield int(server.server_address[1])
    finally:
        server.shutdown()
        server.server_close()


def test_real_transport_connects_to_the_pinned_ip_and_sends_the_host_name(
    loopback_server: int,
) -> None:
    import time

    _Handler.seen.clear()
    req = net.Request(
        "http",
        "files.example",  # not resolvable: only the pinned address can make this work
        loopback_server,
        (LOOPBACK,),
        "/doc",
        {"User-Agent": net.USER_AGENT},
        2.0,
        time.monotonic() + 5,
    )
    resp = net.http_transport(req)
    try:
        assert resp.status == 200 and resp.read(100) == b"pinned ok"
    finally:
        resp.close()
    assert _Handler.seen == [f"files.example:{loopback_server}"]


def test_real_transport_connection_failure_is_a_fetch_error() -> None:
    import time

    req = net.Request("http", "x.example", 9, (LOOPBACK,), "/", {}, 1.0, time.monotonic() + 2)
    with pytest.raises(net.FetchError):
        net.http_transport(req)
