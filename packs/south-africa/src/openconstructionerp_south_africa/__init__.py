"""OpenConstructionERP - South Africa partner pack.

Pre-configures OCERP for South African construction against SANS 1200 civil
works and the ASAQS Standard System of Measuring Building Work, CIDB
contractor grading (1 to 9), the PPPFA 80/20 and 90/10 preferential
procurement scoring, the National Treasury infrastructure delivery and
procurement management framework (FIDPM 2019), ZAR and 15 percent VAT.

This package exports a module-level ``MANIFEST`` instance referenced from
``pyproject.toml``::

    [project.entry-points."openconstructionerp.packs"]
    south-africa = "openconstructionerp_south_africa:MANIFEST"

The OCERP core discovers this entry point at boot, validates the manifest,
and applies the partner overrides (branding, locale, cost regions, validation
rule packs, onboarding script).

This is DataDrivenConstruction's first African market pack. It is written from
public South African standards. The proposal and a reference implementation
came from Aidan Koetaan; see CONTRIBUTORS.md.
"""

from __future__ import annotations

from .manifest import MANIFEST

__all__ = ["MANIFEST"]
__version__ = "0.1.0"
