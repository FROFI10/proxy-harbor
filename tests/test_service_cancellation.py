"""Controlled service lifecycle regressions using the real SQLite storage."""

import asyncio
from types import SimpleNamespace

import pytest

from proxyharbor.config import Settings
from proxyharbor.models import CHECK_VALIDATION_VERSION, CheckResult, ProxyCandidate
from proxyharbor.service import ProxyService
from proxyharbor.storage import Storage


@pytest.fixture
async def storage():
    database = Storage(":memory:")
    await database.open()
    try:
        yield database
    finally:
        await database.close()


@pytest.fixture
def held_commit(storage, monkeypatch):
    gate = SimpleNamespace(reached=asyncio.Event(), release=asyncio.Event(), cancelled=False)
    commit = storage._connection().commit

    async def delay_first_commit_return():
        await commit()  # The actual SQLite COMMIT has already succeeded.
        if not gate.reached.is_set():
            gate.reached.set()
            try:
                await gate.release.wait()
            except asyncio.CancelledError:
                gate.cancelled = True
                raise

    def arm():
        monkeypatch.setattr(storage._connection(), "commit", delay_first_commit_return)

    gate.arm = arm
    return gate


class FailedChecker:
    """Network-free checks still pass real result values to SQLite."""

    async def start(self):
        pass

    async def check(self, candidate):
        return CheckResult(candidate, False, error="fixture refused")

    async def close(self):
        pass


async def test_checker_close_error_finalizes_failed_cycle(storage):
    class CloseErrorChecker(FailedChecker):
        async def close(self):
            raise OSError("checker cleanup failed")

    await storage.add_candidates([ProxyCandidate("8.8.8.8", 8080, "http")], "fixture")
    service = ProxyService(storage, Settings(auto_collect=False), [],
                           checker_factory=lambda **kwargs: CloseErrorChecker())
    try:
        assert await service.start("recheck")
        outcome = await asyncio.gather(service.wait_idle(), return_exceptions=True)
        snapshot = service.snapshot()
        assert snapshot["running"] is False
        assert snapshot["finished_at"] is not None
        assert snapshot["state"] == "error"
        assert snapshot["errors"] == 1
        assert "checker cleanup failed" in snapshot["last_error"]
        assert any("checker cleanup failed" in item["message"] for item in snapshot["logs"])
        runs = await storage.list_runs()
        assert len(runs) == 1
        assert runs[0]["status"] == "failed"
        assert runs[0]["errors"] == 1
        assert runs[0]["checked"] == snapshot["checked"] == 1
        assert runs[0]["finished_at"] == snapshot["finished_at"]
        assert outcome == [None]
        assert service._task.done()
        assert await service.stop() is False
    finally:
        await service.close()


async def test_cancel_after_sqlite_commit_counts_each_check_once(storage, held_commit):
    candidates = [ProxyCandidate("8.8.8.8", 8000 + index, "http") for index in range(32)]
    assert await storage.add_candidates(candidates, "fixture") == len(candidates)
    held_commit.arm()
    service = ProxyService(storage, Settings(auto_collect=False, check_concurrency=2), [],
                           checker_factory=lambda **kwargs: FailedChecker())
    stopper = None
    try:
        assert await service.start("recheck")
        await asyncio.wait_for(held_commit.reached.wait(), timeout=2)
        writer = next(task for task in asyncio.all_tasks() if task.get_name() == "proxyharbor-db-writer")
        stopper = asyncio.create_task(service.stop())

        async def cancellation_reaches_writer():
            while not writer.cancelling():
                await asyncio.sleep(0)
            await asyncio.sleep(0)  # Deliver the requested cancellation at the held COMMIT.

        await asyncio.wait_for(cancellation_reaches_writer(), timeout=2)
        held_commit.release.set()
        assert await asyncio.wait_for(stopper, timeout=2) is True
        page = await storage.list_proxies(status="all", limit=100)
        assert page["total"] == len(page["items"]) == len(candidates)
        assert {row["url"] for row in page["items"]} == {item.url for item in candidates}
        assert {row["failures"] for row in page["items"]} == {1}, service.snapshot()
        assert all(row["successes"] == 0 for row in page["items"])
        assert held_commit.cancelled is False
        snapshot = service.snapshot()
        assert snapshot["checked"] == len(candidates)
        assert snapshot["working"] == 0
        assert snapshot["running"] is False
        runs = await storage.list_runs()
        assert len(runs) == 1
        assert runs[0]["status"] == "cancelled"
        assert runs[0]["checked"] == len(candidates)
        assert not [task for task in asyncio.all_tasks()
                    if task.get_name().startswith("proxyharbor-") and not task.done()]
    finally:
        held_commit.release.set()
        if stopper is not None:
            await asyncio.gather(stopper, return_exceptions=True)
        await service.close()


