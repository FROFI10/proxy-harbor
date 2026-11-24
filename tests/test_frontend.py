"""Browser behavior tests against a controlled same-origin API, never live proxy feeds."""

from __future__ import annotations

import copy
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "proxyharbor" / "static"


def stats_payload(**changes):
    payload = {
        "total": 0, "alive": 0, "pending": 0, "dead": 0, "stale": 0, "https": 0,
        "average_latency_ms": None, "protocols": {"http": 0, "socks4": 0, "socks5": 0},
        "requests": 0, "sources_total": 0, "sources_enabled": 0, "last_check": None,
        "service": {
            "state": "idle", "running": False, "stage": "Ожидание", "started_at": None,
            "finished_at": None, "cycle_id": None, "sources_done": 0, "sources_total": 0,
            "parsed": 0, "added": 0, "checked": 0, "working": 0, "queue": 0, "errors": 0,
            "last_error": None, "next_run_at": None, "logs": [], "history": [],
        },
    }
    payload.update(changes)
    return payload


class ControlledAPI:
    def proxy_response(self, query):
        items = copy.deepcopy(self.proxies)
        status = query.get("status", ["alive"])[0]
        if status != "all":
            items = [row for row in items if row["status"] == status]
        if status == "alive":
            cutoff = time.time() - self.settings["freshness"]
            items = [row for row in items if (row.get("last_checked") or 0) >= cutoff]
        protocol = query.get("protocol", [""])[0]
        if protocol:
            items = [row for row in items if row["protocol"] == protocol]
        if query.get("https_only", ["false"])[0] == "true":
            items = [row for row in items if row["supports_https"]]
        latency = query.get("max_latency_ms", [""])[0]
        if latency:
            items = [row for row in items if row["latency_ms"] is not None and row["latency_ms"] <= float(latency)]
        search = query.get("query", [""])[0].lower()
        if search:
            items = [row for row in items if search in row["url"].lower()]
        limit, offset = int(query.get("limit", [50])[0]), int(query.get("offset", [0])[0])
        return {"items": items[offset:offset + limit], "total": len(items), "limit": limit, "offset": offset}

    def __init__(self):
        self.lock = threading.RLock()
        self.requests = []
        self.failures = {}
        self.stats = stats_payload()
        self.proxies = []
        self.sources = []
        self.runs = []
        self.settings = {
            "auto_collect": True, "collect_interval": 900, "check_concurrency": 120,
            "source_concurrency": 10, "check_timeout": 4.0, "connect_timeout": 1.5,
            "source_timeout": 15.0, "max_per_cycle": 20000, "recheck_interval": 600,
            "freshness": 600, "retention_days": 3,
            "http_probe_url": "http://api.ipify.org?format=json",
            "https_probe_url": "https://api.ipify.org?format=json",
        }
        self.responses = {}
        self.csp = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
                    "img-src 'self' data:; connect-src 'self'; font-src 'self'; "
                    "base-uri 'none'; frame-ancestors 'none'; form-action 'self'")
        api = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def do_GET(self):
                self.handle_request("GET")

            def do_POST(self):
                self.handle_request("POST")

            def do_PATCH(self):
                self.handle_request("PATCH")

            def do_DELETE(self):
                self.handle_request("DELETE")

            def handle_request(self, method):
                parsed = urlparse(self.path)
                path = parsed.path
                if not path.startswith("/api/"):
                    filename = {"/": "index.html", "/static/app.css": "app.css",
                                "/static/app.js": "app.js"}.get(path)
                    if filename and (STATIC / filename).is_file():
                        content = (STATIC / filename).read_bytes()
                        content_type = {"index.html": "text/html; charset=utf-8",
                                        "app.css": "text/css; charset=utf-8",
                                        "app.js": "text/javascript; charset=utf-8"}[filename]
                        self.send_response(200)
                        self.send_header("Content-Type", content_type)
                        self.send_header("Content-Security-Policy", api.csp)
                        self.send_header("Content-Length", str(len(content)))
                        self.end_headers()
                        self.wfile.write(content)
                    else:
                        self.send_error(404)
                    return
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length)) if length else None
                query = parse_qs(parsed.query, keep_blank_values=True)
                with api.lock:
                    api.requests.append({"method": method, "path": path, "query": query, "body": body})
                    if path in api.failures:
                        status, payload = api.failures[path]
                    elif (method, path) in api.responses:
                        response = api.responses[(method, path)]
                        status, payload = response(body, query) if callable(response) else response
                    elif path == "/api/stats":
                        status, payload = 200, copy.deepcopy(api.stats)
                    elif path == "/api/sources":
                        status, payload = 200, {"items": copy.deepcopy(api.sources), "total": len(api.sources)}
                    elif path == "/api/runs":
                        status, payload = 200, {"items": copy.deepcopy(api.runs), "total": len(api.runs)}
                    elif path == "/api/settings":
                        status, payload = 200, copy.deepcopy(api.settings)
                    elif path == "/api/proxies":
                        status, payload = 200, api.proxy_response(query)
                    else:
                        status, payload = 404, {"detail": "Неизвестный тестовый маршрут"}
                if isinstance(payload, str):
                    content, content_type = payload.encode(), "text/plain; charset=utf-8"
                else:
                    content, content_type = json.dumps(payload, ensure_ascii=False).encode(), "application/json"
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                try:
                    self.wfile.write(content)
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                    pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)

    def matching(self, path, method="GET"):
        with self.lock:
            return [copy.deepcopy(r) for r in self.requests if r["path"] == path and r["method"] == method]


