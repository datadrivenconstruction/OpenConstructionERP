"""Layout generator eval harness — measures pass@k for the ACAP generator.

Runs the real LLM pipeline against a fixed set of fixtures and reports
how many fixtures produce a valid floor-plan within N passes.

Usage:
    python -m app.modules.acap.layout.eval
"""

from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger(__name__)

# ── Eval fixtures ────────────────────────────────────────────────────────────

FIXTURES: list[dict] = [
    {
        "name": "rumah_minimalis_1lt_36",
        "requirement_text": "Rumah minimalis type 36: ruang tamu, 2 kamar tidur (1 utama), 1 kamar mandi, dapur, ruang keluarga, carport untuk 1 mobil.",
        "kavling_width_m": 6.0,
        "kavling_length_m": 12.0,
        "jumlah_lantai": 1,
        "expect_room_types": [
            "ruang_tamu", "kamar_tidur_utama", "kamar_tidur", "kamar_mandi",
            "dapur", "ruang_keluarga", "carport",
        ],
    },
    {
        "name": "rumah_minimalis_1lt_45",
        "requirement_text": "Rumah minimalis type 45: ruang tamu, ruang keluarga, 2 kamar tidur (1 utama), 1 kamar mandi, dapur, ruang makan, carport.",
        "kavling_width_m": 6.0,
        "kavling_length_m": 15.0,
        "jumlah_lantai": 1,
        "expect_room_types": [
            "ruang_tamu", "ruang_keluarga", "kamar_tidur_utama", "kamar_tidur",
            "kamar_mandi", "dapur", "ruang_makan", "carport",
        ],
    },
    {
        "name": "rumah_2lt_keluarga",
        "requirement_text": "Rumah 2 lantai untuk keluarga: lantai 1 ruang tamu, ruang keluarga, dapur, ruang makan, kamar mandi, carport; lantai 2 3 kamar tidur (1 utama), 2 kamar mandi, ruang keluarga kecil.",
        "kavling_width_m": 8.0,
        "kavling_length_m": 15.0,
        "jumlah_lantai": 2,
        "expect_room_types": [
            "ruang_tamu", "ruang_keluarga", "dapur", "ruang_makan", "kamar_mandi",
            "carport", "kamar_tidur_utama", "kamar_tidur", "sirkulasi",
        ],
    },
    {
        "name": "rumah_murah_batam_1lt",
        "requirement_text": "Rumah subsidi Batam: ruang tamu minimal, 2 kamar tidur, 1 kamar mandi, dapur kecil, teras depan. Budget rendah, efisien.",
        "kavling_width_m": 6.0,
        "kavling_length_m": 10.0,
        "jumlah_lantai": 1,
        "expect_room_types": [
            "ruang_tamu", "kamar_tidur", "kamar_mandi", "dapur", "teras",
        ],
    },
    {
        "name": "rumah_ali_2lantai_renovasi",
        "requirement_text": "Rumah renovasi 2 lantai di Batam: lantai 1 ruang tamu, dapur, ruang makan, kamar mandi, gudang kecil, carport; lantai 2 2 kamar tidur (1 utama dengan kamar mandi dalam), ruang keluarga, teras balkon. Aksen tropis.",
        "kavling_width_m": 8.0,
        "kavling_length_m": 15.0,
        "jumlah_lantai": 2,
        "expect_room_types": [
            "ruang_tamu", "dapur", "ruang_makan", "kamar_mandi",
            "gudang", "carport", "kamar_tidur_utama", "kamar_tidur",
            "ruang_keluarga", "teras", "sirkulasi",
        ],
    },
    {
        "name": "rumah_kost_4_kamar",
        "requirement_text": "Rumah kost 4 kamar tidur, 2 kamar mandi (shared), dapur bersama, ruang tamu kecil. 1 lantai.",
        "kavling_width_m": 8.0,
        "kavling_length_m": 14.0,
        "jumlah_lantai": 1,
        "expect_room_types": [
            "kamar_tidur", "kamar_mandi", "dapur", "ruang_tamu", "sirkulasi",
        ],
    },
    {
        "name": "rumah_tropis_modern_2lt",
        "requirement_text": "Rumah tropis modern 2 lantai: ruang tamu, ruang keluarga, dapur terbuka, ruang makan, 3 kamar tidur, 3 kamar mandi, carport 2 mobil, taman kecil, musholla. Ada void/plafon tinggi di ruang keluarga.",
        "kavling_width_m": 10.0,
        "kavling_length_m": 16.0,
        "jumlah_lantai": 2,
        "expect_room_types": [
            "ruang_tamu", "ruang_keluarga", "dapur", "ruang_makan",
            "kamar_tidur_utama", "kamar_tidur", "kamar_mandi",
            "carport", "taman", "musholla", "sirkulasi",
        ],
    },
    {
        "name": "rumah_kecil_1lt_sempit",
        "requirement_text": "Rumah kecil di lahan sempit: 1 kamar tidur, 1 kamar mandi, dapur, ruang tamu merangkap ruang keluarga. Sangat compact.",
        "kavling_width_m": 4.5,
        "kavling_length_m": 10.0,
        "jumlah_lantai": 1,
        "expect_room_types": [
            "kamar_tidur", "kamar_mandi", "dapur", "ruang_tamu",
        ],
    },
    {
        "name": "rumah_mewah_modern_1lt",
        "requirement_text": "Rumah mewah 1 lantai: ruang tamu besar, ruang keluarga, ruang makan formal, dapur modern, 2 kamar tidur utama (masing-masing dengan kamar mandi dalam), 1 kamar tidur tamu, 1 kamar mandi tamu, carport 2 mobil, teras belakang, taman, musholla.",
        "kavling_width_m": 12.0,
        "kavling_length_m": 20.0,
        "jumlah_lantai": 1,
        "expect_room_types": [
            "ruang_tamu", "ruang_keluarga", "ruang_makan", "dapur",
            "kamar_tidur_utama", "kamar_tidur", "kamar_mandi",
            "carport", "teras", "taman", "musholla",
        ],
    },
    {
        "name": "rumah_garasi_workshop",
        "requirement_text": "Rumah dengan garasi besar + workshop: ruang tamu, 2 kamar tidur, 1 kamar mandi, dapur, garasi untuk 2 mobil plus ruang kerja/workshop, gudang.",
        "kavling_width_m": 8.0,
        "kavling_length_m": 18.0,
        "jumlah_lantai": 1,
        "expect_room_types": [
            "ruang_tamu", "kamar_tidur", "kamar_mandi", "dapur",
            "garasi", "gudang",
        ],
    },
]


