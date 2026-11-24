"""Source security and registry contracts; offline localhost integration tests."""

import importlib
import json
import socket
from types import SimpleNamespace

import aiohttp
import pytest
import pytest_asyncio
from aiohttp import web


def sources_module():
    try:
        return importlib.import_module("proxyharbor.sources")
    except ModuleNotFoundError as exc:
        pytest.fail(f"source module not implemented: {exc}")


def test_validate_source_url_rejects_unsafe_urls():
    validate = sources_module().validate_source_url
    bad = [
        "file:///etc/passwd",
        "ftp://example.com/list",
        "https://user:secret@example.com/feed",
        "http://localhost/list",
        "http://LOCALHOST./list",
        "http://127.0.0.1:8000/list",
        "http://10.0.0.1/list",
        "http://169.254.169.254/latest/meta-data/",
        "http://[::1]/list",
        "http://[::ffff:127.0.0.1]/list",
        "http://0.0.0.0/list",
        "http://2130706433/list",
        "http://0x7f000001/list",
        "http://127.1/list",
        "https://example.com:0/list",
        "https://example.com:65536/list",
        "https:///list",
        "https://example.com\\@127.0.0.1/list",
        "https://example.com/list\nnext",
        "https://example.com/#secret",
    ]
    for url in bad:
        with pytest.raises(ValueError, match="(?i)url|host|port|public|private|credential|scheme|fragment"):
            validate(url)
    assert validate("https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt") == (
        "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt"
    )
    assert validate("https://[2606:4700:4700::1111]:443/list?x=1") == (
        "https://[2606:4700:4700::1111]:443/list?x=1"
    )


def test_load_sources_validates_normalizes_and_deduplicates(tmp_path):
    load = sources_module().load_sources
    path = tmp_path / "sources.json"
    url = "https://example.com/proxies.txt"
    path.write_text(
        json.dumps(
            [
                {"id": "primary", "name": "Publisher HTTP", "url": url},
                {"id": "connect", "name": "Publisher CONNECT", "url": url, "protocol": "https"},
                {
                    "id": "socks",
                    "name": "Publisher SOCKS5",
                    "url": url,
                    "protocol": "socks5",
                    "enabled": False,
                },
            ]
        ),
        encoding="utf-8",
    )
    result = load(path)
    assert [source.id for source in result] == ["primary", "socks"]
    assert [(s.protocol, s.format, s.enabled) for s in result] == [
        ("http", "text", True),
        ("socks5", "text", False),
    ]
    path.write_text(json.dumps([{"id": "unsafe", "name": "Unsafe", "url": "http://10.0.0.1/feed"}]))
    with pytest.raises(ValueError, match="public"):
        load(path)


