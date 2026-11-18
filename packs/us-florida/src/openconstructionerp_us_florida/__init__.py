"""OpenConstructionERP - Florida construction pack.

State depth for Florida, layered on the national US pack rather than
repeating it. What this pack adds:

* **Sales tax on construction** - under a lump sum contract the contractor is
  the ultimate consumer of the materials it installs; a retail sale plus
  installation contract collects tax from the customer instead. The county
  surtax reaches only the first 5,000 dollars of a single item
* **Wages** - no state prevailing wage law, and from 30 September 2026 a local
  government may not use its contracts to set the wages its contractors pay
* **Retainage** - 5 percent on public contracts over 200 thousand dollars;
  private retainage follows the contract
* **Payment and lien clocks** - 20 business days for local government
  payments, and the notice to owner within 45 days, claim of lien within 90
  days and enforcement within one year

No cost database is bundled. The rules the application reads are served by the
``oe_us_fl_pack`` backend module, which carries a statutory citation on every
figure; this package is the activatable pack around them.

This package exports a module-level ``MANIFEST`` instance of
:class:`PartnerPackManifest` referenced from ``pyproject.toml``::

    [project.entry-points."openconstructionerp.partner_packs"]
    us-florida = "openconstructionerp_us_florida:MANIFEST"
"""

from __future__ import annotations

from .manifest import MANIFEST

__all__ = ["MANIFEST"]
__version__ = "0.1.0"
