"""‌⁠‍BIMElementRule — per-element validation rule for BIM models.

A :class:`BIMElementRule` is a plain Python class (not a database row) that
describes a single validation check to run against every
``BIMElement`` in a model. The rule consists of three pieces:

* ``element_filter`` — cheap dict-based filter that decides whether an
  element is in scope for this rule (by element_type prefix, discipline,
  storey, category, ...).
* ``property_checks`` — list of checks against ``BIMElement.properties``
  (the free-form JSON blob of IFC/Revit attributes).
* ``quantity_checks`` — list of checks against ``BIMElement.quantities``
  (area_m2, volume_m3, thickness_m, ...).

The rule is stateless and deterministic. Running it against an element
returns a list of per-element :class:`BIMElementRuleResult` entries — one
per failing check (passing checks contribute to the pass count but do not
emit result rows, so large clean models stay cheap).

This module intentionally does NOT touch the engine's global
``rule_registry`` — BIM element rules are a separate rule shape (operate
over individual ORM rows rather than a flat data dict) and are driven by
:class:`app.modules.validation.bim_validation_service.BIMValidationService`
directly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

Severity = Literal["error", "warning", "info"]


# ── Result shape ─────────────────────────────────────────────────────────────


@dataclass
class BIMElementRuleResult:
    """‌⁠‍Single per-element result emitted by a :class:`BIMElementRule`."""

    rule_id: str
    rule_name: str
    severity: Severity
    passed: bool
    message: str
    element_id: str
    element_name: str | None = None
    element_type: str | None = None
    details: dict[str, Any] = field(default_factory=dict)


# ── Rule class ───────────────────────────────────────────────────────────────


@dataclass
class BIMElementRule:
    """‌⁠‍Declarative per-element validation rule.

    Attributes:
        rule_id: Unique rule identifier (e.g. ``"bim.wall.has_thickness"``).
        name: Human-readable rule name.
        severity: ``"error"`` | ``"warning"`` | ``"info"``.
        description: Optional long-form rationale shown in rule catalogues.
        element_filter: Dict describing which elements this rule applies to.
            Supported keys (all optional, all ANDed together):

            * ``element_type`` — exact match (case-insensitive)
            * ``element_type_startswith`` — prefix match (case-insensitive),
              may be a single string or list of prefixes
            * ``element_type_in`` — list of exact matches (case-insensitive)
            * ``discipline`` — exact match (case-insensitive)
            * ``storey`` — exact match
            * ``category`` — match against ``properties["category"]``

        property_checks: List of property-level checks. Each entry is a dict
            with at least ``property``. Supported keys:

            * ``property`` — dotted path inside ``element.properties``
            * ``must_exist`` — property must be present and non-empty
            * ``must_equal`` — property must equal this value
            * ``must_be_in`` — property must be in this list
            * ``must_match`` — property must match this regex (str)

        quantity_checks: List of quantity-level checks. Each entry is a dict
            with at least ``quantity``. Supported keys:

            * ``quantity`` — dotted path inside ``element.quantities``
            * ``must_exist`` — quantity key must be present and non-null
            * ``must_be_gt`` — numeric value must be > threshold
            * ``must_be_gte`` — numeric value must be >= threshold
            * ``must_be_lt`` — numeric value must be < threshold
            * ``must_be_lte`` — numeric value must be <= threshold

        require_any_of_properties: Optional list of property paths where at
            least ONE must exist (e.g. door width may live in either
            ``properties`` or ``quantities``).
        require_any_of_quantities: Same, but for quantities.
        require_any_positive_quantity: Optional list of quantity paths where
            at least ONE must be present AND a number strictly greater than
            zero. Use this (not ``require_any_of_quantities``) when the rule
            name/contract promises a *positive* value — e.g. "wall thickness
            > 0". Presence-only checks let a ``thickness_m = 0`` (or the
            non-numeric string ``"0,24"``) silently PASS (E-BIM-010).
        require_storey: If True, the element must have a non-empty ``storey``.
        require_name: If True, the element must have a real ``name`` (not
            ``None``, ``""``, or the literal string ``"None"``).
    """

    rule_id: str
    name: str
    severity: Severity
    description: str = ""
    element_filter: dict[str, Any] = field(default_factory=dict)
    property_checks: list[dict[str, Any]] = field(default_factory=list)
    quantity_checks: list[dict[str, Any]] = field(default_factory=list)
    require_any_of_properties: list[str] = field(default_factory=list)
    require_any_of_quantities: list[str] = field(default_factory=list)
    require_any_positive_quantity: list[str] = field(default_factory=list)
    require_storey: bool = False
    require_name: bool = False
    enabled: bool = True

    # ── Matching ────────────────────────────────────────────────────────

    def matches(self, element: Any) -> bool:
        """Return True if ``element`` is in scope for this rule."""
        f = self.element_filter
        if not f:
            return True

        etype = (getattr(element, "element_type", None) or "").strip()
        etype_lc = etype.lower()

        if "element_type" in f:
            if etype_lc != str(f["element_type"]).lower():
                return False

        if "element_type_startswith" in f:
            raw = f["element_type_startswith"]
            prefixes = [raw] if isinstance(raw, str) else list(raw or [])
            if not any(etype_lc.startswith(str(p).lower()) for p in prefixes):
                return False

        if "element_type_in" in f:
            allowed = {str(x).lower() for x in f["element_type_in"] or []}
            if etype_lc not in allowed:
                return False

        if "discipline" in f:
            disc = (getattr(element, "discipline", None) or "").lower()
            if disc != str(f["discipline"]).lower():
                return False

        if "storey" in f:
            if (getattr(element, "storey", None) or "") != f["storey"]:
                return False

        if "category" in f:
            props = getattr(element, "properties", None) or {}
            if str(props.get("category", "")).lower() != str(f["category"]).lower():
                return False

        return True

    # ── Evaluation ──────────────────────────────────────────────────────

    def evaluate(self, element: Any) -> list[BIMElementRuleResult]:
        """Run all checks against ``element`` and return failing results.

        Only failing checks emit result rows. A fully passing element
        produces zero entries — callers track the pass count externally.
        """
        results: list[BIMElementRuleResult] = []
        props: dict[str, Any] = getattr(element, "properties", None) or {}
        quants: dict[str, Any] = getattr(element, "quantities", None) or {}

        def _emit(message: str, details: dict[str, Any] | None = None) -> None:
            results.append(
                BIMElementRuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    passed=False,
                    message=message,
                    element_id=str(getattr(element, "id", "")),
                    element_name=getattr(element, "name", None),
                    element_type=getattr(element, "element_type", None),
                    details=details or {},
                )
            )

        # Storey requirement
        if self.require_storey:
            storey = getattr(element, "storey", None)
            if not storey or not str(storey).strip():
                _emit(
                    f"Element has no storey assigned (rule {self.rule_id})",
                    {"field": "storey"},
                )

        # Name requirement
        if self.require_name:
            nm = getattr(element, "name", None)
            if nm is None or str(nm).strip() in {"", "None"}:
                _emit(
                    f"Element has empty or placeholder name (rule {self.rule_id})",
                    {"field": "name", "value": nm},
                )

        # Property checks
        for check in self.property_checks:
            path = check.get("property")
            if not path:
                continue
            value = _lookup_path(props, path)
            failure = _check_value(value, check)
            if failure is not None:
                _emit(
                    f"Property '{path}' {failure} (rule {self.rule_id})",
                    {"property": path, "value": value, "check": check},
                )

        # Quantity checks
        for check in self.quantity_checks:
            path = check.get("quantity")
            if not path:
                continue
            value = _lookup_path(quants, path)
            failure = _check_value(value, check)
            if failure is not None:
                _emit(
                    f"Quantity '{path}' {failure} (rule {self.rule_id})",
                    {"quantity": path, "value": value, "check": check},
                )

        # any-of-properties
        if self.require_any_of_properties:
            if not any(_has_value(_lookup_path(props, p)) for p in self.require_any_of_properties):
                _emit(
                    "Element missing all of: " + ", ".join(self.require_any_of_properties),
                    {"any_of": self.require_any_of_properties, "scope": "properties"},
                )

        # any-of-quantities
        if self.require_any_of_quantities:
            if not any(_has_value(_lookup_path(quants, p)) for p in self.require_any_of_quantities):
                _emit(
                    "Element missing all of: " + ", ".join(self.require_any_of_quantities),
                    {"any_of": self.require_any_of_quantities, "scope": "quantities"},
                )

        # any-positive-quantity — at least one path must be a number > 0
        # (E-BIM-010). A 0 / "" / non-numeric value does NOT satisfy this.
        if self.require_any_positive_quantity:
            satisfied = False
            for p in self.require_any_positive_quantity:
                num = _coerce_number(_lookup_path(quants, p))
                if num is not None and num > 0:
                    satisfied = True
                    break
            if not satisfied:
                _emit(
                    "Element missing a positive value for any of: " + ", ".join(self.require_any_positive_quantity),
                    {
                        "any_positive_of": self.require_any_positive_quantity,
                        "scope": "quantities",
                    },
                )

        return results


# ── Helpers ──────────────────────────────────────────────────────────────────


def _lookup_path(blob: dict[str, Any], path: str) -> Any:
    """Resolve a dotted path inside ``blob``. Missing keys return ``None``."""
    if not isinstance(blob, dict) or not path:
        return None
    cur: Any = blob
    for part in path.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
        if cur is None:
            return None
    return cur


def _has_value(value: Any) -> bool:
    """Return True if ``value`` is a meaningful (non-empty) value."""
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip() not in {"", "None"}
    if isinstance(value, (list, dict, tuple, set)):
        return len(value) > 0
    return True


_GROUP_WHITESPACE = "   \t"  # space, NBSP, NARROW NBSP, tab


def _coerce_number(value: Any) -> float | None:
    """Coerce a value into a float, tolerant of locale number formats.

    BIM elements imported from German/EU CAD pipelines carry numeric
    properties as strings with comma decimals or trailing units
    (``"0,24"``, ``"1.234,56"``, ``"3.0 m"``). The old ``float(value)``
    rejected all of those and the caller reported a *false* "is not a
    number" ERROR — non-deterministic compliance by locale (E-I18N-017).
    This mirrors the canonical coercion used by the core BOQ rules.

    Returns ``None`` only when the value genuinely is not a number.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        f = float(value)
        return f if f == f and f not in (float("inf"), float("-inf")) else None
    if not isinstance(value, str):
        return None

    text = value.strip()
    if not text:
        return None

    sign = 1.0
    if text[0] in "+-":
        if text[0] == "-":
            sign = -1.0
        text = text[1:].strip()

    import re as _re

    m = _re.match(r"[0-9][0-9.,   \t]*", text)
    if not m:
        return None
    numeric = m.group(0).strip(_GROUP_WHITESPACE)
    for ws in _GROUP_WHITESPACE:
        numeric = numeric.replace(ws, "")
    if not numeric:
        return None

    has_dot = "." in numeric
    has_comma = "," in numeric
    if has_dot and has_comma:
        if numeric.rfind(",") > numeric.rfind("."):
            numeric = numeric.replace(".", "").replace(",", ".")
        else:
            numeric = numeric.replace(",", "")
    elif has_comma:
        if numeric.count(",") > 1:
            numeric = numeric.replace(",", "")
        else:
            numeric = numeric.replace(",", ".")
    elif has_dot and numeric.count(".") > 1:
        numeric = numeric.replace(".", "")

    try:
        return sign * float(numeric)
    except ValueError:
        return None


