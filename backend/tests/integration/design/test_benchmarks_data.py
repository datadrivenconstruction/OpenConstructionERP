import json
import re
from pathlib import Path

# In this repo the package sits beside tests/; in the ERP overlay it is app/modules/design.
_HERE = Path(__file__).resolve()
DATA = next(
    p / "data" / "benchmarks"
    for p in (_HERE.parents[1] / "design", *(q / "app" / "modules" / "design" for q in _HERE.parents))
    if (p / "data" / "benchmarks").is_dir()
)
UNITS = {"BGF": "EUR/m2", "BRI": "EUR/m3", "WFL": "EUR/m2"}
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _files():
    files = sorted(DATA.glob("*.json"))
    assert files
    return files


def test_rows_have_source_and_date():
    for f in _files():
        doc = json.loads(f.read_text(encoding="utf-8"))
        assert doc["schema"] == "ddc-benchmarks/1"
        assert doc["rows"]
        for r in doc["rows"]:
            assert r["source_url"].startswith("https://"), r
            assert DATE.match(r["published"]), r
            assert DATE.match(r["accessed"]), r
            assert r["quote"].strip(), r
            assert r["publisher"].strip(), r
            assert any(r[k] is not None for k in ("low", "mid", "high")), r


def test_ordering_and_units():
    for f in _files():
        for r in json.loads(f.read_text(encoding="utf-8"))["rows"]:
            assert r["basis"] in UNITS, r
            assert r["unit"] == UNITS[r["basis"]], r
            vals = [r[k] for k in ("low", "mid", "high") if r[k] is not None]
            assert vals == sorted(vals), r


def test_derived_rows_document_formula():
    for f in _files():
        for r in json.loads(f.read_text(encoding="utf-8"))["rows"]:
            if r.get("derived"):
                assert r["derivation"].strip() and r["index_source_url"].startswith("https://"), r


def test_dates_without_a_release_statement_say_where_they_come_from():
    rows = [r for f in _files() for r in json.loads(f.read_text(encoding="utf-8"))["rows"]]
    for r in rows:
        if r["publisher"].startswith("Statistisches Bundesamt"):
            assert r["published"] != "2022-07-25" and r["published_basis"], r  # that date is not traceable


def test_unpriced_model_positions_are_documented():
    """The DE example stays unpriced (inside_range null) until an open unit rate exists; each position says so here."""
    doc = next(
        json.loads(f.read_text(encoding="utf-8"))
        for f in _files()
        if json.loads(f.read_text(encoding="utf-8"))["country"] == "DE"
    )
    listed = {u["cost_group"] for u in doc["unsourced"] if u.get("positions")}
    assert {"320", "330", "334", "340", "344", "350", "360", "400"} <= listed
    for r in doc["rows"]:
        if r["basis"] == "BGF":  # NHK 2010 row: unindexed, so it must not pose as a current price
            assert r["price_level_year"] == 2010 and not r.get("derived")