@pytest.fixture
def browser():
    # A session-scoped sync driver leaves its asyncio loop marked as running
    # between tests and breaks later pytest-asyncio backend tests.
    with sync_playwright() as playwright:
        if Path(playwright.chromium.executable_path).exists():
            instance = playwright.chromium.launch(
                headless=True, executable_path=playwright.chromium.executable_path
            )
        else:
            # Native Edge is available on Windows while Chromium is being installed.
            instance = playwright.chromium.launch(channel="msedge", headless=True)
        yield instance
        instance.close()


@pytest.fixture
def api():
    instance = ControlledAPI()
    yield instance
    instance.close()


@pytest.fixture
def page(browser):
    context = browser.new_context(viewport={"width": 1440, "height": 1000}, locale="ru-RU")
    instance = context.new_page()
    instance.set_default_timeout(2500)
    errors = []
    instance.on("pageerror", lambda error: errors.append(str(error)))
    yield instance
    context.close()
    assert not errors, "Uncaught browser errors: " + repr(errors)


def open_ui(page, api):
    page.goto(api.url)


def test_navigation_changes_visible_section_and_title(page, api):
    open_ui(page, api)
    expect(page.get_by_role("heading", name="Обзор", exact=True)).to_be_visible()
    for label, view in [("Прокси", "proxies"), ("Источники", "sources"),
                        ("API", "api"), ("Настройки", "settings"), ("Обзор", "overview")]:
        page.get_by_role("link", name=label, exact=True).click()
        expect(page.locator(f"#view-{view}")).to_be_visible()
        expect(page.locator("#page-title")).to_have_text(label)
        expect(page.get_by_role("link", name=label, exact=True)).to_have_attribute("aria-current", "page")
    page.go_back()
    expect(page.locator("#page-title")).to_have_text("Настройки")


def test_monitor_reads_real_stats_pipeline_and_history_without_html_injection(page, api):
    stats = stats_payload(total=42, alive=7, pending=19, dead=10, stale=6, https=3,
                          average_latency_ms=123.4, requests=28, sources_enabled=4, sources_total=5)
    stats["service"].update(
        state="checking", running=True, stage="Проверка кандидатов", parsed=42, added=19,
        checked=12, working=7, queue=30, sources_done=4, sources_total=5, errors=1,
        logs=[{"time": 1700000000, "level": "warning", "message": "<img src=x onerror=alert(1)>"}],
        history=[{"time": 1700000000, "alive": 2, "checked": 8},
                 {"time": 1700000060, "alive": 7, "checked": 12},
                 {"time": 1700000120, "alive": 4, "checked": 14}],
    )
    api.stats = stats
    open_ui(page, api)
    expect(page.locator("#kpi-alive")).to_have_text("7")
    expect(page.locator("#kpi-total")).to_have_text("42")
    expect(page.locator("#kpi-stale")).to_have_text("6")
    expect(page.locator("#kpi-latency")).to_have_text("123 мс")
    expect(page.locator("#pipeline-queue")).to_have_text("30")
    expect(page.locator("#service-state")).to_have_text("Проверка")
    expect(page.locator("#service-stage")).to_have_text("Проверка кандидатов")
    expect(page.locator("#source-progress")).to_have_attribute("aria-valuenow", "4")
    expect(page.locator("#activity-log")).to_contain_text("<img src=x onerror=alert(1)>")
    assert page.locator("#activity-log img").count() == 0
    expect(page.locator("#history-chart")).to_be_visible()
    assert len(page.locator("#history-chart polyline").get_attribute("points").split()) == 3
    expect(page.locator("#history-empty")).to_be_hidden()
    expect(page.locator("#connection-status")).to_contain_text("На связи")
    assert api.matching("/api/stats")


def test_polling_keeps_last_good_data_marks_offline_and_recovers(page, api):
    api.stats = stats_payload(total=8, alive=5)
    open_ui(page, api)
    expect(page.locator("#kpi-alive")).to_have_text("5")
    api.failures["/api/stats"] = (503, {"detail": "<script>ошибка сети</script>"})
    expect(page.locator("#connection-status")).to_contain_text("Нет связи", timeout=6000)
    expect(page.locator("#connection-banner")).to_contain_text("Показаны последние полученные данные")
    expect(page.locator("#connection-banner")).to_contain_text("<script>ошибка сети</script>")
    assert page.locator("#connection-banner script").count() == 0
    expect(page.locator("#kpi-alive")).to_have_text("5")
    assert len(api.matching("/api/stats")) >= 2
    api.failures.clear()
    api.stats = stats_payload(total=12, alive=9)
    page.get_by_role("button", name="Повторить сейчас").click()
    expect(page.locator("#kpi-alive")).to_have_text("9")
    expect(page.locator("#connection-status")).to_contain_text("На связи")
    expect(page.locator("#connection-banner")).to_be_hidden()


