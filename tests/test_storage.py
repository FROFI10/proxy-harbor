import asyncio
import time
from collections import Counter
from types import SimpleNamespace

import aiosqlite
import pytest

from proxyharbor.models import CHECK_VALIDATION_VERSION, CheckResult, ProxyCandidate, SourceSpec


def verified_result(*args, **kwargs):
    """Storage fixtures represent a completed independent challenge, not an IP-only echo."""
    kwargs.setdefault("validation_version", CHECK_VALIDATION_VERSION)
    return CheckResult(*args, **kwargs)


@pytest.fixture
async def storage(tmp_path):
    from proxyharbor.storage import Storage

    database = Storage(tmp_path / "pool.sqlite3")
    await database.open()
    try:
        yield database
    finally:
        await database.close()


async def test_candidate_batches_deduplicate_protocol_identity_and_persist(tmp_path):
    from proxyharbor.models import ProxyCandidate
    from proxyharbor.storage import Storage

    path = tmp_path / "nested" / "pool.sqlite3"
    first = ProxyCandidate("8.8.8.8", 8080, "http")
    second = ProxyCandidate("8.8.8.8", 8080, "socks5")
    storage = Storage(path)
    await storage.open()
    try:
        assert await storage.add_candidates([first, first, second], "feed") == 2
        assert await storage.add_candidates([first, second], "feed") == 0
        assert await storage.add_candidates([first], "other-feed") == 0
        assert await storage.pending_candidates() == [first, second]
    finally:
        await storage.close()
    reopened = Storage(path)
    await reopened.open()
    try:
        assert await reopened.pending_candidates(limit=1) == [first]
    finally:
        await reopened.close()


async def test_verification_results_transition_rows_and_preserve_provenance(storage):
    first = ProxyCandidate("8.8.8.8", 8080, "http")
    second = ProxyCandidate("2606:4700:4700::1111", 1080, "socks5")
    await storage.add_candidates([first, second], "feed")
    await storage.add_candidates([first, first], "second-feed")
    checked = time.time()
    await storage.save_results(
        [
            verified_result(
                first, True, latency_ms=20.0, supports_https=True, exit_ip="1.1.1.1", checked_at=checked
            ),
            verified_result(second, False, error="timeout", checked_at=checked),
        ]
    )
    page = await storage.list_proxies(status="all")
    assert page["total"] == 2
    rows = {row["url"]: row for row in page["items"]}
    alive = rows[first.url]
    assert alive["status"] == "alive"
    assert alive["last_checked"] == checked
    assert alive["latency_ms"] == 20.0
    assert alive["supports_https"] is True
    assert alive["exit_ip"] == "1.1.1.1"
    assert (alive["successes"], alive["failures"], alive["requests"], alive["source_count"]) == (1, 0, 0, 2)
    assert alive["first_seen"] <= alive["last_seen"] <= time.time()
    assert alive["address"] == first.address
    assert isinstance(alive["id"], int)
    assert rows[second.url]["address"] == "[2606:4700:4700::1111]:1080"
    assert rows[second.url]["status"] == "dead"
    assert rows[second.url]["supports_https"] is False
    await storage.save_result(verified_result(first, False, error="refused"))
    updated = next(
        row for row in (await storage.list_proxies(status="all"))["items"] if row["url"] == first.url
    )
    assert updated["status"] == "dead"
    assert updated["successes"] == updated["failures"] == 1
    assert updated["latency_ms"] is None
    assert updated["exit_ip"] is None
    assert updated["supports_https"] is False


