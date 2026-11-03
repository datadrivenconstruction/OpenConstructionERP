# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Document assistant module manifest."""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_doc_assistant",
    version="0.1.0",
    display_name="Document Assistant",
    description=(
        "Ask a question in plain language over the project's specifications, drawings, RFIs, submittals, "
        "correspondence, minutes and contracts. Answers cite document, revision, page or sheet and section, "
        "and say so plainly when the documents do not contain the answer"
    ),
    author="OpenConstructionERP Core Team",
    category="core",
    depends=["oe_users", "oe_projects", "oe_documents", "oe_file_search", "oe_rfi"],
    auto_install=True,
    enabled=True,
)
