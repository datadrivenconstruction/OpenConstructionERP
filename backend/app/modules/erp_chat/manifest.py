# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""ERP Chat module manifest."""

from app.core.module_loader import InferenceDeclaration, InferenceRole, ModuleManifest

manifest = ModuleManifest(
    name="oe_erp_chat",
    version="0.1.0",
    display_name="ERP Chat",
    description="AI chat over construction ERP data: reads through tools, proposes changes a person applies",
    author="OpenConstructionERP Core Team",
    category="core",
    # No hard dependency on the modules a proposal writes to (BOQ, tasks, ...):
    # the action registry offers a propose_* tool only while its module is
    # loaded and enabled, so switching one off removes a tool, not the chat.
    depends=["oe_ai", "oe_projects"],
    auto_install=True,
    enabled=True,
    inference=InferenceDeclaration(
        role=InferenceRole.CALLS_MODEL,
        what=(
            "An answer to a question the user typed about their own project data, which read tools to "
            "call to get that data, and the changes to propose (a BOQ line, a task and the other "
            "propose_* actions) together with a confidence and a one-line reason for each"
        ),
        basis=(
            "service.py posts to the Anthropic and OpenAI endpoints with its own HTTP client rather "
            "than only through the shared provider layer, which is why it is named twice by the gate. "
            "The read tools only read. A change is a propose_* tool from actions/registry.py: it checks "
            "the model's arguments for the person asking, project access included, and stores a "
            "proposal, nothing else - no BOQ line, no task. The record is written only when a person "
            "applies the proposal through /erp_chat/actions/, which runs the gates of that record's own "
            "REST route for that person (permission, project access, owner and lock checks) and writes "
            "through the domain service with them as the actor, so the assistant never has more rights "
            "than the person who clicks Apply. Every apply and every undo is logged to oe_activity_log "
            "with via=ai_assistant, who asked, who approved and the model's confidence. Recorded here "
            "because a register that lists this beside a module that only renders text would be "
            "describing two different things with one word"
        ),
    ),
)