async def test_proxy_listing_filters_pages_and_excludes_stale_verified_rows(storage):
    now = time.time()
    slow = ProxyCandidate("8.8.8.8", 80, "http")
    best = ProxyCandidate("1.1.1.1", 8080, "http")
    socks = ProxyCandidate("8.8.8.8", 1080, "socks5")
    stale = ProxyCandidate("9.9.9.9", 80, "http")
    pending = ProxyCandidate("2606:4700:4700::1111", 80, "socks4")
    dead = ProxyCandidate("8.8.4.4", 80, "http")
    await storage.add_candidates([slow, best, socks, stale, pending, dead], "feed")
    await storage.save_results(
        [
            verified_result(slow, True, 50, False, "8.8.8.8", checked_at=now),
            verified_result(best, True, 10, True, "1.1.1.1", checked_at=now),
            verified_result(socks, True, 20, True, "8.8.8.8", checked_at=now - 1),
            verified_result(stale, True, 1, True, "9.9.9.9", checked_at=now - 601),
            verified_result(dead, False, checked_at=now),
        ]
    )
    page = await storage.list_proxies(limit=1, offset=1, freshness=600)
    assert page["total"] == 3
    assert [row["url"] for row in page["items"]] == [socks.url]
    assert (page["limit"], page["offset"]) == (1, 1)
    filtered = await storage.list_proxies(protocol="http", max_latency_ms=20, https_only=True)
    assert filtered["total"] == 1
    assert filtered["items"][0]["url"] == best.url
    assert (await storage.list_proxies(status="all"))["total"] == 6
    assert (await storage.list_proxies(status="pending"))["items"][0]["url"] == pending.url
    assert (await storage.list_proxies(status="dead"))["items"][0]["url"] == dead.url
    assert (await storage.list_proxies(query="8080"))["items"][0]["url"] == best.url
    assert (await storage.list_proxies(status="all", query="socks4://[2606:"))["items"][0][
        "url"
    ] == pending.url
    assert (await storage.list_proxies(query="' OR 1=1 --"))["total"] == 0
    assert (await storage.list_proxies(query="%"))["total"] == 0
    recent = await storage.list_proxies(sort="recent")
    assert recent["items"][-1]["url"] == socks.url
    assert (await storage.list_proxies(sort="requests"))["total"] == 3


async def test_due_queue_prioritizes_untested_then_old_alive_and_excludes_recent_failures(storage):
    now = time.time()
    old_dead = ProxyCandidate("8.8.8.8", 8001, "http")
    untested = ProxyCandidate("8.8.8.8", 8002, "http")
    old_alive = ProxyCandidate("8.8.8.8", 8003, "http")
    recent_dead = ProxyCandidate("8.8.8.8", 8004, "http")
    await storage.add_candidates([old_dead, untested, old_alive, recent_dead], "feed")
    await storage.save_results(
        [
            verified_result(old_dead, False, checked_at=now - 700),
            verified_result(old_alive, True, 10, exit_ip="1.1.1.1", checked_at=now - 700),
            verified_result(recent_dead, False, checked_at=now),
        ]
    )
    assert await storage.pending_candidates(limit=2, recheck_after=600) == [untested, old_alive]
    assert await storage.pending_candidates(recheck_after=600) == [untested, old_alive, old_dead]
    assert len(await storage.pending_candidates(recheck_after=0)) == 4
    assert await storage.pending_candidates(limit=0) == []
    with pytest.raises(ValueError):
        await storage.pending_candidates(recheck_after=-1)


@pytest.mark.parametrize("strategy", ["best", "random"])
async def test_issuance_only_returns_filtered_fresh_verified_proxies_and_counts_requests(storage, strategy):
    now = time.time()
    first = ProxyCandidate("8.8.8.8", 80, "http")
    second = ProxyCandidate("1.1.1.1", 8080, "http")
    stale = ProxyCandidate("9.9.9.9", 80, "http")
    pending = ProxyCandidate("8.8.4.4", 80, "socks4")
    await storage.add_candidates([first, second, stale, pending], "manual-import")
    await storage.save_results(
        [
            verified_result(first, True, 10, False, "8.8.8.8", checked_at=now),
            verified_result(second, True, 5, True, "1.1.1.1", checked_at=now),
            verified_result(stale, True, 1, True, "9.9.9.9", checked_at=now - 601),
        ]
    )
    issued = await storage.get_proxies(limit=2, strategy=strategy)
    assert {row["url"] for row in issued} == {first.url, second.url}
    assert all(row["requests"] == 1 and row["source_count"] == 1 for row in issued)
    if strategy == "best":
        assert [row["url"] for row in issued] == [second.url, first.url]
    filtered = await storage.get_proxies(
        protocol="http", https_only=True, max_latency_ms=5, strategy=strategy
    )
    assert filtered[0]["url"] == second.url
    assert filtered[0]["requests"] == 2
    assert await storage.get_proxies(protocol="socks4", strategy=strategy) == []
    assert await storage.get_proxies(limit=0, strategy=strategy) == []
    persisted = await storage.list_proxies(sort="requests")
    assert persisted["items"][0]["url"] == second.url
    assert persisted["items"][0]["requests"] == 2


