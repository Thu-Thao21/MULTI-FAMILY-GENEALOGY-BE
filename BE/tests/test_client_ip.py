"""Which address is counted (Mốc E, step E3): the peer by default, X-Forwarded-For only when
TRUST_PROXY_HEADERS is on, and one warning per process when the header arrives while it is off."""

from __future__ import annotations

import logging

import pytest
from starlette.requests import Request

from app.core import client_ip as client_ip_module
from app.core.client_ip import client_ip, parse_ip
from tests.guest_harness import GuestWorld

PEER = "198.51.100.1"


def make_request(peer: str | None = PEER, *forwarded: str) -> Request:
    headers = [(b"x-forwarded-for", value.encode()) for value in forwarded]
    scope = {"type": "http", "method": "GET", "path": "/", "headers": headers, "query_string": b""}
    if peer is not None:
        scope["client"] = (peer, 4242)
    return Request(scope)


@pytest.fixture(autouse=True)
def fresh_warning_state():
    client_ip_module._reset_warning_state()
    yield
    client_ip_module._reset_warning_state()


# ------------------------------------------------------------------ the default: the peer


def test_by_default_only_the_peer_address_counts_and_the_header_is_ignored():
    assert client_ip(make_request(PEER, "203.0.113.50")) == PEER
    assert client_ip(make_request(PEER, "10.0.0.1, 203.0.113.50")) == PEER
    assert client_ip(make_request(PEER)) == PEER


def test_a_caller_cannot_choose_the_address_that_is_counted_by_default():
    for forged in ("1.2.3.4", "127.0.0.1", "::1", "garbage", ""):
        assert client_ip(make_request(PEER, forged), trust_proxy_headers=False) == PEER


def test_a_peer_that_is_not_an_ip_address_gives_none():
    assert client_ip(make_request("testclient")) is None
    assert client_ip(make_request(None)) is None


# ------------------------------------------------------------------ trusting the proxy


def trusted(request: Request, count: int = 1):
    return client_ip(request, trust_proxy_headers=True, trusted_proxy_count=count)


def test_with_one_trusted_proxy_the_last_entry_is_the_client():
    assert trusted(make_request(PEER, "203.0.113.50")) == "203.0.113.50"
    assert trusted(make_request(PEER, "6.6.6.6, 203.0.113.50")) == "203.0.113.50"


def test_entries_on_the_left_are_what_the_caller_wrote_and_are_never_used():
    forged = "1.2.3.4, 5.6.7.8, 203.0.113.50"
    assert trusted(make_request(PEER, forged)) == "203.0.113.50"


def test_with_two_trusted_proxies_the_second_entry_from_the_right_is_the_client():
    assert trusted(make_request(PEER, "6.6.6.6, 203.0.113.50, 192.0.2.10"), 2) == "203.0.113.50"
    assert trusted(make_request(PEER, "203.0.113.50, 192.0.2.10"), 2) == "203.0.113.50"


def test_a_header_with_fewer_entries_than_proxies_falls_back_to_the_peer():
    assert trusted(make_request(PEER, "203.0.113.50"), 2) == PEER


@pytest.mark.parametrize("value", ["", "   ", ",", "garbage", "203.0.113.50, not-an-ip", "999.1.1.1"])
def test_a_missing_empty_or_invalid_entry_falls_back_to_the_peer_never_to_a_made_up_value(value):
    assert trusted(make_request(PEER, value)) == PEER


def test_no_header_falls_back_to_the_peer_when_trusting():
    assert trusted(make_request(PEER)) == PEER


def test_several_header_lines_are_read_as_one_list():
    request = make_request(PEER, "6.6.6.6", "203.0.113.50")
    assert trusted(request) == "203.0.113.50"
    assert trusted(request, 2) == "6.6.6.6"


def test_ports_and_brackets_are_understood():
    assert trusted(make_request(PEER, "203.0.113.50:51234")) == "203.0.113.50"
    assert trusted(make_request(PEER, "[2001:db8::1]:443")) == "2001:db8::1"
    assert trusted(make_request(PEER, "2001:db8::1")) == "2001:db8::1"


