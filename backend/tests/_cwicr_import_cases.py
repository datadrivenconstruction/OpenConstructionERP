"""A CWICR parquet built to break a cost import that reads the file in batches.

A work item (rate code) spans several parquet rows, and the import builds one
cost row per item from all of them: the first non-empty value of each column,
every resource, every scope step, the variant catalogue of an abstract resource.
Read whole, every row of an item is in the one frame. Read in batches, an item
whose rows sit in two batches is where a streaming loader can go wrong, so this
file is made of such items, together with the shapes the real bases carry:

* ``A`` comes back twice after other items, and its second visit brings the
  only ``category_type`` it has and an abstract resource with three variants.
* ``B`` comes back some forty rows later with its category, so everything after
  its first visit is held behind it until then.
* ``G`` opens late and comes back as the last row of the file, so the items
  after it can only be released at the end.
* ``C`` is one item spread over fifteen rows.
* rows without a rate code carry resources and are counted, never stored.
* `` D `` and ``D`` are two items that strip to the same code, so the scope
  steps of one are matched to the other.
* two codes over 100 characters truncate to the same stored code.
* ``H`` and `` H`` also store as one code, but ``K`` opens between them and
  closes after them, so the order the rows are handed over in depends on
  releasing them by the first row of each raw code, not of the stored one.
* ``E`` has no usable description and is skipped; ``N`` has a NUL character,
  which PostgreSQL refuses.
* ``resource_code`` is an integer column with missing values, but none among
  the first twenty fillers, so a batch of those alone would read it as integers
  where the whole file reads it as floats.
* the ``F`` items pad the file so it spans many batches and several flushes.

The file is written with pyarrow and carries no pandas metadata, like the
smallest of the real national bases.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

COLUMNS: dict[str, str] = {
    "rate_code": "string",
    "rate_original_name": "string",
    "rate_final_name": "string",
    "rate_unit": "string",
    "total_cost_per_position": "float",
    "collection_name": "string",
    "section_name": "string",
    "subsection_name": "string",
    "category_type": "string",
    "cost_of_working_hours": "float",
    "price_abstract_resource_position_count": "int",
    "resource_name": "string",
    "resource_code": "int",
    "resource_unit": "string",
    "resource_quantity": "float",
    "resource_price_per_unit_current": "float",
    "resource_cost": "float",
    "row_type": "string",
    "is_machine": "bool",
    "is_material": "bool",
    "is_labor": "bool",
    "work_composition_text": "string",
    "price_abstract_resource_variable_parts": "string",
    "price_abstract_resource_est_price_all_values": "string",
    "price_abstract_resource_est_price_all_values_per_unit": "string",
    "price_abstract_resource_common_start": "string",
    "price_abstract_resource_est_price_min": "float",
    "price_abstract_resource_est_price_max": "float",
    "price_abstract_resource_est_price_mean": "float",
    "price_abstract_resource_est_price_median": "float",
    "price_abstract_resource_unit": "string",
    "price_abstract_resource_group_per_unit": "string",
}

LONG_A = "L" * 100 + "-first"
LONG_B = "L" * 100 + "-second"


def _row(code: str | None, **values: Any) -> dict[str, Any]:
    row: dict[str, Any] = dict.fromkeys(COLUMNS)
    row["rate_code"] = code
    row.update(values)
    return row


def _head(code: str | None, name: str, *, cost: float = 100.0, unit: str | None = "m3", **extra: Any) -> dict[str, Any]:
    return _row(
        code,
        rate_original_name=name,
        rate_final_name=name + " variant",
        rate_unit=unit,
        total_cost_per_position=cost,
        collection_name="Works",
        section_name="Concrete",
        subsection_name="Walls",
        cost_of_working_hours=cost / 4,
        **extra,
    )


def _resource(code: str | None, name: str, resource_code: int | None, *, cost: float = 10.0, **extra: Any) -> dict:
    values: dict[str, Any] = {
        "resource_name": name,
        "resource_code": resource_code,
        "resource_unit": "hrs",
        "resource_quantity": 1.5,
        "resource_price_per_unit_current": cost / 1.5,
        "resource_cost": cost,
        "row_type": "Labour",
        "is_labor": True,
        "is_material": False,
        "is_machine": False,
    }
    values.update(extra)
    return _row(code, **values)


def _scope(code: str | None, text: str) -> dict[str, Any]:
    return _row(code, work_composition_text=text, row_type="Scope of work")


def hard_case_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = [
        # A, first visit: no unit on its first row, no category anywhere yet.
        _head("A", "Cast wall", unit=None),
        _row("A", rate_unit="m3"),
        _resource("A", "Carpenter", 1),
        _scope("A", "Set up formwork."),
        # B, first visit.
        _head("B", "Lay bricks", cost=55.5),
        _resource("B", "Bricklayer", 2, cost=20.0),
        _resource("B", "Bricks", 3, cost=30.0, row_type="Material", is_labor=None, is_material=True),
        # A, second visit: the category and an abstract resource with variants.
        _row("A", category_type="Structural"),
        _resource(
            "A",
            "Concrete",
            7,
            cost=0.0,
            resource_quantity=0.0,
            row_type="Abstract resource",
            is_labor=False,
            is_material=True,
            price_abstract_resource_variable_parts="C20/25 • C25/30 • C30/37",
            price_abstract_resource_est_price_all_values="100 • 110 • 0",
            price_abstract_resource_est_price_all_values_per_unit="m3=10.5 • 11 • 12",
            price_abstract_resource_common_start="Ready-mix concrete",
            price_abstract_resource_position_count=3,
            price_abstract_resource_est_price_min=100.0,
            price_abstract_resource_est_price_max=110.0,
            price_abstract_resource_est_price_mean=105.0,
            price_abstract_resource_est_price_median=105.0,
            price_abstract_resource_unit="m3",
            price_abstract_resource_group_per_unit="Concrete",
        ),
        _scope("A", "Pour and vibrate."),
    ]
    # C: one item over fifteen rows, the labour flag missing on some.
    rows.append(_head("C", "Excavate trench", cost=12.0))
    for index in range(14):
        rows.append(
            _resource("C", f"Machine {index}", 100 + index, cost=1.0 + index, is_labor=None if index % 3 else True)
        )
    # Rows with no rate code: counted as resources, never stored.
    rows.append(_resource(None, "Orphan labour", 900))
    rows.append(_resource(None, "Orphan plant", 901, is_machine=True))
    # " D " and "D" strip to the same stored code.
    rows += [
        _head(" D ", "Spaced item"),
        _scope(" D ", "Spaced step."),
        _resource(" D ", "Spaced labour", 11),
        _head("D", "Plain item"),
        _resource("D", "Plain labour", 12),
        _scope("D", "Plain step."),
    ]
    # Two codes over 100 characters that truncate to the same stored code.
    rows += [
        _head(LONG_A, "Long code one"),
        _resource(LONG_A, "Long labour one", 13),
        _head(LONG_B, "Long code two"),
        _resource(LONG_B, "Long labour two", 14),
    ]
    # B, last visit, some forty rows after its first.
    rows.append(_resource("B", "Mortar", 4, cost=5.5, row_type="Material", is_material=True, is_labor=False))
    rows.append(_row("B", category_type="Masonry"))
    # E: nothing to describe it, so it is skipped. N: a NUL in its name.
    rows += [
        _row("E", rate_unit="pcs"),
        _resource("E", "Unused", 15),
        _head("N", "Bad\x00name"),
        _resource("N", "Bad labour", 16),
    ]
    # "H" and " H" store as the same code, and K opens between them and is
    # still open when " H" arrives. The whole frame hands over H, K, H in the
    # order the three raw codes first appear, so a loader that releases H and
    # " H" together, ahead of K, changes which rows share a flush. It sits
    # where no earlier item is still open, since an open item would hold all
    # three back and release them together, in the right order by accident.
    rows += [
        _head("H", "Interleaved first"),
        _head("K", "Interleaved between"),
        _head(" H", "Interleaved second"),
        _resource("K", "Between labour", 18),
    ]
    # Padding, with the only missing resource codes late in the file. G opens
    # among them and closes the file, so everything after it waits for the end.
    # Each filler is one row that carries both the item and its resource, as
    # the real bases repeat the item's columns on every row, so the first
    # twenty make batches with no missing resource code at all.
    for index in range(30):
        code = f"F{index:02d}"
        rows.append(
            _resource(
                code,
                f"Filler labour {index}",
                None if index >= 20 and index % 2 else 200 + index,
                rate_original_name=f"Filler item {index}",
                rate_final_name=f"Filler item {index}",
                rate_unit="m2",
                total_cost_per_position=float(index),
            )
        )
        if index >= 20 and index % 4 == 0:
            rows.append(_scope(code, f"Filler step {index}."))
        if index == 24:
            rows.append(_head("G", "Late item"))
    rows.append(_resource("G", "Late labour", 17))
    return rows


def write_hard_case_parquet(path: Path, rows: list[dict[str, Any]] | None = None) -> int:
    """Write the hard-case parquet with pyarrow; returns its row count."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    rows = hard_case_rows() if rows is None else rows
    types = {"string": pa.string(), "float": pa.float64(), "int": pa.int64(), "bool": pa.bool_()}
    table = pa.table({name: pa.array([r[name] for r in rows], type=types[kind]) for name, kind in COLUMNS.items()})
    pq.write_table(table, path)
    return len(rows)


