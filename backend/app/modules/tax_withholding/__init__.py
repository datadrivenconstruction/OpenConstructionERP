# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Tax withholding module.

Two taxes that both land on a subcontractor payment and that the product could
not express at all until now.

**Withholding.** The payer deducts tax from the subcontractor and remits it to
the state: the UK Construction Industry Scheme at 0, 20 or 30 percent depending
on verification; German Bauabzugsteuer at 15 percent under section 48 EStG
unless a Freistellungsbescheinigung is held; Irish Relevant Contracts Tax at 0,
20 or 35; Italian ritenuta d'acconto; US backup withholding where no certified
taxpayer identification number is on file.

**Reverse charge.** The buyer accounts for the VAT instead of the seller, and
the invoice has to carry the statutory wording and no VAT amount: the UK
domestic reverse charge for construction services, German section 13b UStG,
Spanish inversion del sujeto pasivo, French autoliquidation.

None of this is retainage. ``finance`` and ``subcontractors`` already model
money held back from a certified claim and released later, and both of them
call it withholding - see the note at the top of
:mod:`app.modules.tax_withholding.models` for why no column here shares that
name. Tax withheld goes to the state and the payee reclaims it themselves;
retainage comes back from the payer.

No network calls. The schemes are seed data and the submissions are records; a
government platform is an adapter behind that, not a dependency of the core.
"""


async def on_startup() -> None:
    """Module startup hook (called by the module loader after mount).

    Registers three things, all load-bearing:

    * the module's permissions, without which ``RequirePermission`` denies an
      unregistered key and every endpoint here is admin-only in production
      while every admin-authenticated test keeps passing;
    * the ``tax_withholding`` validation rule set, which the deduction and
      reverse-charge endpoints run on every save and which gates taking a
      record out of draft;
    * the provider that hands a payment certificate the statutory tax figures
      stored for its document. The registry belongs to ``contracts`` and is
      looked up at startup rather than imported at the top, so this module
      still loads on an install without it.

    Idempotent - every registry overwrites by key, so a hot reload
    re-registers cleanly.
    """
    from app.modules.tax_withholding.permissions import register_tax_withholding_permissions
    from app.modules.tax_withholding.service import register_certificate_tax_provider
    from app.modules.tax_withholding.validators import register_tax_withholding_rules

    register_tax_withholding_permissions()
    register_tax_withholding_rules()
    register_certificate_tax_provider()
