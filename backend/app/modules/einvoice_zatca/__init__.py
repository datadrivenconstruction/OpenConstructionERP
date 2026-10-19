# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Saudi Arabia ZATCA FATOORA phase 2 e-invoicing.

A plugin of :mod:`app.modules.einvoice_clearance`. On startup it registers into
that module's registries; remove this folder and Saudi Arabia goes back to being
a regime row the offline reference adapter can rehearse. It owns two tables (the
EGS units and their chains) and a small router for onboarding them.

Shape
=====
``codes.py``       the code lists and the KSA-2 subtype.
``data.py``        dated, sourced facts: VAT rates, construction rules, environments, API paths.
``c14n.py``        the canonicalization the invoice hash needs.
``hashing.py``     the invoice hash and the certificate and signed-properties digests.
``builder.py``     UBL 2.1 KSA document from neutral inputs.
``qr.py``          the TLV QR.
``signing.py``     pluggable signers (stored key, signing service, test).
``stamp.py``       the XAdES stamp and QR applied to a document.
``csr.py``         the certificate signing request.
``checks.py``      the offline rule checks.
``models.py``      EGS units and chain entries.
``service.py``     onboarding, the chain and the payload builder.
``client.py``      the FATOORA REST client.
``adapter.py``     the clearance adapter (key ``zatca_fatoora``).
``validators.py``  the rules.
``router.py``      onboarding endpoints.

Facts and sources are in ``docs/design/saudi-arabia/zatca.md``.
"""


async def on_startup() -> None:
    """Register permissions, the adapter, the payload builder and the rules.

    Idempotent: every registry overwrites by key.
    """
    from app.modules.einvoice_clearance.adapters import adapter_registry
    from app.modules.einvoice_clearance.service import register_payload_builder
    from app.modules.einvoice_zatca.adapter import ZatcaAdapter
    from app.modules.einvoice_zatca.permissions import register_einvoice_zatca_permissions
    from app.modules.einvoice_zatca.service import build_from_invoice
    from app.modules.einvoice_zatca.validators import ZATCA_FORMAT, register_zatca_rules

    register_einvoice_zatca_permissions()
    adapter_registry.register(ZatcaAdapter())
    register_payload_builder(ZATCA_FORMAT, build_from_invoice)
    register_zatca_rules()
