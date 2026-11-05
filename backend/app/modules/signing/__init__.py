# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""E-signature workflow abstraction and attestation registry.

A project-scoped model of who must sign what, and a register of the signature
*attestations* that have been recorded against a document. It is deliberately
jurisdiction-neutral and provider-neutral: it describes a signature by its legal
*capability* (a qualified electronic signature, an advanced electronic
signature, a simple electronic signature, a digital-certificate signature) and
never by a vendor or a country's product. Real regional schemes - RU УКЭП/GOST,
EU eIDAS QES, India DSC, US e-sign - plug in later as provider adapters keyed on
the same capability vocabulary.

What this module is NOT
=======================
It performs **no cryptography** and stores **no secrets**. It never accepts a
private key, a certificate file, a password or any credential. It records
attestations (who signed, in what role, at what time, against which content
hash, with which certificate *metadata*) and models the workflow state machine
(draft -> awaiting_signatures -> partially_signed -> fully_signed | declined |
expired). The actual signing happens in an external signing tool; this module
only registers the fact of it and reasons about staleness, completeness and
certificate-metadata expiry.
"""


async def on_startup() -> None:
    """Module startup hook - register permissions."""
    from app.modules.signing.permissions import register_signing_permissions

    register_signing_permissions()
    from app.modules.signing.validators import register_signing_validation_rules

    register_signing_validation_rules()
