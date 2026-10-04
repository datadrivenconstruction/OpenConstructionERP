"""The cost base import as it was before it streamed, kept as a test oracle.

This is ``_process_and_insert_cwicr`` from ``backend/app/modules/costs/router.py``
at commit c34df4f82, the last version that read the whole parquet into one pandas
frame, copied verbatim. Only the module-level names it used are qualified with
``_router.`` so they resolve, and patch, exactly as they did inside the router.

The streaming loader that replaced it promises the same rows, values, order and
flush boundaries. The tests compare the two on fixtures built to split every
hard case across tiny read batches, so a difference in the stream shows up as
a difference against this frozen behaviour instead of against a second copy of
the new code. Do not "fix" anything in here: its quirks are the contract.
"""

# ruff: noqa

from __future__ import annotations

import uuid
from typing import Any

from app.modules.costs import router as _router


def whole_frame_import(parquet_path: str, db_id: str, db_file: str) -> dict[str, Any]:
    """Process CWICR parquet + insert into PostgreSQL. Runs in a thread.

    Uses vectorized pandas (no iterrows!) and delegates the load to
    ``_pg_bulk_insert_cost_rows`` (PostgreSQL ``COPY`` into a staging table +
    ``INSERT ... ON CONFLICT (code, region) DO NOTHING``). ``db_file`` carries
    the sync SQLAlchemy URL (``postgresql+psycopg2://...``) of the target
    cluster.
    """
    import gc
    import json as _json
    import logging
    import math
    import time

    import pandas as pd

    _log = logging.getLogger("cwicr_import")
    start = time.monotonic()

    # 1. Read parquet - only the columns this function actually uses.
    # The full CWICR parquet has ~85 columns; loading them all doubles
    # memory for no reason and OOM-kills 4 GB servers.
    _NEEDED_COLUMNS = frozenset(
        {
            "rate_code",
            "rate_original_name",
            "rate_final_name",
            "rate_unit",
            "total_cost_per_position",
            "collection_name",
            "department_name",
            "section_name",
            "subsection_name",
            "category_type",
            "cost_of_working_hours",
            "total_value_machinery_equipment",
            "total_material_cost_per_position",
            "total_labor_hours_all_personnel",
            "count_total_people_per_unit",
            # Resource columns
            "resource_name",
            "resource_code",
            "resource_unit",
            "resource_quantity",
            "resource_cost",
            "resource_cost_eur",
            "resource_price_per_unit_current",
            "resource_price_per_unit_eur_current",
            "row_type",
            "is_machine",
            "is_material",
            "is_labor",
            # Scope of work
            "work_composition_text",
            "is_scope",
            # Abstract resource / variant columns
            "price_abstract_resource_variable_parts",
            "price_abstract_resource_est_price_all_values",
            "price_abstract_resource_position_count",
            "price_abstract_resource_est_price_min",
            "price_abstract_resource_est_price_max",
            "price_abstract_resource_est_price_mean",
            "price_abstract_resource_est_price_median",
            "price_abstract_resource_unit",
            "price_abstract_resource_group_per_unit",
            "price_abstract_resource_variable_parts_per_unit",
            "price_abstract_resource_est_price_all_values_per_unit",
            "price_abstract_resource_common_start",
        }
    )
    import pyarrow.parquet as pq

    _file_schema = pq.read_schema(parquet_path)
    _orig_by_lower = {n.strip().lower(): n for n in _file_schema.names}
    _use_cols = [_orig_by_lower[k] for k in _NEEDED_COLUMNS if k in _orig_by_lower]
    df = pd.read_parquet(parquet_path, columns=_use_cols or None)
    total_rows = len(df)
    df.columns = [str(c).strip().lower() for c in df.columns]

    if "rate_code" not in df.columns:
        return {"imported": 0, "skipped": 0, "total_rows": total_rows, "error": "no rate_code column"}

    # 2. Vectorized processing - use groupby.first() instead of iterrows
    if "rate_original_name" in df.columns and "rate_final_name" in df.columns:
        df["_desc"] = _router._join_work_name_columns(
            df["rate_original_name"].fillna("").astype(str).str.strip(),
            df["rate_final_name"].fillna("").astype(str).str.strip(),
            join=not _router.base_registry.is_national_region(db_id),
        )
    elif "rate_original_name" in df.columns:
        df["_desc"] = df["rate_original_name"].fillna("").astype(str)
    else:
        df["_desc"] = ""

    # Aggregate: take first row's values per rate_code (vectorized, no iteration)
    agg_cols = {}
    for col in [
        "_desc",
        "rate_unit",
        "total_cost_per_position",
        "collection_name",
        "department_name",
        "section_name",
        "subsection_name",
        "category_type",
        "cost_of_working_hours",
        "total_value_machinery_equipment",
        "total_material_cost_per_position",
        "total_labor_hours_all_personnel",
        "count_total_people_per_unit",
    ]:
        if col in df.columns:
            agg_cols[col] = "first"

    # Abstract-resource rows carry per-variant price options; preserve them so the UI can offer a picker.
    # Column names follow the actual CWICR parquet schema (variable_parts / est_price_all_values),
    # not the legacy aliases. position_count is a single per-rate_code total, not per-variant.
    _ABSTRACT_COLS = (
        "row_type",
        "price_abstract_resource_variable_parts",
        "price_abstract_resource_est_price_all_values",
        "price_abstract_resource_position_count",
        "price_abstract_resource_est_price_min",
        "price_abstract_resource_est_price_max",
        "price_abstract_resource_est_price_mean",
        "price_abstract_resource_est_price_median",
        "price_abstract_resource_unit",
        "price_abstract_resource_group_per_unit",
        "price_abstract_resource_variable_parts_per_unit",
        "price_abstract_resource_est_price_all_values_per_unit",
    )
    for col in _ABSTRACT_COLS:
        if col in df.columns:
            agg_cols[col] = "first"

    grouped = df.groupby("rate_code", sort=False).agg(agg_cols)
    _log.info("Grouped %d unique items from %d rows in %.1fs", len(grouped), total_rows, time.monotonic() - start)

    # 3. Build insert tuples (vectorized - no Python loop over rows)
    def _safe_float(v: object) -> float:
        if v is None:
            return 0.0
        try:
            f = float(v)  # type: ignore[arg-type]
            return 0.0 if math.isnan(f) else f
        except (ValueError, TypeError):
            return 0.0

    def _safe_str(v: object) -> str:
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return ""
        return str(v).strip()

    def _split_bul(value: object) -> list[str]:
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return []
        return [p.strip() for p in str(value).split("\u2022") if p.strip()]

    # 4. Pre-build resource components per rate_code using vectorized pandas
    # Filter out empty rows, then group resources by rate_code
    _LABOR_UNITS = {"hrs", "h", "person-hour", "person-hours", "man-hours"}

    # Handle column name variants across different CWICR regional databases:
    # Most databases use: resource_cost, resource_price_per_unit_current
    # ENG_TORONTO uses:   resource_cost_eur, resource_price_per_unit_eur_current
    _cost_col = "resource_cost" if "resource_cost" in df.columns else "resource_cost_eur"
    _price_col = (
        "resource_price_per_unit_current"
        if "resource_price_per_unit_current" in df.columns
        else "resource_price_per_unit_eur_current"
    )

    res_cols = [
        "rate_code",
        "resource_name",
        "resource_code",
        "resource_unit",
        "resource_quantity",
        _price_col,
        _cost_col,
        "row_type",
        "is_machine",
        "is_material",
        "is_labor",
    ]
    available_res_cols = [c for c in res_cols if c in df.columns]

    # ── Per-component variants index (from Abstract resource rows) ──
    # Each rate_code can have several "Абстрактный ресурс" / "Abstract
    # resource" rows - one per variable component (e.g. formwork type +
    # board type + crane type). Each row carries its own
    # ``price_abstract_resource_variable_parts`` list. We index by
    # (rate_code, resource_code) so we can stamp the variant catalog onto
    # the matching component below - replacing the previous "first row
    # wins, dump on the cost item" behaviour that lost 2 of 3 variant
    # slots on KANE_RINE_KAKARI_KARI and similar rates.
    def _strip_unit_prefix(tok: str) -> str:
        # First per-unit token can be prefixed with a unit marker
        # (e.g. ``м3=20688.85``) - strip it so we can parse the number.
        if "=" in tok:
            return tok.split("=", 1)[1].strip()
        return tok

    abstract_variants_by_pair: dict[tuple[str, str], dict[str, Any]] = {}
    if "price_abstract_resource_variable_parts" in df.columns and "resource_code" in df.columns:
        abs_mask = df["price_abstract_resource_variable_parts"].fillna("").astype(str).str.len() > 0
        # Narrow to just the columns this loop reads before iterating. Without
        # it, ``df[abs_mask].iterrows()`` materializes a Series across all ~85
        # parquet columns per row; selecting the dozen columns actually used
        # mirrors the scope-of-work index below and trims the per-row overhead.
        # Same row set, same values - only the unused columns are dropped.
        _abs_cols = [
            c
            for c in (
                "rate_code",
                "resource_code",
                "price_abstract_resource_variable_parts",
                "price_abstract_resource_est_price_all_values",
                "price_abstract_resource_est_price_all_values_per_unit",
                "price_abstract_resource_common_start",
                "price_abstract_resource_est_price_min",
                "price_abstract_resource_est_price_max",
                "price_abstract_resource_est_price_mean",
                "price_abstract_resource_est_price_median",
                "price_abstract_resource_unit",
                "price_abstract_resource_group_per_unit",
            )
            if c in df.columns
        ]
        for _, r in df.loc[abs_mask, _abs_cols].iterrows():
            rc = _safe_str(r.get("rate_code", ""))
            rescode = _safe_str(r.get("resource_code", ""))
            if not rc or not rescode:
                continue
            labels = _split_bul(r.get("price_abstract_resource_variable_parts"))
            values = _split_bul(r.get("price_abstract_resource_est_price_all_values"))
            pu_vals_raw = _split_bul(r.get("price_abstract_resource_est_price_all_values_per_unit"))
            pu_vals = [_strip_unit_prefix(t) for t in pu_vals_raw]
            if not labels or len(labels) < 2:
                continue
            # Many rate rows (e.g. KANE_RINE_KAKARI_KARI's three variant
            # slots) have an empty ``..._all_values`` column and only the
            # ``_per_unit`` series populated. Fall back to per-unit so we
            # still build the variant catalog instead of dropping it.
            if len(values) != len(labels) and len(pu_vals) == len(labels):
                values = pu_vals
            if len(values) != len(labels):
                continue
            # ``common_start`` is the shared abstract-resource base name
            # (e.g. "Beton, Sortenliste C") that prefixes every variant's
            # variable_part. Read it BEFORE building variants so each row's
            # ``full_label`` = ``common_start + label`` - what the BOQ
            # resource row + Resource Summary display after a pick. The
            # picker still renders ``label`` (variable part only) in its
            # accordion rows because ``stats.common_start`` shows the base
            # once as a header; the BOQ side has no header and needs the
            # full composed name on each entry.
            common_start = _safe_str(r.get("price_abstract_resource_common_start"))[:240]
            variants_l: list[dict] = []
            for i, (lbl, val) in enumerate(zip(labels, values, strict=False)):
                v = _safe_float(val)
                if v <= 0:
                    continue
                variable_part = lbl[:200]
                full_label = (f"{common_start} {variable_part}".strip() if common_start else variable_part)[:400]
                variants_l.append(
                    {
                        "index": i,
                        "label": variable_part,
                        "full_label": full_label,
                        "price": round(v, 2),
                        "price_per_unit": round(_safe_float(pu_vals[i]), 4) if i < len(pu_vals) else None,
                    }
                )
            if not variants_l:
                continue
            abstract_variants_by_pair[(rc, rescode)] = {
                "variants": variants_l,
                "variant_stats": {
                    "min": round(_safe_float(r.get("price_abstract_resource_est_price_min")), 2),
                    "max": round(_safe_float(r.get("price_abstract_resource_est_price_max")), 2),
                    "mean": round(_safe_float(r.get("price_abstract_resource_est_price_mean")), 2),
                    "median": round(_safe_float(r.get("price_abstract_resource_est_price_median")), 2),
                    "unit": _safe_str(r.get("price_abstract_resource_unit"))[:20],
                    "group": _safe_str(r.get("price_abstract_resource_group_per_unit"))[:120],
                    "count": len(variants_l),
                    "common_start": common_start,
                },
            }
    _log.info("Indexed %d per-component variant catalogs", len(abstract_variants_by_pair))

    # ── Scope-of-work index ──
    # ``work_composition_text`` carries the ordered steps describing HOW a
    # position is performed (e.g. "Установка телескопических стоек." /
    # "Bodenbearbeitung nach Maß." / "Préparation du sol."). The companion
    # ``is_scope`` flag is set in EN/RU exports but stays False in DE/FR
    # exports, so we don't gate on it - instead we treat any row with a
    # non-empty ``work_composition_text`` AND an empty ``resource_name`` as
    # a scope step. Verified universal across all 16 cached regional
    # parquets (168 120 scope rows in each, 0 overlaps with resource rows).
    scope_by_code: dict[str, list[str]] = {}
    if "work_composition_text" in df.columns:
        wct_str = df["work_composition_text"].fillna("").astype(str)
        rname_str = df["resource_name"].fillna("").astype(str) if "resource_name" in df.columns else None
        scope_mask = wct_str.str.len() > 0
        if rname_str is not None:
            scope_mask = scope_mask & (rname_str.str.len() == 0)
        scope_sub = df[scope_mask][["rate_code", "work_composition_text"]]
        for _, r in scope_sub.iterrows():
            rc = _safe_str(r.get("rate_code", ""))
            text = _safe_str(r.get("work_composition_text", ""))
            if not rc or not text or text == "nan":
                continue
            scope_by_code.setdefault(rc, []).append(text[:500])
    _log.info("Indexed scope_of_work for %d rate_codes", len(scope_by_code))

    resources_by_code: dict[str, list[dict]] = {}
    if "resource_name" in df.columns and _cost_col in df.columns:
        # Filter rows that have resource data (non-empty name, non-zero cost)
        res_df = df[
            available_res_cols
            + (
                ["price_abstract_resource_variable_parts"]
                if "price_abstract_resource_variable_parts" in df.columns
                else []
            )
        ].copy()
        res_df = res_df[res_df["resource_name"].fillna("").str.len() > 0]
        if _cost_col in res_df.columns:
            # A row is a genuine resource component when it carries EITHER a
            # cost OR a norm quantity. Coefficient bases (Vietnam Dinh Muc,
            # Indonesia AHSP) publish the full labour / material / machine
            # breakdown with norm quantities but no prices (priced regionally),
            # so gating on cost alone dropped every one of their resources.
            # Keeping rows that carry a quantity fixes that; priced bases are
            # unaffected (their resource rows already carry a cost) beyond also
            # retaining a few legitimately unpriced-but-quantified lines.
            _keep = res_df[_cost_col].fillna(0).astype(float).abs() > 0.001
            if "resource_quantity" in res_df.columns:
                _keep = _keep | (pd.to_numeric(res_df["resource_quantity"], errors="coerce").fillna(0.0).abs() > 1e-9)
            # Abstract-resource rows are variant slots the user picks from - keep
            # them even when both cost and quantity are zero. Without this
            # carve-out KAME-LI-MENE-KAPU and similar amortisation / option rows
            # get silently dropped and the user loses one of their variant picks.
            if "price_abstract_resource_variable_parts" in res_df.columns:
                _keep = _keep | (res_df["price_abstract_resource_variable_parts"].fillna("").astype(str).str.len() > 0)
            res_df = res_df[_keep]
        if "row_type" in res_df.columns:
            res_df = res_df[res_df["row_type"].fillna("") != "Scope of work"]

        # FULLY VECTORIZED: build component dicts via column operations, then
        # group by rate_code once using a dict accumulator. This replaces the
        # previous iterrows() loop which was O(N) Python interpreter overhead
        # (~5min for 900K rows → now ~5s).
        if len(res_df) > 0:
            # Normalize types
            res_df["_rc"] = res_df["rate_code"].astype(str)
            res_df["_name"] = res_df["resource_name"].fillna("").astype(str).str.slice(0, 200)
            res_df["_code"] = (
                res_df["resource_code"].fillna("").astype(str).str.slice(0, 50)
                if "resource_code" in res_df.columns
                else ""
            )
            res_df["_unit"] = (
                res_df["resource_unit"].fillna("").astype(str).str.slice(0, 20)
                if "resource_unit" in res_df.columns
                else ""
            )
            res_df["_qty"] = (
                pd.to_numeric(res_df["resource_quantity"], errors="coerce").fillna(0.0).round(4)
                if "resource_quantity" in res_df.columns
                else 0.0
            )
            res_df["_rate"] = (
                pd.to_numeric(res_df[_price_col], errors="coerce").fillna(0.0).round(2)
                if _price_col in res_df.columns
                else 0.0
            )
            res_df["_cost_v"] = pd.to_numeric(res_df[_cost_col], errors="coerce").fillna(0.0).round(2)

            # Compute ctype vectorized
            _row_type = res_df.get("row_type", pd.Series([""] * len(res_df), index=res_df.index)).fillna("").astype(str)
            _is_mach = (
                res_df.get("is_machine", pd.Series([False] * len(res_df), index=res_df.index))
                .fillna(False)
                .astype(bool)
            )
            _is_mat = (
                res_df.get("is_material", pd.Series([False] * len(res_df), index=res_df.index))
                .fillna(False)
                .astype(bool)
            )
            _unit_lc = res_df["_unit"].str.lower()
            _is_labor_unit = _unit_lc.isin(_LABOR_UNITS)

            # Default
            ctype_arr = pd.Series(["other"] * len(res_df), index=res_df.index, dtype=object)
            # Material via row_type == Abstract resource
            ctype_arr = ctype_arr.mask(_row_type == "Abstract resource", "material")
            # is_material branch
            ctype_arr = ctype_arr.mask(_is_mat & ~_is_labor_unit, "material")
            ctype_arr = ctype_arr.mask(_is_mat & _is_labor_unit, "labor")
            # is_machine branch (overrides is_material)
            ctype_arr = ctype_arr.mask(_is_mach, "equipment")
            ctype_arr = ctype_arr.mask(_is_mach & (_row_type == "Machinist"), "operator")
            ctype_arr = ctype_arr.mask(_is_mach & (_row_type == "Electricity"), "electricity")
            # Explicit labour flag. Most bases tag the labour line with is_labor
            # rather than putting a labor unit on a material row, so fill any row
            # still left "other" that carries is_labor. Guarded on == "other" so
            # it never overrides a material / equipment / operator classification
            # already set above. Without this, coefficient bases (Vietnam Dinh
            # Muc, Indonesia AHSP) and even the priced bases' plain labour lines
            # fall through unclassified instead of typing as labor.
            _is_labor = (
                res_df.get("is_labor", pd.Series([False] * len(res_df), index=res_df.index)).fillna(False).astype(bool)
            )
            ctype_arr = ctype_arr.mask(_is_labor & (ctype_arr == "other"), "labor")
            res_df["_type"] = ctype_arr

            # Build records via zip over numpy arrays - much faster than iterrows
            rc_arr = res_df["_rc"].to_numpy()
            name_arr = res_df["_name"].to_numpy()
            code_arr = res_df["_code"].to_numpy()
            unit_arr = res_df["_unit"].to_numpy()
            qty_arr = res_df["_qty"].to_numpy()
            rate_arr = res_df["_rate"].to_numpy()
            cost_arr = res_df["_cost_v"].to_numpy()
            type_arr = res_df["_type"].to_numpy()

            # strict=True surfaces array length drift immediately instead of
            # silently truncating component rows mid-import - important for a
            # cost-data pipeline where a missing column would otherwise corrupt
            # the assembly composition without leaving any audit trail.
            for rc, nm, cd, un, qt, rt, cs, tp in zip(
                rc_arr,
                name_arr,
                code_arr,
                unit_arr,
                qty_arr,
                rate_arr,
                cost_arr,
                type_arr,
                strict=True,
            ):
                comps = resources_by_code.get(rc)
                if comps is None:
                    comps = []
                    resources_by_code[rc] = comps
                comp: dict[str, Any] = {
                    "name": nm,
                    "code": cd,
                    "unit": un,
                    "quantity": float(qt),
                    "unit_rate": float(rt),
                    "cost": float(cs),
                    "type": tp,
                }
                # Stamp per-component variant catalog if this resource is one
                # of the abstract-resource (variant) slots for this rate.
                v_data = abstract_variants_by_pair.get((rc, cd))
                if v_data is not None:
                    comp["available_variants"] = v_data["variants"]
                    comp["available_variant_stats"] = v_data["variant_stats"]
                comps.append(comp)

        _log.info("Built resources for %d rate_codes in %.1fs", len(resources_by_code), time.monotonic() - start)

    # Free the raw DataFrame before the INSERT phase - it is no longer
    # needed; only ``grouped``, ``resources_by_code``, ``scope_by_code``
    # and ``abstract_variants_by_pair`` survive past this point.
    del df
    gc.collect()

    # 5. Build the insert rows. ``db_file`` carries the sync SQLAlchemy URL
    # (postgresql://...) of the target cluster - see the caller. Every row is
    # accumulated and handed to ``_pg_bulk_insert_cost_rows`` (COPY into a
    # staging table + ON CONFLICT DO NOTHING) below.

    # CWICR parquet carries no currency column - every rate is denominated in
    # the region's local currency. Resolve it ONCE from ``db_id`` (constant for
    # the whole import) so each row persists its true ISO currency instead of
    # the empty string that read-side fallbacks then had to paper over.
    resolved_currency = _router._resolve_currency(None, db_id)

    skipped_count = 0
    imported = 0
    batch: list[tuple] = []
    # Codes of rows PostgreSQL refused. Kept apart from ``skipped_count``, which
    # counts rows this transform drops on purpose (no description, no code):
    # those are expected on every base, these are a partial load.
    failed_codes: list[str] = []

    for rate_code, row in grouped.iterrows():
        desc = _safe_str(row.get("_desc", ""))
        if len(desc) < 3:
            desc = _safe_str(row.get("subsection_name", ""))
        if len(desc) < 3:
            skipped_count += 1
            continue

        code = _safe_str(rate_code)[:100]
        if not code:
            skipped_count += 1
            continue

        unit = _safe_str(row.get("rate_unit", "m2"))[:20] or "m2"
        rate = round(_safe_float(row.get("total_cost_per_position", 0)), 2)

        classification: dict[str, str] = {}
        for key in ("collection_name", "department_name", "section_name", "subsection_name"):
            val = _safe_str(row.get(key, ""))
            if val:
                classification[key.replace("_name", "")] = val
        cat = _safe_str(row.get("category_type", ""))
        if cat:
            classification["category"] = cat

        metadata: dict[str, Any] = {}
        for mkey, col in [
            ("labor_cost", "cost_of_working_hours"),
            ("equipment_cost", "total_value_machinery_equipment"),
            ("material_cost", "total_material_cost_per_position"),
            ("labor_hours", "total_labor_hours_all_personnel"),
            ("workers_per_unit", "count_total_people_per_unit"),
        ]:
            v = _safe_float(row.get(col, 0))
            if v > 0:
                metadata[mkey] = round(v, 2)

        # ── Scope of work - ordered steps describing HOW the position is
        # performed (e.g. "Установка телескопических стоек."). Sourced from
        # rows flagged ``is_scope=True`` and pre-indexed above.
        steps = scope_by_code.get(code)
        if steps:
            metadata["scope_of_work"] = steps

        labels = _split_bul(row.get("price_abstract_resource_variable_parts"))
        values = _split_bul(row.get("price_abstract_resource_est_price_all_values"))
        pu_vals_raw = _split_bul(row.get("price_abstract_resource_est_price_all_values_per_unit"))
        pu_vals = [_strip_unit_prefix(t) for t in pu_vals_raw]
        # Some rate rows have an empty ``..._all_values`` series and only
        # the per-unit one is populated - fall back so the legacy picker
        # still gets a catalog instead of dropping it on import.
        if labels and len(values) != len(labels) and len(pu_vals) == len(labels):
            values = pu_vals
        # ``common_start`` is the shared base name for the abstract resource
        # (e.g. "Ready-mix concrete"); each ``variable_parts[i]`` is the
        # distinguishing tail (e.g. "C25/30 delivered"). The picker renders
        # ``common_start`` once as a header and the rows show only the
        # variable tails. ``full_label`` = ``common_start + variable_part``
        # is what the BOQ resource row displays after a pick - replacing
        # the position's default description so the user sees the actual
        # concrete material chosen.
        common_start = _safe_str(row.get("price_abstract_resource_common_start"))[:240]
        # position_count is a single per-rate_code total in the parquet, not per-variant.
        total_position_count = int(_safe_float(row.get("price_abstract_resource_position_count")))
        if labels and len(labels) > 1 and len(values) == len(labels):
            variants = []
            for i, (lbl, val) in enumerate(zip(labels, values, strict=False)):
                v = _safe_float(val)
                if v <= 0:
                    continue
                variable_part = lbl[:200]
                full_label = (f"{common_start} {variable_part}".strip() if common_start else variable_part)[:400]
                variants.append(
                    {
                        "index": i,
                        "label": variable_part,
                        "full_label": full_label,
                        "price": round(v, 2),
                        "price_per_unit": round(_safe_float(pu_vals[i]), 4) if i < len(pu_vals) else None,
                    }
                )
            if variants:
                metadata["variants"] = variants
                metadata["variant_stats"] = {
                    "min": round(_safe_float(row.get("price_abstract_resource_est_price_min")), 2),
                    "max": round(_safe_float(row.get("price_abstract_resource_est_price_max")), 2),
                    "mean": round(_safe_float(row.get("price_abstract_resource_est_price_mean")), 2),
                    "median": round(_safe_float(row.get("price_abstract_resource_est_price_median")), 2),
                    "unit": _safe_str(row.get("price_abstract_resource_unit"))[:20],
                    "group": _safe_str(row.get("price_abstract_resource_group_per_unit"))[:120],
                    "count": len(variants),
                    "position_count": total_position_count,
                    "common_start": common_start,
                }

        # Get full resource components for this rate_code
        components = resources_by_code.get(code, [])

        batch.append(
            (
                str(uuid.uuid4()),
                code,
                desc[:500],
                unit,
                str(rate),
                resolved_currency,
                "cwicr",
                _json.dumps(classification),
                "[]",
                _json.dumps(components),
                "{}",
                1,
                db_id,
                _json.dumps(metadata),
            )
        )

        # Hand the rows over in bounded slices instead of building the whole
        # region first. Each flush is its own committed transaction, so peak
        # memory stays flat and a killed import resumes rather than restarts.
        if len(batch) >= _router._INSERT_FLUSH_ROWS:
            imported += _router._insert_cost_rows_isolating_rejects(db_file, batch, failed_codes)
            batch.clear()

    # PostgreSQL: idempotent bulk insert via ON CONFLICT (code, region)
    # DO NOTHING. Whatever the loop did not fill a flush with lands here.
    if batch:
        imported += _router._insert_cost_rows_isolating_rejects(db_file, batch, failed_codes)
        batch.clear()

    elapsed = round(time.monotonic() - start, 1)
    _log.info(
        "CWICR %s: %d imported, %d skipped, %d rejected by the database in %.1fs",
        db_id,
        imported,
        skipped_count,
        len(failed_codes),
        elapsed,
    )

    # Total resource components carried by the imported work items. Each CWICR
    # work item (rate_code) bundles a labour/material/equipment breakdown in its
    # ``components`` array (the parquet is literally
    # ``..._workitems_costs_resources_...``); surfacing the aggregate count lets
    # the partner-pack installer report the embedded resource database it just
    # loaded alongside the work catalog.
    resource_components = sum(len(v) for v in resources_by_code.values())

    return {
        "imported": imported,
        "skipped": skipped_count,
        "failed": len(failed_codes),
        "failed_codes": failed_codes[: _router._FAILED_CODES_REPORTED],
        "total_rows": total_rows,
        "unique_items": len(grouped),
        "resource_components": resource_components,
        "database": db_id,
    }