# ── Safe regex guard (E-SEC-002) ─────────────────────────────────────────────
#
# ``must_match`` patterns come from untrusted IDS / Excel / COBie imports
# (ids_parser stores attacker-controlled ``<xs:pattern value=...>``). Running
# an arbitrary regex with ``re.search`` and no bounds lets a
# catastrophic-backtracking pattern like ``(a+)+$`` peg a CPU core and hang
# the request worker indefinitely.
#
# A single flat heuristic is provably insufficient — every one of the classic
# bypass shapes ( ``((a)+)+$`` nested groups, ``(a+){10,}$`` bounded repeat of
# a quantified group, ``(a|a)*$`` overlapping-alternation group, ``(.*a){30}$``
# bounded repeat of a wildcard group, ``(([a-z])+.)+...`` deeply nested ) slips
# past it. We therefore make the *static structural analyzer* the sound primary
# control: it walks the group/quantifier tree and rejects any construct that
# can yield exponential or super-linear backtracking. As defense-in-depth we
# additionally run the match itself under the third-party ``regex`` engine's
# hard ``timeout=`` wall-clock bound *when that module is importable* — but the
# static gate alone is sufficient, so an environment without ``regex``
# installed is still safe (no hard dependency).

_MAX_PATTERN_LEN = 1_000
_MAX_MATCH_INPUT_LEN = 5_000
# Hard wall-clock ceiling for a single match when an engine-level timeout is
# available. Acceptance bar: no pattern may exceed ~1 s on a 5 000-char input.
_MATCH_TIMEOUT_S = 0.75

