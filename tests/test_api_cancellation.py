"""Controlled API cancellation and persistence, with real in-memory SQLite."""

import asyncio
import json
import threading
from contextlib import asynccontextmanager
from dataclasses import asdict, replace

import httpx
import pytest

from proxyharbor.app import create_app
from proxyharbor.config import Settings, load_settings, save_settings
from proxyharbor.models import SourceSpec
from proxyharbor.service import ProxyService
from proxyharbor.sources import load_sources, save_sources
from proxyharbor.storage import Storage


@asynccontextmanager
async def real_api(root, sources=(), *, raise_app_exceptions=True):
    storage = Storage(":memory:")
    settings = Settings(auto_collect=False)
    service = ProxyService(storage, settings, sources)
    application = create_app(root=root, settings=settings, storage=storage, service=service)
    transport = httpx.ASGITransport(app=application, client=("127.0.0.1", 51001),
                                   raise_app_exceptions=raise_app_exceptions)
    async with application.router.lifespan_context(application):
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8765") as client:
            yield client, storage, service, application
    assert storage._conn is None


@pytest.mark.asyncio
async def test_cancelled_settings_write_finishes_before_next_patch(tmp_path, monkeypatch):
    from proxyharbor import app as app_module

    storage = Storage(":memory:")
    settings = Settings(auto_collect=False)
    service = ProxyService(storage, settings, [])
    application = create_app(root=tmp_path, settings=settings, storage=storage, service=service)
    save_settings(tmp_path / "config.json", settings)
    loop = asyncio.get_running_loop()
    writer_entered = asyncio.Event()
    writer_finished = asyncio.Event()
    release_writer = threading.Event()
    settings_before_second_write = []
    real_save = save_settings

    def delayed_save(path, updated):
        if updated.check_concurrency == 37:
            loop.call_soon_threadsafe(writer_entered.set)
            if not release_writer.wait(5):
                raise TimeoutError("controlled writer was not released")
            try:
                real_save(path, updated)
            finally:
                loop.call_soon_threadsafe(writer_finished.set)
        else:
            settings_before_second_write.append(service.settings.check_concurrency)
            real_save(path, updated)

    monkeypatch.setattr(app_module, "save_settings", delayed_save)
    transport = httpx.ASGITransport(app=application, client=("127.0.0.1", 51001))
    async with application.router.lifespan_context(application):
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8765") as client:
            first = asyncio.create_task(client.patch("/api/settings", json={"check_concurrency": 37}))
            second = None
            try:
                await asyncio.wait_for(writer_entered.wait(), 5)
                first.cancel()
                # Let cancellation reach the route while the real OS writer is blocked.
                await asyncio.wait({first}, timeout=0.05)
                second = asyncio.create_task(client.patch("/api/settings", json={"check_concurrency": 72}))
                early_second, _ = await asyncio.wait({second}, timeout=0.1)
                lock_held = application.state.configuration_lock.locked()
                first_finished_early = first.done()
                first.cancel()  # Repeated cancellation must not abandon the worker either.
                release_writer.set()
                with pytest.raises(asyncio.CancelledError):
                    await first
                response = await asyncio.wait_for(second, 5)
                await asyncio.wait_for(writer_finished.wait(), 5)
                assert response.status_code == 200
                assert (await client.get("/api/settings")).json()["check_concurrency"] == 72
                assert load_settings(tmp_path / "config.json").check_concurrency == 72
                assert settings_before_second_write == [37]
                assert lock_held is True
                assert first_finished_early is False
                assert not early_second
            finally:
                release_writer.set()
                await asyncio.gather(*[task for task in (first, second) if task is not None],
                                     return_exceptions=True)


