(() => {
  "use strict";

  const $ = (selector, root = document) => root.querySelector(selector);
  const views = {
    overview: ["Обзор", "Доступность, ход проверки и события сервиса."],
    proxies: ["Прокси", "Реестр адресов, результаты проверки и фильтры выдачи."],
    sources: ["Источники", "Публичные списки, состояние загрузки и управление каталогом."],
    api: ["API", "Выдача только свежих проверенных прокси для ваших приложений."],
    settings: ["Настройки", "Параметры локального сервиса. Изменения действуют со следующего цикла."]
  };
  const state = { view: "overview", stats: null, lastGoodAt: null, logSignature: null, historySignature: null };
  const countFormat = new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 0 });
  const timeFormat = new Intl.DateTimeFormat("ru-RU", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  const dateFormat = new Intl.DateTimeFormat("ru-RU", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
  const serviceLabels = { idle: "Ожидание", collecting: "Сбор", checking: "Проверка", stopping: "Остановка", error: "Ошибка цикла" };

  function numeric(value) {
    return typeof value === "number" && Number.isFinite(value);
  }

  function formatCount(value) {
    return numeric(value) ? countFormat.format(value) : "—";
  }

  function timestamp(value, short = false) {
    const date = typeof value === "number" ? new Date(value * 1000) : new Date(value);
    return value != null && Number.isFinite(date.getTime()) ? (short ? timeFormat : dateFormat).format(date) : "—";
  }

  function element(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text != null) node.textContent = String(text);
    return node;
  }

  function announce(message, kind = "success") {
    const node = $("#notice");
    node.textContent = message;
    node.dataset.kind = kind;
    node.hidden = false;
  }

  async function requestPayload(path, options = {}) {
    const { timeout = 12000, ...fetchOptions } = options;
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeout);
    try {
      const response = await fetch(path, { ...fetchOptions, cache: "no-store", credentials: "same-origin",
        headers: { Accept: "application/json", ...fetchOptions.headers }, signal: controller.signal });
      const text = await response.text();
      let data = null;
      try { data = text ? JSON.parse(text) : null; } catch { /* Plaintext is valid for issuance and export. */ }
      if (!response.ok) {
        const detail = Array.isArray(data?.detail) ? data.detail.map(item => item.msg || String(item)).join("; ") : data?.detail;
        const error = new Error(typeof detail === "string" ? detail : "Ошибка HTTP " + response.status);
        error.status = response.status;
        error.responseText = text;
        throw error;
      }
      return { data, text, status: response.status, contentType: response.headers.get("content-type") || "" };
    } catch (error) {
      if (error.name === "AbortError") throw new Error("Сервис не ответил за " + timeout / 1000 + " секунд");
      if (error instanceof TypeError) throw new Error("Локальный API недоступен");
      throw error;
    } finally { clearTimeout(timer); }
  }

  async function requestJSON(path, options = {}) {
    const response = await requestPayload(path, options);
    if (response.data == null) throw new Error("Сервис вернул ответ не в формате JSON (HTTP " + response.status + ")");
    return response.data;
  }

  function sendJSON(path, method, body, timeout = 12000) {
    return requestJSON(path, { method, body: JSON.stringify(body), timeout, headers: { "Content-Type": "application/json" } });
  }

  function svgElement(tag, attrs, text) {
    const node = document.createElementNS("http://www.w3.org/2000/svg", tag);
    for (const [name, value] of Object.entries(attrs || {})) node.setAttribute(name, String(value));
    if (text != null) node.textContent = String(text);
    return node;
  }

  function renderHistory(history) {
    const points = (Array.isArray(history) ? history : []).filter(row => numeric(row.time) && numeric(row.alive) && row.alive >= 0).slice(-60).sort((a, b) => a.time - b.time);
    const signature = JSON.stringify(points);
    if (signature === state.historySignature) return;
    state.historySignature = signature;
    const chart = $("#history-chart");
    chart.toggleAttribute("hidden", points.length < 2);
    $("#history-empty").hidden = points.length >= 2;
    $("#history-caption").textContent = points.length ? formatCount(points.length) + " замера · последний в " + timestamp(points.at(-1).time, true) : "Нет завершённых замеров";
    if (points.length < 2) return;
    const start = points[0].time;
    const span = points.at(-1).time - start;
    const max = Math.max(1, ...points.map(row => row.alive));
    const x = (row, index) => 40 + (span ? (row.time - start) / span : index / (points.length - 1)) * 530;
    const y = row => 143 - row.alive / max * 115;
    chart.replaceChildren(svgElement("desc", { id: "history-description" }, "Доступность по " + points.length + " реальным замерам сервиса. Максимум: " + formatCount(max) + "."));
    for (const [position, label] of [[28, max], [85.5, Math.round(max / 2)], [143, 0]]) {
      chart.append(svgElement("line", { x1: 40, y1: position, x2: 570, y2: position, class: "chart-grid" }));
      chart.append(svgElement("text", { x: 31, y: position + 4, "text-anchor": "end" }, formatCount(label)));
    }
    chart.append(svgElement("polyline", { points: points.map((row, index) => x(row, index).toFixed(2) + "," + y(row).toFixed(2)).join(" ") }));
    points.forEach((row, index) => {
      const dot = svgElement("circle", { cx: x(row, index), cy: y(row), r: 3 });
      dot.append(svgElement("title", {}, timestamp(row.time) + " · рабочих " + formatCount(row.alive) + " · проверено " + formatCount(row.checked)));
      chart.append(dot);
    });
    chart.append(svgElement("text", { x: 40, y: 169 }, timestamp(points[0].time, true)));
    chart.append(svgElement("text", { x: 570, y: 169, "text-anchor": "end" }, timestamp(points.at(-1).time, true)));
  }

  function renderLogs(logs) {
    const items = (Array.isArray(logs) ? logs : []).slice(-80);
    const signature = JSON.stringify(items);
    if (signature === state.logSignature) return;
    state.logSignature = signature;
    const list = $("#activity-log");
    if (!items.length) { list.replaceChildren(element("li", "log-empty", "Событий пока нет. Запустите сбор или проверку.")); return; }
    const levels = { info: "Информация", warning: "Предупреждение", error: "Ошибка" };
    const fragment = document.createDocumentFragment();
    items.slice().reverse().forEach(item => {
      const row = element("li");
      row.dataset.level = Object.hasOwn(levels, item.level) ? item.level : "info";
      const time = element("time", "", timestamp(item.time, true));
      time.title = timestamp(item.time);
      row.append(time, element("span", "log-level", levels[row.dataset.level]), element("span", "log-message", item.message));
      fragment.append(row);
    });
    list.replaceChildren(fragment);
  }

  function renderStats(data) {
    for (const key of ["alive", "total", "pending", "stale", "https"]) $("#kpi-" + key).textContent = formatCount(data[key]);
    $("#kpi-latency").textContent = numeric(data.average_latency_ms) ? formatCount(data.average_latency_ms) + " мс" : "—";
    $("#pool-last-check").textContent = data.last_check ? "Последняя проверка: " + timestamp(data.last_check) : "Проверок ещё нет";
    const service = data.service || {};
    $("#service-state").textContent = serviceLabels[service.state] || "Неизвестное состояние";
    $("#service-state").dataset.state = service.state;
    $("#service-stage").textContent = service.stage || "Ожидание действий";
    for (const key of ["parsed", "added", "checked", "working", "queue", "errors"]) $("#pipeline-" + key).textContent = formatCount(service[key]);
    $("#source-progress-label").textContent = formatCount(service.sources_done) + " / " + formatCount(service.sources_total);
    const progress = $("#source-progress");
    const total = numeric(service.sources_total) ? Math.max(1, service.sources_total) : 1;
    const done = numeric(service.sources_done) ? Math.min(total, Math.max(0, service.sources_done)) : 0;
    progress.setAttribute("aria-valuemax", String(total));
    progress.setAttribute("aria-valuenow", String(done));
    $("span", progress).style.width = (service.sources_total > 0 ? done / total * 100 : 0) + "%";
    $("#cycle-time").textContent = service.started_at ? "Начало: " + timestamp(service.started_at, true) : "Цикл ещё не запускался";
    $("#next-cycle").textContent = service.next_run_at ? "Следующий: " + timestamp(service.next_run_at, true) : "Автозапуск не назначен";
    $("#cycle-error").hidden = !service.last_error;
    $("#cycle-error").textContent = service.last_error || "";
    renderHistory(service.history);
    renderLogs(service.logs);
  }

  function renderCycleControls() {
    const service = state.stats?.service;
    const running = service?.running || ["collecting", "checking", "stopping"].includes(service?.state);
    $("#action-collect").disabled = !state.online || state.actionBusy || running;
    $("#action-recheck").disabled = !state.online || state.actionBusy || running;
    $("#action-stop").disabled = !state.online || state.actionBusy || !running || service?.state === "stopping";
    $("#cycle-controls").setAttribute("aria-busy", String(Boolean(state.actionBusy)));
    $("#cycle-hint").textContent = !state.online ? "Сервис недоступен" : state.actionBusy ? "Выполняется запрос…" : running ? service.stage || "Цикл выполняется" : "Готов к запуску · без параллельных циклов";
  }

  async function runCycleAction(action) {
    if (state.actionBusy) return;
    state.actionBusy = true;
    renderCycleControls();
    try {
      const result = await requestJSON("/api/" + action, { method: "POST" });
      if (pollBusy) await pollFlight;
      const confirmed = await pollStats();
      const accepted = action === "stop" ? result.stopped : result.started;
      const message = typeof result.message === "string" ? result.message : "Запрос обработан сервисом";
      announce(confirmed ? message : "Запрос принят, но подтвердить состояние не удалось. " + message,
        confirmed && accepted ? "success" : "warning");
    } catch (error) { announce("Команда не выполнена: " + error.message, "error"); }
    finally { state.actionBusy = false; renderCycleControls(); }
  }

  let pollTimer = null;
  let pollBusy = false;
  let pollFlight = null;

  function pollStats() {
    if (pollBusy) return pollFlight;
    pollFlight = performPoll();
    return pollFlight;
  }

  async function performPoll() {
    clearTimeout(pollTimer);
    pollBusy = true;
    $("#retry-connection").disabled = true;
    try {
      const data = await requestJSON("/api/stats");
      if (!data || !numeric(data.total) || !numeric(data.alive) || !data.service) throw new Error("Неполный ответ статистики");
      state.stats = data;
      state.online = true;
      state.lastGoodAt = Date.now();
      renderStats(data);
      $("#connection-status").replaceChildren(element("i"), document.createTextNode("На связи"));
      $("#connection-status").className = "status-badge online";
      $("#last-sync").textContent = "Обновлено в " + timeFormat.format(new Date(state.lastGoodAt));
      $("#connection-banner").hidden = true;
      if (state.view === "proxies" && !state.proxyLoading) loadProxies();
      if (state.view === "sources" && !state.sourceLoading && !state.sourceMutationBusy) loadSources();
      return true;
    } catch (error) {
      state.online = false;
      $("#connection-status").replaceChildren(element("i"), document.createTextNode("Нет связи"));
      $("#connection-status").className = "status-badge offline";
      $("#connection-error").textContent = (state.lastGoodAt ? "Показаны последние полученные данные. " : "Данные не получены. Проверьте, что локальный сервис запущен. ") + "Ошибка: " + (error instanceof TypeError ? "Локальный API недоступен" : error.message);
      $("#connection-banner").hidden = false;
      $("#last-sync").textContent = state.lastGoodAt ? "Последние данные: " + timeFormat.format(new Date(state.lastGoodAt)) : "Данные ещё не получены";
      return false;
    } finally {
      pollBusy = false;
      $("#retry-connection").disabled = false;
      renderCycleControls();
      refreshProxyFreshness();
      pollTimer = setTimeout(pollStats, 3000);
    }
  }

  state.proxyOffset = 0;
  state.proxyTotal = null;
  state.proxySerial = 0;
  state.proxySignature = null;

  let settingsFlight = null;
  async function fetchRuntimeSettings(force = false) {
    if (state.settings && !force) return true;
    if (settingsFlight) return settingsFlight;
    settingsFlight = requestJSON("/api/settings").then(data => {
      if (!data || !numeric(data.freshness) || data.freshness <= 0) throw new Error("Неполный ответ настроек");
      state.settings = data;
      state.settingsError = null;
      $("#freshness-note").textContent = "Порог свежести: " + formatCount(data.freshness) + " с. Устаревшие видны в «Все состояния» и исключены из выдачи.";
      if (state.proxyItems) renderProxyRows(state.proxyItems);
      return true;
    }).catch(error => {
      $("#freshness-note").textContent = "Порог свежести недоступен: " + error.message + ". Свежесть в полном реестре не подтверждена.";
      state.settingsError = error.message;
      return false;
    }).finally(() => { settingsFlight = null; });
    return settingsFlight;
  }

  function proxyStatus(proxy) {
    if (proxy.status === "pending" || !proxy.last_checked) return ["pending", "Не проверен"];
    if (proxy.status === "dead") return ["dead", "Не отвечает"];
    if (proxy.status === "stale") return ["stale", "Устарел"];
    if (proxy.status !== "alive") return ["unknown", "Неизвестно"];
    if (!state.settings) return ["unknown", "Свежесть неизвестна"];
    const checked = typeof proxy.last_checked === "number" ? proxy.last_checked : Date.parse(proxy.last_checked) / 1000;
    if (!Number.isFinite(checked)) return ["pending", "Не проверен"];
    return Date.now() / 1000 - checked > state.settings.freshness ? ["stale", "Устарел"] : ["alive", "Рабочий · свежий"];
  }

  function proxyParams(includePage = true) {
    const params = new URLSearchParams();
    if (includePage) { params.set("limit", $("#proxy-limit").value); params.set("offset", String(state.proxyOffset)); }
    params.set("status", $("#proxy-status").value);
    if ($("#proxy-protocol").value) params.set("protocol", $("#proxy-protocol").value);
    if ($("#proxy-latency").value) params.set("max_latency_ms", $("#proxy-latency").value);
    params.set("https_only", String($("#proxy-https").checked));
    params.set("sort", $("#proxy-sort").value);
    if ($("#proxy-query").value.trim()) params.set("query", $("#proxy-query").value.trim());
    return params;
  }

  function emptyTable(body, columns, message) {
    const row = element("tr");
    const cell = element("td", "table-empty", message);
    cell.colSpan = columns;
    row.append(cell);
    body.replaceChildren(row);
  }

  function rowButton(action, id, label, text) {
    const button = element("button", "button button-small", text);
    button.type = "button";
    button.dataset.action = action;
    button.dataset.id = String(id);
    button.setAttribute("aria-label", label);
    button.title = label;
    return button;
  }

  async function copyText(text, successMessage = "Текст скопирован") {
    try {
      if (!navigator.clipboard?.writeText) throw new Error("Буфер недоступен");
      await navigator.clipboard.writeText(String(text));
      announce(successMessage);
      return true;
    } catch {
      $("#copy-value").value = String(text);
      if (!$("#copy-dialog").open) $("#copy-dialog").showModal();
      $("#copy-value").focus();
      $("#copy-value").select();
      return false;
    }
  }

  function renderProxyRows(items) {
    const body = $("#proxy-table-body");
    if (!items.length) { emptyTable(body, 8, "Нет адресов по этим фильтрам. Запустите сбор, импортируйте список или измените условия."); return; }
    const fragment = document.createDocumentFragment();
    items.forEach(proxy => {
      const row = element("tr");
      row.dataset.id = String(proxy.id);
      const endpoint = element("td");
      endpoint.append(element("code", "", proxy.url));
      if (proxy.exit_ip) endpoint.append(element("div", "cell-detail", "Выход: " + proxy.exit_ip));
      const [status, label] = proxyStatus(proxy);
      const badge = element("span", "pill", label);
      badge.dataset.status = status;
      badge.title = status === "alive" ? "Проверен полным запросом; доступен для выдачи" : "Не выдаётся как свежий рабочий прокси";
      const statusCell = element("td");
      statusCell.append(badge);
      const https = proxy.last_checked ? (proxy.supports_https ? "Да" : "Нет") : "—";
      row.append(endpoint, element("td", "mono", proxy.protocol?.toUpperCase()), statusCell,
        element("td", "mono", numeric(proxy.latency_ms) ? formatCount(proxy.latency_ms) + " мс" : "—"),
        element("td", proxy.supports_https && status === "alive" ? "mint" : "muted", https), element("td", "small-muted", timestamp(proxy.last_checked)),
        element("td", "mono", formatCount(proxy.requests)));
      const actions = element("td");
      const group = element("div", "cell-actions");
      group.append(rowButton("copy", proxy.id, "Скопировать URL " + proxy.url, "URL"));
      actions.append(group);
      row.append(actions);
      fragment.append(row);
    });
    body.replaceChildren(fragment);
  }

  function renderPagination() {
    const limit = Number($("#proxy-limit").value);
    $("#proxy-prev").disabled = state.proxyLoading || state.proxyOffset === 0;
    $("#proxy-next").disabled = state.proxyLoading || state.proxyTotal == null || state.proxyOffset + limit >= state.proxyTotal;
    $("#proxy-count").textContent = state.proxyTotal == null ? "—" : state.proxyTotal === 0 ? "0 прокси" :
      formatCount(state.proxyOffset + 1) + "–" + formatCount(Math.min(state.proxyOffset + limit, state.proxyTotal)) + " из " + formatCount(state.proxyTotal);
  }

  function refreshProxyFreshness() {
    if (!state.proxyItems) return;
    const proxies = new Map(state.proxyItems.map(row => [String(row.id), row]));
    $("#proxy-table-body").querySelectorAll("tr[data-id]").forEach(row => {
      const proxy = proxies.get(row.dataset.id);
      if (!proxy) return;
      const [status, label] = proxyStatus(proxy);
      const badge = $(".pill", row);
      badge.textContent = label;
      badge.dataset.status = status;
      badge.title = status === "alive" ? "Проверен полным запросом; доступен для выдачи" : "Не выдаётся как свежий рабочий прокси";
      row.cells[4].className = proxy.supports_https && status === "alive" ? "mint" : "muted";
    });
  }

  async function loadProxies() {
    if (!$("#proxy-filters").reportValidity()) return false;
    const serial = ++state.proxySerial;
    state.proxyLoading = true;
    $("#proxy-results").setAttribute("aria-busy", "true");
    $("#proxy-result-meta").textContent = "Получаем адреса…";
    renderPagination();
    try {
      const [data] = await Promise.all([requestJSON("/api/proxies?" + proxyParams()), fetchRuntimeSettings()]);
      if (serial !== state.proxySerial) return false;
      if (!Array.isArray(data?.items) || !numeric(data.total) || data.total < 0) throw new Error("Неполный ответ реестра");
      if (data.total === 0) state.proxyOffset = 0;
      else if (state.proxyOffset >= data.total) {
        const limit = Number($("#proxy-limit").value);
        state.proxyOffset = Math.floor((data.total - 1) / limit) * limit;
        return await loadProxies();
      }
      state.proxyTotal = data.total;
      state.proxyItems = data.items;
      const signature = JSON.stringify(data.items);
      if (signature !== state.proxySignature) { state.proxySignature = signature; renderProxyRows(data.items); }
      refreshProxyFreshness();
      $("#proxy-error").hidden = true;
      $("#proxy-result-meta").textContent = "Данные получены в " + timeFormat.format(new Date());
      return true;
    } catch (error) {
      if (serial !== state.proxySerial) return false;
      $("#proxy-error").textContent = "Не удалось загрузить адреса: " + error.message + (state.proxyItems ? ". Показан предыдущий результат." : "");
      $("#proxy-error").hidden = false;
      $("#proxy-result-meta").textContent = "Нет актуального ответа";
      return false;
    } finally {
      if (serial === state.proxySerial) { state.proxyLoading = false; $("#proxy-results").setAttribute("aria-busy", "false"); renderPagination(); }
    }
  }

  let proxySearchTimer = null;
  function updateProxyFilters() { clearTimeout(proxySearchTimer); state.proxyOffset = 0; loadProxies(); }

  function downloadFile(content, fileFormat) {
    const blob = new Blob([content], { type: fileFormat === "json" ? "application/json;charset=utf-8" : "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = element("a");
    link.href = url;
    link.download = "proxy-harbor-" + new Date().toISOString().slice(0, 10) + (fileFormat === "json" ? ".json" : ".txt");
    document.body.append(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1500);
  }

  async function importProxies(event) {
    event.preventDefault();
    if (state.importBusy || !$("#import-form").reportValidity()) return;
    const text = $("#import-text").value;
    if (!text.trim()) { $("#import-text").setCustomValidity("Вставьте хотя бы один адрес"); $("#import-text").reportValidity(); return; }
    state.importBusy = true;
    $("#import-submit").disabled = true;
    $("#import-form").setAttribute("aria-busy", "true");
    $("#import-error").hidden = true;
    try {
      const data = await sendJSON("/api/import", "POST", { text, protocol: $("#import-protocol").value });
      if (!numeric(data.parsed) || !numeric(data.added)) throw new Error("Неполный ответ импорта");
      $("#proxy-filters").reset();
      $("#proxy-status").value = "pending";
      state.proxyOffset = 0;
      const confirmed = await loadProxies();
      if (pollBusy) await pollFlight;
      await pollStats();
      $("#import-dialog").close();
      $("#import-text").value = "";
      announce("Распознано: " + formatCount(data.parsed) + " · новых: " + formatCount(data.added) + ". Адреса ещё не проверены." + (confirmed ? "" : " Импорт принят; обновить реестр не удалось."), confirmed ? "success" : "warning");
    } catch (error) { $("#import-error").textContent = "Импорт не выполнен: " + error.message; $("#import-error").hidden = false; }
    finally { state.importBusy = false; $("#import-submit").disabled = false; $("#import-form").setAttribute("aria-busy", "false"); }
  }

  async function exportProxies(fileFormat) {
    if (state.exportBusy || !$("#proxy-filters").reportValidity()) return;
    state.exportBusy = true;
    $("#export-text").disabled = true;
    $("#export-json").disabled = true;
    const wanted = Number($("#export-limit").value);
    const filters = proxyParams(false);
    try {
      let content;
      let count;
      // Export has no search parameter in the contract. Use the list endpoint
      // for searched exports rather than silently discarding the search.
      if (filters.has("query")) {
        filters.set("status", "alive");
        const items = [];
        const seen = new Set();
        let offset = 0;
        let total = null;
        while (items.length < wanted) {
          filters.set("limit", String(Math.min(100, wanted - items.length)));
          filters.set("offset", String(offset));
          const data = await requestJSON("/api/proxies?" + filters);
          if (!Array.isArray(data?.items) || !numeric(data.total)) throw new Error("Неполный ответ экспорта");
          total = data.total;
          for (const row of data.items) {
            if (!seen.has(row.url)) { items.push(row); seen.add(row.url); }
          }
          offset += data.items.length;
          if (!data.items.length || offset >= total) break;
          if (offset >= 10000) throw new Error("Пул меняется слишком быстро. Повторите экспорт после цикла.");
        }
        count = items.length;
        content = fileFormat === "json" ? JSON.stringify({ items, total, count }, null, 2) : items.map(row => row.url).join("\n") + (count ? "\n" : "");
      } else {
        const params = new URLSearchParams();
        for (const key of ["protocol", "max_latency_ms", "https_only"]) if (filters.has(key)) params.set(key, filters.get(key));
        params.set("format", fileFormat);
        params.set("limit", String(wanted));
        const response = await requestPayload("/api/proxies/export?" + params);
        if (fileFormat === "json") {
          const items = Array.isArray(response.data) ? response.data : response.data?.items;
          if (!Array.isArray(items)) throw new Error("Неполный ответ экспорта");
          count = items.length;
          content = JSON.stringify({ items, total: response.data?.total ?? count, count }, null, 2);
        } else {
          content = response.text;
          count = content.split(/\r?\n/).filter(line => line.trim()).length;
        }
      }
      if (!count) { announce("Нет свежих рабочих прокси по этим фильтрам. Файл не создан.", "warning"); return; }
      downloadFile(content, fileFormat);
      announce("Экспортировано: " + formatCount(count) + ". Лимит: " + formatCount(wanted) + ". Во время проверки состав пула может меняться.");
    } catch (error) { announce("Экспорт не выполнен: " + error.message, "error"); }
    finally { state.exportBusy = false; $("#export-text").disabled = false; $("#export-json").disabled = false; }
  }

  state.sourceSerial = 0;
  function publicWebURL(value) {
    try { const url = new URL(value); return ["http:", "https:"].includes(url.protocol) && !url.username && !url.password; }
    catch { return false; }
  }

  function sourceBusy(busy) {
    state.sourceMutationBusy = busy;
    $("#source-discover").disabled = busy;
    $("#source-submit").disabled = busy;
    $("#source-results").setAttribute("aria-busy", String(busy));
    $("#source-table-body").querySelectorAll("button").forEach(button => { button.disabled = busy; });
  }

  function renderSources(items) {
    const body = $("#source-table-body");
    if (!items.length) { emptyTable(body, 7, "Источников пока нет. Добавьте публичный список или запустите подбор через GitHub."); return; }
    const fragment = document.createDocumentFragment();
    items.forEach(source => {
      const row = element("tr");
      row.dataset.id = String(source.id);
      const name = element("td");
      name.append(element("div", "source-title", source.name));
      const url = element(publicWebURL(source.url) ? "a" : "span", "source-url", source.url);
      url.title = source.url;
      if (url.tagName === "A") { url.href = source.url; url.target = "_blank"; url.rel = "noopener noreferrer"; }
      name.append(url);
      if (source.last_error) name.append(element("p", "source-row-error", "Ошибка: " + source.last_error));
      const health = element("td");
      const badge = element("span", "pill", source.last_error ? "Ошибка загрузки" : source.last_fetch ? "Получен" : "Не загружен");
      badge.dataset.status = source.last_error ? "stale" : "unknown";
      health.append(badge);
      const actions = element("td");
      const group = element("div", "cell-actions");
      const toggle = rowButton("toggle", source.id, "Состояние источника " + source.name, source.enabled ? "Включён" : "Отключён");
      toggle.classList.add("switch");
      toggle.setAttribute("role", "switch");
      toggle.setAttribute("aria-checked", String(Boolean(source.enabled)));
      group.append(toggle, rowButton("delete", source.id, "Удалить источник " + source.name, "Удалить"));
      actions.append(group);
      row.append(name, element("td", "mono", String(source.protocol).toUpperCase()), health,
        element("td", "mono", formatCount(source.found) + " / " + formatCount(source.added)),
        element("td", "small-muted", timestamp(source.last_fetch)),
        element("td", "mono", numeric(source.elapsed_ms) ? formatCount(source.elapsed_ms) + " мс" : "—"), actions);
      fragment.append(row);
    });
    body.replaceChildren(fragment);
    if (state.sourceMutationBusy) sourceBusy(true);
  }

  async function loadSources() {
    const serial = ++state.sourceSerial;
    state.sourceLoading = true;
    try {
      const data = await requestJSON("/api/sources");
      if (serial !== state.sourceSerial) return false;
      if (!Array.isArray(data?.items) || data.total !== data.items.length) throw new Error("Неполный ответ каталога");
      state.sourceItems = data.items;
      const signature = JSON.stringify(data.items);
      if (signature !== state.sourceSignature) { state.sourceSignature = signature; renderSources(data.items); }
      $("#source-count").textContent = "Всего: " + formatCount(data.total) + " · включено: " + formatCount(data.items.filter(row => row.enabled).length);
      $("#source-error").hidden = true;
      return true;
    } catch (error) {
      if (serial !== state.sourceSerial) return false;
      $("#source-error").textContent = "Каталог недоступен: " + error.message + (state.sourceItems ? ". Показаны последние полученные данные." : "");
      $("#source-error").hidden = false;
      return false;
    } finally { if (serial === state.sourceSerial) state.sourceLoading = false; }
  }

  async function addSource(event) {
    event.preventDefault();
    if (state.sourceMutationBusy || !$("#source-form").reportValidity()) return;
    const payload = { name: $("#source-name").value, url: $("#source-url").value,
      protocol: $("#source-protocol").value, format: $("#source-format").value, enabled: $("#source-enabled").checked };
    if (!publicWebURL(payload.url)) { $("#source-form-error").textContent = "Нужен публичный HTTP(S) URL без логина и пароля."; $("#source-form-error").hidden = false; return; }
    sourceBusy(true);
    $("#source-form-error").hidden = true;
    try {
      const result = await sendJSON("/api/sources", "POST", payload);
      const loaded = await loadSources();
      const confirmed = loaded && state.sourceItems.some(row => String(row.id) === String(result.id) && row.url === payload.url);
      $("#source-dialog").close();
      if (confirmed) $("#source-form").reset();
      announce(confirmed ? "Источник добавлен в каталог. Он будет загружен при следующем сборе." : "Запрос добавления принят, но каталог не подтвердил изменение.", confirmed ? "success" : "warning");
    } catch (error) { $("#source-form-error").textContent = "Источник не добавлен: " + error.message; $("#source-form-error").hidden = false; }
    finally { sourceBusy(false); }
  }

  async function changeSource(source, action) {
    if (state.sourceMutationBusy) return;
    if (action === "delete" && !window.confirm("Удалить источник «" + source.name + "»? Адреса в реестре останутся.")) return;
    sourceBusy(true);
    try {
      const path = "/api/sources/" + encodeURIComponent(source.id);
      if (action === "toggle") await sendJSON(path, "PATCH", { enabled: !source.enabled });
      else await requestJSON(path, { method: "DELETE" });
      const loaded = await loadSources();
      const current = state.sourceItems?.find(row => String(row.id) === String(source.id));
      const confirmed = loaded && (action === "toggle" ? current?.enabled === !source.enabled : !current);
      announce(confirmed ? action === "toggle" ? "Состояние источника сохранено." : "Источник удалён. Адреса в реестре сохранены." : "Запрос принят, но изменение каталога не подтверждено.", confirmed ? "success" : "warning");
    } catch (error) { announce("Изменение источника не выполнено: " + error.message, "error"); }
    finally { sourceBusy(false); }
  }

  async function discoverSources() {
    if (state.sourceMutationBusy) return;
    sourceBusy(true);
    announce("Подбираем публичные списки через GitHub. Это может занять некоторое время.", "warning");
    try {
      const result = await requestJSON("/api/sources/discover", { method: "POST", timeout: 120000 });
      if (!numeric(result.added)) throw new Error("Неполный ответ подбора");
      const confirmed = await loadSources();
      announce((result.message || "Подбор завершён: добавлено " + formatCount(result.added)) + (confirmed ? "" : ". Обновить каталог не удалось."), confirmed && result.added > 0 ? "success" : "warning");
    } catch (error) { announce("Подбор не выполнен: " + error.message, "error"); }
    finally { sourceBusy(false); }
  }

  const settingsKeys = ["auto_collect", "collect_interval", "check_concurrency", "source_concurrency", "check_timeout", "connect_timeout", "source_timeout", "max_per_cycle", "recheck_interval", "freshness", "retention_days", "http_probe_url", "https_probe_url"];

  function settingsValues() {
    const values = {};
    for (const key of settingsKeys) {
      const input = $("[name=\"" + key + "\"]", $("#settings-form"));
      values[key] = input.type === "checkbox" ? input.checked : input.type === "number" ? Number(input.value) : input.value;
    }
    return values;
  }

  function settingsDirtyState() {
    const values = settingsValues();
    state.settingsDirty = state.settingsLoaded && settingsKeys.some(key => values[key] !== state.settingsSnapshot[key]);
    $("#settings-save").disabled = !state.settingsLoaded || state.settingsSaving || !state.settingsDirty;
    $("#settings-cancel").disabled = state.settingsSaving || !state.settingsDirty;
    if (!state.settingsSaving && state.settingsLoaded) $("#settings-status").textContent = state.settingsDirty ? "Не сохранено · есть изменения" : "Без несохранённых изменений";
  }

  function fillSettings(values) {
    for (const key of settingsKeys) {
      const input = $("[name=\"" + key + "\"]", $("#settings-form"));
      if (input.type === "checkbox") input.checked = values[key] === true;
      else input.value = values[key] == null ? "" : String(values[key]);
    }
    state.settingsLoaded = true;
    state.settingsSnapshot = { ...values };
    $("#settings-fields").disabled = false;
    settingsDirtyState();
  }

  async function loadSettingsForm(force = false) {
    if (state.settingsSaving || (state.settingsDirty && !force)) return;
    if (force && state.settingsDirty && !window.confirm("Перечитать настройки и отменить несохранённые изменения?")) return;
    $("#settings-reload").disabled = true;
    $("#settings-status").textContent = "Получаем настройки…";
    const loaded = await fetchRuntimeSettings(true);
    if (loaded) { fillSettings(state.settings); $("#settings-error").hidden = true; $("#settings-status").textContent = "С сервера · " + timeFormat.format(new Date()); }
    else { $("#settings-error").textContent = "Настройки недоступны: " + (state.settingsError || "Нет ответа сервиса"); $("#settings-error").hidden = false; $("#settings-status").textContent = "Нет актуального ответа"; }
    $("#settings-reload").disabled = false;
  }

  async function saveSettings(event) {
    event.preventDefault();
    if (state.settingsSaving || !state.settingsDirty || !$("#settings-form").reportValidity()) return;
    const values = settingsValues();
    const changed = {};
    for (const key of settingsKeys) if (values[key] !== state.settingsSnapshot[key]) changed[key] = values[key];
    state.settingsSaving = true;
    $("#settings-fields").disabled = true;
    $("#settings-save").disabled = true;
    $("#settings-cancel").disabled = true;
    $("#settings-reload").disabled = true;
    $("#settings-status").textContent = "Сохраняем и проверяем…";
    $("#settings-error").hidden = true;
    let confirmed = false;
    try {
      await sendJSON("/api/settings", "PATCH", changed);
      if (settingsFlight) await settingsFlight;
      const loaded = await fetchRuntimeSettings(true);
      confirmed = loaded && Object.entries(changed).every(([key, value]) => state.settings[key] === value);
      if (confirmed) fillSettings(state.settings);
      else { $("#settings-error").textContent = "Запрос сохранения принят, но проверка настроек не подтвердила изменение. Черновик сохранён в форме."; $("#settings-error").hidden = false; }
    } catch (error) { $("#settings-error").textContent = "Настройки не сохранены: " + error.message; $("#settings-error").hidden = false; }
    finally {
      state.settingsSaving = false;
      $("#settings-fields").disabled = false;
      $("#settings-reload").disabled = false;
      settingsDirtyState();
      if (confirmed) $("#settings-status").textContent = "Сохранено · подтверждено чтением API";
    }
  }

  const apiPaths = { proxy: "/api/proxy", export: "/api/proxies/export", list: "/api/proxies", stats: "/api/stats" };
  const allowedGetPaths = new Set([...Object.values(apiPaths), "/api/settings", "/api/sources", "/api/runs", "/health"]);

  function updateApiExample() {
    const url = $("#api-url").value;
    const kind = $("#api-example-kind").value;
    const quoted = "'" + url.replace(/'/g, "''") + "'";
    let code;
    if (kind === "python") code = "from urllib.request import urlopen\n\nurl = " + JSON.stringify(url) + "\nwith urlopen(url, timeout=15) as response:\n    print(response.read().decode(\"utf-8\"))";
    else if (kind === "powershell") code = "$uri = " + quoted + "\nInvoke-RestMethod -Method Get -Uri $uri";
    else code = "curl.exe --fail-with-body --silent --show-error " + quoted;
    $("#api-example-code").textContent = code;
  }

  function buildApiRequest() {
    const kind = $("#api-kind").value;
    const params = new URLSearchParams();
    for (const id of ["api-protocol", "api-latency", "api-https"]) $("#" + id).disabled = kind === "stats";
    $("#api-strategy").disabled = kind !== "proxy";
    $("#api-format").disabled = kind === "stats" || kind === "list";
    $("#api-limit").disabled = kind !== "export" && kind !== "list";
    $("#api-limit").max = kind === "list" ? "500" : "10000";
    if (kind !== "stats") {
      if ($("#api-protocol").value) params.set("protocol", $("#api-protocol").value);
      if ($("#api-latency").value) params.set("max_latency_ms", $("#api-latency").value);
      params.set("https_only", String($("#api-https").checked));
      if (kind === "proxy") params.set("strategy", $("#api-strategy").value);
      if (kind === "proxy" || kind === "export") params.set("format", $("#api-format").value);
      if (kind === "list" || kind === "export") params.set("limit", $("#api-limit").value);
      if (kind === "list") { params.set("offset", "0"); params.set("status", "alive"); params.set("sort", "latency"); }
    }
    $("#api-url").value = location.origin + apiPaths[kind] + (params.size ? "?" + params : "");
    updateApiExample();
  }

  async function testApiRequest(event) {
    event.preventDefault();
    if (state.apiTesting || !$("#api-test-form").reportValidity() || !$("#api-builder-form").reportValidity()) return;
    let url;
    try { url = new URL($("#api-url").value); }
    catch { $("#api-error").textContent = "Укажите корректный URL запроса."; $("#api-error").hidden = false; return; }
    if (url.origin !== location.origin || !allowedGetPaths.has(url.pathname) || url.username || url.password) {
      $("#api-error").textContent = "Только локальные GET-запросы к документированным адресам этого сервиса.";
      $("#api-error").hidden = false;
      return;
    }
    state.apiTesting = true;
    $("#api-test").disabled = true;
    $("#api-error").hidden = true;
    $("#api-response-meta").textContent = "Выполняется запрос…";
    const started = performance.now();
    try {
      const response = await requestPayload(url.pathname + url.search);
      $("#api-response").textContent = response.data == null ? response.text : JSON.stringify(response.data, null, 2);
      $("#api-response-meta").textContent = "HTTP " + response.status + " · " + formatCount(performance.now() - started) + " мс";
    } catch (error) {
      $("#api-error").textContent = "Запрос не выполнен: " + error.message;
      $("#api-error").hidden = false;
      $("#api-response").textContent = error.responseText || error.message;
      $("#api-response-meta").textContent = (error.status ? "HTTP " + error.status : "Сетевая ошибка") + " · " + formatCount(performance.now() - started) + " мс";
    } finally { state.apiTesting = false; $("#api-test").disabled = false; }
  }

  function renderView() {
    const requested = location.hash.slice(1);
    state.view = Object.hasOwn(views, requested) ? requested : "overview";
    for (const key of Object.keys(views)) $("#view-" + key).hidden = key !== state.view;
    document.querySelectorAll("[data-view]").forEach(link => {
      if (link.dataset.view === state.view) link.setAttribute("aria-current", "page");
      else link.removeAttribute("aria-current");
    });
    $("#page-title").textContent = views[state.view][0];
    $("#page-description").textContent = views[state.view][1];
    document.title = "Proxy Harbor — " + views[state.view][0];
    if (state.view === "proxies") loadProxies();
    if (state.view === "sources") loadSources();
    if (state.view === "settings") loadSettingsForm();
  }

  $("#service-address").textContent = location.host;
  $(".skip-link").addEventListener("click", event => { event.preventDefault(); $("#main").focus(); });
  window.addEventListener("hashchange", renderView);
  window.addEventListener("pagehide", () => clearTimeout(pollTimer));
  $("#retry-connection").addEventListener("click", pollStats);
  for (const action of ["collect", "recheck", "stop"]) $("#action-" + action).addEventListener("click", () => runCycleAction(action));
  $("#proxy-filters").addEventListener("submit", event => { event.preventDefault(); updateProxyFilters(); });
  for (const id of ["proxy-status", "proxy-protocol", "proxy-https", "proxy-sort", "proxy-limit"]) $("#" + id).addEventListener("change", updateProxyFilters);
  for (const id of ["proxy-query", "proxy-latency"]) $("#" + id).addEventListener("input", () => { clearTimeout(proxySearchTimer); proxySearchTimer = setTimeout(updateProxyFilters, 300); });
  $("#proxy-reset").addEventListener("click", () => { $("#proxy-filters").reset(); $("#proxy-limit").value = "50"; updateProxyFilters(); });
  $("#proxy-prev").addEventListener("click", () => { state.proxyOffset = Math.max(0, state.proxyOffset - Number($("#proxy-limit").value)); loadProxies(); });
  $("#proxy-next").addEventListener("click", () => { state.proxyOffset += Number($("#proxy-limit").value); loadProxies(); });
  $("#proxy-table-body").addEventListener("click", event => {
    const button = event.target.closest("button[data-action]");
    if (!button) return;
    const proxy = state.proxyItems?.find(row => String(row.id) === button.dataset.id);
    if (proxy && button.dataset.action === "copy") copyText(proxy.url, "URL скопирован");
  });
  $("#export-text").addEventListener("click", () => exportProxies("text"));
  $("#export-json").addEventListener("click", () => exportProxies("json"));
  $("#open-import").addEventListener("click", () => { $("#import-error").hidden = true; $("#import-dialog").showModal(); $("#import-text").focus(); });
  $("#import-form").addEventListener("submit", importProxies);
  $("#import-text").addEventListener("input", () => $("#import-text").setCustomValidity(""));
  $("#open-source").addEventListener("click", () => { $("#source-form-error").hidden = true; $("#source-dialog").showModal(); $("#source-name").focus(); });
  $("#source-form").addEventListener("submit", addSource);
  $("#source-discover").addEventListener("click", discoverSources);
  $("#source-table-body").addEventListener("click", event => {
    const button = event.target.closest("button[data-action]");
    if (!button) return;
    const source = state.sourceItems?.find(row => String(row.id) === button.dataset.id);
    if (source) changeSource(source, button.dataset.action);
  });
  $("#settings-form").addEventListener("input", settingsDirtyState);
  $("#settings-form").addEventListener("change", settingsDirtyState);
  $("#settings-form").addEventListener("submit", saveSettings);
  $("#settings-reload").addEventListener("click", () => loadSettingsForm(true));
  $("#settings-cancel").addEventListener("click", () => { fillSettings(state.settingsSnapshot); $("#settings-error").hidden = true; });
  $("#api-builder-form").addEventListener("submit", event => { event.preventDefault(); buildApiRequest(); });
  $("#api-builder-form").addEventListener("input", buildApiRequest);
  $("#api-builder-form").addEventListener("change", buildApiRequest);
  $("#api-kind").addEventListener("change", () => { $("#api-limit").value = $("#api-kind").value === "list" ? "50" : "1000"; buildApiRequest(); });
  $("#api-example-kind").addEventListener("change", updateApiExample);
  $("#api-url").addEventListener("input", updateApiExample);
  $("#api-test-form").addEventListener("submit", testApiRequest);
  $("#api-copy-url").addEventListener("click", () => copyText($("#api-url").value, "URL запроса скопирован"));
  $("#api-copy-example").addEventListener("click", () => copyText($("#api-example-code").textContent, "Пример скопирован"));
  buildApiRequest();
  renderView();
  pollStats();
})();