# A "repeatable" atom that, when wrapped in an outer quantifier, produces
# catastrophic backtracking: an unbounded quantifier ( + * ) OR a bounded
# repeat with a non-trivial count ( {n} {n,} {n,m} where the upper bound is
# absent or > 1 ).  ``??`` / ``{0,1}`` / ``?`` are linear and excluded.
_INNER_QUANT = __import__("re").compile(
    r"""
    (?:
        [+*]                 # unbounded
      | \{\s*\d*\s*,\s*\d*\s*\}   # {n,} {,m} {n,m} {,}
      | \{\s*[2-9]\d*\s*\}        # {n} with n >= 2
      | \{\s*1\d+\s*\}            # {n} with n >= 10
    )
    \+?\??                   # optional possessive / lazy modifier
    """,
    __import__("re").VERBOSE,
)
# An outer quantifier applied to a group: ``)`` followed by + * {..} (lazy or
# possessive variants included).  ``)?`` alone is linear and excluded.
_OUTER_QUANT_ON_GROUP = __import__("re").compile(
    r"""
    \)                       # close of a group
    (?:
        [+*]
      | \{\s*\d*\s*,\s*\d*\s*\}
      | \{\s*[2-9]\d*\s*\}
      | \{\s*1\d+\s*\}
    )
    \+?\??
    """,
    __import__("re").VERBOSE,
)