@pytest_asyncio.fixture
async def local_feed(monkeypatch):
    """Only this fixture's DNS name is pinned to localhost; no production switch."""
    module = sources_module()
    app = web.Application()
    hits = []

    async def text(request):
        hits.append(request.path)
        return web.Response(text="8.8.8.8:8080\n1.1.1.1:80\n", content_type="text/plain")

    async def redirect(request):
        hits.append(request.path)
        return web.Response(
            status=302,
            headers={
                "Location": request.query.get("target", "/loop" if request.path == "/loop" else "/text")
            },
        )

    async def compressed(request):
        import gzip
        import zlib

        data = b"8.8.8.8:80\n" * 100_000
        encoding = request.query.get("encoding", "gzip")
        packed = gzip.compress(data) if encoding == "gzip" else zlib.compress(data)
        mode = request.query.get("mode")
        if mode == "multi":
            packed = gzip.compress(b"8.8.8.8:80\n") + packed
        elif mode == "truncated":
            packed = packed[:-8]
        elif mode == "empty-train":
            packed = gzip.compress(b"") * 10000
        return web.Response(body=packed, headers={"Content-Encoding": encoding})

    async def slow(request):
        import asyncio

        await asyncio.sleep(float(request.query.get("delay", "0.04")))
        if request.query.get("target"):
            return web.Response(status=302, headers={"Location": request.query["target"]})
        return await text(request)

    async def json_feed(request):
        if request.query.get("shape") == "upper":
            return web.json_response(
                {"LISTA": [{"LIST": [{"IP": "8.8.8.8", "PORT": "8080"}, {"IP": "127.0.0.1", "PORT": "80"}]}]}
            )
        return web.json_response(
            {
                "data": [
                    {"ip": "8.8.8.8", "port": "8080", "protocols": ["https", "http"]},
                    {"ip": "127.0.0.1", "port": 80, "protocols": ["http"]},
                ]
            }
        )

    async def html_feed(request):
        return web.Response(
            text="<table><tr><td>8.8.8.8</td><td>8080</td></tr>"
            "<tr><td>127.0.0.1</td><td>80</td></tr></table>"
            "<script>1.1.1.1:9999</script>",
            content_type="text/html",
        )

    async def empty(request):
        return web.Response(text="")

    async def status(request):
        hits.append(request.path)
        return web.Response(status=int(request.query.get("code", "503")), text="maintenance")

    app.router.add_get("/text", text)
    app.router.add_get("/redirect", redirect)
    app.router.add_get("/loop", redirect)
    app.router.add_get("/status", status)
    app.router.add_get("/compressed", compressed)
    app.router.add_get("/slow", slow)
    app.router.add_get("/empty", empty)
    app.router.add_get("/json", json_feed)
    app.router.add_get("/html", html_feed)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    original = getattr(module, "_resolve_public", None)

    async def fixture_dns(host, port, family=socket.AF_UNSPEC):
        if host == "feed-fixture.example":
            return [
                {
                    "hostname": host,
                    "host": "127.0.0.1",
                    "port": port,
                    "family": socket.AF_INET,
                    "proto": 0,
                    "flags": socket.AI_NUMERICHOST,
                }
            ]
        if original is None:
            raise AssertionError("public DNS resolver not implemented")
        return await original(host, port, family)

    monkeypatch.setattr(module, "_resolve_public", fixture_dns, raising=False)
    try:
        yield f"http://feed-fixture.example:{port}", hits
    finally:
        await runner.cleanup()


def fixture_source(url, format="text"):
    return SimpleNamespace(
        id="fixture", name="Local fixture", url=url, protocol="http", format=format, enabled=True
    )


async def test_fetch_source_reads_a_real_http_feed(local_feed):
    base, hits = local_feed
    async with aiohttp.ClientSession(trust_env=False) as session:
        text = await sources_module().fetch_source(session, fixture_source(base + "/text"))
    assert text == "8.8.8.8:8080\n1.1.1.1:80\n"
    assert hits == ["/text"]


async def test_redirect_revalidates_dns_against_public_to_private_rebinding(local_feed, monkeypatch):
    base, hits = local_feed
    module = sources_module()
    fixture_dns = module._resolve_public
    resolutions = 0

    async def rebinding_dns(host, port, family=socket.AF_UNSPEC):
        nonlocal resolutions
        resolutions += 1
        if resolutions > 1:
            raise ValueError("DNS must return only public addresses; rebinding blocked")
        return await fixture_dns(host, port, family)

    monkeypatch.setattr(module, "_resolve_public", rebinding_dns)
    async with aiohttp.ClientSession(trust_env=False) as session:
        with pytest.raises(ValueError, match="rebinding"):
            await module.fetch_source(session, fixture_source(base + "/redirect"))
    assert resolutions == 2
    assert hits == ["/redirect"]


@pytest.mark.parametrize(
    "private", ["127.0.0.1", "10.20.0.1", "169.254.169.254", "::1", "::ffff:127.0.0.1", "224.0.0.1"]
)
async def test_dns_rejects_every_nonpublic_answer_even_after_a_public_one(monkeypatch, private):
    async def answers(*args, **kwargs):
        family = socket.AF_INET6 if ":" in private else socket.AF_INET
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 80)),
            (family, socket.SOCK_STREAM, 6, "", (private, 80)),
        ]

    import asyncio

    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", answers)
    with pytest.raises(ValueError, match="(?i)DNS.*public|public.*DNS"):
        await sources_module()._resolve_public("attacker.example", 80)


async def test_fetch_follows_only_validated_redirects_with_a_hard_limit(local_feed):
    from urllib.parse import quote

    base, hits = local_feed
    fetch = sources_module().fetch_source
    async with aiohttp.ClientSession(trust_env=False) as session:
        assert "8.8.8.8:8080" in await fetch(session, fixture_source(base + "/redirect"))
        for target in ["http://127.0.0.1/text", "http://user:pass@public.example/list", "file:///etc/passwd"]:
            with pytest.raises(ValueError, match="public|credentials|scheme"):
                await fetch(session, fixture_source(base + "/redirect?target=" + quote(target, safe="")))
        with pytest.raises(RuntimeError, match="redirect"):
            await fetch(session, fixture_source(base + "/loop"))
    assert hits.count("/text") == 1
    assert hits.count("/loop") <= 6


