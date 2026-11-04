"""Match the sheets of two drawing revisions and align measurement geometry (pure, no DB).

Carry-over used to copy a measurement to the same page number at the same pixels.
That is wrong when a sheet is inserted (page order shifts) or when the new
revision is shifted, cropped or redrawn at a slightly different scale. This
module proposes where each measurement lands and how sure it is; a human
confirms every proposal (nothing here writes anything).

* :func:`match_pages` pairs old and new sheets by sheet number, then title, and
  only falls back to page order when a side carries no sheet identity at all.
* :func:`estimate_transform` fits a similarity transform (uniform scale plus
  shift, no rotation) to anchor pairs, with the RMS residual of the fit.
* :func:`confidence` folds page match, alignment residual and scale verdict into
  one 0..1 number; :func:`band` turns it into high / review / remeasure.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any

#: Bands, in order: at or above HIGH the proposal is safe to accept in bulk;
#: from REVIEW up it needs a look; below it the measurement is not copied.
HIGH = 0.85
REVIEW = 0.6

METHOD_TITLE = "title"
METHOD_INDEX = "index"
METHOD_MANUAL = "manual"

BAND_HIGH = "high"
BAND_REVIEW = "review"
BAND_REMEASURE = "remeasure"

#: Without anchor pairs the geometry is unverified, so it can never reach HIGH.
UNALIGNED_FACTOR = 0.8
#: A residual of this fraction of the page diagonal zeroes the alignment factor.
RESIDUAL_LIMIT = 0.02

_SCALE_FACTOR = {"same": 1.0, "not_applicable": 1.0, "changed": 0.9, "unverified": 0.8}
_TITLE_FUZZY_MIN = 0.85


@dataclass(frozen=True, slots=True)
class PageMatch:
    """One old sheet and the new sheet proposed for it (``new`` is None when none fits)."""

    old: int
    new: int | None
    score: float
    method: str

    def as_dict(self) -> dict[str, Any]:
        """JSON shape of the API."""
        return {"old": self.old, "new": self.new, "score": round(self.score, 3), "method": self.method}


@dataclass(frozen=True, slots=True)
class Transform:
    """``new = scale * old + (dx, dy)``; ``ok`` is False when no fit was possible."""

    scale: float = 1.0
    dx: float = 0.0
    dy: float = 0.0
    residual: float = 0.0
    ok: bool = False

    def as_dict(self) -> dict[str, Any]:
        """JSON shape of the API."""
        return {
            "scale": round(self.scale, 6),
            "dx": round(self.dx, 3),
            "dy": round(self.dy, 3),
            "residual": round(self.residual, 3),
            "ok": self.ok,
        }


def _norm(text: Any) -> str:
    return re.sub(r"[^0-9a-z]+", "", str(text or "").lower())


def match_pages(
    old_meta: list[dict[str, Any]],
    new_meta: list[dict[str, Any]],
    page_map: dict[int, int] | None = None,
) -> list[PageMatch]:
    """Pair every old page with at most one new page.

    ``old_meta`` / ``new_meta`` are ``{"page": int, "number": str|None, "title": str|None}``.
    ``page_map`` (old -> new) is the human override and always wins. Matching
    order: sheet number (1.0), exact title (0.9), near title (0.9 * similarity),
    then page order, but page order only for a page whose side has no sheet
    number or title (0.7 when both documents have the same page count, else 0.5).
    A page with identity that matches nothing is reported as missing, never
    silently paired by position.
    """
    new_by_page = {int(m["page"]): m for m in new_meta}
    claimed: set[int] = set()
    out: dict[int, PageMatch] = {}

    for old_page, new_page in (page_map or {}).items():
        if new_page in new_by_page and new_page not in claimed:
            out[int(old_page)] = PageMatch(int(old_page), int(new_page), 1.0, METHOD_MANUAL)
            claimed.add(int(new_page))

    olds = [m for m in old_meta if int(m["page"]) not in out]

    def assign(score_of: Any, method: str) -> None:
        pairs: list[tuple[float, int, int]] = []
        for o in olds:
            if int(o["page"]) in out:
                continue
            for n in new_meta:
                if int(n["page"]) in claimed:
                    continue
                s = score_of(o, n)
                if s > 0:
                    pairs.append((s, int(o["page"]), int(n["page"])))
        # Best score first; ties go to the lower page numbers so the result is stable.
        for s, op, np_ in sorted(pairs, key=lambda p: (-p[0], p[1], p[2])):
            if op in out or np_ in claimed:
                continue
            out[op] = PageMatch(op, np_, s, method)
            claimed.add(np_)

    def by_number(o: dict[str, Any], n: dict[str, Any]) -> float:
        a, b = _norm(o.get("number")), _norm(n.get("number"))
        return 1.0 if a and a == b else 0.0

    def by_title(o: dict[str, Any], n: dict[str, Any]) -> float:
        a, b = _norm(o.get("title")), _norm(n.get("title"))
        if not a or not b:
            return 0.0
        if a == b:
            return 0.9
        ratio = SequenceMatcher(None, a, b).ratio()
        return round(0.9 * ratio, 3) if ratio >= _TITLE_FUZZY_MIN else 0.0

    assign(by_number, METHOD_TITLE)
    assign(by_title, METHOD_TITLE)

    same_count = len(old_meta) == len(new_meta)
    new_blank = {int(n["page"]): not (_norm(n.get("number")) or _norm(n.get("title"))) for n in new_meta}

    def by_index(o: dict[str, Any], n: dict[str, Any]) -> float:
        if int(o["page"]) != int(n["page"]):
            return 0.0
        if _norm(o.get("number")) or _norm(o.get("title")) or not new_blank[int(n["page"])]:
            return 0.0
        return 0.7 if same_count else 0.5

    assign(by_index, METHOD_INDEX)

    return [out.get(int(m["page"])) or PageMatch(int(m["page"]), None, 0.0, METHOD_INDEX) for m in old_meta]


def anchor_xy(point: Any) -> tuple[float, float] | None:
    try:
        if isinstance(point, dict):
            return float(point["x"]), float(point["y"])
        if isinstance(point, (list, tuple)) and len(point) >= 2:
            return float(point[0]), float(point[1])
    except (KeyError, TypeError, ValueError):
        return None
    return None


def estimate_transform(old_anchors: list[Any], new_anchors: list[Any]) -> Transform:
    """Least-squares similarity fit (uniform scale and shift) from paired anchors.

    Fewer than two usable pairs, or anchors that coincide, give ``ok=False``
    with the identity so the caller can fall back to "no alignment".
    """
    pairs = []
    for a, b in zip(old_anchors or [], new_anchors or [], strict=False):
        pa, pb = anchor_xy(a), anchor_xy(b)
        if pa and pb:
            pairs.append((pa, pb))
    if len(pairs) < 2:
        return Transform()
    n = len(pairs)
    ox = sum(p[0][0] for p in pairs) / n
    oy = sum(p[0][1] for p in pairs) / n
    nx = sum(p[1][0] for p in pairs) / n
    ny = sum(p[1][1] for p in pairs) / n
    denom = sum((p[0][0] - ox) ** 2 + (p[0][1] - oy) ** 2 for p in pairs)
    if denom <= 1e-12:
        return Transform()
    num = sum((p[0][0] - ox) * (p[1][0] - nx) + (p[0][1] - oy) * (p[1][1] - ny) for p in pairs)
    scale = num / denom
    if scale <= 0:
        return Transform()
    dx, dy = nx - scale * ox, ny - scale * oy
    sq = sum((scale * p[0][0] + dx - p[1][0]) ** 2 + (scale * p[0][1] + dy - p[1][1]) ** 2 for p in pairs)
    return Transform(scale=scale, dx=dx, dy=dy, residual=math.sqrt(sq / n), ok=True)


def apply_transform(points: list[Any], t: Transform) -> list[dict[str, float]]:
    """Map ``{x, y}`` points through ``t``; unusable points are dropped."""
    out: list[dict[str, float]] = []
    for p in points or []:
        xy = anchor_xy(p)
        if xy:
            out.append({"x": round(t.scale * xy[0] + t.dx, 3), "y": round(t.scale * xy[1] + t.dy, 3)})
    return out


def confidence(page_score: float, t: Transform, page_diagonal: float | None, scale_check: str) -> float:
    """Confidence 0..1 that a carried measurement sits right on the new sheet.

    Falls monotonically as the fit residual grows (relative to the page
    diagonal), is capped below HIGH when nothing could verify the geometry, and
    is reduced when the new sheet's scale differs from or is missing against the
    old one.
    """
    if t.ok:
        diag = page_diagonal if page_diagonal and page_diagonal > 0 else 1000.0
        align = max(0.0, 1.0 - min(t.residual / (diag * RESIDUAL_LIMIT), 1.0))
    else:
        align = UNALIGNED_FACTOR
    value = page_score * align * _SCALE_FACTOR.get(scale_check, 0.8)
    return round(max(0.0, min(1.0, value)), 3)


def band(value: float) -> str:
    """``high`` / ``review`` / ``remeasure`` for a confidence value."""
    if value >= HIGH:
        return BAND_HIGH
    return BAND_REVIEW if value >= REVIEW else BAND_REMEASURE