async def test_round_robin_is_atomic_across_connections_and_persists_restart(tmp_path):
    from proxyharbor.storage import Storage

    path = tmp_path / "round-robin.sqlite3"
    first, second = Storage(path), Storage(path)
    await first.open()
    await second.open()
    candidates = [ProxyCandidate("8.8.8.8", port, "http") for port in (8001, 8002, 8003)]
    try:
        await first.add_candidates(candidates, "manual-import")
        await first.save_results(
            [verified_result(candidate, True, 10, exit_ip="1.1.1.1") for candidate in candidates]
        )
        assert (await first.get_proxies(strategy="round_robin"))[0]["url"] == candidates[0].url
        await first.close()
        await first.open()
        assert (await first.get_proxies(strategy="round_robin"))[0]["url"] == candidates[1].url
        batches = await asyncio.gather(
            *[(first if index % 2 else second).get_proxies(strategy="round_robin") for index in range(60)]
        )
        counts = Counter(batch[0]["url"] for batch in batches)
        assert set(counts) == {candidate.url for candidate in candidates}
        assert len(batches) == 60
        assert min(counts.values()) == max(counts.values())
        persisted = await first.list_proxies(status="all")
        assert sum(row["requests"] for row in persisted["items"]) == 62
        assert (
            max(row["requests"] for row in persisted["items"])
            - min(row["requests"] for row in persisted["items"])
            <= 1
        )
    finally:
        await first.close()
        await second.close()


async def test_client_reports_invalidate_without_bypassing_full_checker_freshness(storage):
    first = ProxyCandidate("8.8.8.8", 80, "http")
    stale = ProxyCandidate("1.1.1.1", 80, "http")
    pending = ProxyCandidate("9.9.9.9", 80, "http")
    await storage.add_candidates([first, stale, pending], "manual-import")
    checked = time.time()
    await storage.save_results(
        [
            verified_result(first, True, 10, True, "8.8.8.8", checked_at=checked),
            verified_result(stale, True, 10, True, "1.1.1.1", checked_at=checked - 700),
        ]
    )
    rows = {row["url"]: row for row in (await storage.list_proxies(status="all"))["items"]}
    assert await storage.report_proxy(rows[first.url]["id"], False) is True
    assert await storage.get_proxies() == []
    assert await storage.report_proxy(rows[first.url]["id"], True) is True
    assert await storage.report_proxy(rows[stale.url]["id"], True) is True
    assert await storage.report_proxy(rows[pending.url]["id"], True) is True
    assert await storage.report_proxy(999999, False) is False
    assert await storage.report_proxy(999999, True) is False
    await storage.save_result(verified_result(first, True, 10, True, "8.8.8.8", checked_at=checked))
    current = {row["url"]: row for row in (await storage.list_proxies(status="all"))["items"]}
    assert current[first.url]["status"] == "dead"
    assert current[first.url]["supports_https"] is False
    assert current[first.url]["last_checked"] == checked
    assert current[stale.url]["last_checked"] == checked - 700
    assert current[pending.url]["status"] == "pending"
    assert await storage.get_proxies() == []
    await storage.save_result(verified_result(first, True, 9, True, "8.8.8.8"))
    assert (await storage.get_proxies())[0]["url"] == first.url


async def test_source_registry_preserves_fetch_metadata_without_fake_manual_feed(storage):
    await storage.add_candidates([ProxyCandidate("8.8.8.8", 80, "http")], "manual-import")
    assert await storage.list_sources() == []
    source = SourceSpec("source'1", "Feed ' name", "https://example.org/list?kind=http")
    disabled = SourceSpec("second", "SOCKS", "https://example.org/socks", "socks5", "json", False)
    await storage.upsert_sources([source, disabled])
    await storage.record_source_result(source.id, found=12, added=3, error="upstream 429", elapsed_ms=15.5)
    updated = SourceSpec(source.id, "Renamed", source.url)
    await storage.upsert_sources([updated])
    rows = {row["id"]: row for row in await storage.list_sources()}
    assert len(rows) == 2
    assert rows[source.id]["name"] == "Renamed"
    assert rows[source.id]["url"] == source.url
    assert rows[source.id]["found"] == 12
    assert rows[source.id]["added"] == 3
    assert rows[source.id]["last_error"] == "upstream 429"
    assert rows[source.id]["elapsed_ms"] == 15.5
    assert rows[source.id]["last_fetch"] <= time.time()
    assert rows[source.id]["enabled"] is True
    assert rows[disabled.id]["enabled"] is False
    assert rows[disabled.id]["last_fetch"] is None
    assert await storage.set_source_enabled(source.id, False) is True
    assert await storage.set_source_enabled("absent", True) is False
    await storage.record_source_result(source.id, found=5, added=0, error=None, elapsed_ms=3)
    row = next(row for row in await storage.list_sources() if row["id"] == source.id)
    assert row["enabled"] is False
    assert row["last_error"] is None
    assert (row["found"], row["added"]) == (5, 0)
    await storage.close()
    await storage.open()
    assert len(await storage.list_sources()) == 2
    proxies = await storage.list_proxies(status="all")
    assert proxies["items"][0]["source_count"] == 1


