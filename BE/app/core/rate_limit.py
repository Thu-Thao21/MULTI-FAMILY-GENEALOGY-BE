"""In-memory sliding-window rate limiter for the public endpoints (Mốc E, step E3).

Exact sliding log: every key keeps the times of its allowed calls inside the window. A call is
refused when the window already holds `limit` calls; the refusal is not recorded, so waiting
frees the window by itself. Retry-After is the number of seconds (rounded up, at least 1)
until the oldest call leaves the window.

Keys are (limiter name, caller address). IPv4 as is; IPv6 grouped by its /64 so a client
cannot dodge the limit by rotating addresses inside its own network.

Memory is bounded:
  * expired calls are dropped whenever a key is touched;
  * every `sweep_interval` seconds the whole table is swept and empty keys are deleted;
  * the table never holds more than `max_keys` keys: when it is full it is swept first and,
    if that is not enough, the least recently used key is evicted. An attacker with very many
    addresses can use that to reset his own counters, at a cost to himself; the table itself
    cannot grow.

Safe for threads (a lock) and for the event loop (check() never awaits).

LIMITS (docs/known_issues.md KI-17): the counters live in ONE process. N workers allow N times
the limit, a restart resets everything, and behind a reverse proxy without TRUST_PROXY_HEADERS
all clients share one address. It slows down simple spam; it is not a defence against a
distributed attacker. A shared limiter (Redis, a table) or a limit at the proxy is the
follow-up.
"""

from __future__ import annotations

import ipaddress
import math
import threading
import time
from collections import OrderedDict, deque
from dataclasses import dataclass
from typing import Callable

from fastapi import Request

from app.core.client_ip import client_ip
from app.core.errors import AppError
from app.schemas.errors import ErrorCode

UNKNOWN_CLIENT = "unknown"
DEFAULT_SWEEP_INTERVAL_SECONDS = 60.0


def limiter_key(ip: str | None) -> str:
    """Bucket for a caller address: IPv4 exact, IPv6 by /64, unknown callers share one bucket."""
    if not ip:
        return UNKNOWN_CLIENT
    try:
        address = ipaddress.ip_address(ip)
    except ValueError:
        return UNKNOWN_CLIENT
    if address.version == 6:
        if address.ipv4_mapped is not None:
            return f"v4:{address.ipv4_mapped}"
        return f"v6:{ipaddress.ip_network(f'{address}/64', strict=False).network_address}"
    return f"v4:{address}"


@dataclass(frozen=True)
class Decision:
    allowed: bool
    retry_after: int = 0  # seconds, only meaningful when not allowed


class SlidingWindowLimiter:
    def __init__(
        self,
        limit: int,
        window_seconds: float,
        *,
        max_keys: int = 10_000,
        sweep_interval: float = DEFAULT_SWEEP_INTERVAL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if limit < 1 or window_seconds <= 0 or max_keys < 1:
            raise ValueError("limit, window_seconds and max_keys must be positive")
        self.limit = limit
        self.window = float(window_seconds)
        self.max_keys = max_keys
        self.sweep_interval = float(sweep_interval)
        self._clock = clock
        self._hits: OrderedDict[str, deque[float]] = OrderedDict()
        self._last_sweep = clock()
        self._lock = threading.Lock()

    def __len__(self) -> int:
        return len(self._hits)

    def check(self, key: str) -> Decision:
        with self._lock:
            now = self._clock()
            if now - self._last_sweep >= self.sweep_interval:
                self._sweep(now)
            hits = self._hits.get(key)
            if hits is None:
                if len(self._hits) >= self.max_keys:
                    self._sweep(now)
                while len(self._hits) >= self.max_keys:
                    self._hits.popitem(last=False)  # least recently used
                hits = self._hits[key] = deque()
            self._drop_expired(hits, now)
            self._hits.move_to_end(key)
            if len(hits) >= self.limit:
                retry_after = max(1, math.ceil(hits[0] + self.window - now))
                return Decision(False, retry_after)
            hits.append(now)
            return Decision(True)

    def _drop_expired(self, hits: deque[float], now: float) -> None:
        horizon = now - self.window
        while hits and hits[0] <= horizon:
            hits.popleft()

    def _sweep(self, now: float) -> None:
        for key in list(self._hits):
            hits = self._hits[key]
            self._drop_expired(hits, now)
            if not hits:
                del self._hits[key]
        self._last_sweep = now


class RateLimiters:
    """The limiters of the app plus the settings that decide the caller address."""

    def __init__(
        self,
        *,
        enabled: bool,
        registration: SlidingWindowLimiter,
        track: SlidingWindowLimiter,
        trust_proxy_headers: bool = False,
        trusted_proxy_count: int = 1,
    ) -> None:
        self.enabled = enabled
        self.registration = registration
        self.track = track
        self.trust_proxy_headers = trust_proxy_headers
        self.trusted_proxy_count = trusted_proxy_count

    def enforce(self, which: str, request: Request) -> None:
        """Raise 429 (with Retry-After) when the caller is over the limit; do nothing when disabled."""
        if not self.enabled:
            return
        limiter = {"registration": self.registration, "track": self.track}[which]
        ip = client_ip(
            request,
            trust_proxy_headers=self.trust_proxy_headers,
            trusted_proxy_count=self.trusted_proxy_count,
        )
        decision = limiter.check(limiter_key(ip))
        if not decision.allowed:
            raise AppError(
                ErrorCode.RATE_LIMITED,
                "Too many requests. Try again later.",
                headers={"Retry-After": str(decision.retry_after)},
            )


def build_rate_limiters(settings, clock: Callable[[], float] = time.monotonic) -> RateLimiters:
    return RateLimiters(
        enabled=settings.RATE_LIMIT_ENABLED,
        registration=SlidingWindowLimiter(
            settings.RATE_LIMIT_REGISTRATION_MAX,
            settings.RATE_LIMIT_REGISTRATION_WINDOW_SECONDS,
            max_keys=settings.RATE_LIMIT_MAX_KEYS,
            clock=clock,
        ),
        track=SlidingWindowLimiter(
            settings.RATE_LIMIT_TRACK_MAX,
            settings.RATE_LIMIT_TRACK_WINDOW_SECONDS,
            max_keys=settings.RATE_LIMIT_MAX_KEYS,
            clock=clock,
        ),
        trust_proxy_headers=settings.TRUST_PROXY_HEADERS,
        trusted_proxy_count=settings.TRUSTED_PROXY_COUNT,
    )


def rate_limited(which: str):
    """Route dependency. Runs before the body is validated, so invalid bodies count too."""

    async def dependency(request: Request) -> None:
        limiters = getattr(request.app.state, "rate_limiters", None)
        if limiters is None:  # a deployment bug: fail loudly, never silently unlimited
            raise RuntimeError("app.state.rate_limiters is not configured")
        limiters.enforce(which, request)

    return dependency