@pytest.mark.parametrize("candidate_count", [32, 36, 37, 38])
async def test_repeated_writer_cancellation_preserves_completed_sqlite_results(storage, held_commit,
                                                                              candidate_count):
    protocols = ("http", "socks4", "socks5")
    candidates = [ProxyCandidate("8.8.8.8", 8000 + index, protocols[index % 3]) for index in range(candidate_count)]
    produced = {}
    all_checked = asyncio.Event()

    class MixedChecker(FailedChecker):
        async def check(self, candidate):
            ok = candidate.port % 2 == 0
            checked = CheckResult(candidate, ok, latency_ms=25.0 if ok else None,
                                  supports_https=ok and candidate.port % 3 == 0,
                                  exit_ip="1.1.1.1" if ok else None,
                                  validation_version=CHECK_VALIDATION_VERSION)
            produced[candidate.url] = checked
            if len(produced) == len(candidates):
                all_checked.set()
            return checked

    assert await storage.add_candidates(candidates, "fixture") == len(candidates)
    held_commit.arm()
    service = ProxyService(storage, Settings(auto_collect=False, check_concurrency=2), [],
                           checker_factory=lambda **kwargs: MixedChecker())
    stopper = None
    try:
        assert await service.start("recheck")
        await asyncio.wait_for(held_commit.reached.wait(), timeout=2)
        await asyncio.wait_for(all_checked.wait(), timeout=2)
        writer = next(task for task in asyncio.all_tasks() if task.get_name() == "proxyharbor-db-writer")
        stopper = asyncio.create_task(service.stop())

        async def cancel_repeatedly():
            while not writer.cancelling():
                await asyncio.sleep(0)
            await asyncio.sleep(0)
            for _ in range(2):
                writer.cancel()
                await asyncio.sleep(0)

        await asyncio.wait_for(cancel_repeatedly(), timeout=2)
        held_commit.release.set()
        assert await asyncio.wait_for(stopper, timeout=2) is True
        snapshot = service.snapshot()
        page = await storage.list_proxies(status="all", limit=100)
        assert snapshot["checked"] == len(produced) == len(candidates), {
            "produced": len(produced),
            "sqlite_checked": sum(row["successes"] + row["failures"] for row in page["items"]),
            "pending": [row["url"] for row in page["items"] if row["status"] == "pending"],
        }
        assert snapshot["working"] == sum(item.ok for item in produced.values())
        assert held_commit.cancelled is False
        assert page["total"] == len(page["items"]) == len(candidates)
        assert {row["url"] for row in page["items"]} == set(produced)
        for row in page["items"]:
            checked = produced[row["url"]]
            assert (row["successes"], row["failures"]) == (int(checked.ok), int(not checked.ok))
            assert row["latency_ms"] == checked.latency_ms
            assert row["supports_https"] == checked.supports_https
            assert row["exit_ip"] == checked.exit_ip
            assert row["last_checked"] == checked.checked_at
        runs = await storage.list_runs()
        assert len(runs) == 1
        assert runs[0]["status"] == "cancelled"
        assert runs[0]["checked"] == snapshot["checked"]
        assert runs[0]["working"] == snapshot["working"]
        assert snapshot["running"] is False
        assert snapshot["queue"] == 0
        assert not [task for task in asyncio.all_tasks()
                    if task.get_name().startswith("proxyharbor-") and not task.done()]
    finally:
        held_commit.release.set()
        if stopper is not None:
            await asyncio.gather(stopper, return_exceptions=True)
        await service.close()


async def test_repeated_cycle_cancellation_waits_for_checker_cleanup(storage):
    checking = asyncio.Event()
    closing = asyncio.Event()
    release_close = asyncio.Event()
    close_cancelled = False
    closed = False

    class GatedChecker(FailedChecker):
        async def check(self, candidate):
            checking.set()
            await asyncio.Event().wait()

        async def close(self):
            nonlocal close_cancelled, closed
            closing.set()
            try:
                await release_close.wait()
                closed = True
            except asyncio.CancelledError:
                close_cancelled = True
                raise

    await storage.add_candidates([ProxyCandidate("8.8.8.8", 8080, "http")], "fixture")
    service = ProxyService(storage, Settings(auto_collect=False), [],
                           checker_factory=lambda **kwargs: GatedChecker())
    stopper = None
    try:
        assert await service.start("recheck")
        await asyncio.wait_for(checking.wait(), timeout=2)
        stopper = asyncio.create_task(service.stop())
        await asyncio.wait_for(closing.wait(), timeout=2)
        for _ in range(2):
            service._task.cancel()
            await asyncio.sleep(0)
        release_close.set()
        assert await asyncio.wait_for(stopper, timeout=2) is True
        assert close_cancelled is False
        assert closed is True
        snapshot = service.snapshot()
        assert snapshot["running"] is False
        assert snapshot["finished_at"] is not None
        runs = await storage.list_runs()
        assert len(runs) == 1
        assert runs[0]["status"] == "cancelled"
        assert runs[0]["checked"] == 0
        assert runs[0]["finished_at"] == snapshot["finished_at"]
        assert not [task for task in asyncio.all_tasks()
                    if task.get_name().startswith("proxyharbor-") and not task.done()]
    finally:
        release_close.set()
        if stopper is not None:
            await asyncio.gather(stopper, return_exceptions=True)
        await service.close()


