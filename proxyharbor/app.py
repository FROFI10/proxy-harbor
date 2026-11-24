"""Same-origin, loopback FastAPI service and web dashboard."""

import asyncio
import logging
import os
import tempfile
import uuid
from contextlib import asynccontextmanager
from dataclasses import asdict, fields, replace
from pathlib import Path
from typing import Literal

import aiohttp
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi import Path as ApiPath
from fastapi.exceptions import RequestValidationError
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, ValidationError, create_model, field_validator

from . import __version__
from .config import Settings, load_settings, save_settings
from .security import LocalBoundaryMiddleware
from .service import ProxyService

logger = logging.getLogger("proxyharbor.api")

SettingsUpdate = create_model(
    "SettingsUpdate", __config__=ConfigDict(extra="forbid", strict=True),
    **{name: (field.annotation | None, None) for name, field in Settings.model_fields.items()},
)


class SourceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    name: str = Field(min_length=1, max_length=256)
    url: str = Field(min_length=1, max_length=4096)
    protocol: Literal["http", "socks4", "socks5"] = "http"
    format: Literal["text", "html", "json", "csv"] = "text"
    enabled: bool = True

    @field_validator("url")
    @classmethod
    def public_url(cls, value):
        from .sources import validate_source_url
        return validate_source_url(value)

    @field_validator("name")
    @classmethod
    def plain_name(cls, value):
        if not value.strip() or any(ord(char) < 32 or ord(char) == 127 for char in value):
            raise ValueError("Название должно быть непустым текстом без управляющих символов")
        return value


