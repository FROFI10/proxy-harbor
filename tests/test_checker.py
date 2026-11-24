import asyncio
import contextlib
import gzip
import ipaddress
import json
import ssl
import time
import zlib
from contextlib import asynccontextmanager
from urllib.parse import urlsplit

import pytest
from aiohttp import web

# Public, test-only self-signed certificate/key; never used in production.
TEST_CERT = "-----BEGIN CERTIFICATE-----\nMIIDOzCCAiOgAwIBAgIULBgytTDiOSt+A819SFaJ/tNxbecwDQYJKoZIhvcNAQEL\nBQAwFTETMBEGA1UEAwwKcHJvYmUudGVzdDAgFw0yNjExMjQxNzIwMDRaGA8yMTI2\nMTAzMTE3MjAwNFowFTETMBEGA1UEAwwKcHJvYmUudGVzdDCCASIwDQYJKoZIhvcN\nAQEBBQADggEPADCCAQoCggEBALCjFp1MWUdEZPeYveIj1I1kPd3A8EOvu2TXr6Ui\ny6gGF/TvEjhsubnfM1N1BgnIM89J1Wlhy/cpg+SEVChDNu+n/EHc4lSCSRQ4x3sM\n0ZATWqvLYiCOtQy5ltvNvs8V0kWdtAUmjgtlRr1rmiLMF/UAwfRL/aQg/hnHQOns\nk53FUX6JPx/XT7UkvyGBBts9nFfeym3+b9oXvTq22a5/RQfvWHPUOUDooSZ9s2Lg\n0/LWOgL5u2nxiFOW4nFA1u53ID/HRcJAfjwDbFck0u+TVloSaXVYzHvUmOKgPFMP\nd3DTYz8a5lCPaeDan//Bknes63MKAPy/8eWS55E40AEN3m8CAwEAAaOBgDB+MB0G\nA1UdDgQWBBQrQCy9d3+4zInGXL0s+XphDU6WnTAfBgNVHSMEGDAWgBQrQCy9d3+4\nzInGXL0s+XphDU6WnTAPBgNVHRMBAf8EBTADAQH/MCsGA1UdEQQkMCKCCnByb2Jl\nLnRlc3SCDmNoYWxsZW5nZS50ZXN0hwR/AAABMA0GCSqGSIb3DQEBCwUAA4IBAQAQ\nwWUM9XEl7BGrVMTK+i6zuMDUnvwkL2bWiYDqKG0q90e0sNHquyvpR2jleewqSn2x\ngiIqQw458vpS56lI4fZrnSxC6bgEB6+pUs5R6ey6BjHXOLbnoQcu872skpX+kBIz\n/pONg1vvX5bEsioDA6qAC+86I9FDRdLQsE30Og6tmAY1bJiZnLRWHzJEUxqzobrQ\nuDZi53hhVsj+E1Dl3kAQtvZRzx4ljOT1ag4EaNC9rXFMp3QVJGDBKrQQXkFyxPBf\nNDMVWKBXq1K2aHMamDf9hOb3gahFAycstZzIUg4+lspAIT/PVc3UCyxtV1hVn/sj\nBxeqwq9sWdyOunMA+psq\n-----END CERTIFICATE-----\n"
TEST_KEY = "-----BEGIN PRIVATE KEY-----\nMIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQCwoxadTFlHRGT3\nmL3iI9SNZD3dwPBDr7tk16+lIsuoBhf07xI4bLm53zNTdQYJyDPPSdVpYcv3KYPk\nhFQoQzbvp/xB3OJUgkkUOMd7DNGQE1qry2IgjrUMuZbbzb7PFdJFnbQFJo4LZUa9\na5oizBf1AMH0S/2kIP4Zx0Dp7JOdxVF+iT8f10+1JL8hgQbbPZxX3spt/m/aF706\nttmuf0UH71hz1DlA6KEmfbNi4NPy1joC+btp8YhTluJxQNbudyA/x0XCQH48A2xX\nJNLvk1ZaEml1WMx71JjioDxTD3dw02M/GuZQj2ng2p//wZJ3rOtzCgD8v/HlkueR\nONABDd5vAgMBAAECggEAEew9HLEvs+axigVXwGJGAczEkZjZ/ZGPZarppHYUjRQv\n38dW+skJdV3mTYG9HvFPVH6s5rhTeQefiD3nHii9InHR9kriij79Xvholp3qhlXN\nvaBxm1UaSNQXWxk+0wYR+RoIjKc+AtOqwF3yh1+xz0cy5vDDp/Y9t5bmCXZa/3Ho\nCJq+KLKhQJzv+niKK/c21OA85nIJzybK1xBRA/IrLwi6hTEs+vu7rca3NO3nBoX4\np0VPNQg15vanqqSNrO5twIzFnFyMzhjH1i2QUBKq8kG6oxTg/dTabUvrNCGgcl1V\ncVXuc2Yhvita/rzAoLB0euHDBb3pzeDVXceKP2ynDQKBgQDf7oJyIkQ4bZSRv64E\nbCpQdJWzImt9WJ2tt5d6nyTEoJUBrqQHklJxY2Xu0+r1QDASrZ0nyCfrY9b4z8IU\nrfBmvy1tdlo5nJa8q/GHfJYIgkfHviwCRNC4JhWQ8dNZfyZgVyyiWNdHCQ6X2VX6\n9GTFLn8m4B5J4SItWwB8LSy1+wKBgQDJ7rm4HU+Rmfp4kHTdkpZHNPr2jyHvc2VP\nmKmArwAx6bbW1zd2oXoAGIQKtsm6asZedwdjv2A10KeQhiWyMwXHD4O1kR4gpDbT\nI5xSZioLIvhGM76xBfGQAIifZ79U6XcSRCl7f/8HmDcPgYIKeWDiQyWtuXPKomU+\n7TNrAsDzHQKBgQCM39JGlRIP4bgefNSvyZBRLxbiK9wtbes8Vww/wxBxdohnF4Pv\nk3i0BpEgz0a35RqZFYmRdlTOu++IdcMmGUrsiIa+nz8hkUYvCYiX8KO+VJ9tpFCx\nWLNptePJXKjWW6w73Xuh4nwEH0mD8+EoUEl41sh9H29OkQhcOiyy8gR3swKBgG+w\nvEaq56zYJyLye8FmZ/qgwkMH7jQ8doftH6wOn6P76mawiXvzWsCczsQCUFfs4SW0\n3oB8hOGfNF+K42TKNeLhoO8Xgjt5uN1V8AvfeFfKktp5mnrdl7wXn3nT748uxu5y\nhyNJK61ust2/u0bB1iWwEDIjxnkJE8kXd/4zere9AoGAM0MjgIdZve6G4F9K68bc\nalTiV+iVR/3TEOe1UsE6mIWbt3/k1PWMfJ3oFbehK5b2F65RzJPi2meXqsmgWLZq\nTLOdO0Tk9OlzlgC0jl/tW2E3Xwry5TKb4kjSIZPC2oJnMtkp+wlIa3m1jROki9ch\n2atrLnOf2QsYDQTJIbhJx8w=\n-----END PRIVATE KEY-----\n"