@pytest.mark.parametrize("action,label", [("collect", "Собрать прокси"), ("recheck", "Перепроверить")])
def test_cycle_controls_send_commands_and_confirm_state_by_readback(page, api, action, label):
    def start(_body, _query):
        api.stats["service"].update(state="checking", running=True, stage="Проверка кандидатов")
        return 200, {"started": True, "message": "<b>Цикл запущен</b>"}

    def stop(_body, _query):
        api.stats["service"].update(state="idle", running=False, stage="Ожидание")
        return 200, {"stopped": True, "message": "Цикл остановлен"}

    api.responses[("POST", f"/api/{action}")] = start
    api.responses[("POST", "/api/stop")] = stop
    open_ui(page, api)
    expect(page.get_by_role("button", name=label, exact=True)).to_be_enabled()
    expect(page.get_by_role("button", name="Остановить", exact=True)).to_be_disabled()
    page.get_by_role("button", name=label, exact=True).click()
    expect(page.locator("#service-state")).to_have_text("Проверка")
    expect(page.get_by_role("button", name="Собрать прокси", exact=True)).to_be_disabled()
    expect(page.get_by_role("button", name="Перепроверить", exact=True)).to_be_disabled()
    expect(page.get_by_role("button", name="Остановить", exact=True)).to_be_enabled()
    expect(page.locator("#notice")).to_contain_text("<b>Цикл запущен</b>")
    assert page.locator("#notice b").count() == 0
    assert len(api.matching(f"/api/{action}", "POST")) == 1
    requests = api.requests[:]
    write_index = next(i for i, request in enumerate(requests) if request["method"] == "POST")
    assert any(request["path"] == "/api/stats" for request in requests[write_index + 1:])
    page.get_by_role("button", name="Остановить", exact=True).click()
    expect(page.locator("#service-state")).to_have_text("Ожидание")
    expect(page.get_by_role("button", name=label, exact=True)).to_be_enabled()
    assert len(api.matching("/api/stop", "POST")) == 1


def proxy_row(identifier, **changes):
    host = f"9.9.9.{identifier}"
    row = {
        "id": identifier, "host": host, "port": 1080, "protocol": "socks5",
        "url": f"socks5://{host}:1080", "address": f"{host}:1080", "status": "alive",
        "latency_ms": 100, "supports_https": True, "exit_ip": host,
        "first_seen": time.time(), "last_seen": time.time(), "last_checked": time.time(),
        "successes": 1, "failures": 0, "requests": 0, "source_count": 1,
    }
    row.update(changes)
    return row


def test_proxy_filters_reset_pagination_and_use_contract_query_params(page, api):
    api.proxies = [proxy_row(i) for i in range(1, 72)]
    open_ui(page, api)
    page.get_by_role("link", name="Прокси", exact=True).click()
    expect(page.locator("#proxy-count")).to_have_text("1–50 из 71")
    expect(page.locator("#proxy-table-body tr")).to_have_count(50)
    page.get_by_label("На странице", exact=True).select_option("25")
    expect(page.locator("#proxy-count")).to_have_text("1–25 из 71")
    page.get_by_role("button", name="Следующая страница").click()
    expect(page.locator("#proxy-count")).to_have_text("26–50 из 71")
    assert api.matching("/api/proxies")[-1]["query"]["offset"] == ["25"]
    page.get_by_label("Протокол", exact=True).select_option("socks5")
    page.get_by_label("Отклик не более, мс").fill("500")
    page.get_by_label("Проверенный HTTPS", exact=True).check()
    page.get_by_label("Состояние", exact=True).select_option("all")
    page.get_by_label("Сортировка", exact=True).select_option("recent")
    page.get_by_label("Поиск по IP, порту или URL").fill("9.9.9.1")
    expect(page.locator("#proxy-count")).to_have_text("1–11 из 11")
    request = api.matching("/api/proxies")[-1]
    assert request["query"] == {
        "limit": ["25"], "offset": ["0"], "status": ["all"], "protocol": ["socks5"],
        "max_latency_ms": ["500"], "https_only": ["true"], "sort": ["recent"], "query": ["9.9.9.1"],
    }
    page.get_by_role("button", name="Сбросить фильтры").click()
    expect(page.locator("#proxy-count")).to_have_text("1–50 из 71")
    request = api.matching("/api/proxies")[-1]["query"]
    assert request["status"] == ["alive"] and "protocol" not in request and "query" not in request


