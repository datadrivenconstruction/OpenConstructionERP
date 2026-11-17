# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Unit tests for the pure MSPDI (MS Project XML) reader and its round trip with the writer.

No database and no app: the reader turns bytes into plain records, the writer
turns plain records into bytes, and the two must agree on hierarchy, links,
dates, calendars, baselines and percent complete.
"""

from __future__ import annotations

import pytest

from app.modules.schedule.mspdi_export import (
    MspdiActivity,
    MspdiCalendar,
    MspdiPredecessor,
    MspdiProject,
    build_mspdi_xml,
)
from app.modules.schedule.mspdi_import import MspdiReadError, parse_mspdi

# A 7-hour day (420 minutes), a Monday-to-Friday calendar with one holiday,
# a summary with two children, every link type, a negative lag and a baseline.
SAMPLE = b"""<?xml version="1.0" encoding="UTF-8"?>
<Project xmlns="http://schemas.microsoft.com/project">
  <Name>Tower A</Name>
  <MinutesPerDay>420</MinutesPerDay>
  <CalendarUID>1</CalendarUID>
  <Calendars>
    <Calendar><UID>1</UID><Name>Site week</Name><IsBaseCalendar>1</IsBaseCalendar>
      <WeekDays>
        <WeekDay><DayType>1</DayType><DayWorking>0</DayWorking></WeekDay>
        <WeekDay><DayType>2</DayType><DayWorking>1</DayWorking></WeekDay>
        <WeekDay><DayType>3</DayType><DayWorking>1</DayWorking></WeekDay>
        <WeekDay><DayType>4</DayType><DayWorking>1</DayWorking></WeekDay>
        <WeekDay><DayType>5</DayType><DayWorking>1</DayWorking></WeekDay>
        <WeekDay><DayType>6</DayType><DayWorking>1</DayWorking></WeekDay>
        <WeekDay><DayType>7</DayType><DayWorking>0</DayWorking></WeekDay>
        <WeekDay><DayType>0</DayType><DayWorking>0</DayWorking>
          <TimePeriod><FromDate>2026-05-14T00:00:00</FromDate><ToDate>2026-05-14T23:59:00</ToDate></TimePeriod>
        </WeekDay>
      </WeekDays>
    </Calendar>
  </Calendars>
  <Tasks>
    <Task><UID>0</UID><Name>Tower A</Name><OutlineLevel>0</OutlineLevel><Summary>1</Summary></Task>
    <Task><UID>1</UID><Name>Shell</Name><WBS>1</WBS><OutlineLevel>1</OutlineLevel><Summary>1</Summary>
      <Start>2026-05-04T08:00:00</Start><Finish>2026-05-15T17:00:00</Finish><Duration>PT70H0M0S</Duration></Task>
    <Task><UID>2</UID><Name>Walls</Name><WBS>1.1</WBS><OutlineLevel>2</OutlineLevel>
      <Start>2026-05-04T08:00:00</Start><Finish>2026-05-08T17:00:00</Finish><Duration>PT35H0M0S</Duration>
      <PercentComplete>40</PercentComplete>
      <Baseline><Number>0</Number><Start>2026-05-04T08:00:00</Start><Finish>2026-05-07T17:00:00</Finish>
        <Duration>PT28H0M0S</Duration></Baseline></Task>
    <Task><UID>3</UID><Name>Roof</Name><WBS>1.2</WBS><OutlineLevel>2</OutlineLevel>
      <Start>2026-05-11T08:00:00</Start><Finish>2026-05-15T17:00:00</Finish><Duration>PT28H0M0S</Duration>
      <PredecessorLink><PredecessorUID>2</PredecessorUID><Type>1</Type><LinkLag>4200</LinkLag></PredecessorLink></Task>
    <Task><UID>4</UID><Name>Handover</Name><WBS>2</WBS><OutlineLevel>1</OutlineLevel><Milestone>1</Milestone>
      <Start>2026-05-18T08:00:00</Start><Finish>2026-05-18T08:00:00</Finish><Duration>PT0H0M0S</Duration>
      <PredecessorLink><PredecessorUID>3</PredecessorUID><Type>0</Type></PredecessorLink>
      <PredecessorLink><PredecessorUID>2</PredecessorUID><Type>3</Type><LinkLag>-8400</LinkLag></PredecessorLink></Task>
  </Tasks>
