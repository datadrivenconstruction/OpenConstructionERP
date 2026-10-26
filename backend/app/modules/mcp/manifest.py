# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""MCP server module manifest."""

from app.core.module_loader import InferenceDeclaration, InferenceRole, ModuleManifest

manifest = ModuleManifest(
    name="oe_mcp",
    version="1.0.0",
    display_name="MCP server",
    description=(
        "Model Context Protocol endpoint: an external AI client reads a person's projects under that "
        "person's permissions and proposes changes the person confirms in the app"
    ),
    author="OpenConstructionERP Core Team",
    category="integration",
    # Read tools reach BOQ, schedule, costs, validation, RFIs, submittals, punch
    # items and documents only while those modules are enabled; the proposal
    # tools come from the assistant's action registry in oe_erp_chat.
    depends=["oe_users", "oe_projects", "oe_erp_chat"],
    auto_install=True,
    enabled=True,
    inference=InferenceDeclaration(
        role=InferenceRole.CONSUMES_RESULT,
        what=(
            "Changes an external AI client proposes through the propose_* tools (a BOQ line, a task, an "
            "RFI and the other assistant actions), each with the client's confidence and rationale"
        ),
        basis=(
            "The module runs no model. A propose_* call is validated by the same action spec the in-app "
            "assistant uses and stored as an oe_erp_chat_action row with source=mcp and status proposed; "
            "nothing else is written. The record changes only when a person applies the proposal in the "
            "Changes view, under the gates of that record's own REST route for that person"
        ),
    ),
)
