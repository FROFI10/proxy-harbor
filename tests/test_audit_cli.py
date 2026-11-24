import pytest


def test_large_catalog_keeps_healthy_variants_after_publisher_diversity():
    from scripts.audit_sources import select_sources

    rows = [
        {"id": "a", "name": "A", "url": "https://example.com/a.txt", "protocol": "http", "format": "text",
         "publisher": "example", "healthy": True},
        {"id": "b", "name": "B", "url": "https://example.com/b.txt", "protocol": "http", "format": "text",
         "publisher": "example", "healthy": True},
        {"id": "bad", "name": "Bad", "url": "https://example.com/bad.txt", "protocol": "http", "format": "text",
         "publisher": "other", "healthy": False},
    ]
    selected = select_sources(rows, max_feeds=500)
    assert [item.id for item in selected] == ["a", "b"]
    assert all(item.enabled for item in selected)
    assert rows[2]["selected"] is False


def test_audit_cli_uses_the_same_500_feed_limit_as_the_service(monkeypatch):
    from scripts import audit_sources

    observed = []

    async def run(args):
        observed.append(args.max_feeds)
        return {"summary": {"enabled_feeds": 0}}

    monkeypatch.setattr(audit_sources, "_run_audit", run)
    assert audit_sources.main(["--max-feeds", "500"]) == 0
    assert observed == [500]
    with pytest.raises(SystemExit):
        audit_sources.main(["--max-feeds", "501"])
