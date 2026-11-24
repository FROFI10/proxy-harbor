"""Asynchronous SQLite pool. All timestamps are UTC epoch seconds."""

import asyncio
import ipaddress
import math
import time
from contextlib import asynccontextmanager
from pathlib import Path

import aiosqlite

from .models import (
    CHECK_VALIDATION_VERSION,
    CheckResult,
    ProxyCandidate,
    SourceSpec,
    is_public_ip,
    validate_candidate,
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS proxies (
    id INTEGER PRIMARY KEY,
    host TEXT NOT NULL,
    port INTEGER NOT NULL CHECK (port BETWEEN 1 AND 65535),
    protocol TEXT NOT NULL CHECK (protocol IN ('http', 'socks4', 'socks5')),
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'alive', 'dead')),
    latency_ms REAL,
    supports_https INTEGER NOT NULL DEFAULT 0 CHECK (supports_https IN (0, 1)),
    exit_ip TEXT,
    error TEXT,
    first_seen REAL NOT NULL,
    last_seen REAL NOT NULL,
    last_checked REAL,
    successes INTEGER NOT NULL DEFAULT 0,
    failures INTEGER NOT NULL DEFAULT 0,
    requests INTEGER NOT NULL DEFAULT 0,
    last_issued INTEGER NOT NULL DEFAULT 0,
    validation_version INTEGER NOT NULL DEFAULT 0,
    validated_at REAL,
    UNIQUE (protocol, host, port)
);
CREATE TABLE IF NOT EXISTS proxy_sources (
    proxy_id INTEGER NOT NULL REFERENCES proxies(id) ON DELETE CASCADE,
    source_id TEXT NOT NULL,
    first_seen REAL NOT NULL,
    last_seen REAL NOT NULL,
    PRIMARY KEY (proxy_id, source_id)
);
CREATE TABLE IF NOT EXISTS proxy_invalidations (
    proxy_id INTEGER PRIMARY KEY REFERENCES proxies(id) ON DELETE CASCADE,
    invalidated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_proxies_live ON proxies(status, last_checked, latency_ms);
CREATE INDEX IF NOT EXISTS idx_proxies_due ON proxies(last_checked, status, id);
CREATE INDEX IF NOT EXISTS idx_proxies_seen ON proxies(last_seen);
CREATE INDEX IF NOT EXISTS idx_proxies_filters ON proxies(status, protocol, supports_https, last_checked, latency_ms);
CREATE INDEX IF NOT EXISTS idx_proxies_issuance ON proxies(status, last_issued, id);
CREATE INDEX IF NOT EXISTS idx_proxies_issued ON proxies(last_issued);
CREATE TABLE IF NOT EXISTS issuance_counter (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    value INTEGER NOT NULL DEFAULT 0
);
INSERT OR IGNORE INTO issuance_counter(singleton, value) VALUES (1, 0);
CREATE TABLE IF NOT EXISTS sources (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    url TEXT NOT NULL,
    protocol TEXT NOT NULL DEFAULT 'http',
    format TEXT NOT NULL DEFAULT 'text',
    enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
    last_fetch REAL,
    found INTEGER NOT NULL DEFAULT 0,
    added INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    elapsed_ms REAL
);
CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    started_at REAL NOT NULL,
    finished_at REAL,
    mode TEXT NOT NULL,
    status TEXT NOT NULL,
    parsed INTEGER NOT NULL DEFAULT 0,
    added INTEGER NOT NULL DEFAULT 0,
    checked INTEGER NOT NULL DEFAULT 0,
    working INTEGER NOT NULL DEFAULT 0,
    errors INTEGER NOT NULL DEFAULT 0,
    duration_ms REAL
);
CREATE INDEX IF NOT EXISTS idx_runs_started ON runs(started_at DESC, id);
"""


class Storage:
    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        self._conn: aiosqlite.Connection | None = None
        self._lock = asyncio.Lock()
        self._pending_protocol_cursor = 0

    def _connection(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("storage is not open")
        return self._conn

    async def open(self) -> None:
        async with self._lock:
            if self._conn is not None:
                return
            if self.path != ":memory:":
                await asyncio.to_thread(Path(self.path).parent.mkdir, parents=True, exist_ok=True)
            conn = await aiosqlite.connect(self.path, isolation_level=None, timeout=30)
            conn.row_factory = aiosqlite.Row
            try:
                for statement in (
                    "PRAGMA journal_mode=WAL",
                    "PRAGMA synchronous=NORMAL",
                    "PRAGMA foreign_keys=ON",
                ):
                    cursor = await conn.execute(statement)
                    await cursor.close()
                cursor = await conn.executescript(_SCHEMA)
                await cursor.close()
                # Serialize upgrades, including concurrent opens of a legacy database.
                cursor = await conn.execute("BEGIN IMMEDIATE")
                await cursor.close()
                async with conn.execute("PRAGMA table_info(proxies)") as cursor:
                    columns = {row["name"] for row in await cursor.fetchall()}
                for name, definition in (
                    ("validation_version", "INTEGER NOT NULL DEFAULT 0"),
                    ("validated_at", "REAL"),
                ):
                    if name not in columns:
                        cursor = await conn.execute(f"ALTER TABLE proxies ADD COLUMN {name} {definition}")
                        await cursor.close()
                cursor = await conn.execute(
                    """UPDATE proxies SET status='pending', last_checked=NULL, latency_ms=NULL,
                       supports_https=0, exit_ip=NULL, validation_version=0, validated_at=NULL,
                       error='Requires independent proxy challenge validation'
                       WHERE status='alive' AND (validation_version != ? OR validated_at IS NULL
                           OR last_checked IS NULL OR validated_at != last_checked)""",
                    (CHECK_VALIDATION_VERSION,),
                )
                await cursor.close()
                cursor = await conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_proxies_validation ON proxies(validation_version,status,last_checked,latency_ms)"
                )
                await cursor.close()
                await conn.commit()
            except BaseException:
                await conn.rollback()
                await conn.close()
                raise
            self._conn = conn

    async def close(self) -> None:
        async with self._lock:
            if self._conn is not None:
                await self._conn.close()
                self._conn = None

    @asynccontextmanager
    async def _transaction(self, *, write: bool = True):
        async with self._lock:
            conn = self._connection()
            try:
                cursor = await conn.execute("BEGIN IMMEDIATE" if write else "BEGIN")
                await cursor.close()
                yield conn
                await conn.commit()
            except BaseException:
                await conn.rollback()
                raise

    @staticmethod
    def _prepare_candidates(candidates: list[ProxyCandidate]) -> list[ProxyCandidate]:
        unique: dict[str, ProxyCandidate] = {}
        for candidate in candidates:
            candidate = validate_candidate(candidate)
            unique.setdefault(candidate.key, candidate)
        return list(unique.values())

    async def add_candidates(self, candidates: list[ProxyCandidate], source_id: str) -> int:
        if not isinstance(source_id, str) or not source_id:
            raise ValueError("source_id must be a non-empty string")
        candidates = await asyncio.to_thread(self._prepare_candidates, candidates)
        now = time.time()
        identities = [(candidate.protocol, candidate.host, candidate.port) for candidate in candidates]
        async with self._transaction() as conn:
            cursor = await conn.executemany(
                "INSERT OR IGNORE INTO proxies(protocol, host, port, first_seen, last_seen) VALUES (?, ?, ?, ?, ?)",
                [(*identity, now, now) for identity in identities],
            )
            added = cursor.rowcount
            await cursor.close()
            cursor = await conn.executemany(
                "UPDATE proxies SET last_seen = MAX(last_seen, ?) WHERE protocol = ? AND host = ? AND port = ?",
                [(now, *identity) for identity in identities],
            )
            await cursor.close()
            cursor = await conn.executemany(
                """INSERT INTO proxy_sources(proxy_id, source_id, first_seen, last_seen)
                   SELECT id, ?, ?, ? FROM proxies WHERE protocol = ? AND host = ? AND port = ?
                   ON CONFLICT(proxy_id, source_id) DO UPDATE SET last_seen = MAX(last_seen, excluded.last_seen)""",
                [(source_id, now, now, *identity) for identity in identities],
            )
            await cursor.close()
        return added

    async def pending_candidates(
        self, limit: int = 10000, recheck_after: float = 600
    ) -> list[ProxyCandidate]:
        self._page(limit)
        self._non_negative("recheck_after", recheck_after)
        cutoff = time.time() - recheck_after
        async with self._lock:
            protocol_start = self._pending_protocol_cursor
            async with self._connection().execute(
                """WITH due AS (
                       SELECT p.*, CASE WHEN p.last_checked IS NULL OR (p.status='alive' AND NOT COALESCE(
                           p.validation_version=? AND p.validated_at IS NOT NULL AND p.validated_at=p.last_checked,0))
                           THEN 0 WHEN p.status='alive' THEN 1 ELSE 2 END AS priority
                       FROM proxies p WHERE p.last_checked IS NULL OR p.last_checked <= ?
                           OR (p.status='alive' AND NOT COALESCE(p.validation_version=?
                               AND p.validated_at IS NOT NULL AND p.validated_at=p.last_checked,0))
                   ), balanced AS (
                       SELECT *, ROW_NUMBER() OVER(PARTITION BY priority,protocol ORDER BY last_checked,id) AS protocol_rank
                       FROM due
                   ) SELECT host,port,protocol FROM balanced ORDER BY priority,protocol_rank,
                       ((CASE protocol WHEN 'http' THEN 0 WHEN 'socks4' THEN 1 ELSE 2 END - ? + 3) % 3),id LIMIT ?""",
                (CHECK_VALIDATION_VERSION, cutoff, CHECK_VALIDATION_VERSION, protocol_start, limit),
            ) as cursor:
                rows = await cursor.fetchall()
            if rows:
                self._pending_protocol_cursor = (protocol_start + 1) % 3
        return [ProxyCandidate(row["host"], row["port"], row["protocol"]) for row in rows]

    async def save_result(self, result: CheckResult) -> None:
        await self.save_results([result])

    @classmethod
    def _prepare_results(cls, results: list[CheckResult], now: float) -> list[tuple]:
        values = []
        for result in results:
            candidate = validate_candidate(result.candidate)
            if type(result.ok) is not bool or type(result.supports_https) is not bool:
                raise ValueError("check flags must be boolean")
            if type(result.validation_version) is not int or result.validation_version < 0:
                raise ValueError("invalid check validation version")
            if result.ok and result.validation_version != CHECK_VALIDATION_VERSION:
                raise ValueError("alive results require the current independent challenge verification")
            cls._non_negative("checked_at", result.checked_at)
            if result.latency_ms is not None:
                cls._non_negative("latency_ms", result.latency_ms)
            if result.error is not None and not isinstance(result.error, str):
                raise ValueError("check error must be a string or None")
            exit_ip = None
            if result.ok:
                if not isinstance(result.exit_ip, str) or not is_public_ip(result.exit_ip):
                    raise ValueError("successful checks require a public exit IP")
                exit_ip = str(ipaddress.ip_address(result.exit_ip))
            values.append(
                (
                    candidate.protocol,
                    candidate.host,
                    candidate.port,
                    "alive" if result.ok else "dead",
                    result.latency_ms if result.ok else None,
                    int(result.ok and result.supports_https),
                    exit_ip,
                    result.error,
                    now,
                    now,
                    result.checked_at,
                    int(result.ok),
                    int(not result.ok),
                    result.validation_version,
                    result.checked_at if result.ok else None,
                )
            )
        return values

    async def save_results(self, results: list[CheckResult]) -> None:
        values = await asyncio.to_thread(self._prepare_results, results, time.time())
        async with self._transaction() as conn:
            cursor = await conn.executemany(
                """INSERT INTO proxies(
                       protocol, host, port, status, latency_ms, supports_https, exit_ip, error,
                       first_seen, last_seen, last_checked, successes, failures, validation_version, validated_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(protocol, host, port) DO UPDATE SET
                       status = excluded.status, latency_ms = excluded.latency_ms,
                       supports_https = excluded.supports_https, exit_ip = excluded.exit_ip,
                       error = excluded.error, last_checked = excluded.last_checked,
                       validation_version = excluded.validation_version, validated_at = excluded.validated_at,
                       successes = proxies.successes + excluded.successes,
                       failures = proxies.failures + excluded.failures
                   WHERE (proxies.last_checked IS NULL OR excluded.last_checked >= proxies.last_checked)
                   AND NOT EXISTS (
                       SELECT 1 FROM proxy_invalidations pi WHERE pi.proxy_id = proxies.id
                       AND pi.invalidated_at >= excluded.last_checked
                   )""",
                values,
            )
            await cursor.close()

    @staticmethod
    def _proxy_row(row: aiosqlite.Row) -> dict:
        item = dict(row)
        candidate = ProxyCandidate(item["host"], item["port"], item["protocol"])
        item["url"] = candidate.url
        item["address"] = candidate.address
        item["supports_https"] = bool(item["supports_https"])
        if item["status"] == "alive" and (
            item["validation_version"] != CHECK_VALIDATION_VERSION
            or item["validated_at"] is None
            or item["validated_at"] != item["last_checked"]
        ):
            item.update(
                status="pending",
                supports_https=False,
                latency_ms=None,
                exit_ip=None,
                error="Requires independent proxy challenge validation",
            )
        item.pop("last_issued", None)
        item.pop("validated_at", None)
        return item

    @staticmethod
    def _non_negative(name: str, value: float) -> None:
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or value < 0
        ):
            raise ValueError(f"{name} must be finite and non-negative")

    @staticmethod
    def _page(limit: int, offset: int = 0) -> None:
        if type(limit) is not int or limit < 0 or type(offset) is not int or offset < 0:
            raise ValueError("limit and offset must be non-negative integers")

    @classmethod
    def _filters(
        cls,
        *,
        protocol=None,
        max_latency_ms=None,
        https_only=False,
        freshness=600,
        status="alive",
        query=None,
    ) -> tuple[str, list]:
        if status not in {"alive", "pending", "dead", "all"}:
            raise ValueError("invalid proxy status")
        if protocol is not None and protocol not in {"http", "socks4", "socks5"}:
            raise ValueError("invalid proxy protocol")
        cls._non_negative("freshness", freshness)
        conditions = []
        parameters = []
        if status == "pending":
            conditions.append("""(p.status='pending' OR (p.status='alive' AND NOT COALESCE(
                p.validation_version=? AND p.validated_at IS NOT NULL AND p.validated_at=p.last_checked,0)))""")
            parameters.append(CHECK_VALIDATION_VERSION)
        elif status != "all":
            conditions.append("p.status = ?")
            parameters.append(status)
        if status == "alive":
            now = time.time()
            conditions.append("""p.validation_version=? AND p.validated_at IS NOT NULL AND p.validated_at=p.last_checked
                AND p.last_checked >= ? AND p.last_checked <= ? AND p.exit_ip IS NOT NULL""")
            parameters.extend((CHECK_VALIDATION_VERSION, now - freshness, now))
        if protocol is not None:
            conditions.append("p.protocol = ?")
            parameters.append(protocol)
        if max_latency_ms is not None:
            cls._non_negative("max_latency_ms", max_latency_ms)
            conditions.append("p.latency_ms <= ?")
            parameters.append(max_latency_ms)
        if https_only:
            conditions.append("p.supports_https = 1")
        if query is not None:
            if not isinstance(query, str):
                raise ValueError("query must be a string")
            conditions.append("""(
                INSTR(LOWER(p.host), ?) > 0 OR INSTR(CAST(p.port AS TEXT), ?) > 0 OR
                INSTR(p.protocol || '://' || CASE WHEN INSTR(p.host, ':') > 0
                    THEN '[' || p.host || ']' ELSE p.host END || ':' || p.port, ?) > 0
            )""")
            parameters.extend((query.lower(), query, query.lower()))
        return " AND ".join(conditions) or "1 = 1", parameters

    async def list_proxies(
        self,
        limit=50,
        offset=0,
        protocol=None,
        max_latency_ms=None,
        https_only=False,
        freshness=600,
        status="alive",
        sort="latency",
        query=None,
    ) -> dict:
        self._page(limit, offset)
        sorts = {
            "latency": "(p.latency_ms IS NULL), p.latency_ms, p.id",
            "recent": "p.last_checked DESC, p.id",
            "requests": "p.requests DESC, p.id",
        }
        if sort not in sorts:
            raise ValueError("invalid proxy sort")
        where, parameters = self._filters(
            protocol=protocol,
            max_latency_ms=max_latency_ms,
            https_only=https_only,
            freshness=freshness,
            status=status,
            query=query,
        )
        async with self._transaction(write=False) as conn:
            async with conn.execute(f"SELECT COUNT(*) FROM proxies p WHERE {where}", parameters) as cursor:
                total = (await cursor.fetchone())[0]
            async with conn.execute(
                f"""SELECT p.*, (SELECT COUNT(*) FROM proxy_sources ps WHERE ps.proxy_id = p.id) AS source_count
                    FROM proxies p WHERE {where}
                    ORDER BY {sorts[sort]} LIMIT ? OFFSET ?""",
                [*parameters, limit, offset],
            ) as cursor:
                items = [self._proxy_row(row) for row in await cursor.fetchall()]
        return {"items": items, "total": total, "limit": limit, "offset": offset}

    async def get_proxies(
        self, limit=1, protocol=None, max_latency_ms=None, https_only=False, freshness=600, strategy="random"
    ) -> list[dict]:
        self._page(limit)
        strategies = {
            "random": "RANDOM()",
            "best": "(p.latency_ms IS NULL), p.latency_ms, p.id",
            "round_robin": "p.last_issued, p.id",
        }
        if strategy not in strategies:
            raise ValueError("invalid issuance strategy")
        async with self._transaction() as conn:
            where, parameters = self._filters(
                protocol=protocol, max_latency_ms=max_latency_ms, https_only=https_only, freshness=freshness
            )
            async with conn.execute(
                f"SELECT p.id FROM proxies p WHERE {where} ORDER BY {strategies[strategy]} LIMIT ?",
                [*parameters, limit],
            ) as cursor:
                ids = [row[0] for row in await cursor.fetchall()]
            if not ids:
                return []
            async with conn.execute(
                "UPDATE issuance_counter SET value = value + ? WHERE singleton = 1 RETURNING value",
                (len(ids),),
            ) as cursor:
                end = (await cursor.fetchone())[0]
            start = end - len(ids)
            cursor = await conn.executemany(
                "UPDATE proxies SET requests = requests + 1, last_issued = ? WHERE id = ?",
                [(start + index, proxy_id) for index, proxy_id in enumerate(ids, 1)],
            )
            await cursor.close()
            async with conn.execute(
                """SELECT p.*, (SELECT COUNT(*) FROM proxy_sources ps WHERE ps.proxy_id = p.id) AS source_count
                   FROM proxies p WHERE p.last_issued > ? AND p.last_issued <= ? ORDER BY p.last_issued""",
                (start, end),
            ) as cursor:
                return [self._proxy_row(row) for row in await cursor.fetchall()]

    async def report_proxy(self, proxy_id: int, ok: bool) -> bool:
        if type(proxy_id) is not int or type(ok) is not bool:
            raise ValueError("report requires an integer proxy_id and boolean ok")
        async with self._transaction() as conn:
            if ok:
                async with conn.execute("SELECT 1 FROM proxies WHERE id = ?", (proxy_id,)) as cursor:
                    return await cursor.fetchone() is not None
            cursor = await conn.execute(
                """UPDATE proxies SET status = 'dead', supports_https = 0, latency_ms = NULL,
                   exit_ip = NULL, validation_version=0, validated_at=NULL,
                   error = 'failed client report', failures = failures + 1 WHERE id = ?""",
                (proxy_id,),
            )
            found = cursor.rowcount > 0
            await cursor.close()
            if found:
                cursor = await conn.execute(
                    """INSERT INTO proxy_invalidations(proxy_id, invalidated_at) VALUES (?, ?)
                       ON CONFLICT(proxy_id) DO UPDATE SET invalidated_at = excluded.invalidated_at""",
                    (proxy_id, time.time()),
                )
                await cursor.close()
            return found

    async def stats(self, freshness=600) -> dict:
        """Protocol/HTTPS/latency metrics describe the fresh verified pool only."""
        self._non_negative("freshness", freshness)
        async with self._transaction(write=False) as conn:
            now = time.time()
            async with conn.execute(
                """WITH trusted AS (
                       SELECT *, CASE WHEN validation_version=? AND validated_at IS NOT NULL
                           AND validated_at=last_checked THEN 1 ELSE 0 END AS verified FROM proxies
                   ), classified AS (
                       SELECT *, CASE WHEN status = 'alive' AND verified=1 AND last_checked >= ? AND last_checked <= ?
                                     AND exit_ip IS NOT NULL THEN 1 ELSE 0 END AS fresh FROM trusted
                   ) SELECT COUNT(*) AS total, COALESCE(SUM(fresh), 0) AS alive,
                       COALESCE(SUM(status = 'pending' OR (status='alive' AND verified=0)), 0) AS pending,
                       COALESCE(SUM(status = 'dead'), 0) AS dead,
                       COALESCE(SUM(status = 'alive' AND verified=1 AND fresh = 0), 0) AS stale,
                       COALESCE(SUM(fresh = 1 AND supports_https = 1), 0) AS https,
                       AVG(CASE WHEN fresh = 1 THEN latency_ms END) AS average_latency_ms,
                       COALESCE(SUM(fresh = 1 AND protocol = 'http'), 0) AS protocol_http,
                       COALESCE(SUM(fresh = 1 AND protocol = 'socks4'), 0) AS protocol_socks4,
                       COALESCE(SUM(fresh = 1 AND protocol = 'socks5'), 0) AS protocol_socks5,
                       COALESCE(SUM(requests), 0) AS requests, MAX(last_checked) AS last_check
                   FROM classified""",
                (CHECK_VALIDATION_VERSION, now - freshness, now),
            ) as cursor:
                result = dict(await cursor.fetchone())
            async with conn.execute(
                "SELECT COUNT(*) AS sources_total, COALESCE(SUM(enabled), 0) AS sources_enabled FROM sources"
            ) as cursor:
                result.update(dict(await cursor.fetchone()))
        result["protocols"] = {
            protocol: result.pop(f"protocol_{protocol}") for protocol in ("http", "socks4", "socks5")
        }
        return result

    async def upsert_sources(self, sources: list[SourceSpec]) -> None:
        values = [
            (source.id, source.name, source.url, source.protocol, source.format, int(source.enabled))
            for source in sources
        ]
        async with self._transaction() as conn:
            cursor = await conn.executemany(
                """INSERT INTO sources(id, name, url, protocol, format, enabled) VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET name = excluded.name, url = excluded.url,
                   protocol = excluded.protocol, format = excluded.format, enabled = excluded.enabled""",
                values,
            )
            await cursor.close()

    async def list_sources(self) -> list[dict]:
        async with self._lock:
            async with self._connection().execute("SELECT * FROM sources ORDER BY name, id") as cursor:
                items = [dict(row) for row in await cursor.fetchall()]
        for item in items:
            item["enabled"] = bool(item["enabled"])
        return items

    async def record_source_result(
        self, source_id: str, *, found: int, added: int, error: str | None, elapsed_ms: float
    ) -> None:
        self._page(found, added)
        self._non_negative("elapsed_ms", elapsed_ms)
        if added > found:
            raise ValueError("added cannot exceed found")
        if error is not None and not isinstance(error, str):
            raise ValueError("source error must be a string or None")
        async with self._transaction() as conn:
            cursor = await conn.execute(
                "UPDATE sources SET last_fetch = ?, found = ?, added = ?, last_error = ?, elapsed_ms = ? WHERE id = ?",
                (time.time(), found, added, error, elapsed_ms, source_id),
            )
            await cursor.close()

    async def set_source_enabled(self, source_id: str, enabled: bool) -> bool:
        if type(enabled) is not bool:
            raise ValueError("enabled must be a boolean")
        async with self._transaction() as conn:
            cursor = await conn.execute(
                "UPDATE sources SET enabled = ? WHERE id = ?", (int(enabled), source_id)
            )
            found = cursor.rowcount > 0
            await cursor.close()
            return found

    async def save_run(self, data: dict) -> None:
        columns = (
            "id",
            "started_at",
            "finished_at",
            "mode",
            "status",
            "parsed",
            "added",
            "checked",
            "working",
            "errors",
            "duration_ms",
        )
        if not isinstance(data.get("id"), str) or not data["id"]:
            raise ValueError("run id must be a non-empty string")
        self._non_negative("started_at", data["started_at"])
        for name in ("finished_at", "duration_ms"):
            if data.get(name) is not None:
                self._non_negative(name, data[name])
        counters = {name: data.get(name, 0) for name in ("parsed", "added", "checked", "working", "errors")}
        for value in counters.values():
            self._page(value)
        values = {**data, **counters}
        async with self._transaction() as conn:
            cursor = await conn.execute(
                """INSERT INTO runs(id, started_at, finished_at, mode, status, parsed, added, checked, working, errors, duration_ms)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET started_at = excluded.started_at, finished_at = excluded.finished_at,
                       mode = excluded.mode, status = excluded.status, parsed = excluded.parsed, added = excluded.added,
                       checked = excluded.checked, working = excluded.working, errors = excluded.errors,
                       duration_ms = excluded.duration_ms""",
                [values.get(column) for column in columns],
            )
            await cursor.close()

    async def list_runs(self, limit=20) -> list[dict]:
        self._page(limit)
        async with self._lock:
            async with self._connection().execute(
                "SELECT * FROM runs ORDER BY started_at DESC, id DESC LIMIT ?", (limit,)
            ) as cursor:
                return [dict(row) for row in await cursor.fetchall()]

    async def prune(self, retention_days=3) -> int:
        """Prune unseen expired candidates, preserving recently verified alive rows."""
        self._non_negative("retention_days", retention_days)
        cutoff = time.time() - retention_days * 86400
        async with self._transaction() as conn:
            cursor = await conn.execute(
                """DELETE FROM proxies WHERE last_seen < ?
                   AND (status != 'alive' OR last_checked IS NULL OR last_checked < ?)""",
                (cutoff, cutoff),
            )
            removed = cursor.rowcount
            await cursor.close()
            return removed
