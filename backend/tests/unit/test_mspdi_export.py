# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the pure MSPDI (MS Project XML) exporter.

Runs anywhere - no DB, no app import. Builds an XML document and parses it
back to assert the structure round-trips with the MSP-XML importer's
assumptions (8h day, constraint and relationship code maps, lag in
tenths-of-a-minute).
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

from app.modules.schedule.mspdi_export import (
    MSP_NS,
    MspdiActivity,
    MspdiPredecessor,
    MspdiProject,
    build_mspdi_xml,
)

_NS = f"{{{MSP_NS}}}"


def _parse(xml_str: str) -> ET.Element:
    return ET.fromstring(xml_str)


def _tasks(root: ET.Element) -> list[ET.Element]:
    tasks_el = root.find(f"{_NS}Tasks")
    assert tasks_el is not None
    return tasks_el.findall(f"{_NS}Task")


def _text(task: ET.Element, tag: str) -> str | None:
    el = task.find(f"{_NS}{tag}")
    return el.text if el is not None else None


def _project(**kwargs: object) -> MspdiProject:
    base = MspdiProject(
        name="Tower A",
        activities=[
            MspdiActivity(
                uid=1,
                name="Mobilise",
                start_date="2026-05-01",
                end_date="2026-05-05",
                duration_days=5,
                progress_pct=40.0,
            ),
            MspdiActivity(
                uid=2,
                name="Handover",
                start_date="2026-06-01",
                end_date="2026-06-01",
                duration_days=0,
                activity_type="milestone",
            ),
        ],
        predecessors_by_uid={2: [MspdiPredecessor(predecessor_uid=1, lag_days=2)]},
    )
    for k, v in kwargs.items():
        setattr(base, k, v)
    return base


def test_document_is_valid_xml_in_msp_namespace() -> None:
    root = _parse(build_mspdi_xml(_project()))
    assert root.tag == f"{_NS}Project"
    assert _text_from(root, "Name") == "Tower A"


def _text_from(root: ET.Element, tag: str) -> str | None:
    el = root.find(f"{_NS}{tag}")
    return el.text if el is not None else None


def test_task_fields_render() -> None:
    tasks = _tasks(_parse(build_mspdi_xml(_project())))
    assert len(tasks) == 2
    first = tasks[0]
    assert _text(first, "UID") == "1"
    assert _text(first, "Name") == "Mobilise"
    # 5 days at 8h/day -> PT40H0M0S.
    assert _text(first, "Duration") == "PT40H0M0S"
    assert _text(first, "PercentComplete") == "40"
    assert _text(first, "Milestone") == "0"
    # Start normalises to an MSP datetime.
    assert _text(first, "Start") == "2026-05-01T08:00:00"


def test_milestone_flag_and_zero_duration() -> None:
    tasks = _tasks(_parse(build_mspdi_xml(_project())))
    handover = tasks[1]
    assert _text(handover, "Milestone") == "1"
    assert _text(handover, "Duration") == "PT0H0M0S"


def test_predecessor_link_type_and_lag() -> None:
    tasks = _tasks(_parse(build_mspdi_xml(_project())))
    handover = tasks[1]
    link = handover.find(f"{_NS}PredecessorLink")
    assert link is not None
    assert link.find(f"{_NS}PredecessorUID").text == "1"  # type: ignore[union-attr]
    # Default FS -> code 1.
    assert link.find(f"{_NS}Type").text == "1"  # type: ignore[union-attr]
    # 2 days lag -> 2 * 8 * 60 * 10 = 9600 tenths-of-a-minute.
    assert link.find(f"{_NS}LinkLag").text == "9600"  # type: ignore[union-attr]


def test_relationship_type_codes() -> None:
    proj = _project(predecessors_by_uid={2: [MspdiPredecessor(predecessor_uid=1, relationship_type="SS")]})
    tasks = _tasks(_parse(build_mspdi_xml(proj)))
    link = tasks[1].find(f"{_NS}PredecessorLink")
    assert link is not None
    assert link.find(f"{_NS}Type").text == "3"  # SS -> 3  # type: ignore[union-attr]


def test_constraint_maps_to_msp_code() -> None:
    proj = _project(
        activities=[
            MspdiActivity(
                uid=1,
                name="Fixed start",
                start_date="2026-05-01",
                end_date="2026-05-02",
                duration_days=1,
                constraint_type="must_start_on",
                constraint_date="2026-05-01",
            )
        ],
        predecessors_by_uid={},
    )
    task = _tasks(_parse(build_mspdi_xml(proj)))[0]
    assert _text(task, "ConstraintType") == "1"  # must_start_on -> 1
    assert _text(task, "ConstraintDate") == "2026-05-01T08:00:00"


def test_self_link_is_dropped_is_callers_job_but_builder_emits_given() -> None:
    # The builder emits exactly the links it is given; de-dup / self-link
    # filtering happens in the router. With no predecessors, no links render.
    proj = _project(predecessors_by_uid={})
    tasks = _tasks(_parse(build_mspdi_xml(proj)))
    assert tasks[1].find(f"{_NS}PredecessorLink") is None
