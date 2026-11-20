# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Least-squares adjustment of a field traverse (parametric, Gauss-Markov).

The same observations as :mod:`field_traverse` (one angle right per station,
one distance per leg) are adjusted together, each weighted by its a priori
standard deviation:

* angle: ``sd_angle`` plus target centering ``sd_c / D`` on both sights;
* distance: ``a mm + b ppm`` plus centering on both ends.

Unknowns are the E, N of every station that is not fixed. A loop fixes the
start station and the azimuth of its first leg (a hard constraint, solved with
a bordered normal matrix); a link fixes both end stations and both reference
azimuths. Redundancy is three either way: the angular and the two coordinate
closures.

Outputs: adjusted coordinates, residuals, the a posteriori variance factor with
a two-sided chi-square test, standardized residuals (largest flagged, Baarda's
3.29 marks a suspected blunder), absolute error ellipses per station and
relative ellipses per leg, one sigma, from the a priori variance factor.
Multiply the semi-axes by ``CONFIDENCE_95`` for the 95 % ellipse.

Instrument classes are manufacturer accuracy grades, the same in every market;
the person can edit every value.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from app.modules.survey_core.field_traverse import LINK, LOOP, Station
from app.modules.survey_core.field_traverse import adjust as bowditch

RHO = 180.0 / math.pi * 3600.0  # arc seconds per radian
#: Two-dimensional 95 % factor, ``sqrt(chi2(2, 0.95))``.
CONFIDENCE_95 = math.sqrt(-2.0 * math.log(0.05))
#: Baarda's critical value for a standardized residual (alpha 0.001, two-sided).
BAARDA_CRITICAL = 3.29


@dataclass(frozen=True)
class InstrumentClass:
    key: str
    angle_sd_sec: float
    dist_sd_mm: float
    dist_ppm: float
    centering_sd_mm: float = 1.0


INSTRUMENT_CLASSES: tuple[InstrumentClass, ...] = (
    InstrumentClass("ts_1", 1.0, 1.0, 1.0),
    InstrumentClass("ts_2", 2.0, 2.0, 2.0),
    InstrumentClass("ts_5", 5.0, 3.0, 2.0),
)


@dataclass(frozen=True)
class Weights:
    angle_sd_sec: float
    dist_sd_mm: float
    dist_ppm: float = 0.0
    centering_sd_mm: float = 0.0


@dataclass
class Residual:
    kind: str  # "angle" or "distance"
    ref: str  # station id, or "A-B" for a leg
    observed: float  # degrees or metres
    residual: float  # arc seconds or millimetres
    sd: float  # a priori, arc seconds or millimetres
    redundancy: float
    standardized: float | None
    flagged: bool = False
    suspect: bool = False


@dataclass
class Ellipse:
    ref: str
    a_m: float
    b_m: float
    #: Azimuth of the major axis, degrees from grid north, 0..180.
    azimuth_deg: float
    sd_e_m: float = 0.0
    sd_n_m: float = 0.0


@dataclass
class LsqStation:
    station_id: str
    e: float
    n: float
    fixed: bool


@dataclass
class LsqResult:
    shape: str
    iterations: int
    observations: int
    unknowns: int
    redundancy: int
    vtpv: float
    sigma0: float
    chi2_lower: float
    chi2_upper: float
    chi2_pass: bool
    alpha: float
    stations: list[LsqStation] = field(default_factory=list)
    residuals: list[Residual] = field(default_factory=list)
    ellipses: list[Ellipse] = field(default_factory=list)
    relative_ellipses: list[Ellipse] = field(default_factory=list)


# ── chi-square quantiles without scipy ──────────────────────────────────────