@pytest.mark.asyncio
async def test_cancelled_source_write_finishes_before_next_toggle(tmp_path, monkeypatch):
    from proxyharbor import sources as sources_module

    original = SourceSpec("feed", "Controlled registry fixture",
                          "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt")
    storage = Storage(":memory:")
    settings = Settings(auto_collect=False)
    service = ProxyService(storage, settings, [original])
    application = create_app(root=tmp_path, settings=settings, storage=storage, service=service)
    registry = tmp_path / "data" / "sources.json"
    save_sources(registry, [original])
    loop = asyncio.get_running_loop()
    writer_entered = asyncio.Event()
    writer_finished = asyncio.Event()
    release_writer = threading.Event()
    states_before_second_write = []

    def delayed_save(path, updated):
        if not updated[0].enabled:
            loop.call_soon_threadsafe(writer_entered.set)
            if not release_writer.wait(5):
                raise TimeoutError("controlled writer was not released")
            try:
                save_sources(path, updated)
            finally:
                loop.call_soon_threadsafe(writer_finished.set)
        else:
            states_before_second_write.append(service.sources[0].enabled)
            save_sources(path, updated)

    monkeypatch.setattr(sources_module, "save_sources", delayed_save)
    transport = httpx.ASGITransport(app=application, client=("127.0.0.1", 51001))
    async with application.router.lifespan_context(application):
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8765") as client:
            first = asyncio.create_task(client.patch("/api/sources/feed", json={"enabled": False}))
            second = None
            try:
                await asyncio.wait_for(writer_entered.wait(), 5)
                first.cancel()
                await asyncio.wait({first}, timeout=0.05)
                second = asyncio.create_task(client.patch("/api/sources/feed", json={"enabled": True}))
                early_second, _ = await asyncio.wait({second}, timeout=0.1)
                lock_held = application.state.configuration_lock.locked()
                first_finished_early = first.done()
                first.cancel()
                release_writer.set()
                with pytest.raises(asyncio.CancelledError):
                    await first
                response = await asyncio.wait_for(second, 5)
                await asyncio.wait_for(writer_finished.wait(), 5)
                assert response.status_code == 200
                assert (await client.get("/api/sources")).json()["items"][0]["enabled"] is True
                assert (await storage.list_sources())[0]["enabled"] is True
                assert load_sources(registry)[0].enabled is True
                assert states_before_second_write == [False]
                assert lock_held is True
                assert first_finished_early is False
                assert not early_second
            finally:
                release_writer.set()
                await asyncio.gather(*[task for task in (first, second) if task is not None],
                                     return_exceptions=True)


@pytest.mark.asyncio
async def test_source_json_failure_preserves_original_database_state(tmp_path, monkeypatch):
    from proxyharbor import sources as sources_module

    original = SourceSpec("feed", "Controlled registry fixture",
                          "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt")
    archived = SourceSpec("archived", "Disabled database history",
                          "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/socks4.txt",
                          protocol="socks4", enabled=False)
    storage = Storage(":memory:")
    settings = Settings(auto_collect=False)
    service = ProxyService(storage, settings, [original])
    application = create_app(root=tmp_path, settings=settings, storage=storage, service=service)
    registry = tmp_path / "data" / "sources.json"
    save_sources(registry, [original])
    file_before = registry.read_bytes()
    real_replace = sources_module.os.replace

    def fail_registry_replace(source, destination):
        if str(destination) == str(registry):
            raise PermissionError("controlled source JSON replacement failure")
        return real_replace(source, destination)

    transport = httpx.ASGITransport(app=application, client=("127.0.0.1", 51001))
    async with application.router.lifespan_context(application):
        await storage.upsert_sources([archived])
        await storage.record_source_result("feed", found=3, added=1, error="fixture diagnostic", elapsed_ms=12)
        database_before = await storage.list_sources()
        monkeypatch.setattr(sources_module.os, "replace", fail_registry_replace)
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8765") as client:
            response = await client.patch("/api/sources/feed", json={"enabled": False})
            assert response.status_code == 500
            assert (await client.get("/api/sources")).json()["items"][0]["enabled"] is True
            assert service.sources == [original]
            assert registry.read_bytes() == file_before
            assert await storage.list_sources() == database_before


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled", [True, False])
async def test_source_delete_json_failure_preserves_deletion_state(tmp_path, monkeypatch, enabled):
    from proxyharbor import sources as sources_module

    original = SourceSpec("feed", "Controlled registry fixture",
                          "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt",
                          enabled=enabled)
    registry = tmp_path / "data" / "sources.json"
    save_sources(registry, [original])
    file_before = registry.read_bytes()
    real_replace = sources_module.os.replace

    def fail_registry_replace(source, destination):
        if str(destination) == str(registry):
            raise PermissionError("controlled source JSON replacement failure")
        return real_replace(source, destination)

    async with real_api(tmp_path, [original]) as (client, storage, service, application):
        await storage.record_source_result("feed", found=3, added=1, error="fixture diagnostic", elapsed_ms=12)
        database_before = await storage.list_sources()
        monkeypatch.setattr(sources_module.os, "replace", fail_registry_replace)
        response = await client.delete("/api/sources/feed")
        assert response.status_code == 500
        assert (await client.get("/api/sources")).json()["items"][0]["enabled"] is enabled
        assert service.sources == [original]
        assert registry.read_bytes() == file_before
        assert await storage.list_sources() == database_before


