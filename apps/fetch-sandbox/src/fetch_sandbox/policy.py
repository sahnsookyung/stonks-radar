from __future__ import annotations

import ipaddress
import socket
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


class FetchDenied(ValueError):
    pass


def assert_url_allowed(url: str) -> list[str]:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise FetchDenied("Only http/https protocols are allowed")
    if not parsed.hostname:
        raise FetchDenied("Hostname is required")
    infos = socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80))
    resolved: list[str] = []
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        resolved.append(str(ip))
        if any(ip in network for network in PRIVATE_NETWORKS):
            raise FetchDenied(f"Private, link-local, loopback, or metadata IP blocked: {ip}")
    return sorted(set(resolved))


def resolve_redirect(base_url: str, location: str) -> str:
    next_url = urljoin(base_url, location)
    assert_url_allowed(next_url)
    return next_url
