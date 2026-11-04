"""entity_scope: the v1.6.2 → v1.6.5 regression story.

v1.6.2 shipped a version of entity_scope() that read ``entry.hass`` — an
attribute ConfigEntry does not have — so it returned "" for *every* entry and
the fix was dead on arrival (two accounts produced identical unique_ids, HA
silently dropped the second set, the shared account showed no devices).
v1.6.5 takes hass explicitly. These tests exist so that specific failure mode
can never come back silently.
"""
from __future__ import annotations

from custom_components.okp_cloud.const import entity_scope

MAIN_ID = "01M6GJ1WVDWPZSK1HGT762MSHS"
SHARED_ID = "01M6GJWJPHQQSX0A19X1D1PZV0"


def test_first_entry_gets_empty_scope(hass_with_entries):
    """The oldest entry keeps the historical ids (no suffix)."""
    hass, entries = hass_with_entries(
        [(MAIN_ID, 1793704653), (SHARED_ID, 1793705527)]
    )
    assert entity_scope(hass, entries[0]) == ""


def test_second_entry_gets_id_suffix(hass_with_entries):
    """A later entry is suffixed with the tail of its own entry_id."""
    hass, entries = hass_with_entries(
        [(MAIN_ID, 1793704653), (SHARED_ID, 1793705527)]
    )
    assert entity_scope(hass, entries[1]) == f"_{SHARED_ID[-6:]}"


def test_scope_is_stable_across_calls(hass_with_entries):
    """Same inputs -> same suffix; automations rely on it not drifting."""
    hass, entries = hass_with_entries(
        [(MAIN_ID, 1793704653), (SHARED_ID, 1793705527)]
    )
    assert entity_scope(hass, entries[1]) == entity_scope(hass, entries[1])


def test_ordering_is_by_creation_time_not_list_order(hass_with_entries):
    """async_entries() order is arbitrary; created_at decides who is 'first'."""
    hass, entries = hass_with_entries(
        [(SHARED_ID, 1793705527), (MAIN_ID, 1793704653)]
    )
    assert entity_scope(hass, entries[0]) == f"_{SHARED_ID[-6:]}"
    assert entity_scope(hass, entries[1]) == ""


def test_works_without_created_at(hass_with_entries):
    """Pre-2022.7 entries carry no created_at; ordering must not raise.

    Undated entries sort as the oldest (0.0), so they win the empty scope -
    the same treatment as any other first entry. The important part is that
    the mixed float/datetime sort does not raise.
    """
    hass, entries = hass_with_entries(
        [(SHARED_ID, None), (MAIN_ID, 1793704653)]
    )
    # No TypeError, and the two entries get *different* scopes.
    scopes = {entity_scope(hass, e) for e in entries}
    assert len(scopes) == 2
    assert entity_scope(hass, entries[0]) == ""


def test_regression_entry_without_hass_attribute(hass_with_entries, config_entry_factory):
    """THE v1.6.2 bug: entity_scope must not depend on entry.hass.

    ConfigEntry has no hass attribute in Home Assistant — hass is only ever
    passed as a method argument. The v1.6.2 implementation did
    getattr(entry, "hass", None) and silently returned "" for every entry.
    """
    hass, entries = hass_with_entries(
        [(MAIN_ID, 1793704653), (SHARED_ID, 1793705527)]
    )
    for entry in entries:
        assert not hasattr(entry, "hass")
    assert entity_scope(hass, entries[1]) != ""


def test_none_arguments_return_empty(hass_with_entries):
    """Defensive contract: None hass or None entry yields no suffix."""
    hass, _ = hass_with_entries([(MAIN_ID, 1793704653)])
    assert entity_scope(None, None) == ""
    assert entity_scope(hass, None) == ""
