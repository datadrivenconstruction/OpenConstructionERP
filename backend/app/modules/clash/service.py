# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""‌⁠‍Clash detection engine + run lifecycle.

Three-phase, mathematically-exact narrow phase over **real triangle
meshes** (faces → vertices) supplied by
:class:`app.modules.clash.geometry.ClashGeometryProvider`:

1. **Broad phase** - uniform spatial hash (grid) over per-element world
   AABBs so only elements sharing a cell are pair-tested: O(n) buckets
   instead of O(n²). When real GLB geometry is available the AABBs come
   from the actual mesh extents; otherwise we fall back to the canonical
   ``oe_bim_element.bounding_box`` (DDC cad2data) so a model with no GLB
   still produces a (coarser, bbox-grade) result.
2. **Mid phase** - Oriented-Bounding-Box Separating Axis Theorem
   (15 candidate axes: 3+3 face normals + 9 edge cross products). A pure
   quick reject that culls the vast majority of AABB candidates before
   the expensive triangle test, with zero false negatives.
3. **Narrow phase** - pure-numpy, fully-vectorised **Möller (1997)
   triangle–triangle intersection** between the two elements' real
   triangles. A pair is a HARD clash iff at least one triangle pair
   actually intersects *and* the geometry-derived penetration estimate
   exceeds ``run.tolerance_m``; a CLEARANCE clash iff it is not hard and
   the *real measured* minimum surface-to-surface distance is within
   ``run.clearance_m`` (vectorised point-to-triangle, both directions).

Reference for the triangle test:
    Tomas Möller, "A Fast Triangle-Triangle Intersection Test",
    Journal of Graphics Tools, 2(2):25-30, 1997. The interval-overlap
    formulation on the line of intersection of the two triangle planes
    is used; coplanar pairs fall back to the 2-D edge/containment test
    of the same paper.

No IfcOpenShell, no native IFC - geometry is GLB triangles produced by
the DDC pipeline, or the canonical bbox fallback (the architecture guide §3).
"""

from __future__ import annotations

import hashlib
import logging
import math
import uuid
from datetime import UTC, datetime
from itertools import combinations

import numpy as np
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import event_bus
from app.modules.bcf.bcf_xml import BCFParseError, parse_bcfzip
from app.modules.bcf.schemas import PerspectiveCamera, TopicCreate, Vec3, ViewpointCreate
from app.modules.bcf.service import BCFService
from app.modules.clash.events import (
    CLASH_HIGH_SEVERITY_DETECTED,
    HIGH_SEVERITIES,
    TRIGGER_CONFIRMED,
    TRIGGER_CREATED,
)
from app.modules.clash.models import (
    ClashCluster,
    ClashIssue,
    ClashProfile,
    ClashResult,
    ClashRun,
    ClashSuppression,
)
from app.modules.clash.repository import ClashRepository
from app.modules.clash.schemas import (
    CLASH_ACTION_TARGETS,
    CLASH_GROUPING_DIMENSIONS,
    CLASH_ISSUE_STATUSES,
    CLASH_SEVERITIES,
    CLASH_STATUSES,
    CLASH_TYPES,
    OPEN_STATUSES,
    ClashBCFExportRequest,
    ClashProfileApplyRequest,
    ClashProfileCreate,
    ClashProfileUpdate,
    ClashRule,
    ClashRunCreate,
    ClashSelectionSet,
)

try:  # The geometry loader is a sibling module; tolerate its absence.
    from app.modules.clash.geometry import ClashGeometryProvider, ElementGeom
except Exception:  # noqa: BLE001 - fall back to a structural stub for tests
    ClashGeometryProvider = None  # type: ignore[assignment,misc]
    ElementGeom = None  # type: ignore[assignment,misc]

logger = logging.getLogger(__name__)

# Safety rails: a single sync run will not chew unbounded CPU/RAM.
_MAX_ELEMENTS = 60_000
_MAX_PAIRS = 3_000_000
_MAX_RESULTS = 25_000
# Bounding the cells an element can occupy stops one floor-sized slab from
# being inserted into tens of thousands of buckets.
_MAX_CELLS_PER_ELEMENT = 512
# Triangle budget per element. Above this the mesh is deterministically
# decimated to the largest-area triangles so a single pathological mesh
# (a tessellated dome, a re-bar cage) cannot blow the per-pair runtime.
_MAX_TRIS_PER_ELEMENT = 4000
# Numeric epsilon for the Möller plane / interval tests (metres scale).
_EPS = 1e-9

# Sentinel for "caller did not pass a precomputed value" - distinct from
# ``None`` which legitimately means "this element has no usable mesh".
_UNSET: object = object()

# Statuses that mean a human has confirmed the clash is a real, accepted
# interference worth coordinating (as opposed to ``new`` / ``active`` which
# are pre-triage, or ``ignored`` which is a false positive). Moving a
# high/critical clash into one of these fires the high-severity event.
_CONFIRMED_CLASH_STATUSES: frozenset[str] = frozenset({"reviewed", "approved"})


def _now() -> datetime:
    return datetime.now(UTC)


def _signature_from_description(desc: str) -> str:
    """Recover the canonical clash signature from a BCF topic description.

    Mirrors the format the exporter writes:

        "{clash_type_capitalized} clash · {disc_a} ↔ {disc_b}\n"
        "A: {a_name} ({a_stable_id})\n"
        "B: {b_name} ({b_stable_id})\n"
        ...

    Pulled from the description body alone so a third-party BCF tool
    that round-trips topic_status / comments / assigned_to but leaves
    the description untouched still resolves. Returns ``""`` when the
    expected lines are missing (the import then falls back to the
    topic GUID before giving up).
    """
    if not desc:
        return ""
    lines = desc.split("\n")
    head = lines[0] if lines else ""
    clash_type = ""
    low = head.lower()
    if low.startswith("hard clash"):
        clash_type = "hard"
    elif low.startswith("clearance clash"):
        clash_type = "clearance"
    if not clash_type:
        return ""

    def _stable_from(line: str) -> str:
        """Pull the stable id from a ``X: name (stable_id)`` line."""
        lp = line.rfind("(")
        rp = line.rfind(")")
        if lp < 0 or rp <= lp:
            return ""
        return line[lp + 1 : rp].strip()

    a_sid = ""
    b_sid = ""
    for line in lines[1:]:
        if line.startswith("A: ") and not a_sid:
            a_sid = _stable_from(line)
        elif line.startswith("B: ") and not b_sid:
            b_sid = _stable_from(line)
        if a_sid and b_sid:
            break
    if not a_sid or not b_sid:
        return ""
    return _signature(a_sid, b_sid, clash_type)


# BCF topic_status (free-text by spec) → our review-workflow enum.
# Anything we can't confidently map drops to ``None`` so the import
# leaves the existing status untouched (never silently corrupts state).
_BCF_STATUS_MAP: dict[str, str] = {
    "open": "active",
    "active": "active",
    "in progress": "active",
    "in-progress": "active",
    "review": "reviewed",
    "reviewed": "reviewed",
    "to be reviewed": "reviewed",
    "resolved": "resolved",
    "closed": "resolved",
    "fixed": "resolved",
    "approved": "approved",
    "accepted": "approved",
    "ignored": "ignored",
    "rejected": "ignored",
    "wont fix": "ignored",
    "won't fix": "ignored",
}


def _bcf_status_to_clash_status(topic_status: str | None) -> str | None:
    """Map a BCF topic_status string onto our review-workflow enum.

    Case- and whitespace-insensitive. Returns ``None`` for an unmapped
    or empty value so the caller can leave the row's status untouched.
    """
    if not topic_status:
        return None
    key = topic_status.strip().lower()
    return _BCF_STATUS_MAP.get(key)


def _signature(a_stable_id: str, b_stable_id: str, clash_type: str) -> str:
    """Stable, run-independent identity of a clashing element pair.

    ``sha1(min(a,b)|max(a,b)|clash_type)[:16]`` over the two stable ids.
    Order-independent (the pair {A,B} hashes the same regardless of which
    element the engine put first), so the same physical interference gets
    the same signature across re-runs - that is the join key the
    run-to-run comparison and triage carry-forward rely on.
    """
    a = a_stable_id or ""
    b = b_stable_id or ""
    lo, hi = (a, b) if a <= b else (b, a)
    raw = f"{lo}|{hi}|{clash_type}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


# ── Smart-issue signature (v41) ─────────────────────────────────────────

# Default spatial grid in millimetres for ``ClashRun.spatial_grid_mm`` -
# coarse enough to absorb sub-mm geometry drift on re-runs but fine
# enough that a real geometry change (moving a pipe by half a metre)
# hashes to a fresh issue. Tweakable per-run on the model.
_DEFAULT_SPATIAL_GRID_MM = 500
# How many consecutive runs an issue must be absent for before we move
# it from ``resolved`` to ``archived``. Three is the convention from
# Navisworks/Solibri: one missing run is noise, three is "really gone".
_ARCHIVE_AFTER_MISSING = 3


def _canon_guid(value: object) -> str:
    """Canonicalise a stable id / guid for the signature input.

    NFKC-normalises unicode + lower-cases + trims so two callers can pass
    e.g. ``"GUID-AB12"`` and ``" guid-ab12 "`` and get the same hash.
    ``None`` / empty → ``""`` so the caller knows the GUID is missing and
    can decide to fall back to the weak signature.
    """
    if value is None:
        return ""
    import unicodedata as _ud

    s = str(value).strip()
    if not s:
        return ""
    return _ud.normalize("NFKC", s).lower()


def _bucket(value: float, grid_mm: int) -> int:
    """Quantise a metre coordinate to its ``grid_mm`` cell index.

    ``floor((value_m * 1000) / grid_mm)``. Pure integer arithmetic on the
    millimetre scale so two centroids that differ by < grid_mm map to
    the same bucket and therefore the same signature.
    """
    if grid_mm <= 0:
        return 0
    try:
        mm = float(value) * 1000.0
    except (TypeError, ValueError):
        return 0
    if not math.isfinite(mm):
        return 0
    return int(math.floor(mm / float(grid_mm)))


def _compute_signature_hash(
    *,
    a_guid: str | None,
    b_guid: str | None,
    centroid: tuple[float, float, float],
    clash_type: str,
    grid_mm: int = _DEFAULT_SPATIAL_GRID_MM,
    weak_fallback: tuple[str, str, list[str]] | None = None,
) -> tuple[str, str]:
    """Compute the canonical clash signature hash.

    Returns ``(signature_hash, quality)`` where ``quality`` is ``"strong"``
    when real stable ids drove the hash, ``"weak"`` when the GUID-less
    fallback (ifc_class | material | sorted quantity keys) was used.

    ``signature = SHA1(canon(min) || "|" || canon(max) || "|" ||
                       bucket(cx) || "," || bucket(cy) || "," || bucket(cz)
                       || "|" || clash_type)``

    The GUID pair is sorted before hashing so ``(A, B)`` and ``(B, A)``
    yield the same hash. The clash-box centroid is bucketed by
    ``grid_mm`` so sub-mm drift between re-runs hashes to the same
    issue. ``clash_type`` is included so a hard hit and a clearance hit
    at the same spot are tracked as separate issues.

    Weak fallback: when either ``a_guid`` or ``b_guid`` canonicalises to
    the empty string AND ``weak_fallback`` is supplied
    (``(ifc_class, material, [quantity_keys])``), the GUIDs are replaced
    with ``sha1(ifc_class | material | sorted-keys)`` and the function
    flags the result as ``"weak"``. Without a fallback the strong path
    is used regardless (preserving the historical strong-only contract).
    """
    a_canon = _canon_guid(a_guid)
    b_canon = _canon_guid(b_guid)
    quality = "strong"
    if (not a_canon or not b_canon) and weak_fallback is not None:
        ifc_class, material, qty_keys = weak_fallback
        ifc_c = _canon_guid(ifc_class)
        mat_c = _canon_guid(material)
        keys = sorted(_canon_guid(k) for k in (qty_keys or []) if k)
        raw = f"{ifc_c}|{mat_c}|{','.join(keys)}"
        weak_hash = hashlib.sha1(raw.encode("utf-8")).hexdigest()
        # Re-use the weak hash on both sides so the sort still works.
        a_canon = weak_hash
        b_canon = weak_hash
        quality = "weak"
    lo, hi = (a_canon, b_canon) if a_canon <= b_canon else (b_canon, a_canon)
    cx, cy, cz = centroid
    bx = _bucket(cx, grid_mm)
    by = _bucket(cy, grid_mm)
    bz = _bucket(cz, grid_mm)
    ctype = _canon_guid(clash_type) or "hard"
    raw = f"{lo}|{hi}|{bx},{by},{bz}|{ctype}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest(), quality


_SEVERITY_BUMP_NEXT: dict[str, str] = {
    "low": "medium",
    "medium": "high",
    "high": "critical",
    "critical": "critical",
}


# ── Wave A4 - rules / clusters / FP feedback ─────────────────────────────

# Minimum false-positive count on a single discipline pair before the
# rule-suggestion endpoint will recommend an automatic tolerance bump.
# Tuned conservatively: a one-off FP is noise, but three on the same
# pair is a coordination signal worth surfacing.
_FP_SUGGESTION_THRESHOLD = 3
# Cluster pass safety cap - DBSCAN is O(n²) in the worst case (no
# spatial index), and a coordination run can produce tens of thousands
# of clashes. Above this point we no-op the clustering and leave every
# row at ``cluster_id=NULL`` rather than spending unbounded CPU.
_MAX_CLUSTER_RESULTS = 5_000
# Default neighbourhood radius (metres) + minimum cluster size for the
# spatial DBSCAN pass over clash centroids. ``eps_m`` is "two clashes
# this close are in the same cluster"; ``min_samples`` is the minimum
# group size to count as a real cluster (others become NULL noise).
_DEFAULT_CLUSTER_EPS_M = 0.6
_DEFAULT_CLUSTER_MIN_SAMPLES = 2


def _apply_rules(run: object, pair: tuple[str, str]) -> dict | None:
    """Find the matching rule for a discipline pair, or ``None``.

    ``pair`` is ``(discipline_a, discipline_b)`` from a candidate clash
    pair - symmetric, so ``(A, B)`` and ``(B, A)`` both match a rule
    declared for ``(A, B)``. Disabled rules are skipped. The *first*
    enabled match in the run's ``rules`` list wins (the rule editor
    preserves user order, so "more specific" rows naturally sort to
    the top by author convention).

    Returns the raw rule dict (or ``None``) so callers don't depend on
    the Pydantic schema - keeps this fully testable without instantiating
    :class:`ClashRule`. Defensive: any malformed rule entry is skipped,
    never crashes.
    """
    rules = getattr(run, "rules", None) or []
    if not isinstance(rules, list):
        return None
    da_n = (pair[0] or "").strip().lower()
    db_n = (pair[1] or "").strip().lower()
    if not da_n and not db_n:
        return None
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        if not bool(rule.get("enabled", True)):
            continue
        ra = str(rule.get("discipline_a") or "").strip().lower()
        rb = str(rule.get("discipline_b") or "").strip().lower()
        if not ra or not rb:
            continue
        if {ra, rb} == {da_n, db_n}:
            return rule
    return None


def _label_for_cluster(members: list[object], cluster_id: int) -> str:
    """Heuristic short label for a cluster, no LLM call.

    Picks the most common discipline pair across the cluster's members
    and appends the most common storey (when known). Examples:

        "MEP × Structural - Level 3"
        "Architectural × Architectural"   (intra-discipline cluster)
        "Cluster 7"                       (no usable members)

    Pure function over the member rows - used both at write time
    (engine path) and as the fallback for ad-hoc relabelling.
    """
    if not members:
        return f"Cluster {cluster_id}"
    pair_counts: dict[tuple[str, str], int] = {}
    storey_counts: dict[int, int] = {}
    for m in members:
        a = str(getattr(m, "a_discipline", "") or "Unassigned").strip() or "Unassigned"
        b = str(getattr(m, "b_discipline", "") or "Unassigned").strip() or "Unassigned"
        pair = (a, b) if a <= b else (b, a)
        pair_counts[pair] = pair_counts.get(pair, 0) + 1
        for sk in ("a_storey", "b_storey"):
            sv = getattr(m, sk, None)
            if sv is None:
                continue
            try:
                storey_counts[int(sv)] = storey_counts.get(int(sv), 0) + 1
            except (TypeError, ValueError):
                continue
    if not pair_counts:
        return f"Cluster {cluster_id}"
    # Dominant pair: highest count, then alphabetic tie-break for
    # determinism. The previous version computed `top_pair` twice with
    # divergent tie-break logic; the first assignment was dead code, so
    # results were inconsistent only when re-reading the variable for
    # debugging. Keep one stable expression.
    top_pair = max(pair_counts, key=lambda p: (pair_counts[p], -ord(p[0][:1] or "z")))
    label = f"{top_pair[0]} × {top_pair[1]}"
    if storey_counts:
        top_storey = max(storey_counts, key=lambda s: (storey_counts[s], -s))
        label += f" - Level {top_storey}"
    return label[:255]


def _dbscan_cluster(
    points: list[tuple[float, float, float]],
    eps_m: float = _DEFAULT_CLUSTER_EPS_M,
    min_samples: int = _DEFAULT_CLUSTER_MIN_SAMPLES,
) -> list[int | None]:
    """Hand-rolled DBSCAN over 3-D centroids → cluster id per point.

    Returns a parallel list of ``cluster_id``s (1-based) or ``None`` for
    DBSCAN noise. Pure Python, no sklearn - uses O(n²) neighbourhood
    scans capped by :data:`_MAX_CLUSTER_RESULTS`. Above the cap every
    point becomes ``None`` (graceful no-op): the cluster column simply
    stays unset and the chip group renders empty.

    Standard density-based clustering (Ester 1996):
      * A point is a *core* point if it has ``min_samples`` neighbours
        within ``eps_m`` (inclusive of itself).
      * Each unvisited core point spawns a new cluster; its density-
        reachable neighbours are absorbed iteratively (BFS).
      * Non-core points adjacent to a cluster get its label (border).
      * Points reached by no core remain ``None`` (noise).

    Deterministic: clusters are numbered in the iteration order of
    ``points``, so two identical inputs always produce the same labels.
    """
    n = len(points)
    if n == 0 or n > _MAX_CLUSTER_RESULTS:
        return [None] * n
    if min_samples < 1:
        min_samples = 1
    eps_sq = float(eps_m) * float(eps_m)

    # O(n²) neighbourhood scan - explicit upper-bound by the cap above.
    # Each entry is a list of neighbour indices (inclusive of self).
    neighbours: list[list[int]] = [[] for _ in range(n)]
    for i in range(n):
        xi, yi, zi = points[i]
        for j in range(i, n):
            xj, yj, zj = points[j]
            dx = xi - xj
            dy = yi - yj
            dz = zi - zj
            if dx * dx + dy * dy + dz * dz <= eps_sq:
                neighbours[i].append(j)
                if i != j:
                    neighbours[j].append(i)

    labels: list[int | None] = [None] * n
    visited = [False] * n
    cluster_id = 0
    for i in range(n):
        if visited[i]:
            continue
        visited[i] = True
        nbrs = neighbours[i]
        if len(nbrs) < min_samples:
            # Not core - leave as noise; may still get absorbed later by
            # a neighbouring core point's BFS.
            continue
        cluster_id += 1
        labels[i] = cluster_id
        # BFS-expand from this seed.
        queue = list(nbrs)
        qi = 0
        while qi < len(queue):
            k = queue[qi]
            qi += 1
            if not visited[k]:
                visited[k] = True
                k_nbrs = neighbours[k]
                if len(k_nbrs) >= min_samples:
                    # k is also core - extend the frontier.
                    for kn in k_nbrs:
                        if labels[kn] is None and kn not in queue:
                            queue.append(kn)
            if labels[k] is None:
                labels[k] = cluster_id
    return labels


def _suggest_rule_from_fps(
    fp_pairs: list[tuple[str, str]],
    fp_max_penetration_by_pair: dict[tuple[str, str], float] | None = None,
) -> tuple[dict | None, str, int]:
    """Mine a (rule, reason, fp_count) suggestion from FP discipline pairs.

    ``fp_pairs`` is the list of canonicalised ``(disc_a, disc_b)`` tuples
    (alphabetically ordered per pair) extracted from the run's recorded
    false-positives. When any single pair crosses
    :data:`_FP_SUGGESTION_THRESHOLD` we propose a rule that widens that
    pair's tolerance just past the largest observed FP penetration (so
    the same geometric near-misses no longer trip the engine), with a
    safe floor and ceiling. ``fp_count = 0`` and ``rule = None`` when no
    pair has enough signal - the UI then hides the suggestion banner.
    """
    if not fp_pairs:
        return None, "", 0
    counts: dict[tuple[str, str], int] = {}
    for pair in fp_pairs:
        counts[pair] = counts.get(pair, 0) + 1
    # Largest-FP pair, ties broken alphabetically for determinism.
    top_pair, top_count = max(counts.items(), key=lambda kv: (kv[1], -ord((kv[0][0] or "z")[:1] or "z")))
    if top_count < _FP_SUGGESTION_THRESHOLD:
        return None, "", top_count
    # Tolerance proposal: a safe 0.05 m default, widened just past the
    # largest observed FP penetration when known (capped at 0.50 m so we
    # never recommend something catastrophic).
    proposed_tol = 0.05
    if fp_max_penetration_by_pair:
        max_pen = float(fp_max_penetration_by_pair.get(top_pair, 0.0) or 0.0)
        if max_pen > 0:
            proposed_tol = min(0.50, max(0.05, round(max_pen + 0.01, 3)))
    rule = {
        "id": f"sugg-{top_pair[0]}-{top_pair[1]}",
        "discipline_a": top_pair[0],
        "discipline_b": top_pair[1],
        "tolerance_m": proposed_tol,
        "severity_override": None,
        "enabled": True,
    }
    reason = f"{top_count} false positives on {top_pair[0]} × {top_pair[1]} - widen tolerance to {proposed_tol:g} m"
    return rule, reason, top_count


def _coerce_rules(rules: object) -> list[dict]:
    """Defensive normaliser - return only dict rule entries.

    The ``rules`` column is plain JSON, so a misbehaving caller could
    insert non-dict noise. The router exposes whatever this returns, so
    we strip junk silently rather than 500ing.
    """
    if not isinstance(rules, list):
        return []
    return [r for r in rules if isinstance(r, dict)]


def _existing_rule_pairs(rules: object) -> set[frozenset[str]]:
    """Lowercase symmetric pairs already covered by the run's rule set."""
    out: set[frozenset[str]] = set()
    for r in _coerce_rules(rules):
        a = str(r.get("discipline_a") or "").strip().lower()
        b = str(r.get("discipline_b") or "").strip().lower()
        if a and b:
            out.add(frozenset((a, b)))
    return out