# ── Eval runner ──────────────────────────────────────────────────────────────


async def run_eval(session, passes: int = 3) -> dict:
    """Run every fixture up to *passes* times.  A fixture PASSES if any
    attempt yields a valid plan containing all ``expect_room_types`` and
    (when provided) total room area within ±10% of ``expect_total_area_m2``.
    """
    from app.modules.acap.layout.generator import LayoutGenerationError, generate_layout
    from app.modules.acap.layout.validator import is_valid

    passed = 0
    details: list[dict] = []

    for fixture in FIXTURES:
        name = fixture["name"]
        expect_types = set(fixture["expect_room_types"])
        expect_area = fixture.get("expect_total_area_m2")
        fixture_ok = False
        best_valid = False

        for p in range(1, passes + 1):
            try:
                plan = await generate_layout(
                    session=session,
                    requirement_text=fixture["requirement_text"],
                    kavling_width_m=fixture["kavling_width_m"],
                    kavling_length_m=fixture["kavling_length_m"],
                    jumlah_lantai=fixture["jumlah_lantai"],
                    max_retries=1,  # one LLM call per pass (retries handled by eval loop)
                )
            except LayoutGenerationError as exc:
                details.append({
                    "name": name,
                    "pass": p,
                    "ok": False,
                    "valid": False,
                    "reasons": exc.reasons,
                })
                continue
            except Exception as exc:
                details.append({
                    "name": name,
                    "pass": p,
                    "ok": False,
                    "valid": False,
                    "reasons": [str(exc)],
                })
                continue

            valid, reasons = is_valid(plan)
            if not valid:
                details.append({
                    "name": name,
                    "pass": p,
                    "ok": False,
                    "valid": False,
                    "reasons": reasons,
                })
                continue

            # Check expected room types
            plan_types = {r.type for level in plan.levels for r in level.rooms}
            type_ok = expect_types.issubset(plan_types)

            # Check total area (if provided)
            area_ok = True
            if expect_area is not None:
                total = sum(
                    r.area_m2 for level in plan.levels for r in level.rooms
                )
                area_ok = abs(total - expect_area) / expect_area <= 0.10

            fixture_ok = type_ok and area_ok
            details.append({
                "name": name,
                "pass": p,
                "ok": fixture_ok,
                "valid": True,
                "reasons": [],
            })

            if fixture_ok:
                if valid:
                    best_valid = True
                break

        if fixture_ok:
            passed += 1
        else:
            details.append({
                "name": name,
                "pass": passes,
                "ok": False,
                "valid": best_valid,
                "reasons": [f"Not all fixtures passed (type_ok, area_ok) after {passes} passes"],
            })

    total = len(FIXTURES)
    pass_at_3 = passed / total if total > 0 else 0.0

    return {
        "total": total,
        "passed": passed,
        "pass_at_3": pass_at_3,
        "details": details,
    }


async def _main() -> None:
    from app.database import async_session_factory

    async with async_session_factory() as session:
        result = await run_eval(session)
        print(f"Pass@3: {result['passed']}/{result['total']} = {result['pass_at_3']:.0%}")
        print()
        for d in result["details"]:
            status = "PASS" if d["ok"] else "FAIL"
            print(f"  [{d['name']}] pass={d['pass']} {status}")
            if d.get("reasons"):
                for r in d["reasons"]:
                    print(f"    - {r}")


if __name__ == "__main__":
    asyncio.run(_main())
