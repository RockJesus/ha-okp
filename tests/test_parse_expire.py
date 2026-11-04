"""_parse_expire: the CoolKit expiry field zoo.

Deployments name the field differently and some report milliseconds. Reading
it wrong meant refreshing *after* the token died, and the renewal was rejected
with "cannot found access token info" - a whole class of "dead session" bugs.
"""
from __future__ import annotations

from custom_components.okp_cloud.api import _parse_expire

NOW = 1_793_900_000


def test_seconds_field_names():
    for key in ("at_expire_at", "atExpiredTime", "at_expired_at", "expireAt"):
        assert _parse_expire({key: NOW + 3600}) == NOW + 3600


def test_milliseconds_are_converted():
    assert _parse_expire({"atExpiredTime": (NOW + 3600) * 1000}) == NOW + 3600


def test_first_present_field_wins():
    data = {"atExpiredTime": NOW + 60, "expireAt": NOW + 9999}
    assert _parse_expire(data) == NOW + 60


def test_garbage_values_are_skipped():
    data = {"atExpiredTime": "not-a-number", "expireAt": NOW + 60}
    assert _parse_expire(data) == NOW + 60


def test_nothing_usable_returns_zero():
    assert _parse_expire({}) == 0
    assert _parse_expire({"atExpiredTime": None}) == 0