@pytest.mark.parametrize(
    "field,value",
    [
        ("id", ""),
        ("id", "has spaces"),
        ("id", 7),
        ("name", ""),
        ("name", 3),
        ("enabled", "false"),
        ("enabled", 1),
        ("format", "executable"),
        ("protocol", []),
        ("format", []),
        ("id", {"bad": "id"}),
    ],
)
def test_registry_rejects_wrong_field_types_and_values(tmp_path, field, value):
    path = tmp_path / "sources.json"
    row = {"id": "source", "name": "Name", "url": "https://example.com/list", field: value}
    path.write_text(json.dumps([row]), encoding="utf-8")
    with pytest.raises(ValueError):
        sources_module().load_sources(path)


def test_save_sources_validates_before_an_atomic_replace(tmp_path, monkeypatch):
    from proxyharbor.models import SourceSpec

    module = sources_module()
    path = tmp_path / "nested" / "sources.json"
    url = "https://example.com/proxies.txt"
    rows = [SourceSpec("one", "One", url), SourceSpec("two", "Two", url, "https")]
    module.save_sources(path, rows)
    assert [s.id for s in module.load_sources(path)] == ["one"]
    before = path.read_bytes()
    with pytest.raises(ValueError, match="public"):
        module.save_sources(path, [SourceSpec("bad", "Bad", "http://10.0.0.1/list")])
    assert path.read_bytes() == before

    def failing_replace(temporary, destination):
        assert path.read_bytes() == before
        assert json.loads(__import__("pathlib").Path(temporary).read_text(encoding="utf-8"))[0]["id"] == "new"
        raise OSError("fixture disk error")

    monkeypatch.setattr(module.os, "replace", failing_replace)
    with pytest.raises(OSError, match="fixture disk error"):
        module.save_sources(path, [SourceSpec("new", "New", "https://example.com/new")])
    assert path.read_bytes() == before
    assert sorted(p.name for p in path.parent.iterdir()) == ["sources.json"]


@pytest.mark.parametrize("status", [403, 404, 429, 503])
async def test_fetch_raises_descriptive_http_errors(local_feed, status):
    base, _ = local_feed
    url = base + f"/status?code={status}"
    async with aiohttp.ClientSession(trust_env=False) as session:
        with pytest.raises(RuntimeError, match=f"HTTP {status}") as caught:
            await sources_module().fetch_source(session, fixture_source(url))
    assert url in str(caught.value)
    assert caught.value.status == status


@pytest.mark.parametrize("endpoint", ["/text", "/compressed?encoding=gzip", "/compressed?encoding=deflate"])
async def test_fetch_bounds_decompressed_body_including_compression_bombs(local_feed, endpoint):
    base, _ = local_feed
    async with aiohttp.ClientSession(trust_env=False) as session:
        with pytest.raises(RuntimeError, match="decompressed.*limit|body.*limit"):
            await sources_module().fetch_source(session, fixture_source(base + endpoint), max_bytes=16)
        text = await sources_module().fetch_source(
            session, fixture_source(base + "/text"), max_bytes=len("8.8.8.8:8080\n1.1.1.1:80\n")
        )
        assert text == "8.8.8.8:8080\n1.1.1.1:80\n"


@pytest.mark.parametrize("mode,limit", [("multi", 64), ("truncated", 2_000_000), ("empty-train", 64)])
async def test_compressed_streams_cannot_hide_extra_members_or_missing_trailers(local_feed, mode, limit):
    base, _ = local_feed
    async with aiohttp.ClientSession(trust_env=False) as session:
        with pytest.raises(RuntimeError, match="limit|truncated|compressed"):
            await sources_module().fetch_source(
                session, fixture_source(base + "/compressed?mode=" + mode), max_bytes=limit
            )


