"""Validated public proxy source registry and bounded network ingestion."""

from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import json
import math
import os
import re
import socket
import tempfile
import zlib
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from urllib.parse import quote, urlencode, urljoin, urlsplit

import aiohttp

from .models import SourceSpec


def _is_public_address(host: str) -> bool:
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    if not address.is_global or address.is_multicast or address.is_reserved:
        return False
    mapped = getattr(address, "ipv4_mapped", None)
    return mapped is None or _is_public_address(str(mapped))


def validate_source_url(url: str) -> str:
    """Accept only unambiguous HTTP/S URLs; DNS is checked at fetch time.

    Return the original URL, not a silently repaired version. Credentials,
    fragments, local/numeric shorthand hosts and ambiguous syntax are rejected.
    """
    if not isinstance(url, str) or not url or len(url) > 4096:
        raise ValueError("source URL must be a nonempty string of at most 4096 characters")
    if any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in url) or "\\" in url:
        raise ValueError("source URL contains whitespace, controls or a backslash")
    try:
        parts = urlsplit(url)
        host, port = parts.hostname, parts.port
    except ValueError as exc:
        raise ValueError(f"malformed source URL or port: {exc}") from exc
    if parts.scheme.lower() not in {"http", "https"}:
        raise ValueError("source URL scheme must be http or https")
    if parts.username is not None or parts.password is not None or "@" in parts.netloc:
        raise ValueError("source URL credentials are forbidden")
    if parts.fragment or "#" in url:
        raise ValueError("source URL fragments are forbidden")
    if not host or "%" in host or parts.netloc.endswith(":"):
        raise ValueError("source URL has an invalid host or port")
    if port is not None and not 1 <= port <= 65535:
        raise ValueError("source URL port must be between 1 and 65535")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        name = host.rstrip(".").lower()
        if name == "localhost" or name.endswith((".localhost", ".local", ".internal", ".lan", ".home")):
            raise ValueError("source host must be public, not a local/private hostname")
        try:
            name = name.encode("idna").decode("ascii")
        except UnicodeError as exc:
            raise ValueError("invalid source URL hostname") from exc
        labels = name.split(".")
        if (
            len(name) > 253
            or len(labels) < 2
            or any(not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) for label in labels)
        ):
            raise ValueError("invalid source URL hostname; a public fully qualified host is required")
        if all(re.fullmatch(r"(?:0x[0-9a-f]+|[0-9]+)", label) for label in labels):
            raise ValueError("source host must not use ambiguous numeric IP notation")
    else:
        if not _is_public_address(host):
            raise ValueError("source host must be a public globally routable address")
    return url