def _iter_group_bodies(pattern: str):
    """Yield ``(body, outer_quantified)`` for every parenthesised group.

    ``body`` is the raw text between the group's own parentheses (nested
    groups included verbatim). ``outer_quantified`` is ``True`` when the
    group is immediately followed by a repetition quantifier ( + * {n,} … ),
    i.e. the group as a whole is repeated.
    """
    stack: list[int] = []
    for i, ch in enumerate(pattern):
        if ch == "(" and (i == 0 or pattern[i - 1] != "\\"):
            stack.append(i)
        elif ch == ")" and (i == 0 or pattern[i - 1] != "\\") and stack:
            start = stack.pop()
            body = pattern[start + 1 : i]
            tail = pattern[i:]
            outer_quantified = _OUTER_QUANT_ON_GROUP.match(tail) is not None
            yield body, outer_quantified


def _group_has_overlapping_alternation(body: str) -> bool:
    """A group like ``(a|a)`` / ``(a|ab)`` / ``([a-z]|x)`` whose branches can
    match the same prefix is catastrophic the moment the group is repeated:
    the engine tries every partition of the input across the alternation.

    We conservatively flag *any* top-level alternation inside a repeated group
    (excluding fully-anchored single-char-class branches is not worth the
    complexity — realistic IDS patterns don't repeat an alternation group).
    """
    depth = 0
    for i, ch in enumerate(body):
        if ch == "\\":
            continue
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif ch == "|" and depth == 0:
            return True
    return False


