# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""E-signature abstraction module manifest."""

from app.core.module_loader import ModuleManifest
from app.modules.signing.data_paths import DATA_PATHS

manifest = ModuleManifest(
    name="oe_signing",
    version="0.1.0",
    display_name="E-Signature Registry",
    description=(
        "Jurisdiction-neutral e-signature workflow abstraction and attestation "
        "registry. Models who must sign a document, records signature "
        "attestations (signatory, role, signed content hash, certificate "
        "metadata) and reasons about completeness, hash-staleness and "
        "certificate-metadata expiry. Describes a signature by its legal "
        "capability - qualified / advanced / simple electronic, or digital "
        "certificate - never by a vendor. Performs no cryptography and stores "
        "no keys, passwords or credentials; regional schemes plug in as "
        "provider adapters."
    ),
    author="OpenConstructionERP Core Team",
    category="core",
    depends=["oe_users", "oe_projects"],
    auto_install=True,
    enabled=True,
    data_paths=DATA_PATHS,
)
