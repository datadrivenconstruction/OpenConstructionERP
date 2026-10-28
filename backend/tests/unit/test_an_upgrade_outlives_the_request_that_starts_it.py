# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠An upgrade takes longer than any browser waits, so it cannot be a request.

Downloading a release, resolving its dependencies and installing them takes as
long as it takes. The client gave up at 45 seconds and told the user the
upgrade had failed, over an upgrade that was still running and would go on to
succeed (issue #430). The work also ran inline in the event loop of a single
worker, so for its whole duration the server answered nothing at all.

These tests hold the job machinery to the three things that makes true: one
upgrade at a time, a failure that can be read rather than guessed at, and a
runner that never raises, because its caller is a background task whose
exception nobody would ever see.
"""

from __future__ import annotations

import subprocess
import sys

import pytest

from app.core import self_upgrade
from app.core.self_upgrade import (
    FAILED,
    RUNNING,
    SUCCEEDED,
    UpgradeJob,
    claim_upgrade,
    current_upgrade,
    reset_upgrade_state,
    run_upgrade,
)


@pytest.fixture(autouse=True)
def _clean_slate():
    """No test inherits another's job. The registry is process-wide."""
    reset_upgrade_state()
    yield
    reset_upgrade_state()


def _echo(text: str) -> list[str]:
    """A command that succeeds and prints, without depending on a shell."""
    return [sys.executable, "-c", f"print({text!r})"]


def _fail(code: int, message: str) -> list[str]:
    """A command that writes to stderr and exits non-zero."""
    return [
        sys.executable,
        "-c",
        f"import sys; sys.stderr.write({message!r}); sys.exit({code})",
    ]


class TestOnlyOneUpgradeRuns:
    def test_a_second_claim_returns_the_job_already_running(self) -> None:
        """Two pips against one site-packages is the thing to prevent.

        The user does not have to do anything unusual to get here: the browser
        stops waiting long before the upgrade finishes, and pressing the button
        again is the obvious response to a screen that looks stuck.
        """
        first, started_first = claim_upgrade(_echo("one"), "14.6.0")
        second, started_second = claim_upgrade(_echo("two"), "14.6.0")

        assert started_first is True
        assert started_second is False
        assert second.id == first.id
        assert second.command == first.command, "the second caller's command must not replace the running one"

    def test_a_finished_job_releases_the_slot(self) -> None:
        """One at a time, not one ever."""
        first, _ = claim_upgrade(_echo("one"), "14.6.0")
        run_upgrade(first)

        second, started = claim_upgrade(_echo("two"), "14.6.0")
        assert started is True
        assert second.id != first.id

    def test_a_failed_job_also_releases_the_slot(self) -> None:
        """Otherwise one bad install locks the button until a restart.

        Kept separate from the success case because the failure path is the one
        that would strand a user: they can see it went wrong and would have no
        way to try again.
        """
        first, _ = claim_upgrade(_fail(1, "no such package"), "14.6.0")
        run_upgrade(first)
        assert first.status == FAILED

        second, started = claim_upgrade(_echo("retry"), "14.6.0")
        assert started is True
        assert second.id != first.id

    def test_the_registry_answers_who_is_running(self) -> None:
        assert current_upgrade() is None
        job, _ = claim_upgrade(_echo("hello"), "14.6.0")
        assert current_upgrade() is job
        assert job.status == RUNNING


class TestAFailureCanBeRead:
    def test_a_non_zero_exit_is_failed_and_keeps_the_log(self) -> None:
        """ "Failed" on its own is not something a user can act on."""
        job, _ = claim_upgrade(_fail(2, "could not find a version that satisfies"), "14.6.0")
        run_upgrade(job)

        assert job.status == FAILED
        assert job.exit_code == 2
        assert "could not find a version" in job.stderr

    def test_a_clean_exit_is_succeeded_and_keeps_the_log(self) -> None:
        job, _ = claim_upgrade(_echo("Successfully installed openconstructionerp"), "14.6.0")
        run_upgrade(job)

        assert job.status == SUCCEEDED
        assert job.exit_code == 0
        assert "Successfully installed" in job.stdout

    def test_a_command_that_cannot_run_is_reported_not_raised(self) -> None:
        """The runner's caller is a background task. A raise would go nowhere.

        Not a hypothetical: a frozen build has no interpreter to hand, and a
        stripped container may have no pip. Either way the user is owed the
        reason rather than a spinner that never resolves.
        """
        job = UpgradeJob(
            id="x",
            command=["definitely-not-a-real-executable-oce"],
            running_version="14.6.0",
            started_at="2026-08-11T00:00:00+00:00",
        )
        run_upgrade(job)

        assert job.status == FAILED
        assert job.error, "the exception text is the only explanation there is"

    def test_a_timeout_says_so_rather_than_hanging(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _timeout(*_args, **_kwargs):
            raise subprocess.TimeoutExpired(cmd="pip", timeout=self_upgrade.UPGRADE_TIMEOUT_SECONDS)

        monkeypatch.setattr(self_upgrade.subprocess, "run", _timeout)

        job, _ = claim_upgrade(_echo("never gets here"), "14.6.0")
        run_upgrade(job)

        assert job.status == FAILED
        assert str(self_upgrade.UPGRADE_TIMEOUT_SECONDS) in job.error

    def test_a_finished_job_is_always_stamped(self) -> None:
        """Whatever ended it, the job knows when. A running job does not.

        This is what lets the client tell "still going" from "went wrong and
        stopped" without reading the status string twice.
        """
        job, _ = claim_upgrade(_echo("done"), "14.6.0")
        assert job.finished_at is None
        run_upgrade(job)
        assert job.finished_at is not None


class TestWhatTheApiReports:
    def test_restart_is_required_only_when_the_version_moved(self) -> None:
        """Python caches imports, so a successful install changes nothing here.

        The process goes on serving the version it started with no matter what
        pip wrote to disk, which is exactly why the answer is computed from the
        two version strings rather than from the exit code.
        """
        job = UpgradeJob(
            id="x",
            command=["pip"],
            running_version="14.6.0",
            started_at="2026-08-11T00:00:00+00:00",
            installed_version="14.7.0",
        )
        assert job.restart_required is True

        job.installed_version = "14.6.0"
        assert job.restart_required is False

    def test_an_unknown_installed_version_does_not_claim_a_restart(self) -> None:
        """Written down because the empty string is not equal to the running
        version either, so the naive comparison would demand a restart on an
        upgrade that never reported what it installed."""
        job = UpgradeJob(
            id="x",
            command=["pip"],
            running_version="14.6.0",
            started_at="2026-08-11T00:00:00+00:00",
            installed_version="",
        )
        assert job.restart_required is False

    def test_the_payload_carries_the_id_the_client_polls_with(self) -> None:
        job, _ = claim_upgrade(_echo("hi"), "14.6.0")
        payload = job.as_dict()

        assert payload["job_id"] == job.id
        assert payload["status"] == RUNNING
        assert payload["ok"] is False, "a running upgrade has not succeeded yet"

    def test_ok_tracks_success_rather_than_acceptance(self) -> None:
        """The old route returned ok for the finished pip run, and a client
        reading it as "accepted" would call a running upgrade a success."""
        job, _ = claim_upgrade(_echo("hi"), "14.6.0")
        run_upgrade(job)
        assert job.as_dict()["ok"] is True

        failed, _ = claim_upgrade(_fail(1, "boom"), "14.6.0")
        run_upgrade(failed)
        assert failed.as_dict()["ok"] is False