@pytest.mark.asyncio
@pytest.mark.parametrize("had_registry", [True, False])
async def test_source_database_failure_rolls_back_file_and_metadata(tmp_path, monkeypatch, had_registry):
    original = SourceSpec("feed", "Controlled registry fixture",
                          "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt")
    registry = tmp_path / "data" / "sources.json"
    if had_registry:
        registry.parent.mkdir(parents=True)
        # Preserve the exact preimage, not merely save_sources' normalized encoding.
        registry.write_text(json.dumps([asdict(original)], separators=(",", ":")) + "\n\n", encoding="utf-8")
    file_before = registry.read_bytes() if had_registry else None

    async with real_api(tmp_path, [original]) as (client, storage, service, application):
        # The DB's previous metadata must be restored, even if RAM differs.
        stored_original = replace(original, name="Original SQLite metadata", protocol="socks4", format="json")
        await storage.upsert_sources([stored_original])
        await storage.record_source_result("feed", found=3, added=1, error="fixture diagnostic", elapsed_ms=12)
        database_before = await storage.list_sources()
        real_upsert = storage.upsert_sources

        async def fail_after_real_commit(updated):
            await real_upsert(updated)
            if any(spec.id == "feed" and not spec.enabled for spec in updated):
                raise OSError("controlled database acknowledgement failure")

        monkeypatch.setattr(storage, "upsert_sources", fail_after_real_commit)
        response = await client.patch("/api/sources/feed", json={"enabled": False})
        assert response.status_code == 500
        assert service.sources == [original]
        assert (registry.read_bytes() if registry.exists() else None) == file_before
        assert await storage.list_sources() == database_before
        assert (await client.get("/api/sources")).json()["items"][0]["enabled"] is True