def _collect_fp_pairs(
    rows: list[ClashResult],
) -> tuple[list[tuple[str, str]], dict[tuple[str, str], float]]:
    """Extract canonical FP discipline pairs + their max penetration.

    A clash is treated as a false-positive sample when its current
    ``status == 'ignored'`` (the FP feedback loop flips ignored on the
    way through), OR when its history audit trail carries an
    ``fp_flag``/``flag_fp`` entry. Pair tuples are alphabetically
    canonical so the suggester sees ``(A, B)`` and ``(B, A)`` as one.
    """
    pairs: list[tuple[str, str]] = []
    max_pen: dict[tuple[str, str], float] = {}
    for r in rows:
        is_fp = (r.status or "") == "ignored"
        if not is_fp:
            for h in r.history or []:
                fld = str((h or {}).get("field", "")).lower()
                if fld in ("fp_flag", "flag_fp", "false_positive"):
                    is_fp = True
                    break
        if not is_fp:
            continue
        a = (r.a_discipline or "").strip() or "Unassigned"
        b = (r.b_discipline or "").strip() or "Unassigned"
        pair = (a, b) if a <= b else (b, a)
        pairs.append(pair)
        pen = float(r.penetration_m or 0.0)
        if pen > max_pen.get(pair, 0.0):
            max_pen[pair] = pen
    return pairs, max_pen


def _dominant_pair_and_storey(
    members: list[ClashResult],
) -> tuple[tuple[str, str], int | None]:
    """Most-common discipline pair + storey of a cluster's member rows.

    Returns ``("",""), None`` when ``members`` is empty so the caller
    can render the chip with a generic ``"Cluster N"`` label without
    branching on type. Mirrors the inner logic of
    :func:`_label_for_cluster` but exposed as a structured tuple for the
    REST projection.
    """
    if not members:
        return ("", ""), None
    pair_counts: dict[tuple[str, str], int] = {}
    storey_counts: dict[int, int] = {}
    for m in members:
        a = (getattr(m, "a_discipline", "") or "Unassigned").strip() or "Unassigned"
        b = (getattr(m, "b_discipline", "") or "Unassigned").strip() or "Unassigned"
        pair = (a, b) if a <= b else (b, a)
        pair_counts[pair] = pair_counts.get(pair, 0) + 1
        for sk in ("a_storey", "b_storey"):
            sv = getattr(m, sk, None)
            if sv is None:
                continue
            try:
                storey_counts[int(sv)] = storey_counts.get(int(sv), 0) + 1
            except (TypeError, ValueError):
                continue
    if not pair_counts:
        return ("", ""), None
    top_pair = max(pair_counts, key=lambda p: (pair_counts[p], p))
    top_storey: int | None = None
    if storey_counts:
        top_storey = max(storey_counts, key=lambda s: (storey_counts[s], -s))
    return top_pair, top_storey


# Worst-first ordering for picking a cluster's headline severity. Mirrors
# :data:`CLASH_SEVERITIES` (index 0 = worst). Kept local so the proposal
# helper stays a pure function with no schema import at call time.
_SEVERITY_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3}
# Clash severity → work-item priority. The punchlist / task priority
# vocabularies both accept these four bands, so the mapping is 1:1; a
# missing / unknown severity degrades to ``medium`` (never blocks).
_SEVERITY_TO_PRIORITY = {
    "critical": "critical",
    "high": "high",
    "medium": "medium",
    "low": "low",
}


def _max_severity(members: list[ClashResult]) -> str | None:
    """Return the worst (highest-rank) severity across a cluster, or None.

    ``None`` only when ``members`` is empty - every result row carries a
    server-defaulted ``severity`` so a non-empty cluster always resolves
    one. Pure function over the rows.
    """
    if not members:
        return None
    worst = "low"
    worst_rank = _SEVERITY_RANK["low"]
    for m in members:
        raw = (getattr(m, "severity", "") or "medium").strip() or "medium"
        # Coerce an unknown band to ``medium`` so we never surface a stray
        # raw string (e.g. a typo'd severity) as the cluster's headline.
        sev = raw if raw in _SEVERITY_RANK else "medium"
        rank = _SEVERITY_RANK[sev]
        if rank < worst_rank:
            worst_rank = rank
            worst = sev
    return worst


def _build_cluster_action_proposal(
    cluster_id: int,
    members: list[ClashResult],
    label: str,
    target: str,
) -> dict:
    """Draft an AI-augmented work-item proposal from a cluster's members.

    Pure heuristic - **no LLM call**. Derives a readable title, a body that
    lists the dominant interference and a sample of element pairs, a
    priority (mapped from the cluster's worst severity), a suggested
    assignee (the most-common assignee already on the member rows, if any)
    and a ``confidence`` score.

    Confidence rewards a cluster that is easy for a coordinator to action:
    a single dominant discipline pair, a resolved storey and a clear worst
    severity push it up; a tiny or geometrically scattered cluster pulls it
    down. The score is advisory only - the human still confirms (and may
    edit every field) before anything is created.

    Returns a plain dict matching :class:`ClashGroupActionProposal`.
    """
    (disc_a, disc_b), storey = _dominant_pair_and_storey(members)
    max_sev = _max_severity(members)
    priority = _SEVERITY_TO_PRIORITY.get(max_sev or "medium", "medium")
    n = len(members)

    pair_label = label.strip() or (f"{disc_a} x {disc_b}" if disc_a or disc_b else f"Cluster {cluster_id}")
    title = f"Coordinate clash group: {pair_label}"[:255]

    # Most-common existing assignee across the members (carry the human's
    # earlier triage forward as the default), else none.
    assignee_counts: dict[str, int] = {}
    for m in members:
        a = (getattr(m, "assigned_to", "") or "").strip()
        if a:
            assignee_counts[a] = assignee_counts.get(a, 0) + 1
    suggested_assignee = max(assignee_counts, key=lambda k: assignee_counts[k]) if assignee_counts else None

    # Body: headline + up to five representative element pairs so the
    # site team can find the interference without opening the model.
    lines = [
        f"Auto-drafted from a {n}-clash coordination group.",
        f"Dominant interference: {disc_a or 'Unassigned'} vs {disc_b or 'Unassigned'}"
        + (f" on Level {storey}" if storey is not None else ""),
        f"Highest severity in group: {max_sev or 'medium'}.",
        "",
        "Representative element pairs:",
    ]
    for m in members[:5]:
        a_name = (getattr(m, "a_name", "") or "?").strip() or "?"
        b_name = (getattr(m, "b_name", "") or "?").strip() or "?"
        ctype = (getattr(m, "clash_type", "") or "hard").strip() or "hard"
        lines.append(f"- {a_name} vs {b_name} ({ctype})")
    if n > 5:
        lines.append(f"- ... and {n - 5} more")
    description = "\n".join(lines)[:5000]

    # ── Confidence: 0..1, advisory only ───────────────────────────────
    confidence = 0.35
    # A clear dominant pair (resolved disciplines, not Unassigned) is the
    # single biggest signal that the group is coherent.
    if disc_a and disc_b and disc_a != "Unassigned" and disc_b != "Unassigned":
        confidence += 0.25
    if storey is not None:
        confidence += 0.15
    if max_sev in ("critical", "high"):
        confidence += 0.15
    # Larger, denser clusters are more obviously worth one shared action.
    if n >= 5:
        confidence += 0.10
    confidence = round(min(confidence, 1.0), 2)

    return {
        "cluster_id": int(cluster_id),
        "target": target if target in CLASH_ACTION_TARGETS else "punchlist",
        "title": title,
        "description": description,
        "priority": priority,
        "suggested_assignee": suggested_assignee,
        "member_count": n,
        "dominant_disciplines": [d for d in (disc_a, disc_b) if d],
        "storey": storey,
        "max_severity": max_sev,
        "confidence": confidence,
        "already_linked": False,
        "existing_action_id": None,
        "existing_action_target": None,
    }


def _resolved_mttr_hours(rows: list[ClashResult]) -> float | None:
    """Average wall-clock hours from row creation to first ``resolved``.

    Each row contributes one sample iff its history has at least one
    ``status``-field entry with ``after == 'resolved'``. The earliest
    such entry's ``ts`` minus the row's ``created_at`` is the row's
    resolution latency in hours. Returns ``None`` when no row qualifies
    (the dashboard hides the MTTR tile in that case).
    """
    samples: list[float] = []
    for r in rows:
        history = getattr(r, "history", None) or []
        resolved_ts: str | None = None
        for h in history:
            if not isinstance(h, dict):
                continue
            if str(h.get("field", "")).lower() != "status":
                continue
            if str(h.get("after", "")).lower() != "resolved":
                continue
            ts = str(h.get("ts") or "")
            if ts and (resolved_ts is None or ts < resolved_ts):
                resolved_ts = ts
        if not resolved_ts:
            continue
        try:
            ended = datetime.fromisoformat(resolved_ts.replace("Z", "+00:00"))
        except ValueError:
            continue
        started = getattr(r, "created_at", None)
        if started is None:
            continue
        # Both timestamps need to be tz-aware for the subtraction to
        # work; coerce naive timestamps (legacy SQLite test rows) to UTC.
        utc = UTC
        if started.tzinfo is None:
            started = started.replace(tzinfo=utc)
        if ended.tzinfo is None:
            ended = ended.replace(tzinfo=utc)
        delta = (ended - started).total_seconds() / 3600.0
        if delta >= 0:
            samples.append(delta)
    if not samples:
        return None
    return round(sum(samples) / len(samples), 3)


def _compute_kpi(rows: list[ClashResult]) -> dict:
    """Build the dashboard JSON projection for ``GET /runs/{id}/kpi``.

    One pass over the row list. ``top_clashing_pairs`` is the top five
    discipline pairs by ``count`` (open_count desc, then pair alphabetic
    on ties - deterministic).
    """
    total = len(rows)
    by_status: dict[str, int] = {}
    by_severity: dict[str, int] = dict.fromkeys(CLASH_SEVERITIES, 0)
    by_type: dict[str, int] = {}
    pair_counts: dict[tuple[str, str], dict[str, int]] = {}
    for r in rows:
        st = r.status or "new"
        by_status[st] = by_status.get(st, 0) + 1
        sev = getattr(r, "severity", None) or "medium"
        by_severity[sev] = by_severity.get(sev, 0) + 1
        ct = r.clash_type or "hard"
        by_type[ct] = by_type.get(ct, 0) + 1
        a = (r.a_discipline or "Unassigned").strip() or "Unassigned"
        b = (r.b_discipline or "Unassigned").strip() or "Unassigned"
        pair = (a, b) if a <= b else (b, a)
        cell = pair_counts.setdefault(pair, {"count": 0, "open_count": 0})
        cell["count"] += 1
        if st in OPEN_STATUSES:
            cell["open_count"] += 1
    by_pair_full: list[dict] = []
    for (a, b), c in sorted(pair_counts.items()):
        count = c["count"]
        open_count = c["open_count"]
        share = (open_count / count) if count else 0.0
        by_pair_full.append(
            {
                "a": a,
                "b": b,
                "count": count,
                "open_count": open_count,
                "open_share": round(share, 4),
            }
        )
    # Top five by count desc, open_count desc, pair alphabetic - stable.
    top_pairs = sorted(
        by_pair_full,
        key=lambda p: (-p["count"], -p["open_count"], p["a"], p["b"]),
    )[:5]
    return {
        "total": total,
        "by_status": by_status,
        "by_severity": by_severity,
        "by_type": by_type,
        "by_discipline_pair": by_pair_full,
        "mttr_hours": _resolved_mttr_hours(rows),
        "top_clashing_pairs": top_pairs,
    }


def _severity_suggestion(clash_type: str, penetration_m: float, base: str) -> str | None:
    """Wave A2 advisory bump for deep hard clashes (pure annotation).

    The engine-assigned ``severity`` stays the source of truth - this is
    a non-authoritative ``meta['severity_suggestion']`` the UI surfaces
    as a "Suggested: …" chip the user can act on. Triggers when a hard
    clash interpenetrates more than 0.10 m AND the base severity has
    headroom; ``None`` otherwise (clearance, shallow, or already at the
    ceiling).
    """
    if clash_type != "hard" or penetration_m <= 0.10:
        return None
    nxt = _SEVERITY_BUMP_NEXT.get(base)
    if not nxt or nxt == base:
        return None
    return nxt


def _severity_for(clash_type: str, penetration_m: float, distance_m: float, clearance_m: float) -> str:
    """Geometry-derived triage urgency.

    Hard clash - keyed off interpenetration depth (deeper = worse):
    ``>= 0.10 m`` critical, ``>= 0.03 m`` high, ``>= 0.005 m`` medium,
    else low. Clearance clash - keyed off the gap-to-threshold ratio
    ``g/c`` (a clearance violation is never *critical*): ``<= 0.25``
    high, ``<= 0.50`` medium, else low. ``clearance_m <= 0`` is guarded
    (degrades to ``medium``) so a bad config never raises here.
    """
    if clash_type == "hard":
        p = penetration_m
        if p >= 0.10:
            return "critical"
        if p >= 0.03:
            return "high"
        if p >= 0.005:
            return "medium"
        return "low"
    # clearance - proximity violation, never critical.
    c = clearance_m
    if c <= 0:
        return "medium"
    ratio = distance_m / c
    if ratio <= 0.25:
        return "high"
    if ratio <= 0.50:
        return "medium"
    return "low"


def _norm_bbox(bb: object) -> tuple[float, float, float, float, float, float] | None:
    """‌⁠‍Normalise either bbox dialect to ``(minx,miny,minz,maxx,maxy,maxz)``.

    The DDC pipeline writes the flat ``min_x..max_z`` form per element;
    some legacy paths use the nested ``{"min":{x,y,z},"max":{x,y,z}}``
    model-level shape. Anything malformed / zero-volume → ``None``.
    """
    if not isinstance(bb, dict):
        return None
    try:
        if "min_x" in bb:
            mn = (float(bb["min_x"]), float(bb["min_y"]), float(bb["min_z"]))
            mx = (float(bb["max_x"]), float(bb["max_y"]), float(bb["max_z"]))
        elif "min" in bb and "max" in bb:
            lo, hi = bb["min"], bb["max"]
            mn = (float(lo["x"]), float(lo["y"]), float(lo["z"]))
            mx = (float(hi["x"]), float(hi["y"]), float(hi["z"]))
        else:
            return None
    except (KeyError, TypeError, ValueError):
        return None
    # Reject NaN/Inf and degenerate (non-positive volume) boxes.
    vals = (*mn, *mx)
    if any(not math.isfinite(v) for v in vals):
        return None
    if mx[0] <= mn[0] or mx[1] <= mn[1] or mx[2] <= mn[2]:
        return None
    return (mn[0], mn[1], mn[2], mx[0], mx[1], mx[2])


def _discipline_of(element: object) -> str:
    """‌⁠‍Resolve an element's coordination discipline.

    Prefer the persisted ``discipline`` column (the DDC pipeline already
    classifies on import); otherwise reuse bim_hub's keyword classifier on
    the element type so this module never re-implements the taxonomy.
    """
    d = (getattr(element, "discipline", None) or "").strip()
    if d:
        return d.capitalize()
    try:
        from app.modules.bim_hub.ifc_processor import _classify_discipline

        return _classify_discipline(getattr(element, "element_type", "") or "").capitalize()
    except Exception:  # noqa: BLE001 - classification is best-effort
        return "Unassigned"


def _type_of(element: object) -> str:
    """Element's category / family-type (the indexed ``element_type``)."""
    return (getattr(element, "element_type", None) or "").strip()


def _category_of(element: object) -> str:
    """Element's source-native category (Revit category / ``ifc_class``).

    Mirrors :meth:`ClashRepository._category_of` so a selection set built
    on the ``category`` grouping resolves to the very same elements the
    Set A/B picker advertised. Falls back to ``element_type``.
    """
    props = getattr(element, "properties", None) or {}
    for key in ("category", "rvt_category", "ifc_class", "revit_category"):
        v = props.get(key)
        if v:
            return str(v).strip()
    return _type_of(element)


def _ifc_entity_of(element: object) -> str:
    """Raw IFC entity (``IfcWall``…) - empty for non-IFC elements."""
    props = getattr(element, "properties", None) or {}
    for key in ("ifc_type", "ifc_entity", "IfcEntity"):
        v = props.get(key)
        if v:
            return str(v).strip()
    return ""


def _system_of(element: object) -> str:
    """Resolve an element's building *system* for multi-dim grouping.

    Prefers an explicit MEP system property (``system`` / ``System`` /
    ``system_name`` / IFC ``Pset_*System``), then falls back to the
    family / type name a Revit / DDC element carries. Returns ``""`` when
    the element has no usable system metadata - the grouping selector
    then hides the ``discipline_system`` dimension (graceful degradation).
    Item #23 - snapshotted onto :class:`ClashResult.a_element_system`.
    """
    props = getattr(element, "properties", None) or {}
    if not isinstance(props, dict):
        return ""
    for key in (
        "system",
        "System",
        "system_name",
        "SystemName",
        "mep_system",
        "ifc_system",
        "family",
        "Family",
        "family_name",
        "type_name",
        "TypeName",
    ):
        v = props.get(key)
        if v is not None and not isinstance(v, (dict, list)):
            sv = str(v).strip()
            if sv:
                return sv[:100]
    return ""


def _property_value_of(element: object, key: str) -> str | None:
    """An element's scalar ``properties[key]`` as a trimmed string.

    Returns ``None`` when the element has no usable value for ``key`` -
    missing/None ``properties``, key absent, or a non-scalar
    (dict/list) value. Never raises.
    """
    props = getattr(element, "properties", None)
    if not isinstance(props, dict):
        return None
    v = props.get(key)
    if v is None or isinstance(v, (dict, list)):
        return None
    return str(v).strip()