def _gammp(a: float, x: float) -> float:
    """Regularized lower incomplete gamma P(a, x) (series, else continued fraction)."""
    if x <= 0:
        return 0.0
    gln = math.lgamma(a)
    if x < a + 1.0:
        term = total = 1.0 / a
        ap = a
        for _ in range(500):
            ap += 1.0
            term *= x / ap
            total += term
            if abs(term) < abs(total) * 1e-15:
                break
        return total * math.exp(-x + a * math.log(x) - gln)
    b, c, d = x + 1.0 - a, 1.0 / 1e-300, 1.0 / (x + 1.0 - a)
    h = d
    for i in range(1, 500):
        an = -i * (i - a)
        b += 2.0
        d = an * d + b
        d = 1e-300 if abs(d) < 1e-300 else d
        c = b + an / c
        c = 1e-300 if abs(c) < 1e-300 else c
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < 1e-15:
            break
    return 1.0 - math.exp(-x + a * math.log(x) - gln) * h


def chi2_cdf(x: float, dof: int) -> float:
    return _gammp(dof / 2.0, x / 2.0)


def chi2_quantile(p: float, dof: int) -> float:
    """Inverse chi-square CDF by bisection; exact to 1e-10."""
    lo, hi = 0.0, max(10.0, dof * 10.0)
    while chi2_cdf(hi, dof) < p:
        hi *= 2.0
    for _ in range(200):
        mid = (lo + hi) / 2.0
        if chi2_cdf(mid, dof) < p:
            lo = mid
        else:
            hi = mid
        if hi - lo < 1e-10:
            break
    return (lo + hi) / 2.0


# ── geometry ────────────────────────────────────────────────────────────────


def _az(e1: float, n1: float, e2: float, n2: float) -> float:
    return math.atan2(e2 - e1, n2 - n1) % (2.0 * math.pi)


def _wrap(rad: float) -> float:
    return (rad + math.pi) % (2.0 * math.pi) - math.pi


def ellipse(qee: float, qnn: float, qen: float, ref: str = "") -> Ellipse:
    """Semi-axes and orientation of the standard ellipse of a 2x2 covariance (m^2)."""
    mid = (qee + qnn) / 2.0
    rad = math.sqrt(max(((qee - qnn) / 2.0) ** 2 + qen**2, 0.0))
    a = math.sqrt(max(mid + rad, 0.0))
    b = math.sqrt(max(mid - rad, 0.0))
    theta = math.degrees(0.5 * math.atan2(2.0 * qen, qnn - qee)) % 180.0
    return Ellipse(ref, a, b, theta, math.sqrt(max(qee, 0.0)), math.sqrt(max(qnn, 0.0)))


