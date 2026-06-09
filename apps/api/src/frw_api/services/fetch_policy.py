from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import ParseResult, urljoin, urlparse

from frw_api.core.settings import get_settings


PRIVATE_NETWORKS = [
    ipaddress.ip_network("0.0.0.0/8"),  # NOSONAR - intentional SSRF blocklist.
    ipaddress.ip_network("10.0.0.0/8"),  # NOSONAR - intentional SSRF blocklist.
    ipaddress.ip_network("127.0.0.0/8"),  # NOSONAR - intentional SSRF blocklist.
    ipaddress.ip_network("169.254.0.0/16"),  # NOSONAR - intentional SSRF blocklist.
    ipaddress.ip_network("172.16.0.0/12"),  # NOSONAR - intentional SSRF blocklist.
    ipaddress.ip_network("192.168.0.0/16"),  # NOSONAR - intentional SSRF blocklist.
    ipaddress.ip_network("224.0.0.0/4"),  # NOSONAR - intentional SSRF blocklist.
    ipaddress.ip_network("240.0.0.0/4"),  # NOSONAR - intentional SSRF blocklist.
    ipaddress.ip_network("::1/128"),  # NOSONAR - intentional SSRF blocklist.
    ipaddress.ip_network("fc00::/7"),  # NOSONAR - intentional SSRF blocklist.
    ipaddress.ip_network("fe80::/10"),  # NOSONAR - intentional SSRF blocklist.
    ipaddress.ip_network("ff00::/8"),  # NOSONAR - intentional SSRF blocklist.
]


@dataclass(frozen=True)
class FetchPolicyDecision:
    allowed: bool
    reason: str
    resolved_ips: list[str]


def evaluate_url(url: str) -> FetchPolicyDecision:
    parsed = urlparse(url)
    preflight = _url_preflight_decision(parsed)
    if preflight is not None:
        return preflight
    return _dns_policy_decision(parsed.hostname, parsed.port or _default_port(parsed.scheme))


def _url_preflight_decision(parsed: ParseResult) -> FetchPolicyDecision | None:
    if parsed.scheme not in ("http", "https"):
        return FetchPolicyDecision(False, "Only http and https URLs are allowed", [])
    if parsed.scheme == "http" and not get_settings().source_fetch_allow_http:
        return FetchPolicyDecision(False, "Plain HTTP source fetches are disabled", [])
    if parsed.hostname is None:
        return FetchPolicyDecision(False, "URL must include a hostname", [])
    return None


def _default_port(scheme: str) -> int:
    return 443 if scheme == "https" else 80


def _dns_policy_decision(hostname: str, port: int) -> FetchPolicyDecision:
    try:
        infos = socket.getaddrinfo(hostname, port)
    except socket.gaierror as exc:
        return FetchPolicyDecision(False, f"DNS resolution failed: {exc}", [])
    resolved: list[str] = []
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        resolved.append(str(ip))
        if is_blocked_ip(str(ip)):
            return FetchPolicyDecision(False, f"Private or metadata IP blocked: {ip}", resolved)
    return FetchPolicyDecision(True, "allowed", sorted(set(resolved)))


def is_blocked_ip(value: str) -> bool:
    try:
        ip = ipaddress.ip_address(value)
    except ValueError:
        return True
    return any(ip in network for network in PRIVATE_NETWORKS)


def resolve_redirect(base_url: str, location: str) -> FetchPolicyDecision:
    return evaluate_url(urljoin(base_url, location))


def redirect_url(base_url: str, location: str) -> str:
    return urljoin(base_url, location)