def _in_set(element: object, etype: str, disc: str, spec: dict | None) -> bool:
    """True iff an element belongs to a Navisworks-style selection set.

    ``spec`` is ``{"element_types": [...], "disciplines": [...],
    "categories": [...], "ifc_entities": [...], "properties":
    {key: [...]}}``. Every list (and every per-property value list) is a
    *union*: every chip the user adds widens the set, so an element
    matches when its ``element_type``, ``discipline``, source-native
    category, IFC entity **or** - for ANY key in ``properties`` - its
    string-coerced/trimmed ``properties[key]`` is listed. The extra
    lists/maps let the picker facet by any grouping parameter while the
    engine still resolves membership to real elements. An empty /
    missing spec matches nothing (the run-create guard already rejects
    empty sets for this mode). Defensive: a missing/None properties
    dict or non-scalar value simply never matches, never crashes.
    """
    if not spec:
        return False
    if etype in (spec.get("element_types") or []):
        return True
    if disc in (spec.get("disciplines") or []):
        return True
    cats = spec.get("categories") or []
    if cats and _category_of(element) in cats:
        return True
    ents = spec.get("ifc_entities") or []
    if ents and _ifc_entity_of(element) in ents:
        return True
    props = spec.get("properties")
    if isinstance(props, dict):
        for key, allowed in props.items():
            if not allowed:
                continue
            val = _property_value_of(element, key)
            if val is not None and val in allowed:
                return True
    return False


# ── Mesh helpers ───────────────────────────────────────────────────────────


def _triangles(geom: object) -> np.ndarray | None:
    """Resolve a geometry's triangle soup as an ``(T,3,3)`` float64 array.

    ``faces`` index into ``vertices``. Degenerate / empty meshes (no
    vertices, no faces, all-collinear triangles) return ``None`` so the
    caller treats the element as non-clashable rather than crashing.
    Meshes above :data:`_MAX_TRIS_PER_ELEMENT` are deterministically
    decimated to their largest-area triangles (stable sort, no RNG).
    """
    verts = getattr(geom, "vertices", None)
    faces = getattr(geom, "faces", None)
    if verts is None or faces is None:
        return None
    v = np.asarray(verts, dtype=np.float64)
    f = np.asarray(faces, dtype=np.int64)
    if v.ndim != 2 or v.shape[0] < 3 or v.shape[1] != 3:
        return None
    if f.ndim != 2 or f.shape[0] < 1 or f.shape[1] != 3:
        return None
    if not np.isfinite(v).all():
        return None
    # Drop out-of-range indices defensively.
    in_range = (f >= 0).all(axis=1) & (f < v.shape[0]).all(axis=1)
    f = f[in_range]
    if f.shape[0] == 0:
        return None
    tris = v[f]  # (T,3,3)

    # Discard zero-area (degenerate / collinear) triangles - they cannot
    # bound a volume and break the Möller plane test.
    e1 = tris[:, 1] - tris[:, 0]
    e2 = tris[:, 2] - tris[:, 0]
    cross = np.cross(e1, e2)
    area2 = np.einsum("ij,ij->i", cross, cross)  # 4·area²
    keep = area2 > (_EPS * _EPS)
    tris = tris[keep]
    if tris.shape[0] == 0:
        return None

    if tris.shape[0] > _MAX_TRIS_PER_ELEMENT:
        a2 = area2[keep]
        # Largest-area-first, stable so equal-area ties keep input order →
        # the decimation is fully deterministic across runs/platforms.
        order = np.argsort(-a2, kind="stable")[:_MAX_TRIS_PER_ELEMENT]
        order = np.sort(order)
        tris = tris[order]
    return tris


def _obb(geom: object) -> tuple[np.ndarray, np.ndarray, np.ndarray] | None:
    """``(center(3,), axes(3,3) unit rows, half(3,))`` or ``None``."""
    c = getattr(geom, "obb_center", None)
    ax = getattr(geom, "obb_axes", None)
    hf = getattr(geom, "obb_half", None)
    if c is None or ax is None or hf is None:
        return None
    c = np.asarray(c, dtype=np.float64).reshape(3)
    ax = np.asarray(ax, dtype=np.float64).reshape(3, 3)
    hf = np.asarray(hf, dtype=np.float64).reshape(3)
    if not (np.isfinite(c).all() and np.isfinite(ax).all() and np.isfinite(hf).all()):
        return None
    return c, ax, hf


def _obb_sat_overlap(
    a: tuple[np.ndarray, np.ndarray, np.ndarray],
    b: tuple[np.ndarray, np.ndarray, np.ndarray],
) -> bool:
    """OBB–OBB Separating Axis Theorem (15 axes) - True iff *not* separated.

    Classic Gottschalk SAT: 3 A-face axes, 3 B-face axes, 9 edge×edge
    cross products. A small epsilon is added to the cross-product test to
    absorb the near-parallel-edge degeneracy. This is a conservative
    quick *reject* - a False guarantees disjoint OBBs (and therefore
    disjoint meshes); a True only means "cannot rule out".
    """
    ca, ax_a, ha = a
    cb, ax_b, hb = b
    t = cb - ca
    # R[i,j] = A_i · B_j ; project the centre offset into A's frame.
    r = ax_a @ ax_b.T
    abs_r = np.abs(r) + 1e-12
    t_a = ax_a @ t

    # 3 axes - faces of A.
    for i in range(3):
        ra = ha[i]
        rb = hb[0] * abs_r[i, 0] + hb[1] * abs_r[i, 1] + hb[2] * abs_r[i, 2]
        if abs(t_a[i]) > ra + rb:
            return False
    # 3 axes - faces of B.
    t_b = ax_b @ t
    for j in range(3):
        ra = ha[0] * abs_r[0, j] + ha[1] * abs_r[1, j] + ha[2] * abs_r[2, j]
        rb = hb[j]
        if abs(t_b[j]) > ra + rb:
            return False
    # 9 axes - edge cross products A_i × B_j.
    for i in range(3):
        i1, i2 = (i + 1) % 3, (i + 2) % 3
        for j in range(3):
            j1, j2 = (j + 1) % 3, (j + 2) % 3
            ra = ha[i1] * abs_r[i2, j] + ha[i2] * abs_r[i1, j]
            rb = hb[j1] * abs_r[i, j2] + hb[j2] * abs_r[i, j1]
            sep = abs(t_a[i2] * r[i1, j] - t_a[i1] * r[i2, j])
            if sep > ra + rb:
                return False
    return True


# ── Möller (1997) triangle–triangle intersection (vectorised) ──────────────


def _coplanar_tri_tri(t1: np.ndarray, t2: np.ndarray, normal: np.ndarray) -> bool:
    """Coplanar fallback: project to 2-D, test edge crossings + containment.

    Möller §"Coplanar triangles": project both triangles onto the axis
    plane where the shared normal is largest, then run the 2-D
    edge-vs-edge intersection plus point-in-triangle containment.
    """
    ax = int(np.argmax(np.abs(normal)))
    i0, i1 = [(1, 2), (0, 2), (0, 1)][ax]
    p1 = t1[:, [i0, i1]]
    p2 = t2[:, [i0, i1]]

    def _seg_cross(a, b, c, d) -> bool:
        def _o(u, v, w):
            return (v[0] - u[0]) * (w[1] - u[1]) - (v[1] - u[1]) * (w[0] - u[0])

        d1, d2 = _o(c, d, a), _o(c, d, b)
        d3, d4 = _o(a, b, c), _o(a, b, d)
        if ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0)):
            return True
        return False

    for ia in range(3):
        a, b = p1[ia], p1[(ia + 1) % 3]
        for ib in range(3):
            c, d = p2[ib], p2[(ib + 1) % 3]
            if _seg_cross(a, b, c, d):
                return True

    def _inside(pt, tri) -> bool:
        d = tri - pt
        s = (
            d[0, 0] * d[1, 1] - d[0, 1] * d[1, 0],
            d[1, 0] * d[2, 1] - d[1, 1] * d[2, 0],
            d[2, 0] * d[0, 1] - d[2, 1] * d[0, 0],
        )
        return (s[0] >= 0 and s[1] >= 0 and s[2] >= 0) or (s[0] <= 0 and s[1] <= 0 and s[2] <= 0)

    return _inside(p1[0], p2) or _inside(p2[0], p1)


def _tri_tri_intersect_mask(A: np.ndarray, B: np.ndarray) -> np.ndarray:
    """Vectorised Möller (1997): ``(len(A), len(B))`` boolean intersect mask.

    For every (a, b) triangle pair this computes the canonical Möller
    test: signed distances of each triangle's vertices to the *other*
    triangle's plane (early reject if all same-sign & non-zero), then the
    overlap of the two intervals carved on the line L = plane1 ∩ plane2.
    Coplanar pairs are routed to :func:`_coplanar_tri_tri`.

    Broadcasting shape convention: A → axis 0 (i), B → axis 1 (j).

    The signed point–plane distances are **normalised** (divided by the
    triangle normal's magnitude) so the near-zero snap below is a true
    Euclidean ~1 nm tolerance, scale-consistent across triangle sizes. A
    raw Möller ``n·v + d`` is scaled by ``|n|``; for a small / thin
    (sliver) triangle ``|n|`` is tiny, so an *absolute* epsilon on the
    raw value behaves like a huge geometric tolerance and two surfaces
    several micrometres apart get mis-snapped onto the plane → falsely
    flagged coplanar → a phantom clash. Normalising removes that
    false-positive class and makes the result independent of triangle
    scale and of floating-point summation order (deterministic across
    numpy builds / platforms). ``_interval_overlap`` consumes only
    per-triangle distance *ratios*, so this per-triangle rescale leaves
    the interval test bit-identical - it changes only the (now correct)
    sign / coplanar / reject decision.

    An exact per-triangle AABB prefilter runs first: two triangles whose
    axis-aligned boxes are disjoint provably cannot intersect, so the
    (normalised) Möller test would reject them anyway. Only the
    AABB-overlapping candidate pairs therefore have their signed
    distances / interval test computed - this avoids materialising the
    dense ``(na, nb, 3)`` distance tensors for the (usually vast)
    majority of non-overlapping pairs, cutting the dominant cost and
    bounding peak memory, while remaining consistent with the normalised
    plane test (both use the same ~1 nm geometric scale).
    """
    na, nb = A.shape[0], B.shape[0]
    out = np.zeros((na, nb), dtype=bool)
    if na == 0 or nb == 0:
        return out

    # --- Per-triangle plane (cheap, O(na)+O(nb)).
    n1 = np.cross(A[:, 1] - A[:, 0], A[:, 2] - A[:, 0])  # (na,3)
    d1 = -np.einsum("ij,ij->i", n1, A[:, 0])  # (na,)
    n2 = np.cross(B[:, 1] - B[:, 0], B[:, 2] - B[:, 0])  # (nb,3)
    d2 = -np.einsum("ij,ij->i", n2, B[:, 0])  # (nb,)

    # --- Exact AABB prefilter → candidate (a,b) index pairs only.
    a_lo = A.min(axis=1)  # (na,3)
    a_hi = A.max(axis=1)
    b_lo = B.min(axis=1)  # (nb,3)
    b_hi = B.max(axis=1)
    overlap = (
        (a_lo[:, None, 0] <= b_hi[None, :, 0] + _EPS)
        & (b_lo[None, :, 0] <= a_hi[:, None, 0] + _EPS)
        & (a_lo[:, None, 1] <= b_hi[None, :, 1] + _EPS)
        & (b_lo[None, :, 1] <= a_hi[:, None, 1] + _EPS)
        & (a_lo[:, None, 2] <= b_hi[None, :, 2] + _EPS)
        & (b_lo[None, :, 2] <= a_hi[:, None, 2] + _EPS)
    )
    ai, bj = np.where(overlap)
    if ai.size == 0:
        return out

    # --- Signed distances on the candidate pairs only → (P,3) each.
    a_c = A[ai]  # (P,3,3)
    b_c = B[bj]
    n1c = n1[ai]
    n2c = n2[bj]
    # Per-triangle inverse normal magnitude → true Euclidean point-plane
    # distance. ``_triangles`` discards zero-area triangles (area² > _EPS²)
    # so |n| ≥ _EPS > 0 and the reciprocal is finite.
    inv1c = 1.0 / np.sqrt(np.einsum("pk,pk->p", n1c, n1c))  # (P,)
    inv2c = 1.0 / np.sqrt(np.einsum("pk,pk->p", n2c, n2c))  # (P,)
    # B's 3 verts vs A's plane; A's 3 verts vs B's plane (normalised).
    dB = (np.einsum("pk,pvk->pv", n1c, b_c) + d1[ai][:, None]) * inv1c[:, None]
    dB = np.where(np.abs(dB) < _EPS, 0.0, dB)
    sB = np.sign(dB)
    same_B = (sB[:, 0] == sB[:, 1]) & (sB[:, 1] == sB[:, 2]) & (sB[:, 0] != 0)
    dA = (np.einsum("pk,pvk->pv", n2c, a_c) + d2[bj][:, None]) * inv2c[:, None]
    dA = np.where(np.abs(dA) < _EPS, 0.0, dA)
    sA = np.sign(dA)
    same_A = (sA[:, 0] == sA[:, 1]) & (sA[:, 1] == sA[:, 2]) & (sA[:, 0] != 0)

    # Trivial reject: one triangle wholly on one side of the other's plane.
    cand = ~(same_B | same_A)
    coplanar = (np.abs(dB).sum(axis=-1) < _EPS) & (np.abs(dA).sum(axis=-1) < _EPS)

    m_int = cand & ~coplanar
    if m_int.any():
        out[ai[m_int], bj[m_int]] = _interval_overlap(
            a_c[m_int],
            b_c[m_int],
            n1c[m_int],
            n2c[m_int],
            dA[m_int],
            dB[m_int],
        )

    # Coplanar pairs (rare) handled with the 2-D fallback, one at a time.
    for p in np.where(cand & coplanar)[0].tolist():
        if _coplanar_tri_tri(a_c[p], b_c[p], n1c[p]):
            out[ai[p], bj[p]] = True
    return out