async def test_fetch_rejects_parent_sessions_that_trust_proxy_environment(local_feed, monkeypatch):
    base, hits = local_feed
    monkeypatch.setenv("HTTP_PROXY", base + "/environment-proxy")
    monkeypatch.setenv("HTTPS_PROXY", base + "/environment-proxy")
    async with aiohttp.ClientSession(trust_env=True) as session:
        with pytest.raises(ValueError, match="trust_env=False"):
            await sources_module().fetch_source(session, fixture_source(base + "/text"))
    assert hits == []
    async with aiohttp.ClientSession(trust_env=False, headers={"Authorization": "fixture-secret"}) as session:
        assert "8.8.8.8" in await sources_module().fetch_source(session, fixture_source(base + "/text"))
    assert hits == ["/text"]


async def test_fetch_timeout_covers_the_whole_redirect_chain_and_cancellation_survives(local_feed):
    import asyncio
    from urllib.parse import quote

    base, _ = local_feed
    hop = "/slow?delay=0.04&target=" + quote("/slow?delay=0.04", safe="")
    async with aiohttp.ClientSession(trust_env=False) as session:
        with pytest.raises(RuntimeError, match="timeout"):
            await sources_module().fetch_source(session, fixture_source(base + hop), timeout=0.07)
        task = asyncio.create_task(
            sources_module().fetch_source(session, fixture_source(base + "/slow?delay=1"))
        )
        await asyncio.sleep(0.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


async def test_fetch_audit_metadata_records_actual_status_final_url_size_and_hash(local_feed):
    import hashlib

    base, _ = local_feed
    expected = b"8.8.8.8:8080\n1.1.1.1:80\n"
    async with aiohttp.ClientSession(trust_env=False) as session:
        document = await sources_module()._fetch_document(session, fixture_source(base + "/redirect"))
    assert document.text == expected.decode()
    assert document.http_status == 200
    assert document.final_url == base + "/text"
    assert document.decompressed_bytes == len(expected)
    assert document.sha256 == hashlib.sha256(expected).hexdigest()


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_bytes": 0},
        {"max_bytes": -1},
        {"max_bytes": True},
        {"max_bytes": 5.5},
        {"max_bytes": 50_000_001},
        {"timeout": 0},
        {"timeout": -1},
        {"timeout": True},
        {"timeout": float("nan")},
        {"timeout": float("inf")},
    ],
)
async def test_fetch_rejects_invalid_bounds_before_any_network_request(local_feed, kwargs):
    base, hits = local_feed
    async with aiohttp.ClientSession(trust_env=False) as session:
        with pytest.raises(ValueError, match="max_bytes|timeout"):
            await sources_module().fetch_source(session, fixture_source(base + "/text"), **kwargs)
    assert hits == []


@pytest.mark.parametrize(
    "endpoint,format", [("/json?shape=upper", "json"), ("/json?shape=geonode", "json"), ("/html", "html")]
)
async def test_json_provider_aliases_and_html_obey_the_public_parser_contract(local_feed, endpoint, format):
    from proxyharbor.parsing import parse_candidates

    base, _ = local_feed
    async with aiohttp.ClientSession(trust_env=False) as session:
        text = await sources_module().fetch_source(session, fixture_source(base + endpoint, format=format))
    assert [candidate.url for candidate in parse_candidates(text, "http", format)] == ["http://8.8.8.8:8080"]


