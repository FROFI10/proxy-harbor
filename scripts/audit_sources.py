"""Reproducible, bounded audit of public proxy-feed URLs (no proxy checks)."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import os
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import aiohttp

from proxyharbor.models import SourceSpec
from proxyharbor.parsing import parse_candidates
from proxyharbor.sources import _fetch_document, save_sources


def publisher_for(url: str) -> str:
    host = (urlsplit(url).hostname or "").lower()
    if host == "raw.githubusercontent.com":
        return "github:" + urlsplit(url).path.strip("/").split("/")[0].lower()
    if host in {"api.proxyscrape.com", "proxyscrape.com"}:
        return "github:proxyscrape"
    if host in {"openproxylist.xyz"}:
        return "github:roosterkid"
    if host == "solproxy.net":
        return "github:solproxy"
    if host.endswith(".github.io"):
        return "github:" + host.removesuffix(".github.io")
    if host in {
        "free-proxy-list.net",
        "www.free-proxy-list.net",
        "www.sslproxies.org",
        "www.us-proxy.org",
        "www.google-proxy.net",
        "www.socks-proxy.net",
    }:
        return "free-proxy-list.net family"
    if host == "databay.com":
        return "github:databay-labs"
    return host.removeprefix("www.")


async def audit_sources(rows: list[dict], concurrency: int = 10, timeout: float = 15) -> list[dict]:
    """Fetch every supplied URL and count parsed public endpoints, never alive proxies."""
    semaphore = asyncio.Semaphore(concurrency)
    async with aiohttp.ClientSession(trust_env=False) as session:

        async def one(row):
            url = row["url"]
            protocol = "http" if row.get("protocol", "http") == "https" else row.get("protocol", "http")
            identity = hashlib.sha256((url + "\n" + protocol).encode()).hexdigest()[:16]
            publisher = publisher_for(url)
            record = {
                "id": row.get("id", "feed-" + identity),
                "name": row.get("name", publisher + " · " + protocol.upper()),
                "url": url,
                "protocol": protocol,
                "format": row.get("format", "text"),
                "enabled": False,
                "publisher": publisher,
                "provenance": row.get("provenance", []),
                "http_status": None,
                "valid_candidates": 0,
                "unique_public_addresses": 0,
                "candidate_protocols": {},
                "healthy": False,
                "selected": False,
                "error": None,
            }
            source = SourceSpec(
                **{key: record[key] for key in ("id", "name", "url", "protocol", "format", "enabled")}
            )
            async with semaphore:
                started = asyncio.get_running_loop().time()
                record["checked_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
                try:
                    document = await _fetch_document(session, source, timeout=timeout)
                    record.update(
                        http_status=document.http_status,
                        final_url=document.final_url,
                        decompressed_bytes=document.decompressed_bytes,
                        sha256=document.sha256,
                    )
                    content_format = source.format
                    if content_format != "json" and document.text.lstrip().startswith(("{", "[")):
                        content_format = "json"
                    elif content_format == "text" and document.text.lstrip().lower().startswith(
                        ("<!doctype html", "<html")
                    ):
                        content_format = "html"
                    candidates = parse_candidates(
                        document.text, source.protocol, content_format, max_items=100000
                    )
                    record["format"] = content_format
                    record["valid_candidates"] = len(candidates)
                    record["candidate_count_limit_reached"] = len(candidates) == 100000
                    record["unique_public_addresses"] = len({(p.host, p.port) for p in candidates})
                    record["candidate_protocols"] = dict(Counter(p.protocol for p in candidates))
                    record["healthy"] = bool(candidates)
                    if not candidates:
                        record["error"] = "HTTP response contains no public proxy entries"
                except (ValueError, RuntimeError, aiohttp.ClientError, OSError, LookupError) as exc:
                    record["error"] = f"{type(exc).__name__}: {exc}"
                    record["http_status"] = getattr(exc, "status", None)
                record["elapsed_ms"] = round((asyncio.get_running_loop().time() - started) * 1000, 2)
            return record

        return await asyncio.gather(*(one(row) for row in rows))


def select_sources(records: list[dict], max_feeds: int = 140) -> list[SourceSpec]:
    """Prefer publisher diversity, then protocols and other healthy feed variants."""
    eligible = [row for row in records if row["healthy"]]
    first, extras, variants, groups, publishers = [], [], [], set(), set()
    for row in eligible:
        group = (row["publisher"], row["protocol"])
        if group in groups:
            variants.append(row)
            continue
        groups.add(group)
        if row["publisher"] not in publishers:
            first.append(row)
            publishers.add(row["publisher"])
        else:
            extras.append(row)
    chosen = (first + extras + variants)[:max_feeds]
    keys = {(row["url"], row["protocol"]) for row in chosen}
    for row in records:
        row["selected"] = (row["url"], row["protocol"]) in keys
        row["enabled"] = row["selected"]
    return [
        SourceSpec(**{key: row[key] for key in ("id", "name", "url", "protocol", "format", "enabled")})
        for row in chosen
    ]


def _atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=path.parent, suffix=".tmp", delete=False
        ) as handle:
            temporary = handle.name
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary:
            Path(temporary).unlink(missing_ok=True)


def summarize(records: list[dict]) -> dict:
    healthy = [r for r in records if r["healthy"]]
    enabled = [r for r in records if r["selected"]]
    failed = [r for r in records if not r["healthy"]]
    return {
        "audited_feeds": len(records),
        "audited_urls": len({r["url"] for r in records}),
        "healthy_feeds": len(healthy),
        "healthy_urls": len({r["url"] for r in healthy}),
        "healthy_publishers": len({r["publisher"] for r in healthy}),
        "enabled_feeds": len(enabled),
        "enabled_urls": len({r["url"] for r in enabled}),
        "enabled_publishers": len({r["publisher"] for r in enabled}),
        "failed_feeds": len(failed),
        "failed_urls": len({r["url"] for r in failed}),
        "excluded_healthy_feeds": len(healthy) - len(enabled),
        "enabled_protocols": dict(Counter(r["protocol"] for r in enabled)),
        "enabled_formats": dict(Counter(r["format"] for r in enabled)),
    }


async def _run_audit(args) -> dict:
    payload = json.loads(args.input.read_text(encoding="utf-8"))
    rows = payload.get("entries") if isinstance(payload, dict) else payload
    if not isinstance(rows, list) or not all(
        isinstance(r, dict) and isinstance(r.get("url"), str) for r in rows
    ):
        raise ValueError("input must be a source array or an audit object with entries")
    unique = {}
    for row in rows:
        protocol = "http" if row.get("protocol", "http") == "https" else row.get("protocol", "http")
        unique.setdefault((row["url"], protocol), row)
    rows = list(unique.values())
    if len(rows) > 600:
        raise ValueError("audit hard limit: at most 600 distinct source URLs/protocols per invocation")
    records = []
    started = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    def persist(finished=False):
        selected = select_sources(records, args.max_feeds)
        save_sources(args.catalog, selected)
        report = {
            "schema_version": 1,
            "started_at": started,
            "finished_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            if finished
            else None,
            "last_saved_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "policy": {
                "concurrency": args.concurrency,
                "total_source_timeout_seconds": args.timeout,
                "max_decompressed_bytes": 5000000,
                "max_candidates_per_feed": 100000,
                "max_redirects": 5,
                "public_dns_only": True,
                "trust_env": False,
                "proxy_connections_tested": False,
            },
            "summary": summarize(records),
            "entries": records,
        }
        _atomic_json(args.output, report)
        return report

    for offset in range(0, len(rows), args.batch_size):
        records.extend(
            await audit_sources(rows[offset : offset + args.batch_size], args.concurrency, args.timeout)
        )
        report = persist()
        print(
            json.dumps({"batch_start": offset, "summary": report["summary"]}, ensure_ascii=False), flush=True
        )
    return persist(finished=True)


def main(argv=None) -> int:
    """Run foreground; replace catalog only with this run's healthy audited feeds."""
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(
        description="Audit public proxy feeds and atomically persist every batch"
    )
    parser.add_argument(
        "--input", type=Path, default=root / "sources.json", help="source array or prior source-audit.json"
    )
    parser.add_argument("--output", type=Path, default=root / "docs" / "source-audit.json")
    parser.add_argument(
        "--catalog", type=Path, default=root / "sources.json", help="rewritten using only healthy feeds"
    )
    parser.add_argument("--concurrency", type=int, default=10)
    parser.add_argument("--timeout", type=float, default=15)
    parser.add_argument("--batch-size", type=int, default=80)
    parser.add_argument("--max-feeds", type=int, default=140)
    args = parser.parse_args(argv)
    if not 1 <= args.concurrency <= 12 or not 1 <= args.batch_size <= 100 or not 1 <= args.max_feeds <= 500:
        parser.error("concurrency 1..12; batch-size 1..100; max-feeds 1..500")
    if not math.isfinite(args.timeout) or not 0 < args.timeout <= 300:
        parser.error("timeout must be finite and between 0 and 300 seconds")
    report = asyncio.run(_run_audit(args))
    print(json.dumps(report["summary"], ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
