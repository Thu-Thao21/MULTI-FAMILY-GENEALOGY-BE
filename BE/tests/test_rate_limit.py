"""The in-memory sliding-window limiter (Mốc E, step E3), with a fake clock. No sleeping."""

from __future__ import annotations

import sys
import threading

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.core.errors import register_exception_handlers
from app.core.rate_limit import (
    RateLimiters,
    SlidingWindowLimiter,
    limiter_key,
    rate_limited,
)
from app.core.request_id import RequestIdMiddleware
from tests.guest_harness import FakeClock


def limiter(limit=3, window=60, *, clock=None, **kw):
    clock = clock or FakeClock(0.0)
    return SlidingWindowLimiter(limit, window, clock=clock, **kw), clock


# ------------------------------------------------------------------ the window


def test_calls_up_to_the_limit_pass_and_the_next_one_is_refused():
    lim, _ = limiter(3, 60)
    assert [lim.check("k").allowed for _ in range(3)] == [True, True, True]
    refused = lim.check("k")
    assert refused.allowed is False and refused.retry_after == 60


def test_retry_after_is_the_time_until_the_oldest_call_leaves_the_window():
    lim, clock = limiter(2, 60)
    assert lim.check("k").allowed          # t = 0
    clock.advance(10)
    assert lim.check("k").allowed          # t = 10
    clock.advance(10)                      # t = 20
    assert lim.check("k").retry_after == 40  # the call of t = 0 leaves at t = 60
    clock.advance(39)                      # t = 59
    assert lim.check("k").retry_after == 1
    clock.advance(1)                       # t = 60: the first call just left the window
    assert lim.check("k").allowed


def test_retry_after_is_rounded_up_and_never_zero():
    lim, clock = limiter(1, 60)
    lim.check("k")
    clock.advance(59.2)                       # 0.8 s left: rounded up to 1, never 0
    assert lim.check("k").retry_after == 1
    clock.advance(0.7)                        # 0.1 s left
    assert lim.check("k").retry_after == 1


@pytest.mark.parametrize("elapsed, expected", [(58.5, 2), (49.8, 11), (30.0, 30), (0.0, 60), (45.01, 15)])
def test_retry_after_is_rounded_up_not_down(elapsed, expected):
    lim, clock = limiter(1, 60)
    lim.check("k")
    clock.advance(elapsed)
    assert lim.check("k").retry_after == expected  # 60 - elapsed, rounded UP to whole seconds


def test_a_call_exactly_one_window_old_no_longer_counts():
    lim, clock = limiter(1, 60)
    lim.check("k")
    clock.advance(59.999)
    assert lim.check("k").allowed is False
    clock.advance(0.001)
    assert lim.check("k").allowed is True


def test_a_refused_call_is_not_recorded_so_hammering_does_not_extend_the_wait():
    lim, clock = limiter(1, 60)
    lim.check("k")                          # t = 0
    for _ in range(50):
        clock.advance(1)
        assert lim.check("k").allowed is False
    clock.advance(10)                       # t = 60
    assert lim.check("k").allowed is True


def test_the_window_slides_it_is_not_a_fixed_bucket():
    lim, clock = limiter(2, 60)
    lim.check("k")                          # t = 0
    clock.advance(59)
    lim.check("k")                          # t = 59
    clock.advance(2)                        # t = 61: only the call of t = 59 is left
    assert lim.check("k").allowed is True
    assert lim.check("k").allowed is False


def test_keys_do_not_share_a_counter():
    lim, _ = limiter(1, 60)
    assert lim.check("a").allowed and lim.check("b").allowed
    assert not lim.check("a").allowed and not lim.check("b").allowed


@pytest.mark.parametrize("limit, window, keys", [(0, 60, 10), (3, 0, 10), (3, -1, 10), (3, 60, 0)])
def test_nonsense_settings_are_refused(limit, window, keys):
    with pytest.raises(ValueError):
        SlidingWindowLimiter(limit, window, max_keys=keys)


# ------------------------------------------------------------------ keys


def test_ipv4_is_keyed_exactly_and_unknown_callers_share_one_bucket():
    assert limiter_key("203.0.113.7") == "v4:203.0.113.7"
    assert limiter_key("203.0.113.8") != limiter_key("203.0.113.7")
    assert limiter_key(None) == limiter_key("") == limiter_key("not-an-ip") == "unknown"


def test_ipv6_is_grouped_by_its_slash_64():
    same_network = [
        "2001:db8:abcd:12::1", "2001:db8:abcd:12::2", "2001:db8:abcd:12:ffff:ffff:ffff:ffff",
    ]
    assert len({limiter_key(a) for a in same_network}) == 1
    assert limiter_key("2001:db8:abcd:13::1") != limiter_key(same_network[0])
    assert limiter_key("2001:db8:abcd:12::1").startswith("v6:")


def test_an_ipv4_mapped_ipv6_address_counts_as_the_ipv4_address():
    assert limiter_key("::ffff:203.0.113.7") == limiter_key("203.0.113.7")


def test_a_client_rotating_ipv6_addresses_in_one_network_cannot_escape_the_limit():
    lim, _ = limiter(2, 60)
    results = [lim.check(limiter_key(f"2001:db8:1:1::{i:x}")).allowed for i in range(1, 6)]
    assert results == [True, True, False, False, False]


# ------------------------------------------------------------------ memory


def test_idle_keys_are_swept_so_the_table_does_not_grow_without_bound():
    lim, clock = limiter(5, 10, sweep_interval=30)
    for i in range(500):
        lim.check(f"v4:10.0.{i // 250}.{i % 250}")
    assert len(lim) == 500
    clock.advance(31)                        # past the window and past the sweep interval
    lim.check("v4:192.0.2.1")                # any call triggers the sweep
    assert len(lim) == 1