@pytest.fixture
def tls_contexts(tmp_path):
    cert = tmp_path / "cert.pem"
    key = tmp_path / "key.pem"
    cert.write_text(TEST_CERT, encoding="ascii")
    key.write_text(TEST_KEY, encoding="ascii")
    server = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server.load_cert_chain(cert, key)
    client = ssl.create_default_context(cafile=str(cert))
    return server, client


async def tunnel(client_reader, client_writer, remote_reader, remote_writer):
    async def pipe(reader, writer):
        while data := await reader.read(65536):
            writer.write(data)
            await writer.drain()

    tasks = [
        asyncio.create_task(pipe(client_reader, remote_writer)),
        asyncio.create_task(pipe(remote_reader, client_writer)),
    ]
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


@asynccontextmanager
async def origin_server(
    *, body=None, raw=None, ssl_context=None, wait_event=None, headers=None, challenge_mode="valid_list"
):
    requests = []

    async def handle(request):
        requests.append(dict(request.headers))
        if wait_event is not None:
            await wait_event.wait()
        if raw is not None:
            return web.Response(body=raw, content_type="application/json", headers=headers)
        return web.json_response({"ip": "8.8.8.8"} if body is None else body)

    app = web.Application()
    app.router.add_get("/", handle)

    async def challenge(request):
        nonce = request.query.get("nonce")
        requests.append({**dict(request.headers), "_nonce": nonce, "_challenge": True})
        try:
            primary = (
                json.loads(raw) if raw is not None else (body if body is not None else {"ip": "8.8.8.8"})
            )
        except (ValueError, UnicodeError):
            primary = {}
        origin = primary.get("ip", "8.8.8.8") if isinstance(primary, dict) else "8.8.8.8"
        echoed = nonce if challenge_mode == "valid_string" else [nonce]
        if challenge_mode == "stale_nonce":
            echoed = "cached"
        elif challenge_mode == "multiple_nonce":
            echoed = [nonce, "unexpected"]
        if challenge_mode == "private_origin":
            origin = "10.0.0.1"
        elif challenge_mode == "mixed_private_origin":
            origin = "8.8.8.8,127.0.0.1"
        args = {} if challenge_mode == "missing_nonce" else {"nonce": echoed}
        return web.json_response({"args": args, "origin": origin})

    app.router.add_get("/anything", challenge)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0, ssl_context=ssl_context)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    try:
        yield port, requests
    finally:
        await runner.cleanup()