def test_proxy_rows_use_server_freshness_to_distinguish_verified_stale_and_unchecked(page, api):
    api.settings["freshness"] = 30
    api.proxies = [proxy_row(1), proxy_row(2, last_checked=time.time() - 90),
                   proxy_row(3, status="pending", last_checked=None, latency_ms=None, supports_https=False),
                   proxy_row(4, status="dead", url="<svg onload=alert(1)>")]
    open_ui(page, api)
    page.get_by_role("link", name="Прокси", exact=True).click()
    page.get_by_label("Состояние", exact=True).select_option("all")
    expect(page.locator('#proxy-table-body tr[data-id="1"]')).to_contain_text("Рабочий · свежий")
    expect(page.locator('#proxy-table-body tr[data-id="2"]')).to_contain_text("Устарел")
    expect(page.locator('#proxy-table-body tr[data-id="3"]')).to_contain_text("Не проверен")
    expect(page.locator('#proxy-table-body tr[data-id="4"]')).to_contain_text("Не отвечает")
    expect(page.locator("#freshness-note")).to_contain_text("30 с")
    assert page.locator("#proxy-table-body svg").count() == 0
    assert api.matching("/api/settings")


@pytest.mark.parametrize("clipboard_denied", [False, True])
def test_copy_row_url_preserves_ipv6_and_has_accessible_manual_fallback(page, api, clipboard_denied):
    url = "socks5://[2606:4700:4700::1111]:1080"
    api.proxies = [proxy_row(1, url=url, host="2606:4700:4700::1111", exit_ip=None)]
    page.context.grant_permissions(["clipboard-read", "clipboard-write"], origin=api.url)
    if clipboard_denied:
        page.add_init_script("Object.defineProperty(navigator.clipboard, 'writeText', {value: async () => {throw new Error('denied');}})")
    open_ui(page, api)
    page.get_by_role("link", name="Прокси", exact=True).click()
    page.get_by_role("button", name=f"Скопировать URL {url}", exact=True).click()
    if clipboard_denied:
        expect(page.get_by_role("dialog", name="Копирование вручную")).to_be_visible()
        expect(page.get_by_label("Текст для копирования")).to_have_value(url)
        page.get_by_role("button", name="Закрыть окно копирования").click()
        expect(page.get_by_role("dialog", name="Копирование вручную")).to_be_hidden()
    else:
        expect(page.locator("#notice")).to_contain_text("URL скопирован")
        assert page.evaluate("navigator.clipboard.readText()") == url


@pytest.mark.parametrize("file_format", ["text", "json"])
def test_export_download_keeps_protocol_https_search_and_latency_filters(page, api, file_format):
    api.proxies = [proxy_row(1), proxy_row(2, latency_ms=900), proxy_row(3, supports_https=False)]

    def export(_body, query):
        data = api.proxy_response({**query, "status": ["alive"], "offset": ["0"]})["items"]
        return 200, "\n".join(row["url"] for row in data) + "\n" if query["format"] == ["text"] else data

    api.responses[("GET", "/api/proxies/export")] = export
    open_ui(page, api)
    page.get_by_role("link", name="Прокси", exact=True).click()
    page.get_by_label("Протокол", exact=True).select_option("socks5")
    page.get_by_label("Проверенный HTTPS", exact=True).check()
    button = page.get_by_role("button", name="Экспорт в текст" if file_format == "text" else "Экспорт в JSON")
    with page.expect_download() as pending:
        button.click()
    content = Path(pending.value.path()).read_text(encoding="utf-8")
    assert "9.9.9.1" in content and "9.9.9.2" in content and "9.9.9.3" not in content
    query = api.matching("/api/proxies/export")[-1]["query"]
    assert query == {"protocol": ["socks5"], "https_only": ["true"], "format": [file_format], "limit": ["1000"]}
    page.get_by_label("Отклик не более, мс").fill("500")
    page.get_by_label("Поиск по IP, порту или URL").fill("9.9.9.1")
    expect(page.locator("#proxy-count")).to_have_text("1–1 из 1")
    with page.expect_download() as pending:
        button.click()
    content = Path(pending.value.path()).read_text(encoding="utf-8")
    if file_format == "text":
        assert content.strip() == api.proxies[0]["url"]
    else:
        assert [row["id"] for row in json.loads(content)["items"]] == [1]
    assert "9.9.9.2" not in content
    expect(page.locator("#notice")).to_contain_text("Экспортировано")


