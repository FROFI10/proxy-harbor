import json

import pytest
from pydantic import ValidationError


@pytest.mark.parametrize(
    "change",
    [
        {"check_concurrency": 0},
        {"check_concurrency": 401},
        {"source_concurrency": 25},
        {"collect_interval": 1},
        {"check_timeout": -1},
        {"connect_timeout": 0},
        {"source_timeout": 100},
        {"max_per_cycle": 100001},
        {"max_candidates": 500001},
        {"retention_days": 0},
        {"freshness": 0},
        {"recheck_interval": 0},
        {"auto_collect": "yes"},
        {"unknown_setting": True},
        {"http_probe_url": "file:///etc/passwd"},
        {"http_probe_url": "http://127.0.0.1/ip"},
        {"http_probe_url": "http://10.0.0.1/ip"},
        {"http_probe_url": "http://localhost/ip"},
        {"http_probe_url": "http://user:password@api.ipify.org/"},
        {"https_probe_url": "http://api.ipify.org/"},
        {"https_probe_url": "https://[::1]/"},
        {"https_probe_url": "https://api.ipify.org:0/"},
        {"http_probe_url": "http://2130706433/"},
        {"http_probe_url": "http://myhost.local/"},
        {"http_probe_url": "http://host.home/ip"},
        {"http_probe_url": "http://224.0.0.1/ip"},
        {"https_probe_url": "https://[ff0e::1]/ip"},
        {"http_probe_url": "http://myhost..com/ip"},
        {"http_probe_url": "http://host.example\\\\file/ip"},
    ],
)
def test_settings_reject_unsafe_values(change):
    from proxyharbor.config import Settings

    with pytest.raises(ValidationError):
        Settings(**change)



def test_defaults_can_be_loaded_without_creating_config(tmp_path):
    from proxyharbor.config import Settings, load_settings

    path = tmp_path / "config.json"
    settings = load_settings(path)
    assert isinstance(settings, Settings)
    assert settings.model_dump() == {
        "auto_collect": True,
        "collect_interval": 900,
        "check_concurrency": 120,
        "source_concurrency": 10,
        "check_timeout": 4.0,
        "connect_timeout": 1.5,
        "source_timeout": 15.0,
        "max_per_cycle": 20000,
        "max_candidates": 100000,
        "recheck_interval": 600,
        "freshness": 600,
        "retention_days": 3,
        "http_probe_url": "http://api.ipify.org?format=json",
        "https_probe_url": "https://api.ipify.org?format=json",
    }
    assert not path.exists()


def test_settings_round_trip_atomically(tmp_path):
    from proxyharbor.config import Settings, load_settings, save_settings

    path = tmp_path / "nested" / "config.json"
    settings = Settings(auto_collect=False, check_concurrency=37)
    save_settings(path, settings)
    assert load_settings(path) == settings
    assert json.loads(path.read_text(encoding="utf-8"))["check_concurrency"] == 37
    save_settings(path, Settings(check_concurrency=41))
    assert load_settings(path).check_concurrency == 41
    assert list(path.parent.glob("*.tmp")) == []

