"""QA: R7 data honesty. Derived rows are recomputed from their parent row and the cited index."""

import json
import re
from pathlib import Path

_HERE = Path(__file__).resolve()
_FILE = next(
    p / "data/benchmarks/de_residential_multi.json"
    for p in (_HERE.parents[1] / "design", *(q / "app/modules/design" for q in _HERE.parents))
    if (p / "data/benchmarks/de_residential_multi.json").is_file()
)
DOC = json.loads(_FILE.read_text(encoding="utf-8"))
ROWS = [r for r in DOC["rows"] if "cost_group" in r and "basis" in r]


def test_derived_rows_recompute_from_parent():
    derived = [r for r in ROWS if r.get("derived")]
    assert derived
    for r in derived:
        f = re.search(r"x \* ([\d.]+) / ([\d.]+) = x \* ([\d.]+)", r["derivation"])
        num, den, fac = (float(x) for x in f.groups())
        assert abs(num / den - fac) < 5e-4, r["derivation"]
        parents = [
            p
            for p in ROWS
            if not p.get("derived")
            and p["source_url"] == r["source_url"]
            and p["cost_group"] == r["cost_group"]
            and p["basis"] == r["basis"]
            and r["quote"].startswith(p["quote"])
        ]
        assert len(parents) == 1, r["covers"]
        for k in ("low", "mid", "high"):
            want = parents[0][k]
            assert (r[k] is None) == (want is None)
            if want is not None:
                assert abs(r[k] - want * num / den) <= 0.5, (k, r[k], want * num / den)


def test_inferred_vat_basis_is_not_asserted_as_fact():
    for r in ROWS:
        if r.get("vat_basis_inferred"):
            assert r["vat_included"] is None, r["covers"]
