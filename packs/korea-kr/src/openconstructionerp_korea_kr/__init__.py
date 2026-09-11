"""OpenConstructionERP - South Korea Construction partner pack (KBIM + KS + MOLIT).

This package exports a module-level ``MANIFEST`` instance of
:class:`PartnerPackManifest` referenced from ``pyproject.toml``::

    [project.entry-points."openconstructionerp.partner_packs"]
    korea-kr = "openconstructionerp_korea_kr:MANIFEST"

The OCERP core discovers this entry point at boot, validates the
manifest, and applies the partner overrides (branding, locale,
cost regions, onboarding script).
"""

from __future__ import annotations

from .manifest import MANIFEST

__all__ = ["MANIFEST"]
__version__ = "0.1.0"
