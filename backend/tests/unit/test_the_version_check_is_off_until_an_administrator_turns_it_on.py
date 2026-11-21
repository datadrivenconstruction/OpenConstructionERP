# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The version check is a workspace setting, and it starts off.

Asking PyPI and GitHub which release is newest is a connection nobody in the
workspace started. It was already switchable twice over - an administrator's
``OE_DISABLE_UPDATE_CHECK`` and the desktop launcher's "Turn off update checks",
both read by :mod:`app.core.update_check_policy` - and both were opt-*out*: the
check ran until somebody found the switch and turned it off, so every install
that nobody had configured was an install that phoned out once a day.

It is an opt-in now, held on the workspace branding record beside the support
destination, for the reasons that record is already the home of the two settings
next to it: it is server-side, so it follows the workspace instead of one
browser; it is admin-only to write and public to read, which is exactly the shape
a disclosure needs - every user can see whether their installation asks, and only
an administrator can change the answer; and it needs no schema change, no
migration and no second cache to keep coherent.

The default is the point of the file, and the ambiguity rule is its mirror image
of the one beside it. ``legal_link_visible`` treats anything that is not exactly
``False`` as visible, because hiding a licence pointer is the direction that needs
permission. ``update_check_enabled`` treats anything that is not exactly ``True``
as off, because asking the internet is the direction that needs permission - the
same sentence :func:`app.core.update_check_policy.update_check_disabled` already
used for a home folder it could not stat. A corrupt file, a hand-edited ``"yes"``,
a ``1`` somebody typed and a missing key all leave the product silent.

These tests need no database and no web framework: the record is a JSON file in a
temporary directory and the policy is stdlib, which is why they sit beside the
sibling file for the two settings they join rather than in a lane that has to boot
a cluster to read a file.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.core import update_check_policy as policy
from app.core.app_branding import (
    BRANDING_FILENAME,
    DEFAULT_BRANDING,
    read_branding,
    sanitise,
    write_branding,
)


def test_a_fresh_workspace_does_not_check(tmp_path: Path) -> None:
    """The default, which is the whole reason this setting exists."""
    assert DEFAULT_BRANDING["update_check_enabled"] is False
    assert read_branding(data_dir=tmp_path)["update_check_enabled"] is False
    # And the policy agrees with the record: no file at all is not a "yes, ask".
    assert policy.update_check_disabled(home=tmp_path, data_dir=tmp_path) is True


def test_an_administrator_turning_it_on_is_stored_and_reaches_the_policy(tmp_path: Path) -> None:
    write_branding({"update_check_enabled": True}, data_dir=tmp_path)
    assert read_branding(data_dir=tmp_path)["update_check_enabled"] is True
    assert policy.update_check_disabled(home=tmp_path, data_dir=tmp_path) is False


def test_turning_it_back_off_is_stored_too(tmp_path: Path) -> None:
    write_branding({"update_check_enabled": True}, data_dir=tmp_path)
    write_branding({"update_check_enabled": False}, data_dir=tmp_path)
    assert read_branding(data_dir=tmp_path)["update_check_enabled"] is False
    assert policy.update_check_disabled(home=tmp_path, data_dir=tmp_path) is True


def test_only_an_exact_true_turns_it_on() -> None:
    """The mirror image of the visibility rule beside it, and for the same reason.

    Every value that is not the boolean ``True`` leaves the product silent: a
    missing key, a hand-edited string, a number, a list. The direction that needs
    permission is the outbound one, so ambiguity resolves against asking.
    """
    for value in (None, "yes", "true", "1", 1, 2, [], {}, 0, False):
        assert sanitise({"update_check_enabled": value})["update_check_enabled"] is False, repr(value)
    assert sanitise({"update_check_enabled": True})["update_check_enabled"] is True


def test_a_hand_edited_record_cannot_turn_the_check_on(tmp_path: Path) -> None:
    """The read path sanitises, so the file is not a way around the admin gate.

    Somebody with write access to the data directory can already do worse things
    than this; what must not happen is a *string* in a JSON file being read as an
    administrator's decision to phone out, because the endpoint that reads it is
    the one that makes the connection.
    """
    path = tmp_path / BRANDING_FILENAME
    path.write_text(json.dumps({"update_check_enabled": "yes", "company_name": "Meridian"}), encoding="utf-8")
    stored = read_branding(data_dir=tmp_path)
    assert stored["update_check_enabled"] is False
    assert stored["company_name"] == "Meridian", "the rest of a hand-edited record is still honoured"
    assert policy.update_check_disabled(home=tmp_path, data_dir=tmp_path) is True


def test_a_corrupt_record_leaves_the_check_off(tmp_path: Path) -> None:
    (tmp_path / BRANDING_FILENAME).write_text("{not json", encoding="utf-8")
    assert read_branding(data_dir=tmp_path)["update_check_enabled"] is False
    assert policy.update_check_disabled(home=tmp_path, data_dir=tmp_path) is True


def test_a_data_directory_that_cannot_be_read_answers_off(tmp_path: Path) -> None:
    """An unreadable record is the same case as an unanswerable home folder.

    The policy already returned "disabled" when it could not stat the launcher's
    opt-out file; a data directory that is not a directory has to answer the same
    way rather than raising inside a request handler.
    """
    not_a_directory = tmp_path / "app_branding.json"
    not_a_directory.write_text("{}", encoding="utf-8")
    assert policy.update_check_disabled(home=tmp_path, data_dir=not_a_directory) is True


def test_the_operator_switches_still_win_over_a_workspace_that_asked(tmp_path: Path) -> None:
    """Turning the setting on in the product cannot overrule an explicit opt-out.

    Both switches predate this one and both mean "never": the administrator's
    environment variable, and the file the desktop launcher writes when a user
    presses "Turn off update checks". A workspace record that says ``True`` while
    either of those is set is a contradiction, and the answer has to be the one
    that sends nothing outward - otherwise an administrator in the UI would be
    able to undo an opt-out a user made from the launcher's own notice.
    """
    write_branding({"update_check_enabled": True}, data_dir=tmp_path)

    opt_out = policy.opt_out_path(tmp_path)
    opt_out.parent.mkdir(parents=True, exist_ok=True)
    opt_out.write_text("OpenConstructionERP does not check for a newer version while this file exists.\n")
    assert policy.update_check_disabled(home=tmp_path, data_dir=tmp_path) is True


def test_the_caller_can_answer_the_workspace_question_itself(tmp_path: Path) -> None:
    """The seam the endpoint and the tests both use.

    ``workspace_enabled`` lets a caller state the record's answer instead of
    having it read, which is how a test can exercise the precedence without
    writing a file, and how a caller that already holds the record - the branding
    response, say - can avoid a second read of the same JSON.
    """
    assert policy.update_check_disabled(home=tmp_path, workspace_enabled=True) is False
    assert policy.update_check_disabled(home=tmp_path, workspace_enabled=False) is True
    # Nothing passed means "read the record", and an absent record says off.
    assert policy.update_check_disabled(home=tmp_path, data_dir=tmp_path) is True


def test_sanitise_never_drops_the_setting_whatever_else_arrives() -> None:
    """A corrupt payload degrades to the default rather than to a KeyError.

    The endpoint reads this key on every call, so a sanitiser that omitted it
    would turn a malformed record into an exception inside a request handler.
    """
    for payload in (None, "branding", [], {"mode": "nonsense"}):
        out = sanitise(payload)
        assert "update_check_enabled" in out, payload
        assert out["update_check_enabled"] is False, payload
