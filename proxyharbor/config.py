"""Validated, local settings. Paths never depend on the caller's cwd."""

import ipaddress
import os
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, validate_assignment=True)

    auto_collect: bool = True
    collect_interval: int = Field(default=900, ge=60, le=86400)
    check_concurrency: int = Field(default=120, ge=1, le=400)
    source_concurrency: int = Field(default=10, ge=1, le=24)
    check_timeout: float = Field(default=4.0, ge=1.0, le=30.0)
    connect_timeout: float = Field(default=1.5, ge=0.2, le=5.0)
    source_timeout: float = Field(default=15.0, ge=5.0, le=60.0)
    max_per_cycle: int = Field(default=20000, ge=1, le=100000)
    max_candidates: int = Field(default=100000, ge=1000, le=500000)
    recheck_interval: int = Field(default=600, ge=60, le=86400)
    freshness: int = Field(default=600, ge=60, le=86400)
    retention_days: int = Field(default=3, ge=1, le=30)
    http_probe_url: str = "http://api.ipify.org?format=json"
    https_probe_url: str = "https://api.ipify.org?format=json"

    @field_validator("http_probe_url", "https_probe_url")
    @classmethod
    def validate_probe_url(cls, value: str, info) -> str:
        try:
            from .sources import validate_source_url
            validate_source_url(value)
            parts = urlsplit(value)
            scheme = "https" if info.field_name == "https_probe_url" else "http"
            host = parts.hostname or ""
            port = parts.port
            if (
                len(value) > 2048
                or parts.scheme != scheme
                or not host
                or parts.username is not None
                or parts.password is not None
                or parts.fragment
                or any(ord(char) <= 32 for char in value)
                or port is not None and not 1 <= port <= 65535
            ):
                raise ValueError("Требуется публичный URL без учётных данных")
            try:
                address = ipaddress.ip_address(host)
            except ValueError:
                lower = host.lower().rstrip(".")
                if "." not in lower or lower.endswith((".local", ".localhost", ".internal", ".lan")):
                    raise ValueError("Локальные имена запрещены") from None
                if lower.replace(".", "").isdigit():
                    raise ValueError("Неканонический числовой IP запрещён") from None
            else:
                if not address.is_global:
                    raise ValueError("Частные и специальные IP запрещены")
        except (ValueError, UnicodeError) as error:
            raise ValueError(f"Некорректный адрес проверки: {error}") from error
        return value


def load_settings(path: str | Path) -> Settings:
    target = Path(path)
    if not target.exists():
        return Settings()
    return Settings.model_validate_json(target.read_text(encoding="utf-8-sig"))


def save_settings(path: str | Path, settings: Settings) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=target.name + ".", suffix=".tmp", dir=target.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(settings.model_dump_json(indent=2) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)