def test_manual_import_sends_literal_text_and_shows_only_unverified_candidates(page, api):
    text = "socks5://9.9.9.1:1080\n<svg onload=alert(1)>\n"

    def import_rows(body, _query):
        api.proxies = [proxy_row(1, status="pending", last_checked=None, supports_https=False, latency_ms=None)]
        api.stats.update(total=1, pending=1, alive=0)
        return 200, {"parsed": 2, "added": 1}

    api.responses[("POST", "/api/import")] = import_rows
    open_ui(page, api)
    page.get_by_role("link", name="Прокси", exact=True).click()
    page.get_by_role("button", name="Импортировать список").click()
    expect(page.get_by_role("dialog", name="Импорт прокси")).to_be_visible()
    page.get_by_label("Список адресов").fill(text)
    page.get_by_label("Протокол для адресов без схемы").select_option("socks5")
    page.get_by_role("button", name="Добавить в реестр").click()
    expect(page.get_by_role("dialog", name="Импорт прокси")).to_be_hidden()
    expect(page.locator("#notice")).to_contain_text("Распознано: 2 · новых: 1")
    expect(page.locator("#notice")).to_contain_text("ещё не проверены")
    expect(page.locator("#proxy-table-body")).to_contain_text("Не проверен")
    assert api.matching("/api/import", "POST")[-1]["body"] == {"text": text, "protocol": "socks5"}
    assert page.locator("#proxy-table-body svg").count() == 0
    assert api.matching("/api/proxies")[-1]["query"]["status"] == ["pending"]
    assert any(request["path"] == "/api/stats" for request in api.requests[1:])


def test_source_catalog_add_toggle_delete_and_manual_discovery_read_back_changes(page, api):
    name = "<b>Тестовый издатель</b>"
    url = "https://publisher.example/proxies.txt"

    def add_source(body, _query):
        row = {"id": "source-1", **body, "last_fetch": None, "found": 0, "added": 0,
               "last_error": None, "elapsed_ms": None}
        api.sources.append(row)
        return 201, row

    def toggle_source(body, _query):
        api.sources[0]["enabled"] = body["enabled"]
        return 200, api.sources[0]

    def delete_source(_body, _query):
        api.sources.clear()
        return 200, {"deleted": True}

    def discover(_body, _query):
        api.sources.append({"id": "discovered-1", "name": "Подобранный источник", "url": url,
                            "protocol": "socks4", "format": "text", "enabled": True,
                            "last_fetch": None, "found": 0, "added": 0, "last_error": None, "elapsed_ms": None})
        return 200, {"added": 1, "message": "Добавлен 1 источник"}

    api.responses[("POST", "/api/sources")] = add_source
    api.responses[("PATCH", "/api/sources/source-1")] = toggle_source
    api.responses[("DELETE", "/api/sources/source-1")] = delete_source
    api.responses[("POST", "/api/sources/discover")] = discover
    open_ui(page, api)
    page.get_by_role("link", name="Источники", exact=True).click()
    expect(page.locator("#source-table-body")).to_contain_text("Источников пока нет")
    assert not api.matching("/api/sources/discover", "POST")
    page.get_by_role("button", name="Добавить источник", exact=True).click()
    page.get_by_label("Название источника").fill(name)
    page.get_by_label("URL источника").fill(url)
    page.get_by_label("Протокол источника").select_option("socks5")
    page.get_by_label("Формат списка").select_option("text")
    page.get_by_role("button", name="Сохранить источник").click()
    expect(page.locator("#source-table-body")).to_contain_text(name)
    assert page.locator("#source-table-body b").count() == 0
    assert api.matching("/api/sources", "POST")[-1]["body"] == {
        "name": name, "url": url, "protocol": "socks5", "format": "text", "enabled": True,
    }
    switch = page.get_by_role("switch", name=f"Состояние источника {name}")
    expect(switch).to_have_attribute("aria-checked", "true")
    switch.click()
    expect(switch).to_have_attribute("aria-checked", "false")
    assert api.matching("/api/sources/source-1", "PATCH")[-1]["body"] == {"enabled": False}
    page.once("dialog", lambda dialog: dialog.accept())
    page.get_by_role("button", name=f"Удалить источник {name}").click()
    expect(page.locator("#source-table-body")).to_contain_text("Источников пока нет")
    assert len(api.matching("/api/sources/source-1", "DELETE")) == 1
    page.get_by_role("button", name="Подобрать через GitHub").click()
    expect(page.locator("#source-table-body")).to_contain_text("Подобранный источник")
    expect(page.locator("#notice")).to_contain_text("Добавлен 1 источник")
    for index, request in enumerate(api.requests):
        if request["method"] in {"POST", "PATCH", "DELETE"}:
            assert any(row["method"] == "GET" and row["path"] == "/api/sources" for row in api.requests[index + 1:])


