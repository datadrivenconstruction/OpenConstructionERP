"""OpenConstructionERP - Egypt country pack (MasterFormat + EGP + Law 182/2018 + ETA).

Exports a module-level ``MANIFEST`` referenced from ``pyproject.toml``::

    [project.entry-points."openconstructionerp.partner_packs"]
    egypt-eg = "openconstructionerp_egypt_eg:MANIFEST"
"""

from __future__ import annotations

from .manifest import MANIFEST

__all__ = ["MANIFEST"]
__version__ = "0.1.0"
