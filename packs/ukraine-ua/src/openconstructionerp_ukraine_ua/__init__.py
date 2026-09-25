"""OpenConstructionERP - Ukraine country pack (кошторис chapters, UAH, ПДВ).

This package exports a module-level ``MANIFEST`` instance of
:class:`PartnerPackManifest` referenced from ``pyproject.toml``::

    [project.entry-points."openconstructionerp.partner_packs"]
    ukraine-ua = "openconstructionerp_ukraine_ua:MANIFEST"
"""

from __future__ import annotations

from .manifest import MANIFEST

__all__ = ["MANIFEST"]
__version__ = "0.1.0"