def _is_pattern_safe(pattern: str) -> bool:
    """Reject patterns whose structure permits catastrophic backtracking.

    Rejection criteria (any one fails the pattern):

    * length over ``_MAX_PATTERN_LEN``;
    * a group that is itself repeated (outer ``+ * {n,} {n} {n,m}``) AND whose
      body contains an inner unbounded/bounded quantifier — covers ``(a+)+``,
      ``((a)+)+``, ``(a+){10,}``, ``(.*a){30}``, ``(([a-z])+.)+…`` ;
    * a *repeated group* that contains a top-level alternation — covers
      ``(a|a)*``, ``(a|ab)+`` ;
    * an un-compilable pattern.
    """
    if len(pattern) > _MAX_PATTERN_LEN:
        return False
    for body, outer_quantified in _iter_group_bodies(pattern):
        if not outer_quantified:
            continue
        # The whole group is repeated. Anything non-trivial inside it now
        # multiplies catastrophically.
        if _INNER_QUANT.search(body):
            return False
        if _group_has_overlapping_alternation(body):
            return False
    return True


def _safe_search(pattern: str, value: str) -> bool | None:
    """Bounded, ReDoS-resistant ``re.search``.

    Returns ``True``/``False`` for a normal match result, or ``None`` if the
    pattern was rejected as unsafe / un-compilable (caller treats that as a
    non-match so a hostile rule degrades to a plain failure instead of
    hanging the worker).

    Defense-in-depth: when the third-party ``regex`` module is importable we
    run the match under its hard ``timeout=`` wall-clock bound so that even a
    pattern the static analyzer misclassified cannot peg a core. The static
    gate above is the sound primary control and is sufficient on its own.
    """
    import re as _re

    if not _is_pattern_safe(pattern):
        return None
    # Bound the input too — backtracking cost is a function of input length
    # as well as pattern shape.
    bounded = value[:_MAX_MATCH_INPUT_LEN]

    try:
        import regex as _regex  # type: ignore[import-not-found]  # noqa: PLC0415
    except ImportError:
        _regex = None  # type: ignore[assignment]

    if _regex is not None:
        try:
            compiled = _regex.compile(pattern)
        except _regex.error:
            return None
        try:
            return compiled.search(bounded, timeout=_MATCH_TIMEOUT_S) is not None
        except TimeoutError:
            # A pathological pattern that slipped the static gate hit the
            # hard wall-clock bound — treat as unsafe / non-match.
            return None

    try:
        compiled = _re.compile(pattern)
    except _re.error:
        return None
    return compiled.search(bounded) is not None


def _check_value(value: Any, check: dict[str, Any]) -> str | None:
    """Run a single check spec against ``value``. Return a failure message
    fragment, or ``None`` if the check passed.
    """
    if check.get("must_exist") and not _has_value(value):
        return "is missing or empty"

    if "must_equal" in check:
        if value != check["must_equal"]:
            return f"expected {check['must_equal']!r}, got {value!r}"

    if "must_be_in" in check:
        allowed = check["must_be_in"] or []
        if value not in allowed:
            return f"value {value!r} not in {allowed!r}"

    if "must_match" in check:
        pattern = str(check["must_match"])
        if not isinstance(value, str):
            return f"does not match /{pattern}/"
        matched = _safe_search(pattern, value)
        if matched is None:
            # Pattern rejected as unsafe (ReDoS / too long / un-compilable):
            # treat as a non-match so a hostile rule degrades gracefully
            # instead of hanging the worker (E-SEC-002).
            return f"does not match /{pattern}/ (pattern rejected as unsafe)"
        if not matched:
            return f"does not match /{pattern}/"

    numeric_keys = ("must_be_gt", "must_be_gte", "must_be_lt", "must_be_lte")
    if any(k in check for k in numeric_keys):
        num = _coerce_number(value)
        if num is None:
            return "is not a number"
        if "must_be_gt" in check and not num > float(check["must_be_gt"]):
            return f"must be > {check['must_be_gt']} (got {num})"
        if "must_be_gte" in check and not num >= float(check["must_be_gte"]):
            return f"must be >= {check['must_be_gte']} (got {num})"
        if "must_be_lt" in check and not num < float(check["must_be_lt"]):
            return f"must be < {check['must_be_lt']} (got {num})"
        if "must_be_lte" in check and not num <= float(check["must_be_lte"]):
            return f"must be <= {check['must_be_lte']} (got {num})"

    return None
