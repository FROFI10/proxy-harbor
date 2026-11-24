import logging
import time

import pytest
from fastapi.testclient import TestClient

from proxyharbor.config import Settings
from proxyharbor.service import ProxyService


class ApiStorage:
    def __init__(self):
        self.rows = []
        self.closed = False
        self.issued = 0
        self.sources = []
        self.runs = []

    async def open(self):
        pass

    async def close(self):
        self.closed = True

    async def upsert_sources(self, sources):
        self.sources = list(sources)

    async def list_sources(self):
        from dataclasses import asdict
        return [asdict(spec) for spec in self.sources]

    async def set_source_enabled(self, source_id, enabled):
        from dataclasses import replace
        self.sources = [replace(spec, enabled=enabled) if spec.id == source_id else spec for spec in self.sources]
        return True

    async def stats(self, freshness=600):
        return {"total": len(self.rows), "alive": len(self.rows), "pending": 0, "dead": 0, "stale": 0,
                "https": 0, "average_latency_ms": None, "protocols": {"http": 0, "socks4": 0, "socks5": 0},
                "requests": self.issued, "sources_total": len(self.sources), "sources_enabled": len(self.sources),
                "last_check": None}

    async def get_proxies(self, limit=1, **filters):
        self.issued += min(limit, len(self.rows))
        return self.rows[:limit]

    async def list_proxies(self, limit=50, offset=0, **filters):
        return {"items": self.rows[offset:offset + limit], "total": len(self.rows)}

    async def report_proxy(self, proxy_id, ok):
        if not any(item["id"] == proxy_id for item in self.rows):
            return False
        if not ok:
            self.rows = [item for item in self.rows if item["id"] != proxy_id]
        return True

    async def add_candidates(self, candidates, source_id):
        if not hasattr(self, "imported"):
            self.imported = {}
        added = 0
        for candidate in candidates:
            if candidate.key not in self.imported:
                self.imported[candidate.key] = candidate
                added += 1
        return added

    async def pending_candidates(self, limit=10000, recheck_after=600):
        return []

    async def prune(self, retention_days=3):
        return 0

    async def save_run(self, data):
        self.runs.append(data)

    async def list_runs(self, limit=20):
        return self.runs[-limit:]


def row():
    return {"id": 1, "host": "8.8.8.8", "port": 8080, "protocol": "http", "url": "http://8.8.8.8:8080",
            "address": "8.8.8.8:8080", "status": "alive", "latency_ms": 25.0, "supports_https": True,
            "exit_ip": "1.1.1.1", "last_checked": time.time()}


@pytest.fixture
def api(tmp_path):
    from proxyharbor.app import create_app

    storage = ApiStorage()
    settings = Settings(auto_collect=False)
    service = ProxyService(storage, settings, [], fetcher=lambda *a, **k: None, parser=lambda *a, **k: [])
    application = create_app(root=tmp_path, settings=settings, storage=storage, service=service)
    with TestClient(application, base_url="http://127.0.0.1:8765", client=("127.0.0.1", 51001)) as client:
        yield client, storage, application
    assert storage.closed


def test_health_stats_and_openapi_are_served_by_a_local_api(api):
    client, storage, application = api
    health = client.get("/health")
    assert health.status_code == 200
    assert health.json() == {"status": "ok", "version": "1.0.0"}
    assert health.headers["x-content-type-options"] == "nosniff"
    stats = client.get("/api/stats")
    assert stats.status_code == 200
    assert stats.json()["alive"] == 0
    assert stats.json()["service"]["running"] is False
    assert client.get("/openapi.json").status_code == 200


def test_proxy_endpoint_returns_503_or_a_proxy_in_requested_format(api):
    client, storage, application = api
    missing = client.get("/api/proxy")
    assert missing.status_code == 503
    assert "detail" in missing.json()
    storage.rows = [row()]
    response = client.get("/api/proxy?strategy=best&https_only=true")
    assert response.status_code == 200
    assert response.json()["url"] == "http://8.8.8.8:8080"
    assert response.json()["proxy"] == response.json()["url"]
    assert client.get("/api/proxy?format=text").text == "http://8.8.8.8:8080\n"
    assert client.get("/api/proxy?format=address").text == "8.8.8.8:8080\n"
    assert client.get("/api/proxy?protocol=ftp").status_code == 422
    assert client.get("/api/proxy?strategy=invalid").status_code == 422
    assert storage.issued == 3