async def test_stats_use_only_fresh_alive_rows_for_availability_metrics(storage):
    empty = await storage.stats()
    assert empty == {
        "total": 0,
        "alive": 0,
        "pending": 0,
        "dead": 0,
        "stale": 0,
        "https": 0,
        "average_latency_ms": None,
        "protocols": {"http": 0, "socks4": 0, "socks5": 0},
        "requests": 0,
        "sources_total": 0,
        "sources_enabled": 0,
        "last_check": None,
    }
    now = time.time()
    candidates = [
        ProxyCandidate("8.8.8.8", 80, "http"),
        ProxyCandidate("1.1.1.1", 1080, "socks5"),
        ProxyCandidate("9.9.9.9", 1080, "socks4"),
        ProxyCandidate("8.8.4.4", 80, "http"),
        ProxyCandidate("1.0.0.1", 80, "http"),
    ]
    await storage.add_candidates(candidates, "manual-import")
    await storage.save_results(
        [
            verified_result(candidates[0], True, 50, True, "8.8.8.8", checked_at=now),
            verified_result(candidates[1], True, 10, False, "1.1.1.1", checked_at=now - 1),
            verified_result(candidates[2], True, 1, True, "9.9.9.9", checked_at=now - 700),
            verified_result(candidates[4], False, checked_at=now),
        ]
    )
    await storage.upsert_sources(
        [
            SourceSpec("first", "First", "https://example.org/first"),
            SourceSpec("second", "Second", "https://example.org/second", enabled=False),
        ]
    )
    await storage.get_proxies(strategy="best")
    stats = await storage.stats(freshness=600)
    assert stats == {
        "total": 5,
        "alive": 2,
        "pending": 1,
        "dead": 1,
        "stale": 1,
        "https": 1,
        "average_latency_ms": 30.0,
        "protocols": {"http": 1, "socks4": 0, "socks5": 1},
        "requests": 1,
        "sources_total": 2,
        "sources_enabled": 1,
        "last_check": now,
    }
    expired = await storage.stats(freshness=0)
    assert expired["alive"] == expired["https"] == 0
    assert expired["stale"] == 3
    assert expired["average_latency_ms"] is None


async def test_run_history_is_upserted_and_persists_in_newest_first_order(storage):
    assert await storage.list_runs() == []
    now = time.time()
    first = {
        "id": "cycle'1",
        "started_at": now - 10,
        "finished_at": now - 9,
        "mode": "collect",
        "status": "completed",
        "parsed": 12,
        "added": 4,
        "checked": 4,
        "working": 1,
        "errors": 0,
        "duration_ms": 1000.0,
    }
    second = {**first, "id": "cycle2", "started_at": now - 5, "finished_at": now - 4, "mode": "recheck"}
    await storage.save_run(first)
    await storage.save_run(second)
    await storage.save_run({**second, "status": "stopped", "working": 0})
    rows = await storage.list_runs()
    assert [row["id"] for row in rows] == [second["id"], first["id"]]
    assert rows[1] == first
    assert rows[0]["status"] == "stopped"
    assert rows[0]["working"] == 0
    assert len(await storage.list_runs(limit=1)) == 1
    assert await storage.list_runs(limit=0) == []
    await storage.close()
    await storage.open()
    assert (await storage.list_runs())[1] == first


