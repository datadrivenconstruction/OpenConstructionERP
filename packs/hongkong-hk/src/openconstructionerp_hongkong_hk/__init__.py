"""OpenConstructionERP - Hong Kong SAR country pack (Cap. 652 payment clock, CIC and CWR levies, HKSMM4 codes).

Exports a module-level ``MANIFEST`` referenced from ``pyproject.toml``::

    [project.entry-points."openconstructionerp.partner_packs"]
    hongkong-hk = "openconstructionerp_hongkong_hk:MANIFEST"
"""

from __future__ import annotations

from .manifest import MANIFEST

__all__ = ["MANIFEST"]
__version__ = "0.1.0"