def test_proxy_listing_export_and_batch_have_honest_counts(api):
    client, storage, application = api
    storage.rows = [row()]
    listing = client.get("/api/proxies?limit=1&offset=0&status=alive&sort=latency")
    assert listing.status_code == 200
    assert listing.json()["total"] == 1
    assert listing.json()["limit"] == 1
    assert len(listing.json()["items"]) == 1
    exported = client.get("/api/proxies/export?format=text&limit=1000")
    assert exported.text == "http://8.8.8.8:8080\n"
    assert "attachment" in exported.headers["content-disposition"]
    assert storage.issued == 0
    batch = client.get("/api/proxies/batch?count=3")
    assert batch.status_code == 200
    assert batch.json()["requested"] == 3
    assert batch.json()["count"] == len(batch.json()["items"]) == 1
    assert storage.issued == 1
    assert client.get("/api/proxies?limit=0").status_code == 422
    assert client.get("/api/proxies?sort=injection").status_code == 422
    assert client.get("/api/proxies/batch?count=1001").status_code == 422


@pytest.mark.parametrize(
    "headers, expected",
    [
        ({"Host": "attacker.example:8765"}, 421),
        ({"Origin": "https://attacker.example"}, 403),
        ({"Origin": "http://127.0.0.1:9999"}, 403),
        ({"Sec-Fetch-Site": "cross-site"}, 403),
    ],
)
def test_local_api_rejects_rebinding_and_cross_origin_requests(api, headers, expected):
    client, storage, application = api
    assert client.get("/api/stats", headers=headers).status_code == expected


def test_local_api_limits_request_body_before_parsing(api):
    client, storage, application = api
    response = client.post("/api/import", content=b"x" * 2_000_001,
                           headers={"Content-Type": "application/json"})
    assert response.status_code == 413
    assert "detail" in response.json()


def test_settings_patch_is_validated_persisted_and_read_back(api):
    client, storage, application = api
    initial = client.get("/api/settings")
    assert initial.status_code == 200
    assert initial.json()["check_concurrency"] == 120
    changed = client.patch("/api/settings", json={"check_concurrency": 72, "auto_collect": False})
    assert changed.status_code == 200
    assert changed.json()["check_concurrency"] == 72
    assert client.get("/api/settings").json()["check_concurrency"] == 72
    from proxyharbor.config import load_settings
    assert load_settings(application.state.root / "config.json").check_concurrency == 72
    assert client.patch("/api/settings", json={"check_concurrency": 0}).status_code == 422
    assert client.patch("/api/settings", json={"password": "not-allowed"}).status_code == 422
    assert client.get("/api/settings").json()["check_concurrency"] == 72


def test_cycle_controls_and_run_history_are_exposed(api):
    client, storage, application = api
    collected = client.post("/api/collect")
    assert collected.status_code == 200
    assert isinstance(collected.json()["started"], bool)
    assert collected.json()["message"]
    stopped = client.post("/api/stop")
    assert stopped.status_code == 200
    assert isinstance(stopped.json()["stopped"], bool)
    rechecked = client.post("/api/recheck")
    assert rechecked.status_code == 200
    assert "started" in rechecked.json()
    client.post("/api/stop")
    runs = client.get("/api/runs")
    assert runs.status_code == 200
    assert runs.json()["total"] == len(runs.json()["items"])
    assert client.get("/api/runs?limit=0").status_code == 422


def test_source_crud_is_persisted_and_read_back(api):
    client, storage, application = api
    initial = client.get("/api/sources")
    assert initial.status_code == 200
    assert initial.json() == {"items": [], "total": 0}
    payload = {"name": "My public source", "url": "https://example.com/public-proxies.txt",
               "protocol": "socks5", "format": "text", "enabled": True}
    created = client.post("/api/sources", json=payload)
    assert created.status_code == 201
    identifier = created.json()["id"]
    listing = client.get("/api/sources").json()
    assert listing["total"] == len(listing["items"]) == 1
    assert listing["items"][0]["url"] == payload["url"]
    assert client.post("/api/sources", json=payload).status_code == 409
    toggled = client.patch(f"/api/sources/{identifier}", json={"enabled": False})
    assert toggled.status_code == 200
    assert client.get("/api/sources").json()["items"][0]["enabled"] is False
    from proxyharbor.sources import load_sources
    registry = application.state.root / "data" / "sources.json"
    assert load_sources(registry)[0].enabled is False
    assert client.post("/api/sources", json={**payload, "url": "http://127.0.0.1/"}).status_code == 422
    assert client.delete(f"/api/sources/{identifier}").status_code == 200
    assert client.get("/api/sources").json()["total"] == 0
    assert load_sources(registry) == []
    assert client.delete(f"/api/sources/{identifier}").status_code == 404