def test_a_touched_key_drops_its_expired_calls_immediately():
    lim, clock = limiter(2, 10, sweep_interval=10_000)
    lim.check("k")
    lim.check("k")
    clock.advance(11)
    assert lim.check("k").allowed          # the old calls no longer count
    assert len(lim._hits["k"]) == 1        # and they are gone from memory


def test_the_table_never_holds_more_than_max_keys():
    lim, _ = limiter(5, 3600, max_keys=100, sweep_interval=10_000)
    for i in range(1000):
        lim.check(f"v4:198.51.{i // 250}.{i % 250}")
        assert len(lim) <= 100
    assert len(lim) == 100


def test_when_full_the_least_recently_used_key_is_evicted_and_a_busy_key_survives():
    lim, _ = limiter(2, 3600, max_keys=3, sweep_interval=10_000)
    lim.check("busy")
    lim.check("b")
    lim.check("c")
    lim.check("busy")           # busy was used again: b is now the least recently used
    lim.check("d")              # the table is full: b goes
    assert set(lim._hits) == {"busy", "c", "d"}
    assert lim.check("busy").allowed is False  # busy kept its count (2 calls)


def test_when_full_expired_keys_are_swept_before_any_live_key_is_evicted():
    lim, clock = limiter(5, 10, max_keys=100, sweep_interval=10_000)
    for i in range(100):
        lim.check(f"k{i}")                    # t = 0
    clock.advance(8)
    lim.check("k0")                           # k0 has a call at t = 8: still live at t = 11
    clock.advance(3)                          # t = 11: k1..k99 have expired
    lim.check("new")                          # full: sweep frees 99 keys, nobody live is evicted
    assert set(lim._hits) == {"k0", "new"}


def test_the_periodic_sweep_runs_by_itself():
    lim, clock = limiter(5, 10, sweep_interval=30)
    lim.check("old")
    clock.advance(29)
    lim.check("other")
    assert "old" in lim._hits               # not yet: only the lazy purge of touched keys
    clock.advance(1)
    lim.check("other")
    assert "old" not in lim._hits


# ------------------------------------------------------------------ threads


class SpyLock:
    """A lock that records how often it was entered."""

    def __init__(self) -> None:
        self.entered = 0

    def __enter__(self):
        self.entered += 1
        return self

    def __exit__(self, *exc):
        return False


def test_every_check_runs_under_the_limiters_own_lock():
    """The stress test below can miss a race on a fast machine; this proves the lock is taken."""
    lim, _ = limiter(3, 60)
    spy = SpyLock()
    lim._lock = spy
    for _ in range(4):
        lim.check("k")
    assert spy.entered == 4


def test_many_threads_on_one_key_never_get_more_than_the_limit():
    lim = SlidingWindowLimiter(100, 3600)  # real clock: the window does not move during the test
    allowed = []

    def worker():
        allowed.extend(lim.check("shared").allowed for _ in range(250))

    previous = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)  # make the interpreter switch threads as often as it can
    try:
        threads = [threading.Thread(target=worker) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    finally:
        sys.setswitchinterval(previous)
    assert len(allowed) == 2000 and sum(allowed) == 100


# ------------------------------------------------------------------ RateLimiters and the dependency


def make_limiters(**kw) -> RateLimiters:
    clock = FakeClock(0.0)
    return RateLimiters(
        enabled=kw.pop("enabled", True),
        registration=SlidingWindowLimiter(2, 60, clock=clock),
        track=SlidingWindowLimiter(1, 60, clock=clock),
        **kw,
    )


def test_a_disabled_limiter_never_refuses_and_never_stores_anything():
    limiters = make_limiters(enabled=False)
    app = FastAPI()
    app.add_middleware(RequestIdMiddleware)
    register_exception_handlers(app)
    app.state.rate_limiters = limiters

    @app.get("/x", dependencies=[Depends(rate_limited("registration"))])
    async def x():
        return {"ok": True}

    client = TestClient(app, client=("203.0.113.1", 1))
    assert all(client.get("/x").status_code == 200 for _ in range(10))
    assert len(limiters.registration) == 0


def test_the_dependency_fails_loudly_when_the_limiters_are_missing():
    app = FastAPI()
    app.add_middleware(RequestIdMiddleware)
    register_exception_handlers(app)

    @app.get("/x", dependencies=[Depends(rate_limited("registration"))])
    async def x():
        return {"ok": True}

    r = TestClient(app, client=("203.0.113.1", 1), raise_server_exceptions=False).get("/x")
    assert r.status_code == 500  # never silently unlimited


def test_the_429_carries_the_envelope_the_retry_after_header_and_the_request_id():
    limiters = make_limiters()
    app = FastAPI()
    app.add_middleware(RequestIdMiddleware)
    register_exception_handlers(app)
    app.state.rate_limiters = limiters

    @app.get("/x", dependencies=[Depends(rate_limited("registration"))])
    async def x():
        return {"ok": True}

    client = TestClient(app, client=("203.0.113.1", 1))
    assert [client.get("/x").status_code for _ in range(2)] == [200, 200]
    r = client.get("/x", headers={"X-Request-ID": "caller-req-123456"})
    assert r.status_code == 429
    assert r.headers["retry-after"] == "60"
    assert r.json() == {"error": {
        "code": "RATE_LIMITED", "message": "Too many requests. Try again later.",
        "request_id": "caller-req-123456"}}
