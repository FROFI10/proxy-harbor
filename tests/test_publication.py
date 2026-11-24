"""Publication guards: portable source and no local private artifacts."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED = {".git", ".venv", "__pycache__", ".pytest_cache", ".ruff_cache", "data", "logs"}
TEXT_SUFFIXES = {".py", ".md", ".json", ".toml", ".txt", ".bat", ".sh", ".yml", ".yaml", ".svg", ".html", ".css", ".js"}


def test_publishable_text_has_no_absolute_personal_home_paths():
    pattern = re.compile(r"(?i)(?:\b[A-Z]:[\\/]Users[\\/]|(?<![:\w])/(?:Users|home)/[^/\s]+/)")
    findings = []
    for path in ROOT.rglob("*"):
        if not path.is_file() or any(part in EXCLUDED for part in path.relative_to(ROOT).parts):
            continue
        if path.suffix not in TEXT_SUFFIXES:
            continue
        if pattern.search(path.read_text(encoding="utf-8", errors="replace")):
            findings.append(path.relative_to(ROOT).as_posix())
    assert findings == [], "Personal absolute paths in publishable files: " + ", ".join(findings)


def test_windows_launchers_do_not_depend_on_an_agent_profile():
    for filename in ("setup.bat", "start.bat"):
        script = (ROOT / filename).read_text(encoding="utf-8").lower()
        assert "hermes" not in script
        assert "%~dp0" in script


def test_gitignore_covers_private_runtime_and_raw_session_reports():
    entries = set((ROOT / ".gitignore").read_text(encoding="utf-8").splitlines())
    required = {".venv/", "data/", "logs/", "config.json", ".env", "docs/*-selection.json", "docs/*-check.json"}
    assert required <= entries


def test_published_seed_is_included_and_fresh_clone_can_start(tmp_path):
    from shutil import copyfile

    from fastapi.testclient import TestClient

    from proxyharbor.app import create_app
    from proxyharbor.config import Settings
    from proxyharbor.sources import load_sources

    seed = ROOT / "sources.json"
    assert seed.is_file(), "The published project must include its startup source catalog"
    expected = load_sources(seed)
    assert len(expected) > 0
    copyfile(seed, tmp_path / "sources.json")
    application = create_app(root=tmp_path, settings=Settings(auto_collect=False))
    with TestClient(application, base_url="http://127.0.0.1:8765", client=("127.0.0.1", 51234)) as client:
        assert client.get("/health").status_code == 200
        response = client.get("/api/sources")
        assert response.status_code == 200
        assert response.json()["total"] == len(expected)
    assert (tmp_path / "data" / "proxies.sqlite3").is_file()