class SourceToggle(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    enabled: bool


class ImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    text: str = Field(min_length=1, max_length=1_000_000)
    protocol: Literal["http", "socks4", "socks5"] = "http"


class ProxyReport(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    ok: bool


async def _complete_operation(operation):
    """Defer request cancellation until the protected operation has settled."""
    task = asyncio.create_task(operation)
    cancellation = None
    while True:
        try:
            result = await asyncio.shield(task)
            break
        except asyncio.CancelledError as error:
            if task.cancelled():
                raise
            cancellation = error
        except Exception:
            if cancellation is not None:
                raise cancellation from None
            raise
    if cancellation is not None:
        raise cancellation
    return result


def _read_optional_file(path):
    try:
        return path.read_bytes()
    except FileNotFoundError:
        return None


def _restore_file(path, previous):
    """Restore the exact preimage (or absence) using an atomic replacement."""
    if _read_optional_file(path) == previous:
        return
    if previous is None:
        path.unlink(missing_ok=True)
        return
    descriptor, temporary = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(previous)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def create_app(*, root=None, settings=None, storage=None, service=None):
    root_path = Path(root or Path(__file__).resolve().parent.parent).resolve()

    @asynccontextmanager
    async def lifespan(application):
        nonlocal settings, storage, service
        settings = settings or load_settings(root_path / "config.json")
        if storage is None:
            from .storage import Storage
            storage = Storage(root_path / "data" / "proxies.sqlite3")
        await storage.open()
        try:
            if service is None:
                from .sources import load_sources
                registry = root_path / "data" / "sources.json"
                sources = load_sources(registry if registry.exists() else root_path / "sources.json")
                service = ProxyService(storage, settings, sources)
            await storage.upsert_sources(service.sources)
            application.state.storage = storage
            application.state.service = service
            application.state.root = root_path
            application.state.configuration_lock = asyncio.Lock()
            application.state.discovery_lock = asyncio.Lock()
            await service.start_scheduler()
            yield
        finally:
            try:
                if service is not None:
                    await service.close()
            finally:
                await storage.close()

    application = FastAPI(title="Proxy Harbor", version=__version__, lifespan=lifespan,
                          description="Локальный пул проверенных публичных HTTP/SOCKS прокси.",
                          docs_url=None, redoc_url=None)

    application.add_middleware(LocalBoundaryMiddleware)

    @application.exception_handler(RequestValidationError)
    async def invalid_request(_request, _error):
        return JSONResponse({"detail": "Некорректный запрос"}, status_code=422)

    @application.exception_handler(Exception)
    async def internal_error(_request, error):
        # Exception text, request URLs and tracebacks can contain credentials.
        logger.error("API request failed (%s)", type(error).__name__)
        return JSONResponse({"detail": "Внутренняя ошибка сервера"}, status_code=500,
                            headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})

    static_directory = Path(__file__).resolve().parent / "static"
    application.mount("/static", StaticFiles(directory=static_directory), name="static")

    @application.get("/", include_in_schema=False)
    async def dashboard():
        return FileResponse(static_directory / "index.html", media_type="text/html")

    @application.get("/favicon.ico", include_in_schema=False)
    async def favicon():
        return Response(status_code=204)

    @application.get("/docs", include_in_schema=False)
    async def documentation():
        return get_swagger_ui_html(
            openapi_url="/openapi.json", title="Proxy Harbor · API",
            swagger_js_url="/static/vendor/swagger-ui-bundle.js",
            swagger_css_url="/static/vendor/swagger-ui.css", swagger_favicon_url="/favicon.ico",
            swagger_ui_parameters={"displayRequestDuration": True, "docExpansion": "none"},
        )

    @application.get("/health", tags=["Состояние"])
    async def health():
        return {"status": "ok", "version": __version__}

    @application.get("/api/stats", tags=["Состояние"])
    async def stats(request: Request):
        current_service = request.app.state.service
        data = await request.app.state.storage.stats(freshness=current_service.settings.freshness)
        data["sources_total"] = len(current_service.sources)
        data["sources_enabled"] = sum(source.enabled for source in current_service.sources)
        data["service"] = current_service.snapshot()
        return data

    @application.get("/api/proxy", tags=["Выдача прокси"])
    async def get_proxy(
        request: Request,
        protocol: Literal["http", "socks4", "socks5"] | None = None,
        max_latency_ms: float | None = Query(default=None, gt=0, le=60000),
        https_only: bool = False,
        strategy: Literal["random", "best", "round_robin"] = "random",
        format: Literal["json", "text", "address"] = "json",
    ):
        rows = await request.app.state.storage.get_proxies(
            limit=1, protocol=protocol, max_latency_ms=max_latency_ms, https_only=https_only,
            freshness=request.app.state.service.settings.freshness, strategy=strategy,
        )
        if not rows:
            raise HTTPException(status_code=503, detail="Нет свежих проверенных прокси с такими фильтрами. "
                                "Запустите сбор или дождитесь проверки.", headers={"Retry-After": "15"})
        item = rows[0]
        if format != "json":
            return PlainTextResponse(item["address"] + "\n" if format == "address" else item["url"] + "\n")
        return {**item, "proxy": item["url"]}

    @application.get("/api/proxies/export", tags=["Выдача прокси"])
    async def export_proxies(
        request: Request,
        protocol: Literal["http", "socks4", "socks5"] | None = None,
        max_latency_ms: float | None = Query(default=None, gt=0, le=60000),
        https_only: bool = False,
        limit: int = Query(default=1000, ge=1, le=10000),
        format: Literal["text", "json", "address"] = "text",
    ):
        data = await request.app.state.storage.list_proxies(
            limit=limit, offset=0, protocol=protocol, max_latency_ms=max_latency_ms,
            https_only=https_only, freshness=request.app.state.service.settings.freshness,
            status="alive", sort="latency",
        )
        if format == "json":
            return JSONResponse({**data, "count": len(data["items"])},
                                headers={"Content-Disposition": 'attachment; filename="proxies.json"'})
        field = "address" if format == "address" else "url"
        text = "".join(item[field] + "\n" for item in data["items"])
        return PlainTextResponse(text, headers={"Content-Disposition": 'attachment; filename="proxies.txt"'})

    @application.get("/api/proxies/batch", tags=["Выдача прокси"])
    async def get_proxy_batch(
        request: Request,
        count: int = Query(default=10, ge=1, le=1000),
        protocol: Literal["http", "socks4", "socks5"] | None = None,
        max_latency_ms: float | None = Query(default=None, gt=0, le=60000),
        https_only: bool = False,
        strategy: Literal["random", "best", "round_robin"] = "random",
        format: Literal["json", "text", "address"] = "json",
    ):
        rows = await request.app.state.storage.get_proxies(
            limit=count, protocol=protocol, max_latency_ms=max_latency_ms, https_only=https_only,
            freshness=request.app.state.service.settings.freshness, strategy=strategy,
        )
        if not rows:
            raise HTTPException(status_code=503, detail="Нет свежих рабочих прокси с такими фильтрами.",
                                headers={"Retry-After": "15"})
        if format != "json":
            field = "address" if format == "address" else "url"
            return PlainTextResponse("".join(item[field] + "\n" for item in rows))
        return {"items": rows, "count": len(rows), "requested": count}

    @application.get("/api/proxies", tags=["Пул прокси"])
    async def list_proxies(
        request: Request,
        limit: int = Query(default=50, ge=1, le=500),
        offset: int = Query(default=0, ge=0, le=1000000),
        protocol: Literal["http", "socks4", "socks5"] | None = None,
        max_latency_ms: float | None = Query(default=None, gt=0, le=60000),
        https_only: bool = False,
        status: Literal["alive", "pending", "dead", "all"] = "alive",
        sort: Literal["latency", "recent", "requests"] = "latency",
        query: str | None = Query(default=None, max_length=120),
    ):
        data = await request.app.state.storage.list_proxies(
            limit=limit, offset=offset, protocol=protocol, max_latency_ms=max_latency_ms,
            https_only=https_only, freshness=request.app.state.service.settings.freshness,
            status=status, sort=sort, query=query,
        )
        return {**data, "limit": limit, "offset": offset}

    @application.get("/api/settings", tags=["Настройки"])
    async def get_settings(request: Request):
        return request.app.state.service.settings.model_dump()

    @application.patch("/api/settings", tags=["Настройки"])
    async def update_settings(request: Request, body: SettingsUpdate):
        async with request.app.state.configuration_lock:
            current_service = request.app.state.service
            try:
                validated = Settings.model_validate({
                    **current_service.settings.model_dump(), **body.model_dump(exclude_unset=True),
                })
            except ValidationError as error:
                raise HTTPException(422, detail="Некорректные настройки") from error
            async def persist_settings():
                try:
                    await asyncio.to_thread(save_settings, request.app.state.root / "config.json", validated)
                except OSError as error:
                    logger.error("Settings persistence failed (%s)", type(error).__name__)
                    raise HTTPException(500, detail="Не удалось сохранить настройки") from error
                current_service.apply_settings(validated)

            await _complete_operation(persist_settings())
            return validated.model_dump()

    @application.post("/api/collect", tags=["Сбор и проверка"])
    async def collect(request: Request):
        started = await request.app.state.service.start("collect")
        return {"started": started, "message": "Сбор запущен" if started else "Цикл уже выполняется"}

    @application.post("/api/recheck", tags=["Сбор и проверка"])
    async def recheck(request: Request):
        started = await request.app.state.service.start("recheck")
        return {"started": started, "message": "Проверка запущена" if started else "Цикл уже выполняется"}

    @application.post("/api/stop", tags=["Сбор и проверка"])
    async def stop(request: Request):
        stopped = await request.app.state.service.stop()
        return {"stopped": stopped, "message": "Текущий цикл остановлен" if stopped else "Нет активного цикла"}

    @application.get("/api/runs", tags=["Состояние"])
    async def runs(request: Request, limit: int = Query(default=20, ge=1, le=100)):
        items = await request.app.state.storage.list_runs(limit=limit)
        return {"items": items, "total": len(items)}

    async def source_rows(request):
        database_rows = {item["id"]: item for item in await request.app.state.storage.list_sources()}
        result = []
        for spec in request.app.state.service.sources:
            result.append({
                "last_fetch": None, "found": 0, "added": 0, "last_error": None, "elapsed_ms": None,
                **database_rows.get(spec.id, {}), **asdict(spec),
            })
        return result

    async def persist_sources(request, updated):
        from .models import SourceSpec
        from .sources import save_sources

        async def persist():
            current_storage = request.app.state.storage
            current_service = request.app.state.service
            registry = request.app.state.root / "data" / "sources.json"
            previous_file = await asyncio.to_thread(_read_optional_file, registry)
            previous_database = [
                SourceSpec(**{field.name: row[field.name] for field in fields(SourceSpec) if field.name in row})
                for row in await current_storage.list_sources()
            ]
            database_touched = False
            try:
                await asyncio.to_thread(save_sources, registry, updated)
                database_touched = True
                await current_storage.upsert_sources(updated)
                retained_ids = {spec.id for spec in updated}
                for spec in current_service.sources:
                    if spec.id not in retained_ids:
                        await current_storage.set_source_enabled(spec.id, False)
            except BaseException as error:
                if isinstance(error, Exception) and not isinstance(error, ValueError):
                    logger.error("Source registry persistence failed (%s)", type(error).__name__)
                try:
                    if database_touched:
                        try:
                            await current_storage.upsert_sources(previous_database)
                        finally:
                            previous_ids = {spec.id for spec in previous_database}
                            for spec in updated:
                                if spec.id not in previous_ids:
                                    await current_storage.set_source_enabled(spec.id, False)
                finally:
                    await asyncio.to_thread(_restore_file, registry, previous_file)
                if isinstance(error, ValueError):
                    raise HTTPException(422, detail="Некорректный каталог источников") from error
                if not isinstance(error, Exception):
                    raise
                raise HTTPException(500, detail="Не удалось сохранить каталог источников") from error
            current_service.sources = list(updated)

        await _complete_operation(persist())

    @application.get("/api/sources", tags=["Источники"])
    async def get_sources(request: Request):
        items = await source_rows(request)
        return {"items": items, "total": len(items)}

    @application.post("/api/sources", status_code=201, tags=["Источники"])
    async def add_source(request: Request, body: SourceCreate):
        from .models import SourceSpec
        async with request.app.state.configuration_lock:
            existing = request.app.state.service.sources
            if len(existing) >= 500:
                raise HTTPException(422, detail="Лимит каталога — 500 источников")
            if any(spec.url == body.url and spec.protocol == body.protocol for spec in existing):
                raise HTTPException(409, detail="Этот URL и протокол уже есть в каталоге")
            spec = SourceSpec(id=uuid.uuid4().hex, **body.model_dump())
            await persist_sources(request, [*existing, spec])
            return next(item for item in await source_rows(request) if item["id"] == spec.id)

    @application.patch("/api/sources/{source_id}", tags=["Источники"])
    async def toggle_source(request: Request, source_id: str, body: SourceToggle):
        async with request.app.state.configuration_lock:
            existing = request.app.state.service.sources
            if not any(spec.id == source_id for spec in existing):
                raise HTTPException(404, detail="Источник не найден")
            updated = [replace(spec, enabled=body.enabled) if spec.id == source_id else spec for spec in existing]
            await persist_sources(request, updated)
            return next(item for item in await source_rows(request) if item["id"] == source_id)

    @application.delete("/api/sources/{source_id}", tags=["Источники"])
    async def delete_source(request: Request, source_id: str):
        async with request.app.state.configuration_lock:
            existing = request.app.state.service.sources
            if not any(spec.id == source_id for spec in existing):
                raise HTTPException(404, detail="Источник не найден")
            await persist_sources(request, [spec for spec in existing if spec.id != source_id])
            return {"deleted": True}

    @application.post("/api/import", tags=["Пул прокси"])
    async def import_candidates(request: Request, body: ImportRequest):
        from .parsing import parse_candidates
        candidates = await asyncio.to_thread(
            parse_candidates, body.text, protocol=body.protocol,
            max_items=request.app.state.service.settings.max_candidates,
        )
        if not candidates:
            raise HTTPException(422, detail="Не найдено корректных публичных IP:port. "
                                "Частные адреса и прокси с авторизацией не принимаются.")
        added = await request.app.state.storage.add_candidates(candidates, "manual-import")
        return {"parsed": len(candidates), "added": added}

    @application.post("/api/proxies/{proxy_id}/report", tags=["Пул прокси"])
    async def report_proxy(request: Request, body: ProxyReport,
                           proxy_id: int = ApiPath(ge=1, le=9223372036854775807)):
        found = await request.app.state.storage.report_proxy(proxy_id, body.ok)
        if not found:
            raise HTTPException(404, detail="Прокси не найден")
        return {"ok": True}

    @application.post("/api/sources/discover", tags=["Источники"])
    async def discover_sources(request: Request):
        from .sources import discover_github_sources
        lock = request.app.state.discovery_lock
        if lock.locked():
            raise HTTPException(409, detail="Поиск источников уже выполняется")
        async with lock:
            try:
                async with asyncio.timeout(60):
                    async with aiohttp.ClientSession(trust_env=False) as session:
                        discovered = await discover_github_sources(
                            session, list(request.app.state.service.sources), max_repos=20,
                        )
            except TimeoutError as error:
                raise HTTPException(504, detail="Поиск GitHub превысил 60 секунд. Попробуйте позже.") from error
            except Exception as error:
                raise HTTPException(502, detail="Поиск GitHub не завершён: " + str(error)) from error
            async with request.app.state.configuration_lock:
                updated = list(request.app.state.service.sources)
                keys = {(item.url, item.protocol) for item in updated}
                ids = {item.id for item in updated}
                added = 0
                for spec in discovered:
                    if len(updated) >= 500:
                        break
                    if (spec.url, spec.protocol) in keys or spec.id in ids:
                        continue
                    updated.append(spec)
                    keys.add((spec.url, spec.protocol))
                    ids.add(spec.id)
                    added += 1
                if added:
                    await persist_sources(request, updated)
                return {"added": added, "message": f"Добавлено новых источников: {added}"}

    return application


app = create_app()