async def test_prune_removes_expired_unseen_rows_and_cascades_provenance(storage, monkeypatch):
    import proxyharbor.storage as module

    now = time.time()
    clock = [now - 4 * 86400]
    monkeypatch.setattr(module, "time", SimpleNamespace(time=lambda: clock[0]))
    candidates = [ProxyCandidate("8.8.8.8", port, "http") for port in (8001, 8002, 8003, 8004)]
    await storage.add_candidates(candidates, "manual-import")
    await storage.save_results(
        [
            verified_result(candidates[0], False, checked_at=clock[0]),
            verified_result(candidates[2], True, 10, exit_ip="8.8.8.8", checked_at=clock[0]),
            verified_result(candidates[3], True, 10, exit_ip="8.8.8.8", checked_at=clock[0]),
        ]
    )
    clock[0] = now
    await storage.save_result(verified_result(candidates[2], True, 10, exit_ip="8.8.8.8", checked_at=now))
    old_rows = (await storage.list_proxies(status="all"))["items"]
    old_dead_id = next(row["id"] for row in old_rows if row["url"] == candidates[0].url)
    await storage.report_proxy(old_dead_id, False)
    recent = ProxyCandidate("1.1.1.1", 80, "http")
    await storage.add_candidates([recent], "feed")
    assert await storage.prune(retention_days=3) == 3
    remaining = (await storage.list_proxies(status="all"))["items"]
    assert {row["url"] for row in remaining} == {candidates[2].url, recent.url}
    assert all(row["source_count"] == 1 for row in remaining)
    async with aiosqlite.connect(storage.path) as conn:
        async with conn.execute("SELECT COUNT(*) FROM proxy_sources") as cursor:
            assert (await cursor.fetchone())[0] == 2
        async with conn.execute("SELECT COUNT(*) FROM proxy_invalidations") as cursor:
            assert (await cursor.fetchone())[0] == 0
    assert await storage.prune(retention_days=3) == 0
    with pytest.raises(ValueError):
        await storage.prune(retention_days=-1)


@pytest.mark.parametrize(
    "invalid",
    [
        {"exit_ip": None},
        {"exit_ip": "127.0.0.1"},
        {"exit_ip": "224.0.0.1"},
        {"latency_ms": float("nan")},
        {"latency_ms": -1},
        {"checked_at": float("nan")},
        {"checked_at": -1},
        {"ok": 1},
    ],
)
async def test_invalid_result_batches_do_not_partially_update_the_pool(storage, invalid):
    first = ProxyCandidate("8.8.8.8", 80, "http")
    second = ProxyCandidate("1.1.1.1", 80, "http")
    await storage.add_candidates([first, second], "manual-import")
    values = {"candidate": second, "ok": True, "latency_ms": 10, "exit_ip": "1.1.1.1", **invalid}
    with pytest.raises(ValueError):
        await storage.save_results(
            [verified_result(first, True, 10, exit_ip="8.8.8.8"), verified_result(**values)]
        )
    rows = (await storage.list_proxies(status="all"))["items"]
    assert all(row["status"] == "pending" and row["last_checked"] is None for row in rows)
    assert all(row["successes"] == row["failures"] == 0 for row in rows)


async def test_older_checks_cannot_overwrite_newer_verification_state(storage):
    candidate = ProxyCandidate("8.8.8.8", 80, "http")
    checked = time.time()
    await storage.add_candidates([candidate], "feed")
    await storage.save_result(verified_result(candidate, True, 10, True, "1.1.1.1", checked_at=checked))
    await storage.save_results(
        [
            verified_result(candidate, False, error="old timeout", checked_at=checked - 100),
            verified_result(candidate, True, 1, False, "9.9.9.9", checked_at=checked - 200),
        ]
    )
    row = (await storage.list_proxies())["items"][0]
    assert row["last_checked"] == checked
    assert row["latency_ms"] == 10
    assert row["exit_ip"] == "1.1.1.1"
    assert row["supports_https"] is True
    assert row["successes"] == 1
    assert row["failures"] == 0


async def test_cancellation_while_waiting_for_sqlite_write_lock_does_not_poison_connection(storage):
    candidate = ProxyCandidate("8.8.8.8", 80, "http")
    await storage.add_candidates([candidate], "feed")
    entered = asyncio.Event()
    loop = asyncio.get_running_loop()
    await storage._conn.set_trace_callback(
        lambda statement: loop.call_soon_threadsafe(entered.set) if statement == "BEGIN IMMEDIATE" else None
    )
    async with aiosqlite.connect(storage.path) as blocker:
        await blocker.execute("BEGIN IMMEDIATE")
        task = asyncio.create_task(
            storage.save_result(verified_result(candidate, True, 10, exit_ip="1.1.1.1"))
        )
        try:
            await asyncio.wait_for(entered.wait(), 2)
            task.cancel()
        finally:
            await blocker.rollback()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 2)
    await storage.save_result(verified_result(candidate, True, 10, exit_ip="1.1.1.1"))
    row = (await storage.list_proxies())["items"][0]
    assert row["successes"] == 1
    assert row["requests"] == 0