def test_manual_import_deduplicates_but_never_marks_candidates_alive(api):
    client, storage, application = api
    payload = {"text": "8.8.8.8:8080\n8.8.8.8:8080\n1.1.1.1:3128\n127.0.0.1:9999", "protocol": "http"}
    imported = client.post("/api/import", json=payload)
    assert imported.status_code == 200
    assert imported.json() == {"parsed": 2, "added": 2}
    assert client.post("/api/import", json=payload).json()["added"] == 0
    assert client.get("/api/proxy").status_code == 503
    assert client.post("/api/import", json={"text": "10.0.0.1:1080", "protocol": "socks5"}).status_code == 422
    assert client.post("/api/import", json={"text": "8.8.8.8:8080", "protocol": "ftp"}).status_code == 422


def test_client_report_can_invalidate_proxy_without_forging_a_check(api):
    client, storage, application = api
    storage.rows = [row()]
    assert client.get("/api/proxy").status_code == 200
    report = client.post("/api/proxies/1/report", json={"ok": False})
    assert report.status_code == 200
    assert report.json() == {"ok": True}
    assert client.get("/api/proxy").status_code == 503
    assert client.post("/api/proxies/999/report", json={"ok": True}).status_code == 404
    assert client.post("/api/proxies/1/report", json={"ok": "yes"}).status_code == 422
    assert client.post("/api/proxies/0/report", json={"ok": False}).status_code == 422


def test_discovery_adds_only_new_sources_and_surfaces_rate_limits(api, monkeypatch):
    from proxyharbor import sources
    from proxyharbor.models import SourceSpec

    client, storage, application = api

    async def discover(session, existing, max_repos=20):
        assert session.trust_env is False
        return [SourceSpec("discovered", "Discovered", "https://example.com/discovered.txt")]

    monkeypatch.setattr(sources, "discover_github_sources", discover, raising=False)
    found = client.post("/api/sources/discover")
    assert found.status_code == 200
    assert found.json()["added"] == 1
    assert client.get("/api/sources").json()["total"] == 1
    assert client.post("/api/sources/discover").json()["added"] == 0

    async def rate_limited(*args, **kwargs):
        raise RuntimeError("GitHub HTTP 403 rate limit")

    monkeypatch.setattr(sources, "discover_github_sources", rate_limited)
    limited = client.post("/api/sources/discover")
    assert limited.status_code == 502
    assert "403" in limited.json()["detail"]
    assert client.get("/api/sources").json()["total"] == 1


def test_dashboard_and_api_documentation_use_local_assets(api):
    client, storage, application = api
    dashboard = client.get("/")
    assert dashboard.status_code == 200
    assert "Proxy Harbor" in dashboard.text
    assert client.get("/static/app.css").status_code == 200
    assert client.get("/static/app.js").status_code == 200
    docs = client.get("/docs")
    assert docs.status_code == 200
    assert "cdn.jsdelivr.net" not in docs.text
    assert "/static/vendor/swagger-ui-bundle.js" in docs.text
    assert client.get("/static/vendor/swagger-ui-bundle.js").status_code == 200
    assert client.get("/static/vendor/swagger-ui.css").status_code == 200
    assert client.get("/favicon.ico").status_code == 204


def test_failed_startup_closes_an_already_opened_database(tmp_path):
    from proxyharbor.app import create_app

    storage = ApiStorage()
    (tmp_path / "sources.json").write_text("not-json", encoding="utf-8")
    application = create_app(root=tmp_path, settings=Settings(auto_collect=False), storage=storage)
    with pytest.raises(ValueError, match="JSON"):
        with TestClient(application, base_url="http://127.0.0.1:8765", client=("127.0.0.1", 51001)):
            pytest.fail("invalid source registry should prevent startup")
    assert storage.closed is True


