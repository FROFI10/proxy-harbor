"""Bounded, application-level verification of untrusted public proxies."""

import asyncio
import ipaddress
import json
import math
import secrets
import ssl
import time
import zlib
from contextlib import asynccontextmanager
from urllib.parse import parse_qsl, urlsplit

import aiohttp
from aiohttp_socks import ProxyConnectionError, ProxyConnector, ProxyError, ProxyTimeoutError

from .models import CHECK_VALIDATION_VERSION, CheckResult, ProxyCandidate, is_public_ip, validate_candidate

_CHECK_ERRORS = (
    ValueError,
    aiohttp.ClientError,
    OSError,
    TimeoutError,
    ProxyConnectionError,
    ProxyError,
    ProxyTimeoutError,
)


class ProxyChecker:
    def __init__(
        self,
        timeout: float = 4.0,
        connect_timeout: float = 1.5,
        http_probe_url: str = "http://api.ipify.org?format=json",
        https_probe_url: str = "https://api.ipify.org?format=json",
        *,
        allow_private: bool = False,
        ssl_context: ssl.SSLContext | None = None,
        max_body_bytes: int = 16384,
        http_challenge_url: str | None = None,
        https_challenge_url: str | None = None,
    ) -> None:
        for name, value in (("timeout", timeout), ("connect_timeout", connect_timeout)):
            if (
                isinstance(value, bool)
                or not isinstance(value, (float, int))
                or not math.isfinite(value)
                or value <= 0
            ):
                raise ValueError(f"{name} must be finite and positive")
        if type(max_body_bytes) is not int or not 1 <= max_body_bytes <= 1048576:
            raise ValueError("max_body_bytes must be between 1 and 1048576")
        for url, scheme in ((http_probe_url, "http"), (https_probe_url, "https")):
            self._validate_probe_url(url, scheme, allow_private=allow_private)
        self._http_challenge_url = http_challenge_url or self._default_challenge(http_probe_url, "http")
        self._https_challenge_url = https_challenge_url or self._default_challenge(https_probe_url, "https")
        for probe, challenge, scheme in (
            (http_probe_url, self._http_challenge_url, "http"),
            (https_probe_url, self._https_challenge_url, "https"),
        ):
            self._validate_probe_url(challenge, scheme, allow_private=allow_private)
            if (
                urlsplit(probe).hostname.rstrip(".").lower()
                == urlsplit(challenge).hostname.rstrip(".").lower()
            ):
                raise ValueError("challenge host must be independent of the configured probe host")
            if urlsplit(challenge).fragment or any(
                key == "nonce" for key, _ in parse_qsl(urlsplit(challenge).query)
            ):
                raise ValueError("challenge URL must not contain a fragment or a pre-existing nonce")
        self.max_body_bytes = max_body_bytes
        self._ssl_context = ssl_context or ssl.create_default_context()
        if not self._ssl_context.check_hostname or self._ssl_context.verify_mode != ssl.CERT_REQUIRED:
            raise ValueError("TLS hostname and certificate verification must remain enabled")
        self.timeout = timeout
        self.connect_timeout = connect_timeout
        self.http_probe_url = http_probe_url
        self.https_probe_url = https_probe_url
        self._allow_private = allow_private
        self._session: aiohttp.ClientSession | None = None
        self._request_timeout = aiohttp.ClientTimeout(
            total=timeout, connect=connect_timeout, sock_connect=connect_timeout, sock_read=timeout
        )

    @staticmethod
    def _validate_probe_url(url: str, scheme: str, *, allow_private: bool) -> None:
        if not isinstance(url, str) or any(character in url for character in "\r\n\t"):
            raise ValueError("invalid probe URL")
        parsed = urlsplit(url)
        if (
            parsed.scheme != scheme
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
        ):
            raise ValueError(f"probe must be an unauthenticated {scheme.upper()} URL")
        if parsed.port is not None and not 1 <= parsed.port <= 65535:
            raise ValueError("invalid probe port")
        if not allow_private:
            if parsed.hostname.rstrip(".").lower() == "localhost":
                raise ValueError("probe must have a public host")
            try:
                ipaddress.ip_address(parsed.hostname)
            except ValueError:
                pass
            else:
                if not is_public_ip(parsed.hostname):
                    raise ValueError("probe must have a public host")

    @staticmethod
    def _default_challenge(probe_url: str, scheme: str) -> str:
        host = urlsplit(probe_url).hostname.rstrip(".").lower()
        provider = "httpbin.org" if host == "httpbingo.org" else "httpbingo.org"
        return f"{scheme}://{provider}/anything"

    @staticmethod
    def _nonce_url(base: str, nonce: str) -> str:
        return base + ("&" if urlsplit(base).query else "?") + "nonce=" + nonce

    async def start(self) -> None:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                connector=aiohttp.TCPConnector(limit=0, ssl=self._ssl_context),
                timeout=self._request_timeout,
                trust_env=False,
                auto_decompress=False,
            )

    async def close(self) -> None:
        if self._session is not None:
            await self._session.close()
            self._session = None

    async def _preflight(self, candidate: ProxyCandidate) -> None:
        async with asyncio.timeout(self.connect_timeout):
            _, writer = await asyncio.open_connection(candidate.host, candidate.port)
            writer.close()
            await writer.wait_closed()

    @asynccontextmanager
    async def _probe_session(self, candidate: ProxyCandidate):
        if candidate.protocol == "http":
            yield self._session, candidate.url
        else:
            connector = ProxyConnector.from_url(candidate.url, rdns=True, ssl=self._ssl_context, limit=4)
            async with aiohttp.ClientSession(
                connector=connector, timeout=self._request_timeout, trust_env=False, auto_decompress=False
            ) as session:
                yield session, None

    async def _read_probe_body(self, response: aiohttp.ClientResponse) -> bytes:
        """Limit both wire bytes and output; never let aiohttp inflate unbounded data."""
        limit = self.max_body_bytes
        if response.content_length is not None and response.content_length > limit:
            raise ValueError("probe response exceeds wire body limit")
        encoding = response.headers.get("Content-Encoding", "identity").strip().lower()
        if encoding in ("", "identity"):
            decoder = None
        elif encoding == "gzip":
            decoder = zlib.decompressobj(16 + zlib.MAX_WBITS)
        elif encoding == "deflate":
            decoder = zlib.decompressobj()
        else:
            raise ValueError("unsupported probe content encoding")
        body = bytearray()
        wire_bytes = 0
        try:
            async for chunk in response.content.iter_chunked(min(8192, limit + 1)):
                wire_bytes += len(chunk)
                if wire_bytes > limit:
                    raise ValueError("probe response exceeds wire body limit")
                output = decoder.decompress(chunk, limit + 1 - len(body)) if decoder is not None else chunk
                body.extend(output)
                if len(body) > limit:
                    raise ValueError("probe response exceeds decompressed body limit")
                if decoder is not None and (decoder.unused_data or decoder.unconsumed_tail):
                    raise ValueError("probe has trailing compressed data or exceeds body limit")
        except zlib.error as exc:
            raise ValueError("invalid compressed probe response") from exc
        if decoder is not None and not decoder.eof:
            raise ValueError("truncated compressed probe response")
        return bytes(body)

    async def _probe(
        self, session: aiohttp.ClientSession, url: str, proxy: str | None, *, nonce: str | None = None
    ) -> tuple[str, float]:
        started = time.perf_counter()
        async with session.get(
            url,
            proxy=proxy,
            allow_redirects=False,
            auto_decompress=False,
            headers={
                "Accept": "application/json",
                "Accept-Encoding": "identity",
                "Cache-Control": "no-cache",
            },
        ) as response:
            if not 200 <= response.status < 300:
                raise ValueError(f"probe returned HTTP {response.status}")
            document = json.loads(await self._read_probe_body(response))
            if nonce is not None:
                args = document.get("args") if isinstance(document, dict) else None
                echoed = args.get("nonce") if isinstance(args, dict) else None
                if echoed != nonce and echoed != [nonce]:
                    raise ValueError("independent challenge did not echo the fresh nonce")
                origin = document.get("origin")
                addresses = origin.split(",") if isinstance(origin, str) else []
                if not addresses or any(not is_public_ip(address.strip()) for address in addresses):
                    raise ValueError("independent challenge must contain a public origin IP")
                exit_ip = addresses[0].strip()
            else:
                exit_ip = document.get("ip", document.get("origin")) if isinstance(document, dict) else None
            if not isinstance(exit_ip, str) or not is_public_ip(exit_ip):
                raise ValueError("probe JSON must contain a public exit IP")
        return str(ipaddress.ip_address(exit_ip)), (time.perf_counter() - started) * 1000

    async def _attempt(
        self, session: aiohttp.ClientSession, url: str, proxy: str | None, *, nonce: str | None = None
    ) -> tuple[tuple[str, float] | None, str | None]:
        try:
            return await self._probe(session, url, proxy, nonce=nonce), None
        except _CHECK_ERRORS as exc:
            return None, f"{type(exc).__name__}: {exc}"[:512]

    async def check(self, candidate: ProxyCandidate) -> CheckResult:
        try:
            candidate = validate_candidate(candidate, allow_private=self._allow_private)
            await self.start()
            await self._preflight(candidate)
            http_nonce, https_nonce = secrets.token_urlsafe(18), secrets.token_urlsafe(18)
            async with self._probe_session(candidate) as (session, proxy):
                http, https, challenge_http, challenge_https = await asyncio.gather(
                    self._attempt(session, self.http_probe_url, proxy),
                    self._attempt(session, self.https_probe_url, proxy),
                    self._attempt(
                        session,
                        self._nonce_url(self._http_challenge_url, http_nonce),
                        proxy,
                        nonce=http_nonce,
                    ),
                    self._attempt(
                        session,
                        self._nonce_url(self._https_challenge_url, https_nonce),
                        proxy,
                        nonce=https_nonce,
                    ),
                )
            http_verified = http[0] is not None and challenge_http[0] is not None
            https_verified = https[0] is not None and challenge_https[0] is not None
            if http_verified or https_verified:
                primary, challenge = (
                    (https[0], challenge_https[0]) if https_verified else (http[0], challenge_http[0])
                )
                exit_ip = challenge[0]
                latency_ms = max(primary[1], challenge[1])
                return CheckResult(
                    candidate,
                    True,
                    latency_ms=latency_ms,
                    exit_ip=exit_ip,
                    supports_https=https_verified,
                    validation_version=CHECK_VALIDATION_VERSION,
                )
            return CheckResult(
                candidate,
                False,
                validation_version=CHECK_VALIDATION_VERSION,
                error=(
                    f"HTTP: {http[1] or 'IP probe passed'}; HTTPS: {https[1] or 'IP probe passed'}; "
                    f"HTTP challenge: {challenge_http[1] or 'passed'}; HTTPS challenge: {challenge_https[1] or 'passed'}"
                )[:1536],
            )
        except (ValueError, aiohttp.ClientError, OSError, TimeoutError) as exc:
            return CheckResult(
                candidate,
                False,
                error=f"{type(exc).__name__}: {exc}"[:512],
                validation_version=CHECK_VALIDATION_VERSION,
            )
