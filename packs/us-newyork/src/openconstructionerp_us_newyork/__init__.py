"""OpenConstructionERP - New York construction pack.

State depth for New York, layered on the national US pack rather than
repeating it. What this pack adds:

* **Sales tax on construction** - a capital improvement is not taxed to the
  customer once Form ST-124 is on file, and the contractor pays tax on its
  materials; a repair or maintenance job is taxed on the whole bill, labor
  included. The same scope can be either, and the bid moves by the combined
  rate times the price
* **Prevailing wage** - Article 8 schedules from the state labor department,
  or from the city Comptroller inside New York City, and certified payroll
  filed electronically in the department's XML format
* **Retainage** - 5 percent per payment on private contracts of 150 thousand
  dollars or more entered into from 17 November 2023, and on public work
* **Payment and lien clocks** - the state, local and private payment clocks,
  and a notice of lien filed within 8 months of the last work (4 months for a
  single family dwelling)

No cost database is bundled. The rules the application reads are served by the
``oe_us_ny_pack`` backend module, which carries a statutory citation on every
figure; this package is the activatable pack around them.

This package exports a module-level ``MANIFEST`` instance of
:class:`PartnerPackManifest` referenced from ``pyproject.toml``::

    [project.entry-points."openconstructionerp.partner_packs"]
    us-newyork = "openconstructionerp_us_newyork:MANIFEST"
"""

from __future__ import annotations

from .manifest import MANIFEST

__all__ = ["MANIFEST"]
__version__ = "0.1.0"
