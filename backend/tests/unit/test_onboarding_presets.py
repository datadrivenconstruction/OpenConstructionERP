"""Unit tests for the company-profile onboarding presets.

The sidebar is gated on ``module_preferences``, which ``modules_for`` builds
from the module set a profile selects. Two behaviours matter and are easy to
regress:

- "Full Enterprise" must light up every functional module. The backend list is
  authoritative, so even if a client catalogue drifts behind the server the
  whole platform still shows.
- A narrow profile must still write an explicit False for the modules it does
  not include, otherwise the sidebar could not hide anything.
"""

from app.core.onboarding_presets import (
    _ALL_FUNCTIONAL,
    _CORE_MODULES,
    get_preset,
    is_core_module,
    modules_for,
)


def test_full_enterprise_enables_every_functional_module() -> None:
    """Full Enterprise pins to the backend's own functional list, all on."""
    preset = get_preset("full_enterprise")
    assert preset is not None
    # The preset itself carries the complete functional set.
    assert set(preset.enabled_modules) == set(_ALL_FUNCTIONAL)

    prefs = modules_for(preset.enabled_modules)
    # Every functional module is explicitly enabled - nothing is hidden.
    for key in _ALL_FUNCTIONAL:
        assert prefs[key] is True, f"{key} should be enabled under Full Enterprise"
    # Sidebar routes that an external report flagged as vanishing are present.
    for key in ("bim_hub", "finance", "crm"):
        assert prefs[key] is True


def test_core_modules_are_always_on() -> None:
    """No profile can hide a core module, even an empty selection."""
    prefs = modules_for([])
    for key in _CORE_MODULES:
        assert prefs[key] is True
        assert is_core_module(key) is True


def test_narrow_profile_disables_unselected_modules() -> None:
    """A profile that omits a functional module writes an explicit False."""
    prefs = modules_for(["boq", "costs", "takeoff"])
    assert prefs["boq"] is True
    # A functional module left out of the selection is turned off so the
    # sidebar can hide it.
    assert prefs["finance"] is False
    assert prefs["crm"] is False


def test_every_known_module_gets_an_explicit_flag() -> None:
    """``modules_for`` returns a complete map, never a partial one."""
    prefs = modules_for([])
    expected = set(_CORE_MODULES) | set(_ALL_FUNCTIONAL)
    assert expected.issubset(set(prefs))
    assert all(isinstance(v, bool) for v in prefs.values())
