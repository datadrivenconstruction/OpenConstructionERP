"""France prices a bill one way, and offers the documents a French unit-price contract uses.

Three French markup stacks used to disagree: the regional table (FC 10, FG 15,
B&A 8), the methodology literal (12 / 7) and the Lyon hospital demo (9 / 12 /
5 plus a separate 6 % contingency). Only the first is the source now.
"""

from __future__ import annotations

import importlib.util
from decimal import Decimal
from pathlib import Path

from app.modules.boq.exchange_formats import EXCHANGE_FORMATS, default_format_for_country, formats_for_country
from app.modules.boq.markup_templates import region_lines_for_country
from app.modules.methodology.templates import TEMPLATES_BY_SLUG

_LYON = Path(__file__).resolve().parents[2] / "app" / "core" / "demo_packs" / "hospital-lyon.py"


def _lyon_template():
    spec = importlib.util.spec_from_file_location("hospital_lyon_demo", _LYON)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.TEMPLATE


def _table() -> list[tuple[str, Decimal, str, str]]:
    lines = region_lines_for_country("FR")
    assert lines
    return [(str(x["name"]), Decimal(str(x["percentage"])), str(x["category"]), str(x["apply_to"])) for x in lines]


def test_the_lyon_demo_is_priced_on_the_national_stack() -> None:
    demo = [(n, Decimal(str(p)), c, a) for n, p, c, a in _lyon_template().markups]
    assert demo == _table()


def test_the_french_stack_carries_no_contingency_on_top_of_benefice_et_aleas() -> None:
    assert "contingency" not in {category for _n, _p, category, _a in _table()}


def test_the_methodology_template_is_the_same_stack() -> None:
    france = TEMPLATES_BY_SLUG["france"]
    assert france["derived_from_region"] == "FR"
    rates = [(s["label"], Decimal(s["rate"])) for s in france["cascade_steps"]]
    assert rates == [(name, pct) for name, pct, _c, _a in _table()]


def test_bpu_and_dqe_are_offered_to_a_french_user_after_the_dpgf() -> None:
    ids = [fmt.format_id for fmt in formats_for_country("FR")]
    assert {"fr_dpgf", "fr_bpu", "fr_dqe"} <= set(ids)
    assert ids.index("fr_dpgf") < ids.index("fr_bpu") < ids.index("fr_dqe")
    assert default_format_for_country("FR") == "fr_dpgf"


def test_the_unit_price_documents_are_read_and_written_as_french_workbooks() -> None:
    rows = {fmt.format_id: fmt for fmt in EXCHANGE_FORMATS}
    for code in ("fr_bpu", "fr_dqe"):
        assert rows[code].reader == "excel"
        assert rows[code].writer == "excel"
        assert rows[code].header_language == "fr"
