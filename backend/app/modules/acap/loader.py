"""Pure-YAML AHSP coefficient loader.

Reads the structured ``data/ahsp/*.yaml`` files and returns a flat list of dicts —
one per AHSP item — with file-level metadata propagated onto every item.

Intentionally NO imports from ``app.*`` (no database, no ORM) so the loader is
testable in isolation with only stdlib and ``pyyaml``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

DEFAULT_DATA_DIR = Path(__file__).parent / "data" / "ahsp"


def load_ahsp_dir(path: str | Path) -> list[dict[str, Any]]:
    """Load every ``*.yaml`` in *path*, flatten items, and return them.

    Each file must have top-level keys ``kategori``, ``referensi``, ``sumber``,
    and an ``items`` list.  The file-level ``kategori``, ``referensi`` and
    ``sumber`` are propagated onto every item dict.

    Returns a list of dicts, each shaped::

        {
            "kode": ...,
            "uraian": ...,
            "satuan": ...,
            "kategori": ...,
            "referensi": ...,
            "referensi_kode": ... | None,
            "sumber": ...,
            "bahan":  [{"nama", "satuan", "koef"}, ...],
            "tenaga": [{"jabatan", "koef_oh"}, ...],
            "alat":   [...],
        }

    Raises:
        FileNotFoundError: *path* does not exist.
        ValueError: duplicate ``kode`` across the whole directory.
    """
    data_dir = Path(path)
    if not data_dir.is_dir():
        raise FileNotFoundError(f"AHSP data directory not found: {data_dir}")

    items: list[dict[str, Any]] = []
    seen: set[str] = set()

    for yaml_file in sorted(data_dir.glob("*.yaml")):
        with yaml_file.open("r", encoding="utf-8") as fh:
            doc = yaml.safe_load(fh)

        if not isinstance(doc, dict):
            continue

        kategori: str = doc.get("kategori", "")
        referensi: str = doc.get("referensi", "")
        sumber: str = doc.get("sumber", "")

        for item in doc.get("items", []):
            kode: str = item["kode"]
            if kode in seen:
                raise ValueError(f"Duplicate AHSP kode: {kode}")
            seen.add(kode)

            items.append(
                {
                    "kode": kode,
                    "uraian": item["uraian"],
                    "satuan": item["satuan"],
                    "kategori": kategori,
                    "referensi": referensi,
                    "referensi_kode": item.get("referensi_kode"),
                    "sumber": sumber,
                    "bahan": item.get("bahan", []),
                    "tenaga": item.get("tenaga", []),
                    "alat": item.get("alat", []),
                }
            )

    return items


# ── Self-check (runs with only pyyaml) ────────────────────────────────────
if __name__ == "__main__":
    data = load_ahsp_dir(DEFAULT_DATA_DIR)

    assert len(data) >= 26, f"Expected ≥26 items, got {len(data)}"

    # No duplicate kode (already enforced by load, but double-check)
    codes = [d["kode"] for d in data]
    assert len(codes) == len(set(codes)), "Duplicate kode detected"

    # Spot-assert K175
    k175 = next(d for d in data if d["kode"] == "ACAP.BETON.K175")
    tenaga_pekerja = next(t for t in k175["tenaga"] if t["jabatan"] == "pekerja")
    assert tenaga_pekerja["koef_oh"] == 1.65, f"K175 pekerja koef_oh expected 1.65, got {tenaga_pekerja['koef_oh']}"
    bahan_semen = next(b for b in k175["bahan"] if "Semen" in b["nama"])
    assert bahan_semen["koef"] == 326.0, f"K175 semen koef expected 326.0, got {bahan_semen['koef']}"

    print(f"loader self-check OK: {len(data)} items")
