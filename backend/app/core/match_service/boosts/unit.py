# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""‌⁠‍Unit boost — rewards unit alignment, penalises type-mismatches.

CWICR position units stay in canonical short codes: ``m``, ``m2`` /
``m²``, ``m3`` / ``m³``, ``kg``, ``pcs``, ``lsum``. Element envelopes
either provide an explicit ``unit_hint`` or carry quantities the
matcher can use to infer one.

The penalty on type-mismatch (e.g. envelope is m³, candidate is m²) is
deliberately larger than the reward on match — a wrong unit means the
unit_rate is meaningless even if the description aligns, so we'd
rather drop the candidate than promote it.
"""

from __future__ import annotations

from typing import Any

from app.core.match_service.config import BOOST_WEIGHTS
from app.core.match_service.envelope import ElementEnvelope, MatchCandidate

# Canonical unit codes the matcher understands.
_VALID_UNITS = {"m", "m2", "m3", "kg", "pcs", "lsum", "lm", "h", "t"}

# Mapping ``quantities`` keys to the inferred unit. We hit this when no
# explicit ``unit_hint`` was supplied — helpful for BIM elements where
# the canonical-format geometry block already implies the unit.
_QUANTITY_TO_UNIT: dict[str, str] = {
    "length_m": "m",
    "perimeter_m": "m",
    "area_m2": "m2",
    "volume_m3": "m3",
    "mass_kg": "kg",
    "weight_kg": "kg",
    "count": "pcs",
    "quantity": "pcs",
}

# Units that disagree on dimensionality — m vs m2 vs m3. A wall extracted
# as area_m2 must NEVER be matched to an m3 cost item; the price would
# be off by a factor of thickness.
_DIMENSION_GROUP: dict[str, str] = {
    "m": "length",
    "lm": "length",
    "m2": "area",
    "m3": "volume",
    "kg": "mass",
    "t": "mass",
    "pcs": "count",
    "lsum": "lsum",
    "h": "time",
}

# Locale-specific unit spellings. CWICR rows in non-Latin catalogues store
# the unit in the catalogue's native script — Chinese 立方米, Japanese 立方メートル,
# Russian шт, Polish szt, Turkish adet etc. Without folding these into the
# canonical short codes the unit_match boost can't fire and a perfectly-
# aligned wall (envelope m3 vs candidate 立方米) silently loses the signal.
#
# Kept lowercase keys; the lookup goes after .strip().lower(). Latin-script
# spellings are added too because some catalogues mix locale labels with
# English in the same column ("cubic meter" / "metro cúbico" / "metro cubo").
_LOCALE_UNIT_ALIASES: dict[str, str] = {
    # ── Chinese (Simplified + Traditional) ──────────────────────────
    "立方米": "m3",
    "立方公尺": "m3",  # zh-CN / zh-TW cubic metre
    "平方米": "m2",
    "平方公尺": "m2",  # zh-CN / zh-TW square metre
    "米": "m",
    "公尺": "m",  # zh-CN / zh-TW metre
    "千克": "kg",
    "公斤": "kg",  # zh-CN / zh-TW kilogram
    "吨": "t",
    "公噸": "t",  # zh-CN / zh-TW tonne
    "件": "pcs",
    "个": "pcs",
    "個": "pcs",
    "套": "pcs",  # set — bucket as pcs (no separate set canon)
    "小时": "h",
    "小時": "h",
    # ── Japanese ─────────────────────────────────────────────────────
    "立方メートル": "m3",
    "立米": "m3",
    "平方メートル": "m2",
    "平米": "m2",
    "メートル": "m",
    "キログラム": "kg",
    "キロ": "kg",
    "トン": "t",
    "本": "pcs",
    "枚": "pcs",  # 個 covered in Chinese block above
    "セット": "pcs",
    "式": "lsum",
    "時間": "h",
    # ── Korean ───────────────────────────────────────────────────────
    "입방미터": "m3",
    "세제곱미터": "m3",
    "제곱미터": "m2",
    "평방미터": "m2",
    "미터": "m",
    "킬로그램": "kg",
    "톤": "t",
    "개": "pcs",  # English "ea" handled in English variants block below
    "세트": "pcs",
    "시간": "h",
    # ── Russian / Cyrillic ───────────────────────────────────────────
    "м": "m",
    "м2": "m2",
    "м²": "m2",
    "кв.м": "m2",
    "кв м": "m2",
    "м3": "m3",
    "м³": "m3",
    "куб.м": "m3",
    "куб м": "m3",
    "кг": "kg",
    "т": "t",
    "тн": "t",
    "шт": "pcs",
    "шт.": "pcs",
    "штук": "pcs",
    "комп": "pcs",
    "компл": "pcs",
    "комплект": "pcs",
    "ч": "h",
    "час": "h",
    # ── Polish ───────────────────────────────────────────────────────
    "szt": "pcs",
    "szt.": "pcs",
    "sztuka": "pcs",
    "kpl": "pcs",
    "kpl.": "pcs",
    "komplet": "pcs",
    "godz": "h",
    "godz.": "h",
    "godzina": "h",
    "tona": "t",
    # ── Turkish ──────────────────────────────────────────────────────
    "adet": "pcs",
    "takım": "pcs",
    "takim": "pcs",
    "saat": "h",
    "ton": "t",
    # ── Spanish / Portuguese ────────────────────────────────────────
    "ud": "pcs",
    "ud.": "pcs",
    "uds": "pcs",
    "unidad": "pcs",
    "un": "pcs",
    "un.": "pcs",
    "unidade": "pcs",
    "ml": "m",  # metro lineal — Spanish / metro linear — Portuguese
    "metro lineal": "m",
    "metro linear": "m",
    "metro cúbico": "m3",
    "metro cubico": "m3",
    "metro cuadrado": "m2",
    "metro quadrado": "m2",
    "tonelada": "t",
    "hora": "h",
    # ── French / Italian / German extras ─────────────────────────────
    "stk": "pcs",
    "stck": "pcs",
    "stück": "pcs",
    "stunde": "h",
    "stunden": "h",
    "std": "h",
    "tonne": "t",
    "tonnes": "t",
    "tonnen": "t",
    "unité": "pcs",
    "unite": "pcs",
    "pce": "pcs",
    "pièce": "pcs",
    "heure": "h",
    "heures": "h",
    "ora": "h",
    "ore": "h",
    "pezzo": "pcs",
    "pezzi": "pcs",
    # ── Arabic / Hindi (transliteration tolerant) ───────────────────
    "متر": "m",
    "متر مربع": "m2",
    "م2": "m2",
    "متر مكعب": "m3",
    "م3": "m3",
    "كيلوغرام": "kg",
    "كغ": "kg",
    "طن": "t",
    "قطعة": "pcs",
    "وحدة": "pcs",
    "ساعة": "h",
    "मीटर": "m",
    "वर्ग मीटर": "m2",
    "घन मीटर": "m3",
    "किलोग्राम": "kg",
    "किलो": "kg",
    "टन": "t",
    "पीस": "pcs",
    "नग": "pcs",
    "घंटा": "h",
    # ── Vietnamese ───────────────────────────────────────────────────
    "mét": "m",
    "mét vuông": "m2",
    "mét khối": "m3",
    "khối": "m3",
    "ki-lô-gam": "kg",
    "ki lô gam": "kg",
    "tấn": "t",
    "cái": "pcs",
    "chiếc": "pcs",
    "giờ": "h",
    # ── Thai ─────────────────────────────────────────────────────────
    "เมตร": "m",
    "ตารางเมตร": "m2",
    "ตร.ม.": "m2",
    "ตร.ม": "m2",
    "ลูกบาศก์เมตร": "m3",
    "ลบ.ม.": "m3",
    "ลบ.ม": "m3",
    "กิโลกรัม": "kg",
    "กก.": "kg",
    "ตัน": "t",
    "ชิ้น": "pcs",
    "อัน": "pcs",
    "ชั่วโมง": "h",
    "ชม.": "h",
    # ── Indonesian / Malay ───────────────────────────────────────────
    "meter": "m",
    "meter persegi": "m2",
    "meter kubik": "m3",
    "kilogram": "kg",
    "buah": "pcs",
    "potong": "pcs",
    "biji": "pcs",
    "jam": "h",
    # ── Persian / Farsi (separate from Arabic — کیہی differ) ────────
    "متر مکعب": "m3",  # Persian ک ≠ Arabic ك
    # Note: "متر مربع" (m2) is shared with Arabic above — Persian variant
    # would use Persian Yeh (ی, U+06CC) but the squared meter symbol is
    # commonly written with Arabic letters even in Persian text.
    "کیلوگرم": "kg",
    "کیلو": "kg",
    "تن": "t",
    "عدد": "pcs",
    "دستگاه": "pcs",
    "ساعت": "h",  # Persian: ساعت (no tā' marbūṭa)
    # ── Bengali ──────────────────────────────────────────────────────
    "মিটার": "m",
    "বর্গমিটার": "m2",
    "বর্গ মিটার": "m2",
    "ঘনমিটার": "m3",
    "ঘন মিটার": "m3",
    "কিলোগ্রাম": "kg",
    "কেজি": "kg",
    "টন": "t",
    "পিস": "pcs",
    "টুকরা": "pcs",
    "ঘণ্টা": "h",
    # ── English variants commonly seen ───────────────────────────────
    "cum": "m3",
    "cu.m": "m3",
    "cubic meter": "m3",
    "cubic metre": "m3",
    "sqm": "m2",
    "sq.m": "m2",
    "square meter": "m2",
    "square metre": "m2",
    "rm": "m",
    "lin.m": "m",
    "lin m": "m",
    "running meter": "m",
    "ea": "pcs",
    "no": "pcs",
    "no.": "pcs",
    "nr": "pcs",
    "ls": "lsum",
    "lump sum": "lsum",
    "lump-sum": "lsum",
    "hour": "h",
    "hours": "h",
    "hr": "h",
    "hrs": "h",
}


def _normalise_unit(unit: str) -> str:
    """‌⁠‍Strip whitespace, lowercase, fold superscript and locale spellings.

    Resolution order:
        1. Strip + lowercase
        2. Fold ``²`` / ``³`` and ``^`` / ``**`` to ASCII (``m²`` → ``m2``)
        3. Locale alias table (``立方米`` → ``m3``, ``шт`` → ``pcs``, …)
        4. Pass through verbatim — comparisons still work even on
           unknown codes.

    Note: CWICR-snapshot units like ``"100 CY"`` / ``"1000 SF"`` are
    intentionally NOT folded into ``m3`` / ``m2`` here. A 2026-05-14
    quality-loop bench Round 1 attempted to add US-imperial aliases +
    leading-multiplier strip; the change destabilised the top-10
    ordering BGE sees and regressed recall@1 from 0.45 → ~0.05 on the
    20-fixture bench. Until we understand the interaction we keep the
    historic conservative behaviour: unknown CWICR-batch units pass
    through verbatim, so the dimensional comparison treats them as
    self-equal (no uniform area-boost across unrelated MFs).
    """
    if not unit:
        return ""
    cleaned = unit.strip().lower()
    cleaned = cleaned.replace("²", "2").replace("³", "3")
    # Some catalogues store ``"m^2"`` or ``"m**2"`` — fold to ``m2``.
    cleaned = cleaned.replace("^", "").replace("**", "")
    if cleaned in _VALID_UNITS:
        return cleaned
    if cleaned in _LOCALE_UNIT_ALIASES:
        return _LOCALE_UNIT_ALIASES[cleaned]
    return cleaned  # Pass through unknown codes — the comparison still works


def _infer_from_quantities(quantities: dict[str, float]) -> str | None:
    """‌⁠‍Pick the unit implied by the highest-precedence non-empty quantity.

    Precedence is dimensional: volume > area > length > mass > count.
    A wall element typically carries both ``area_m2`` and ``length_m``;
    we prefer the more specific dimension because that's what an
    estimator will price the position by.
    """
    precedence = ("volume_m3", "area_m2", "length_m", "perimeter_m", "mass_kg", "weight_kg", "count", "quantity")
    for key in precedence:
        value = quantities.get(key)
        if value is not None and float(value) > 0:
            return _QUANTITY_TO_UNIT.get(key)
    return None


def boost(
    envelope: ElementEnvelope,
    candidate: MatchCandidate,
    settings: Any,  # noqa: ARG001 — unused, kept for interface symmetry
) -> dict[str, float]:
    """Reward unit alignment, penalise dimensional mismatch.

    No-ops (returns ``{}``) when:
        * neither side has a unit, OR
        * one side is missing a unit and the dimensions can't be inferred.
    """
    cand_unit = _normalise_unit(candidate.unit)
    if not cand_unit:
        return {}

    env_unit = _normalise_unit(envelope.unit_hint or "")
    if not env_unit:
        env_unit = _normalise_unit(_infer_from_quantities(envelope.quantities) or "")
    if not env_unit:
        return {}

    if env_unit == cand_unit:
        return {"unit_match": BOOST_WEIGHTS.unit_match}

    # Different units — only penalise on a real dimensional mismatch.
    # ``m`` vs ``lm`` for example is the same dimension; treat as no-op.
    env_dim = _DIMENSION_GROUP.get(env_unit, env_unit)
    cand_dim = _DIMENSION_GROUP.get(cand_unit, cand_unit)
    if env_dim and cand_dim and env_dim != cand_dim:
        return {"unit_mismatch": BOOST_WEIGHTS.unit_mismatch_penalty}

    return {}
