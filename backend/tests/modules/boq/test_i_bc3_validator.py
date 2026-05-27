"""Epic I7 — BC3 / FIEBDC-3 rule pack tests.

Two rules:

* ``bc3.code_required`` (ERROR) — partidas missing
  ``classification.bc3_code`` (or fallback ``code``) fail.
* ``bc3.valid_code`` (WARNING) — codes that violate the FIEBDC-3
  alphanumeric pattern fail.
"""

from __future__ import annotations

import pytest

from app.core.validation.engine import Severity, ValidationContext
from app.core.validation.rules import BC3CodeRequired, BC3ValidCode


def _ctx(positions: list[dict], locale: str = "en") -> ValidationContext:
    return ValidationContext(data={"positions": positions}, metadata={"locale": locale})


class TestBC3CodeRequired:
    @pytest.mark.asyncio
    async def test_pass_when_bc3_code_present(self) -> None:
        rule = BC3CodeRequired()
        results = await rule.validate(
            _ctx([{"id": "p1", "ordinal": "01.01", "classification": {"bc3_code": "E04CM040"}}])
        )
        assert len(results) == 1
        assert results[0].passed
        assert results[0].severity == Severity.ERROR

    @pytest.mark.asyncio
    async def test_pass_when_generic_code_present(self) -> None:
        # The rule accepts ``classification.code`` as a fallback so
        # legacy imports that don't populate ``bc3_code`` don't fail.
        rule = BC3CodeRequired()
        results = await rule.validate(_ctx([{"id": "p1", "ordinal": "01.01", "classification": {"code": "01.01"}}]))
        assert results[0].passed

    @pytest.mark.asyncio
    async def test_fail_when_no_code(self) -> None:
        rule = BC3CodeRequired()
        results = await rule.validate(_ctx([{"id": "p1", "ordinal": "01.01", "classification": {}}]))
        assert not results[0].passed
        assert "01.01" in results[0].message
        assert results[0].severity == Severity.ERROR

    @pytest.mark.asyncio
    async def test_section_rows_are_skipped(self) -> None:
        rule = BC3CodeRequired()
        results = await rule.validate(
            _ctx(
                [
                    {
                        "id": "s1",
                        "ordinal": "01#",
                        "type": "section",
                        "classification": {},
                    }
                ]
            )
        )
        # Section rows shouldn't trigger the rule — chapters carry
        # their own code in `ordinal` and are not partidas.
        assert results == []


class TestBC3ValidCode:
    @pytest.mark.asyncio
    async def test_pass_alphanumeric_code(self) -> None:
        rule = BC3ValidCode()
        results = await rule.validate(
            _ctx([{"id": "p1", "ordinal": "01.01", "classification": {"bc3_code": "E04CM040"}}])
        )
        assert results[0].passed
        assert results[0].severity == Severity.WARNING

    @pytest.mark.asyncio
    async def test_pass_dotted_code(self) -> None:
        rule = BC3ValidCode()
        results = await rule.validate(
            _ctx([{"id": "p1", "ordinal": "01.01", "classification": {"bc3_code": "01.02.03"}}])
        )
        assert results[0].passed

    @pytest.mark.asyncio
    async def test_pass_chapter_code(self) -> None:
        rule = BC3ValidCode()
        results = await rule.validate(
            _ctx([{"id": "p1", "ordinal": "CAP01", "classification": {"bc3_code": "CAP01#"}}])
        )
        assert results[0].passed

    @pytest.mark.asyncio
    async def test_fail_whitespace_code(self) -> None:
        rule = BC3ValidCode()
        results = await rule.validate(_ctx([{"id": "p1", "ordinal": "01", "classification": {"bc3_code": "01 02 03"}}]))
        assert not results[0].passed
        assert "01 02 03" in results[0].message

    @pytest.mark.asyncio
    async def test_fail_leading_dot_code(self) -> None:
        rule = BC3ValidCode()
        results = await rule.validate(_ctx([{"id": "p1", "ordinal": "01", "classification": {"bc3_code": ".01.02"}}]))
        assert not results[0].passed

    @pytest.mark.asyncio
    async def test_missing_code_is_skipped(self) -> None:
        """``valid_code`` only fires when a code is *present* — the
        ``code_required`` rule handles the missing-code case."""
        rule = BC3ValidCode()
        results = await rule.validate(_ctx([{"id": "p1", "ordinal": "01", "classification": {}}]))
        assert results == []