def _validated_sources(rows):
    from .models import SourceSpec

    if not isinstance(rows, list):
        raise ValueError("source registry must be a JSON array")
    result, seen, ids = [], set(), set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("each source must be an object")
        values = {"protocol": "http", "format": "text", "enabled": True, **row}
        source_id, name = values.get("id"), values.get("name")
        if not isinstance(source_id, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", source_id):
            raise ValueError("source id must be 1-128 ASCII letters, digits, dots, underscores or hyphens")
        if not isinstance(name, str) or not name.strip() or len(name) > 256 or any(ord(c) < 32 for c in name):
            raise ValueError("source name must be nonempty text of at most 256 characters without controls")
        if type(values["enabled"]) is not bool:
            raise ValueError("source enabled must be a JSON boolean")
        if not isinstance(values["format"], str) or values["format"] not in {"text", "html", "json", "csv"}:
            raise ValueError("source format must be text, html, json or csv")
        validate_source_url(values.get("url"))
        protocol = values["protocol"]
        if protocol == "https":
            protocol = "http"
        if not isinstance(protocol, str) or protocol not in {"http", "socks4", "socks5"}:
            raise ValueError("source protocol must be http, socks4 or socks5")
        values["protocol"] = protocol
        key = (values["url"], protocol)
        if key in seen:
            continue
        if values.get("id") in ids:
            raise ValueError("source IDs must be unique")
        try:
            source = SourceSpec(**values)
        except TypeError as exc:
            raise ValueError(f"invalid source fields: {exc}") from exc
        result.append(source)
        seen.add(key)
        ids.add(source.id)
    return result


def load_sources(path: str | Path) -> list[SourceSpec]:
    """Load, validate and deduplicate by the exact URL plus normalized protocol."""
    try:
        rows = json.loads(Path(path).read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise ValueError(f"invalid source registry JSON: {exc}") from exc
    return _validated_sources(rows)


def save_sources(path: str | Path, sources: list[SourceSpec]) -> None:
    """Validate the complete registry before atomically replacing the target."""
    rows = _validated_sources([asdict(source) for source in sources])
    data = json.dumps([asdict(source) for source in rows], ensure_ascii=False, indent=2) + "\n"
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            prefix=f".{destination.name}.",
            suffix=".tmp",
            dir=destination.parent,
            delete=False,
        ) as handle:
            temporary = handle.name
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    finally:
        if temporary is not None:
            Path(temporary).unlink(missing_ok=True)


class SourceFetchError(RuntimeError):
    """A bounded source fetch failed; HTTP status is retained for an audit."""

    def __init__(self, message: str, *, url: str, status: int | None = None):
        super().__init__(f"{message}: {url}")
        self.url = url
        self.status = status


async def _resolve_public(host: str, port: int, family: int = socket.AF_UNSPEC) -> list[dict]:
    answers = await asyncio.get_running_loop().getaddrinfo(
        host, port, family=socket.AF_UNSPEC, type=socket.SOCK_STREAM
    )
    if not answers or any(not _is_public_address(address[0]) for _, _, _, _, address in answers):
        raise ValueError(f"DNS for {host} must return only public globally routable addresses")
    return [
        {
            "hostname": host,
            "host": address[0],
            "port": address[1],
            "family": fam,
            "proto": proto,
            "flags": socket.AI_NUMERICHOST,
        }
        for fam, _, proto, _, address in answers
    ]


class _PublicResolver(aiohttp.abc.AbstractResolver):
    async def resolve(self, host: str, port: int = 0, family: int = socket.AF_UNSPEC):
        return await _resolve_public(host, port, family)

    async def close(self):
        pass


async def _read_bounded(response: aiohttp.ClientResponse, max_bytes: int) -> bytes:
    encoding = response.headers.get("Content-Encoding", "identity").strip().lower()
    if encoding not in {"identity", "", "gzip", "deflate"}:
        raise SourceFetchError(
            f"unsupported Content-Encoding {encoding}", url=str(response.url), status=response.status
        )
    decoder = None if encoding in {"identity", ""} else zlib.decompressobj(31 if encoding == "gzip" else 15)
    body, wire_bytes = bytearray(), 0
    async for chunk in response.content.iter_chunked(8192):
        wire_bytes += len(chunk)
        if wire_bytes > 2 * max_bytes + 65536:
            raise SourceFetchError(
                "compressed wire body limit exceeded", url=str(response.url), status=response.status
            )
        pending = chunk
        while pending:
            if decoder is None:
                output, pending = pending, b""
            else:
                if decoder.eof:
                    if encoding != "gzip":
                        raise SourceFetchError(
                            "trailing compressed data", url=str(response.url), status=response.status
                        )
                    decoder = zlib.decompressobj(31)
                try:
                    output = decoder.decompress(pending, max_bytes + 1 - len(body))
                except zlib.error as exc:
                    raise SourceFetchError(
                        f"invalid compressed {encoding} body: {exc}",
                        url=str(response.url),
                        status=response.status,
                    ) from exc
                pending = decoder.unconsumed_tail or decoder.unused_data
            body.extend(output)
            if len(body) > max_bytes:
                raise SourceFetchError(
                    f"decompressed body limit exceeded ({max_bytes} bytes)",
                    url=str(response.url),
                    status=response.status,
                )
    if decoder is not None and not decoder.eof:
        raise SourceFetchError(
            f"truncated compressed {encoding} body", url=str(response.url), status=response.status
        )
    return bytes(body)


@dataclass(frozen=True, slots=True)
class _FetchedDocument:
    text: str
    http_status: int
    final_url: str
    decompressed_bytes: int
    sha256: str


async def fetch_source(
    session: aiohttp.ClientSession, source: SourceSpec, timeout: float = 15, max_bytes: int = 5_000_000
) -> str:
    """Fetch only public HTTP/S with a total deadline and a decompressed bound."""
    return (await _fetch_document(session, source, timeout, max_bytes)).text


async def _fetch_document(
    session: aiohttp.ClientSession, source: SourceSpec, timeout: float = 15, max_bytes: int = 5_000_000
) -> _FetchedDocument:
    """Same protected path as fetch_source, with metadata for the audit script."""
    if type(max_bytes) is not int or not 1 <= max_bytes <= 50_000_000:
        raise ValueError("max_bytes must be an integer between 1 and 50000000")
    if type(timeout) not in {int, float} or not math.isfinite(timeout) or not 0 < timeout <= 300:
        raise ValueError("timeout must be finite, positive and at most 300 seconds")
    if session.trust_env:
        raise ValueError("source parent session must set trust_env=False")
    url = validate_source_url(source.url)
    try:
        async with asyncio.timeout(timeout):
            document = await _fetch_text(url, timeout, max_bytes)
            text = _normalize_json_provider(document.text) if source.format == "json" else document.text
            return replace(document, text=text)
    except TimeoutError as exc:
        raise SourceFetchError(f"source timeout after {timeout} seconds", url=url) from exc


def _normalize_json_provider(text: str) -> str:
    """Adapt proxy-list.download's uppercase IP/PORT aliases without repairing values.

    Audit byte count/hash always describe the original decompressed HTTP body.
    Geonode/lowercase JSON and all non-JSON documents remain unchanged.
    """
    if '"IP"' not in text or '"PORT"' not in text:
        return text
    try:
        value = json.loads(text)
        changed = False

        def walk(item):
            nonlocal changed
            if isinstance(item, dict):
                if "IP" in item and "PORT" in item:
                    item.setdefault("ip", item.pop("IP"))
                    item.setdefault("port", item.pop("PORT"))
                    for upper, lower in (
                        ("USERNAME", "username"),
                        ("PASSWORD", "password"),
                        ("USER", "user"),
                        ("CREDENTIALS", "credentials"),
                    ):
                        if upper in item:
                            item.setdefault(lower, item.pop(upper))
                    changed = True
                for child in item.values():
                    walk(child)
            elif isinstance(item, list):
                for child in item:
                    walk(child)

        walk(value)
        return json.dumps(value, ensure_ascii=False, separators=(",", ":")) if changed else text
    except (ValueError, RecursionError):
        return text


async def _fetch_text(url: str, timeout: float, max_bytes: int) -> _FetchedDocument:
    connector = aiohttp.TCPConnector(
        resolver=_PublicResolver(), use_dns_cache=False, force_close=True, limit=1
    )
    async with aiohttp.ClientSession(
        connector=connector,
        trust_env=False,
        auto_decompress=False,
        headers={"Accept-Encoding": "gzip, deflate"},
    ) as client:
        for hop in range(6):
            async with client.get(
                url, allow_redirects=False, timeout=aiohttp.ClientTimeout(total=timeout)
            ) as response:
                if response.status in {301, 302, 303, 307, 308}:
                    location = response.headers.get("Location")
                    if not location or hop == 5:
                        raise RuntimeError(f"source redirect limit or missing Location: {url}")
                    validate_source_url(location if urlsplit(location).scheme else urljoin(url, location))
                    url = validate_source_url(urljoin(url, location))
                    continue
                if not 200 <= response.status < 300:
                    detail = f"HTTP {response.status} {response.reason}"
                    if response.status in {403, 429}:
                        detail += " (access denied or rate limit; no bypass attempted)"
                        reset = response.headers.get("X-RateLimit-Reset") or response.headers.get(
                            "Retry-After"
                        )
                        if reset:
                            detail += f"; retry/reset hint {reset[:100]}"
                    raise SourceFetchError(detail, url=url, status=response.status)
                body = await _read_bounded(response, max_bytes)
                return _FetchedDocument(
                    body.decode(response.charset or "utf-8", errors="replace"),
                    response.status,
                    str(response.url),
                    len(body),
                    hashlib.sha256(body).hexdigest(),
                )
        raise RuntimeError(f"source redirect limit: {url}")


_GITHUB_API = "https://api.github.com"
_GITHUB_RAW = "https://raw.githubusercontent.com"
_DISCOVERY_TIMEOUT = 120


class GitHubDiscoveryError(RuntimeError):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


async def _github_json(session: aiohttp.ClientSession, url: str) -> dict:
    from .models import SourceSpec

    try:
        payload = await fetch_source(
            session,
            SourceSpec("github-api", "GitHub public API", url, format="json"),
            timeout=15,
            max_bytes=1_000_000,
        )
    except SourceFetchError as exc:
        if exc.status in {403, 429}:
            raise GitHubDiscoveryError(
                f"GitHub public API HTTP {exc.status}: rate limit or access denied; {exc}", exc.status
            ) from exc
        raise GitHubDiscoveryError(f"GitHub public API request failed: {exc}", exc.status) from exc
    try:
        parsed = json.loads(payload)
    except (ValueError, RecursionError) as exc:
        raise GitHubDiscoveryError(f"GitHub malformed API JSON: {url}") from exc
    if not isinstance(parsed, dict):
        raise GitHubDiscoveryError(f"GitHub malformed API response: expected an object at {url}")
    return parsed


async def discover_github_sources(
    session: aiohttp.ClientSession, existing: list[SourceSpec], max_repos: int = 20
) -> list[SourceSpec]:
    """Bounded public API discovery, with an explicit error on rate limits."""
    try:
        async with asyncio.timeout(_DISCOVERY_TIMEOUT):
            return await _discover_github_sources(session, existing, max_repos)
    except TimeoutError as exc:
        raise GitHubDiscoveryError("GitHub discovery timeout: total deadline exceeded") from exc


async def _discover_github_sources(session: aiohttp.ClientSession, existing, max_repos: int):
    """Discover tree-listed public feeds; never return an unverified candidate URL."""
    from .models import SourceSpec
    from .parsing import parse_candidates

    if type(max_repos) is not int or max_repos < 0:
        raise ValueError("max_repos must be a non-negative integer")
    max_repos = min(max_repos, 20)
    if max_repos == 0:
        return []
    query = urlencode(
        {"q": "proxy-list in:name fork:false archived:false", "sort": "updated", "per_page": max_repos}
    )
    search = await _github_json(session, _GITHUB_API + "/search/repositories?" + query)
    if not isinstance(search.get("items"), list):
        raise GitHubDiscoveryError("GitHub malformed search response: items must be an array")
    known = {(s.url, "http" if s.protocol == "https" else s.protocol) for s in existing}
    result = []
    for repo in search["items"][:max_repos]:
        if not isinstance(repo, dict) or repo.get("fork") or repo.get("archived"):
            continue
        name, branch = repo.get("full_name"), repo.get("default_branch")
        if not isinstance(name, str) or not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9_.-]{1,100}", name
        ):
            continue
        if name.split("/")[1] in {".", ".."}:
            continue
        if not isinstance(branch, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,199}", branch):
            continue
        if any(part in {"", ".", ".."} for part in branch.split("/")):
            continue
        tree_url = (
            f"{_GITHUB_API}/repos/{quote(name, safe='/')}/git/trees/{quote(branch, safe='')}?recursive=1"
        )
        try:
            tree = await _github_json(session, tree_url)
        except GitHubDiscoveryError as exc:
            if exc.status == 404:
                continue  # repository deleted or branch moved during discovery
            raise
        if not isinstance(tree.get("tree"), list):
            raise GitHubDiscoveryError("GitHub malformed tree response: tree must be an array")
        repo_protocols = set()
        attempts = 0
        for node in tree["tree"][:2000]:
            if not isinstance(node, dict):
                continue
            path, size = node.get("path"), node.get("size", 0)
            if (
                not isinstance(path, str)
                or not path
                or len(path) > 512
                or "\\" in path
                or any(ord(c) < 32 for c in path)
            ):
                continue
            if any(part in {"", ".", ".."} for part in path.split("/")):
                continue
            if type(size) is not int or not 0 <= size <= 5_000_000:
                continue
            if node.get("type") != "blob" or not path.lower().endswith((".txt", ".json")):
                continue
            label = re.search(r"(?:^|[._/-])(socks5|socks4|https?)(?:$|[._/-])", path.lower())
            generic = any(token in path.lower() for token in ("proxy", "proxies", "all")) or path.endswith(
                ".json"
            )
            if label is None and not generic:
                continue
            protocol = label.group(1) if label else "http"
            protocol = "http" if protocol == "https" else protocol
            url = f"{_GITHUB_RAW}/{quote(name, safe='/')}/{quote(branch, safe='/')}/{quote(path, safe='/')}"
            if (url, protocol) in known or protocol in repo_protocols:
                continue
            attempts += 1
            if attempts > 4:
                break
            source_id = "github-" + hashlib.sha256((url + "\n" + protocol).encode()).hexdigest()[:16]
            source = SourceSpec(
                source_id,
                f"{name} · {protocol.upper()}",
                url,
                protocol,
                "json" if path.lower().endswith(".json") else "text",
                True,
            )
            try:
                body = await fetch_source(session, source)
                candidates = parse_candidates(body, protocol, source.format, max_items=10000)
                if not candidates:
                    continue
                if label is None:
                    alternate = parse_candidates(body, "socks5", source.format, max_items=10000)
                    if {p.key for p in candidates} != {p.key for p in alternate}:
                        continue  # bare mixed feeds have no reliable protocol hint
            except (ValueError, RuntimeError, aiohttp.ClientError, OSError):
                continue
            result.append(source)
            known.add((url, protocol))
            repo_protocols.add(protocol)
    return result