def _interval_overlap(
    A: np.ndarray,
    B: np.ndarray,
    n1: np.ndarray,
    n2: np.ndarray,
    distA: np.ndarray,
    distB: np.ndarray,
) -> np.ndarray:
    """Möller interval test on L = plane(A) ∩ plane(B).

    Direction of L is ``n1 × n2``. Each triangle's three vertices
    projected onto L yield a parameter; the two vertices on the *same*
    side of the other plane are interpolated with the lone vertex to give
    the scalar interval the triangle carves on L. The triangles intersect
    iff those two 1-D intervals overlap. Fully vectorised over the P
    surviving pairs.
    """
    d = np.cross(n1, n2)  # line direction, (P,3)
    ax = np.argmax(np.abs(d), axis=1)  # dominant component → projection axis

    # Per pair p, take the ax[p]-th coordinate of each of the 3 vertices.
    # A,B are (P,3verts,3coords); take_along_axis on the coord axis → (P,3).
    sel = ax[:, None, None]  # (P,1,1)
    pA = np.take_along_axis(A, sel, axis=2)[:, :, 0]  # (P,3)
    pB = np.take_along_axis(B, sel, axis=2)[:, :, 0]  # (P,3)

    def _interval(p: np.ndarray, dist: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        # The vertex whose sign differs from the other two is the "lone"
        # one; choose its index per-pair, then interpolate the two
        # crossing points along the triangle edges meeting it.
        s = np.sign(dist)
        s = np.where(dist == 0.0, 0.0, s)
        # The "lone" vertex is the one whose sign differs from the other
        # two (Möller). Fully vectorised: default 0; if s0==s1 the odd one
        # out is vertex 2; else if s0==s2 it is vertex 1; else vertex 0.
        lone = np.where(s[:, 0] == s[:, 1], 2, np.where(s[:, 0] == s[:, 2], 1, 0)).astype(np.int64)
        idx = np.arange(p.shape[0])
        o = lone
        a1 = (o + 1) % 3
        a2 = (o + 2) % 3
        po, pa1, pa2 = p[idx, o], p[idx, a1], p[idx, a2]
        do, da1, da2 = dist[idx, o], dist[idx, a1], dist[idx, a2]
        # Two crossing points: edge (o→a1) and edge (o→a2).
        denom1 = do - da1
        denom2 = do - da2
        denom1 = np.where(np.abs(denom1) < _EPS, _EPS, denom1)
        denom2 = np.where(np.abs(denom2) < _EPS, _EPS, denom2)
        t1 = po + (pa1 - po) * (do / denom1)
        t2 = po + (pa2 - po) * (do / denom2)
        lo = np.minimum(t1, t2)
        hi = np.maximum(t1, t2)
        return lo, hi

    loA, hiA = _interval(pA, distA)
    loB, hiB = _interval(pB, distB)
    # Closed-interval overlap (touching counts as intersecting at this
    # stage; the penetration-depth gate downstream removes mere touches).
    return (loA <= hiB + _EPS) & (loB <= hiA + _EPS)


# ── Vectorised point ↔ triangle distance (clearance phase) ─────────────────


def _point_tri_dist2(pts: np.ndarray, tri: np.ndarray) -> np.ndarray:
    """Squared distance from each point in ``pts`` (P,3) to triangle ``tri``.

    Ericson, *Real-Time Collision Detection* §5.1.5 closest-point-on-
    triangle via Voronoi regions, vectorised over the P query points.
    """
    a, b, c = tri[0], tri[1], tri[2]
    ab = b - a
    ac = c - a
    ap = pts - a  # (P,3)

    d1 = ap @ ab
    d2 = ap @ ac
    bp = pts - b
    d3 = bp @ ab
    d4 = bp @ ac
    cp = pts - c
    d5 = cp @ ab
    d6 = cp @ ac

    vc = d1 * d4 - d3 * d2
    vb = d5 * d2 - d1 * d6
    va = d3 * d6 - d5 * d4

    closest = np.empty_like(pts)

    # Region A
    m = (d1 <= 0) & (d2 <= 0)
    closest[m] = a
    done = m.copy()
    # Region B
    m = (~done) & (d3 >= 0) & (d4 <= d3)
    closest[m] = b
    done |= m
    # Region C
    m = (~done) & (d6 >= 0) & (d5 <= d6)
    closest[m] = c
    done |= m
    # Edge AB
    m = (~done) & (vc <= 0) & (d1 >= 0) & (d3 <= 0)
    if m.any():
        denom = d1[m] - d3[m]
        v = np.where(np.abs(denom) < _EPS, 0.0, d1[m] / np.where(denom == 0, _EPS, denom))
        closest[m] = a + v[:, None] * ab
    done |= m
    # Edge AC
    m = (~done) & (vb <= 0) & (d2 >= 0) & (d6 <= 0)
    if m.any():
        denom = d2[m] - d6[m]
        v = np.where(np.abs(denom) < _EPS, 0.0, d2[m] / np.where(denom == 0, _EPS, denom))
        closest[m] = a + v[:, None] * ac
    done |= m
    # Edge BC
    m = (~done) & (va <= 0) & ((d4 - d3) >= 0) & ((d5 - d6) >= 0)
    if m.any():
        denom = (d4[m] - d3[m]) + (d5[m] - d6[m])
        w = np.where(np.abs(denom) < _EPS, 0.0, (d4[m] - d3[m]) / np.where(denom == 0, _EPS, denom))
        closest[m] = b + w[:, None] * (c - b)
    done |= m
    # Interior (barycentric)
    m = ~done
    if m.any():
        denom = va[m] + vb[m] + vc[m]
        denom = np.where(np.abs(denom) < _EPS, _EPS, denom)
        v = vb[m] / denom
        w = vc[m] / denom
        closest[m] = a + ab * v[:, None] + ac * w[:, None]

    diff = pts - closest
    return np.einsum("ij,ij->i", diff, diff)


def _min_mesh_distance(A: np.ndarray, B: np.ndarray) -> tuple[float, np.ndarray, np.ndarray]:
    """Real minimum surface gap between two triangle meshes (sampled).

    Symmetric: every vertex of A is tested against every triangle of B
    and vice-versa, returning the smallest distance plus the closest
    point pair (for the clash centroid). This is a *measured* surface
    gap - not a bounding-box gap - so a clearance result reflects the
    true free space between the two solids.
    """
    vA = A.reshape(-1, 3)
    vB = B.reshape(-1, 3)
    best = math.inf
    pa = np.zeros(3)
    pb = np.zeros(3)

    for tri in B:
        d2 = _point_tri_dist2(vA, tri)
        k = int(np.argmin(d2))
        if d2[k] < best:
            best = float(d2[k])
            pa = vA[k]
            # Recover closest point on this tri for the centroid.
            pb = _closest_on_tri(vA[k], tri)
    for tri in A:
        d2 = _point_tri_dist2(vB, tri)
        k = int(np.argmin(d2))
        if d2[k] < best:
            best = float(d2[k])
            pb = vB[k]
            pa = _closest_on_tri(vB[k], tri)
    return math.sqrt(max(best, 0.0)), pa, pb


def _closest_on_tri(p: np.ndarray, tri: np.ndarray) -> np.ndarray:
    """Single closest point on ``tri`` to ``p`` (scalar wrapper)."""
    out = np.empty((1, 3))
    pp = p.reshape(1, 3)
    # Reuse the vectorised routine's geometry by reconstructing closest.
    a, b, c = tri[0], tri[1], tri[2]
    ab, ac, ap = b - a, c - a, (pp - a)[0]
    d1, d2 = ap @ ab, ap @ ac
    if d1 <= 0 and d2 <= 0:
        return a
    bp = (pp - b)[0]
    d3, d4 = bp @ ab, bp @ ac
    if d3 >= 0 and d4 <= d3:
        return b
    cp = (pp - c)[0]
    d5, d6 = cp @ ab, cp @ ac
    if d6 >= 0 and d5 <= d6:
        return c
    vc = d1 * d4 - d3 * d2
    if vc <= 0 and d1 >= 0 and d3 <= 0:
        v = d1 / (d1 - d3) if abs(d1 - d3) > _EPS else 0.0
        return a + v * ab
    vb = d5 * d2 - d1 * d6
    if vb <= 0 and d2 >= 0 and d6 <= 0:
        v = d2 / (d2 - d6) if abs(d2 - d6) > _EPS else 0.0
        return a + v * ac
    va = d3 * d6 - d5 * d4
    if va <= 0 and (d4 - d3) >= 0 and (d5 - d6) >= 0:
        den = (d4 - d3) + (d5 - d6)
        w = (d4 - d3) / den if abs(den) > _EPS else 0.0
        return b + w * (c - b)
    den = va + vb + vc
    den = den if abs(den) > _EPS else _EPS
    v, w = vb / den, vc / den
    out[0] = a + ab * v + ac * w
    return out[0]


def _penetration_depth(A: np.ndarray, B: np.ndarray, mask: np.ndarray) -> tuple[float, np.ndarray]:
    """Honest penetration estimate from the *actually intersecting* tris.

    Collect the vertices of every triangle pair flagged intersecting,
    take the overlap extent of the two intersecting-vertex point sets
    along each world axis, and return the **minimum** axis overlap (the
    shallowest direction you'd have to separate the solids - the same
    "tightest axis" semantics the bbox engine used, but now derived from
    real intersecting geometry rather than whole-element AABBs). The
    second value is the centroid of those intersecting vertices.

    This is an approximation (axis-aligned, vertex-set based), documented
    as such: it is conservative and monotone in true penetration, which
    is exactly what the ``tolerance_m`` gate needs.
    """
    ai, bj = np.where(mask)
    if ai.size == 0:
        return 0.0, np.zeros(3)
    pa = A[ai].reshape(-1, 3)
    pb = B[bj].reshape(-1, 3)
    lo = np.maximum(pa.min(axis=0), pb.min(axis=0))
    hi = np.minimum(pa.max(axis=0), pb.max(axis=0))
    # Per-axis overlap of the two intersecting-vertex point sets, clamped
    # at 0 (a negative means the sets are disjoint on that axis - no
    # penetration contribution there). The penetration depth is the
    # *minimum* axis overlap: the shallowest direction along which the
    # solids would have to be separated. For a coincident-face touch the
    # separating axis has ~0 overlap → pen ≈ 0 → correctly below
    # tolerance, so a slab-on-wall cosmetic contact is NOT a hard clash,
    # while a real interpenetration yields the true tightest-axis depth.
    overlap = np.clip(hi - lo, 0.0, None)
    pen = float(overlap.min())
    centroid = np.vstack([pa, pb]).mean(axis=0)
    return pen, centroid


class ClashService:
    """Stateless clash orchestration over one project's BIM models."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = ClashRepository(session)

    # ── Run lifecycle ──────────────────────────────────────────────────

    async def create_run(
        self,
        project_id: uuid.UUID,
        data: ClashRunCreate,
        user_id: str,
        *,
        spatial_grid_mm: int | None = None,
    ) -> ClashRun:
        """Persist + execute a clash run synchronously, return it complete.

        ``spatial_grid_mm`` overrides the smart-issue signature grid on the
        run (used by the apply-profile path to carry the profile's grid);
        ``None`` keeps the model default (500 mm).
        """
        models = await self.repo.models_for_project(project_id)
        valid_ids = {m.id for m in models}
        requested = [mid for mid in data.model_ids if mid in valid_ids]
        if not requested:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="None of the requested models belong to this project",
            )
        if data.mode not in ("cross_discipline", "all", "selected", "selection_sets"):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Unknown clash mode '{data.mode}'",
            )
        if data.clash_type not in CLASH_TYPES:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Unknown clash type '{data.clash_type}' (expected one of {', '.join(CLASH_TYPES)})",
            )
        set_a = set_b = None
        if data.mode == "selection_sets":
            if data.set_a is None or data.set_b is None or data.set_a.is_empty or data.set_b.is_empty:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="selection_sets mode requires a non-empty "
                    "Set A and Set B (pick at least one type or "
                    "discipline for each).",
                )
            set_a = data.set_a.model_dump()
            set_b = data.set_b.model_dump()

        name = (data.name or "").strip() or (f"Clash run {_now():%Y-%m-%d %H:%M}")
        # Wave A4 - initial rule set carried straight from the request.
        # The engine consults the (possibly empty) list during the broad
        # phase; the rule editor endpoints (PATCH /rules) can mutate it
        # post-hoc without re-running the engine.
        rules_payload = [r.model_dump() for r in (data.rules or [])]
        run = ClashRun(
            project_id=project_id,
            name=name,
            description=(data.description or "").strip() or None,
            model_ids=[str(m) for m in requested],
            clash_type=data.clash_type,
            ignore_same_model=bool(data.ignore_same_model),
            tolerance_m=data.tolerance_m,
            clearance_m=data.clearance_m,
            mode=data.mode,
            discipline_filter=data.discipline_filter,
            set_a=set_a,
            set_b=set_b,
            status="running",
            created_by=str(user_id),
            summary={},
            rules=rules_payload,
            spatial_grid_mm=int(spatial_grid_mm) if spatial_grid_mm else _DEFAULT_SPATIAL_GRID_MM,
        )
        self.repo.add_run(run)
        await self.session.flush()

        try:
            geoms = await self._load_geometry(requested)
            elements = await self.repo.elements_with_geometry(requested)
            results = self._detect(run, elements, geoms)
            self.repo.add_results(results)
            if data.carry_forward:
                await self._carry_forward(run, results)
            run.element_count = len(elements)
            run.total_clashes = len(results)
            run.summary = _build_summary(results)
            # Wave A4 - spatial cluster pass over centroids. Pure
            # write-only: failures degrade to "no clusters" rather than
            # failing the whole run.
            try:
                await self._persist_clusters(run, results)
            except Exception:  # noqa: BLE001 - clustering is best-effort
                logger.exception("Clash run %s cluster pass failed", run.id)
            # v41 - smart-issue upsert + finalize. Best-effort: failures
            # leave the run rows in place but skip the smart-issue write.
            try:
                await self.session.flush()
                for clash in results:
                    if clash.signature_hash:
                        await self.upsert_clash_with_signature(run, clash)
                run.status = "completed"
                run.completed_at = _now()
                await self.finalize_run(run)
            except Exception:  # noqa: BLE001 - smart issues are best-effort
                logger.exception("Clash run %s smart-issue upsert failed", run.id)
                run.status = "completed"
                run.completed_at = _now()
        except Exception as exc:  # noqa: BLE001 - surface, don't 500 the run
            logger.exception("Clash run %s failed", run.id)
            run.status = "failed"
            run.error = f"{type(exc).__name__}: {exc}"[:2000]
            run.completed_at = _now()
        await self.session.flush()
        # Fan a high-severity alert out per critical/high clash so the run
        # owner learns about serious interferences without polling. Detached
        # so the publish never blocks the synchronous run response; the
        # helper itself filters out non-high severities.
        if run.status == "completed":
            for clash in results:
                self._publish_high_severity(
                    clash,
                    project_id=project_id,
                    run_id=run.id,
                    trigger=TRIGGER_CREATED,
                    actor=str(user_id),
                )
        return run

    async def _load_geometry(self, model_ids: list[uuid.UUID]) -> dict[str, object]:
        """Best-effort load of real GLB triangle meshes per element.

        Returns ``{element_id: ElementGeom}``. If the geometry provider
        is unavailable (sibling module not yet present) or a model has no
        GLB, the dict is simply missing those elements and the broad
        phase transparently falls back to the canonical bbox.
        """
        if ClashGeometryProvider is None:
            return {}
        merged: dict[str, object] = {}
        provider = ClashGeometryProvider()
        for mid in model_ids:
            try:
                part = await provider.load(self.session, mid)
            except Exception:  # noqa: BLE001 - degrade to bbox for this model
                logger.exception("Geometry load failed for model %s", mid)
                continue
            if part:
                merged.update(part)
        return merged

    async def _carry_forward(self, run: ClashRun, results: list[ClashResult]) -> None:
        """Persist triage across re-runs by matching clash signatures.

        Find the most recent *completed* run of this project that shares
        a model with the new run; for every new result whose
        ``signature`` matches a prior result's, copy forward the human
        triage state - ``status`` (unless the prior was still ``new``),
        ``assigned_to``, ``due_date`` and ``comments`` (prior comments
        are *prepended*, oldest-context-first). Fully defensive: any
        missing prior run / result / malformed payload simply skips
        carry-forward for that row - it never breaks the new run.
        """
        try:
            prior_run = await self.repo.latest_prior_completed_run(
                run.project_id,
                list(run.model_ids or []),
                exclude_run_id=run.id,
            )
            if prior_run is None:
                return
            prior_rows = await self.repo.all_results(prior_run.id)
        except Exception:  # noqa: BLE001 - carry-forward is best-effort
            logger.exception("Clash carry-forward lookup failed for run %s", run.id)
            return

        # Index prior rows by signature. On the (rare) signature collision
        # within one run keep the first - deterministic, order is the
        # repository's stable query order.
        by_sig: dict[str, ClashResult] = {}
        for pr in prior_rows:
            sig = getattr(pr, "signature", "") or ""
            if sig and sig not in by_sig:
                by_sig[sig] = pr

        for r in results:
            sig = getattr(r, "signature", "") or ""
            if not sig:
                continue
            prior = by_sig.get(sig)
            if prior is None:
                continue
            try:
                prior_status = getattr(prior, "status", "new") or "new"
                if prior_status not in ("new",):
                    r.status = prior_status
                if getattr(prior, "assigned_to", None):
                    r.assigned_to = prior.assigned_to
                if getattr(prior, "due_date", None):
                    r.due_date = prior.due_date
                prior_comments = list(getattr(prior, "comments", None) or [])
                if prior_comments:
                    r.comments = prior_comments + list(r.comments or [])
                # Wave A3 - carry watchers + audit log across re-runs so
                # subscriptions and history survive the engine rerun.
                prior_watchers = list(getattr(prior, "watchers", None) or [])
                if prior_watchers:
                    r.watchers = prior_watchers
                prior_history = list(getattr(prior, "history", None) or [])
                if prior_history:
                    r.history = prior_history
            except Exception:  # noqa: BLE001 - skip just this row
                logger.exception("Clash carry-forward failed for signature %s", sig)
                continue

    async def compare_runs(
        self,
        project_id: uuid.UUID,
        run_id: uuid.UUID,
        base_run_id: uuid.UUID,
    ) -> dict:
        """Diff ``run_id`` against ``base_run_id`` by clash signature.

        ``new`` = signatures only in the current run; ``resolved`` =
        signatures only in the base run; ``persistent`` = signatures in
        both, paired current↔base. Both runs are 404-guarded against the
        project so this can never leak another project's clashes.
        """
        await self.get_run(project_id, run_id)  # 404 if not in project
        await self.get_run(project_id, base_run_id)
        current = await self.repo.all_results(run_id)
        base = await self.repo.all_results(base_run_id)

        cur_by_sig: dict[str, ClashResult] = {}
        for r in current:
            sig = getattr(r, "signature", "") or ""
            if sig:
                cur_by_sig.setdefault(sig, r)
        base_by_sig: dict[str, ClashResult] = {}
        for r in base:
            sig = getattr(r, "signature", "") or ""
            if sig:
                base_by_sig.setdefault(sig, r)

        cur_sigs = set(cur_by_sig)
        base_sigs = set(base_by_sig)

        def _summary(r: ClashResult) -> dict:
            return {
                "id": r.id,
                "a_name": r.a_name,
                "b_name": r.b_name,
                "clash_type": r.clash_type,
                "severity": getattr(r, "severity", "medium") or "medium",
                "penetration_m": r.penetration_m,
                "distance_m": r.distance_m,
                "status": r.status,
                "assigned_to": r.assigned_to,
            }

        new = [_summary(cur_by_sig[s]) for s in sorted(cur_sigs - base_sigs)]
        resolved = [_summary(base_by_sig[s]) for s in sorted(base_sigs - cur_sigs)]
        persistent = [
            {
                "current": _summary(cur_by_sig[s]),
                "base": _summary(base_by_sig[s]),
            }
            for s in sorted(cur_sigs & base_sigs)
        ]
        return {
            "new": new,
            "resolved": resolved,
            "persistent": persistent,
            "stats": {
                "new": len(new),
                "resolved": len(resolved),
                "persistent": len(persistent),
                "base_total": len(base),
                "current_total": len(current),
            },
        }

    # ── Smart-issue identity (v41) ─────────────────────────────────────

    @staticmethod
    def compute_signature(
        *,
        a_guid: str | None,
        b_guid: str | None,
        centroid: tuple[float, float, float],
        clash_type: str,
        grid_mm: int = _DEFAULT_SPATIAL_GRID_MM,
        weak_fallback: tuple[str, str, list[str]] | None = None,
    ) -> tuple[str, str]:
        """Public, stateless signature computation - see :func:`_compute_signature_hash`.

        Exposed on the service so callers and tests don't reach into the
        private helper. Returns ``(signature_hash, quality)``.
        """
        return _compute_signature_hash(
            a_guid=a_guid,
            b_guid=b_guid,
            centroid=centroid,
            clash_type=clash_type,
            grid_mm=grid_mm,
            weak_fallback=weak_fallback,
        )

    async def _format_server_id(self, project_id: uuid.UUID) -> str:
        """Allocate the next ``CLASH-NNN`` id for ``project_id``."""
        n = await self.repo.next_issue_seq(project_id)
        return f"CLASH-{n:03d}"

    async def upsert_clash_with_signature(
        self,
        run: ClashRun,
        clash: ClashResult,
    ) -> ClashIssue:
        """Find or create the smart issue for one clash row and link it.

        The result row's ``signature_hash`` and ``signature_quality`` are
        assumed to be stamped already (the engine path sets them in
        :meth:`_row`; callers using this API on hand-built rows should
        compute them via :meth:`compute_signature` first).

        On insert: creates a fresh :class:`ClashIssue` with the project-
        scoped server-assigned id (``CLASH-NNN``) and ``status='new'``.
        On hit: bumps ``last_seen_run_id`` and resets ``missing_run_count``,
        flipping ``resolved`` issues to ``persisted`` (a reopen) and
        ``archived`` ones back to ``persisted`` as well. Suppressed
        signatures stay ``ignored``. ``new`` becomes ``persisted`` only
        when this is the second or later run that's seen it.

        Returns the (now-linked) :class:`ClashIssue`.
        """
        sig = (clash.signature_hash or "").strip()
        if not sig:
            raise ValueError("ClashResult.signature_hash must be set before upsert")
        # Suppressed signatures resolve to an ignored issue and never
        # surface as new - but we still link the row so the UI can
        # explain why the clash is suppressed.
        suppressed = await self.repo.get_suppression(run.project_id, sig)
        existing = await self.repo.get_issue_by_signature(run.project_id, sig)
        if existing is None:
            server_id = await self._format_server_id(run.project_id)
            issue = ClashIssue(
                project_id=run.project_id,
                signature_hash=sig,
                status="ignored" if suppressed is not None else "new",
                first_seen_run_id=run.id,
                last_seen_run_id=run.id,
                missing_run_count=0,
                server_assigned_id=server_id,
                signature_quality=(clash.signature_quality or "strong"),
                tags=[],
            )
            self.repo.add_issue(issue)
            await self.session.flush()
            clash.issue_id = issue.id
            return issue
        # Hit - bump last_seen + reset missing count + transition status.
        existing.last_seen_run_id = run.id
        existing.missing_run_count = 0
        if suppressed is not None:
            # An active suppression always wins, regardless of prior status.
            existing.status = "ignored"
        else:
            prior_status = existing.status or "new"
            if prior_status in ("resolved", "archived"):
                # Reopen - the signature came back.
                existing.status = "persisted"
                existing.resolved_run_id = None
            elif prior_status == "new":
                # Second-or-later sighting → persisted.
                existing.status = "persisted"
            elif prior_status == "ignored":
                # Suppression must have been lifted between runs - flip
                # back to persisted so coordination can see it again.
                existing.status = "persisted"
            # ``persisted`` stays ``persisted``.
        clash.issue_id = existing.id
        return existing

    async def finalize_run(
        self,
        run: ClashRun,
    ) -> None:
        """Close the smart-issue diff for a freshly-completed run.

        Walks every existing :class:`ClashIssue` for the project and,
        for those *not* present in this run's signatures, bumps
        ``missing_run_count``. Issues that were present in the prior run
        but absent now flip ``new``/``persisted`` → ``resolved`` and stamp
        ``resolved_run_id``. Issues missing for ≥ ``_ARCHIVE_AFTER_MISSING``
        consecutive runs flip ``resolved`` → ``archived``. Suppressed
        issues are untouched (they stay ``ignored``).

        Idempotent on the same run - calling twice produces the same
        terminal state.
        """
        current_sigs = await self.repo.signatures_present_in_run(run.id)
        suppressed_sigs = await self.repo.suppressed_signatures_for_project(run.project_id)
        all_issues = await self.repo.issues_for_project(run.project_id)
        for issue in all_issues:
            sig = issue.signature_hash or ""
            if sig in suppressed_sigs:
                # Suppression overrides lifecycle; never archive or auto-
                # resolve an actively-suppressed signature.
                issue.status = "ignored"
                continue
            if sig in current_sigs:
                # Present this run - the upsert path already moved the
                # status forward, nothing else to do here.
                continue
            # Absent this run.
            prior_status = issue.status or "new"
            issue.missing_run_count = int(issue.missing_run_count or 0) + 1
            if prior_status in ("new", "persisted"):
                issue.status = "resolved"
                issue.resolved_run_id = run.id
            elif prior_status == "resolved":
                if issue.missing_run_count >= _ARCHIVE_AFTER_MISSING:
                    issue.status = "archived"
        await self.session.flush()

    async def suppress(
        self,
        project_id: uuid.UUID,
        signature_hash: str,
        reason: str,
        user_id: uuid.UUID | str | None,
    ) -> ClashSuppression:
        """Suppress a signature for a project + flip matching issues to ``ignored``.

        Idempotent - repeating the call updates the existing suppression's
        reason / user but does not create a duplicate row.
        """
        sig = (signature_hash or "").strip()
        if not sig:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="signature_hash is required",
            )
        rsn = (reason or "").strip()
        if not rsn:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="reason is required",
            )
        existing = await self.repo.get_suppression(project_id, sig)
        uid: uuid.UUID | None = None
        if user_id is not None:
            try:
                uid = uuid.UUID(str(user_id))
            except (TypeError, ValueError):
                uid = None
        if existing is None:
            existing = ClashSuppression(
                project_id=project_id,
                signature_hash=sig,
                reason=rsn,
                suppressed_by_user_id=uid,
            )
            self.repo.add_suppression(existing)
        else:
            existing.reason = rsn
            if uid is not None:
                existing.suppressed_by_user_id = uid
        # Flip every matching issue to ``ignored``.
        matching = await self.repo.get_issue_by_signature(project_id, sig)
        if matching is not None:
            matching.status = "ignored"
        await self.session.flush()
        return existing

    async def unsuppress(
        self,
        project_id: uuid.UUID,
        signature_hash: str,
        user_id: uuid.UUID | str | None,  # noqa: ARG002 - kept for audit symmetry
    ) -> bool:
        """Remove a suppression + flip matching ``ignored`` issues back to ``persisted``.

        Returns True if a suppression row was deleted, False if none was
        found (idempotent no-op).
        """
        sig = (signature_hash or "").strip()
        if not sig:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="signature_hash is required",
            )
        existing = await self.repo.get_suppression(project_id, sig)
        if existing is None:
            return False
        await self.repo.delete_suppression(existing)
        # Flip the matching issue (if any) back to ``persisted`` - the
        # signature is once again "live" coordination work.
        matching = await self.repo.get_issue_by_signature(project_id, sig)
        if matching is not None and matching.status == "ignored":
            matching.status = "persisted"
        await self.session.flush()
        return True

    async def suppress_by_issue(
        self,
        project_id: uuid.UUID,
        issue_id: uuid.UUID,
        reason: str,
        user_id: uuid.UUID | str | None,
    ) -> ClashIssue:
        """Convenience wrapper used by the router (issue_id, not hash)."""
        issue = await self.repo.get_issue(project_id, issue_id)
        if issue is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Clash issue not found",
            )
        await self.suppress(project_id, issue.signature_hash, reason, user_id)
        return issue

    async def unsuppress_by_issue(
        self,
        project_id: uuid.UUID,
        issue_id: uuid.UUID,
        user_id: uuid.UUID | str | None,
    ) -> ClashIssue:
        """Convenience wrapper used by the router (issue_id, not hash)."""
        issue = await self.repo.get_issue(project_id, issue_id)
        if issue is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Clash issue not found",
            )
        await self.unsuppress(project_id, issue.signature_hash, user_id)
        return issue

    # TODO: expose via bulk endpoint - router.py is in flight with
    # another agent, so the service method is shipped on its own and
    # wired up in a follow-up patch.
    async def bulk_suppress(
        self,
        project_id: uuid.UUID,
        issue_ids: list[uuid.UUID],
        reason: str,
        user_id: uuid.UUID | str | None,
    ) -> dict:
        """Suppress many :class:`ClashIssue` rows in a single transaction.

        Atomic - either every authorized issue flips to ``ignored`` and
        gains a :class:`ClashSuppression` row, or nothing does (the
        caller's request-scoped session is rolled back on any error).

        IDOR-safe: ids that don't belong to ``project_id`` are silently
        dropped (the same defensive pattern as the single-issue path);
        the result's ``skipped_ids`` lists them so the caller can surface
        a structured warning. Idempotent: an issue already covered by a
        suppression row gets its ``reason`` updated in place - no duplicate
        rows and the audit trail still records the re-suppression.

        Empty ``issue_ids`` → returns the zero-counts envelope, never raises.

        Args:
            project_id: scoping project (every issue must belong to it).
            issue_ids: list of ``ClashIssue.id`` values to suppress.
            reason: free-text suppression reason (non-empty after strip).
            user_id: actor id for the audit trail (best-effort UUID coerced).

        Returns:
            ``{"suppressed_ids": [...], "skipped_ids": [...],
               "suppressed_count": int, "skipped_count": int}``

        Raises:
            HTTPException 422: ``reason`` is empty / whitespace-only.
        """
        rsn = (reason or "").strip()
        if not rsn:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="reason is required",
            )

        # Empty input is a legal no-op - the UI can wire an "Apply to
        # selected" button without first checking the selection length.
        if not issue_ids:
            return {
                "suppressed_ids": [],
                "skipped_ids": [],
                "suppressed_count": 0,
                "skipped_count": 0,
            }

        # De-duplicate while preserving order - the audit trail entries
        # below are emitted once per issue, never twice for a repeat id.
        seen: set[uuid.UUID] = set()
        unique_ids: list[uuid.UUID] = []
        for iid in issue_ids:
            if iid is None or iid in seen:
                continue
            seen.add(iid)
            unique_ids.append(iid)

        # Coerce user_id once - re-used on every audit + suppression row.
        uid: uuid.UUID | None = None
        if user_id is not None:
            try:
                uid = uuid.UUID(str(user_id))
            except (TypeError, ValueError):
                uid = None

        # IDOR gate: load only project-scoped rows. Anything missing is
        # an unauthorized / vanished id - reported back in ``skipped_ids``
        # so the UI never silently swallows a typo'd selection.
        authorized = await self.repo.get_issues_by_ids(project_id, unique_ids)
        authorized_by_id: dict[uuid.UUID, ClashIssue] = {i.id: i for i in authorized}
        skipped: list[uuid.UUID] = [iid for iid in unique_ids if iid not in authorized_by_id]

        signatures = [i.signature_hash for i in authorized if (i.signature_hash or "").strip()]
        existing_suppressions = await self.repo.get_suppressions_by_signatures(project_id, signatures)

        # Resolve actor string once for the audit log entries written to
        # each affected ClashResult's history JSON column.
        actor = await self.resolve_author(str(user_id)) if user_id else "system"

        suppressed_ids: list[uuid.UUID] = []
        for issue in authorized:
            sig = (issue.signature_hash or "").strip()
            if not sig:
                # Defensive: an issue without a signature hash can't be
                # suppressed (the suppression key IS the signature) - skip
                # it as if it had been unauthorized so the count is honest.
                skipped.append(issue.id)
                continue

            existing = existing_suppressions.get(sig)
            if existing is None:
                row = ClashSuppression(
                    project_id=project_id,
                    signature_hash=sig,
                    reason=rsn,
                    suppressed_by_user_id=uid,
                )
                self.repo.add_suppression(row)
                existing_suppressions[sig] = row
            else:
                # Idempotent re-suppression: update reason + actor in place.
                existing.reason = rsn
                if uid is not None:
                    existing.suppressed_by_user_id = uid

            prior_status = issue.status
            issue.status = "ignored"

            # Audit trail: fan out to every result row attached to this
            # issue so the per-clash Activity tab reflects the bulk op.
            from sqlalchemy import select as _select  # local import - see note

            res_stmt = _select(ClashResult).where(ClashResult.issue_id == issue.id)
            for r in (await self.session.execute(res_stmt)).scalars().all():
                self._append_history(r, actor, "suppression", prior_status, "ignored")

            suppressed_ids.append(issue.id)

        # Single flush at the end → atomic. If the flush raises, the
        # caller's session.rollback() (or AsyncSession context manager)
        # discards every change above so a partial bulk is impossible.
        await self.session.flush()

        return {
            "suppressed_ids": suppressed_ids,
            "skipped_ids": skipped,
            "suppressed_count": len(suppressed_ids),
            "skipped_count": len(skipped),
        }

    async def list_issues(
        self,
        project_id: uuid.UUID,
        *,
        status_filter: str | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[list[tuple[ClashIssue, int]], int]:
        """Project-scoped list of smart issues with member counts."""
        if status_filter is not None and status_filter not in CLASH_ISSUE_STATUSES:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Invalid clash issue status '{status_filter}'",
            )
        return await self.repo.list_issues(
            project_id,
            status=status_filter,
            offset=offset,
            limit=limit,
        )

    async def run_diff(
        self,
        project_id: uuid.UUID,
        run_id: uuid.UUID,
    ) -> dict:
        """Smart-issue diff counts for a run vs the previous one.

        Returns ``{new, persisted, resolved, reopened, ignored}``. ``new`` =
        signatures first seen this run (i.e. their issue's
        ``first_seen_run_id == run_id``). ``persisted`` = signatures seen
        in both runs whose issue is currently ``persisted``. ``resolved``
        = signatures that were in the prior run but not this one
        (``resolved_run_id == run_id``). ``reopened`` = signatures whose
        issue had ``status='resolved'`` in the prior run but is back to
        ``persisted`` this run (the upsert path detects this). ``ignored``
        = signatures whose issue is currently ``ignored`` (suppressed).
        """
        run = await self.get_run(project_id, run_id)
        sigs_this_run = await self.repo.signatures_present_in_run(run_id)
        issues = await self.repo.issues_by_signatures(project_id, list(sigs_this_run))
        prev_run = await self.repo.previous_run(project_id, run_id)
        prev_sigs: set[str] = set()
        if prev_run is not None:
            prev_sigs = await self.repo.signatures_present_in_run(prev_run.id)

        new = 0
        persisted = 0
        reopened = 0
        ignored = 0
        for sig, issue in issues.items():
            st = (issue.status or "").lower()
            if st == "ignored":
                ignored += 1
                continue
            if str(issue.first_seen_run_id) == str(run_id):
                new += 1
                continue
            # First seen before this run and present again now. The upsert
            # path flipped a resolved/archived issue back to ``persisted``
            # and cleared ``resolved_run_id``, so the lifecycle signal is:
            # an issue is reopened this run iff it transitioned
            # resolved/archived -> persisted during this run, i.e. it was
            # absent from the previous run (``sig not in prev_sigs``) but
            # has an older identity. If it was also in the previous run it
            # simply persisted across both.
            if sig in prev_sigs:
                persisted += 1
            elif prev_run is not None:
                reopened += 1
        # Resolved: count of issues whose resolved_run_id == run_id (the
        # finalize_run pass stamps these).
        all_issues = await self.repo.issues_for_project(project_id)
        resolved = sum(1 for i in all_issues if i.resolved_run_id is not None and str(i.resolved_run_id) == str(run_id))
        return {
            "new": int(new),
            "persisted": int(persisted),
            "resolved": int(resolved),
            "reopened": int(reopened),
            "ignored": int(ignored),
        }

    async def list_runs(self, project_id: uuid.UUID) -> list[ClashRun]:
        return await self.repo.list_runs(project_id)

    async def get_run(self, project_id: uuid.UUID, run_id: uuid.UUID) -> ClashRun:
        run = await self.repo.get_run(project_id, run_id)
        if run is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Clash run not found")
        return run

    async def delete_run(self, project_id: uuid.UUID, run_id: uuid.UUID) -> None:
        run = await self.get_run(project_id, run_id)
        await self.repo.delete_run(run)

    # ── Persistent clash profiles (item #23) ───────────────────────────

    @staticmethod
    def _validate_profile_config(mode: str, clash_type: str) -> None:
        """Reject an unknown mode / clash_type before persisting a profile.

        Mirrors the guards in :meth:`create_run` so a profile can never be
        saved with config that would 422 the moment it is applied.
        """
        if mode not in ("cross_discipline", "all", "selected", "selection_sets"):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Unknown clash mode '{mode}'",
            )
        if clash_type not in CLASH_TYPES:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Unknown clash type '{clash_type}' (expected one of {', '.join(CLASH_TYPES)})",
            )

    async def create_profile(
        self,
        project_id: uuid.UUID,
        data: ClashProfileCreate,
        user_id: str,
    ) -> ClashProfile:
        """Save a run configuration as a named, reusable profile.

        Name uniqueness is enforced per project (a 409 on a clash) so the
        picker never shows two profiles with the same name. Selection sets
        / rules are stored as plain JSON snapshots.
        """
        name = data.name.strip()
        if not name:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Profile name must not be empty.",
            )
        self._validate_profile_config(data.mode, data.clash_type)
        existing = await self.repo.get_profile_by_name(project_id, name)
        if existing is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"A clash profile named '{name}' already exists in this project.",
            )
        profile = ClashProfile(
            project_id=project_id,
            name=name,
            description=(data.description or "").strip() or None,
            clash_type=data.clash_type,
            ignore_same_model=bool(data.ignore_same_model),
            tolerance_m=data.tolerance_m,
            clearance_m=data.clearance_m,
            mode=data.mode,
            discipline_filter=data.discipline_filter,
            set_a=data.set_a.model_dump() if data.set_a is not None else None,
            set_b=data.set_b.model_dump() if data.set_b is not None else None,
            rules=[r.model_dump() for r in (data.rules or [])],
            spatial_grid_mm=int(data.spatial_grid_mm),
            created_by=str(user_id),
        )
        self.repo.add_profile(profile)
        await self.session.flush()
        return profile

    async def list_profiles(self, project_id: uuid.UUID) -> list[ClashProfile]:
        return await self.repo.list_profiles(project_id)

    async def get_profile(self, project_id: uuid.UUID, profile_id: uuid.UUID) -> ClashProfile:
        profile = await self.repo.get_profile(project_id, profile_id)
        if profile is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Clash profile not found")
        return profile

    async def update_profile(
        self,
        project_id: uuid.UUID,
        profile_id: uuid.UUID,
        data: ClashProfileUpdate,
        user_id: str,
    ) -> ClashProfile:
        """Patch a profile in place (only supplied fields change).

        ``updated_at`` is bumped by the ORM ``onupdate`` whenever any
        column is dirtied. Renaming to an already-taken name 409s.
        """
        profile = await self.get_profile(project_id, profile_id)
        fields = data.model_dump(exclude_unset=True)
        if "name" in fields:
            new_name = (fields["name"] or "").strip()
            if not new_name:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Profile name must not be empty.",
                )
            if new_name != profile.name:
                clash = await self.repo.get_profile_by_name(project_id, new_name)
                if clash is not None and clash.id != profile.id:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail=f"A clash profile named '{new_name}' already exists in this project.",
                    )
            profile.name = new_name
        if "description" in fields:
            profile.description = (fields["description"] or "").strip() or None
        # Validate config changes against the same guards as a run.
        new_mode = fields.get("mode", profile.mode)
        new_ctype = fields.get("clash_type", profile.clash_type)
        if "mode" in fields or "clash_type" in fields:
            self._validate_profile_config(new_mode, new_ctype)
        if "clash_type" in fields:
            profile.clash_type = fields["clash_type"]
        if "ignore_same_model" in fields:
            profile.ignore_same_model = bool(fields["ignore_same_model"])
        if "tolerance_m" in fields:
            profile.tolerance_m = float(fields["tolerance_m"])
        if "clearance_m" in fields:
            profile.clearance_m = float(fields["clearance_m"])
        if "mode" in fields:
            profile.mode = fields["mode"]
        if "discipline_filter" in fields:
            profile.discipline_filter = fields["discipline_filter"]
        if "set_a" in fields:
            sa = data.set_a
            profile.set_a = sa.model_dump() if sa is not None else None
        if "set_b" in fields:
            sb = data.set_b
            profile.set_b = sb.model_dump() if sb is not None else None
        if "rules" in fields and data.rules is not None:
            profile.rules = [r.model_dump() for r in data.rules][:500]
        if "spatial_grid_mm" in fields:
            profile.spatial_grid_mm = int(fields["spatial_grid_mm"])
        await self.session.flush()
        return profile

    async def delete_profile(self, project_id: uuid.UUID, profile_id: uuid.UUID) -> None:
        profile = await self.get_profile(project_id, profile_id)
        await self.repo.delete_profile(profile)

    async def apply_profile_to_new_run(
        self,
        project_id: uuid.UUID,
        profile_id: uuid.UUID,
        data: ClashProfileApplyRequest,
        user_id: str,
    ) -> ClashRun:
        """Launch + execute a fresh clash run using a profile as template.

        The profile supplies every engine parameter; the caller supplies
        the models to test plus an optional run name. The run snapshots
        the config (so a later profile edit never mutates a past run).
        """
        profile = await self.get_profile(project_id, profile_id)
        run_create = ClashRunCreate(
            name=(data.name or "").strip() or f"{profile.name} run {_now():%Y-%m-%d %H:%M}",
            description=profile.description,
            model_ids=list(data.model_ids),
            clash_type=profile.clash_type,
            ignore_same_model=bool(profile.ignore_same_model),
            tolerance_m=float(profile.tolerance_m),
            clearance_m=float(profile.clearance_m),
            mode=profile.mode,
            discipline_filter=profile.discipline_filter,
            set_a=ClashSelectionSet.model_validate(profile.set_a) if profile.set_a else None,
            set_b=ClashSelectionSet.model_validate(profile.set_b) if profile.set_b else None,
            carry_forward=bool(data.carry_forward),
            rules=[ClashRule.model_validate(r) for r in _coerce_rules(profile.rules)],
        )
        return await self.create_run(
            project_id,
            run_create,
            user_id,
            spatial_grid_mm=int(profile.spatial_grid_mm),
        )

    # ── Multi-dimensional grouping (item #23) ──────────────────────────

    async def grouped_summary(
        self,
        project_id: uuid.UUID,
        run_id: uuid.UUID,
        dimension: str,
    ) -> dict:
        """Group a run's clashes by one of the multi-dimensional axes.

        IDOR-guarded via :meth:`get_run`. ``dimension`` is one of
        :data:`CLASH_GROUPING_DIMENSIONS`; an unknown value degrades to
        ``discipline_pair`` (the default, forgiving param-normalisation
        the rest of the module already uses).
        """
        await self.get_run(project_id, run_id)
        if dimension not in CLASH_GROUPING_DIMENSIONS:
            dimension = "discipline_pair"
        rows = await self.repo.all_results(run_id)
        return _build_grouped_summary(rows, dimension)

    # ── Wave A4: clusters, rules, suggestions, KPI ─────────────────────

    async def _persist_clusters(self, run: ClashRun, results: list[ClashResult]) -> None:
        """Run DBSCAN over centroids → stamp ``cluster_id`` + ClashCluster.

        Pure side-effect over the result rows + the ``oe_clash_cluster``
        table. Skipped when there are fewer than two results (a single
        clash is never a "cluster"). The cluster pass is wrapped in a
        broad ``except`` by the caller - every failure mode here
        (degenerate centroids, DBSCAN cap, write error) leaves
        ``cluster_id`` columns at ``NULL`` and the chip group simply
        renders empty.
        """
        if not results or len(results) < _DEFAULT_CLUSTER_MIN_SAMPLES:
            return
        # Defensive copy of the existing rows so re-run replaces (the
        # carry-forward path may have produced a fresh list).
        await self.repo.clear_clusters(run.id)
        points = [(float(r.cx or 0.0), float(r.cy or 0.0), float(r.cz or 0.0)) for r in results]
        labels = _dbscan_cluster(points)
        # Group members by label so we can persist one ClashCluster per
        # bucket. ``None`` is DBSCAN noise - no row, no chip.
        buckets: dict[int, list[ClashResult]] = {}
        for r, cid in zip(results, labels, strict=False):
            r.cluster_id = cid
            if cid is None:
                continue
            buckets.setdefault(cid, []).append(r)
        if not buckets:
            return
        cluster_rows: list[ClashCluster] = []
        for cid, members in sorted(buckets.items()):
            label = _label_for_cluster(members, cid)
            cluster_rows.append(
                ClashCluster(
                    run_id=run.id,
                    cluster_id=cid,
                    label=label,
                    size=len(members),
                )
            )
        self.repo.add_clusters(cluster_rows)

    async def list_clusters(self, project_id: uuid.UUID, run_id: uuid.UUID) -> list[dict]:
        """Return ``[{cluster_id, label, size, dominant_disciplines, storey}]``.

        ``dominant_disciplines`` and ``storey`` are derived from the
        cluster's member rows (a single pass - no per-cluster DB query).
        IDOR-guarded via :meth:`get_run`.
        """
        await self.get_run(project_id, run_id)
        clusters = await self.repo.clusters_for_run(run_id)
        if not clusters:
            return []
        # Index members so we can attach the dominant pair + storey.
        rows = await self.repo.all_results(run_id)
        by_cluster: dict[int, list[ClashResult]] = {}
        for r in rows:
            cid = getattr(r, "cluster_id", None)
            if cid is None:
                continue
            by_cluster.setdefault(int(cid), []).append(r)

        out: list[dict] = []
        for c in clusters:
            members = by_cluster.get(int(c.cluster_id), [])
            dom_pair, dom_storey = _dominant_pair_and_storey(members)
            out.append(
                {
                    "cluster_id": int(c.cluster_id),
                    "label": c.label or "",
                    "size": int(c.size or len(members)),
                    "dominant_disciplines": list(dom_pair),
                    "storey": dom_storey,
                }
            )
        return out

    async def _cluster_members(self, run_id: uuid.UUID, cluster_id: int) -> list[ClashResult]:
        """Every result row stamped with ``cluster_id`` inside this run.

        Single in-memory filter over the run's rows (cluster sizes are
        small and bounded by the DBSCAN cap), so no per-cluster query.
        """
        rows = await self.repo.all_results(run_id)
        return [r for r in rows if getattr(r, "cluster_id", None) is not None and int(r.cluster_id) == int(cluster_id)]

    @staticmethod
    def _existing_action_link(members: list[ClashResult]) -> dict | None:
        """Return the first ``meta['linked_action']`` found on the members.

        The cluster→work-item link is stamped onto every member's ``meta``
        JSONB (there is no dedicated column / table), so any one member
        carrying a link means the whole group was already actioned. Used to
        keep :meth:`create_action_from_cluster` idempotent.
        """
        for m in members:
            link = (getattr(m, "meta", None) or {}).get("linked_action")
            if isinstance(link, dict) and link.get("action_id"):
                return link
        return None

    async def propose_cluster_action(
        self,
        project_id: uuid.UUID,
        run_id: uuid.UUID,
        cluster_id: int,
        target: str = "punchlist",
    ) -> dict:
        """AI-augmented draft for turning a clash cluster into a work item.

        IDOR-guarded via :meth:`get_run`. Raises 404 when the cluster has no
        members (unknown id / pre-clustering run). The returned dict matches
        :class:`ClashGroupActionProposal`; the engine only *proposes* - the
        coordinator reviews and confirms via :meth:`create_action_from_cluster`.
        When the group already has a linked work item the proposal carries
        ``already_linked=True`` + the existing id so the UI can disable the
        confirm button instead of spawning a duplicate.
        """
        await self.get_run(project_id, run_id)
        if target not in CLASH_ACTION_TARGETS:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Unknown action target '{target}' (expected one of {', '.join(CLASH_ACTION_TARGETS)})",
            )
        members = await self._cluster_members(run_id, cluster_id)
        if not members:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Clash cluster not found")
        clusters = await self.repo.clusters_for_run(run_id)
        label = next((c.label for c in clusters if int(c.cluster_id) == int(cluster_id)), "")
        proposal = _build_cluster_action_proposal(cluster_id, members, label or "", target)
        existing = self._existing_action_link(members)
        if existing is not None:
            proposal["already_linked"] = True
            proposal["existing_action_id"] = existing.get("action_id")
            proposal["existing_action_target"] = existing.get("target")
        return proposal

    async def create_action_from_cluster(
        self,
        project_id: uuid.UUID,
        run_id: uuid.UUID,
        cluster_id: int,
        *,
        target: str = "punchlist",
        title: str | None = None,
        description: str | None = None,
        priority: str | None = None,
        assigned_to: str | None = None,
        due_date: str | None = None,
        advance_status: bool = True,
        actor: str | None = None,
    ) -> dict:
        """Create one punch item / task from a clash cluster, with link-back.

        Cross-module bridge (the human-confirmed half of the
        ``clash.high_severity`` auto-bridge): instead of one item per clash,
        a coordinator collapses a whole spatial cluster into a single tracked
        work item. The new row carries a back-link to the run + cluster + the
        representative clash result; every member clash gets the reverse link
        stamped onto its ``meta`` JSONB plus an audit-history entry, and its
        still-``new`` status optionally advances to ``reviewed`` so the board
        reflects the human action.

        Idempotent: if any member already carries ``meta['linked_action']``
        the call is a no-op and returns ``created=False`` pointing at the
        existing item. IDOR-guarded via :meth:`get_run`.
        """
        run = await self.get_run(project_id, run_id)
        if target not in CLASH_ACTION_TARGETS:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Unknown action target '{target}' (expected one of {', '.join(CLASH_ACTION_TARGETS)})",
            )
        members = await self._cluster_members(run_id, cluster_id)
        if not members:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Clash cluster not found")

        # ── Idempotency: never spawn a second item for one group ──────────
        existing = self._existing_action_link(members)
        if existing is not None:
            return {
                "created": False,
                "action_id": str(existing.get("action_id")),
                "action_target": str(existing.get("target") or target),
                "cluster_id": int(cluster_id),
                "results_linked": 0,
                "results_advanced": 0,
            }

        clusters = await self.repo.clusters_for_run(run_id)
        label = next((c.label for c in clusters if int(c.cluster_id) == int(cluster_id)), "")
        proposal = _build_cluster_action_proposal(cluster_id, members, label or "", target)
        # Human overrides win over the AI draft, field by field.
        final_title = (title or proposal["title"]).strip()[:255] or proposal["title"]
        final_desc = (description if description is not None else proposal["description"])[:5000]
        final_priority = priority or proposal["priority"]
        final_assignee = assigned_to if assigned_to is not None else proposal["suggested_assignee"]
        actor_id = str(actor or "system")
        representative = members[0]
        member_result_ids = [str(m.id) for m in members]
        member_element_ids = list(
            dict.fromkeys(
                [str(getattr(m, "a_element_id", "")) for m in members]
                + [str(getattr(m, "b_element_id", "")) for m in members]
            )
        )
        shared_meta = {
            "source": "clash_cluster",
            "clash_run_id": str(run_id),
            "clash_cluster_id": int(cluster_id),
            "clash_cluster_label": label or "",
            "clash_result_ids": member_result_ids,
            "clash_member_count": len(members),
        }

        # ── Create the work item in the target module ───────────────────
        # A coordination assignee is usually a user UUID. The punchlist
        # ``assigned_to`` column is a plain String(36) (accepts any value);
        # the tasks ``responsible_id`` is a real GUID column, so only pass
        # it there when it parses as a UUID - never crash on free text.
        def _as_uuid_str(value: str | None) -> str | None:
            if not value:
                return None
            try:
                return str(uuid.UUID(str(value)))
            except (ValueError, AttributeError, TypeError):
                return None

        # The request ``due_date`` is an ISO day string; the punchlist
        # column is a datetime. Parse defensively - bad input → no deadline.
        punch_due: datetime | None = None
        if due_date and len(due_date) == 10:
            try:
                punch_due = datetime.fromisoformat(due_date)
            except ValueError:
                punch_due = None

        action_id: str
        if target == "punchlist":
            from app.modules.punchlist.schemas import PunchItemCreate
            from app.modules.punchlist.service import PunchListService

            punch = await PunchListService(self.session).create_item(
                PunchItemCreate(
                    project_id=project_id,
                    title=final_title,
                    description=final_desc,
                    priority=final_priority,
                    assigned_to=final_assignee,
                    due_date=punch_due,
                    metadata=shared_meta,
                ),
                user_id=actor_id,
            )
            # Stamp the single-result back-link column so the existing
            # per-clash idempotency guard in the punchlist event bridge
            # also sees this group as already-handled for its lead member.
            punch.clash_result_id = str(representative.id)
            await self.session.flush()
            action_id = str(punch.id)
        else:  # target == "task"
            from app.modules.tasks.schemas import TaskCreate
            from app.modules.tasks.service import TaskService

            # Task priority vocabulary is low|normal|high|urgent - remap the
            # clash band so the create call validates.
            task_priority = {
                "low": "low",
                "medium": "normal",
                "high": "high",
                "critical": "urgent",
            }.get(final_priority, "normal")
            task = await TaskService(self.session).create_task(
                TaskCreate(
                    project_id=project_id,
                    task_type="coordination",
                    title=final_title[:500],
                    description=final_desc,
                    responsible_id=_as_uuid_str(final_assignee),
                    priority=task_priority,
                    due_date=due_date if (due_date and len(due_date) == 10) else None,
                    bim_element_ids=[e for e in member_element_ids if e][:200],
                    metadata=shared_meta,
                ),
                user_id=actor_id,
            )
            action_id = str(task.id)

        # ── Stamp the reverse link + audit trail onto every member ──────
        link = {
            "target": target,
            "action_id": action_id,
            "created_at": _now().isoformat(),
            "actor": actor_id,
        }
        advanced = 0
        for m in members:
            meta = dict(getattr(m, "meta", None) or {})
            meta["linked_action"] = link
            m.meta = meta
            self._append_history(m, actor_id, "linked_action", None, f"{target}:{action_id}")
            if advance_status and m.status == "new":
                self._append_history(m, actor_id, "status", m.status, "reviewed")
                m.status = "reviewed"
                advanced += 1
        await self.session.flush()

        # Refresh the cached status counts so the dashboard KPI stays true.
        if advanced:
            rows, _ = await self.repo.list_results(run_id, limit=_MAX_RESULTS)
            run.summary = _build_summary(list(rows))
            await self.session.flush()

        return {
            "created": True,
            "action_id": action_id,
            "action_target": target,
            "cluster_id": int(cluster_id),
            "results_linked": len(members),
            "results_advanced": advanced,
        }

    async def list_rules(self, project_id: uuid.UUID, run_id: uuid.UUID) -> list[dict]:
        """Return the run's persisted rule list (raw JSON-friendly dicts)."""
        run = await self.get_run(project_id, run_id)
        return _coerce_rules(run.rules)

    async def replace_rules(
        self,
        project_id: uuid.UUID,
        run_id: uuid.UUID,
        rules: list[dict],
    ) -> list[dict]:
        """Replace the rule set on a run (capped at 500). Returns the saved list.

        Capped server-side as a defence-in-depth complement to the
        schema's ``max_length=500`` - a misbehaving client cannot stuff
        the run with thousands of inert rows. Reassigns the JSON column
        so SQLAlchemy detects the change across backends.
        """
        run = await self.get_run(project_id, run_id)
        capped = list(rules)[:500]
        run.rules = capped
        await self.session.flush()
        return _coerce_rules(run.rules)

    async def rule_suggestions(self, project_id: uuid.UUID, run_id: uuid.UUID) -> list[dict]:
        """Mine the run's recorded false-positive history for rule suggestions.

        Each suggestion is keyed off discipline pairs that were *ignored
        with a reason* (FP feedback). A pair must cross
        :data:`_FP_SUGGESTION_THRESHOLD` to surface. The pair is matched
        symmetrically; a rule already on the run (same pair, regardless
        of tolerance) suppresses the suggestion to avoid suggesting
        what's already in place.
        """
        run = await self.get_run(project_id, run_id)
        rows = await self.repo.all_results(run_id)
        fp_pairs, fp_max_pen = _collect_fp_pairs(rows)
        existing_pairs = _existing_rule_pairs(run.rules)
        # Filter out pairs that already have a rule, then mine.
        filtered_pairs = [p for p in fp_pairs if frozenset(p) not in existing_pairs]
        filtered_max_pen = {k: v for k, v in fp_max_pen.items() if frozenset(k) not in existing_pairs}
        rule, reason, fp_count = _suggest_rule_from_fps(filtered_pairs, filtered_max_pen)
        if rule is None:
            return []
        return [{"rule": rule, "reason": reason, "fp_count": fp_count}]

    async def apply_rule_suggestion(
        self,
        project_id: uuid.UUID,
        run_id: uuid.UUID,
        discipline_a: str,
        discipline_b: str,
        tolerance_m: float,
        *,
        actor: str,
    ) -> tuple[bool, int]:
        """Append a new rule + re-evaluate existing results.

        Adds a fresh :class:`ClashRule` row to ``run.rules`` (symmetric on
        the pair - duplicates against any existing pair are skipped with
        ``rule_added=False``). Any hard clash on the pair whose
        ``penetration_m`` now falls at or below ``tolerance_m`` is
        flipped to ``status='ignored'``, with a history entry.

        Returns ``(rule_added, results_affected)``.
        """
        run = await self.get_run(project_id, run_id)
        da = (discipline_a or "").strip()
        db_ = (discipline_b or "").strip()
        if not da or not db_:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="discipline_a and discipline_b must be non-empty",
            )
        existing = _coerce_rules(run.rules)
        pair = frozenset((da.lower(), db_.lower()))
        already = any(
            frozenset(
                (
                    str(r.get("discipline_a") or "").strip().lower(),
                    str(r.get("discipline_b") or "").strip().lower(),
                )
            )
            == pair
            for r in existing
        )
        rule_added = False
        if not already:
            new_rule = {
                "id": f"sugg-{da}-{db_}-{int(_now().timestamp())}"[:64],
                "discipline_a": da[:64],
                "discipline_b": db_[:64],
                "tolerance_m": float(tolerance_m),
                "severity_override": None,
                "enabled": True,
            }
            run.rules = (existing + [new_rule])[:500]
            rule_added = True
        # Re-evaluate: every hard clash on this pair whose penetration
        # now sits at or below the new tolerance becomes ``ignored``.
        rows = await self.repo.all_results(run_id)
        affected = 0
        for r in rows:
            if (r.clash_type or "") != "hard":
                continue
            r_pair = frozenset(((r.a_discipline or "").strip().lower(), (r.b_discipline or "").strip().lower()))
            if r_pair != pair:
                continue
            if float(r.penetration_m or 0.0) > float(tolerance_m):
                continue
            if r.status == "ignored":
                continue
            self._append_history(
                r,
                str(actor or "system"),
                "status",
                r.status,
                "ignored",
            )
            r.status = "ignored"
            affected += 1
        # Refresh the cached status counts so the dashboard KPI stays true.
        if affected or rule_added:
            run.summary = _build_summary(rows)
        await self.session.flush()
        return rule_added, affected

    async def compute_kpi(self, project_id: uuid.UUID, run_id: uuid.UUID) -> dict:
        """Aggregate a dashboard-ready KPI payload for a run.

        Single in-memory pass over every result row - no extra DB calls
        beyond the existing list-by-run query. MTTR is derived from the
        history audit trail (status→resolved transitions); ``None`` when
        no row has a qualifying transition yet (the UI hides the tile).
        """
        await self.get_run(project_id, run_id)
        rows = await self.repo.all_results(run_id)
        return _compute_kpi(rows)

    # ── Engine ─────────────────────────────────────────────────────────

    def _detect(
        self,
        run: ClashRun,
        elements: list[object],
        geoms: dict[str, object] | None = None,
    ) -> list[ClashResult]:
        """Broad (grid) → mid (OBB-SAT) → narrow (Möller tri-tri) pipeline."""
        geoms = geoms or {}

        # Per-element record: (element, aabb, discipline, ElementGeom|None).
        # Deterministic ordering: stable_id then element_id, no RNG.
        ordered = sorted(
            elements[:_MAX_ELEMENTS],
            key=lambda e: (
                str(getattr(e, "stable_id", "") or ""),
                str(getattr(e, "id", "") or ""),
            ),
        )

        boxes: list[tuple[object, tuple[float, float, float, float, float, float], str, object]] = []
        for el in ordered:
            g = geoms.get(str(getattr(el, "id", "")))
            aabb = None
            if g is not None:
                ga = getattr(g, "aabb", None)
                if ga is not None and len(ga) == 6 and all(math.isfinite(v) for v in ga):
                    if ga[3] > ga[0] and ga[4] > ga[1] and ga[5] > ga[2]:
                        aabb = (
                            float(ga[0]),
                            float(ga[1]),
                            float(ga[2]),
                            float(ga[3]),
                            float(ga[4]),
                            float(ga[5]),
                        )
            if aabb is None:
                aabb = _norm_bbox(getattr(el, "bounding_box", None))
            if aabb is None:
                continue
            boxes.append((el, aabb, _discipline_of(el), g))
        if len(boxes) < 2:
            return []

        # One-time per-run mesh extraction. ``_triangles`` / ``_obb`` are
        # pure deterministic functions of an element's mesh, but in a
        # dense single-model run one element participates in dozens of
        # candidate pairs - extracting per pair re-ran the whole triangle
        # soup (index, cross-product, area filter, stable-sort decimation)
        # O(pairs) times. Doing it once per element here makes it O(n)
        # with byte-identical output (pure memoisation - the narrow-phase
        # maths is untouched), which is the bulk of the runtime win.
        tri_by_idx: list[object] = [(_triangles(g) if g is not None else None) for _, _, _, g in boxes]
        obb_by_idx: list[object] = [(_obb(g) if g is not None else None) for _, _, _, g in boxes]

        # Cell size = 60th-percentile element extent, clamped to a sane
        # band so neither tiny bolts nor whole storeys distort the grid.
        extents = sorted(max(bb[3] - bb[0], bb[4] - bb[1], bb[5] - bb[2]) for _, bb, _, _ in boxes)
        cell = extents[int(len(extents) * 0.6)]
        cell = min(max(cell, 0.5), 10.0)

        grid: dict[tuple[int, int, int], list[int]] = {}
        for idx, (_, bb, _, _) in enumerate(boxes):
            x0, y0, z0 = (int(math.floor(bb[i] / cell)) for i in (0, 1, 2))
            x1, y1, z1 = (int(math.floor(bb[i] / cell)) for i in (3, 4, 5))
            span = (x1 - x0 + 1) * (y1 - y0 + 1) * (z1 - z0 + 1)
            if span > _MAX_CELLS_PER_ELEMENT:
                cx = (x0 + x1) // 2
                cy = (y0 + y1) // 2
                cz = (z0 + z1) // 2
                grid.setdefault((cx, cy, cz), []).append(idx)
                continue
            for gx in range(x0, x1 + 1):
                for gy in range(y0, y1 + 1):
                    for gz in range(z0, z1 + 1):
                        grid.setdefault((gx, gy, gz), []).append(idx)

        dfilter: set[frozenset[str]] | None = None
        if run.mode == "selected" and run.discipline_filter:
            dfilter = {frozenset((str(a), str(b))) for a, b in run.discipline_filter}
        # Navisworks-style selection sets: only A×B cross pairs survive.
        sel_a = run.set_a if run.mode == "selection_sets" else None
        sel_b = run.set_b if run.mode == "selection_sets" else None

        # Navisworks-style "Type" selector. ``getattr`` default keeps the
        # legacy semantics for callers (and the test fakes) that never
        # set the field: ``both`` = hard, then clearance for the non-hard
        # pairs - exactly the historical behaviour.
        ctype = str(getattr(run, "clash_type", "both") or "both")
        if ctype not in CLASH_TYPES:
            ctype = "both"
        # Federated noise filter ("ignore clashes within the same file").
        # Meaningless on a single-model run, so only honoured when the run
        # actually spans more than one model.
        ignore_same_model = (
            bool(getattr(run, "ignore_same_model", False))
            and len({str(getattr(e, "model_id", "")) for e, _, _, _ in boxes}) > 1
        )

        seen: set[tuple[int, int]] = set()
        results: list[ClashResult] = []
        pairs_tested = 0
        tol = float(run.tolerance_m)
        clr = float(run.clearance_m)
        # ``hard`` → never run the soft proximity pass (clr forced to 0).
        # ``clearance`` → suppress the hard classification; only proximity
        # within ``clearance_m`` is reported (so clearance MUST be > 0 to
        # find anything - same contract the UI enforces).
        # ``both`` → unchanged legacy pipeline.
        hard_enabled = ctype != "clearance"
        if ctype == "hard":
            clr = 0.0

        for bucket in grid.values():
            if len(bucket) < 2:
                continue
            for i, j in combinations(sorted(bucket), 2):
                key = (i, j) if i < j else (j, i)
                if key in seen:
                    continue
                seen.add(key)
                pairs_tested += 1
                if pairs_tested > _MAX_PAIRS:
                    logger.warning("Clash run %s hit the %d-pair cap", run.id, _MAX_PAIRS)
                    return results
                ea, ba, da, ga = boxes[key[0]]
                eb, bb_, db, gb = boxes[key[1]]
                if ea.id == eb.id:  # type: ignore[attr-defined]
                    continue
                # Federated noise filter: drop intra-model pairs so a
                # model is never clashed against itself when the user
                # only wants cross-discipline/cross-trade coordination.
                if ignore_same_model and (getattr(ea, "model_id", None) == getattr(eb, "model_id", None)):
                    continue
                # Discipline gating.
                if run.mode == "cross_discipline" and da == db:
                    continue
                if dfilter is not None and frozenset((da, db)) not in dfilter:
                    continue
                # Selection-set gating - keep iff one element is in Set A
                # and the other is in Set B (strictly cross, e.g.
                # walls × pipes; never wall × wall).
                if sel_a is not None:
                    ta_ = _type_of(ea)
                    tb_ = _type_of(eb)
                    if not (
                        (_in_set(ea, ta_, da, sel_a) and _in_set(eb, tb_, db, sel_b))
                        or (_in_set(ea, ta_, da, sel_b) and _in_set(eb, tb_, db, sel_a))
                    ):
                        continue

                # Wave A4 - per-discipline-pair tolerance override. The
                # first matching enabled rule (symmetric on the pair)
                # swaps in its ``tolerance_m`` for the run-wide value and
                # the result will pick up its ``severity_override``.
                pair_rule = _apply_rules(run, (da, db))
                pair_tol = tol
                if pair_rule is not None:
                    try:
                        pair_tol = float(pair_rule.get("tolerance_m") or tol)
                    except (TypeError, ValueError):
                        pair_tol = tol

                row = self._test_pair(
                    run,
                    ea,
                    ba,
                    da,
                    ga,
                    eb,
                    bb_,
                    db,
                    gb,
                    pair_tol,
                    clr,
                    triA=tri_by_idx[key[0]],
                    triB=tri_by_idx[key[1]],
                    oa=obb_by_idx[key[0]],
                    ob=obb_by_idx[key[1]],
                    hard_enabled=hard_enabled,
                )
                if row is not None:
                    if pair_rule is not None:
                        sev_override = pair_rule.get("severity_override")
                        if isinstance(sev_override, str) and sev_override in CLASH_SEVERITIES:
                            row.severity = sev_override
                    results.append(row)
                    if len(results) >= _MAX_RESULTS:
                        logger.warning(
                            "Clash run %s hit the %d-result cap",
                            run.id,
                            _MAX_RESULTS,
                        )
                        return results
        return results

    @staticmethod
    def _aabb_overlap(
        ba: tuple[float, float, float, float, float, float],
        bb: tuple[float, float, float, float, float, float],
    ) -> bool:
        return (
            ba[0] <= bb[3]
            and bb[0] <= ba[3]
            and ba[1] <= bb[4]
            and bb[1] <= ba[4]
            and ba[2] <= bb[5]
            and bb[2] <= ba[5]
        )

    @classmethod
    def _test_pair(
        cls,
        run: ClashRun,
        ea: object,
        ba: tuple[float, float, float, float, float, float],
        da: str,
        ga: object,
        eb: object,
        bb: tuple[float, float, float, float, float, float],
        db: str,
        gb: object,
        tol: float,
        clr: float,
        triA: object = _UNSET,
        triB: object = _UNSET,
        oa: object = _UNSET,
        ob: object = _UNSET,
        hard_enabled: bool = True,
    ) -> ClashResult | None:
        """Mid + narrow phase: classify one element pair, or ``None``.

        Falls back to the legacy exact-AABB classification when *either*
        element lacks a real mesh (bbox-only model) - preserving the old
        behaviour for un-tessellated data while giving mesh-grade
        precision wherever GLB geometry exists.

        ``hard_enabled`` reflects the run's Navisworks-style "Type"
        selector: ``False`` for a ``clash_type='clearance'`` run, where
        the hard interpenetration classification is suppressed and only
        proximity within ``clr`` is reported. It defaults to ``True`` so
        every existing direct caller / test keeps the legacy behaviour.

        ``triA``/``triB``/``oa``/``ob`` may be passed pre-extracted by the
        caller. :func:`_triangles` / :func:`_obb` are pure deterministic
        functions of the element mesh, and a single element participates
        in many candidate pairs, so :meth:`_detect` extracts each once and
        threads the cached value here. When a value is left ``_UNSET``
        (e.g. the unit tests that call this method directly) it is
        extracted here exactly as before - the result is byte-identical
        either way; only redundant recomputation is removed.
        """
        if triA is _UNSET:
            triA = _triangles(ga) if ga is not None else None
        if triB is _UNSET:
            triB = _triangles(gb) if gb is not None else None

        if triA is None or triB is None:
            return cls._test_pair_bbox(
                run,
                ea,
                ba,
                da,
                eb,
                bb,
                db,
                tol,
                clr,
                ga,
                gb,
                hard_enabled=hard_enabled,
            )

        # Broad AABB re-check (grid buckets are conservative).
        if not cls._aabb_overlap(ba, bb):
            if clr <= 0:
                return None

        # Mid phase: OBB-SAT quick reject (zero false negatives).
        if oa is _UNSET:
            oa = _obb(ga) if ga is not None else None
        if ob is _UNSET:
            ob = _obb(gb) if gb is not None else None
        sat_separated = False
        if oa is not None and ob is not None:
            if not _obb_sat_overlap(oa, ob):
                sat_separated = True

        clash_type = ""
        penetration = 0.0
        distance = 0.0
        cx = cy = cz = 0.0

        if hard_enabled and not sat_separated:
            mask = _tri_tri_intersect_mask(triA, triB)
            if mask.any():
                pen, centroid = _penetration_depth(triA, triB, mask)
                if pen > tol:
                    clash_type = "hard"
                    penetration = pen
                    cx, cy, cz = (
                        float(centroid[0]),
                        float(centroid[1]),
                        float(centroid[2]),
                    )

        if not clash_type and clr > 0:
            dist, pa, pb = _min_mesh_distance(triA, triB)
            if 1e-9 < dist <= clr:
                clash_type = "clearance"
                distance = dist
                mid = (np.asarray(pa) + np.asarray(pb)) / 2.0
                cx, cy, cz = float(mid[0]), float(mid[1]), float(mid[2])

        if not clash_type:
            return None

        return cls._row(
            run,
            ea,
            da,
            eb,
            db,
            clash_type,
            penetration,
            distance,
            cx,
            cy,
            cz,
            ga,
            gb,
        )

    @classmethod
    def _test_pair_bbox(
        cls,
        run: ClashRun,
        ea: object,
        ba: tuple[float, float, float, float, float, float],
        da: str,
        eb: object,
        bb: tuple[float, float, float, float, float, float],
        db: str,
        tol: float,
        clr: float,
        ga: object = None,
        gb: object = None,
        hard_enabled: bool = True,
    ) -> ClashResult | None:
        """Legacy exact-AABB classification (no-GLB fallback path).

        ``hard_enabled`` mirrors :meth:`_test_pair`: when ``False``
        (a ``clash_type='clearance'`` run) an interpenetrating box pair
        is dropped - only a true non-overlapping proximity within ``clr``
        is reported. Defaults ``True`` so direct callers keep the legacy
        behaviour.
        """
        ox = min(ba[3], bb[3]) - max(ba[0], bb[0])
        oy = min(ba[4], bb[4]) - max(ba[1], bb[1])
        oz = min(ba[5], bb[5]) - max(ba[2], bb[2])

        clash_type = ""
        penetration = 0.0
        distance = 0.0
        if ox > 0 and oy > 0 and oz > 0:
            # Overlapping boxes: a hard candidate. With the hard pass
            # suppressed (clearance-only run) this pair is simply not
            # reported - an interpenetration is never a clearance hit.
            if not hard_enabled:
                return None
            penetration = min(ox, oy, oz)
            if penetration <= tol:
                return None
            clash_type = "hard"
            cx = (max(ba[0], bb[0]) + min(ba[3], bb[3])) / 2
            cy = (max(ba[1], bb[1]) + min(ba[4], bb[4])) / 2
            cz = (max(ba[2], bb[2]) + min(ba[5], bb[5])) / 2
        elif clr > 0:
            sx = max(ba[0] - bb[3], bb[0] - ba[3], 0.0)
            sy = max(ba[1] - bb[4], bb[1] - ba[4], 0.0)
            sz = max(ba[2] - bb[5], bb[2] - ba[5], 0.0)
            distance = math.sqrt(sx * sx + sy * sy + sz * sz)
            if distance <= 1e-9 or distance > clr:
                return None
            clash_type = "clearance"
            cx = ((ba[0] + ba[3]) / 2 + (bb[0] + bb[3]) / 2) / 2
            cy = ((ba[1] + ba[4]) / 2 + (bb[1] + bb[4]) / 2) / 2
            cz = ((ba[2] + ba[5]) / 2 + (bb[2] + bb[5]) / 2) / 2
        else:
            return None

        return cls._row(
            run,
            ea,
            da,
            eb,
            db,
            clash_type,
            penetration,
            distance,
            cx,
            cy,
            cz,
            ga,
            gb,
        )

    @staticmethod
    def _storey_of(geom: object) -> int | None:
        """Resolve an element's storey index from its ElementGeom.

        The geometry loader clusters a level index from real geometry Z
        onto ``ElementGeom.storey``. Absent (no GLB / loader did not set
        it / older loader) → ``None`` so the row + level matrix degrade
        gracefully without ever crashing.
        """
        if geom is None:
            return None
        s = getattr(geom, "storey", None)
        if s is None:
            return None
        try:
            return int(s)
        except (TypeError, ValueError):
            return None

    @classmethod
    def _row(
        cls,
        run: ClashRun,
        ea: object,
        da: str,
        eb: object,
        db: str,
        clash_type: str,
        penetration: float,
        distance: float,
        cx: float,
        cy: float,
        cz: float,
        ga: object = None,
        gb: object = None,
    ) -> ClashResult:
        """Build a :class:`ClashResult` row (single construction point)."""
        a_sid = str(getattr(ea, "stable_id", "") or "")
        b_sid = str(getattr(eb, "stable_id", "") or "")
        clr = float(getattr(run, "clearance_m", 0.0) or 0.0)
        sev = _severity_for(clash_type, penetration, distance, clr)
        suggestion = _severity_suggestion(clash_type, penetration, sev)
        # Smart-issue signature (v41). Bucketed centroid + sorted GUID pair
        # + clash type → SHA-1. Per-run ``spatial_grid_mm`` lets a project
        # dial the precision; defaults to 500 mm.
        grid_mm = int(getattr(run, "spatial_grid_mm", None) or _DEFAULT_SPATIAL_GRID_MM)
        # Weak-fallback inputs - only consulted when one stable_id is empty.
        a_props = getattr(ea, "properties", None) or {}
        b_props = getattr(eb, "properties", None) or {}
        ifc_a = str(a_props.get("ifc_class") or a_props.get("category") or getattr(ea, "element_type", "") or "")
        ifc_b = str(b_props.get("ifc_class") or b_props.get("category") or getattr(eb, "element_type", "") or "")
        mat_a = str(a_props.get("material") or "")
        mat_b = str(b_props.get("material") or "")
        ifc_class_combined = f"{ifc_a}|{ifc_b}" if ifc_a or ifc_b else ""
        material_combined = f"{mat_a}|{mat_b}" if mat_a or mat_b else ""
        # Quantity keys (deterministic) - from either props.quantities or
        # the geometric properties keys themselves; sorted for stability.
        qty_keys: list[str] = []
        for src in (a_props, b_props):
            qsrc = src.get("quantities") if isinstance(src, dict) else None
            if isinstance(qsrc, dict):
                qty_keys.extend(str(k) for k in qsrc)
        sig_hash, sig_quality = _compute_signature_hash(
            a_guid=a_sid,
            b_guid=b_sid,
            centroid=(cx, cy, cz),
            clash_type=clash_type,
            grid_mm=grid_mm,
            weak_fallback=(
                ifc_class_combined,
                material_combined,
                qty_keys,
            ),
        )
        tol_at_sig_mm = float(getattr(run, "tolerance_m", 0.0) or 0.0) * 1000.0
        meta: dict = {}
        if suggestion is not None:
            meta["severity_suggestion"] = suggestion
        return ClashResult(
            run_id=run.id,
            a_element_id=ea.id,  # type: ignore[attr-defined]
            b_element_id=eb.id,  # type: ignore[attr-defined]
            a_stable_id=a_sid,
            b_stable_id=b_sid,
            a_name=(getattr(ea, "name", None) or getattr(ea, "element_type", "") or "")[:500],
            b_name=(getattr(eb, "name", None) or getattr(eb, "element_type", "") or "")[:500],
            a_discipline=da[:64] or "Unassigned",
            b_discipline=db[:64] or "Unassigned",
            a_element_type=(getattr(ea, "element_type", "") or "")[:100],
            b_element_type=(getattr(eb, "element_type", "") or "")[:100],
            a_element_system=_system_of(ea),
            b_element_system=_system_of(eb),
            a_model_id=ea.model_id,  # type: ignore[attr-defined]
            b_model_id=eb.model_id,  # type: ignore[attr-defined]
            a_storey=cls._storey_of(ga),
            b_storey=cls._storey_of(gb),
            clash_type=clash_type,
            penetration_m=round(penetration, 4),
            distance_m=round(distance, 4),
            cx=round(cx, 4),
            cy=round(cy, 4),
            cz=round(cz, 4),
            status="new",
            severity=sev,
            signature=_signature(a_sid, b_sid, clash_type),
            signature_hash=sig_hash,
            signature_quality=sig_quality,
            tolerance_at_signature_time_mm=tol_at_sig_mm,
            comments=[],
            watchers=[],
            history=[],
            meta=meta,
        )

    # ── Result triage ──────────────────────────────────────────────────

    @staticmethod
    def _append_history(
        result: ClashResult,
        actor: str,
        field: str,
        before: object,
        after: object,
    ) -> None:
        """Append one audit entry to ``result.history``.

        ``before`` / ``after`` are best-effort string-coerced for the
        Activity tab; ``None`` survives as ``None`` (no prior / no
        natural pair). Reassigns the JSON column (instead of in-place
        ``.append``) so SQLAlchemy detects the change on every backend
        (the same dirty-tracking pattern the comments column uses).
        """

        def _str(v: object) -> str | None:
            if v is None:
                return None
            return str(v)

        entry = {
            "ts": _now().isoformat(),
            "actor": str(actor or "system"),
            "field": str(field),
            "before": _str(before),
            "after": _str(after),
        }
        result.history = list(result.history or []) + [entry]

    @staticmethod
    def _extract_mentions(text: str) -> list[str]:
        """Pull ``<at>user-id</at>`` user-ids from a comment body.

        The frontend serialises an @mention as the literal token
        ``<at>{userId}</at>`` inside the text; this is the matching
        parser. Defensive - duplicates are de-duplicated preserving
        first-seen order, and obvious junk (empty / whitespace) skipped.
        Never raises.
        """
        if not text:
            return []
        out: list[str] = []
        seen: set[str] = set()
        i = 0
        while True:
            start = text.find("<at>", i)
            if start < 0:
                break
            end = text.find("</at>", start + 4)
            if end < 0:
                break
            uid = text[start + 4 : end].strip()
            if uid and uid not in seen:
                seen.add(uid)
                out.append(uid)
            i = end + 5
        return out

    def _publish_high_severity(
        self,
        result: ClashResult,
        *,
        project_id: uuid.UUID,
        run_id: uuid.UUID,
        trigger: str,
        actor: str | None,
    ) -> None:
        """Emit ``clash.high_severity.detected`` for a high/critical clash.

        Fire-and-forget via :meth:`EventBus.publish_detached` so the
        request commits (and releases the writer lock) before the
        notifications subscriber opens its own session. Only ``critical``
        and ``high`` severities publish; everything else is a no-op so
        subscribers are never spammed with routine clashes.
        """
        severity = str(getattr(result, "severity", "") or "").lower()
        if severity not in HIGH_SEVERITIES:
            return
        event_bus.publish_detached(
            CLASH_HIGH_SEVERITY_DETECTED,
            {
                "project_id": str(project_id),
                "run_id": str(run_id),
                "result_id": str(result.id),
                "severity": severity,
                "trigger": trigger,
                "clash_type": result.clash_type,
                "a_name": result.a_name,
                "b_name": result.b_name,
                "assigned_to": str(result.assigned_to) if result.assigned_to else "",
                "watchers": [str(w) for w in (result.watchers or []) if w],
                "actor": str(actor) if actor else "",
            },
            source_module="clash",
        )

    async def _notify(
        self,
        recipients: list[str],
        notification_type: str,
        title_key: str,
        *,
        project_id: uuid.UUID,
        run_id: uuid.UUID,
        result_id: uuid.UUID,
        actor: str,
        body_context: dict | None = None,
    ) -> None:
        """Fan a clash event out to recipients via the notifications module.

        Best-effort - any failure (missing module, bad user id, db error)
        is logged and swallowed; collaboration never blocks triage.
        ``actor`` is filtered out so the caller never notifies themselves.
        Duplicates are de-duplicated preserving order.
        """
        seen: set[str] = set()
        targets: list[str] = []
        for uid in recipients:
            sid = str(uid or "").strip()
            if not sid or sid == str(actor) or sid in seen:
                continue
            seen.add(sid)
            targets.append(sid)
        if not targets:
            return
        try:
            from app.modules.notifications.service import NotificationService

            svc = NotificationService(self.session)
            await svc.notify_users(
                targets,
                notification_type=notification_type,
                title_key=title_key,
                entity_type="clash_result",
                entity_id=str(result_id),
                body_context=body_context or {},
                action_url=f"/clash?run={run_id}&result={result_id}",
                metadata={"project_id": str(project_id), "run_id": str(run_id)},
            )
        except Exception:  # noqa: BLE001 - never block triage on notify
            logger.info(
                "Clash notification skipped (type=%s, result=%s)",
                notification_type,
                result_id,
            )

    async def update_result(
        self,
        project_id: uuid.UUID,
        run_id: uuid.UUID,
        result_id: uuid.UUID,
        *,
        new_status: str | None,
        assigned_to: str | None,
        due_date: str | None = None,
        severity: str | None = None,
        add_comment: dict | None = None,
        actor: str | None = None,
    ) -> ClashResult:
        run = await self.get_run(project_id, run_id)
        result = await self.repo.get_result(run_id, result_id)
        if result is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Clash not found")
        actor_id = str(actor or "system")
        # Track which fields changed so we can fan notifications out once
        # at the end (cheaper than N parallel publish calls).
        changed_fields: list[str] = []
        if new_status is not None:
            if new_status not in CLASH_STATUSES:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"Invalid clash status '{new_status}'",
                )
            if result.status != new_status:
                self._append_history(result, actor_id, "status", result.status, new_status)
                result.status = new_status
                changed_fields.append("status")
        if severity is not None:
            if severity not in CLASH_SEVERITIES:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"Invalid clash severity '{severity}'",
                )
            if result.severity != severity:
                self._append_history(result, actor_id, "severity", result.severity, severity)
                result.severity = severity
                changed_fields.append("severity")
        if assigned_to is not None:
            new_assignee = assigned_to or None
            if (result.assigned_to or None) != new_assignee:
                self._append_history(
                    result,
                    actor_id,
                    "assigned_to",
                    result.assigned_to,
                    new_assignee,
                )
                result.assigned_to = new_assignee
                changed_fields.append("assigned_to")
        if due_date is not None:
            new_due = due_date or None
            if (result.due_date or None) != new_due:
                self._append_history(result, actor_id, "due_date", result.due_date, new_due)
                result.due_date = new_due
                changed_fields.append("due_date")
        mentioned: list[str] = []
        added_comment_ts: str | None = None
        if add_comment is not None:
            text = str(add_comment.get("text") or "").strip()
            if text:
                ts = _now().isoformat()
                item = {
                    "author": str(add_comment.get("author") or "system"),
                    "author_id": add_comment.get("author_id"),
                    "ts": ts,
                    "text": text,
                    "reply_to": add_comment.get("reply_to") or None,
                }
                # Reassign (not in-place append) so the plain-JSON column
                # is detected dirty and persisted on every backend.
                result.comments = list(result.comments or []) + [item]
                self._append_history(result, actor_id, "comment_add", None, text[:160])
                mentioned = self._extract_mentions(text)
                added_comment_ts = ts
        await self.session.flush()
        # Refresh the cached status counts so the dashboard KPI stays true.
        rows, _ = await self.repo.list_results(run_id, limit=_MAX_RESULTS)
        run.summary = _build_summary(list(rows))
        await self.session.flush()

        # ── Fan-out: best-effort notifications to watchers + @mentions ──
        # Watchers learn about every triage mutation + new comment;
        # @mentioned users learn about the comment specifically. The
        # caller is filtered out inside :meth:`_notify`.
        watchers = [str(w) for w in (result.watchers or []) if w]
        if changed_fields and watchers:
            await self._notify(
                watchers,
                notification_type="clash_updated",
                title_key="clash.notification.updated",
                project_id=project_id,
                run_id=run_id,
                result_id=result_id,
                actor=actor_id,
                body_context={
                    "fields": ",".join(changed_fields),
                    "a_name": result.a_name,
                    "b_name": result.b_name,
                },
            )
        if added_comment_ts is not None:
            if watchers:
                await self._notify(
                    watchers,
                    notification_type="clash_comment",
                    title_key="clash.notification.comment",
                    project_id=project_id,
                    run_id=run_id,
                    result_id=result_id,
                    actor=actor_id,
                    body_context={
                        "a_name": result.a_name,
                        "b_name": result.b_name,
                    },
                )
            if mentioned:
                await self._notify(
                    mentioned,
                    notification_type="clash_mention",
                    title_key="clash.notification.mention",
                    project_id=project_id,
                    run_id=run_id,
                    result_id=result_id,
                    actor=actor_id,
                    body_context={
                        "a_name": result.a_name,
                        "b_name": result.b_name,
                    },
                )

        # ── High-severity confirmation alert ──────────────────────────
        # A clash is "confirmed" when a human moves it into a review state
        # (reviewed / approved) or raises its severity into the high band.
        # Publish the cross-module event in both cases so notifications can
        # alert the relevant users. ``_publish_high_severity`` no-ops when
        # the current severity is not critical/high.
        confirmed_status = "status" in changed_fields and result.status in _CONFIRMED_CLASH_STATUSES
        raised_severity = "severity" in changed_fields
        if confirmed_status or raised_severity:
            self._publish_high_severity(
                result,
                project_id=project_id,
                run_id=run_id,
                trigger=TRIGGER_CONFIRMED,
                actor=actor_id,
            )
        return result

    async def bulk_update_results(
        self,
        project_id: uuid.UUID,
        run_id: uuid.UUID,
        result_ids: list[uuid.UUID],
        *,
        new_status: str | None = None,
        assigned_to: str | None = None,
        severity: str | None = None,
        actor: str | None = None,
    ) -> int:
        """Apply one triage change to many clashes in a single round-trip.

        Backs the review table's bulk-actions toolbar (set status / severity /
        assignee over the current selection) so a large selection no longer
        fires one PATCH per row. Validates the target values once up-front,
        patches every matching row, appends per-row audit history, then
        rebuilds the run summary **once** at the end (rather than once per
        row). Watcher notifications are fanned out best-effort per changed
        row. Returns the number of rows that actually changed.
        """
        run = await self.get_run(project_id, run_id)  # IDOR + 404 guard
        actor_id = str(actor or "system")

        # Validate once - a bad value fails the whole batch before any write.
        if new_status is not None and new_status not in CLASH_STATUSES:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Invalid clash status '{new_status}'",
            )
        if severity is not None and severity not in CLASH_SEVERITIES:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Invalid clash severity '{severity}'",
            )
        if new_status is None and severity is None and assigned_to is None:
            return 0

        # De-duplicate ids preserving order; cap the batch so a runaway
        # selection can't hold the event loop (matches the export ceiling).
        seen: set[uuid.UUID] = set()
        unique_ids: list[uuid.UUID] = []
        for rid in result_ids:
            if rid not in seen:
                seen.add(rid)
                unique_ids.append(rid)
        if len(unique_ids) > _MAX_RESULTS:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Bulk selection exceeds {_MAX_RESULTS} rows.",
            )

        rows = await self.repo.results_by_ids(run_id, unique_ids)
        # (result, changed_fields) for the post-flush notification fan-out.
        touched: list[tuple[ClashResult, list[str]]] = []
        for result in rows:
            changed_fields: list[str] = []
            if new_status is not None and result.status != new_status:
                self._append_history(result, actor_id, "status", result.status, new_status)
                result.status = new_status
                changed_fields.append("status")
            if severity is not None and result.severity != severity:
                self._append_history(result, actor_id, "severity", result.severity, severity)
                result.severity = severity
                changed_fields.append("severity")
            if assigned_to is not None:
                new_assignee = assigned_to or None
                if (result.assigned_to or None) != new_assignee:
                    self._append_history(result, actor_id, "assigned_to", result.assigned_to, new_assignee)
                    result.assigned_to = new_assignee
                    changed_fields.append("assigned_to")
            if changed_fields:
                touched.append((result, changed_fields))

        if not touched:
            return 0

        await self.session.flush()
        # Rebuild the cached status counts ONCE for the whole batch.
        all_rows, _ = await self.repo.list_results(run_id, limit=_MAX_RESULTS)
        run.summary = _build_summary(list(all_rows))
        await self.session.flush()

        for result, changed_fields in touched:
            watchers = [str(w) for w in (result.watchers or []) if w]
            if watchers:
                await self._notify(
                    watchers,
                    notification_type="clash_updated",
                    title_key="clash.notification.updated",
                    project_id=project_id,
                    run_id=run_id,
                    result_id=result.id,
                    actor=actor_id,
                    body_context={
                        "fields": ",".join(changed_fields),
                        "a_name": result.a_name,
                        "b_name": result.b_name,
                    },
                )
        return len(touched)

    # ── Watchers ───────────────────────────────────────────────────────

    async def set_watch(
        self,
        project_id: uuid.UUID,
        run_id: uuid.UUID,
        result_id: uuid.UUID,
        user_id: str,
        watching: bool,
    ) -> tuple[list[str], bool]:
        """Add or remove ``user_id`` from this clash's watcher list.

        Idempotent: a duplicate watch / unwatch is a no-op. Returns the
        current watcher list plus the caller's own watching flag.
        """
        await self.get_run(project_id, run_id)  # IDOR / 404 guard
        result = await self.repo.get_result(run_id, result_id)
        if result is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Clash not found")
        uid = str(user_id)
        current = [str(w) for w in (result.watchers or []) if w]
        if watching:
            if uid not in current:
                current.append(uid)
        else:
            current = [w for w in current if w != uid]
        # Reassign to mark the JSON column dirty across backends.
        result.watchers = current
        await self.session.flush()
        return current, uid in current

    # ── BCF import (round-trip triage sync) ────────────────────────────

    async def import_bcf(
        self,
        project_id: uuid.UUID,
        run_id: uuid.UUID,
        payload: bytes,
        *,
        actor: str,
    ) -> tuple[int, int, int]:
        """Replay a ``.bcfzip`` against this run, syncing triage state.

        Reuses the existing BCF 2.1/3.0 codec from the ``bcf`` module so
        we never duplicate XML parsing. For each parsed topic we
        recompute the canonical clash signature from the stable IDs the
        matching :meth:`export_bcf` embedded into the topic
        description, and patch the matching :class:`ClashResult` row
        with the topic's status / assignee / due date / new comments /
        BCF guid (BCF status maps onto our ``CLASH_STATUSES`` enum, with
        unknown values left as-is so a third-party round-trip never
        corrupts our review state). Topics with no signature hit are
        logged + counted as ``unmatched`` - they are never created here,
        because a clash is an engine-derived artefact, not a user issue.

        Returns ``(matched, unmatched, parse_errors)``.
        """
        await self.get_run(project_id, run_id)  # IDOR + 404 guard
        try:
            parsed = parse_bcfzip(payload)
        except BCFParseError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Invalid BCF archive: {exc}",
            ) from exc

        # Index this run's results by signature once - a federated run
        # can carry tens of thousands of rows. O(N + T) instead of O(N×T).
        all_rows = await self.repo.all_results(run_id)
        by_sig: dict[str, ClashResult] = {}
        for r in all_rows:
            sig = (getattr(r, "signature", "") or "").strip()
            if sig and sig not in by_sig:
                by_sig[sig] = r

        matched = 0
        unmatched = 0
        parse_errors = sum(1 for i in parsed.issues if getattr(i, "severity", "") == "error")
        for topic in parsed.topics:
            sig = _signature_from_description(topic.description or "")
            row: ClashResult | None = None
            if sig:
                row = by_sig.get(sig)
            if row is None and getattr(topic, "guid", None):
                row = next(
                    (r for r in all_rows if (r.bcf_topic_guid or "") == topic.guid),
                    None,
                )
            if row is None:
                logger.info(
                    "BCF topic %s has no matching clash signature (skipped)",
                    getattr(topic, "guid", "?"),
                )
                unmatched += 1
                continue
            self._sync_row_from_topic(row, topic, actor=actor)
            matched += 1

        if matched:
            await self.session.flush()
            # Re-roll the cached run summary so the by_status counts
            # reflect the imported state (the KPI strip stays honest).
            rows2, _ = await self.repo.list_results(run_id, limit=_MAX_RESULTS)
            run = await self.get_run(project_id, run_id)
            run.summary = _build_summary(list(rows2))
            await self.session.flush()

        logger.info(
            "BCF import on run %s: matched=%d unmatched=%d errors=%d",
            run_id,
            matched,
            unmatched,
            parse_errors,
        )
        return matched, unmatched, parse_errors

    def _sync_row_from_topic(self, row: ClashResult, topic: object, *, actor: str) -> None:
        """Patch a clash row with a parsed BCF topic's triage state.

        Pulled out of :meth:`import_bcf` so the row-merge logic is one
        cohesive block we can keep narrow and test-isolatable. Every
        mutation goes through :meth:`_append_history` so the audit log
        records the BCF round-trip just like an in-app edit.
        """
        new_status = _bcf_status_to_clash_status(getattr(topic, "topic_status", None))
        if new_status and row.status != new_status:
            self._append_history(row, actor, "status", row.status, new_status)
            row.status = new_status
        new_assignee = (getattr(topic, "assigned_to", None) or "").strip() or None
        if new_assignee is not None and (row.assigned_to or None) != new_assignee:
            self._append_history(row, actor, "assigned_to", row.assigned_to, new_assignee)
            row.assigned_to = new_assignee
        due = getattr(topic, "due_date", None)
        if due is not None:
            try:
                iso_day = due.strftime("%Y-%m-%d")
            except Exception:  # noqa: BLE001 - never block import on date format
                iso_day = None
            if iso_day and (row.due_date or None) != iso_day:
                self._append_history(row, actor, "due_date", row.due_date, iso_day)
                row.due_date = iso_day
        # Append any BCF comments we haven't yet - keyed on (author|text)
        # so a re-import doesn't double up.
        existing_keys = {
            f"{(c.get('author') or '').strip()}|{(c.get('text') or '').strip()}"
            for c in (row.comments or [])
            if isinstance(c, dict)
        }
        new_comments: list[dict] = []
        for c in getattr(topic, "comments", None) or []:
            text = (getattr(c, "comment", "") or "").strip()
            if not text:
                continue
            author = (getattr(c, "author", "") or "").strip() or "system"
            key = f"{author}|{text}"
            if key in existing_keys:
                continue
            existing_keys.add(key)
            ts_raw = getattr(c, "date", None)
            try:
                ts_iso = ts_raw.isoformat() if ts_raw is not None else _now().isoformat()
            except Exception:  # noqa: BLE001
                ts_iso = _now().isoformat()
            new_comments.append(
                {
                    "author": author,
                    "author_id": None,
                    "ts": ts_iso,
                    "text": text,
                    "reply_to": None,
                }
            )
        if new_comments:
            row.comments = list(row.comments or []) + new_comments
            self._append_history(
                row,
                actor,
                "bcf_import",
                None,
                f"{len(new_comments)} comment(s)",
            )
        new_guid = getattr(topic, "guid", None) or None
        if new_guid and row.bcf_topic_guid != new_guid:
            self._append_history(row, actor, "bcf_topic_guid", row.bcf_topic_guid, new_guid)
            row.bcf_topic_guid = new_guid

    async def resolve_author(self, user_id: str) -> str:
        """Best-effort human label for a comment author.

        Prefer the user's ``full_name``, fall back to ``email``, then to
        the raw id, and finally ``"system"`` - never raises (mirrors the
        best-effort user lookup in the IDOR guard).
        """
        try:
            from app.modules.users.repository import UserRepository

            user = await UserRepository(self.session).get_by_id(uuid.UUID(str(user_id)))
            if user is not None:
                name = (getattr(user, "full_name", "") or "").strip()
                if name:
                    return name
                email = (getattr(user, "email", "") or "").strip()
                if email:
                    return email
        except Exception:  # noqa: BLE001 - author label is best-effort
            logger.exception("Comment author lookup failed for %s", user_id)
        return str(user_id) or "system"

    async def list_results(self, run_id: uuid.UUID, **kw: object):
        return await self.repo.list_results(run_id, **kw)  # type: ignore[arg-type]

    # ── BCF export ─────────────────────────────────────────────────────

    async def export_bcf(
        self,
        project_id: uuid.UUID,
        run_id: uuid.UUID,
        data: ClashBCFExportRequest,
        author: str,
        user_id: str,
    ) -> tuple[int, int]:
        """Mirror selected clashes into native BCF topics. (exported, skipped)."""
        run = await self.get_run(project_id, run_id)
        selection = await self.repo.results_for_export(run_id, data.result_ids)
        bcf = BCFService(self.session)
        exported = 0
        skipped = 0
        for r in selection:
            if r.bcf_topic_guid:
                skipped += 1
                continue
            priority = "High" if r.clash_type == "hard" else "Normal"
            desc = (
                f"{r.clash_type.capitalize()} clash · "
                f"{r.a_discipline} ↔ {r.b_discipline}\n"
                f"A: {r.a_name} ({r.a_stable_id})\n"
                f"B: {r.b_name} ({r.b_stable_id})\n"
                f"Penetration: {r.penetration_m} m · "
                f"Clearance gap: {r.distance_m} m\n"
                f"Location: ({r.cx}, {r.cy}, {r.cz})\n"
                f"Source: clash run '{run.name}'"
            )
            topic = await bcf.create_topic(
                project_id,
                TopicCreate(
                    title=f"Clash: {r.a_name} × {r.b_name}"[:500],
                    description=desc,
                    topic_type="Clash",
                    topic_status="Open",
                    priority=priority,
                    labels=[r.clash_type, r.a_discipline, r.b_discipline],
                    bim_model_id=str(r.a_model_id),
                ),
                author=author,
                user_id=str(user_id),
            )
            # Camera pulled back along +XYZ looking at the clash centroid.
            eye = Vec3(x=r.cx + 8.0, y=r.cy - 8.0, z=r.cz + 8.0)
            look = Vec3(x=-1.0, y=1.0, z=-1.0)
            await bcf.add_viewpoint(
                project_id,
                topic.id,
                ViewpointCreate(
                    perspective_camera=PerspectiveCamera(
                        camera_view_point=eye,
                        camera_direction=look,
                        camera_up_vector=Vec3(x=0.0, y=0.0, z=1.0),
                        field_of_view=60.0,
                    ),
                    element_stable_ids=[r.a_stable_id, r.b_stable_id],
                ),
                str(user_id),
            )
            r.bcf_topic_guid = topic.guid
            exported += 1
        await self.session.flush()
        return exported, skipped


