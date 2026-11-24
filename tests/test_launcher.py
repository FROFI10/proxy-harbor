import pytest


def test_launcher_only_accepts_loopback_hosts_and_valid_ports():
    from run import parse_arguments

    defaults = parse_arguments([])
    assert defaults.host == "127.0.0.1"
    assert defaults.port == 8765
    assert defaults.open_browser is False
    assert defaults.no_auto is False
    assert parse_arguments(["--port", "9876", "--no-auto"]).port == 9876
    with pytest.raises(SystemExit):
        parse_arguments(["--host", "0.0.0.0"])
    with pytest.raises(SystemExit):
        parse_arguments(["--port", "65536"])
    with pytest.raises(SystemExit):
        parse_arguments(["--port", "0"])


def test_single_instance_lock_rejects_overlap_and_releases_cleanly(tmp_path):
    from proxyharbor.instance import SingleInstanceLock

    path = tmp_path / "data" / "service.lock"
    with SingleInstanceLock(path):
        with pytest.raises(RuntimeError, match="запущен"):
            with SingleInstanceLock(path):
                pytest.fail("second instance acquired the same lock")
    with SingleInstanceLock(path):
        assert path.exists()


def test_launcher_builds_local_single_worker_runtime_from_its_own_folder(tmp_path, monkeypatch):
    import uvicorn

    import run
    from proxyharbor.config import load_settings

    seen = {}

    def factory(**options):
        seen.update(options)
        return "test-app-handle"

    class Server:
        started = True

        def __init__(self, config):
            seen["config"] = config

        def run(self):
            seen["ran"] = True

    monkeypatch.setattr(run, "PROJECT_ROOT", tmp_path, raising=False)
    monkeypatch.setattr(run, "create_app", factory, raising=False)
    monkeypatch.setattr(uvicorn, "Server", Server)
    assert run.main(["--port", "9876", "--no-auto"]) == 0
    assert seen["root"] == tmp_path.resolve()
    assert seen["settings"].auto_collect is False
    assert seen["config"].host == "127.0.0.1"
    assert seen["config"].port == 9876
    assert seen["config"].workers == 1
    assert seen["config"].proxy_headers is False
    assert seen["ran"] is True
    assert load_settings(tmp_path / "config.json").auto_collect is True


def test_version_command_works_outside_the_project_folder(tmp_path):
    import subprocess
    import sys
    from pathlib import Path

    response = subprocess.run([sys.executable, str(Path(__file__).resolve().parents[1] / "run.py"), "--version"],
                              cwd=tmp_path, capture_output=True, text=True, timeout=20)
    assert response.returncode == 0
    assert response.stdout.strip() == "1.0.0"


def test_browser_is_opened_only_after_server_is_ready(monkeypatch):
    import webbrowser
    from types import SimpleNamespace

    import run

    opened = []
    monkeypatch.setattr(webbrowser, "open", lambda url: opened.append(url))
    run._open_when_ready(SimpleNamespace(started=True, should_exit=False), "http://127.0.0.1:8765")
    assert opened == ["http://127.0.0.1:8765"]
    run._open_when_ready(SimpleNamespace(started=False, should_exit=True), "http://127.0.0.1:9999")
    assert len(opened) == 1