@pytest.mark.parametrize("ok", [True, False])
def test_proxy_report_rejects_ids_outside_signed_64_bit_range(tmp_path, ok):
    from proxyharbor.app import create_app
    from proxyharbor.storage import Storage

    storage = Storage(":memory:")
    settings = Settings(auto_collect=False)
    service = ProxyService(storage, settings, [])
    application = create_app(root=tmp_path, settings=settings, storage=storage, service=service)
    with TestClient(application, base_url="http://127.0.0.1:8765", client=("127.0.0.1", 51001),
                    raise_server_exceptions=False) as client:
        response = client.post("/api/proxies/9223372036854775808/report", json={"ok": ok})
        assert response.status_code == 422
        for identifier in ("1", "9223372036854775807"):
            missing = client.post(f"/api/proxies/{identifier}/report", json={"ok": ok})
            assert missing.status_code == 404
            assert isinstance(missing.json()["detail"], str)


@pytest.fixture
def real_api_client(tmp_path):
    from proxyharbor.app import create_app
    from proxyharbor.storage import Storage

    storage = Storage(":memory:")
    settings = Settings(auto_collect=False)
    service = ProxyService(storage, settings, [])
    application = create_app(root=tmp_path, settings=settings, storage=storage, service=service)
    with TestClient(application, base_url="http://127.0.0.1:8765", client=("127.0.0.1", 51001),
                    raise_server_exceptions=False) as client:
        yield client, storage, application
    assert storage._conn is None


@pytest.mark.parametrize("method, url, body", [
    ("GET", "/api/proxies?limit=API_SECRET", None),
    ("POST", "/api/proxies/1/report", {"ok": "API_SECRET"}),
    ("POST", "/api/sources", {"name": "Fixture", "url": "https://user:API_SECRET@example.com"}),
    ("PATCH", "/api/settings", {"password": "API_SECRET"}),
    ("PATCH", "/api/settings", {"http_probe_url": "http://user:API_SECRET@api.ipify.org"}),
])
def test_validation_errors_are_safe_json_strings(real_api_client, method, url, body):
    client, storage, application = real_api_client
    response = client.request(method, url, json=body) if body is not None else client.request(method, url)
    assert response.status_code == 422
    assert set(response.json()) == {"detail"}
    assert isinstance(response.json()["detail"], str)
    assert response.json()["detail"]
    assert "API_SECRET" not in response.text


def test_unhandled_database_error_is_safe_json_and_sanitized_log(real_api_client, monkeypatch, caplog):
    client, storage, application = real_api_client
    real_stats = storage.stats

    async def broken_stats(**kwargs):
        await real_stats(**kwargs)
        # Produce a real SQLite error containing a controlled private marker.
        await storage._connection().execute("SELECT * FROM API_SECRET")

    monkeypatch.setattr(storage, "stats", broken_stats)
    caplog.set_level(logging.ERROR, logger="proxyharbor.api")
    response = client.get("/api/stats?token=API_SECRET")
    assert response.status_code == 500
    assert response.headers["content-type"].startswith("application/json")
    assert set(response.json()) == {"detail"}
    assert isinstance(response.json()["detail"], str)
    assert response.json()["detail"]
    assert "API_SECRET" not in response.text
    assert "no such table" not in response.text
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    records = [record for record in caplog.records if record.name == "proxyharbor.api"]
    assert records
    assert any("OperationalError" in record.getMessage() for record in records)
    assert all(record.exc_info is None for record in records)
    assert "API_SECRET" not in caplog.text