async def test_checker_cleanup_timeout_finalizes_failed_stop(storage, monkeypatch):
    checking = asyncio.Event()
    closing = asyncio.Event()
    release_close = asyncio.Event()
    close_cancelled = False

    class HungCloseChecker(FailedChecker):
        async def check(self, candidate):
            checking.set()
            await asyncio.Event().wait()

        async def close(self):
            nonlocal close_cancelled
            closing.set()
            try:
                await release_close.wait()
            except asyncio.CancelledError:
                close_cancelled = True
                raise

    await storage.add_candidates([ProxyCandidate("8.8.8.8", 8080, "http")], "fixture")
    service = ProxyService(storage, Settings(auto_collect=False), [],
                           checker_factory=lambda **kwargs: HungCloseChecker())
    monkeypatch.setattr(service, "_checker_close_timeout", 0.02, raising=False)
    stopper = None
    try:
        assert await service.start("recheck")
        await asyncio.wait_for(checking.wait(), timeout=2)
        stopper = asyncio.create_task(service.stop())
        await asyncio.wait_for(closing.wait(), timeout=2)
        done, _ = await asyncio.wait({stopper}, timeout=0.5)
        assert stopper in done, "checker.close must not prevent bounded shutdown"
        assert await stopper is True
        assert close_cancelled is True
        snapshot = service.snapshot()
        assert snapshot["running"] is False
        assert snapshot["state"] == "error"
        assert snapshot["finished_at"] is not None
        assert snapshot["errors"] == 1
        assert "cleanup timed out" in snapshot["last_error"]
        runs = await storage.list_runs()
        assert len(runs) == 1
        assert runs[0]["status"] == "failed"
        assert runs[0]["errors"] == snapshot["errors"]
        assert runs[0]["finished_at"] == snapshot["finished_at"]
        assert not [task for task in asyncio.all_tasks()
                    if task.get_name().startswith("proxyharbor-") and not task.done()]
    finally:
        release_close.set()
        if stopper is not None:
            await asyncio.gather(stopper, return_exceptions=True)
        await service.close()


async def test_cancellation_during_failed_run_commit_observes_sqlite_outcome(storage, held_commit):
    checking = asyncio.Event()

    class CloseErrorChecker(FailedChecker):
        async def check(self, candidate):
            checking.set()
            await asyncio.Event().wait()

        async def close(self):
            raise OSError("checker cleanup failed during stop")

    await storage.add_candidates([ProxyCandidate("8.8.8.8", 8080, "http")], "fixture")
    held_commit.arm()
    service = ProxyService(storage, Settings(auto_collect=False), [],
                           checker_factory=lambda **kwargs: CloseErrorChecker())
    stopper = None
    try:
        assert await service.start("recheck")
        await asyncio.wait_for(checking.wait(), timeout=2)
        stopper = asyncio.create_task(service.stop())
        await asyncio.wait_for(held_commit.reached.wait(), timeout=2)
        for _ in range(2):
            service._task.cancel()
            await asyncio.sleep(0)
        held_commit.release.set()
        assert await asyncio.wait_for(stopper, timeout=2) is True
        assert held_commit.cancelled is False
        snapshot = service.snapshot()
        assert snapshot["running"] is False
        assert snapshot["state"] == "error"
        assert snapshot["errors"] == 1
        assert "checker cleanup failed during stop" in snapshot["last_error"]
        runs = await storage.list_runs()
        assert len(runs) == 1
        assert runs[0]["status"] == "failed"
        assert runs[0]["checked"] == 0
        assert runs[0]["errors"] == snapshot["errors"]
        assert runs[0]["finished_at"] == snapshot["finished_at"]
        assert not [task for task in asyncio.all_tasks()
                    if task.get_name().startswith("proxyharbor-") and not task.done()]
    finally:
        held_commit.release.set()
        if stopper is not None:
            await asyncio.gather(stopper, return_exceptions=True)
        await service.close()
