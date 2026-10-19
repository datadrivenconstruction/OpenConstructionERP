# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Egyptian Tax Authority (ETA) e-invoicing.

A plugin of :mod:`app.modules.einvoice_clearance`, written the way that
module's adapter boundary asks for: it lives in its own package, adds no tables
and no routes, and on startup registers into the clearance module's existing
registries. Remove this folder and Egypt goes back to being a regime row the
offline reference adapter can rehearse.

Shape
=====
``codes.py``          ETA's code tables, shipped unedited from the SDK.
``serialization.py``  the canonical form ETA hashes and signs.
``calculation.py``    the line and document equations, computed and checked.
``builder.py``        finance invoice -> ETA v1.0 JSON document.
``checks.py``         what ETA would refuse, found before sending.
``validators.py``     those checks as rules in the clearance rule set.
``der.py``, ``signing.py``  CAdES-BES, with the key on a token, an HSM or a
                      signing service; a test signer for tests.
``client.py``         the ETA REST API.
``adapter.py``        the clearance adapter (key ``eta_eg``).

Facts and sources are in ``docs/design/egypt/eta.md``. Everything here is
pinned in the tests to the samples ETA publishes in its SDK.
"""


async def on_startup() -> None:
    """Register the adapter, the payload builder and the rules.

    Idempotent: all three registries overwrite by key.
    """
    from app.modules.einvoice_clearance.adapters import adapter_registry
    from app.modules.einvoice_clearance.service import register_payload_builder
    from app.modules.einvoice_eta.adapter import EtaAdapter
    from app.modules.einvoice_eta.builder import build_from_invoice
    from app.modules.einvoice_eta.validators import ETA_DOCUMENT_FORMAT, register_eta_rules

    adapter_registry.register(EtaAdapter())
    register_payload_builder(ETA_DOCUMENT_FORMAT, build_from_invoice)
    register_eta_rules()