@asynccontextmanager
async def http_proxy(*, allow_connect=False, reject_http=False, allowed_hosts=None):
    state = {"connections": 0, "requests": []}
    tasks = set()

    async def handle(reader, writer):
        state["connections"] += 1
        upstream = None
        try:
            head = await reader.readuntil(b"\r\n\r\n")
            lines = head.decode("latin1").split("\r\n")
            method, target, _ = lines[0].split(" ", 2)
            state["requests"].append((method, target))
            if method == "CONNECT":
                if not allow_connect:
                    writer.write(b"HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\n\r\n")
                    await writer.drain()
                    return
                url = urlsplit("http://" + target)
                remote_host = (
                    "127.0.0.1" if url.hostname in {"probe.test", "challenge.test"} else url.hostname
                )
                remote_reader, upstream = await asyncio.open_connection(remote_host, url.port)
                writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
                await writer.drain()
                await tunnel(reader, writer, remote_reader, upstream)
                return
            if reject_http:
                writer.write(b"HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\n\r\n")
                await writer.drain()
                return
            url = urlsplit(target)
            if allowed_hosts is not None and url.hostname not in allowed_hosts:
                writer.write(b"HTTP/1.1 409 Conflict\r\nContent-Length: 0\r\n\r\n")
                await writer.drain()
                return
            remote_host = "127.0.0.1" if url.hostname in {"probe.test", "challenge.test"} else url.hostname
            remote_reader, upstream = await asyncio.open_connection(remote_host, url.port or 80)
            path = url.path or "/"
            if url.query:
                path += "?" + url.query
            headers = [
                line
                for line in lines[1:]
                if line and not line.lower().startswith(("connection:", "proxy-connection:"))
            ]
            outbound = f"{method} {path} HTTP/1.1\r\n" + "\r\n".join(headers)
            upstream.write(
                (outbound + "\r\nConnection: close\r\nX-Fixture-Proxy: yes\r\n\r\n").encode("latin1")
            )
            await upstream.drain()
            while data := await remote_reader.read(65536):
                writer.write(data)
                await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionError, OSError):
            pass
        finally:
            if upstream is not None:
                upstream.close()
                with contextlib.suppress(ConnectionError, OSError):
                    await upstream.wait_closed()
            writer.close()
            with contextlib.suppress(ConnectionError, OSError):
                await writer.wait_closed()

    def connected(reader, writer):
        task = asyncio.create_task(handle(reader, writer))
        tasks.add(task)
        task.add_done_callback(tasks.discard)

    server = await asyncio.start_server(connected, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    try:
        yield port, state
    finally:
        server.close()
        await server.wait_closed()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


@asynccontextmanager
async def socks_proxy(protocol):
    handshakes = []
    tasks = set()

    async def handle(reader, writer):
        upstream = None
        try:
            version = (await reader.readexactly(1))[0]
            if protocol == "socks4" and version == 4:
                command = await reader.readexactly(1)
                port = int.from_bytes(await reader.readexactly(2), "big")
                ip = await reader.readexactly(4)
                await reader.readuntil(b"\x00")
                rdns = ip[:3] == b"\x00\x00\x00" and ip[3] != 0
                host = (
                    (await reader.readuntil(b"\x00"))[:-1].decode() if rdns else str(ipaddress.ip_address(ip))
                )
                assert command == b"\x01"
                reply = b"\x00\x5a" + port.to_bytes(2, "big") + b"\x7f\x00\x00\x01"
            elif protocol == "socks5" and version == 5:
                count = (await reader.readexactly(1))[0]
                methods = await reader.readexactly(count)
                assert 0 in methods
                writer.write(b"\x05\x00")
                await writer.drain()
                version, command, _, kind = await reader.readexactly(4)
                assert (version, command) == (5, 1)
                rdns = kind == 3
                if kind == 3:
                    size = (await reader.readexactly(1))[0]
                    host = (await reader.readexactly(size)).decode()
                else:
                    host = str(ipaddress.ip_address(await reader.readexactly(4 if kind == 1 else 16)))
                port = int.from_bytes(await reader.readexactly(2), "big")
                reply = b"\x05\x00\x00\x01\x7f\x00\x00\x01" + port.to_bytes(2, "big")
            else:
                return
            handshakes.append({"host": host, "port": port, "rdns": rdns})
            remote_reader, upstream = await asyncio.open_connection("127.0.0.1", port)
            writer.write(reply)
            await writer.drain()
            await tunnel(reader, writer, remote_reader, upstream)
        except (asyncio.IncompleteReadError, ConnectionError, OSError):
            pass
        finally:
            if upstream is not None:
                upstream.close()
                with contextlib.suppress(ConnectionError, OSError):
                    await upstream.wait_closed()
            writer.close()
            with contextlib.suppress(ConnectionError, OSError):
                await writer.wait_closed()

    def connected(reader, writer):
        task = asyncio.create_task(handle(reader, writer))
        tasks.add(task)
        task.add_done_callback(tasks.discard)

    server = await asyncio.start_server(connected, "127.0.0.1", 0)
    try:
        yield server.sockets[0].getsockname()[1], handshakes
    finally:
        server.close()
        await server.wait_closed()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


@pytest.mark.parametrize("protocol", ["socks4", "socks5"])
async def test_socks_proxies_use_remote_dns_and_real_http_https_tunnels(protocol, tls_contexts):
    from proxyharbor.checker import ProxyChecker
    from proxyharbor.models import ProxyCandidate

    server_ssl, client_ssl = tls_contexts
    async with (
        origin_server() as (http_port, http_received),
        origin_server(ssl_context=server_ssl) as (https_port, https_received),
        socks_proxy(protocol) as (proxy_port, handshakes),
    ):
        checker = fixture_checker(
            ProxyChecker,
            timeout=0.8,
            connect_timeout=0.3,
            allow_private=True,
            ssl_context=client_ssl,
            http_probe_url=f"http://probe.test:{http_port}/",
            https_probe_url=f"https://probe.test:{https_port}/",
        )
        try:
            result = await checker.check(ProxyCandidate("127.0.0.1", proxy_port, protocol))
        finally:
            await checker.close()
        assert result.ok is True, result.error
        assert result.supports_https is True
        assert result.exit_ip == "8.8.8.8"
        assert len(http_received) == len(https_received) == 2
        assert len(handshakes) == 4
        assert {record["host"] for record in handshakes} == {"probe.test", "challenge.test"}
        assert all(record["rdns"] for record in handshakes)


def fixture_checker(checker_type, **options):
    """Explicit local echo dependency; production always selects an independent provider."""
    for scheme in ("http", "https"):
        probe = options.get(f"{scheme}_probe_url")
        if probe and urlsplit(probe).hostname in {"127.0.0.1", "probe.test"}:
            options.setdefault(
                f"{scheme}_challenge_url", f"{scheme}://challenge.test:{urlsplit(probe).port}/anything"
            )
    return checker_type(**options)


async def test_http_proxy_is_verified_with_real_forward_request_after_tcp_preflight():
    from proxyharbor.checker import ProxyChecker
    from proxyharbor.models import ProxyCandidate

    async with origin_server() as (origin_port, received), http_proxy() as (proxy_port, state):
        checker = fixture_checker(
            ProxyChecker,
            timeout=0.5,
            connect_timeout=0.2,
            allow_private=True,
            http_probe_url=f"http://127.0.0.1:{origin_port}/",
            https_probe_url=f"https://127.0.0.1:{origin_port}/",
        )
        await checker.start()
        before = time.time()
        try:
            result = await checker.check(ProxyCandidate("127.0.0.1", proxy_port, "http"))
        finally:
            await checker.close()
        assert result.ok is True
        assert result.exit_ip == "8.8.8.8"
        assert result.supports_https is False
        assert result.error is None
        assert result.latency_ms >= 0
        assert before <= result.checked_at <= time.time()
        assert state["connections"] >= 2
        assert any(method == "GET" for method, _ in state["requests"])
        assert received[0]["X-Fixture-Proxy"] == "yes"


async def test_https_only_proxy_requires_verified_tls_connect(tls_contexts):
    from proxyharbor.checker import ProxyChecker
    from proxyharbor.models import ProxyCandidate

    server_ssl, client_ssl = tls_contexts
    async with (
        origin_server(ssl_context=server_ssl) as (origin_port, received),
        http_proxy(allow_connect=True, reject_http=True) as (proxy_port, state),
    ):
        options = {
            "timeout": 0.8,
            "connect_timeout": 0.3,
            "allow_private": True,
            "http_probe_url": f"http://127.0.0.1:{origin_port}/",
            "https_probe_url": f"https://127.0.0.1:{origin_port}/",
        }
        candidate = ProxyCandidate("127.0.0.1", proxy_port, "http")
        trusted = fixture_checker(ProxyChecker, **options, ssl_context=client_ssl)
        try:
            result = await trusted.check(candidate)
        finally:
            await trusted.close()
        assert result.ok is True
        assert result.supports_https is True
        assert result.exit_ip == "8.8.8.8"
        assert result.latency_ms >= 0
        assert sorted(method for method, _ in state["requests"]) == ["CONNECT", "CONNECT", "GET", "GET"]
        assert len(received) == 2

        untrusted = fixture_checker(ProxyChecker, **options)
        try:
            rejected = await untrusted.check(candidate)
        finally:
            await untrusted.close()
        assert rejected.ok is False
        assert rejected.supports_https is False
        assert "certificate" in rejected.error.lower()
        assert len(received) == 2


@pytest.mark.parametrize(
    "raw,expected",
    [
        (b'{"ip":"8.8.8.8"}', "8.8.8.8"),
        (b'{"ip":"2606:4700:4700:0:0:0:0:1111"}', "2606:4700:4700::1111"),
        (b'{"ip":"127.0.0.1"}', None),
        (b'{"ip":"224.0.0.1"}', None),
        (b'{"ip":"192.0.2.1"}', None),
        (b'{"ip":123}', None),
        (b'["8.8.8.8"]', None),
        (b"not json", None),
        (b'{"ip":"8.8.8.8","padding":"' + b"x" * 1024 + b'"}', None),
    ],
)
async def test_checker_requires_bounded_json_with_public_exit_ip(raw, expected):
    from proxyharbor.checker import ProxyChecker
    from proxyharbor.models import ProxyCandidate

    async with origin_server(raw=raw) as (origin_port, _), http_proxy() as (proxy_port, _):
        checker = fixture_checker(
            ProxyChecker,
            timeout=0.5,
            connect_timeout=0.2,
            allow_private=True,
            max_body_bytes=128,
            http_probe_url=f"http://127.0.0.1:{origin_port}/",
            https_probe_url=f"https://127.0.0.1:{origin_port}/",
        )
        try:
            result = await checker.check(ProxyCandidate("127.0.0.1", proxy_port, "http"))
        finally:
            await checker.close()
        assert result.ok is (expected is not None)
        assert result.exit_ip == expected
        if expected is None:
            assert result.error


@pytest.mark.parametrize(
    "options",
    [
        {"timeout": 0},
        {"timeout": -1},
        {"timeout": float("nan")},
        {"timeout": float("inf")},
        {"connect_timeout": 0},
        {"connect_timeout": float("inf")},
        {"max_body_bytes": 0},
        {"max_body_bytes": True},
        {"http_probe_url": "ftp://example.org/"},
        {"https_probe_url": "http://example.org/"},
        {"https_probe_url": "https://user:password@example.org/"},
        {"http_probe_url": "http://127.0.0.1/"},
        {"https_probe_url": "https://localhost/"},
        {"https_probe_url": "https://example.org:65536/"},
        {"ssl_context": ssl._create_unverified_context()},
    ],
)
def test_checker_configuration_cannot_disable_bounds_or_https_verification(options):
    from proxyharbor.checker import ProxyChecker

    with pytest.raises(ValueError):
        ProxyChecker(**options)


async def test_checker_propagates_cancellation_during_a_real_proxy_request():
    from proxyharbor.checker import ProxyChecker
    from proxyharbor.models import ProxyCandidate

    unblock = asyncio.Event()
    async with origin_server(wait_event=unblock) as (origin_port, received), http_proxy() as (proxy_port, _):
        checker = fixture_checker(
            ProxyChecker,
            timeout=2,
            connect_timeout=0.2,
            allow_private=True,
            http_probe_url=f"http://127.0.0.1:{origin_port}/",
            https_probe_url=f"https://127.0.0.1:{origin_port}/",
        )
        task = asyncio.create_task(checker.check(ProxyCandidate("127.0.0.1", proxy_port, "http")))
        try:
            async with asyncio.timeout(1):
                while not received:
                    await asyncio.sleep(0.001)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        finally:
            unblock.set()
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            await checker.close()


async def test_tcp_acceptance_without_probe_json_is_dead_with_a_bounded_timeout():
    from proxyharbor.checker import ProxyChecker
    from proxyharbor.models import ProxyCandidate

    unblock = asyncio.Event()
    async with origin_server(wait_event=unblock) as (origin_port, _), http_proxy() as (proxy_port, state):
        checker = fixture_checker(
            ProxyChecker,
            timeout=0.15,
            connect_timeout=0.1,
            allow_private=True,
            http_probe_url=f"http://127.0.0.1:{origin_port}/",
            https_probe_url=f"https://127.0.0.1:{origin_port}/",
        )
        started = time.perf_counter()
        try:
            result = await checker.check(ProxyCandidate("127.0.0.1", proxy_port, "http"))
            elapsed = time.perf_counter() - started
        finally:
            unblock.set()
            await checker.close()
        assert result.ok is False
        assert result.supports_https is False
        assert result.latency_ms is None
        assert "Timeout" in result.error
        assert elapsed < checker.timeout + checker.connect_timeout + 0.5
        assert state["connections"] >= 2
        assert any(method == "GET" for method, _ in state["requests"])


@pytest.mark.parametrize(
    "encoding,raw,expected",
    [
        ("gzip", gzip.compress(b'{"ip":"8.8.8.8"}'), True),
        ("deflate", zlib.compress(b'{"ip":"8.8.8.8"}'), True),
        ("gzip", gzip.compress(b'{"ip":"8.8.8.8","padding":"' + b"x" * 20000 + b'"}'), False),
        ("gzip", gzip.compress(b'{"ip":"8.8.8.8"}') + gzip.compress(b"") * 20, False),
        ("gzip", gzip.compress(b'{"ip":"8.8.8.8"}')[:-5], False),
    ],
)
async def test_compressed_probe_bodies_are_bounded_on_wire_and_after_decompression(encoding, raw, expected):
    from proxyharbor.checker import ProxyChecker
    from proxyharbor.models import ProxyCandidate

    async with (
        origin_server(raw=raw, headers={"Content-Encoding": encoding}) as (origin_port, received),
        http_proxy() as (proxy_port, _),
    ):
        checker = fixture_checker(
            ProxyChecker,
            timeout=0.5,
            connect_timeout=0.2,
            allow_private=True,
            max_body_bytes=128,
            http_probe_url=f"http://127.0.0.1:{origin_port}/",
            https_probe_url=f"https://127.0.0.1:{origin_port}/",
        )
        try:
            result = await checker.check(ProxyCandidate("127.0.0.1", proxy_port, "http"))
        finally:
            await checker.close()
        assert result.ok is expected
        assert received[0]["Accept-Encoding"] == "identity"
        if expected:
            assert result.exit_ip == "8.8.8.8"
        else:
            assert result.error


@pytest.mark.parametrize("host", ["127.0.0.1", "example.org", "224.0.0.1"])
async def test_production_checker_rejects_nonpublic_or_nonliteral_peers_before_tcp(host):
    from proxyharbor.checker import ProxyChecker
    from proxyharbor.models import ProxyCandidate

    async with http_proxy() as (port, state):
        checker = fixture_checker(ProxyChecker, timeout=0.2, connect_timeout=0.1)
        try:
            result = await checker.check(ProxyCandidate(host, port, "http"))
        finally:
            await checker.close()
        assert result.ok is False
        assert result.error
        assert state["connections"] == 0
        assert state["requests"] == []


async def test_failed_proxy_handshake_never_falls_back_to_a_direct_probe():
    from proxyharbor.checker import ProxyChecker
    from proxyharbor.models import ProxyCandidate

    async with origin_server() as (origin_port, received), socks_proxy("socks5") as (proxy_port, handshakes):
        checker = fixture_checker(
            ProxyChecker,
            timeout=0.3,
            connect_timeout=0.1,
            allow_private=True,
            http_probe_url=f"http://127.0.0.1:{origin_port}/",
            https_probe_url=f"https://127.0.0.1:{origin_port}/",
        )
        await checker.start()
        session = checker._session
        assert session.trust_env is False
        await checker.start()
        assert checker._session is session
        try:
            result = await checker.check(ProxyCandidate("127.0.0.1", proxy_port, "http"))
        finally:
            await checker.close()
        assert result.ok is False
        assert result.error
        assert received == []
        assert handshakes == []
        assert session.closed is True


async def test_ip_echo_reverse_endpoint_is_not_a_general_proxy():
    from proxyharbor.checker import ProxyChecker
    from proxyharbor.models import ProxyCandidate

    async with (
        origin_server() as (origin_port, received),
        http_proxy(allowed_hosts={"probe.test"}) as (port, state),
    ):
        checker = ProxyChecker(
            timeout=0.5,
            connect_timeout=0.2,
            allow_private=True,
            http_probe_url=f"http://probe.test:{origin_port}/",
            https_probe_url=f"https://probe.test:{origin_port}/",
        )
        try:
            result = await checker.check(ProxyCandidate("127.0.0.1", port, "http"))
        finally:
            await checker.close()
        assert result.ok is False, "an ipify-only reverse endpoint is not a forward proxy"
        assert result.supports_https is False
        assert result.error
        assert len(received) == 1
        assert any(
            urlsplit(target).hostname == "httpbingo.org"
            for method, target in state["requests"]
            if method == "GET"
        )


async def test_custom_origin_ip_probe_is_kept_and_uses_an_independent_challenge():
    from proxyharbor.checker import ProxyChecker
    from proxyharbor.models import ProxyCandidate

    async with origin_server(body={"origin": "8.8.8.8"}) as (origin_port, _), http_proxy() as (port, _):
        http_url = f"http://127.0.0.1:{origin_port}/?custom=kept"
        https_url = f"https://127.0.0.1:{origin_port}/?custom=kept"
        checker = fixture_checker(
            ProxyChecker,
            timeout=0.5,
            connect_timeout=0.2,
            allow_private=True,
            http_probe_url=http_url,
            https_probe_url=https_url,
        )
        try:
            result = await checker.check(ProxyCandidate("127.0.0.1", port, "http"))
        finally:
            await checker.close()
        assert result.ok is True, result.error
        assert result.supports_https is False
        assert result.exit_ip == "8.8.8.8"
        assert checker.http_probe_url == http_url
        assert checker.https_probe_url == https_url
    alternative = ProxyChecker(
        http_probe_url="http://httpbingo.org/ip", https_probe_url="https://httpbingo.org/ip"
    )
    assert urlsplit(alternative._http_challenge_url).hostname == "httpbin.org"
    assert urlsplit(alternative._https_challenge_url).hostname == "httpbin.org"


@pytest.mark.parametrize(
    "mode,expected",
    [
        ("valid_list", True),
        ("valid_string", True),
        ("stale_nonce", False),
        ("multiple_nonce", False),
        ("private_origin", False),
        ("mixed_private_origin", False),
        ("missing_nonce", False),
    ],
)
async def test_independent_challenge_requires_exact_fresh_nonce_and_public_origin(mode, expected):
    from proxyharbor.checker import ProxyChecker
    from proxyharbor.models import CHECK_VALIDATION_VERSION, ProxyCandidate

    async with origin_server(challenge_mode=mode) as (origin_port, received), http_proxy() as (port, _):
        checker = fixture_checker(
            ProxyChecker,
            timeout=0.5,
            connect_timeout=0.2,
            allow_private=True,
            http_probe_url=f"http://127.0.0.1:{origin_port}/",
            https_probe_url=f"https://127.0.0.1:{origin_port}/",
        )
        candidate = ProxyCandidate("127.0.0.1", port, "http")
        try:
            first = await checker.check(candidate)
            second = await checker.check(candidate)
        finally:
            await checker.close()
        assert first.ok is second.ok is expected
        assert first.supports_https is second.supports_https is False
        assert first.validation_version == second.validation_version == CHECK_VALIDATION_VERSION
        challenges = [row for row in received if row.get("_challenge")]
        assert len(challenges) == 2
        assert len({row["_nonce"] for row in challenges}) == 2
        assert all(row["_nonce"] and row["Host"].startswith("challenge.test:") for row in challenges)
        if not expected:
            assert first.error and second.error
