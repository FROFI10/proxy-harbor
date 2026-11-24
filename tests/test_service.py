import asyncio
import time
from types import SimpleNamespace

from proxyharbor.config import Settings


class MemoryStorage:
    def __init__(self):
        self.candidates = {}
        self.results = []
        self.runs = []
        self.source_results = []

    async def add_candidates(self, candidates, source_id):
        added = 0
        for item in candidates:
            if item.key not in self.candidates:
                self.candidates[item.key] = item
                added += 1
        return added

    async def pending_candidates(self, limit=10000, recheck_after=600):
        return list(self.candidates.values())[:limit]

    async def save_results(self, results):
        self.results.extend(results)

    async def record_source_result(self, source_id, **data):
        self.source_results.append({"id": source_id, **data})

    async def save_run(self, data):
        self.runs.append(dict(data))

    async def prune(self, retention_days=3):
        return 0

    async def stats(self, freshness=600):
        return {"alive": sum(result.ok for result in self.results)}


def candidate(host, port=8080):
    return SimpleNamespace(host=host, port=port, protocol="http", key=f"http://{host}:{port}")


def result(item, ok=True):
    return SimpleNamespace(candidate=item, ok=ok, latency_ms=25.0, checked_at=time.time())


async def test_collection_persists_checks_and_reports_truthful_counters():
    from proxyharbor.service import ProxyService

    storage = MemoryStorage()
    source = SimpleNamespace(id="test-feed", name="Test", url="https://example.com/proxies", enabled=True,
                             protocol="http", format="text")
    candidates = [candidate("8.8.8.8"), candidate("1.1.1.1")]
    sessions = []

    async def fetcher(session, source, **options):
        sessions.append(session)
        return "fixture-feed"

    def parser(text, **options):
        assert text == "fixture-feed"
        return candidates

    class Checker:
        closed = False

        async def start(self):
            pass

        async def check(self, item):
            await asyncio.sleep(0.001)
            return result(item, item.host == "8.8.8.8")

        async def close(self):
            self.closed = True

    checker = Checker()
    service = ProxyService(storage, Settings(auto_collect=False), [source],
                           fetcher=fetcher, parser=parser, checker_factory=lambda **kw: checker)
    assert await service.start("collect") is True
    await service.wait_idle()
    snapshot = service.snapshot()
    assert snapshot["state"] == "idle"
    assert snapshot["running"] is False
    assert snapshot["parsed"] == 2
    assert snapshot["added"] == 2
    assert snapshot["checked"] == 2
    assert snapshot["working"] == 1
    assert snapshot["queue"] == 0
    assert snapshot["sources_done"] == 1
    assert len(storage.results) == 2
    assert storage.source_results[0]["error"] is None
    assert storage.runs[0]["status"] == "completed"
    assert checker.closed is True
    assert sessions[0].closed is True
    await service.close()


async def test_stop_before_task_starts_finalizes_cancelled_cycle():
    from proxyharbor.service import ProxyService

    storage = MemoryStorage()
    service = ProxyService(storage, Settings(auto_collect=False), [], fetcher=lambda *a, **k: None,
                           parser=lambda *a, **k: [])
    assert await service.start("collect") is True
    assert await service.start("collect") is False
    assert await service.stop() is True
    assert service.snapshot()["running"] is False
    assert service.snapshot()["state"] == "idle"
    assert len(storage.runs) == 1
    assert storage.runs[0]["status"] == "cancelled"
    assert await service.stop() is False
    await service.close()
    assert await service.start("collect") is False


async def test_auto_scheduler_collects_then_can_be_disabled():
    from proxyharbor.service import ProxyService

    completed = asyncio.Event()

    class Storage(MemoryStorage):
        async def save_run(self, data):
            await super().save_run(data)
            completed.set()

    storage = Storage()
    service = ProxyService(storage, Settings(auto_collect=True), [],
                           fetcher=lambda *a, **k: None, parser=lambda *a, **k: [])
    await service.start_scheduler()
    await asyncio.wait_for(completed.wait(), timeout=2)
    assert storage.runs[0]["mode"] == "collect"
    assert service.snapshot()["next_run_at"] > time.time()
    service.apply_settings(Settings(auto_collect=False))
    assert service.snapshot()["next_run_at"] is None
    await service.close()
    assert service._scheduler_task.done()


async def test_source_failures_and_empty_feeds_do_not_abort_other_sources():
    from proxyharbor.service import ProxyService

    storage = MemoryStorage()
    sources = [SimpleNamespace(id=name, name=name, url=f"https://example.com/{name}", enabled=True,
                               protocol="http", format="text") for name in ("bad", "empty", "good")]

    async def fetcher(session, source, **options):
        if source.id == "bad":
            raise OSError("HTTP 503 upstream")
        return source.id

    def parser(text, **options):
        return [] if text == "empty" else [candidate("8.8.8.8")]

    class Checker:
        async def start(self):
            pass

        async def close(self):
            pass

        async def check(self, item):
            return result(item)

    service = ProxyService(storage, Settings(auto_collect=False), sources, fetcher=fetcher, parser=parser,
                           checker_factory=lambda **kw: Checker())
    assert await service.start("collect")
    await service.wait_idle()
    snapshot = service.snapshot()
    assert snapshot["errors"] == 2
    assert snapshot["sources_done"] == 3
    assert snapshot["checked"] == 1
    recorded = {item["id"]: item for item in storage.source_results}
    assert recorded["empty"]["error"] is not None
    assert recorded["bad"]["error"] == "HTTP 503 upstream"
    assert recorded["good"]["error"] is None
    await service.close()



