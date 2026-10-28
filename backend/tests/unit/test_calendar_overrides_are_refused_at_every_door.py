# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Every entrance to the CPM work calendar refuses the same overrides.

The engine has more than one way in. A calendar reaches it through a
schedule's ``metadata`` and through the CPM endpoint's request body, and the
two do not share a schema. Guarding one and not the other is the defect these
tests exist to prevent, so they are parametrized over the doors rather than
written twice: a third entrance joins by adding a row to ``DOORS``, and every
case in this file then applies to it.

The refusals carry their own negative control. ``_PreChangeCPMCalculateRequest``
is the request model exactly as it stood before the guard was added, and every
value the request-body door now refuses is asserted to have been accepted by
it. Without that, a suite that passed for both doors while only one was
guarded would look identical to this one.
"""

from typing import Any
from uuid import uuid4

import pytest
from pydantic import BaseModel, ValidationError

from app.core.cpm import ACCEPTED_EXCEPTION_FORMS
from app.modules.schedule.schemas import CPMCalculateRequest, ScheduleCreate, ScheduleUpdate


def _via_create_metadata(calendar: dict[str, Any]) -> dict[str, Any]:
    """Enter through a new schedule's metadata and return the stored override."""
    built = ScheduleCreate(project_id=uuid4(), name="Door under test", metadata={"calendar": calendar})
    return built.metadata["calendar"]


def _via_update_metadata(calendar: dict[str, Any]) -> dict[str, Any]:
    """Enter through a schedule patch's metadata and return the stored override."""
    built = ScheduleUpdate(metadata={"calendar": calendar})
    assert built.metadata is not None
    return built.metadata["calendar"]


def _via_request_body(calendar: dict[str, Any]) -> dict[str, Any]:
    """Enter through the CPM endpoint's request body and return the override."""
    built = CPMCalculateRequest(calendar=calendar)
    assert built.calendar is not None
    return built.calendar


#: Every entrance to the engine's calendar, with the source prefix its errors
#: must carry. The prefix is asserted so a message cannot name a field that
#: merely resembles the one the writer has to correct.
DOORS = [
    pytest.param(_via_create_metadata, "metadata.calendar", id="schedule-create-metadata"),
    pytest.param(_via_update_metadata, "metadata.calendar", id="schedule-update-metadata"),
    pytest.param(_via_request_body, "calendar", id="cpm-request-body"),
]

#: Spellings that name one unambiguous day. Each is stored as the canonical
#: ``YYYY-MM-DD`` so the readers that compare ISO strings without parsing them
#: see one spelling rather than six.
ACCEPTED = [
    pytest.param("2026-05-01", id="iso"),
    pytest.param("20260501", id="compact"),
    pytest.param("2026-05-01T00:00:00", id="iso-datetime-T"),
    pytest.param("2026-05-01 00:00:00", id="iso-datetime-space"),
    pytest.param("2026-05-01T09:30:00", id="iso-datetime-with-time"),
    pytest.param(" 2026-05-01 ", id="untrimmed"),
]

#: Spellings that name no single day, or name one only by guessing which of two
#: locale conventions the writer meant.
REFUSED = [
    pytest.param("01/05/2026", id="slashed-ambiguous"),
    pytest.param("2026-5-1", id="unpadded"),
    pytest.param("2026-13-01", id="impossible-month"),
    pytest.param("2026-02-30", id="impossible-day"),
    pytest.param("next friday", id="prose"),
    pytest.param("", id="empty"),
    pytest.param(None, id="none"),
]


class _PreChangeCPMCalculateRequest(BaseModel):
    """The CPM request model exactly as it stood before the guard was added.

    Kept so the refusals below have something to be refused against. It is a
    fixture, not production code.
    """

    calendar: dict[str, Any] | None = None


# ── Control: the doors work at all ────────────────────────────────────────


@pytest.mark.parametrize(("door", "prefix"), DOORS)
def test_a_good_calendar_passes_every_door(door, prefix) -> None:
    """Control. Without this, every refusal below could pass by refusing all input."""
    stored = door({"work_days": [0, 1, 2, 3, 4], "exceptions": ["2026-05-01"]})
    assert stored["work_days"] == [0, 1, 2, 3, 4]
    assert stored["exceptions"] == ["2026-05-01"]


@pytest.mark.parametrize(("door", "prefix"), DOORS)
def test_a_calendar_without_exceptions_passes_every_door(door, prefix) -> None:
    """The key is optional, and its absence is not an empty list."""
    stored = door({"work_days": [0, 1, 2, 3, 4]})
    assert "exceptions" not in stored


# ── Exceptions: accepted spellings ────────────────────────────────────────


