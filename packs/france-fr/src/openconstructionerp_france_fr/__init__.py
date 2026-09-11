"""OpenConstructionERP - France Construction partner pack (DPGF + NF DTU + TVA).

This package exports a module-level ``MANIFEST`` instance of
:class:`PartnerPackManifest` referenced from ``pyproject.toml``::

    [project.entry-points."openconstructionerp.partner_packs"]
    france-fr = "openconstructionerp_france_fr:MANIFEST"

The OCERP core discovers this entry point at boot, validates the
manifest, and applies the partner overrides (branding, locale,
cost regions, validation rule sets, onboarding script).
"""

from __future__ import annotations

from .manifest import MANIFEST

__all__ = ["MANIFEST"]
__version__ = "0.1.0"