</Project>
"""


def _by_uid(doc):
    return {t.uid: t for t in doc.tasks}


def test_hierarchy_comes_from_outline_levels_and_root_is_skipped() -> None:
    doc = parse_mspdi(SAMPLE)
    tasks = _by_uid(doc)
    assert set(tasks) == {"1", "2", "3", "4"}
    assert tasks["1"].parent_uid is None
    assert tasks["2"].parent_uid == "1"
    assert tasks["3"].parent_uid == "1"
    assert tasks["4"].parent_uid is None
    assert tasks["1"].activity_type == "summary"
    assert tasks["4"].activity_type == "milestone"
    assert tasks["2"].wbs == "1.1"


def test_durations_and_lags_use_the_files_minutes_per_day() -> None:
    doc = parse_mspdi(SAMPLE)
    tasks = _by_uid(doc)
    assert doc.minutes_per_day == 420
    assert tasks["2"].duration_days == 5  # 35 h at 7 h/day
    assert tasks["3"].duration_days == 4
    links = {(lk.predecessor_uid, lk.successor_uid, lk.relationship_type): lk.lag_days for lk in doc.links}
    assert links[("2", "3", "FS")] == 1  # 4200 tenths of a minute = 420 min = one 7 h day
    assert links[("2", "4", "SS")] == -2
    assert links[("3", "4", "FF")] == 0


def test_dates_percent_and_baseline_are_read() -> None:
    tasks = _by_uid(parse_mspdi(SAMPLE))
    walls = tasks["2"]
    assert (walls.start, walls.finish) == ("2026-05-04", "2026-05-08")
    assert walls.percent_complete == 40.0
    assert walls.baseline_start == "2026-05-04"
    assert walls.baseline_finish == "2026-05-07"
    assert walls.baseline_duration_days == 4
    assert tasks["3"].baseline_start is None


def test_calendar_working_days_and_exceptions() -> None:
    doc = parse_mspdi(SAMPLE)
    assert len(doc.calendars) == 1
    cal = doc.calendars[0]
    assert cal.uid == "1" and cal.name == "Site week"
    assert cal.work_days == [0, 1, 2, 3, 4]  # Monday..Friday, Python weekday numbers
    assert cal.holidays == ["2026-05-14"]
    assert cal.hours_per_day == 7.0
    assert doc.project_calendar_uid == "1"


def test_clean_file_has_no_issues() -> None:
    assert parse_mspdi(SAMPLE).issues == []


def test_hostile_or_broken_xml_is_refused() -> None:
    with pytest.raises(MspdiReadError) as bad:
        parse_mspdi(b"<Project><Tasks>")
    assert bad.value.code == "invalid_xml"
    evil = b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY e SYSTEM "file:///etc/passwd">]><Project>&e;</Project>'
    with pytest.raises(MspdiReadError) as hostile:
        parse_mspdi(evil)
    assert hostile.value.code == "rejected"
    with pytest.raises(MspdiReadError) as empty:
        parse_mspdi(b'<Project xmlns="http://schemas.microsoft.com/project"><Name>x</Name></Project>')
    assert empty.value.code == "no_tasks"


def _issue_codes(doc) -> set[tuple[str, str]]:
    return {(i.code, i.ref) for i in doc.issues}


def test_problems_are_reported_not_repaired_silently() -> None:
    raw = b"""<Project xmlns="http://schemas.microsoft.com/project"><Tasks>
      <Task><UID>1</UID><Name>No dates</Name><OutlineLevel>1</OutlineLevel></Task>
      <Task><UID>2</UID><Name>Backwards</Name><OutlineLevel>1</OutlineLevel>
        <Start>2026-05-08T08:00:00</Start><Finish>2026-05-04T17:00:00</Finish></Task>
      <Task><UID>2</UID><Name>Twin</Name><OutlineLevel>1</OutlineLevel>
        <Start>2026-05-04T08:00:00</Start><Finish>2026-05-04T17:00:00</Finish></Task>
      <Task><UID>3</UID><Name>Jump</Name><OutlineLevel>3</OutlineLevel><PercentComplete>140</PercentComplete>
        <Start>2026-05-04T08:00:00</Start><Finish>2026-05-05T17:00:00</Finish>
        <PredecessorLink><PredecessorUID>99</PredecessorUID></PredecessorLink>
        <PredecessorLink><PredecessorUID>3</PredecessorUID></PredecessorLink>
        <PredecessorLink><PredecessorUID>1</PredecessorUID><Type>7</Type></PredecessorLink>
        <PredecessorLink><PredecessorUID>1</PredecessorUID><Type>3</Type></PredecessorLink></Task>
    </Tasks></Project>"""
    doc = parse_mspdi(raw)
    codes = _issue_codes(doc)
    assert ("missing_dates", "1") in codes
    assert ("finish_before_start", "2") in codes
    assert ("duplicate_uid", "2") in codes
    assert ("outline_gap", "3") in codes
    assert ("percent_out_of_range", "3") in codes
    assert ("dangling_link", "3") in codes
    assert ("self_link", "3") in codes
    assert ("unknown_link_type", "3") in codes
    assert ("duplicate_link", "3") in codes  # one link per pair: the first one is kept
    # Nothing invented: the undated task keeps empty dates, the duplicate is dropped.
    tasks = _by_uid(doc)
    assert tasks["1"].start == "" and tasks["1"].finish == ""
    assert tasks["2"].name == "Backwards"
    assert tasks["3"].percent_complete == 100.0
    # A level-3 task under a level-1 sibling hangs on the nearest open parent.
    assert tasks["3"].parent_uid == "2"
    assert [(lk.predecessor_uid, lk.relationship_type) for lk in doc.links] == [("1", "FS")]
    severities = {i.code: i.severity for i in doc.issues}
    assert severities["missing_dates"] == "error"
    assert severities["duplicate_uid"] == "error"
    assert severities["dangling_link"] == "warning"


def test_calendar_without_working_days_is_flagged() -> None:
    raw = b"""<Project xmlns="http://schemas.microsoft.com/project">
      <Calendars><Calendar><UID>5</UID><Name>Closed</Name><WeekDays>
        <WeekDay><DayType>2</DayType><DayWorking>0</DayWorking></WeekDay>
      </WeekDays></Calendar></Calendars>
      <Tasks><Task><UID>1</UID><Name>A</Name><Start>2026-05-04T08:00:00</Start>
        <Finish>2026-05-04T17:00:00</Finish></Task></Tasks></Project>"""
    doc = parse_mspdi(raw)
    assert ("calendar_no_work_days", "calendar:5") in _issue_codes(doc)


def test_export_then_import_keeps_tasks_links_dates_calendar_and_baseline() -> None:
    project = MspdiProject(
        name="Round trip",
        hours_per_day=8,
        calendars=[MspdiCalendar(uid=1, name="Mon-Fri", work_days=[0, 1, 2, 3, 4], holidays=["2026-05-25"])],
        project_calendar_uid=1,
        activities=[
            MspdiActivity(
                uid=1,
                name="Shell",
                start_date="2026-05-04",
                end_date="2026-05-15",
                duration_days=10,
                activity_type="summary",
                wbs_code="1",
                outline_level=1,
            ),
            MspdiActivity(
                uid=2,
                name="Walls",
                start_date="2026-05-04",
                end_date="2026-05-08",
                duration_days=5,
                progress_pct=40,
                wbs_code="1.1",
                outline_level=2,
                baseline_start="2026-05-04",
                baseline_end="2026-05-07",
                baseline_duration_days=4,
            ),
            MspdiActivity(
                uid=3,
                name="Roof",
                start_date="2026-05-11",
                end_date="2026-05-15",
                duration_days=5,
                wbs_code="1.2",
                outline_level=2,
                calendar_uid=1,
            ),
            MspdiActivity(
                uid=4,
                name="Handover",
                start_date="2026-05-18",
                end_date="2026-05-18",
                duration_days=0,
                activity_type="milestone",
                wbs_code="2",
                outline_level=1,
            ),
        ],
        predecessors_by_uid={
            3: [MspdiPredecessor(predecessor_uid=2, relationship_type="FS", lag_days=1)],
            4: [
                MspdiPredecessor(predecessor_uid=3, relationship_type="FF"),
                MspdiPredecessor(predecessor_uid=2, relationship_type="SS", lag_days=-2),
            ],
        },
    )
    doc = parse_mspdi(build_mspdi_xml(project).encode("utf-8"))
    assert doc.issues == []
    tasks = _by_uid(doc)
    assert [(t.uid, t.name, t.wbs, t.parent_uid, t.start, t.finish, t.duration_days) for t in doc.tasks] == [
        ("1", "Shell", "1", None, "2026-05-04", "2026-05-15", 10),
        ("2", "Walls", "1.1", "1", "2026-05-04", "2026-05-08", 5),
        ("3", "Roof", "1.2", "1", "2026-05-11", "2026-05-15", 5),
        ("4", "Handover", "2", None, "2026-05-18", "2026-05-18", 0),
    ]
    assert tasks["1"].activity_type == "summary"
    assert tasks["4"].activity_type == "milestone"
    assert tasks["2"].percent_complete == 40.0
    assert (tasks["2"].baseline_start, tasks["2"].baseline_finish, tasks["2"].baseline_duration_days) == (
        "2026-05-04",
        "2026-05-07",
        4,
    )
    assert tasks["3"].calendar_uid == "1"
    assert sorted((lk.predecessor_uid, lk.successor_uid, lk.relationship_type, lk.lag_days) for lk in doc.links) == [
        ("2", "3", "FS", 1),
        ("2", "4", "SS", -2),
        ("3", "4", "FF", 0),
    ]
    assert [(c.uid, c.name, c.work_days, c.holidays) for c in doc.calendars] == [
        ("1", "Mon-Fri", [0, 1, 2, 3, 4], ["2026-05-25"])
    ]
    assert doc.project_calendar_uid == "1"


def test_tree_order_puts_parents_first_with_their_depth() -> None:
    from types import SimpleNamespace

    from app.modules.schedule.mspdi_export_context import tree_order

    child = SimpleNamespace(id="c", parent_id="p")
    grandchild = SimpleNamespace(id="g", parent_id="c")
    parent = SimpleNamespace(id="p", parent_id=None)
    orphan = SimpleNamespace(id="o", parent_id="gone")
    loop_a = SimpleNamespace(id="x", parent_id="y")
    loop_b = SimpleNamespace(id="y", parent_id="x")
    ordered = tree_order([grandchild, child, orphan, parent, loop_a, loop_b])
    assert [(a.id, level) for a, level in ordered] == [
        ("o", 1),
        ("p", 1),
        ("c", 2),
        ("g", 3),
        ("x", 1),
        ("y", 1),
    ]
