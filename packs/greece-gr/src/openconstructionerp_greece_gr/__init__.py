"""OpenConstructionERP - Greece country pack (ΝΕΤ articles, EUR, ΦΠΑ).

This package exports a module-level ``MANIFEST`` instance of
:class:`PartnerPackManifest` referenced from ``pyproject.toml``::

    [project.entry-points."openconstructionerp.partner_packs"]
    greece-gr = "openconstructionerp_greece_gr:MANIFEST"
"""

from __future__ import annotations

from .manifest import MANIFEST

__all__ = ["MANIFEST"]
__version__ = "0.1.0"
