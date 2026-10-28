# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Regression tests for the ReDoS input caps added in v11.17.0.

Three server-side regexes take caller-influenced strings and are super-linear
in shape, so a crafted long value could stall a request (stdlib ``re`` has no
timeout). Each call site now bounds the input length before the match runs.
These tests feed each parser a pathological input and assert it (a) still
returns the correct result and (b) completes near-instantly, which only holds
because the length cap keeps the regex off the unbounded string.
"""

from __future__ import annotations

import time
from decimal import Decimal

from app.modules.bim_hub.smart_views import OP_REGEX, _eval_leaf
from app.modules.change_intelligence.intake_normalizer import parse_duration_days

# Generous wall-clock ceiling. The bounded parsers finish in well under a
# millisecond; an unbounded backtracker on these inputs would run for many
# seconds. One second leaves a huge margin so the check never flakes on slow CI.
_MAX_SECONDS = 1.0


def test_parse_duration_days_caps_pathological_input() -> None:
    # A number, a long whitespace run, then a non-matching tail: the shape that
    # makes ``^\s*(num)\s*(word)?\s*$`` backtrack polynomially without the cap.
    evil = "5" + " " * 200_000 + "!"
    start = time.perf_counter()
    days, warning = parse_duration_days(evil)
    elapsed = time.perf_counter() - start
    assert elapsed < _MAX_SECONDS
    # It returns a clean 2-tuple rather than hanging - that is the invariant.
    assert isinstance(days, Decimal) or days is None
    assert isinstance(warning, str) or warning is None


def test_parse_duration_days_normal_values_unchanged() -> None:
    assert parse_duration_days("3")[0] == Decimal("3")
    assert parse_duration_days("1,5 days")[0] == Decimal("1.5")
    assert parse_duration_days("2 weeks")[0] == Decimal("14")
    assert parse_duration_days("")[0] is None


def test_smart_view_regex_rejects_oversized_pattern() -> None:
    # A user-supplied filter pattern over the 1000-char bound is refused before
    # any matching happens, so a catastrophic pattern cannot even start.
    element = {"properties": {"category": "Steel Beam"}}
    leaf = {"field": "category", "op": OP_REGEX, "value": "a" * 2_000}
    start = time.perf_counter()
    result = _eval_leaf(element, leaf)
    elapsed = time.perf_counter() - start
    assert result is False
    assert elapsed < _MAX_SECONDS


def test_smart_view_regex_still_matches_normal_pattern() -> None:
    element = {"properties": {"category": "Steel Beam"}}
    assert _eval_leaf(element, {"field": "category", "op": OP_REGEX, "value": "beam"}) is True
    assert _eval_leaf(element, {"field": "category", "op": OP_REGEX, "value": "concrete"}) is False


def test_smart_view_regex_subject_is_length_bounded() -> None:
    # A huge subject with an anchored pattern: the [:10000] subject cap keeps the
    # match off an unbounded string. The "beam" tail sits past the cap, so the
    # anchored pattern no longer matches the truncated subject - proof the cap
    # is active, and it completes instantly either way.
    element = {"properties": {"category": "x" * 500_000 + "beam"}}
    leaf = {"field": "category", "op": OP_REGEX, "value": "beam$"}
    start = time.perf_counter()
    result = _eval_leaf(element, leaf)
    elapsed = time.perf_counter() - start
    assert result is False
    assert elapsed < _MAX_SECONDS


def test_email_regex_bounded_input_is_fast() -> None:
    # The email handler caps the recipient at 254 chars (RFC 5321) before the
    # two greedy character classes ever see it. A worst-case no-at-no-dot string
    # at that length still classifies instantly.
    from app.modules.property_dev.router import _EMAIL_RE

    evil = "a" * 254
    start = time.perf_counter()
    match = _EMAIL_RE.match(evil)
    elapsed = time.perf_counter() - start
    assert match is None
    assert elapsed < _MAX_SECONDS
    assert _EMAIL_RE.match("dev@example.com") is not None
