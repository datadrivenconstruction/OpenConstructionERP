"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the claims-grade quality-report assembly (cpm_report).

Pure (stdlib only) - exercises the full ``quality_report`` aggregation over a
small hand-built network so the wiring between ``compute_cpm`` and every
claims-grade post-processor is covered without the app / DB barrier.
"""

from __future__ import annotations

from app.modules.schedule_advanced.cpm import Activity, QAOptions, TaskNetwork
from app.modules.schedule_advanced.cpm_report import quality_report


def _diamond() -> TaskNetwork:
    """A -> B -> C is the driving chain (len 9); A -> D is a float path (float 5)."""
    return TaskNetwork(
        [
            Activity(id="A", duration=3, predecessors=[]),
            Activity(id="B", duration=2, predecessors=[("A", "FS", 0)]),
            Activity(id="C", duration=4, predecessors=[("B", "FS", 0)]),
            Activity(id="D", duration=1, predecessors=[("A", "FS", 0)]),
        ]
    )


def test_quality_report_core_metrics() -> None:
    report = quality_report(_diamond())

    assert report["project_finish_workday"] == 9
    assert report["num_activities"] == 4
    assert report["num_critical"] == 3  # A, B, C
    assert report["longest_path"] == ["A", "B", "C"]
    assert report["longest_path_length_days"] == 9
    assert report["critical_activity_ids"] == ["A", "B", "C"]


def test_float_paths_driving_first() -> None:
    report = quality_report(_diamond())
    fpaths = report["float_paths"]

    assert fpaths, "expected at least the driving float path"
    assert fpaths[0]["index"] == 0
    assert fpaths[0]["activity_ids"] == ["A", "B", "C"]
    assert fpaths[0]["relative_float"] == 0
    # Relative float is non-decreasing across the ranked decomposition.
    rel = [p["relative_float"] for p in fpaths]
    assert rel == sorted(rel)


def test_qa_log_flags_open_ends() -> None:
    report = quality_report(_diamond())
    codes = {(f["activity_id"], f["code"]) for f in report["qa_log"]}

    # A is an open start; C and D are open finishes.
    assert ("A", "OPEN_START") in codes
    assert ("C", "OPEN_FINISH") in codes
    assert ("D", "OPEN_FINISH") in codes


def test_qa_log_milestones_suppressed() -> None:
    opts = QAOptions(start_milestones={"A"}, finish_milestones={"C", "D"})
    report = quality_report(_diamond(), options=opts)
    codes = {f["code"] for f in report["qa_log"]}

    assert "OPEN_START" not in codes
    assert "OPEN_FINISH" not in codes


def test_explanations_cover_longest_path() -> None:
    report = quality_report(_diamond())
    expl = {e["activity_id"]: e for e in report["explanations"]}

    assert set(expl) == {"A", "B", "C"}
    # A is driven from project start; B is driven by A.
    assert "project start" in expl["A"]["why_critical"].lower()
    assert "driven by A" in expl["B"]["why_critical"]
    for e in expl.values():
        assert e["float_explanation"]


def test_report_is_order_independent() -> None:
    net = _diamond()
    shuffled = TaskNetwork(list(reversed(net.activities)))
    assert quality_report(shuffled) == quality_report(net)