def test_a_zero_or_negative_proxy_count_is_not_trusted():
    assert client_ip(make_request(PEER, "203.0.113.50"), trust_proxy_headers=True, trusted_proxy_count=0) == PEER


@pytest.mark.parametrize(
    "text, expected",
    [("203.0.113.7", "203.0.113.7"), (" 203.0.113.7 ", "203.0.113.7"), ("203.0.113.7:80", "203.0.113.7"),
     ("[::1]:80", "::1"), ("2001:DB8::1", "2001:db8::1"), ("", None), (None, None), ("x", None),
     ("1.2.3", None), ("1.2.3.4.5", None)],
)
def test_parse_ip(text, expected):
    assert parse_ip(text) == expected


# ------------------------------------------------------------------ the warning (once per process)


def forwarded_warnings(caplog) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.name == "mfg.client_ip" and r.levelno == logging.WARNING]


def test_the_warning_is_logged_once_per_process_when_the_header_arrives_while_trust_is_off(caplog):
    caplog.set_level(logging.DEBUG)
    for _ in range(5):
        client_ip(make_request(PEER, "203.0.113.50"))
    [message] = forwarded_warnings(caplog)
    assert "X-Forwarded-For" in message and "TRUST_PROXY_HEADERS" in message
    assert "once per process" in message


def test_the_warning_never_contains_an_address(caplog):
    caplog.set_level(logging.DEBUG)
    client_ip(make_request(PEER, "203.0.113.99, 192.0.2.77"))
    [message] = forwarded_warnings(caplog)
    for address in ("203.0.113.99", "192.0.2.77", PEER, "203.0.113", "192.0.2"):
        assert address not in message
    assert all(address not in caplog.text for address in ("203.0.113.99", "192.0.2.77", PEER))


def test_there_is_no_warning_without_the_header(caplog):
    caplog.set_level(logging.DEBUG)
    for _ in range(3):
        client_ip(make_request(PEER))
    assert forwarded_warnings(caplog) == []


def test_there_is_no_warning_when_the_proxy_headers_are_trusted(caplog):
    caplog.set_level(logging.DEBUG)
    for _ in range(3):
        trusted(make_request(PEER, "203.0.113.50"))
    assert forwarded_warnings(caplog) == []


def test_a_header_that_is_present_but_empty_still_counts_as_received(caplog):
    caplog.set_level(logging.DEBUG)
    client_ip(make_request(PEER, ""))
    assert len(forwarded_warnings(caplog)) == 1


def test_a_second_process_would_warn_again_once(caplog):
    """The state is per process: resetting it (what a new process starts with) allows one more."""
    caplog.set_level(logging.DEBUG)
    client_ip(make_request(PEER, "203.0.113.50"))
    client_ip_module._reset_warning_state()
    client_ip(make_request(PEER, "203.0.113.50"))
    assert len(forwarded_warnings(caplog)) == 2


# ------------------------------------------------------------------ through the endpoints


def test_a_forged_forwarded_for_does_not_escape_the_registration_limit_by_default():
    w = GuestWorld()
    for i in range(5):
        assert w.register(headers={"X-Forwarded-For": f"203.0.113.{i + 10}"}).status_code == 201
    assert w.register(headers={"X-Forwarded-For": "198.18.0.200"}).status_code == 429


def test_when_trusted_each_client_behind_the_proxy_has_its_own_counter():
    w = GuestWorld(trust_proxy_headers=True, trusted_proxy_count=1)
    for _ in range(5):
        assert w.register(headers={"X-Forwarded-For": "203.0.113.10"}).status_code == 201
    assert w.register(headers={"X-Forwarded-For": "203.0.113.10"}).status_code == 429
    assert w.register(headers={"X-Forwarded-For": "203.0.113.11"}).status_code == 201


def test_when_trusted_a_forged_left_entry_does_not_escape_the_limit():
    w = GuestWorld(trust_proxy_headers=True, trusted_proxy_count=1)
    for i in range(5):
        r = w.register(headers={"X-Forwarded-For": f"6.6.6.{i}, 203.0.113.10"})
        assert r.status_code == 201
    assert w.register(headers={"X-Forwarded-For": "7.7.7.7, 203.0.113.10"}).status_code == 429
