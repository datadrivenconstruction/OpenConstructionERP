# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Build the trainer API fixture responses from the Pydantic schemas.

The responses are constructed as schema instances, so a fixture that does not
validate cannot be written at all. Each one is written twice:

* ``backend/tests/fixtures/trainer/api/<name>.json`` for the backend suites;
* ``frontend/src/features/trainer/__fixtures__/<name>.ts`` as a typed
  ``export const``. A JSON import would widen every string literal to
  ``string``, so ``tsc`` could not check it against the literal unions in
  ``types.ts``; an object literal assigned to the interface is checked field by
  field, extra keys included.

The content follows ``course_fixture_v1.json``: task 1 passed, task 2 failed
its first check (profit compounded on overheads), tasks 3 to 5 locked.
Timestamps and ids are fixed so the output is byte-for-byte reproducible.

``test_trainer_contract_parity.py`` rebuilds everything and compares it with
the files on disk, so an edited schema without a regenerated fixture fails.

Run from ``backend/``::

    python tests/fixtures/trainer/generate_api_fixtures.py
"""

from __future__ import annotations

import json
import sys
import uuid
from datetime import UTC, date, datetime
from pathlib import Path

from pydantic import BaseModel

HERE = Path(__file__).resolve().parent
BACKEND_DIR = HERE.parents[2]
REPO_ROOT = BACKEND_DIR.parent
API_DIR = HERE / "api"
FRONTEND_FIXTURES_DIR = REPO_ROOT / "frontend" / "src" / "features" / "trainer" / "__fixtures__"

if str(BACKEND_DIR) not in sys.path:  # run as a script from anywhere
    sys.path.insert(0, str(BACKEND_DIR))

from app.modules.trainer import schemas as s  # noqa: E402

_BOQ_ID = "7a4c1f0e-2b3d-4e5f-8a9b-0c1d2e3f4a5b"
_ATTEMPT_FAIL_ID = uuid.UUID("3f0b8d6e-1c2a-4b5d-9e8f-7a6b5c4d3e21")
_ATTEMPT_PASS_ID = uuid.UUID("5e2d1c0b-9a8f-4e7d-8c6b-5a4f3e2d1c09")
_CLIENT_FAIL_ID = uuid.UUID("0d9c8b7a-6f5e-4d3c-8b2a-1f0e9d8c7b61")
_CLIENT_PASS_ID = uuid.UUID("1e0d9c8b-7a6f-4e5d-9c3b-2a1f0e9d8c72")
_T1_PASSED_AT = datetime(2026, 10, 5, 9, 12, tzinfo=UTC)
_T2_FAILED_AT = datetime(2026, 10, 5, 10, 40, tzinfo=UTC)
_T2_PASSED_AT = datetime(2026, 10, 5, 11, 5, tzinfo=UTC)

_COURSE_ID = "fx-quillmere-1"
_BOQ_ROUTE = f"/boq/{_BOQ_ID}"


def _rings(numbers: bool, trace: bool, explain: bool) -> s.TaskRings:
    return s.TaskRings(numbers=numbers, trace=trace, explain=explain)


def _progress(done: int, numbers: int, trace: int, explain: int) -> s.CourseProgress:
    return s.CourseProgress(
        done=done,
        total=5,
        rings=s.ProgressRings(
            numbers=s.RingProgress(done=numbers, total=5),
            trace=s.RingProgress(done=trace, total=5),
            explain=s.RingProgress(done=explain, total=5),
        ),
    )


def build_me() -> s.TrainerMe:
    """``GET /me`` after task 1 passed and task 2 failed once."""
    locked = {"status": "locked", "rings": _rings(False, False, False), "target": None, "video": None}
    tasks = [
        s.TaskSummary(
            id="t1-direct-cost",
            n=1,
            title="Price the blockwork and read the direct cost",
            module="boq",
            opens="boq.markups_panel",
            opens_label="Markups",
            estimated_minutes=15,
            status="passed",
            rings=_rings(True, True, True),
            target=s.TaskTarget(route=_BOQ_ROUTE, anchor=None),
            video=s.TaskVideo(episode="FX01", title="Pricing a position", route="/videos?episode=FX01"),
            checked_prompt="Type the direct cost the bill shows now.",
            lock_reason=None,
        ),
        s.TaskSummary(
            id="t2-markups",
            n=2,
            title="Add overheads and profit",
            module="boq",
            opens="bid_management",
            opens_label="Bid Management",
            estimated_minutes=20,
            status="needs_revision",
            rings=_rings(False, True, False),
            target=s.TaskTarget(route=_BOQ_ROUTE, anchor="boq-markups-panel"),
            video=s.TaskVideo(episode="FX02", title="Markups on direct cost", route="/videos?episode=FX02"),
            checked_prompt="Type the overheads amount.",
            lock_reason=None,
        ),
        s.TaskSummary(
            id="t3-tender",
            n=3,
            title="Level the roofing bids and award",
            module="bid_management",
            opens="contracts.progress_claims",
            opens_label="Progress claims",
            estimated_minutes=25,
            checked_prompt="Type Alderby's normalised total and the lowest normalised bid.",
            lock_reason="Opens when task 2 passes.",
            **locked,
        ),
        s.TaskSummary(
            id="t4-valuation",
            n=4,
            title="Value the first claim",
            module="contracts",
            opens="variations",
            opens_label="Variations",
            estimated_minutes=25,
            checked_prompt="Type the retention on claim 1.",
            lock_reason=None,
            **locked,
        ),
        s.TaskSummary(
            id="t5-variation",
            n=5,
            title="Value the rooflight variation",
            module="variations",
            opens=f"badge:{_COURSE_ID}",
            opens_label="Course badge",
            estimated_minutes=25,
            checked_prompt="Type the net value of the variation.",
            lock_reason=None,
            **locked,
        ),
    ]
    unlocks = [
        s.UnlockInfo(
            lock_id="boq.markups_panel",
            kind="panel",
            state="open",
            opened_by_task=1,
            opened_at=_T1_PASSED_AT,
            seen=True,
            tiles=[s.UnlockTile(title="Markups", text="Add overheads and profit on the bill.")],
        ),
        s.UnlockInfo(
            lock_id="bid_management",
            kind="module",
            state="locked",
            opened_by_task=2,
            opened_at=None,
            seen=False,
            tiles=[],
        ),
        s.UnlockInfo(
            lock_id="contracts.progress_claims",
            kind="tab",
            state="locked",
            opened_by_task=3,
            opened_at=None,
            seen=False,
            tiles=[],
        ),
        s.UnlockInfo(
            lock_id="variations",
            kind="module",
            state="locked",
            opened_by_task=4,
            opened_at=None,
            seen=False,
            tiles=[],
        ),
        s.UnlockInfo(
            lock_id=f"badge:{_COURSE_ID}",
            kind="badge",
            state="locked",
            opened_by_task=5,
            opened_at=None,
            seen=False,
            tiles=[],
        ),
    ]
    week_days = [
        s.WeekDay(date=date(2026, 10, 5), state="done"),
        s.WeekDay(date=date(2026, 10, 6), state="empty"),
        s.WeekDay(date=date(2026, 10, 7), state="empty"),
        s.WeekDay(date=date(2026, 10, 8), state="empty"),
        s.WeekDay(date=date(2026, 10, 9), state="empty"),
        s.WeekDay(date=date(2026, 10, 10), state="off"),
        s.WeekDay(date=date(2026, 10, 11), state="off"),
    ]
    return s.TrainerMe(
        course=s.CourseInfo(
            id=_COURSE_ID,
            version="1.0.0",
            title="Quillmere Depot: from bill to variation (test fixture)",
            summary="A synthetic five-task course for the trainer test suites.",
            language="en",
            country="GB",
            locale="en-GB",
            currency="GBP",
            contract="Fictional lump-sum building contract with quantities",
            badge=s.CourseBadge(id=_COURSE_ID, title="Quillmere Depot: bill to variation"),
        ),
        tasks=tasks,
        unlocks=unlocks,
        nav=s.NavInfo(outside_course="hidden", always_open=["projects", "boq"]),
        progress=_progress(done=1, numbers=1, trace=2, explain=1),
        week=s.WeekInfo(goal=3, done=1, days=week_days),
        level=None,
    )


def _t2_fields(passing: bool) -> list[s.FieldResult]:
    """The five graded items of task 2, failing on the grand total and explain."""
    grand_total = (
        s.FieldResult(
            key="grand_total",
            source="erp",
            verdict="ok",
            observed="34367.82",
            diagnosis=None,
            feedback=None,
        )
        if passing
        else s.FieldResult(
            key="grand_total",
            source="erp",
            verdict="wrong",
            observed="34489.48",
            diagnosis=s.Diagnosis(
                id="t2-profit-compounded",
                kind="error",
                message="Profit was charged on the overheads as well.",
                related=[s.RelatedValue(name="fx_profit_amount", value="1520.70", kind="money")],
            ),
            feedback=None,
        )
    )
    explain = (
        s.FieldResult(
            key="t2-explain",
            source="panel",
            verdict="ok",
            observed="0",
            diagnosis=None,
            feedback="Right: 5% of 2433.12 is the 121.66 difference.",
        )
        if passing
        else s.FieldResult(
            key="t2-explain",
            source="panel",
            verdict="wrong",
            observed="1",
            diagnosis=None,
            feedback="Rounding moves a few pence, not 121.66.",
        )
    )
    return [
        s.FieldResult(
            key="overheads_amount",
            source="panel",
            verdict="ok",
            observed="2433.12",
            diagnosis=None,
            feedback=None,
        ),
        grand_total,
        s.FieldResult(
            key="profit_rate",
            source="erp",
            verdict="ok",
            observed="5.00",
            diagnosis=None,
            feedback=None,
        ),
        s.FieldResult(
            key="t2-trace",
            source="panel",
            verdict="ok",
            observed="0",
            diagnosis=None,
            feedback="Yes: 30414.00 x 5% = 1520.70.",
        ),
        explain,
    ]


def build_attempt_fail() -> s.AttemptResult:
    """Task 2, first check: profit compounded, wrong explain option."""
    return s.AttemptResult(
        attempt_id=_ATTEMPT_FAIL_ID,
        client_attempt_id=_CLIENT_FAIL_ID,
        task_id="t2-markups",
        verdict="fail",
        graded_items=5,
        passed_items=3,
        fields=_t2_fields(passing=False),
        task_status="needs_revision",
        rings=_rings(False, True, False),
        progress=_progress(done=1, numbers=1, trace=2, explain=1),
        unlocked=[],
        regressed=False,
        revealed_hint="Both markups apply to direct cost.",
        checked_at=_T2_FAILED_AT,
    )


def build_attempt_pass() -> s.AttemptResult:
    """Task 2, second check: everything right, Bid Management opens."""
    return s.AttemptResult(
        attempt_id=_ATTEMPT_PASS_ID,
        client_attempt_id=_CLIENT_PASS_ID,
        task_id="t2-markups",
        verdict="pass",
        graded_items=5,
        passed_items=5,
        fields=_t2_fields(passing=True),
        task_status="passed",
        rings=_rings(True, True, True),
        progress=_progress(done=2, numbers=2, trace=2, explain=2),
        unlocked=["bid_management"],
        regressed=False,
        revealed_hint=None,
        checked_at=_T2_PASSED_AT,
    )


def build_task() -> s.TaskView:
    """``GET /tasks/t2-markups`` after the failed check."""
    return s.TaskView(
        id="t2-markups",
        n=2,
        title="Add overheads and profit",
        module="boq",
        status="needs_revision",
        brief="Add the overheads and profit the firm agreed for this job, both on direct cost.",
        given=[
            s.GivenItem(name="Overheads rate", value="8", kind="percent"),
            s.GivenItem(name="Profit rate", value="5", kind="percent"),
        ],
        steps=[
            "Open the markups panel of the main bill.",
            "Add overheads at 8 per cent on direct cost.",
            "Add profit at 5 per cent on direct cost.",
            "Type the overheads amount; the checker reads the grand total from the bill.",
        ],
        hints=["Both markups apply to direct cost."],
        hints_total=2,
        panel_notes=[],
        has_date_steps=False,
        checks=[
            s.NumbersCheckView(
                id="t2-numbers",
                kind="numbers",
                prompt="Type the overheads amount.",
                fields=[s.CheckField(key="overheads_amount", label="Overheads", kind="money", currency="GBP")],
            ),
            s.ChoiceCheckView(
                id="t2-trace",
                kind="trace",
                prompt="What is profit calculated on?",
                options=[
                    s.ChoiceOption(index=0, text="Direct cost only."),
                    s.ChoiceOption(index=1, text="Direct cost plus overheads."),
                    s.ChoiceOption(index=2, text="The grand total."),
                ],
            ),
            s.ChoiceCheckView(
                id="t2-explain",
                kind="explain",
                prompt="Why does compounding profit change the total?",
                options=[
                    s.ChoiceOption(index=0, text="Profit would also be charged on the overheads."),
                    s.ChoiceOption(index=1, text="The ERP rounds each markup."),
                    s.ChoiceOption(index=2, text="Overheads are counted twice."),
                ],
            ),
        ],
        readback=[
            s.ReadbackItemView(id="rb0", what="Grand total of the main bill", kind="money"),
            s.ReadbackItemView(id="rb1", what="Percentage of the profit markup", kind="percent"),
        ],
        answers=[
            s.SavedAnswer(name="overheads_amount", kind="number", value_text="2433.12", option_index=None),
            s.SavedAnswer(name="t2-trace", kind="option", value_text=None, option_index=0),
            s.SavedAnswer(name="t2-explain", kind="option", value_text=None, option_index=1),
        ],
        answers_revision=3,
        last_attempt=build_attempt_fail(),
    )


def build_readback() -> s.ReadbackResponse:
    """``GET /tasks/t2-markups/readback`` while the profit is still compounded."""
    return s.ReadbackResponse(
        task_id="t2-markups",
        items=[
            s.ReadbackValue(id="rb0", state="mismatch", app_value="34489.48", kind="money"),
            s.ReadbackValue(id="rb1", state="match", app_value="5.00", kind="percent"),
        ],
        read_at=_T2_FAILED_AT,
    )


#: name -> (builder, TS export name, TS type name)
FIXTURES: dict[str, tuple[object, str, str]] = {
    "me": (build_me, "meFixture", "TrainerMe"),
    "task": (build_task, "taskFixture", "TaskView"),
    "attempt_pass": (build_attempt_pass, "attemptPassFixture", "AttemptResult"),
    "attempt_fail": (build_attempt_fail, "attemptFailFixture", "AttemptResult"),
    "readback": (build_readback, "readbackFixture", "ReadbackResponse"),
}

#: The schema class each fixture must validate against.
FIXTURE_SCHEMAS: dict[str, type[BaseModel]] = {
    "me": s.TrainerMe,
    "task": s.TaskView,
    "attempt_pass": s.AttemptResult,
    "attempt_fail": s.AttemptResult,
    "readback": s.ReadbackResponse,
}

_TS_HEADER = (
    "// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP\n"
    "// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction\n"
    "// Generated by backend/tests/fixtures/trainer/generate_api_fixtures.py from the\n"
    "// backend Pydantic schemas. Do not edit by hand: change the generator and rerun it.\n"
)


def render_json(model: BaseModel) -> str:
    """The JSON text of one fixture, as written to disk."""
    return json.dumps(model.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n"


def ts_file_name(name: str) -> str:
    """``attempt_pass`` -> ``attemptPass.ts``."""
    head, *rest = name.split("_")
    return head + "".join(part.capitalize() for part in rest) + ".ts"


def render_ts(name: str, model: BaseModel) -> str:
    """The TypeScript module of one fixture, as written to disk."""
    _builder, export_name, type_name = FIXTURES[name]
    body = json.dumps(model.model_dump(mode="json"), indent=2, ensure_ascii=False)
    return f"{_TS_HEADER}import type {{ {type_name} }} from '../types';\n\nexport const {export_name}: {type_name} = {body};\n"


def build_all() -> dict[str, BaseModel]:
    """Every fixture, keyed by name."""
    return {name: builder() for name, (builder, _e, _t) in FIXTURES.items()}  # type: ignore[operator]


def expected_files() -> dict[Path, str]:
    """Every file the generator owns, with the exact text it must hold."""
    files: dict[Path, str] = {}
    for name, model in build_all().items():
        files[API_DIR / f"{name}.json"] = render_json(model)
        files[FRONTEND_FIXTURES_DIR / ts_file_name(name)] = render_ts(name, model)
    return files


def main() -> None:
    """Write every fixture file."""
    for path, text in expected_files().items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
        print(f"wrote {path.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