@pytest.mark.asyncio
async def test_failed_source_creation_leaves_no_enabled_orphan(tmp_path, monkeypatch):
    registry = tmp_path / "data" / "sources.json"
    save_sources(registry, [])
    file_before = registry.read_bytes()
    async with real_api(tmp_path) as (client, storage, service, application):
        real_upsert = storage.upsert_sources

        async def fail_after_real_commit(updated):
            await real_upsert(updated)
            if updated:
                raise OSError("controlled database acknowledgement failure")

        monkeypatch.setattr(storage, "upsert_sources", fail_after_real_commit)
        response = await client.post("/api/sources", json={
            "name": "Controlled registry fixture",
            "url": "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt",
        })
        assert response.status_code == 500
        assert (await client.get("/api/sources")).json() == {"items": [], "total": 0}
        assert service.sources == []
        assert registry.read_bytes() == file_before
        database_rows = await storage.list_sources()
        # The fixed Storage interface cannot delete history rows; they must be inactive.
        assert database_rows
        assert not any(row["enabled"] for row in database_rows)


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["toggle", "delete"])
async def test_cancelled_source_rollback_holds_configuration_lock(tmp_path, monkeypatch, operation):
    original = SourceSpec("feed", "Controlled registry fixture",
                          "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt")
    registry = tmp_path / "data" / "sources.json"
    save_sources(registry, [original])
    file_before = registry.read_bytes()
    rollback_entered = asyncio.Event()
    release_rollback = asyncio.Event()
    failure_happened = False

    async with real_api(tmp_path, [original]) as (client, storage, service, application):
        await storage.record_source_result("feed", found=3, added=1, error="fixture diagnostic", elapsed_ms=12)
        database_before = await storage.list_sources()
        real_upsert = storage.upsert_sources
        real_set_enabled = storage.set_source_enabled

        async def controlled_upsert(updated):
            nonlocal failure_happened
            if failure_happened:
                rollback_entered.set()
                await release_rollback.wait()
            await real_upsert(updated)
            if operation == "toggle" and any(not spec.enabled for spec in updated):
                failure_happened = True
                raise OSError("controlled database acknowledgement failure")

        async def controlled_disable(source_id, enabled):
            nonlocal failure_happened
            result = await real_set_enabled(source_id, enabled)
            if operation == "delete" and not enabled and not failure_happened:
                failure_happened = True
                raise OSError("controlled deletion acknowledgement failure")
            return result

        monkeypatch.setattr(storage, "upsert_sources", controlled_upsert)
        monkeypatch.setattr(storage, "set_source_enabled", controlled_disable)
        first = asyncio.create_task(client.patch("/api/sources/feed", json={"enabled": False})
                                    if operation == "toggle" else client.delete("/api/sources/feed"))
        second = None
        try:
            await asyncio.wait_for(rollback_entered.wait(), 5)
            first.cancel()
            await asyncio.wait({first}, timeout=0.05)
            second = asyncio.create_task(client.patch("/api/settings", json={"check_concurrency": 72}))
            early_second, _ = await asyncio.wait({second}, timeout=0.1)
            lock_held = application.state.configuration_lock.locked()
            first_finished_early = first.done()
            first.cancel()
            release_rollback.set()
            with pytest.raises(asyncio.CancelledError):
                await first
            assert (await asyncio.wait_for(second, 5)).status_code == 200
            assert not early_second
            assert lock_held is True
            assert first_finished_early is False
            assert service.sources == [original]
            assert registry.read_bytes() == file_before
            assert await storage.list_sources() == database_before
            assert (await client.get("/api/sources")).json()["items"][0]["enabled"] is True
            assert load_settings(tmp_path / "config.json").check_concurrency == 72
        finally:
            release_rollback.set()
            await asyncio.gather(*[task for task in (first, second) if task is not None], return_exceptions=True)


@pytest.mark.asyncio
async def test_failed_metadata_rollback_still_disables_new_source(tmp_path, monkeypatch):
    original = SourceSpec("feed", "Controlled registry fixture",
                          "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt")
    registry = tmp_path / "data" / "sources.json"
    save_sources(registry, [original])
    file_before = registry.read_bytes()
    async with real_api(tmp_path, [original], raise_app_exceptions=False) as (client, storage, service, application):
        real_upsert = storage.upsert_sources

        async def controlled_upsert(updated):
            if len(updated) > 1:
                await real_upsert(updated)
                raise OSError("controlled database acknowledgement failure")
            raise OSError("controlled rollback metadata failure")

        monkeypatch.setattr(storage, "upsert_sources", controlled_upsert)
        response = await client.post("/api/sources", json={
            "name": "New controlled registry fixture",
            "url": "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/socks4.txt",
            "protocol": "socks4",
        })
        assert response.status_code == 500
        assert isinstance(response.json()["detail"], str)
        assert service.sources == [original]
        assert registry.read_bytes() == file_before
        database_rows = await storage.list_sources()
        new_rows = [row for row in database_rows if row["id"] != original.id]
        assert new_rows
        assert not any(row["enabled"] for row in new_rows)
