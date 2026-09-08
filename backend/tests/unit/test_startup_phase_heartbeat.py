"""No phase of startup may be silent for longer than the heartbeat interval.

The desktop launcher gives up on a sidecar that has written nothing for four
minutes, and until the port is bound the only evidence that a boot is working is
what the process writes. Several startup phases are long and internally silent:
the route-table build takes 32.1s quiet and 58.6s under load and writes one line
when it finishes, and the module load, the migrations and first-run seeding have
the same shape.

None of those is near four minutes, so these tests do not pin an active failure.
They pin the general form of one that did happen in the phase before logging is
configured, which is that a phase nobody has measured lately is one nobody knows
the silence of. Two properties carry that:

* something is written while a phase is still running, not only when it ends;
* a phase that has run past its budget stops being vouched for, so a boot that
  is genuinely wedged can still be given up on.

Nothing here asserts a wall-clock duration. The blocking phase is held open on
an event and the assertion is that reports appeared before it was released.
"""

from __future__ import annotations

import threading
import time

import pytest

#: Longest any test here waits on a condition before calling it a failure.
_PATIENCE = 10.0


def _capture(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Record what the heartbeat logs instead of emitting it."""
    from app import main

    lines: list[str] = []
    monkeypatch.setattr(
        main.logger,
        "info",
        lambda msg, *args: lines.append(msg % args if args else msg),
    )
    return lines


def _wait_until(predicate, patience: float = _PATIENCE) -> bool:
    """Poll ``predicate`` until it holds or ``patience`` runs out."""
    limit = time.monotonic() + patience
    while time.monotonic() < limit:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def test_a_phase_that_blocks_is_reported_while_it_blocks(monkeypatch: pytest.MonkeyPatch) -> None:
    """The point of the whole thing: output exists before the phase finishes."""
    from app import main

    lines = _capture(monkeypatch)
    monkeypatch.setattr(main, "_BOOT_HEARTBEAT_SECONDS", 0.05)

    release = threading.Event()
    with main._heartbeat_through_startup():
        main._set_boot_phase("Routing")
        assert _wait_until(lambda: len(lines) >= 2), f"a silent phase is the defect: {lines}"
        # The mechanism, stated without a stopwatch: the reports above exist and
        # the phase has not been allowed to finish yet.
        assert not release.is_set()
        release.set()

    assert all("Routing" in line for line in lines), f"the phase must be named: {lines}"
    assert all("Still working" in line for line in lines)


def test_the_reported_phase_follows_the_section_headers(monkeypatch: pytest.MonkeyPatch) -> None:
    """A phase change renames the report and restarts its clock."""
    from app import main

    lines = _capture(monkeypatch)
    monkeypatch.setattr(main, "_BOOT_HEARTBEAT_SECONDS", 0.05)

    with main._heartbeat_through_startup():
        main._set_boot_phase("Modules")
        assert _wait_until(lambda: any("Modules" in line for line in lines))
        main._set_boot_phase("Demo data")
        assert _wait_until(lambda: any("Demo data" in line for line in lines))

    first_seed = next(i for i, line in enumerate(lines) if "Demo data" in line)
    assert all("Modules" not in line for line in lines[first_seed:]), (
        f"the heartbeat went on naming a phase that had ended: {lines}"
    )


def test_a_phase_past_its_budget_stops_being_vouched_for(monkeypatch: pytest.MonkeyPatch) -> None:
    """A wedged boot has to be allowed to look wedged, or the watchdog is dead.

    This is the property that keeps the repair from being worse than the bug it
    fixes. Reporting is what stops, not the boot.

    The budget is narrowed after the phase has been reported and widened again
    before the phase moves on, rather than being set small for the whole test.
    Held small throughout, one constant has to do two contradictory jobs: be
    wide enough that two reports fit inside it, and expire while the test is
    still watching. A runner under load that lands the first tick inside a
    0.3s budget and the next one outside it satisfies neither, and then waits
    out the full patience for a second report that can no longer come. That is
    how this failed on macOS while passing on Linux and Windows, on a machine
    difference rather than a product one. The property asserted is unchanged;
    the two demands are separated in time so that no scheduling delay can put
    them in conflict.
    """
    from app import main

    lines = _capture(monkeypatch)
    shipped_budget = main._BOOT_PHASE_BUDGET_SECONDS
    monkeypatch.setattr(main, "_BOOT_HEARTBEAT_SECONDS", 0.05)

    with main._heartbeat_through_startup():
        # The budget is still the shipped one here, so this waits on the
        # heartbeat alone and has no expiry to race.
        main._set_boot_phase("Modules")
        assert _wait_until(lambda: len(lines) >= 2), f"never reported at all: {lines}"

        # Retire the phase by declaring a budget it has already outrun, rather
        # than by setting a small one and waiting for the clock to reach it.
        monkeypatch.setattr(main, "_BOOT_PHASE_BUDGET_SECONDS", (time.monotonic() - main._boot_phase_started) / 2)
        assert time.monotonic() - main._boot_phase_started > main._BOOT_PHASE_BUDGET_SECONDS, (
            "the phase has to be over budget before silence means anything"
        )

        # Once the phase is past its budget no further report is possible, so
        # two readings taken after that point must agree however badly this
        # machine happens to be scheduling threads. The first wait lets a tick
        # that had already passed its budget check land before the reading.
        time.sleep(main._BOOT_HEARTBEAT_SECONDS * 2)
        settled = len(lines)
        time.sleep(0.3)
        assert len(lines) == settled, f"a stuck phase was still being vouched for: {lines[settled:]}"

        # A phase that does move on is reported again: the budget retires one
        # phase, not the heartbeat. The budget goes back to the shipped value
        # first, so this asserts the phase change and not the budget's width.
        monkeypatch.setattr(main, "_BOOT_PHASE_BUDGET_SECONDS", shipped_budget)
        main._set_boot_phase("Demo data")
        assert _wait_until(lambda: any("Demo data" in line for line in lines)), (
            f"the budget retired the whole heartbeat rather than one phase: {lines}"
        )


def test_the_heartbeat_stops_when_startup_finishes(monkeypatch: pytest.MonkeyPatch) -> None:
    """It reports a boot, so it must not outlive one."""
    from app import main

    lines = _capture(monkeypatch)
    monkeypatch.setattr(main, "_BOOT_HEARTBEAT_SECONDS", 0.05)

    with main._heartbeat_through_startup():
        main._set_boot_phase("Database")
        assert _wait_until(lambda: len(lines) >= 2)

    settled = len(lines)
    time.sleep(0.3)
    assert len(lines) == settled, f"the reporter outlived the startup it reports on: {lines[settled:]}"


def test_every_section_header_goes_through_the_one_that_sets_the_phase() -> None:
    """A header written inline would make the heartbeat name the phase before it.

    This is a source check because the alternative is standing up the real
    lifespan, which boots a database. It catches the regression that has already
    happened once: the route-table phase logged its own ``=== Routing ===``
    inline, so anything reading the phase from :func:`_section` would have gone
    on reporting ``Ready`` throughout the longest silent step of the boot. The
    failure mode is silent, since the heartbeat still ticks and still feeds the
    launcher while naming the wrong thing.
    """
    import inspect
    from pathlib import Path

    from app import main

    source = Path(inspect.getfile(main)).read_text(encoding="utf-8")
    headers = [line.strip() for line in source.splitlines() if 'logger.info("=== ' in line or 'f"=== ' in line]
    assert len(headers) == 1, f"a section header is being written outside _section: {headers}"

    section_src = inspect.getsource(main.create_app)
    assert "_set_boot_phase(title)" in section_src, "_section no longer tells the heartbeat which phase it is"


def test_a_startup_with_no_slow_phase_says_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    """A normal boot must not gain a progress line, or every log grows one.

    The property is the wait that comes before the first report, which is
    exactly the line a later reading of "why is the first report fifteen seconds
    late" would remove. The interval is left at its real value on purpose.
    """
    from app import main

    lines = _capture(monkeypatch)

    with main._heartbeat_through_startup():
        main._set_boot_phase("Database")

    assert lines == [], f"a boot with no slow phase in it must stay quiet: {lines}"
