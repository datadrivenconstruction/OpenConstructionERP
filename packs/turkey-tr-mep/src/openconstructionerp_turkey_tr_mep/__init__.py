"""OpenConstructionERP - Turkey MEP contractor pack.

The Türkiye country configuration with the menu and module set of a
mechanical, electrical and plumbing contractor. This package exports a
module-level ``MANIFEST`` instance of :class:`PartnerPackManifest` referenced
from ``pyproject.toml``::

    [project.entry-points."openconstructionerp.partner_packs"]
    turkey-tr-mep = "openconstructionerp_turkey_tr_mep:MANIFEST"

The manifest is derived from the ``turkey-tr`` country pack at import time, so
this pack carries no copy of the country configuration.
"""

from __future__ import annotations

from .manifest import MANIFEST

__all__ = ["MANIFEST"]
__version__ = "0.1.0"
