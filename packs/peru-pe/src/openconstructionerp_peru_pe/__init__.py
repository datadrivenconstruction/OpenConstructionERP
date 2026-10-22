"""OpenConstructionERP - Peru construction partner pack (presupuesto, IGV, valorizaciones).

Exports a module-level ``MANIFEST`` referenced from ``pyproject.toml``::

    [project.entry-points."openconstructionerp.partner_packs"]
    peru-pe = "openconstructionerp_peru_pe:MANIFEST"
"""

from __future__ import annotations

from .manifest import MANIFEST

__all__ = ["MANIFEST"]
__version__ = "0.1.0"