@pytest.mark.parametrize("failure_kind, expected", [
    ("settings-io", 500), ("sources-io", 500), ("sources-validation", 422),
])
def test_persistence_errors_do_not_expose_diagnostics(real_api_client, monkeypatch, caplog,
                                                    failure_kind, expected):
    from dataclasses import replace

    from proxyharbor import app as app_module
    from proxyharbor import sources as sources_module
    from proxyharbor.config import save_settings

    client, storage, application = real_api_client
    if failure_kind == "settings-io":
        target = application.state.root / "config.json"
        save_settings(target, application.state.service.settings)
        method, url, body = "PATCH", "/api/settings", {"check_concurrency": 37}
    else:
        target = application.state.root / "data" / "sources.json"
        sources_module.save_sources(target, [])
        method, url, body = "POST", "/api/sources", {
            "name": "Controlled registry fixture",
            "url": "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt",
        }
    file_before = target.read_bytes()
    real_replace = app_module.os.replace

    def fail_target_replace(source, destination):
        if str(destination) == str(target):
            raise PermissionError("controlled IO diagnostic: API_SECRET")
        return real_replace(source, destination)

    if failure_kind == "sources-validation":
        real_save = sources_module.save_sources

        def validation_failure(path, updated):
            invalid = [*updated[:-1], replace(updated[-1], url="http://example.com:API_SECRET")]
            real_save(path, invalid)

        monkeypatch.setattr(sources_module, "save_sources", validation_failure)
    else:
        monkeypatch.setattr(app_module.os, "replace", fail_target_replace)
    caplog.set_level(logging.ERROR, logger="proxyharbor.api")
    response = client.request(method, url, json=body)
    assert response.status_code == expected
    assert set(response.json()) == {"detail"}
    assert isinstance(response.json()["detail"], str)
    assert "API_SECRET" not in response.text
    assert "API_SECRET" not in caplog.text
    assert target.read_bytes() == file_before
    assert client.get("/api/settings").json()["check_concurrency"] == 120
    assert client.get("/api/sources").json() == {"items": [], "total": 0}
    assert client.portal.call(storage.list_sources) == []
    if expected == 500:
        records = [record for record in caplog.records if record.name == "proxyharbor.api"]
        assert records
        assert all(record.exc_info is None for record in records)


@pytest.mark.parametrize("failure_stage", ["upsert", "scheduler", "service-close", "storage-close", "upsert-and-close"])
def test_lifespan_failures_still_close_real_storage(tmp_path, monkeypatch, failure_stage):
    from proxyharbor.app import create_app
    from proxyharbor.storage import Storage

    storage = Storage(":memory:")
    settings = Settings(auto_collect=False)
    service = ProxyService(storage, settings, [])
    application = create_app(root=tmp_path, settings=settings, storage=storage, service=service)
    events = []
    real_upsert = storage.upsert_sources
    real_scheduler = service.start_scheduler
    real_service_close = service.close
    real_storage_close = storage.close

    async def failed_upsert(sources):
        await real_upsert(sources)
        raise OSError("controlled upsert failure")

    async def failed_scheduler():
        await real_scheduler()
        raise OSError("controlled scheduler failure")

    async def service_close():
        events.append("service-close")
        await real_service_close()
        if failure_stage in {"service-close", "upsert-and-close"}:
            raise OSError("controlled service close failure")

    async def storage_close():
        events.append("storage-close")
        await real_storage_close()
        if failure_stage == "storage-close":
            raise OSError("controlled storage close failure")

    if failure_stage in {"upsert", "upsert-and-close"}:
        monkeypatch.setattr(storage, "upsert_sources", failed_upsert)
    if failure_stage == "scheduler":
        monkeypatch.setattr(service, "start_scheduler", failed_scheduler)
    monkeypatch.setattr(service, "close", service_close)
    monkeypatch.setattr(storage, "close", storage_close)
    with pytest.raises(OSError, match="controlled .* failure"):
        with TestClient(application, base_url="http://127.0.0.1:8765", client=("127.0.0.1", 51001)) as client:
            assert failure_stage in {"service-close", "storage-close"}
            assert client.get("/health").status_code == 200
    assert events == ["service-close", "storage-close"]
    assert storage._conn is None
    if service._scheduler_task is not None:
        assert service._scheduler_task.done()


def test_error_contract_preserves_validation_missing_and_unavailable_statuses(real_api_client):
    client, storage, application = real_api_client
    responses = [
        (client.get("/api/proxies?limit=0"), 422),
        (client.post("/api/proxies/1/report", content="{", headers={"Content-Type": "application/json"}), 422),
        (client.post("/api/proxies/1/report", json={"ok": True}), 404),
        (client.delete("/api/sources/missing"), 404),
        (client.get("/not-found"), 404),
        (client.get("/api/proxy"), 503),
        (client.get("/api/proxies/batch"), 503),
    ]
    for response, expected in responses:
        assert response.status_code == expected
        assert set(response.json()) == {"detail"}
        assert isinstance(response.json()["detail"], str)
        assert response.json()["detail"]
        if expected == 503:
            assert response.headers["retry-after"] == "15"


