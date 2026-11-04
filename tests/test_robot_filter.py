"""_looks_like_robot: the shared-account device filter.

Shared devices only reach the integration through CoolKit's thing list, which
mixes every device type on the account (plugs, cameras, sensors). Adopting all
of them would create junk entities for the user's whole smart home; dropping
the robot would recreate the "shared account shows nothing" bug. The filter
has to walk exactly that line.
"""
from __future__ import annotations

from custom_components.okp_cloud.config_flow import _looks_like_robot


def test_robot_dp_is_recognised():
    for key in ("workState", "sweep", "cleaningArea", "startUpload", "uiActive"):
        assert _looks_like_robot({key: 1}) is True


def test_non_robot_dp_is_rejected():
    # dp keys a plug / sensor / camera would carry, none of the robot hints.
    assert _looks_like_robot({"power": 1, "voltage": 220}) is False
    assert _looks_like_robot({"brightness": 80}) is False


def test_empty_params_counts_as_robot():
    """An offline shared robot arrives with no dp payload - keep it.

    Better to show a device that turns out to be offline than to silently
    drop the robot the user just shared (that was the original bug).
    """
    assert _looks_like_robot({}) is True
    assert _looks_like_robot(None) is True


def test_non_dict_params_counts_as_robot():
    """Defensive: the cloud must not be able to crash setup with junk."""
    assert _looks_like_robot("junk") is True
    assert _looks_like_robot(42) is True
