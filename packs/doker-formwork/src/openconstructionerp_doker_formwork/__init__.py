"""Formwork pack for OpenConstructionERP.

Exposes ``MANIFEST`` for the ``openconstructionerp.partner_packs`` entry-point.
"""

from __future__ import annotations

from .manifest import MANIFEST

__all__ = ["MANIFEST"]
__version__ = "0.2.0"