def adjust_lsq(
    shape: str,
    start: tuple[float, float],
    azimuth_deg: float,
    stations: list[Station],
    weights: Weights,
    angle_sense: str = "right",
    end: tuple[float, float] | None = None,
    closing_azimuth_deg: float | None = None,
    alpha: float = 0.05,
    max_iterations: int = 10,
) -> LsqResult:
    """Parametric least-squares adjustment of a loop or link traverse.

    Args:
        shape: ``loop`` or ``link``.
        start: E, N of the first station (fixed).
        azimuth_deg: loop - azimuth of the first leg (fixed); link - backsight azimuth at the start.
        stations: in traverse order, as for the Bowditch adjustment.
        weights: a priori standard deviations.
        angle_sense: ``right`` or ``left``.
        end: link only - E, N of the last station (fixed).
        closing_azimuth_deg: link only - forward reference azimuth at the last station.
        alpha: significance level of the two-sided chi-square test.
        max_iterations: Gauss-Newton iterations at most.

    Raises:
        ValueError: on observations that cannot form the traverse, zero weights or a singular geometry.
    """
    if weights.angle_sd_sec <= 0 or (weights.dist_sd_mm <= 0 and weights.dist_ppm <= 0):
        raise ValueError("Every observation needs a positive standard deviation")
    # Bowditch gives the approximate coordinates and validates the input.
    approx = bowditch(shape, start, azimuth_deg, stations, angle_sense, end, closing_azimuth_deg)
    n = len(stations)
    ids = [s.station_id for s in stations]
    if len(set(ids)) != n:
        raise ValueError("Station IDs must be unique")
    angles = [math.radians(s.angle_deg if angle_sense == "right" else 360.0 - s.angle_deg) for s in stations]
    xy = np.array([[s.e, s.n] for s in approx.stations], dtype=float)
    if shape == LINK:
        xy[-1] = end  # type: ignore[assignment]
    fixed = {0} if shape == LOOP else {0, n - 1}
    free = [i for i in range(n) if i not in fixed]
    col = {st: 2 * k for k, st in enumerate(free)}
    u = 2 * len(free)
    legs = [(i, (i + 1) % n) for i in range(n)] if shape == LOOP else [(i, i + 1) for i in range(n - 1)]
    back_az = math.radians(azimuth_deg)
    close_az = math.radians(closing_azimuth_deg) if closing_azimuth_deg is not None else 0.0
    sd_c = weights.centering_sd_mm / 1000.0

    def dist(i: int, j: int) -> float:
        return float(math.hypot(xy[j, 0] - xy[i, 0], xy[j, 1] - xy[i, 1]))

    def az_row(i: int, j: int, row: np.ndarray, sign: float) -> None:
        de, dn = xy[j, 0] - xy[i, 0], xy[j, 1] - xy[i, 1]
        d2 = de * de + dn * dn
        if d2 <= 1e-6:  # closer than a millimetre
            raise ValueError("Two stations coincide; the geometry cannot be adjusted")
        for p, ce, cn in ((j, dn / d2, -de / d2), (i, -dn / d2, de / d2)):
            if p in col:
                row[col[p]] += sign * ce
                row[col[p] + 1] += sign * cn

    def model() -> tuple[np.ndarray, np.ndarray, np.ndarray, list[tuple[str, str, float, float]]]:
        rows, comp, sds, meta = [], [], [], []
        for k in range(n):
            row = np.zeros(u)
            if shape == LOOP:
                b, f = (k - 1) % n, (k + 1) % n
                value = _az(*xy[k], *xy[f]) - _az(*xy[k], *xy[b])
                az_row(k, f, row, 1.0)
                az_row(k, b, row, -1.0)
                sights = [dist(k, b), dist(k, f)]
            elif k == 0:
                value = _az(*xy[0], *xy[1]) - back_az
                az_row(0, 1, row, 1.0)
                sights = [dist(0, 1)]
            elif k == n - 1:
                value = close_az - _az(*xy[k], *xy[k - 1])
                az_row(k, k - 1, row, -1.0)
                sights = [dist(k, k - 1)]
            else:
                value = _az(*xy[k], *xy[k + 1]) - _az(*xy[k], *xy[k - 1])
                az_row(k, k + 1, row, 1.0)
                az_row(k, k - 1, row, -1.0)
                sights = [dist(k, k - 1), dist(k, k + 1)]
            sd = math.sqrt((weights.angle_sd_sec / RHO) ** 2 + sum((sd_c / s) ** 2 for s in sights if s > 0))  # radians
            rows.append(row)
            comp.append(_wrap(value - angles[k]))
            sds.append(sd)
            meta.append(("angle", ids[k], math.degrees(angles[k]), sd * RHO))
        for i, j in legs:
            d = dist(i, j)
            if d <= 1e-3:
                raise ValueError("Two stations coincide; the geometry cannot be adjusted")
            row = np.zeros(u)
            de, dn = xy[j, 0] - xy[i, 0], xy[j, 1] - xy[i, 1]
            for p, ce, cn in ((j, de / d, dn / d), (i, -de / d, -dn / d)):
                if p in col:
                    row[col[p]] += ce
                    row[col[p] + 1] += cn
            obs = stations[i].distance_m or 0.0
            sd = math.sqrt((weights.dist_sd_mm / 1000.0) ** 2 + (weights.dist_ppm * 1e-6 * obs) ** 2 + 2.0 * sd_c**2)
            rows.append(row)
            comp.append(d - obs)
            sds.append(sd)
            meta.append(("distance", f"{ids[i]}-{ids[j]}", obs, sd * 1000.0))
        return np.array(rows).reshape(len(rows), u), np.array(comp), np.array(sds), meta

    def constraint() -> tuple[np.ndarray, np.ndarray]:
        if shape != LOOP:
            return np.zeros((0, u)), np.zeros(0)
        row = np.zeros(u)
        az_row(0, 1, row, 1.0)
        return row.reshape(1, u), np.array([_wrap(back_az - _az(*xy[0], *xy[1]))])

    iterations = 0
    qxx = np.zeros((u, u))
    for iterations in range(1, max_iterations + 1):  # noqa: B007
        a_mat, comp, sds, _ = model()
        p = 1.0 / sds**2
        l_vec = -comp  # observed minus computed
        normal = a_mat.T @ (a_mat * p[:, None])
        rhs = a_mat.T @ (p * l_vec)
        c_mat, c_vec = constraint()
        k = c_mat.shape[0]
        bordered = np.zeros((u + k, u + k))
        bordered[:u, :u] = normal
        bordered[:u, u:] = c_mat.T
        bordered[u:, :u] = c_mat
        if u + k == 0:
            break
        if np.linalg.matrix_rank(bordered) < u + k:
            raise ValueError("The geometry is singular; the traverse cannot be adjusted")
        inv = np.linalg.inv(bordered)
        qxx = inv[:u, :u]
        dx = inv @ np.concatenate([rhs, c_vec])
        for st, c in col.items():
            xy[st, 0] += dx[c]
            xy[st, 1] += dx[c + 1]
        if np.max(np.abs(dx[:u]), initial=0.0) < 1e-7:
            break

    a_mat, comp, sds, meta = model()
    p = 1.0 / sds**2
    v = comp  # adjusted minus observed
    vtpv = float(np.sum(p * v * v))
    m = len(v)
    k = 1 if shape == LOOP else 0
    r = m - u + k
    if r <= 0:
        raise ValueError("The traverse has no redundancy to adjust")
    qvv = 1.0 / p - np.einsum("ij,jk,ik->i", a_mat, qxx, a_mat)
    sigma0 = math.sqrt(vtpv / r)
    lower = chi2_quantile(alpha / 2.0, r)
    upper = chi2_quantile(1.0 - alpha / 2.0, r)

    residuals: list[Residual] = []
    for i, (kind, ref, obs, sd) in enumerate(meta):
        q = float(qvv[i])
        red = q * float(p[i])
        w = float(v[i] / math.sqrt(q)) if red > 1e-6 else None
        scale = RHO if kind == "angle" else 1000.0
        residuals.append(Residual(kind, ref, obs, float(v[i]) * scale, sd, red, w))
    scored = [x for x in residuals if x.standardized is not None]
    if scored:
        worst = max(scored, key=lambda x: abs(x.standardized or 0.0))
        worst.flagged = True
        for x in scored:
            x.suspect = abs(x.standardized or 0.0) > BAARDA_CRITICAL

    def cov(i: int, j: int) -> np.ndarray:
        out = np.zeros((2, 2))
        if i in col and j in col:
            out = qxx[col[i] : col[i] + 2, col[j] : col[j] + 2]
        return out

    ellipses = [ellipse(*_q3(cov(i, i)), ref=ids[i]) for i in free]
    relative = []
    for i, j in legs:
        q = cov(i, i) + cov(j, j) - cov(i, j) - cov(j, i)
        relative.append(ellipse(*_q3(q), ref=f"{ids[i]}-{ids[j]}"))

    return LsqResult(
        shape=shape,
        iterations=iterations,
        observations=m,
        unknowns=u,
        redundancy=r,
        vtpv=vtpv,
        sigma0=sigma0,
        chi2_lower=lower,
        chi2_upper=upper,
        chi2_pass=lower <= vtpv <= upper,
        alpha=alpha,
        stations=[LsqStation(ids[i], float(xy[i, 0]), float(xy[i, 1]), i in fixed) for i in range(n)],
        residuals=residuals,
        ellipses=ellipses,
        relative_ellipses=relative,
    )


def _q3(q: np.ndarray) -> tuple[float, float, float]:
    return float(q[0, 0]), float(q[1, 1]), float((q[0, 1] + q[1, 0]) / 2.0)


__all__ = [
    "BAARDA_CRITICAL",
    "CONFIDENCE_95",
    "INSTRUMENT_CLASSES",
    "Ellipse",
    "InstrumentClass",
    "LsqResult",
    "LsqStation",
    "Residual",
    "Weights",
    "adjust_lsq",
    "chi2_quantile",
    "ellipse",
]