def audit_module():
    from pathlib import Path

    path = Path(__file__).parents[1] / "scripts" / "audit_sources.py"
    assert path.exists(), "source auditor has not been implemented"
    spec = importlib.util.spec_from_file_location("source_auditor", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def test_audit_fetches_real_http_feeds_and_selects_only_nonempty_successes(local_feed):
    base, _ = local_feed
    auditor = audit_module()
    rows = [
        {"url": base + suffix, "protocol": "http", "format": "text", "publisher": "fixture"}
        for suffix in ["/text", "/status?code=503", "/empty"]
    ]
    results = await auditor.audit_sources(rows, concurrency=2, timeout=2)
    by_url = {entry["url"]: entry for entry in results}
    assert by_url[base + "/text"]["http_status"] == 200
    assert by_url[base + "/text"]["valid_candidates"] == 2
    assert by_url[base + "/text"]["healthy"] is True
    assert by_url[base + "/status?code=503"]["http_status"] == 503
    assert by_url[base + "/status?code=503"]["healthy"] is False
    assert by_url[base + "/empty"]["healthy"] is False
    assert "no public proxy entries" in by_url[base + "/empty"]["error"]
    selected = auditor.select_sources(results, max_feeds=140)
    assert len(selected) == 1 and selected[0].url == base + "/text" and selected[0].enabled


async def test_auditor_cli_persists_each_batch_and_a_verified_catalog(local_feed, tmp_path):
    import asyncio

    from proxyharbor.sources import load_sources

    base, _ = local_feed
    auditor = audit_module()
    input_path, output_path, catalog = (
        tmp_path / "input.json",
        tmp_path / "audit.json",
        tmp_path / "sources.json",
    )
    rows = [
        {"url": base + path, "protocol": "http", "format": "text"}
        for path in ["/text", "/status?code=503", "/empty"]
    ]
    input_path.write_text(json.dumps(rows), encoding="utf-8")
    code = await asyncio.to_thread(
        auditor.main,
        [
            "--input",
            str(input_path),
            "--output",
            str(output_path),
            "--catalog",
            str(catalog),
            "--batch-size",
            "2",
            "--concurrency",
            "2",
            "--timeout",
            "2",
        ],
    )
    assert code == 0
    report = json.loads(output_path.read_text(encoding="utf-8"))
    assert report["summary"]["audited_urls"] == 3
    assert report["summary"]["healthy_urls"] == 1
    assert report["summary"]["failed_urls"] == 2
    assert report["summary"]["enabled_feeds"] == 1
    assert report["finished_at"] is not None
    assert len(load_sources(catalog)) == 1


@pytest_asyncio.fixture
async def github_feeds(local_feed, monkeypatch):
    module = sources_module()
    requests = []
    control = {"status": 200, "repos": ["alice/proxy-list", "bob/proxy-list"], "many": False}
    app = web.Application()

    async def search(request):
        requests.append(request.path)
        if control.get("search_delay"):
            import asyncio

            await asyncio.sleep(control["search_delay"])
        if control["status"] != 200:
            return web.json_response({"message": "public API rate limit"}, status=control["status"])
        if "payload" in control:
            return web.json_response(control["payload"])
        if control.get("invalid_json"):
            return web.Response(text="<html>challenge</html>")
        return web.json_response(
            {
                "items": [
                    {"full_name": repo, "default_branch": "main", "fork": False} for repo in control["repos"]
                ]
            }
        )

    async def tree(request):
        requests.append(request.path)
        if "tree_payload" in control:
            return web.json_response(control["tree_payload"])
        owner = request.match_info["owner"]
        paths = (
            ["http.txt", "socks5.txt", "empty.txt", "metadata.json"] if owner == "alice" else ["proxies.json"]
        )
        if control["many"]:
            paths = [f"http-{i}.txt" for i in range(100)]
        return web.json_response(
            {"tree": [{"type": "blob", "path": p, "size": 100} for p in paths], "truncated": False}
        )

    async def raw(request):
        requests.append(request.path)
        path = request.match_info["tail"]
        if path.endswith("empty.txt"):
            return web.Response(text="127.0.0.1:80\n")
        if path.endswith("metadata.json"):
            return web.json_response({"ip": "8.8.8.8", "port": 80})
        if path.endswith("proxies.json"):
            return web.json_response({"data": [{"ip": "1.1.1.1", "port": "1080", "protocols": ["socks4"]}]})
        return web.Response(text="8.8.8.8:8080\n")

    app.router.add_get("/search/repositories", search)
    app.router.add_get("/repos/{owner}/{repo}/git/trees/{branch}", tree)
    app.router.add_get("/raw/{tail:.*}", raw)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    base = f"http://feed-fixture.example:{port}"
    monkeypatch.setattr(module, "_GITHUB_API", base, raising=False)
    monkeypatch.setattr(module, "_GITHUB_RAW", base + "/raw", raising=False)
    try:
        yield base, requests, control
    finally:
        await runner.cleanup()


async def test_github_discovery_reads_trees_and_verifies_each_new_feed(github_feeds):
    from proxyharbor.models import SourceSpec

    base, requests, _ = github_feeds
    existing_url = base + "/raw/alice/proxy-list/main/http.txt"
    existing = [SourceSpec("old", "Existing", existing_url)]
    async with aiohttp.ClientSession(trust_env=False) as session:
        found = await sources_module().discover_github_sources(session, existing, max_repos=2)
    assert {(s.url, s.protocol, s.format) for s in found} == {
        (base + "/raw/alice/proxy-list/main/socks5.txt", "socks5", "text"),
        (base + "/raw/bob/proxy-list/main/proxies.json", "http", "json"),
    }
    assert all(s.enabled for s in found)
    assert len({s.id for s in found}) == len(found)
    assert "/raw/alice/proxy-list/main/http.txt" not in requests
    assert requests.count("/search/repositories") == 1


@pytest.mark.parametrize("status", [403, 429])
async def test_github_discovery_surfaces_api_rate_limits_without_retry_storms(github_feeds, status):
    _, requests, control = github_feeds
    control["status"] = status
    async with aiohttp.ClientSession(trust_env=False) as session:
        with pytest.raises(RuntimeError, match=f"GitHub.*{status}.*rate") as caught:
            await sources_module().discover_github_sources(session, [], max_repos=2)
    assert caught.value.status == status
    assert requests == ["/search/repositories"]


async def test_github_discovery_has_hard_repo_file_and_result_limits(github_feeds):
    _, requests, control = github_feeds
    control["repos"] = [f"publisher{i}/proxy-list" for i in range(80)]
    control["many"] = True
    async with aiohttp.ClientSession(trust_env=False) as session:
        found = await sources_module().discover_github_sources(session, [], max_repos=200)
    assert len(found) <= 60
    assert sum(path.startswith("/repos/") for path in requests) <= 20
    assert sum(path.startswith("/raw/") for path in requests) <= 80
    requests.clear()
    async with aiohttp.ClientSession(trust_env=False) as session:
        assert await sources_module().discover_github_sources(session, [], max_repos=0) == []
    assert requests == []
    for value in [-1, True, 2.5, "20"]:
        async with aiohttp.ClientSession(trust_env=False) as session:
            with pytest.raises(ValueError, match="max_repos"):
                await sources_module().discover_github_sources(session, [], max_repos=value)
    assert requests == []


@pytest.mark.parametrize(
    "change",
    [
        {"invalid_json": True},
        {"payload": []},
        {"payload": {"items": "unexpected"}},
        {"tree_payload": {"tree": "unexpected"}},
    ],
)
async def test_github_discovery_rejects_malformed_api_responses_cleanly(github_feeds, change):
    _, _, control = github_feeds
    control.update(change)
    async with aiohttp.ClientSession(trust_env=False) as session:
        with pytest.raises(RuntimeError, match="GitHub.*malformed"):
            await sources_module().discover_github_sources(session, [], max_repos=2)


@pytest.mark.parametrize("case", ["repos", "nodes", "forks"])
async def test_github_discovery_validates_identifiers_before_lookup(github_feeds, case):
    _, requests, control = github_feeds
    if case == "repos":
        control["payload"] = {
            "items": [
                None,
                {"full_name": "alice/../secret", "default_branch": "main"},
                {"full_name": "alice/proxy-list", "default_branch": ".."},
            ]
        }
    elif case == "forks":
        control["payload"] = {
            "items": [
                {"full_name": "alice/proxy-list", "default_branch": "main", "fork": True},
                {"full_name": "bob/proxy-list", "default_branch": "main", "archived": True},
            ]
        }
    else:
        control["repos"] = ["alice/proxy-list"]
        control["tree_payload"] = {
            "tree": [
                None,
                {"type": "blob", "path": 42},
                {"type": "blob", "path": "../http.txt", "size": 10},
                {"type": "blob", "path": "http.txt", "size": 5_000_001},
            ]
        }
    async with aiohttp.ClientSession(trust_env=False) as session:
        assert await sources_module().discover_github_sources(session, [], max_repos=20) == []
    assert not any(path.startswith("/raw/") for path in requests)
    if case != "nodes":
        assert requests == ["/search/repositories"]


async def test_github_discovery_has_a_total_deadline(github_feeds, monkeypatch):
    _, requests, control = github_feeds
    control["search_delay"] = 0.05
    monkeypatch.setattr(sources_module(), "_DISCOVERY_TIMEOUT", 0.01, raising=False)
    async with aiohttp.ClientSession(trust_env=False) as session:
        with pytest.raises(RuntimeError, match="GitHub discovery timeout"):
            await sources_module().discover_github_sources(session, [], max_repos=20)
    assert requests == ["/search/repositories"]
