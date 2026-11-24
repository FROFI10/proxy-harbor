"""Extract proxy endpoints from untrusted public source documents."""

import csv
import io
import json
import re
from collections.abc import Iterator
from html.parser import HTMLParser
from itertools import chain
from urllib.parse import urlsplit

from .models import ProxyCandidate, validate_candidate


def _record_endpoints(record: dict, protocol: str) -> Iterator[tuple[str, str]]:
    if any(record.get(key) for key in ("username", "password", "user", "credentials")):
        return
    host = record.get("ip", record.get("host"))
    port = record.get("port")
    if not isinstance(host, str) or isinstance(port, bool):
        return
    if not (type(port) is int or isinstance(port, str) and port.isascii() and port.isdigit()):
        return
    host = f"[{host}]" if ":" in host and not host.startswith("[") else host
    protocols = record.get("protocols", record.get("protocol", protocol))
    if isinstance(protocols, str):
        protocols = [protocols]
    if isinstance(protocols, list):
        for item in protocols:
            if isinstance(item, str):
                yield f"{host}:{port}", item.lower()


def _json_endpoints(value: object, protocol: str) -> Iterator[tuple[str, str]]:
    if isinstance(value, str):
        for line in value.splitlines():
            yield line.strip(), protocol
    elif isinstance(value, list):
        for child in value:
            yield from _json_endpoints(child, protocol)
    elif isinstance(value, dict):
        if any(value.get(key) for key in ("username", "password", "user", "credentials")):
            return
        yield from _record_endpoints(value, protocol)
        for child in value.values():
            if isinstance(child, (dict, list, str)):
                yield from _json_endpoints(child, protocol)


def _text_endpoints(text: str, protocol: str) -> Iterator[tuple[str, str]]:
    for match in re.finditer(r"[^\s,;|]+", text):
        token = match.group(0)
        yield token.strip("\"'"), protocol


class _ProxyHTML(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.visible: list[str] = []
        self.links: list[str] = []
        self.rows: list[list[str]] = []
        self.row: list[str] | None = None
        self.cell: list[str] | None = None
        self.hidden = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("script", "style"):
            self.hidden += 1
        if self.hidden:
            return
        self.visible.append("\n")
        if tag == "a":
            self.links.extend(value for key, value in attrs if key == "href" and value)
        elif tag == "tr":
            self.row = []
        elif tag in ("td", "th"):
            self.cell = []

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style"):
            self.hidden = max(0, self.hidden - 1)
        if self.hidden:
            return
        self.visible.append("\n")
        if tag in ("td", "th") and self.cell is not None:
            if self.row is not None:
                self.row.append("".join(self.cell).strip())
            self.cell = None
        elif tag == "tr" and self.row is not None:
            self.rows.append(self.row)
            self.row = None

    def handle_data(self, data: str) -> None:
        if not self.hidden:
            self.visible.append(data)
            if self.cell is not None:
                self.cell.append(data)


def _html_endpoints(text: str, protocol: str) -> Iterator[tuple[str, str]]:
    document = _ProxyHTML()
    document.feed(text)
    for cells in document.rows:
        if len(cells) >= 2:
            item_protocol = next(
                (cell.lower() for cell in cells[2:] if cell.lower() in {"http", "https", "socks4", "socks5"}),
                protocol,
            )
            yield from _record_endpoints({"ip": cells[0], "port": cells[1]}, item_protocol)
    for link in document.links:
        yield link, protocol
    yield from _text_endpoints("".join(document.visible), protocol)


def _csv_endpoints(text: str, protocol: str) -> Iterator[tuple[str, str]]:
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    reader = csv.reader(io.StringIO(text), dialect)
    try:
        first = next(reader, [])
        header = [cell.strip().lower() for cell in first]
        has_header = bool(set(header) & {"ip", "host", "port", "proxy", "url"})
        if not has_header:
            reader = chain([first], reader)
        for row in reader:
            if has_header:
                record = dict(zip(header, (cell.strip() for cell in row)))
            elif len(row) >= 2:
                record = {"ip": row[0].strip(), "port": row[1].strip()}
                if len(row) >= 3:
                    record["protocol"] = row[2].strip().lower()
            else:
                for cell in row:
                    yield cell.strip(), protocol
                continue
            if any(record.get(key) for key in ("username", "password", "user", "credentials")):
                continue
            yield from _record_endpoints(record, protocol)
            for key in ("proxy", "url"):
                if record.get(key):
                    yield record[key], record.get("protocol") or protocol
    except csv.Error:
        return


def _parse_endpoint(value: str, protocol: str) -> ProxyCandidate | None:
    try:
        parsed = urlsplit(value if "://" in value else f"{protocol}://{value}")
        if parsed.username is not None or parsed.password is not None:
            return None
        if parsed.path not in ("", "/") or parsed.query or parsed.fragment:
            return None
        item_protocol = "http" if parsed.scheme == "https" else parsed.scheme
        return validate_candidate(ProxyCandidate(parsed.hostname or "", parsed.port, item_protocol))
    except (ValueError, TypeError):
        return None


def parse_candidates(
    text: str, protocol: str = "http", format: str = "text", max_items: int = 100000
) -> list[ProxyCandidate]:
    """Parse public endpoints, preserving first appearance and protocol identity."""
    if type(max_items) is not int or max_items < 0:
        raise ValueError("max_items must be a non-negative integer")
    if protocol not in {"http", "https", "socks4", "socks5"}:
        raise ValueError("unsupported proxy protocol")
    if format not in {"text", "html", "json", "csv"}:
        raise ValueError("unsupported source format")
    if max_items == 0:
        return []
    result: dict[str, ProxyCandidate] = {}
    if format == "json":
        try:
            endpoints = _json_endpoints(json.loads(text), protocol)
        except (ValueError, RecursionError):
            return []
    elif format == "html":
        endpoints = _html_endpoints(text, protocol)
    elif format == "csv":
        endpoints = _csv_endpoints(text, protocol)
    else:
        endpoints = _text_endpoints(text, protocol)
    for value, item_protocol in endpoints:
        candidate = _parse_endpoint(value, item_protocol)
        if candidate is not None:
            result.setdefault(candidate.key, candidate)
            if len(result) >= max_items:
                break
    return list(result.values())