def _build_summary(results: list[ClashResult]) -> dict:
    """Aggregate results into the cached dashboard payload.

    Produces two coordination grids with the *identical* cell shape so
    the frontend renders them with one component:

    * ``matrix`` - discipline×discipline (string keys). Correct for true
      multi-discipline federated uploads. Untouched by the storey work.
    * ``level_matrix`` - storey×storey (integer keys). The meaningful
      view for the common single-discipline intra-model run, where the
      discipline matrix collapses to a useless 1×1. Built only from
      result rows whose *both* storeys are known (non-NULL); a clash with
      an unknown storey is still counted in every other aggregate.

    ``storeys`` is the sorted distinct set of storey indices appearing in
    the level matrix (its row/column axis).
    """
    disciplines: set[str] = set()
    cell: dict[tuple[str, str], dict[str, int]] = {}
    storeys: set[int] = set()
    level_cell: dict[tuple[int, int], dict[str, int]] = {}
    by_status: dict[str, int] = {}
    by_type: dict[str, int] = {}
    by_severity: dict[str, int] = dict.fromkeys(CLASH_SEVERITIES, 0)
    for r in results:
        a, b = sorted((r.a_discipline or "Unassigned", r.b_discipline or "Unassigned"))
        disciplines.add(a)
        disciplines.add(b)
        c = cell.setdefault((a, b), {"count": 0, "open_count": 0})
        c["count"] += 1
        is_open = r.status in OPEN_STATUSES
        if is_open:
            c["open_count"] += 1
        by_status[r.status] = by_status.get(r.status, 0) + 1
        by_type[r.clash_type] = by_type.get(r.clash_type, 0) + 1
        sev = getattr(r, "severity", None) or "medium"
        by_severity[sev] = by_severity.get(sev, 0) + 1

        # Level matrix: only when both storeys resolved (NULL = unknown).
        sa_ = getattr(r, "a_storey", None)
        sb_ = getattr(r, "b_storey", None)
        if sa_ is not None and sb_ is not None:
            la, lb = (int(sa_), int(sb_)) if int(sa_) <= int(sb_) else (int(sb_), int(sa_))
            storeys.add(la)
            storeys.add(lb)
            lc = level_cell.setdefault((la, lb), {"count": 0, "open_count": 0})
            lc["count"] += 1
            if is_open:
                lc["open_count"] += 1

    matrix = [
        {"a": a, "b": b, "count": v["count"], "open_count": v["open_count"]} for (a, b), v in sorted(cell.items())
    ]
    level_matrix = [
        {"a": a, "b": b, "count": v["count"], "open_count": v["open_count"]} for (a, b), v in sorted(level_cell.items())
    ]
    return {
        "disciplines": sorted(disciplines),
        "matrix": matrix,
        "storeys": sorted(storeys),
        "level_matrix": level_matrix,
        "by_status": by_status,
        "by_type": by_type,
        "by_severity": by_severity,
    }


