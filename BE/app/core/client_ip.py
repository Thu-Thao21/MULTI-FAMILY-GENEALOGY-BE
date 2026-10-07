"""The IP address of the caller, for rate limiting (Mốc E, step E3).

Default: the address of the TCP peer, and X-Forwarded-For is IGNORED. The header is written
by the caller, so trusting it lets anyone pick the address that is counted (and so escape the
limit). Behind a reverse proxy that is the ONLY way in, set TRUST_PROXY_HEADERS=true: the
header is then read from the RIGHT, because each trusted proxy appends the address it saw as
its peer, so the entries on the left are whatever the caller sent. TRUSTED_PROXY_COUNT is the
number of proxies in front of the app (1: the last entry is the client).

Anything that is not a valid address, a missing header or a header with fewer entries than
TRUSTED_PROXY_COUNT falls back to the peer address, never to a value the caller made up.

When X-Forwarded-For arrives while TRUST_PROXY_HEADERS is off, ONE warning per process says
so (without any address): behind a proxy every client would otherwise share the proxy's IP
and be limited together (docs/known_issues.md KI-11, KI-17).
"""

from __future__ import annotations

import ipaddress
import logging
import threading

from starlette.requests import Request

logger = logging.getLogger("mfg.client_ip")

FORWARDED_FOR = "x-forwarded-for"

_warn_lock = threading.Lock()
_warned_forwarded_for = False


def _reset_warning_state() -> None:
    """Tests only: forget that the warning was already logged."""
    global _warned_forwarded_for
    with _warn_lock:
        _warned_forwarded_for = False


def _warn_forwarded_for_ignored_once() -> None:
    global _warned_forwarded_for
    with _warn_lock:
        if _warned_forwarded_for:
            return
        _warned_forwarded_for = True
    logger.warning(
        "X-Forwarded-For header received while TRUST_PROXY_HEADERS is off: the header is "
        "ignored. Behind a reverse proxy every client now shares the proxy address for rate "
        "limiting; set TRUST_PROXY_HEADERS=true only if the proxy is the sole way in "
        "(docs/known_issues.md KI-11 and KI-17). Logged once per process."
    )


def parse_ip(text: str | None) -> str | None:
    """A normalized address, or None. Accepts 'a.b.c.d:port' and '[v6]:port' forms."""
    if not text:
        return None
    value = text.strip()
    if value.startswith("[") and "]" in value:
        value = value[1 : value.index("]")]
    elif value.count(":") == 1 and "." in value:
        value = value.split(":", 1)[0]
    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        return None


def client_ip(
    request: Request, *, trust_proxy_headers: bool = False, trusted_proxy_count: int = 1
) -> str | None:
    peer = parse_ip(request.client.host) if request.client else None
    header_values = request.headers.getlist(FORWARDED_FOR)
    if not trust_proxy_headers:
        if header_values:
            _warn_forwarded_for_ignored_once()
        return peer
    if not header_values:
        return peer
    entries = [part.strip() for value in header_values for part in value.split(",")]
    if trusted_proxy_count < 1 or len(entries) < trusted_proxy_count:
        return peer
    return parse_ip(entries[-trusted_proxy_count]) or peer
