"""An RVT the installed converter rejects is an error, not a missing converter."""

from __future__ import annotations

import pytest

from app.modules.bim_hub.router import rvt_failure_status


def test_an_outdated_converter_asks_for_a_reinstall() -> None:
    assert rvt_failure_status("converter_outdated") == "needs_converter"


@pytest.mark.parametrize("cause", ["unknown", "timeout", "empty_output", ""])
def test_a_file_the_converter_rejected_is_an_error(cause: str) -> None:
    assert rvt_failure_status(cause) == "error"
