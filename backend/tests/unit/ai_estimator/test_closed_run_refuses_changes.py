# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""An applied or cancelled estimate run no longer changes.

Applying a run writes its confirmed groups into a BOQ and marks the run
``applied``; cancelling marks it ``cancelled``. ``add_sources`` and ``cancel``
already refused a run past their point, but every other writer (analyze, stage
confirm, matching, the intake steps and the group edits) rewrote the run or its
groups whatever its status. A confirm on an applied group even put it back to
``confirmed``, so a second apply would write the same lines into the bill twice.

Each writer is driven with stubbed repositories whose first write raises a
sentinel, so a test observes whether the call stopped before writing. Every
refusal is asserted by its detail text, because several writers raise 409 for
other reasons, and every writer also gets an open-run control that must still
reach the write.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException

from app.modules.ai_estimator import schemas
from app.modules.ai_estimator.intake import IntakeService
from app.modules.ai_estimator.service import AiEstimatorService


class _ReachedTheWrite(Exception):
    """Raised by the stubs for the first step that writes."""


def _write(*_args: Any, **_kwargs: Any) -> Any:
    raise _ReachedTheWrite


async def _awrite(*_args: Any, **_kwargs: Any) -> Any:
    raise _ReachedTheWrite


def _run(status: str) -> Any:
    return SimpleNamespace(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        status=status,
        checkpoints={},
        suggested_config={},
        metadata_={},
        catalogue_id=None,
        region=None,
        currency=None,
        group_by=None,
        construction_stage=None,
        source_inputs={},
    )


def _group(run: Any) -> Any:
    return SimpleNamespace(
        id=uuid.uuid4(),
        run_id=run.id,
        status="applied" if run.status == "applied" else "suggested",
        candidate_id="c1",
        candidates=[{"candidate_id": "c1", "code": "X", "unit_rate": "1", "score": 0.9}],
        confidence=0.95,
        element_ids=["e1", "e2"],
        quantities={"count": 2.0},
        group_key="k",
        sort_order=0,
        description="d",
    )


def _service(run: Any, grp: Any) -> AiEstimatorService:
    service = AiEstimatorService.__new__(AiEstimatorService)

    async def _get_run(_rid: Any) -> Any:
        return run

    async def _list_for_run(_rid: Any, **_kw: Any) -> list[Any]:
        return [grp]

    service.session = SimpleNamespace(delete=_awrite, flush=_awrite, add=_write)  # type: ignore[assignment]
    service.run_repo = SimpleNamespace(get_by_id=_get_run, update_fields=_awrite)  # type: ignore[assignment]
    service.group_repo = SimpleNamespace(  # type: ignore[assignment]
        list_for_run=_list_for_run, update_fields=_awrite, add=_awrite, get_by_id=_awrite
    )
    service._log = _awrite  # type: ignore[method-assign]
    service._bind_run_catalogue = _awrite  # type: ignore[method-assign]
    return service


def _intake_service(run: Any) -> tuple[IntakeService, Any]:
    service = IntakeService.__new__(IntakeService)
    intake = SimpleNamespace(
        id=uuid.uuid4(),
        detected_type="residential_house",
        params={},
        param_status={},
        packages=[{"package_key": "p1", "selected": True, "group_ids": [str(uuid.uuid4())]}],
        raw_request="",
    )

    async def _get_run(_rid: Any) -> Any:
        return run

    service.session = SimpleNamespace(delete=_awrite, flush=_awrite)  # type: ignore[assignment]
    service.run_repo = SimpleNamespace(get_by_id=_get_run, update_fields=_awrite)  # type: ignore[assignment]
    service.intake_repo = SimpleNamespace(update_fields=_awrite)  # type: ignore[assignment]
    service.group_repo = SimpleNamespace(get_by_id=_awrite)  # type: ignore[assignment]
    service._require_type = lambda *_a, **_kw: SimpleNamespace(key="residential_house")  # type: ignore[method-assign]
    service._reseed_type = _awrite  # type: ignore[method-assign]
    service._apply_defaults = lambda *_a, **_kw: None  # type: ignore[method-assign]
    return service, intake


async def _call(writer: str, run: Any) -> None:
    grp = _group(run)
    user = uuid.uuid4()
    if writer.startswith("intake."):
        isvc, intake = _intake_service(run)
        if writer == "intake.answer":
            await isvc.answer(run, intake, schemas.IntakeAnswerRequest(project_type="other_type"))
        elif writer == "intake.confirm_parameters":
            await isvc.confirm_parameters(run, intake, schemas.ConfirmParametersRequest(params={}))
        elif writer == "intake.edit_packages":
            await isvc.edit_packages(run, intake, schemas.IntakePackagesRequest(remove=["p1"]))
        elif writer == "intake.finish":
            await isvc.finish(run, intake, user)
        return
    svc = _service(run, grp)
    if writer == "analyze":
        await svc.analyze(run, use_ai=False)
    elif writer == "confirm_stage":
        await svc.confirm_stage(run, schemas.StageConfirmRequest(stage="grouping"), user)
    elif writer == "run_matching":
        await svc.run_matching(run, schemas.RunMatchRequest())
    elif writer == "update_group":
        await svc.update_group(grp, schemas.GroupUpdate(notes="n"), user)
    elif writer == "confirm_group":
        await svc.confirm_group(grp, schemas.ConfirmGroupRequest(), user)
    elif writer == "merge_groups":
        # One group id in the body is refused with 400 by the input check, so a
        # closed-run refusal has to come first to be seen here.
        await svc.merge_groups(run, schemas.GroupMergeRequest(group_ids=[grp.id]))
    elif writer == "split_group":
        await svc.split_group(run, schemas.GroupSplitRequest(element_ids=["e1"]))
    elif writer == "bulk_confirm":
        await svc.bulk_confirm(run, schemas.BulkConfirmRequest(threshold=0.5), user)
    else:  # pragma: no cover - a typo in the parametrisation
        raise AssertionError(writer)


_WRITERS = [
    "analyze",
    "confirm_stage",
    "run_matching",
    "update_group",
    "confirm_group",
    "merge_groups",
    "split_group",
    "bulk_confirm",
    "intake.answer",
    "intake.confirm_parameters",
    "intake.edit_packages",
    "intake.finish",
]

_DETAIL = {
    "applied": "An applied run can no longer be changed.",
    "cancelled": "A cancelled run can no longer be changed.",
}


@pytest.mark.parametrize("closed", ["applied", "cancelled"])
@pytest.mark.parametrize("writer", _WRITERS)
async def test_a_closed_run_refuses_the_write(writer: str, closed: str) -> None:
    with pytest.raises(HTTPException) as exc:
        await _call(writer, _run(closed))
    assert exc.value.status_code == 409
    assert exc.value.detail == _DETAIL[closed]


# Merging one group is refused by its own input check on an open run, so its
# control asserts that check (400) instead of the write.
_OPEN_OUTCOME_OVERRIDES = {"merge_groups": 400}


@pytest.mark.parametrize("writer", _WRITERS)
async def test_an_open_run_still_reaches_the_write(writer: str) -> None:
    run = _run("review")
    expected = _OPEN_OUTCOME_OVERRIDES.get(writer)
    if expected is None:
        with pytest.raises(_ReachedTheWrite):
            await _call(writer, run)
    else:
        with pytest.raises(HTTPException) as exc:
            await _call(writer, run)
        assert exc.value.status_code == expected


async def test_a_failed_run_can_still_be_analyzed_again() -> None:
    """``failed`` is not closed: re-running the analysis is the retry path."""
    with pytest.raises(_ReachedTheWrite):
        await _call("analyze", _run("failed"))