def _disc(value: object) -> str:
    """Normalise a discipline cell to a non-empty label."""
    return (str(value or "").strip()) or "Unassigned"


def _disc_system(disc: object, system: object) -> str:
    """Compose the ``discipline · system`` axis key for the system matrix.

    Falls back to the bare discipline when an element carried no system
    (so a partially-tagged model still groups meaningfully).
    """
    d = _disc(disc)
    s = str(system or "").strip()
    return f"{d} · {s}" if s else d


def _build_grouped_summary(results: list[ClashResult], dimension: str) -> dict:
    """Multi-dimensional grouping of a run's clashes (item #23).

    Exactly one payload is populated for ``dimension``; the rest stay
    empty so the response shape is stable. ``has_system_data`` reports
    whether ANY clash resolved a building system, so the UI can hide the
    ``discipline_system`` option when there is nothing to show.

    * ``discipline_pair`` - the flat discipline×discipline matrix (same
      cell shape as :func:`_build_summary`).
    * ``level`` - one ``{key, count, open_count}`` bucket per storey
      index; clashes whose level is unknown fall into the ``"(no level)"``
      bucket so the totals always add up.
    * ``level_discipline`` - a discipline×discipline matrix per storey
      (only rows whose level resolved); rendered as level tabs.
    * ``discipline_system`` - discipline·system × discipline·system grid.
    """
    has_system_data = any(
        (getattr(r, "a_element_system", "") or "").strip() or (getattr(r, "b_element_system", "") or "").strip()
        for r in results
    )
    out: dict = {
        "dimension": dimension,
        "disciplines": [],
        "matrix": [],
        "levels": [],
        "level_disciplines": [],
        "systems": [],
        "system_matrix": [],
        "has_system_data": has_system_data,
    }

    if dimension == "level":
        # 1-D: clashes per storey. Unknown level → "(no level)" bucket.
        buckets: dict[str, dict[str, int]] = {}
        for r in results:
            sa = getattr(r, "a_storey", None)
            sb = getattr(r, "b_storey", None)
            # A clash spans two levels; attribute it to the lower one when
            # both are known, else to whichever resolved, else (no level).
            level: str
            known = [int(s) for s in (sa, sb) if s is not None]
            level = str(min(known)) if known else "(no level)"
            c = buckets.setdefault(level, {"count": 0, "open_count": 0})
            c["count"] += 1
            if r.status in OPEN_STATUSES:
                c["open_count"] += 1

        def _level_sort(key: str) -> tuple[int, int]:
            # Numeric levels sort ascending; "(no level)" sorts last.
            try:
                return (0, int(key))
            except ValueError:
                return (1, 0)

        out["levels"] = [
            {"key": k, "count": v["count"], "open_count": v["open_count"]}
            for k, v in sorted(buckets.items(), key=lambda kv: _level_sort(kv[0]))
        ]
        return out

    if dimension == "level_discipline":
        # discipline×discipline matrix per storey (both storeys known).
        per_level: dict[int, dict[tuple[str, str], dict[str, int]]] = {}
        for r in results:
            sa = getattr(r, "a_storey", None)
            sb = getattr(r, "b_storey", None)
            if sa is None or sb is None:
                continue
            lvl = min(int(sa), int(sb))
            a, b = sorted((_disc(r.a_discipline), _disc(r.b_discipline)))
            cell = per_level.setdefault(lvl, {}).setdefault((a, b), {"count": 0, "open_count": 0})
            cell["count"] += 1
            if r.status in OPEN_STATUSES:
                cell["open_count"] += 1
        out["level_disciplines"] = [
            {
                "level": lvl,
                "cells": [
                    {"a": a, "b": b, "count": v["count"], "open_count": v["open_count"]}
                    for (a, b), v in sorted(cells.items())
                ],
            }
            for lvl, cells in sorted(per_level.items())
        ]
        return out

    if dimension == "discipline_system":
        systems: set[str] = set()
        cell_s: dict[tuple[str, str], dict[str, int]] = {}
        for r in results:
            a = _disc_system(r.a_discipline, getattr(r, "a_element_system", ""))
            b = _disc_system(r.b_discipline, getattr(r, "b_element_system", ""))
            a, b = sorted((a, b))
            systems.add(a)
            systems.add(b)
            cell = cell_s.setdefault((a, b), {"count": 0, "open_count": 0})
            cell["count"] += 1
            if r.status in OPEN_STATUSES:
                cell["open_count"] += 1
        out["systems"] = sorted(systems)
        out["system_matrix"] = [
            {"a": a, "b": b, "count": v["count"], "open_count": v["open_count"]} for (a, b), v in sorted(cell_s.items())
        ]
        return out

    # Default: discipline_pair (flat discipline×discipline matrix).
    disciplines: set[str] = set()
    cell_d: dict[tuple[str, str], dict[str, int]] = {}
    for r in results:
        a, b = sorted((_disc(r.a_discipline), _disc(r.b_discipline)))
        disciplines.add(a)
        disciplines.add(b)
        cell = cell_d.setdefault((a, b), {"count": 0, "open_count": 0})
        cell["count"] += 1
        if r.status in OPEN_STATUSES:
            cell["open_count"] += 1
    out["dimension"] = "discipline_pair"
    out["disciplines"] = sorted(disciplines)
    out["matrix"] = [
        {"a": a, "b": b, "count": v["count"], "open_count": v["open_count"]} for (a, b), v in sorted(cell_d.items())
    ]
    return out
