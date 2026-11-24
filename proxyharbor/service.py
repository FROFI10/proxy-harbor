"""One bounded collection/check cycle at a time, with live progress."""

import asyncio
import logging
import time
import uuid
from collections import deque
from contextlib import suppress

import aiohttp

from .config import Settings

logger = logging.getLogger("proxyharbor.service")


class ProxyService:
    _checker_close_timeout = 5.0

    def __init__(self, storage, settings: Settings, sources, *, fetcher=None, parser=None,
                 checker_factory=None):
        self.storage = storage
        self.settings = settings
        self.sources = list(sources)
        self.fetcher = fetcher
        self.parser = parser
        self.checker_factory = checker_factory
        self._task = None
        self._closed = False
        self._mode = "collect"
        self._lock = asyncio.Lock()
        self._scheduler_task = None
        self._schedule_changed = asyncio.Event()
        self._next_collect_at = time.time()
        self._next_recheck_at = time.time() + settings.recheck_interval
        self._logs = deque(maxlen=160)
        self._history = deque(maxlen=120)
        self._progress = {
            "state": "idle", "running": False, "stage": "Готов к сбору",
            "started_at": None, "finished_at": None, "cycle_id": None,
            "sources_done": 0, "sources_total": 0, "parsed": 0, "added": 0,
            "checked": 0, "working": 0, "queue": 0, "errors": 0,
            "last_error": None, "next_run_at": None,
        }

    def snapshot(self):
        return {**self._progress, "logs": list(self._logs), "history": list(self._history)}

    def _log(self, message, level="info"):
        self._logs.append({"time": time.time(), "level": level, "message": str(message)})
        getattr(logger, level if level != "warning" else "warning")(message)

    @staticmethod
    async def _settle_task(task):
        """Observe an owned task's outcome without forwarding caller cancellation."""
        cancelled = False
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                cancelled = True
        task.result()
        return cancelled

    async def _close_checker(self, checker):
        try:
            async with asyncio.timeout(self._checker_close_timeout):
                await checker.close()
        except asyncio.TimeoutError as error:
            raise TimeoutError(f"Checker cleanup timed out after {self._checker_close_timeout:g}s") from error

    async def start(self, mode="collect"):
        async with self._lock:
            if self._closed or self._task is not None and not self._task.done():
                return False
            self._progress.update({
                "state": "collecting" if mode == "collect" else "checking",
                "running": True, "stage": "Сбор источников" if mode == "collect" else "Проверка прокси",
                "started_at": time.time(), "finished_at": None, "cycle_id": uuid.uuid4().hex,
                "sources_done": 0, "sources_total": 0, "parsed": 0, "added": 0,
                "checked": 0, "working": 0, "queue": 0, "errors": 0, "last_error": None,
            })
            self._mode = mode
            self._task = asyncio.create_task(self._run(mode), name="proxyharbor-cycle")
            return True

    async def wait_idle(self):
        if self._task is not None:
            with suppress(asyncio.CancelledError):
                await self._task

    async def stop(self):
        async with self._lock:
            if self._task is None or self._task.done():
                return False
            self._progress.update(state="stopping", stage="Остановка")
            self._task.cancel()
            await self.wait_idle()
            if self._progress["running"]:
                self._log("Цикл остановлен до начала работы")
                await self._finish_cycle(self._mode, "cancelled", self._progress["started_at"])
            return True

    async def close(self):
        self._closed = True
        if self._scheduler_task is not None:
            self._scheduler_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._scheduler_task
        await self.stop()

    async def start_scheduler(self):
        if not self._closed and (self._scheduler_task is None or self._scheduler_task.done()):
            self._refresh_schedule()
            self._scheduler_task = asyncio.create_task(self._scheduler(), name="proxyharbor-scheduler")

    def apply_settings(self, settings):
        was_enabled = self.settings.auto_collect
        self.settings = settings
        now = time.time()
        self._next_collect_at = now if settings.auto_collect and not was_enabled else now + settings.collect_interval
        self._next_recheck_at = now + settings.recheck_interval
        self._refresh_schedule()
        self._schedule_changed.set()

    def _refresh_schedule(self):
        self._progress["next_run_at"] = (
            min(self._next_collect_at, self._next_recheck_at) if self.settings.auto_collect else None
        )

    async def _scheduler(self):
        while not self._closed:
            self._schedule_changed.clear()
            self._refresh_schedule()
            timeout = 30.0
            if self.settings.auto_collect:
                now = time.time()
                if self._task is None or self._task.done():
                    if now >= self._next_collect_at:
                        await self.start("collect")
                    elif now >= self._next_recheck_at:
                        await self.start("recheck")
                timeout = 1.0 if self._progress["running"] else max(
                    0.05, min(30.0, min(self._next_collect_at, self._next_recheck_at) - now)
                )
            with suppress(asyncio.TimeoutError):
                await asyncio.wait_for(self._schedule_changed.wait(), timeout=timeout)

    async def _run(self, mode):
        settings = self.settings.model_copy()
        started = self._progress["started_at"]
        status = "completed"
        checker = None
        self._log("Запущен сбор и проверка" if mode == "collect" else "Запущена повторная проверка")
        try:
            if mode == "collect":
                await self._collect(settings)
            candidates = await self.storage.pending_candidates(
                limit=settings.max_per_cycle,
                recheck_after=0 if mode == "recheck" else settings.recheck_interval,
            )
            self._progress.update(state="checking", stage="Проверка HTTP / SOCKS", queue=len(candidates))
            if candidates:
                factory = self.checker_factory
                if factory is None:
                    from .checker import ProxyChecker
                    factory = ProxyChecker
                checker = factory(timeout=settings.check_timeout, connect_timeout=settings.connect_timeout,
                                  http_probe_url=settings.http_probe_url, https_probe_url=settings.https_probe_url)
                await checker.start()
                await self._check_candidates(checker, candidates, settings.check_concurrency)
            await self.storage.prune(retention_days=settings.retention_days)
            stats = await self.storage.stats(freshness=settings.freshness)
            self._history.append({"time": time.time(), "alive": stats["alive"],
                                  "checked": self._progress["checked"]})
            self._log(f"Цикл завершён: проверено {self._progress['checked']}, "
                      f"работают {self._progress['working']}")
        except asyncio.CancelledError:
            status = "cancelled"
            self._log("Текущий цикл остановлен пользователем")
        except Exception as error:
            status = "failed"
            self._progress.update(state="error", last_error=str(error))
            self._progress["errors"] += 1
            self._log(f"Ошибка цикла: {error}", "error")
            logger.exception("Cycle failed")
        finally:
            try:
                if checker is not None:
                    close_task = asyncio.create_task(self._close_checker(checker), name="proxyharbor-checker-close")
                    if await self._settle_task(close_task) and status != "failed":
                        status = "cancelled"
            except Exception as error:
                status = "failed"
                self._progress.update(state="error", last_error=str(error))
                self._progress["errors"] += 1
                self._log(f"Ошибка закрытия проверяющего: {error}", "error")
                logger.exception("Checker cleanup failed")
            finally:
                await self._finish_cycle(mode, status, started)

    async def _finish_cycle(self, mode, status, started):
        finished = time.time()
        if mode == "collect":
            self._next_collect_at = finished + self.settings.collect_interval
        self._next_recheck_at = finished + self.settings.recheck_interval
        self._refresh_schedule()
        self._schedule_changed.set()
        self._progress.update(running=False, queue=0, finished_at=finished)
        if status != "failed":
            self._progress.update(state="idle", stage="Цикл остановлен" if status == "cancelled" else "Готов")
        record = {
            "id": self._progress["cycle_id"], "started_at": started, "finished_at": finished,
            "mode": mode, "status": status, "parsed": self._progress["parsed"],
            "added": self._progress["added"], "checked": self._progress["checked"],
            "working": self._progress["working"], "errors": self._progress["errors"],
            "duration_ms": round((finished - started) * 1000, 2),
        }
        task = asyncio.create_task(self.storage.save_run(record), name="proxyharbor-run-record")
        await self._settle_task(task)

    async def _collect(self, settings):
        sources = [source for source in self.sources if source.enabled]
        self._progress["sources_total"] = len(sources)
        fetcher = self.fetcher
        parser = self.parser
        if fetcher is None:
            from .sources import fetch_source
            fetcher = fetch_source
        if parser is None:
            from .parsing import parse_candidates
            parser = parse_candidates
        semaphore = asyncio.Semaphore(settings.source_concurrency)
        seen = set()
        connector = aiohttp.TCPConnector(limit=settings.source_concurrency)
        async with aiohttp.ClientSession(connector=connector, trust_env=False,
                                         headers={"User-Agent": "ProxyHarbor/1.0 (local public-feed collector)"}) as session:
            async def collect_one(source):
                async with semaphore:
                    began = time.perf_counter()
                    found = added = 0
                    error_text = None
                    try:
                        text = await fetcher(session, source, timeout=settings.source_timeout,
                                             max_bytes=5_000_000)
                        parsed = await asyncio.to_thread(parser, text, protocol=source.protocol,
                                                         format=source.format, max_items=settings.max_candidates)
                        found = len(parsed)
                        if not found:
                            raise ValueError("Источник не содержит корректных публичных прокси")
                        self._progress["parsed"] += found
                        admitted = []
                        for item in parsed:
                            if item.key in seen or len(seen) < settings.max_candidates:
                                admitted.append(item)
                                seen.add(item.key)
                        added = await self.storage.add_candidates(admitted, source.id)
                        self._progress["added"] += added
                        self._log(f"{source.name}: найдено {found}, новых {added}")
                    except asyncio.CancelledError:
                        raise
                    except Exception as error:
                        error_text = str(error)[:500]
                        self._progress["errors"] += 1
                        self._log(f"{source.name}: {error_text}", "warning")
                    await self.storage.record_source_result(source.id, found=found, added=added,
                                                            error=error_text,
                                                            elapsed_ms=(time.perf_counter() - began) * 1000)
                    self._progress["sources_done"] += 1
            async with asyncio.TaskGroup() as group:
                for source in sources:
                    group.create_task(collect_one(source))

    async def _check_candidates(self, checker, candidates, concurrency):
        work = asyncio.Queue()
        # Completed checks and the sentinel must never block workers during shutdown.
        results = asyncio.Queue(maxsize=len(candidates) + 1)
        for item in candidates:
            work.put_nowait(item)

        async def worker():
            while not work.empty():
                try:
                    item = work.get_nowait()
                except asyncio.QueueEmpty:
                    return
                checked = await checker.check(item)
                await results.put(checked)

        async def persist_batch(batch):
            if not batch:
                return
            await self.storage.save_results(batch)
            self._progress["checked"] += len(batch)
            self._progress["working"] += sum(result.ok for result in batch)
            self._progress["queue"] = max(0, len(candidates) - self._progress["checked"])

        async def flush_batch(batch):
            if not batch:
                return
            pending = list(batch)
            batch.clear()  # Only the owned task may attempt this batch, even on an error.
            task = asyncio.create_task(persist_batch(pending), name="proxyharbor-db-batch")
            if await self._settle_task(task):
                raise asyncio.CancelledError

        async def writer():
            batch = []
            try:
                while True:
                    try:
                        item = await asyncio.wait_for(results.get(), timeout=0.4)
                    except asyncio.TimeoutError:
                        await flush_batch(batch)
                        continue
                    if item is None:
                        break
                    batch.append(item)
                    if len(batch) >= 32:
                        await flush_batch(batch)
            finally:
                while not results.empty():
                    item = results.get_nowait()
                    if item is not None:
                        batch.append(item)
                await flush_batch(batch)

        async with asyncio.TaskGroup() as group:
            group.create_task(writer(), name="proxyharbor-db-writer")
            workers = [group.create_task(worker()) for _ in range(min(concurrency, len(candidates)))]
            await asyncio.gather(*workers)
            await results.put(None)
