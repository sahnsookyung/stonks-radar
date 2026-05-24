from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse


PRIVATE_NETWORKS = [
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("224.0.0.0/4"),
    ipaddress.ip_network("240.0.0.0/4"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
    ipaddress.ip_network("ff00::/8"),
]


@dataclass(frozen=True)
class FetchPolicyDecision:
    allowed: bool
    reason: str
    resolved_ips: list[str]


def evaluate_url(url: str) -> FetchPolicyDecision:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return FetchPolicyDecision(False, "Only http and https URLs are allowed", [])
    if not parsed.hostname:
        return FetchPolicyDecision(False, "URL must include a hostname", [])
    try:
        infos = socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80))
    except socket.gaierror as exc:
        return FetchPolicyDecision(False, f"DNS resolution failed: {exc}", [])
    resolved: list[str] = []
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        resolved.append(str(ip))
        if any(ip in network for network in PRIVATE_NETWORKS):
            return FetchPolicyDecision(False, f"Private or metadata IP blocked: {ip}", resolved)
    return FetchPolicyDecision(True, "allowed", sorted(set(resolved)))


def resolve_redirect(base_url: str, location: str) -> FetchPolicyDecision:
    return evaluate_url(urljoin(base_url, location))


def redirect_url(base_url: str, location: str) -> str:
    return urljoin(base_url, location)
