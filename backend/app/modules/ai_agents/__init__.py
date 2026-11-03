# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""AI Agents framework - Slice 1.

Provides a generic ReAct-style agent loop on top of the single-call
``ai`` module LLM client. Adds a Tool protocol + ToolRegistry so each
agent can declare exactly which side-effect-free helpers it is allowed
to call, plus per-run persistence (``AgentRun`` + ``AgentStep``) so the
UI can render a vertical timeline of every thought / tool call /
observation / answer.

The runner NEVER auto-applies an agent's output to the BOQ /
project - it returns the proposal so the user can review it in the
review panel (the architecture guide "AI-augmented, human-confirmed" principle).
"""


async def on_startup() -> None:
    """Module startup hook - register permissions + built-in agents."""
    from app.modules.ai_agents.agents.advisors import register_advisor_agents
    from app.modules.ai_agents.agents.boq_drafter import register_boq_drafter
    from app.modules.ai_agents.agents.cost_classifier import register_cost_classifier
    from app.modules.ai_agents.agents.document_analyst import register_document_analyst
    from app.modules.ai_agents.agents.estimate_reviewer import register_estimate_reviewer
    from app.modules.ai_agents.agents.progress_reporter import register_progress_reporter
    from app.modules.ai_agents.agents.project_analyst import register_project_analyst
    from app.modules.ai_agents.agents.rate_benchmarker import register_rate_benchmarker
    from app.modules.ai_agents.permissions import register_ai_agents_permissions

    register_ai_agents_permissions()
    # Built-in agent catalogue. Each agent is self-contained (its own tools +
    # an Agent descriptor with UI metadata); registration is idempotent so a
    # re-run on a hot reload just overwrites by name.
    #
    # Tool-backed agents (read the platform's real project data):
    register_boq_drafter()
    register_estimate_reviewer()
    register_cost_classifier()
    register_document_analyst()
    register_project_analyst()
    register_rate_benchmarker()
    register_progress_reporter()
    # Prompt-only advisory agents (help me think / draft / structure):
    register_advisor_agents()
    # Project catalogue (RFI, daily report, clause review, submittal check) and its rule set.
    from app.modules.ai_agents.catalogue import register_catalogue
    from app.modules.ai_agents.validators import register_ai_agent_rules

    register_catalogue()
    register_ai_agent_rules()