@pytest.mark.parametrize("reject", [False, True])
def test_settings_save_sends_typed_subset_reads_back_and_preserves_failed_drafts(page, api, reject):
    def save(body, _query):
        if reject:
            return 422, {"detail": [{"msg": "Ошибка параметра проверки"}]}
        api.settings.update(body)
        return 200, copy.deepcopy(api.settings)

    api.responses[("PATCH", "/api/settings")] = save
    open_ui(page, api)
    page.get_by_role("link", name="Настройки", exact=True).click()
    expect(page.get_by_label("Параллельных проверок")).to_have_value("120")
    page.get_by_label("Параллельных проверок").fill("42")
    page.get_by_label("Интервал сбора, с").fill("1200")
    page.get_by_label("Автоматический сбор").uncheck()
    page.get_by_label("Тайм-аут проверки, с").fill("3.5")
    page.get_by_label("Свежесть результата, с").fill("300")
    expect(page.locator("#settings-status")).to_contain_text("Не сохранено")
    page.wait_for_timeout(3100)
    expect(page.get_by_label("Свежесть результата, с")).to_have_value("300")
    page.get_by_role("button", name="Сохранить настройки").click()
    expected = {"check_concurrency": 42, "collect_interval": 1200, "auto_collect": False,
                "check_timeout": 3.5, "freshness": 300}
    if reject:
        expect(page.locator("#settings-error")).to_contain_text("Ошибка параметра проверки")
        expect(page.get_by_label("Параллельных проверок")).to_have_value("42")
        expect(page.get_by_role("button", name="Сохранить настройки")).to_be_enabled()
        page.get_by_role("button", name="Отменить изменения").click()
        expect(page.get_by_label("Параллельных проверок")).to_have_value("120")
    else:
        expect(page.locator("#settings-status")).to_contain_text("Сохранено")
        expect(page.get_by_role("button", name="Сохранить настройки")).to_be_disabled()
        patch_index = next(i for i, row in enumerate(api.requests) if row["method"] == "PATCH")
        assert any(row["method"] == "GET" and row["path"] == "/api/settings" for row in api.requests[patch_index + 1:])
        assert api.settings["auto_collect"] is False
    assert api.matching("/api/settings", "PATCH")[-1]["body"] == expected


@pytest.mark.parametrize("response_kind", ["json", "text", "unavailable"])
def test_api_builder_examples_copy_and_get_show_real_success_or_503(page, api, response_kind):
    file_format = "text" if response_kind == "text" else "json"
    row = proxy_row(1)

    def issue(_body, query):
        if response_kind == "unavailable":
            return 503, {"detail": "Нет свежих проверенных прокси"}
        return 200, row["url"] + "\n" if query["format"] == ["text"] else row

    api.responses[("GET", "/api/proxy")] = issue
    page.context.grant_permissions(["clipboard-read", "clipboard-write"], origin=api.url)
    open_ui(page, api)
    page.get_by_role("link", name="API", exact=True).click()
    page.get_by_label("Протокол выдачи").select_option("socks5")
    page.get_by_label("Максимальный отклик, мс").fill("250")
    page.get_by_label("Только проверенный HTTPS").check()
    page.get_by_label("Стратегия выдачи").select_option("best")
    page.get_by_label("Формат ответа").select_option(file_format)
    expected_url = api.url + f"/api/proxy?protocol=socks5&max_latency_ms=250&https_only=true&strategy=best&format={file_format}"
    expect(page.get_by_label("URL запроса", exact=True)).to_have_value(expected_url)
    assert not api.matching("/api/proxy")
    page.get_by_label("Пример запроса").select_option("python")
    expect(page.locator("#api-example-code")).to_contain_text("urlopen")
    expect(page.locator("#api-example-code")).to_contain_text(expected_url)
    page.get_by_role("button", name="Скопировать пример").click()
    # Windows clipboard may convert LF to native CRLF without changing the code.
    assert page.evaluate("navigator.clipboard.readText()").splitlines() == page.locator("#api-example-code").inner_text().splitlines()
    page.get_by_label("Пример запроса").select_option("powershell")
    expect(page.locator("#api-example-code")).to_contain_text("Invoke-RestMethod")
    page.get_by_label("Пример запроса").select_option("curl")
    expect(page.locator("#api-example-code")).to_contain_text("curl.exe")
    page.get_by_role("button", name="Скопировать URL запроса").click()
    assert page.evaluate("navigator.clipboard.readText()") == expected_url
    page.get_by_role("button", name="Выполнить GET").click()
    if response_kind == "unavailable":
        expect(page.locator("#api-response-meta")).to_contain_text("HTTP 503")
        expect(page.locator("#api-response")).to_contain_text("Нет свежих проверенных прокси")
        expect(page.locator("#api-error")).to_be_visible()
    else:
        expect(page.locator("#api-response-meta")).to_contain_text("HTTP 200")
        expect(page.locator("#api-response")).to_contain_text(row["url"])
        expect(page.locator("#api-error")).to_be_hidden()
    assert api.matching("/api/proxy")[-1]["query"] == {
        "protocol": ["socks5"], "max_latency_ms": ["250"], "https_only": ["true"],
        "strategy": ["best"], "format": [file_format],
    }
    external = []
    page.on("request", lambda request: external.append(request.url) if request.url.startswith("https://external.example") else None)
    page.get_by_label("URL запроса", exact=True).fill("https://external.example/api/proxy")
    page.get_by_role("button", name="Выполнить GET").click()
    expect(page.locator("#api-error")).to_contain_text("Только локальные GET-запросы")
    assert not external
    page.get_by_label("Тип запроса").select_option("stats")
    page.get_by_role("button", name="Выполнить GET").click()
    expect(page.locator("#api-response")).to_contain_text('"total"')
    api.responses[("GET", "/api/proxies/export")] = (200, row["url"] + "\n")
    page.get_by_label("Тип запроса").select_option("export")
    page.get_by_label("Формат ответа").select_option("text")
    with page.expect_response(lambda response: "/api/proxies/export?" in response.url):
        page.get_by_role("button", name="Выполнить GET").click()
    expect(page.locator("#api-response")).to_contain_text(row["url"])
    assert api.matching("/api/proxies/export")[-1]["query"]["limit"] == ["1000"]
    page.get_by_label("Тип запроса").select_option("list")
    with page.expect_response(lambda response: "/api/proxies?" in response.url):
        page.get_by_role("button", name="Выполнить GET").click()
    expect(page.locator("#api-response")).to_contain_text('"items"')
    assert api.matching("/api/proxies")[-1]["query"]["limit"] == ["50"]