async def test_weak_alive_cache_is_requeued_on_upgrade_and_cannot_be_issued(tmp_path):
    from proxyharbor.storage import Storage

    path = tmp_path / "legacy-v1.sqlite3"
    candidate = ProxyCandidate("8.8.8.8", 80, "http")
    now = time.time()
    async with aiosqlite.connect(path) as conn:
        await conn.executescript("""
            CREATE TABLE proxies (
                id INTEGER PRIMARY KEY, host TEXT NOT NULL, port INTEGER NOT NULL, protocol TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending', latency_ms REAL, supports_https INTEGER NOT NULL DEFAULT 0,
                exit_ip TEXT, error TEXT, first_seen REAL NOT NULL, last_seen REAL NOT NULL, last_checked REAL,
                successes INTEGER NOT NULL DEFAULT 0, failures INTEGER NOT NULL DEFAULT 0,
                requests INTEGER NOT NULL DEFAULT 0, last_issued INTEGER NOT NULL DEFAULT 0,
                UNIQUE(protocol, host, port)
            );
            CREATE TABLE proxy_sources (
                proxy_id INTEGER NOT NULL REFERENCES proxies(id) ON DELETE CASCADE, source_id TEXT NOT NULL,
                first_seen REAL NOT NULL, last_seen REAL NOT NULL, PRIMARY KEY(proxy_id, source_id)
            );
        """)
        await conn.execute(
            """INSERT INTO proxies(host,port,protocol,status,latency_ms,supports_https,exit_ip,first_seen,last_seen,last_checked,successes,requests)
               VALUES (?,?,?,'alive',1,1,'1.1.1.1',?,?,?,1,2)""",
            (candidate.host, candidate.port, candidate.protocol, now - 1000, now - 10, now - 10),
        )
        await conn.execute("INSERT INTO proxy_sources VALUES (1,'manual-import',?,?)", (now - 1000, now - 10))
        await conn.commit()
    database = Storage(path)
    await database.open()
    try:
        assert (await database.list_proxies())["total"] == 0, (
            "pre-challenge alive cache must not survive an upgrade"
        )
        assert await database.get_proxies() == []
        assert await database.pending_candidates() == [candidate]
        row = (await database.list_proxies(status="all"))["items"][0]
        assert row["status"] == "pending"
        assert row["last_checked"] is None
        assert row["supports_https"] is False
        assert row["validation_version"] == 0
        assert row["source_count"] == 1
        assert row["requests"] == 2
        with pytest.raises(ValueError):
            await database.save_result(CheckResult(candidate, True, 10, exit_ip="1.1.1.1"))
        await database.save_result(
            verified_result(candidate, True, 10, True, "1.1.1.1", checked_at=now - 10, validation_version=2)
        )
        assert (await database.list_proxies())["total"] == 1
        # A stale legacy writer must not refresh an existing V2 verification stamp.
        async with aiosqlite.connect(path) as conn:
            await conn.execute("UPDATE proxies SET last_checked=?, exit_ip='9.9.9.9'", (now - 1,))
            await conn.commit()
        assert await database.get_proxies() == []
        assert (await database.list_proxies())["total"] == 0
        assert (await database.list_proxies(status="pending"))["total"] == 1
        assert (await database.stats())["alive"] == 0
        assert await database.pending_candidates() == [candidate]
    finally:
        await database.close()


async def test_due_queue_mixes_protocols_instead_of_drowning_socks_in_http(storage):
    http = [ProxyCandidate("8.8.8.8", port, "http") for port in range(8000, 8020)]
    socks4 = [ProxyCandidate("1.1.1.1", port, "socks4") for port in (1080, 1081)]
    socks5 = [ProxyCandidate("9.9.9.9", port, "socks5") for port in (1080, 1081)]
    await storage.add_candidates(http + socks4 + socks5, "manual-import")
    candidates = await storage.pending_candidates(limit=6)
    assert Counter(candidate.protocol for candidate in candidates) == {"http": 2, "socks4": 2, "socks5": 2}
    tiny_batches = [await storage.pending_candidates(limit=1) for _ in range(3)]
    assert {batch[0].protocol for batch in tiny_batches} == {"http", "socks4", "socks5"}
