"""SSRF-safe URL validation utilities.

Prevents scraping of internal/private network addresses, localhost,
cloud metadata endpoints, and non-HTTP(S) schemes.
"""

import ipaddress
import logging
import socket
from typing import Optional, Tuple
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

ALLOWED_SCHEMES = {"http", "https"}

# Private/reserved IP ranges that must be blocked to prevent SSRF
BLOCKED_NETWORKS = [
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("100.64.0.0/10"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.0.0.0/24"),
    ipaddress.ip_network("192.0.2.0/24"),
    ipaddress.ip_network("192.88.99.0/24"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("198.18.0.0/15"),
    ipaddress.ip_network("198.51.100.0/24"),
    ipaddress.ip_network("203.0.113.0/24"),
    ipaddress.ip_network("224.0.0.0/4"),
    ipaddress.ip_network("240.0.0.0/4"),
    ipaddress.ip_network("255.255.255.255/32"),
    # IPv6
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("::/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
    ipaddress.ip_network("ff00::/8"),
]

BLOCKED_HOSTNAMES = {"localhost", "metadata.google.internal"}


def _is_ip_blocked(ip_str: str) -> bool:
    """Check if an IP address falls within a blocked range."""
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return True  # Unparseable IPs are blocked
    return any(ip in network for network in BLOCKED_NETWORKS)


def validate_policy_url(url: str) -> Tuple[bool, Optional[str]]:
    """Validate a URL is safe to scrape.

    Returns (is_valid, error_message). error_message is None when valid.
    """
    if not url or not isinstance(url, str):
        return False, "URL must be a non-empty string"

    url = url.strip()
    if len(url) > 2048:
        return False, "URL exceeds maximum length of 2048 characters"

    try:
        parsed = urlparse(url)
    except Exception:
        return False, "Invalid URL format"

    # Scheme check
    if parsed.scheme not in ALLOWED_SCHEMES:
        return False, f"URL scheme must be http or https, got '{parsed.scheme}'"

    hostname = parsed.hostname
    if not hostname:
        return False, "URL must include a hostname"

    # Block known dangerous hostnames
    hostname_lower = hostname.lower()
    if hostname_lower in BLOCKED_HOSTNAMES:
        return False, f"Hostname '{hostname}' is not allowed"

    # Block raw IP addresses in common private ranges (fast check before DNS)
    try:
        ip = ipaddress.ip_address(hostname)
        if _is_ip_blocked(str(ip)):
            return False, "URL points to a private or reserved IP address"
    except ValueError:
        pass  # Not an IP literal — will resolve via DNS below

    # DNS resolution check — ensure hostname doesn't resolve to private IP
    try:
        addrinfo = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
        for _family, _type, _proto, _canonname, sockaddr in addrinfo:
            if _is_ip_blocked(sockaddr[0]):
                return False, "URL resolves to a private or reserved IP address"
    except socket.gaierror:
        return False, f"Could not resolve hostname '{hostname}'"

    return True, None