def test_cached_verified_row_expires_to_stale_even_when_stats_go_offline(page, api):
    api.settings["freshness"] = 60
    api.proxies = [proxy_row(1, last_checked=time.time() - 40)]
    page.clock.install()
    open_ui(page, api)
    page.get_by_role("link", name="Прокси", exact=True).click()
    page.get_by_label("Состояние", exact=True).select_option("all")
    expect(page.locator('#proxy-table-body tr[data-id="1"]')).to_contain_text("Рабочий · свежий")
    api.failures["/api/stats"] = (503, {"detail": "Сервис временно недоступен"})
    page.clock.fast_forward(31000)
    expect(page.locator("#connection-status")).to_contain_text("Нет связи")
    expect(page.locator('#proxy-table-body tr[data-id="1"]')).to_contain_text("Устарел")
    expect(page.locator("#connection-banner")).to_contain_text("последние полученные данные")


def test_mobile_controls_have_touch_targets_and_no_page_overflow_under_csp(page, api):
    api.proxies = [proxy_row(1)]
    page.set_viewport_size({"width": 390, "height": 844})
    page.emulate_media(reduced_motion="reduce")
    page.add_init_script("window.__cspViolations = []; document.addEventListener('securitypolicyviolation', e => window.__cspViolations.push(e.violatedDirective));")
    open_ui(page, api)
    for label, view in [("Обзор", "overview"), ("Прокси", "proxies"), ("Источники", "sources"),
                        ("API", "api"), ("Настройки", "settings")]:
        page.get_by_role("link", name=label, exact=True).click()
        expect(page.locator(f"#view-{view}")).to_be_visible()
        if view == "settings":
            expect(page.get_by_label("Параллельных проверок")).to_have_value("120")
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), label
        offenders = page.locator(f"#view-{view}").evaluate("""root => [...root.querySelectorAll('button, a.button, input:not([type=checkbox]), select, .check-field')]
            .filter(node => node.getClientRects().length && node.getBoundingClientRect().height < 44)
            .map(node => ({id: node.id, height: node.getBoundingClientRect().height}))""")
        assert not offenders, (label, offenders)
    page.get_by_role("link", name="Прокси", exact=True).click()
    page.get_by_role("button", name="Импортировать список").click()
    expect(page.get_by_role("dialog", name="Импорт прокси")).to_be_visible()
    assert page.locator("#import-dialog").evaluate("node => node.scrollWidth <= node.clientWidth")
    page.keyboard.press("Escape")
    expect(page.get_by_role("dialog", name="Импорт прокси")).to_be_hidden()
    assert page.evaluate("window.__cspViolations") == []


@pytest.mark.parametrize("transport", ["http", "network"])
def test_initial_offline_has_no_invented_metrics_or_working_actions(page, api, transport):
    api.stats = stats_payload(total=99, alive=88)
    if transport == "http":
        api.failures["/api/stats"] = (503, {"detail": "Сервис недоступен"})
    else:
        page.route("**/api/stats", lambda route: route.abort("failed"))
    open_ui(page, api)
    expect(page.locator("#connection-status")).to_contain_text("Нет связи")
    expect(page.locator("#connection-banner")).to_contain_text("Данные не получены")
    expect(page.locator("#kpi-alive")).to_have_text("—")
    expect(page.locator("#kpi-total")).to_have_text("—")
    expect(page.locator("#history-chart")).to_be_hidden()
    expect(page.locator("#history-empty")).to_be_visible()
    expect(page.get_by_role("button", name="Собрать прокси", exact=True)).to_be_disabled()
    expect(page.get_by_role("button", name="Остановить", exact=True)).to_be_disabled()
    page.get_by_role("link", name="API", exact=True).click()
    expect(page.locator("#view-api")).to_be_visible()


