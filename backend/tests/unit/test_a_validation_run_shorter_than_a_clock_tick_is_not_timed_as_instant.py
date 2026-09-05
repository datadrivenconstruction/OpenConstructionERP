"""A validation run is timed with a clock fine enough to see it.

``time.monotonic()`` on Windows is backed by the interrupt timer and advances
in steps of about 15.625 ms. A validation pass over a few hundred rules is
ordinary arithmetic over data already in memory and routinely finishes inside
one of those steps, so the two readings that bracket it are the same number
and the difference is exactly zero. The report then stores ``duration_ms: 0``
and the page prints "Duration: 0.0ms", which reads as a measurement rather
than as the failure to measure that it is.

The signature that ruled out "the run really was instant" was a distribution,
not a single reading: across stored reports the distinct durations were 0, 15,
16, 31, 32, 47, 93, 110, 140, 141 and 1578, every one a whole number of ticks,
with nothing in between. ``time.perf_counter()`` is the instrument for an
elapsed interval and resolves to well under a microsecond on the same machine.

Neither test below can be satisfied by a run that happens to be slow. The
first freezes the coarse clock outright, so the old code reports zero no
matter how long the work takes and no matter which platform runs the test -
the defect is reproducible on a Linux runner that has a nanosecond
``monotonic`` of its own and could never provoke it naturally. The second
reads the source rather than the outcome, so it stays honest about the
mechanism even on a machine where both clocks are fine.
"""

import ast
import time
from pathlib import Path

import pytest

from app.core.validation.engine import (
    RuleCategory,
    RuleRegistry,
    RuleResult,
    Severity,
    ValidationContext,
    ValidationEngine,
    ValidationRule,
)


class _TrivialRule(ValidationRule):
    """A rule with no work in it, so the run is as short as a run can be."""

    rule_id = "test.trivial"
    name = "Trivial"
    standard = "test"
    severity = Severity.INFO
    category = RuleCategory.QUALITY

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        return [
            RuleResult(
                rule_id=self.rule_id,
                rule_name=self.name,
                severity=self.severity,
                category=self.category,
                passed=True,
                message="OK",
            )
        ]


@pytest.mark.asyncio
async def test_a_run_is_still_timed_when_the_coarse_clock_stands_still(monkeypatch):
    """A frozen ``monotonic`` must not be able to make a run look instant.

    Freezing rather than coarsening is deliberate. A fake that merely rounds
    down to 15.625 ms steps only produces a zero when the run happens to land
    inside one step, which is a bet on how fast this machine is; a constant
    makes the old subtraction yield exactly 0.0 on every machine and every
    run length, so a green here can only mean the duration came from a
    different clock.
    """
    monkeypatch.setattr(time, "monotonic", lambda: 1_000.0)

    registry = RuleRegistry()
    registry.register(_TrivialRule())
    report = await ValidationEngine(registry).validate(data={}, rule_sets=["test"])

    assert report.duration_ms is not None
    assert report.duration_ms > 0.0, (
        "the run was timed with time.monotonic(), which stands still for about "
        "15.6 ms at a time on Windows; a report that stores 0 ms has not been "
        "timed, it has failed to be timed"
    )


def test_the_clock_that_times_a_validation_run_resolves_below_a_millisecond():
    """The instrument itself, independent of any particular run."""
    assert time.get_clock_info("perf_counter").resolution < 1e-3


def _duration_subtractions_using_monotonic(source: str) -> list[int]:
    """Line numbers where an elapsed interval is differenced from ``monotonic``."""

    def is_monotonic_call(node: ast.AST) -> bool:
        if not isinstance(node, ast.Call):
            return False
        func = node.func
        if isinstance(func, ast.Attribute):
            return func.attr == "monotonic"
        return isinstance(func, ast.Name) and func.id == "monotonic"

    hits = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.BinOp) or not isinstance(node.op, ast.Sub):
            continue
        if is_monotonic_call(node.left) or is_monotonic_call(node.right):
            hits.append(node.lineno)
    return hits


def _validation_sources() -> list[Path]:
    backend = Path(__file__).resolve().parents[2]
    roots = [
        backend / "app" / "core" / "validation",
        backend / "app" / "modules" / "validation",
    ]
    files = [path for root in roots for path in root.rglob("*.py")]
    files.append(backend / "app" / "modules" / "requirements" / "bim_validator.py")
    return [path for path in files if path.is_file()]


def test_no_validation_duration_is_measured_with_the_coarse_clock():
    """Read for the subtraction, not for the word.

    A grep for ``monotonic`` would also flag the deadlines and cache expiries
    that are perfectly correct at 15 ms granularity. What is wrong is
    specifically differencing two readings of it to report how long something
    took, so that is the shape the tree is searched for.
    """
    sources = _validation_sources()
    assert sources, "no validation sources found; the test is looking in the wrong place"

    offenders = {}
    for path in sources:
        lines = _duration_subtractions_using_monotonic(path.read_text(encoding="utf-8"))
        if lines:
            offenders[path.name] = lines

    assert not offenders, (
        f"validation durations are still differenced from time.monotonic(): {offenders}. "
        "Use time.perf_counter() to measure an elapsed interval."
    )