def write_synthetic_parquet(path: Path, items: int, rows_per_item: int = 6) -> None:
    """A plain base of ``items`` work items, each a head row plus resources."""
    rows: list[dict[str, Any]] = []
    for index in range(items):
        code = f"S{index:06d}"
        rows.append(_head(code, f"Synthetic work item number {index}", cost=float(index % 97)))
        for part in range(rows_per_item - 1):
            rows.append(_resource(code, f"Synthetic resource {part} of {index}", 1000 + part, cost=1.0 + part))
    write_hard_case_parquet(path, rows)


def write_orphan_scattered_parquet(path: Path, items: int, every: int, *, literal_none_at: int | None = None) -> int:
    """A plain base with a resource row without a rate code after every ``every`` items.

    Rows without a code belong to no work item, so nothing needs them grouped
    with anything. With ``literal_none_at`` the item at that index is coded with
    the word ``None``, which is what such a row's missing code turns into when
    the transform stringifies it, so that item does collect their resources.
    Returns the row count.
    """
    rows: list[dict[str, Any]] = []
    for index in range(items):
        code = "None" if index == literal_none_at else f"S{index:06d}"
        rows.append(_head(code, f"Plain work item number {index}", cost=float(index % 89)))
        rows.append(_resource(code, f"Plain resource of {index}", 1000 + index % 7))
        if index % every == 0:
            rows.append(_resource(None, f"Orphan resource {index}", 900 + index % 5))
    return write_hard_case_parquet(path, rows)