@pytest.mark.parametrize("kind", ["import", "source"])
def test_failed_user_write_keeps_draft_and_renders_error_as_text(page, api, kind):
    detail = "<img src=x onerror=alert(1)> Запись отклонена"
    api.failures["/api/import" if kind == "import" else "/api/sources"] = (422, {"detail": detail})
    open_ui(page, api)
    if kind == "import":
        page.get_by_role("link", name="Прокси", exact=True).click()
        page.get_by_role("button", name="Импортировать список").click()
        draft = "socks5://9.9.9.1:1080"
        page.get_by_label("Список адресов").fill(draft)
        page.get_by_role("button", name="Добавить в реестр").click()
        error, input_selector, submit = "#import-error", "#import-text", "Добавить в реестр"
    else:
        page.get_by_role("link", name="Источники", exact=True).click()
        page.get_by_role("button", name="Добавить источник", exact=True).click()
        draft = "Новый источник"
        page.get_by_label("Название источника").fill(draft)
        page.get_by_label("URL источника").fill("https://publisher.example/proxies.txt")
        page.get_by_role("button", name="Сохранить источник").click()
        error, input_selector, submit = "#source-form-error", "#source-name", "Сохранить источник"
    expect(page.locator(error)).to_contain_text(detail)
    assert page.locator(error + " img").count() == 0
    expect(page.locator(input_selector)).to_have_value(draft)
    expect(page.get_by_role("button", name=submit)).to_be_enabled()


def test_failed_export_never_downloads_an_error_as_a_proxy_list(page, api):
    api.failures["/api/proxies/export"] = (503, {"detail": "Экспорт временно недоступен"})
    downloads = []
    page.on("download", lambda download: downloads.append(download.suggested_filename))
    open_ui(page, api)
    page.get_by_role("link", name="Прокси", exact=True).click()
    page.get_by_role("button", name="Экспорт в текст").click()
    expect(page.locator("#notice")).to_contain_text("Экспорт временно недоступен")
    expect(page.locator("#notice")).to_have_attribute("data-kind", "error")
    expect(page.get_by_role("button", name="Экспорт в текст")).to_be_enabled()
    assert downloads == []


def test_static_assets_use_local_scripts_safe_dom_and_no_test_rows():
    from html.parser import HTMLParser

    class InspectHTML(HTMLParser):
        def __init__(self):
            super().__init__()
            self.tags = []

        def handle_starttag(self, tag, attrs):
            self.tags.append((tag, dict(attrs)))

    html = (STATIC / "index.html").read_text(encoding="utf-8")
    script = (STATIC / "app.js").read_text(encoding="utf-8")
    css = (STATIC / "app.css").read_text(encoding="utf-8")
    parser = InspectHTML()
    parser.feed(html)
    scripts = [attrs for tag, attrs in parser.tags if tag == "script"]
    assert scripts == [{"src": "/static/app.js", "defer": None}]
    assert all(not name.startswith("on") for _, attrs in parser.tags for name in attrs)
    identifiers = [attrs["id"] for _, attrs in parser.tags if "id" in attrs]
    assert len(identifiers) == len(set(identifiers))
    assert "innerHTML" not in script and "insertAdjacentHTML" not in script and "document.write" not in script
    assert "9.9.9." not in html + script and "publisher.example" not in html + script
    assert "@import" not in css and "https://fonts" not in css
    assert 'lang="ru"' in html and '"Segoe UI"' in css and "Consolas" in css


def test_live_pagination_recovers_when_checked_pool_shrinks(page, api):
    api.proxies = [proxy_row(i) for i in range(1, 72)]
    open_ui(page, api)
    page.get_by_role("link", name="Прокси", exact=True).click()
    expect(page.locator("#proxy-count")).to_have_text("1–50 из 71")
    page.get_by_role("button", name="Следующая страница").click()
    expect(page.locator("#proxy-count")).to_have_text("51–71 из 71")
    api.proxies = api.proxies[:2]
    expect(page.locator("#proxy-count")).to_have_text("1–2 из 2", timeout=6500)
    expect(page.locator("#proxy-table-body tr")).to_have_count(2)
    expect(page.get_by_role("button", name="Предыдущая страница")).to_be_disabled()
    assert api.matching("/api/proxies")[-1]["query"]["offset"] == ["0"]


def test_keyboard_skip_link_keeps_current_section_and_focuses_main(page, api):
    open_ui(page, api)
    page.get_by_role("link", name="API", exact=True).click()
    page.get_by_role("link", name="К содержимому").focus()
    page.keyboard.press("Enter")
    expect(page.locator("#view-api")).to_be_visible()
    expect(page.locator("#main")).to_be_focused()
    assert page.url.endswith("#api")


def test_browser_fixture_does_not_leave_an_asyncio_loop_running_between_tests():
    import asyncio

    with pytest.raises(RuntimeError, match="no running event loop"):
        asyncio.get_running_loop()
