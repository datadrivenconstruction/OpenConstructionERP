"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Database-free tests for project_intelligence presentation helpers."""

from app.modules.project_intelligence.scorer import (
    SEVERITIES,
    CriticalGap,
    ProjectScore,
    gap_counts,
    next_actions,
    score_summary,
    severity_label,
)


def _gap(gid: str, severity: str, action_id: str | None = None) -> CriticalGap:
    return CriticalGap(
        id=gid,
        domain="boq",
        severity=severity,
        title=gid,
        description="",
        impact="",
        action_id=action_id,
    )


def _score(overall: float, grade: str, gaps: list[CriticalGap]) -> ProjectScore:
    return ProjectScore(overall=overall, overall_grade=grade, critical_gaps=gaps)


# ---- severity_label --------------------------------------------------------
def test_severity_label_localized_with_fallback():
    assert severity_label("blocker", "en") == "blocker"
    assert severity_label("blocker", "de") == "Blocker"
    assert severity_label("critical", "ru") == "критично"
    # Unknown language falls back to English, unknown severity to its key.
    assert severity_label("warning", "xx") == "warning"
    assert severity_label("nope") == "nope"


# ---- gap_counts ------------------------------------------------------------
def test_gap_counts_zero_filled_and_ordered():
    score = _score(50.0, "C", [_gap("a", "blocker"), _gap("b", "critical"), _gap("c", "blocker")])
    counts = gap_counts(score)
    assert list(counts.keys()) == list(SEVERITIES)
    assert counts == {"blocker": 2, "critical": 1, "warning": 0, "suggestion": 0}


def test_gap_counts_empty_score():
    assert gap_counts(_score(100.0, "A", [])) == {
        "blocker": 0,
        "critical": 0,
        "warning": 0,
        "suggestion": 0,
    }


# ---- next_actions ----------------------------------------------------------
def test_next_actions_keeps_only_actionable_in_order():
    gaps = [
        _gap("blk", "blocker", action_id="action_create_boq_ai"),
        _gap("crit_no_action", "critical", action_id=None),
        _gap("crit", "critical", action_id="action_run_validation"),
    ]
    actions = next_actions(_score(40.0, "D", gaps))
    assert [g.id for g in actions] == ["blk", "crit"]
    # limit caps the list.
    assert [g.id for g in next_actions(_score(40.0, "D", gaps), limit=1)] == ["blk"]
    assert next_actions(_score(40.0, "D", gaps), limit=0) == []


# ---- score_summary ---------------------------------------------------------
def test_score_summary_clean_project():
    summary = score_summary(_score(92.0, "A", []))
    assert "grade A (92.0/100)" in summary
    assert "No blocking or critical gaps" in summary


def test_score_summary_counts_and_pluralizes():
    gaps = [_gap("a", "blocker"), _gap("b", "critical"), _gap("c", "critical")]
    summary = score_summary(_score(45.0, "D", gaps))
    assert "1 blocker and 2 critical gaps need attention" in summary
    # Singular critical gap.
    one = score_summary(_score(60.0, "C", [_gap("x", "critical")]))
    assert "0 blockers and 1 critical gap need attention" in one


def test_helpers_produce_no_em_dashes_or_smart_quotes():
    banned = "".join(
        map(
            chr,
            (
                0x2014,
                0x2013,
                0x2018,
                0x2019,
                0x201C,
                0x201D,
            ),
        )
    )
    score = _score(45.0, "D", [_gap("a", "blocker")])
    blobs = [score_summary(score)]
    blobs += [severity_label(s, lang) for s in SEVERITIES for lang in ("en", "de", "ru")]
    for blob in blobs:
        assert not any(ch in blob for ch in banned), repr(blob)
