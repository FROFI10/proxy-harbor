"""Value types shared by the collector, checker, and database."""

import ipaddress
import time
from dataclasses import dataclass, field

PROTOCOLS = frozenset({"http", "socks4", "socks5"})
CHECK_VALIDATION_VERSION = 2


def is_public_ip(value: str) -> bool:
    """Require an unscoped, globally routable unicast literal."""
    try:
        ip = ipaddress.ip_address(value)
    except ValueError:
        return False
    return ip.is_global and not ip.is_multicast and not ip.is_reserved and "%" not in value


def validate_candidate(candidate: "ProxyCandidate", *, allow_private: bool = False) -> "ProxyCandidate":
    """Validate at every trust boundary; private bypass is for fixtures only."""
    if not isinstance(candidate.host, str) or "%" in candidate.host:
        raise ValueError("proxy host must be an unscoped IP literal")
    try:
        host = str(ipaddress.ip_address(candidate.host))
    except ValueError as exc:
        raise ValueError("proxy host must be an IP literal") from exc
    if not allow_private and not is_public_ip(host):
        raise ValueError("proxy host must be a public globally routable IP")
    if type(candidate.port) is not int or not 1 <= candidate.port <= 65535:
        raise ValueError("proxy port must be an integer between 1 and 65535")
    if candidate.protocol not in PROTOCOLS:
        raise ValueError("unsupported proxy protocol")
    return ProxyCandidate(host, candidate.port, candidate.protocol)


@dataclass(frozen=True, slots=True)
class ProxyCandidate:
    host: str
    port: int
    protocol: str

    @property
    def address(self) -> str:
        host = f"[{self.host}]" if ":" in self.host else self.host
        return f"{host}:{self.port}"

    @property
    def url(self) -> str:
        return f"{self.protocol}://{self.address}"

    @property
    def key(self) -> str:
        return self.url


@dataclass(slots=True)
class CheckResult:
    candidate: ProxyCandidate
    ok: bool
    latency_ms: float | None = None
    supports_https: bool = False
    exit_ip: str | None = None
    error: str | None = None
    checked_at: float = field(default_factory=time.time)
    # Zero means unverified/legacy; only the full independent challenge sets V2.
    validation_version: int = 0


@dataclass(slots=True)
class SourceSpec:
    id: str
    name: str
    url: str
    protocol: str = "http"
    format: str = "text"
    enabled: bool = True
