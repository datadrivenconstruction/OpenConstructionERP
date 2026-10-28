# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠AI Agents ORM models.

Tables:
    oe_ai_agents_run    - one row per agent invocation (status, totals, output).
    oe_ai_agents_step   - chronological steps within a run
                          (thought / tool_call / observation / answer / error).
    oe_ai_agents_custom - user-authored agents (name, prompt, icon, category).

The run/step tables are append-only from a user's perspective (the runner
writes incrementally as the loop progresses; the API only ever lets you
create a new run or fetch existing ones - no in-place edits). Custom agents
ARE editable/deletable by their creator through the dedicated endpoints.
"""

import uuid

from sqlalchemy import JSON, Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base


class AgentRun(Base):
    """A single agent invocation - the ReAct loop bookkeeping row."""

    __tablename__ = "oe_ai_agents_run"

    agent_name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    project_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True, index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False, index=True)
    # running | completed | failed
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="running")
    # How the run was initiated (Item 29). One of:
    #   "manual"       - a user clicked Run (default; the existing path).
    #   "schedule"     - the cron scheduler fired it.
    #   "event:<name>" - a platform event fired it (e.g. "event:rfi_created").
    # Lets the monitoring panel list automated runs and the audit trail show
    # who/what initiated each automated action.
    trigger_source: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        default="manual",
        server_default="manual",
        index=True,
    )
    # Free-form reason when status=failed (e.g. "iter_limit", "llm_error").
    failure_reason: Mapped[str | None] = mapped_column(String(100), nullable=True)
    user_input: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Final answer (markdown text) or structured proposal serialised as JSON-in-string.
    final_output: Mapped[str | None] = mapped_column(Text, nullable=True)
    iterations: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    started_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    finished_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # Trust envelope (confidence + rationale + sources) parsed off the final
    # answer when a trust-enabled agent emitted one. JSON so it can be surfaced
    # in the run view and later scored against actuals.
    trust: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # type: ignore[assignment]

    def __repr__(self) -> str:
        return f"<AgentRun {self.id} agent={self.agent_name} status={self.status}>"


class AgentStep(Base):
    """One entry in a run's ReAct timeline.

    ``role`` values: ``thought`` (LLM reasoning text), ``tool_call``
    (LLM asked to invoke a tool - ``content`` is ``{name, args}``),
    ``observation`` (tool returned - ``content`` is the result or error),
    ``answer`` (LLM emitted final text - ``content`` is ``{text}``),
    ``error`` (out-of-band failure: unknown tool, parse error, ...).
    """

    __tablename__ = "oe_ai_agents_step"

    run_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_ai_agents_run.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    step_idx: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    role: Mapped[str] = mapped_column(String(30), nullable=False)
    content: Mapped[dict | list | str | None] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=dict,
    )
    token_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    def __repr__(self) -> str:
        return f"<AgentStep run={self.run_id} idx={self.step_idx} role={self.role}>"


class AIFeedback(Base):
    """A user's correct / incorrect verdict on any AI output in the app.

    The accuracy scoreboard scores agent runs, but most AI the user actually
    sees lives outside the agent runner: the AI Estimator result, the
    match-elements suggestions, the cost advisor's answers. Those surfaces have
    no run row to attach a verdict to, so the trust loop used to dead-end there.

    This is the generic sink for that loop. ``surface`` names where the feedback
    came from (e.g. ``ai_estimator`` / ``match_elements`` / ``advisor``) and
    ``ref`` is an optional opaque pointer to the specific output (a run id, a
    match session id, a message id) so a later review can line a verdict up with
    what produced it. Nothing here is money or PII - it is a thumbs-up / down
    plus an optional free-text note, scoped to the caller (and, when relevant,
    one of their projects).
    """

    __tablename__ = "oe_ai_feedback"

    user_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False, index=True)
    # Optional project scope. Verified against the caller's access at write time
    # so a verdict can never be attributed to a project they cannot see.
    project_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True, index=True)
    # Which AI surface the verdict is about (short slug, e.g. "ai_estimator").
    surface: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    # Opaque pointer to the specific output the verdict is about (a run id, a
    # session id, a message id, ...). Free-form so each surface picks what it
    # can line up later; never dereferenced server-side.
    ref: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # The verdict: did this AI output turn out correct?
    correct: Mapped[bool] = mapped_column(Boolean, nullable=False)
    # Optional short correction / context note (what the right answer was, etc.).
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:
        return f"<AIFeedback {self.id} user={self.user_id} surface={self.surface} correct={self.correct}>"


# Custom-agent run names are prefixed with this slug so the run path can tell
# a user-authored agent (``custom:<uuid>``) apart from a built-in one and
# resolve it from the DB instead of the in-memory registry. The colon is safe
# inside ``agent_name`` (VARCHAR(100)) and never collides with a built-in slug.
CUSTOM_AGENT_PREFIX = "custom:"


class CustomAgent(Base):
    """A user-authored agent definition.

    Custom agents live in the DB (built-ins live in the in-memory registry).
    They carry the same presentation + behaviour fields a built-in
    :class:`app.modules.ai_agents.base.Agent` exposes, but they have NO tools:
    a non-technical estimator builds a focused prompt-only helper. The run
    path resolves them by ``agent_name == "custom:<id>"`` and runs them through
    the exact same :class:`AgentRunner` loop as the built-ins.

    Ownership: ``user_id`` is the creator. Only the creator may edit/delete,
    and only the creator sees their custom agents listed alongside the
    built-ins (mirrors the per-user privacy model of agent runs).
    """

    __tablename__ = "oe_ai_agents_custom"

    user_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False, index=True)
    # Human-facing label shown on the card (e.g. "Tender Letter Helper").
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    # One-line "what you get" promise shown under the title.
    tagline: Mapped[str] = mapped_column(String(280), nullable=False, default="")
    # Longer description (optional). Falls back to tagline in the UI.
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # The compiled system prompt the runner sends to the LLM. Built from the
    # friendly guided builder fields (role + goal + audience + format) so a
    # non-technical user never writes a raw prompt by hand.
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    # Coarse catalogue grouping (estimating | quality | documents | analytics
    # | planning | general). The UI buckets cards by this.
    category: Mapped[str] = mapped_column(String(40), nullable=False, default="general")
    # Lucide icon name the frontend maps to a glyph (e.g. "calculator").
    icon: Mapped[str] = mapped_column(String(40), nullable=False, default="sparkles")
    # Ready-to-run example prompts (list[str]); clicking one fills the run box.
    example_prompts: Mapped[list] = mapped_column(JSON, nullable=False, default=list)  # type: ignore[type-arg]
    # The guided-builder spec (role/goal/audience/output_format/extra_guidance)
    # the system_prompt was compiled from, or NULL when the user pasted a raw
    # prompt. Stored so the edit form can re-hydrate the friendly fields instead
    # of showing the compiled prompt.
    guided: Mapped[dict | None] = mapped_column(JSON, nullable=True, default=None)  # type: ignore[type-arg]
    # Workflow-automation envelope for the agent (Item 29). A single JSON dict
    # so scheduling + tool-access can grow without a migration per knob. Shape:
    #   {
    #     "cron": "0 9 * * *" | null,        # 5-field POSIX cron, UTC
    #     "schedule_enabled": bool,           # paused without losing the cron
    #     "next_run_at": "<ISO8601 UTC>"|null,# computed from cron, advanced as it fires
    #     "schedule_input": str,              # the prompt a scheduled run is fired with
    #     "triggers": ["rfi_created", ...],   # event names (wiring deferred)
    #     "allowed_tools": ["search_costs"],  # tool slugs the agent may call
    #   }
    # The Python attribute is deliberately NOT named ``metadata`` - that name is
    # reserved by SQLAlchemy's declarative ``Base`` (the MetaData object).
    automation: Mapped[dict] = mapped_column(  # type: ignore[type-arg]
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:
        return f"<CustomAgent {self.id} user={self.user_id} name={self.display_name!r}>"

    @property
    def cron_expr(self) -> str | None:
        """The agent's cron expression, or ``None`` when not scheduled."""
        auto = self.automation if isinstance(self.automation, dict) else {}
        expr = auto.get("cron")
        return expr if isinstance(expr, str) and expr.strip() else None

    @property
    def schedule_enabled(self) -> bool:
        """Whether the schedule is active (defaults true when a cron is set)."""
        auto = self.automation if isinstance(self.automation, dict) else {}
        return bool(auto.get("schedule_enabled", True))

    @property
    def allowed_tools(self) -> list[str]:
        """Tool slugs the agent is permitted to call (empty = prompt-only)."""
        auto = self.automation if isinstance(self.automation, dict) else {}
        tools = auto.get("allowed_tools")
        return [str(t) for t in tools] if isinstance(tools, list) else []

    @property
    def agent_name(self) -> str:
        """The runner-facing slug for this custom agent (``custom:<uuid>``)."""
        return f"{CUSTOM_AGENT_PREFIX}{self.id}"
