"""Test doubles for the URL importers: a fake resolver, a fake transport and a fake clock.

Nothing here (or in any test using it) opens a socket to the outside world. IP addresses are
built from numbers (`ip4`) rather than typed as literals.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from typing import Any

from promptvault.importers import net


def ip4(a: int, b: int, c: int, d: int) -> str:
    return f"{a}.{b}.{c}.{d}"


PUBLIC = ip4(93, 184, 216, 34)
PUBLIC_B = ip4(8, 8, 4, 4)
LOOPBACK = ip4(127, 0, 0, 1)
METADATA = ip4(169, 254, 169, 254)
PRIVATE_10 = ip4(10, 1, 2, 3)


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class FakeResolver:
    """host -> addresses. A list of lists answers successive lookups differently (rebinding)."""

    def __init__(self, table: dict[str, list[str] | list[list[str]]] | None = None) -> None:
        self.table = table or {}
        self.calls: list[str] = []

    def __call__(self, host: str, port: int) -> list[str]:
        self.calls.append(host)
        answer = self.table.get(host)
        if answer is None:
            return [PUBLIC]  # unknown public-looking names resolve to a public address
        if answer and isinstance(answer[0], list):
            seen = self.calls.count(host)
            return list(answer[min(seen, len(answer)) - 1])  # type: ignore[arg-type]
        return list(answer)  # type: ignore[arg-type]


@dataclass
class Reply:
    status: int = 200
    body: bytes | str | dict[str, Any] | list[Any] = b""
    headers: dict[str, str] = field(default_factory=dict)
    chunk: int = 64 * 1024
    cost: float = 0.0  # fake seconds consumed by each read


class FakeResponse:
    def __init__(self, reply: Reply, clock: FakeClock) -> None:
        body = reply.body
        if isinstance(body, dict | list):
            body = json.dumps(body)
            reply.headers.setdefault("content-type", "application/json")
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.status = reply.status
        self.headers = {k.lower(): v for k, v in reply.headers.items()}
        self._chunks: Iterator[bytes] = iter(
            data[i : i + reply.chunk] for i in range(0, len(data), reply.chunk)
        )
        self._cost, self._clock = reply.cost, clock
        self.closed = False

    def read(self, size: int) -> bytes:
        self._clock.advance(self._cost)
        return next(self._chunks, b"")

    def close(self) -> None:
        self.closed = True


class FakeTransport:
    """url (scheme://host[:port]/path?query) or callable -> Reply. Records every request."""

    def __init__(self, clock: FakeClock) -> None:
        self.routes: dict[str, Reply | Callable[[net.Request], Reply]] = {}
        self.requests: list[net.Request] = []
        self.clock = clock

    def add(self, url: str, body: Any = b"", status: int = 200, **kwargs: Any) -> None:
        headers = dict(kwargs.pop("headers", {}))
        if isinstance(body, str) and "content-type" not in {k.lower() for k in headers}:
            headers["content-type"] = "text/plain; charset=utf-8"
        self.routes[url] = Reply(status=status, body=body, headers=headers, **kwargs)

    def redirect(self, url: str, to: str, status: int = 302) -> None:
        self.routes[url] = Reply(status=status, headers={"location": to})

    def __call__(self, req: net.Request) -> FakeResponse:
        self.requests.append(req)
        default_port = 443 if req.scheme == "https" else 80
        netloc = req.host if req.port == default_port else f"{req.host}:{req.port}"
        url = f"{req.scheme}://{netloc}{req.target}"
        route = self.routes.get(url)
        if route is None:
            return FakeResponse(Reply(status=404, body=b"not found"), self.clock)
        reply = route(req) if callable(route) else route
        return FakeResponse(reply, self.clock)

    def urls(self) -> list[str]:
        return [f"{r.scheme}://{r.host}{r.target}" for r in self.requests]


@dataclass
class Net:
    fetcher: net.Fetcher
    resolver: FakeResolver
    transport: FakeTransport
    clock: FakeClock


def make_net(config: net.NetConfig | None = None, table: dict[str, Any] | None = None) -> Net:
    clock = FakeClock()
    resolver = FakeResolver(table)
    transport = FakeTransport(clock)
    fetcher = net.Fetcher(config, resolver=resolver, transport=transport, clock=clock)
    return Net(fetcher, resolver, transport, clock)


def chunks(data: Iterable[bytes]) -> bytes:
    return b"".join(data)
