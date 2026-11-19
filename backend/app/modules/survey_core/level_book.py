# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Level book reduction: backsight / intermediate / foresight readings to adjusted RLs.

A book is a list of rows in field order. The first row is the starting
benchmark with its RL and a backsight. A change point carries a foresight
(closing the setup) and a backsight (opening the next one). An intermediate
sight is read from the current setup only. The last row is the closing
benchmark with a foresight.

* Rise-and-fall: ``rise = previous reading - this reading`` of one setup.
* Height of instrument: ``HI = RL + BS``, ``RL = HI - IS/FS``.

Both give the same RLs; the method decides which columns the book shows.
Arithmetic check: ``sum BS - sum FS = sum rise - sum fall = last RL - first RL``
(SRV-060). The misclosure against the known closing RL is spread in proportion
to the distance run from the start, so the closing benchmark lands on its
known RL. ``distance_m`` on a row is the distance from the previous change
point (or the start); an intermediate sight does not advance the run.
"""

from __future__ import annotations

from dataclasses import dataclass, field

RISE_FALL = "rise_fall"
HEIGHT_OF_INSTRUMENT = "hi"
_ARITH_TOL = 0.0005


@dataclass(frozen=True)
class BookRow:
    station: str
    bs: float | None = None
    is_: float | None = None
    fs: float | None = None
    distance_m: float | None = None
    #: An RL the person reduced by hand; checked by SRV-060, never used.
    rl_entered: float | None = None


@dataclass
class ReducedRow:
    station: str
    bs: float | None
    is_: float | None
    fs: float | None
    rise: float | None
    fall: float | None
    hi: float | None
    rl: float
    run_m: float
    correction_m: float
    rl_adjusted: float
    #: Correction of this setup in mm, rounded to 0.1 mm with the rounding left on the last one.
    step_mm: float = 0.0


@dataclass
class LevelBookResult:
    method: str
    rows: list[ReducedRow] = field(default_factory=list)
    sum_bs: float = 0.0
    sum_fs: float = 0.0
    sum_rise: float = 0.0
    sum_fall: float = 0.0
    first_rl: float = 0.0
    last_rl: float = 0.0
    #: Last RL as the person entered it (hand reduction), else the computed one.
    last_rl_checked: float = 0.0
    arithmetic_ok: bool = True
    known_close_rl: float | None = None
    misclosure_mm: float | None = None
    distance_km: float = 0.0


def reduce(
    rows: list[BookRow], start_rl: float, close_rl: float | None = None, method: str = RISE_FALL
) -> LevelBookResult:
    """Reduce a level book and distribute the misclosure by distance.

    Raises:
        ValueError: when the book does not open with a backsight or close with a foresight.
    """
    if len(rows) < 2:
        raise ValueError("A level book needs at least two rows")
    if rows[0].bs is None:
        raise ValueError("The first row needs a backsight")
    if rows[-1].fs is None:
        raise ValueError("The last row needs a foresight")
    out = LevelBookResult(method=method, first_rl=start_rl)
    hi = start_rl + rows[0].bs
    previous = rows[0].bs
    rl = start_rl
    run = 0.0
    out.rows.append(ReducedRow(rows[0].station, rows[0].bs, None, None, None, None, hi, rl, 0.0, 0.0, rl))
    out.sum_bs = rows[0].bs
    for row in rows[1:]:
        reading = row.fs if row.fs is not None else row.is_
        if reading is None:
            raise ValueError(f"Row {row.station} has no intermediate or foresight reading")
        diff = previous - reading
        rl = hi - reading
        is_change = row.fs is not None
        this_run = run + (row.distance_m or 0.0)
        if is_change:
            run = this_run
            out.sum_fs += row.fs  # type: ignore[operator]
        out.sum_rise += max(diff, 0.0)
        out.sum_fall += max(-diff, 0.0)
        out.rows.append(
            ReducedRow(
                row.station,
                row.bs,
                None if is_change else row.is_,
                row.fs,
                diff if diff >= 0 else None,
                -diff if diff < 0 else None,
                None,
                rl,
                this_run,
                0.0,
                rl,
            )
        )
        if row.bs is not None:
            if not is_change:
                raise ValueError(f"Row {row.station} has a backsight without a foresight")
            out.sum_bs += row.bs
            hi = rl + row.bs
            out.rows[-1].hi = hi
            previous = row.bs
        else:
            previous = reading
    out.last_rl = rl
    last_entered = rows[-1].rl_entered
    out.last_rl_checked = last_entered if last_entered is not None else rl
    first_entered = rows[0].rl_entered if rows[0].rl_entered is not None else start_rl
    target = out.last_rl_checked - first_entered
    out.arithmetic_ok = (
        abs((out.sum_bs - out.sum_fs) - target) <= _ARITH_TOL
        and abs((out.sum_rise - out.sum_fall) - (out.last_rl - start_rl)) <= _ARITH_TOL
    )
    out.distance_km = run / 1000.0
    if close_rl is not None:
        out.known_close_rl = close_rl
        w = rl - close_rl
        out.misclosure_mm = w * 1000.0
        for r in out.rows:
            r.correction_m = -w * (r.run_m / run) if run > 0 else 0.0
            r.rl_adjusted = r.rl + r.correction_m
        _steps(out.rows, round(-w * 1000.0, 1))
    return out


def _steps(rows: list[ReducedRow], total_mm: float) -> None:
    changes = [r for r in rows[1:] if r.fs is not None]
    previous, shown = 0.0, 0.0
    for i, r in enumerate(changes):
        if i == len(changes) - 1:
            r.step_mm = round(total_mm - shown, 1)
            break
        r.step_mm = round((r.correction_m - previous) * 1000.0, 1)
        previous = r.correction_m
        shown += r.step_mm


__all__ = ["HEIGHT_OF_INSTRUMENT", "RISE_FALL", "BookRow", "LevelBookResult", "ReducedRow", "reduce"]