@pytest.mark.parametrize(("door", "prefix"), DOORS)
@pytest.mark.parametrize("spelling", ACCEPTED)
def test_an_unambiguous_day_is_accepted_and_canonicalised(door, prefix, spelling) -> None:
    stored = door({"work_days": [0, 1, 2, 3, 4], "exceptions": [spelling]})
    assert stored["exceptions"] == ["2026-05-01"]


@pytest.mark.parametrize(("door", "prefix"), DOORS)
def test_accepted_spellings_all_collapse_to_one(door, prefix) -> None:
    """The point of normalising: six spellings of one day become one string.

    The readers downstream compare ISO strings without parsing them, so two
    spellings of the same holiday would be two different holidays to them and
    neither would match the day being tested.
    """
    every = [p.values[0] for p in ACCEPTED]
    stored = door({"work_days": [0, 1, 2, 3, 4], "exceptions": every})
    assert set(stored["exceptions"]) == {"2026-05-01"}


# ── Exceptions: refused spellings ─────────────────────────────────────────


@pytest.mark.parametrize(("door", "prefix"), DOORS)
@pytest.mark.parametrize("spelling", REFUSED)
def test_a_value_naming_no_single_day_is_refused(door, prefix, spelling) -> None:
    with pytest.raises(ValidationError) as err:
        door({"work_days": [0, 1, 2, 3, 4], "exceptions": [spelling]})
    assert f"{prefix}.exceptions" in str(err.value)


@pytest.mark.parametrize(("door", "prefix"), DOORS)
def test_the_refusal_names_the_offending_value_and_the_accepted_forms(door, prefix) -> None:
    with pytest.raises(ValidationError) as err:
        door({"work_days": [0, 1, 2, 3, 4], "exceptions": ["2026-05-01", "01/05/2026"]})
    message = str(err.value)
    assert "01/05/2026" in message, "the writer cannot fix what the error does not name"
    assert ACCEPTED_EXCEPTION_FORMS in message


@pytest.mark.parametrize(("door", "prefix"), DOORS)
def test_a_bare_string_is_refused_rather_than_walked_character_by_character(door, prefix) -> None:
    """A single date is still a list of one.

    Iterating the string instead would make ``"2026-05-01"`` ten one-character
    exceptions and report ten separate refusals for one mistake.
    """
    with pytest.raises(ValidationError) as err:
        door({"work_days": [0, 1, 2, 3, 4], "exceptions": "2026-05-01"})
    assert f"{prefix}.exceptions" in str(err.value)
    assert "str" in str(err.value)


# ── Work days: the field the sibling guard already covered elsewhere ──────


@pytest.mark.parametrize(("door", "prefix"), DOORS)
@pytest.mark.parametrize("weekdays", [[0, 1, 2, 3, 4], [5, 6], [0, 1, 2, 3, 4, 5, 6], [3]])
def test_a_real_week_is_accepted(door, prefix, weekdays) -> None:
    stored = door({"work_days": weekdays})
    assert stored["work_days"] == weekdays


@pytest.mark.parametrize(("door", "prefix"), DOORS)
@pytest.mark.parametrize("weekdays", [[0, 1, 7], [-1], [7], [0, 1, 2, 3, 4, 99]])
def test_a_weekday_outside_the_week_is_refused(door, prefix, weekdays) -> None:
    """Sunday is 6, not 7. A calendar counting to 7 silently shortens the week."""
    with pytest.raises(ValidationError) as err:
        door({"work_days": weekdays})
    assert f"{prefix}.work_days" in str(err.value)


# ── Negative control, aimed at the door this commit adds ──────────────────


@pytest.mark.parametrize("spelling", REFUSED)
def test_the_request_body_door_used_to_accept_every_refused_spelling(spelling) -> None:
    """Every value the request-body door now refuses was accepted before.

    A suite that passed against this fixture as well would be reporting the
    metadata guard that already existed rather than the one added here.
    """
    built = _PreChangeCPMCalculateRequest(calendar={"work_days": [0, 1, 2, 3, 4], "exceptions": [spelling]})
    assert built.calendar is not None
    assert built.calendar["exceptions"] == [spelling], "the old door stored it exactly as sent"


@pytest.mark.parametrize("weekdays", [[0, 1, 7], [-1], [7]])
def test_the_request_body_door_used_to_accept_impossible_weekdays(weekdays) -> None:
    built = _PreChangeCPMCalculateRequest(calendar={"work_days": weekdays})
    assert built.calendar is not None
    assert built.calendar["work_days"] == weekdays


def test_the_pre_change_fixture_is_not_secretly_guarded() -> None:
    """Guards the control itself.

    If the fixture ever gained a validator, the two tests above would start
    passing for the wrong reason and stop being a control at all.
    """
    assert not _PreChangeCPMCalculateRequest.__pydantic_decorators__.field_validators
    assert not _PreChangeCPMCalculateRequest.__pydantic_decorators__.model_validators
