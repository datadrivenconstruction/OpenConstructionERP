# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Persisting which modules are on.

The guard here reads as one rule and does two things. Core modules cannot be
turned off, which is the rule everybody knows about; and until a module is
installed at runtime nothing ever asks to turn a core module back on, so the
second half went unnoticed.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.module_state import get_module_state, load_module_states, set_module_enabled

CORE = {"oe_users", "oe_projects"}


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    """A state file of this test's own, never the instance's."""
    return tmp_path / "instance"


class TestTurningACoreModuleOff:
    def test_it_is_refused(self, data_dir: Path) -> None:
        with pytest.raises(ValueError, match="core module"):
            set_module_enabled("oe_users", False, core_modules=CORE, data_dir=data_dir)

    def test_nothing_is_written(self, data_dir: Path) -> None:
        with pytest.raises(ValueError):
            set_module_enabled("oe_users", False, core_modules=CORE, data_dir=data_dir)
        assert load_module_states(data_dir) == {}


class TestTurningACoreModuleOn:
    """The direction that has to work.

    Enabling a module loads the ones it depends on first, and a generated
    module depends on the platform's own. Refusing here failed the whole
    install with a message about disabling something nobody asked to disable.
    """

    def test_it_is_allowed(self, data_dir: Path) -> None:
        state = set_module_enabled("oe_users", True, core_modules=CORE, data_dir=data_dir)
        assert state.enabled is True
        assert state.disabled_at is None

    def test_it_is_persisted(self, data_dir: Path) -> None:
        set_module_enabled("oe_users", True, core_modules=CORE, data_dir=data_dir)
        assert get_module_state("oe_users", data_dir).enabled is True

    def test_a_core_module_that_was_off_comes_back_on(self, data_dir: Path) -> None:
        """A state file written before a module became core, or edited by hand."""
        set_module_enabled("oe_users", False, core_modules=set(), data_dir=data_dir)
        assert get_module_state("oe_users", data_dir).enabled is False

        set_module_enabled("oe_users", True, core_modules=CORE, data_dir=data_dir)

        recovered = get_module_state("oe_users", data_dir)
        assert recovered.enabled is True
        assert recovered.disabled_at is None


class TestAnOrdinaryModule:
    def test_it_goes_off_and_on_again(self, data_dir: Path) -> None:
        set_module_enabled("oe_site_diary", False, core_modules=CORE, data_dir=data_dir)
        off = get_module_state("oe_site_diary", data_dir)
        assert off.enabled is False
        assert off.disabled_at, "nothing records when it was turned off"

        set_module_enabled("oe_site_diary", True, core_modules=CORE, data_dir=data_dir)
        assert get_module_state("oe_site_diary", data_dir).enabled is True

    def test_an_unknown_module_defaults_to_on(self, data_dir: Path) -> None:
        assert get_module_state("oe_never_seen", data_dir).enabled is True
