"""OpenConstructionERP - Pakistan construction partner pack (GST, provincial sales tax, PEC and PPRA forms).

Exports a module-level ``MANIFEST`` referenced from ``pyproject.toml``::

    [project.entry-points."openconstructionerp.partner_packs"]
    pakistan-pk = "openconstructionerp_pakistan_pk:MANIFEST"
"""

from __future__ import annotations

from .manifest import MANIFEST

__all__ = ["MANIFEST"]
__version__ = "0.1.0"
