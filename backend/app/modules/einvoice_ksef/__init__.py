# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Polish KSeF 2.0 e-invoicing with the FA(3) structure.

A plugin of :mod:`app.modules.einvoice_clearance`, the same shape as Egypt's
``einvoice_eta``: its own package, no tables, no routes. On startup it registers
into the clearance module's registries. Remove this folder and Poland goes back
to being a regime row the offline reference adapter can rehearse.

Shape
=====
``facts.py``          dated, sourced facts: schemas, phases, deadlines, hosts.
``ksef_number.py``    the KSeF number and its CRC-8.
``fa3.py``            the FA(3) writer and a reader for the rules.
``split_payment.py``  whether P_18A applies.
``builder.py``        finance invoice -> FA(3).
``offline.py``        offline modes and upload deadlines.
``qr.py``             KOD I and KOD II.
``crypto.py``         document and token encryption for the API.
``client.py``         the KSeF API 2.0.
``adapter.py``        the clearance adapter (key ``ksef_pl``).
``payments.py``       the KSeF number of an invoice, and payment titles.
``jpk.py``            the JPK_V7(3) per-document marker.
``validators.py``     the rules.

Facts and sources are in ``docs/design/poland/ksef.md``.
"""


async def on_startup() -> None:
    """Register the adapter, the payload builder and the rules.

    Idempotent: all three registries overwrite by key.
    """
    from app.modules.einvoice_clearance.adapters import adapter_registry
    from app.modules.einvoice_clearance.service import register_payload_builder
    from app.modules.einvoice_ksef.adapter import KsefAdapter
    from app.modules.einvoice_ksef.builder import build_from_invoice
    from app.modules.einvoice_ksef.facts import FA3
    from app.modules.einvoice_ksef.validators import register_ksef_rules

    adapter_registry.register(KsefAdapter())
    register_payload_builder(FA3.key, build_from_invoice)
    register_ksef_rules()
