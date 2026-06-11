"""Discount grocery retail pack (DACH) for OpenConstructionERP.

An industry pack for German-speaking discount food-retail new-builds. It
ships three fully priced example projects (Heilbronn, Heidelberg and
Karlsruhe), each a DIN 276 cost plan with a complete Leistungsverzeichnis,
plus the DACH standards stack (DIN 276, GAEB DA XML 3.3, LV quality and BKI
benchmarks).
"""

from __future__ import annotations

from .manifest import MANIFEST

__all__ = ["MANIFEST"]
__version__ = "0.1.0"
