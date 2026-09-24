# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""ERP Chat service - agent loop with SSE streaming and tool calling.

Supports Anthropic and OpenAI APIs with tool-calling (function calling).
Other providers fall back to plain text via the shared ai_client.call_ai().

The model reads through the tools in ``tools.py`` and changes nothing. A
change is a ``propose_*`` tool from ``actions.registry``: the call stores a
proposal, which is committed before its ``tool_result`` frame so the card's
Apply request (another session) finds it, and the person applies it through
``/erp_chat/actions/`` under the record's own REST gates.
"""

import asyncio
import json
import logging
import time
import uuid
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from fastapi import HTTPException
from sqlalchemy import case, func, select
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.erp_chat.actions import registry as action_registry
from app.modules.erp_chat.actions.base import ActionConflictError
from app.modules.erp_chat.actions.service import ChatActionService, propose_tool_result
from app.modules.erp_chat.models import ChatMessage, ChatSession, ChatTurnFeedback
from app.modules.erp_chat.prompts import SYSTEM_PROMPT, SYSTEM_PROMPT_NO_TOOLS, build_context_block
from app.modules.erp_chat.schemas import StreamChatRequest
from app.modules.erp_chat.tools import (
    TOOL_DEFINITIONS,
    TOOL_HANDLER_MAP,
    TOOL_PERMISSIONS,
    ToolAuthError,
    ToolPermissionDenied,
    _auth_error,
    _extract_project_id,
    _require_project_access,
    check_tool_permission,
    manager_permission_error_result,
)

logger = logging.getLogger(__name__)

# Maximum tool-calling rounds to prevent infinite loops
MAX_AGENT_ROUNDS = 5

# Providers beyond OpenAI itself that we call with a tool schema over the
# OpenAI chat-completions protocol.
#
# Issue #424: tool access used to be a two-literal branch on the provider name,
# so OpenRouter - which speaks that identical protocol - was routed to a
# plain-text call and the model dutifully told the user that live data was
# unavailable "with the current AI provider". That statement was true of the
# implementation and false about the transport.
#
# Widening this set is per provider and on evidence, not by category. Response
# shapes already diverge INSIDE the OpenAI-compatible group - ai_client keeps a
# provider-keyed text extractor for exactly that reason - Cohere is a different
# contract outright, and ollama/vllm must keep the SSRF-guarded transport they
# have today.
TOOL_CAPABLE_OPENAI_COMPAT = frozenset({"openrouter"})

# Every provider whose response is shaped like an OpenAI chat completion. The
# three response parsers below key off this set rather than a single literal:
# widening the dispatch alone is the half-applied fix, and it fails silently -
# tool calls read as absent, appended results are dropped, and the user gets a
# blank bubble instead of an answer.
OPENAI_WIRE_PROVIDERS = frozenset({"openai"}) | TOOL_CAPABLE_OPENAI_COMPAT

# Timeout for AI API calls
AI_TIMEOUT = 120.0

# Maximum serialized size of a single tool result re-fed to the LLM.
# ~8000 chars ≈ 2000 tokens - keeps the agent loop from blowing up the
# context window on large `get_boq_items`/list-style tool returns.
MAX_TOOL_RESULT_CHARS = 8000

# ── Conversation-history hardening ────────────────────────────────────────
# The frontend can submit ``conversation_history`` verbatim. We MUST cap it
# before re-feeding to the LLM, otherwise (a) prompt injection via stuffed
# history grows unbounded, (b) cost explodes on a single request, and
# (c) the provider rejects/truncates the request unpredictably.
MAX_HISTORY_MESSAGES = 20  # keep most-recent N turns only
MAX_HISTORY_MESSAGE_CHARS = 4000  # truncate each individual message
ALLOWED_HISTORY_ROLES = ("user", "assistant")

# Per-user 24h soft token budget. When exceeded, the chat endpoint refuses
# further requests until the window rolls over. Default ~500K tokens / day
# is generous for legitimate ERP-chat usage and caps runaway spend from a
# single compromised account or buggy client.
import os as _os

DAILY_TOKEN_BUDGET = int(_os.environ.get("ERPCHAT_DAILY_TOKEN_BUDGET", "500000"))


def _truncate_tool_result(result: Any) -> Any:
    """Trim tool output to a safe size before re-injecting into the LLM context.

    Strategy: if the result has a ``data`` list longer than 50 items, cap it.
    Then serialize and, if still too large, return a compact summary skeleton.
    Non-dict results are returned as-is.
    """
    if not isinstance(result, dict):
        return result

    # If result has a `data` list, cap it at 50 items
    if isinstance(result.get("data"), list) and len(result["data"]) > 50:
        original_len = len(result["data"])
        result = {
            **result,
            "data": result["data"][:50],
            "_truncated": f"showing 50 of {original_len} items",
        }

    # Final string-length check
    serialized = json.dumps(result, default=str)
    if len(serialized) > MAX_TOOL_RESULT_CHARS:
        data = result.get("data")
        return {
            "summary": (result.get("summary") or "")[:1000],
            "renderer": result.get("renderer", "generic_table"),
            "data": data[:20] if isinstance(data, list) else None,
            "_truncated": (f"original size {len(serialized)} chars, truncated to fit context window"),
        }
    return result


def _result_for_model(result: Any) -> Any:
    """The part of a tool result the model reads back on its next round.

    A proposal's full DTO (option lists, i18n keys, flags for the caller) is
    for the card and for the stored history. The model gets the proposal's id,
    status and summary, which already names every field and says the change is
    not saved. Re-feeding the DTO cost tokens on every later round, and past
    ``MAX_TOOL_RESULT_CHARS`` the truncation kept only the first 1000
    characters of the summary, which can cut off exactly that sentence.
    """
    if not isinstance(result, dict) or result.get("renderer") != "action_proposal":
        return result
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    return {
        "renderer": "action_proposal",
        "action_id": data.get("id"),
        "status": data.get("status"),
        "summary": result.get("summary"),
    }


def _sse(event_type: str, data: dict[str, Any]) -> str:
    """Format a Server-Sent Event string."""
    return f"event: {event_type}\ndata: {json.dumps(data)}\n\n"


def _proposal_tools(openai_shape: bool) -> list[dict[str, Any]]:
    """The registry's ``propose_*`` tools, read at request time.

    The registry decides which actions are available right now (an action's
    module can be switched off), so the set is never frozen at import. A
    broken registry costs the proposal tools, not the read tools with them.
    """
    try:
        if openai_shape:
            return action_registry.openai_tool_definitions()
        return action_registry.tool_definitions()
    except Exception:
        logger.exception("erp_chat: the action registry failed; offering the read tools only")
        return []


def _proposal_spec(tool_name: str) -> Any:
    """The action spec behind ``tool_name``, or None when it is not a proposal tool."""
    try:
        return action_registry.get_spec_for_tool(tool_name)
    except Exception:
        logger.exception("erp_chat: the action registry failed to look up %s", tool_name)
        return None


def _anthropic_tool_schema() -> list[dict[str, Any]]:
    """Every tool the model may call, in Anthropic's shape: the read tools, then the proposal tools."""
    return [*TOOL_DEFINITIONS, *_proposal_tools(openai_shape=False)]


def _openai_tool_schema() -> list[dict[str, Any]]:
    """The same tools as :func:`_anthropic_tool_schema`, as OpenAI ``function`` entries.

    Returns:
        The tool schema as OpenAI ``function`` entries. One builder shared by
        every provider on that wire protocol, so admitting a provider cannot
        quietly hand it a different set of tools.
    """
    read_tools = [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t["description"],
                "parameters": t["input_schema"],
            },
        }
        for t in TOOL_DEFINITIONS
    ]
    return [*read_tools, *_proposal_tools(openai_shape=True)]


@dataclass(frozen=True)
class _TurnContext:
    """What the prompt may say about the person's screen, resolved on the server.

    ``project_id`` is set only for a project the person can open, so the
    project's name and currency never reach the prompt for anyone else.
    """

    project_id: uuid.UUID | None = None
    project_name: str | None = None
    project_currency: str | None = None
    route: str | None = None
    locale: str | None = None


class ERPChatService:
    """Orchestrates AI chat with tool-calling over SSE."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        # Per-stream observability accumulator. ``_call_anthropic`` /
        # ``_call_openai`` push the per-round split here; ``_persist_messages``
        # rolls it up onto the assistant ChatMessage row so we have the
        # T8 dashboard's token/cache/latency signal without storing one
        # ChatMessage per provider call.
        self._last_turn: dict[str, Any] = {
            "tokens_input": 0,
            "tokens_output": 0,
            "cache_hit": None,
            "latency_ms": 0,
        }
        # The system prompts of this turn. ``stream_response`` appends the
        # request's context block (date, language, open project, page); a
        # provider call made outside a turn sends the bare prompts.
        self._system_prompt = SYSTEM_PROMPT
        self._system_prompt_no_tools = SYSTEM_PROMPT_NO_TOOLS

    def _record_turn_metrics(
        self,
        *,
        tokens_in: int,
        tokens_out: int,
        cache_hit: bool,
        latency_ms: int,
    ) -> None:
        """Accumulate per-round metrics onto the in-flight assistant turn.

        Multi-round agent loops produce several provider calls per assistant
        message; we sum tokens + latency and OR the cache-hit signal so a
        single round serving from cache marks the whole turn as a hit.
        """
        self._last_turn["tokens_input"] = (self._last_turn.get("tokens_input") or 0) + tokens_in
        self._last_turn["tokens_output"] = (self._last_turn.get("tokens_output") or 0) + tokens_out
        prior_hit = self._last_turn.get("cache_hit")
        if cache_hit:
            self._last_turn["cache_hit"] = True
        elif prior_hit is None:
            # First round reported a definite miss - record it; later True
            # wins via the branch above.
            self._last_turn["cache_hit"] = False
        self._last_turn["latency_ms"] = (self._last_turn.get("latency_ms") or 0) + latency_ms

    # ── Session management ───────────────────────────────────────────────

    async def get_or_create_session(
        self, user_id: str, session_id: uuid.UUID | None, project_id: uuid.UUID | None
    ) -> ChatSession:
        """Get an existing chat session or create a new one."""
        if session_id:
            stmt = select(ChatSession).where(ChatSession.id == session_id, ChatSession.user_id == uuid.UUID(user_id))
            result = await self.session.execute(stmt)
            chat_session = result.scalar_one_or_none()
            if chat_session:
                return chat_session

        # Create new session. Wrap flush() in asyncio.shield() - when the
        # caller is an SSE streaming endpoint, Starlette's BaseHTTPMiddleware
        # can cancel the request task between chunks and kill the in-flight
        # INSERT mid-flush. shield() keeps the DB write atomic from the
        # engine's perspective.
        chat_session = ChatSession(
            user_id=uuid.UUID(user_id),
            project_id=project_id,
            title="New Chat",
        )
        self.session.add(chat_session)
        await asyncio.shield(self.session.flush())
        return chat_session

    async def list_sessions(self, user_id: str, limit: int = 20) -> tuple[list[ChatSession], int]:
        """List chat sessions for a user, newest first."""
        uid = uuid.UUID(user_id)
        base = select(ChatSession).where(ChatSession.user_id == uid)

        from sqlalchemy import func

        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = base.order_by(ChatSession.updated_at.desc()).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all()), total

    async def get_session_messages(self, session_id: uuid.UUID, user_id: str) -> list[ChatMessage]:
        """Get all messages for a session."""
        stmt = (
            select(ChatMessage)
            .join(ChatSession, ChatMessage.session_id == ChatSession.id)
            .where(
                ChatMessage.session_id == session_id,
                ChatSession.user_id == uuid.UUID(user_id),
            )
            .order_by(ChatMessage.created_at)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def delete_session(self, session_id: uuid.UUID, user_id: str) -> bool:
        """Delete a chat session and its messages."""
        stmt = select(ChatSession).where(ChatSession.id == session_id, ChatSession.user_id == uuid.UUID(user_id))
        result = await self.session.execute(stmt)
        chat_session = result.scalar_one_or_none()
        if not chat_session:
            return False
        await self.session.delete(chat_session)
        await self.session.flush()
        return True

    # ── AI provider resolution ───────────────────────────────────────────

    async def _resolve_ai(self, user_id: str) -> tuple[str, str, str | None]:
        """Resolve AI provider, API key, and the user's model-id override.

        ``settings.preferred_model`` stores the *provider id* (e.g.
        ``"openrouter"``), not a model name - the per-provider model the user
        actually typed in Settings > AI lives in
        ``model_overrides[provider]``. Returning that (via
        ``resolve_provider_key_model``) so the fallback path can pass it to
        ``call_ai`` is the erp_chat half of the issue #138 fix.

        Returns:
            Tuple of (provider, api_key, model_override_or_none).
        """
        from app.modules.ai.ai_client import resolve_provider_key_model
        from app.modules.ai.repository import AISettingsRepository

        repo = AISettingsRepository(self.session)
        settings = await repo.get_by_user_id(uuid.UUID(user_id))
        provider, api_key, model_override = resolve_provider_key_model(settings)
        return provider, api_key, model_override

    # ── Request context and mid-turn commits ─────────────────────────────

    async def _resolve_turn_context(self, user_id: str, request: StreamChatRequest) -> _TurnContext:
        """The page, language and open project of this request, the project checked against access.

        ``client_context.project_id`` wins over the older ``project_id`` field.
        Both are only what the browser claims, so the project goes through the
        platform's project access rule first. A project the person cannot open
        is dropped rather than refused: the chat still answers, and nothing
        about that project reaches the prompt or a new chat session row, not
        even whether it exists.
        """
        client = request.client_context
        dropped = _TurnContext(route=client.route if client else None, locale=request.locale)
        candidate = (client.project_id if client else None) or request.project_id
        if candidate is None:
            return dropped

        from app.dependencies import verify_project_access
        from app.modules.projects.models import Project

        try:
            # A savepoint, because the check swallows some lookup errors and a
            # failed statement would otherwise leave the turn's transaction
            # unusable for everything after it.
            async with self.session.begin_nested():
                await verify_project_access(candidate, user_id, self.session)
                row = (
                    await self.session.execute(select(Project.name, Project.currency).where(Project.id == candidate))
                ).one_or_none()
        except HTTPException:
            logger.info("erp_chat: project %s is not open to user %s; answering without it", candidate, user_id)
            return dropped
        except Exception:
            logger.warning("erp_chat: could not resolve project %s; answering without it", candidate, exc_info=True)
            return dropped
        if row is None:
            return dropped
        return _TurnContext(
            project_id=candidate,
            project_name=row[0],
            project_currency=row[1],
            route=dropped.route,
            locale=dropped.locale,
        )

    async def _commit_turn(self, chat_session: ChatSession) -> bool:
        """Commit what the turn wrote so far, so another request can read it now.

        A proposal must be visible to the Apply request of its card, which runs
        on another connection, as soon as the card is on screen; the stream
        otherwise commits only after its last frame. Returns False, after a
        rollback, when the commit fails.
        """
        try:
            await asyncio.shield(self.session.commit())
        except Exception:
            logger.exception("erp_chat: commit inside the turn failed")
            await self.session.rollback()
            return False
        # The stream's own session keeps its objects loaded across a commit
        # (expire_on_commit=False). One that expires them would turn the next
        # attribute read into a lazy load, which async IO cannot do.
        state = sa_inspect(chat_session, raiseerr=False)
        if state is not None and state.expired_attributes:
            await self.session.refresh(chat_session)
        return True

    async def _attach_proposals(self, batch_id: str, message_id: uuid.UUID) -> None:
        """Point this turn's proposals at the assistant message that carried them.

        In a savepoint: when it fails, the proposals stay committed and in the
        Changes list, only without their message, and the rest of the turn's
        tail still runs on a usable transaction.
        """
        try:
            async with self.session.begin_nested():
                await ChatActionService(self.session).attach_message(batch_id=batch_id, message_id=message_id)
        except Exception:
            logger.exception("erp_chat: could not attach message %s to proposal batch %s", message_id, batch_id)

    # ── Main streaming entry point ───────────────────────────────────────

    async def stream_response(self, user_id: str, request: StreamChatRequest) -> AsyncGenerator[str, None]:
        """Main SSE streaming generator.

        Yields SSE-formatted strings: session_id, tool_start, tool_result, text, done events.
        """
        try:
            # 0. Where the person is: page, language, and the open project,
            # which only counts once the access check has passed. A new chat
            # session stores that checked project, never the raw request field.
            turn = await self._resolve_turn_context(user_id, request)
            context_block = build_context_block(
                now=datetime.now(UTC),
                locale=turn.locale,
                project_id=turn.project_id,
                project_name=turn.project_name,
                project_currency=turn.project_currency,
                route=turn.route,
            )
            self._system_prompt = SYSTEM_PROMPT + context_block
            self._system_prompt_no_tools = SYSTEM_PROMPT_NO_TOOLS + context_block
            # One batch per user turn: the proposals of this turn share it, so
            # the card tray can offer "apply all" and the assistant message can
            # be attached to them once it is stored.
            batch_id = str(uuid.uuid4())
            proposals_stored = 0

            # 1. Get or create session
            chat_session = await self.get_or_create_session(user_id, request.session_id, turn.project_id)
            yield _sse("session_id", {"session_id": str(chat_session.id)})

            # 1b. Enforce per-user 24h token budget. Rate-limit handles
            # request frequency; this is the LLM-cost guardrail.
            within_budget, tokens_used_24h = await self.check_daily_token_budget(user_id)
            if not within_budget:
                logger.warning(
                    "erp_chat budget exceeded: user=%s used_24h=%d limit=%d",
                    user_id,
                    tokens_used_24h,
                    DAILY_TOKEN_BUDGET,
                )
                yield _sse(
                    "error",
                    {
                        "message": (
                            "Daily AI token budget exceeded "
                            f"({tokens_used_24h:,} / {DAILY_TOKEN_BUDGET:,}). "
                            "Try again tomorrow or contact your administrator."
                        )
                    },
                )
                yield _sse("done", {})
                return

            # 2. Build messages from history
            messages = await self._build_messages(
                chat_session.id, user_id, request.message, request.conversation_history
            )

            # 3. Resolve AI provider
            try:
                provider, api_key, preferred_model = await self._resolve_ai(user_id)
            except ValueError as exc:
                yield _sse("error", {"message": str(exc)})
                yield _sse("done", {})
                return

            # 4. Agent loop
            all_tool_calls: list[dict[str, Any]] = []
            all_tool_results: list[dict[str, Any]] = []
            assistant_text = ""
            total_tokens = 0

            for _round in range(MAX_AGENT_ROUNDS):
                try:
                    if provider == "anthropic":
                        result, tokens = await self._call_anthropic(api_key, messages, preferred_model)
                    elif provider == "openai":
                        result, tokens = await self._call_openai(api_key, messages, preferred_model)
                    elif provider in TOOL_CAPABLE_OPENAI_COMPAT:
                        result, tokens = await self._call_openai_compat_tools(
                            provider, api_key, messages, preferred_model
                        )
                    else:
                        # Fallback: no tool support - a single plain-text call.
                        # Break into the shared tail below instead of streaming
                        # and returning here, so this provider class gets the
                        # same persistence, token accounting and ``done``
                        # payload as the tool-capable ones (issue #417).
                        assistant_text, fallback_tokens = await self._call_fallback(
                            provider, api_key, request.message, preferred_model
                        )
                        total_tokens += fallback_tokens
                        break
                except ValueError as exc:
                    # Expected user-facing errors from ai_client (bad API key,
                    # rate limit, malformed image). One line at WARNING is
                    # enough - full traceback floods the journal.
                    logger.warning("AI API call refused (round %d): %s", _round, exc)
                    yield _sse("error", {"message": str(exc)})
                    yield _sse("done", {})
                    return
                except Exception as exc:
                    # Name the provider. Transport-level failures (an httpx
                    # HTTPStatusError from raise_for_status: 401 bad key, 429,
                    # 400 dead model slug) are NOT ValueError and land here, and
                    # the no-tool branch below serves 17 different providers -
                    # an unattributed "AI API error" leaves the user with no
                    # idea which of their configured providers refused.
                    logger.exception("AI API call failed (provider=%s round=%d)", provider, _round)
                    yield _sse("error", {"message": f"AI API error ({provider}): {exc}"})
                    yield _sse("done", {})
                    return

                total_tokens += tokens

                # Parse response for tool calls
                tool_calls = self._extract_tool_calls(provider, result)

                if not tool_calls:
                    # No tool calls - extract text and finish.
                    try:
                        assistant_text = self._extract_text(provider, result)
                    except ValueError as exc:
                        # The hardened reader refused a response that carries
                        # no usable text (issue #138 - a billed completion the
                        # user would otherwise see as an empty bubble). Its
                        # message names the provider and the finish reason.
                        logger.warning("AI response carried no usable text (provider=%s): %s", provider, exc)
                        if all_tool_calls:
                            # Tools already ran this turn and their results are
                            # on screen. Erroring out here would skip the shared
                            # persistence tail, so the turn would not be stored
                            # and ``done`` would carry no message_id - the exact
                            # shape issue #417 fixed. Keep the turn instead.
                            assistant_text = "I've gathered the data above. Let me know if you need further analysis."
                            break
                        # Nothing ran, so there is no turn worth keeping and the
                        # reader's message is the most useful thing we have.
                        yield _sse("error", {"message": str(exc)})
                        yield _sse("done", {})
                        return
                    break

                # Execute tools and yield events
                tool_results_for_round: list[dict[str, Any]] = []
                for tc in tool_calls:
                    tool_name = tc["name"]
                    tool_args = tc["args"]
                    tool_id = tc.get("id", str(uuid.uuid4()))

                    yield _sse("tool_start", {"tool": tool_name, "args": tool_args})

                    handler = TOOL_HANDLER_MAP.get(tool_name)
                    if _proposal_spec(tool_name) is not None:
                        # A proposal stores a pending card and writes nothing
                        # else, so it skips the manager gate below, which exists
                        # for tools that write directly. The assistant never has
                        # more rights than the person who clicks Apply; apply
                        # re-runs the REST gates. Project access is still
                        # checked in the spec's build, for the person asking.
                        tool_result = await propose_tool_result(
                            self.session,
                            tool_name=tool_name,
                            args=tool_args if isinstance(tool_args, dict) else {},
                            user_id=user_id,
                            chat_session_id=chat_session.id,
                            project_id=turn.project_id,
                            batch_id=batch_id,
                        )
                        if tool_result.get("renderer") == "action_proposal":
                            # Committed before the card reaches the screen, so
                            # its Apply request (another connection) finds it.
                            if await self._commit_turn(chat_session):
                                proposals_stored += 1
                            else:
                                tool_result = ActionConflictError(code="internal_error").to_tool_result()
                    elif handler:
                        # RBAC gate: write tools require manager+ on the
                        # referenced project. IDOR posture must be
                        # preserved - non-existent / inaccessible projects
                        # ALWAYS surface as 404-style (handler's
                        # ``_require_project_access`` does this) so we
                        # never leak project existence by returning the
                        # role-denied card to a non-tenant. Order:
                        #   1. IDOR check (project exists + accessible).
                        #   2. Role check (manager+ for write tools).
                        # 1 fails → handler's 404-shaped error result.
                        # 2 fails → manager_permission_required card.
                        # No handler in TOOL_HANDLER_MAP writes today; the gate
                        # stays as the fail-closed default for one that would.
                        tool_result = None
                        is_write = TOOL_PERMISSIONS.get(tool_name, "read") == "write"

                        if is_write:
                            project_id = _extract_project_id(tool_name, tool_args)
                            if project_id is not None:
                                try:
                                    await _require_project_access(
                                        self.session,
                                        project_id,
                                        user_id,
                                    )
                                except ToolAuthError as _te:
                                    # 404 posture - never reach the role check.
                                    tool_result = _auth_error(str(_te))
                                except Exception:
                                    logger.exception(
                                        "IDOR check failed for %s",
                                        tool_name,
                                    )
                            if tool_result is None:
                                # Project accessible (or no project_id -
                                # then the role gate alone applies). Check
                                # manager+.
                                try:
                                    await check_tool_permission(
                                        self.session,
                                        tool_name,
                                        tool_args,
                                        user_id,
                                    )
                                except ToolPermissionDenied:
                                    tool_result = manager_permission_error_result()
                                except Exception:
                                    logger.exception(
                                        "check_tool_permission failed for %s",
                                        tool_name,
                                    )
                                    # Fail-closed on lookup error to avoid
                                    # accidentally elevating a denied call.
                                    tool_result = manager_permission_error_result()

                        if tool_result is None:
                            try:
                                tool_result = await handler(
                                    self.session,
                                    tool_args,
                                    user_id,
                                )
                            except Exception as exc:
                                logger.exception("Tool handler %s failed", tool_name)
                                tool_result = {
                                    "renderer": "error",
                                    "data": {"error": str(exc)},
                                    "summary": f"Tool error: {exc}",
                                }
                    else:
                        tool_result = {
                            "renderer": "error",
                            "data": {"error": f"Unknown tool: {tool_name}"},
                            "summary": f"Unknown tool: {tool_name}",
                        }

                    yield _sse(
                        "tool_result",
                        {
                            "tool": tool_name,
                            "result": tool_result,
                        },
                    )

                    all_tool_calls.append({"name": tool_name, "args": tool_args, "id": tool_id})
                    all_tool_results.append(
                        {
                            "tool": tool_name,
                            "id": tool_id,
                            "result": tool_result,
                        }
                    )
                    tool_results_for_round.append(
                        {
                            "tool_name": tool_name,
                            "tool_id": tool_id,
                            "result": tool_result,
                        }
                    )

                # Add tool results to messages for next round
                messages = self._append_tool_results(provider, messages, result, tool_results_for_round)
            else:
                # Hit max rounds - extract whatever text we have. A refusal
                # from the hardened reader is not fatal here: the tool results
                # are already on screen, so fall through to the summary line
                # rather than erroring out a turn that produced data.
                assistant_text = ""
                if result:  # type: ignore[possibly-undefined]
                    try:
                        assistant_text = self._extract_text(provider, result)
                    except ValueError as exc:
                        logger.warning("No text in the final round (provider=%s): %s", provider, exc)
                if not assistant_text:
                    assistant_text = "I've gathered the data above. Let me know if you need further analysis."

            # 5. Stream text to client in chunks for smooth UX
            if assistant_text:
                chunk_size = 50
                for i in range(0, len(assistant_text), chunk_size):
                    yield _sse("text", {"content": assistant_text[i : i + chunk_size]})

            # 6. Persist messages - shield so middleware cancellation can't
            # tear down the DB write mid-flush. Returns the persisted
            # assistant ChatMessage id so the client can reconcile its
            # optimistic bubble id and submit per-turn thumbs feedback that
            # actually lands (the T8 dashboard depends on this).
            assistant_message_id = await asyncio.shield(
                self._persist_messages(
                    chat_session,
                    user_id,
                    request.message,
                    assistant_text,
                    all_tool_calls,
                    all_tool_results,
                    total_tokens,
                )
            )
            if proposals_stored and assistant_message_id is not None:
                await self._attach_proposals(batch_id, assistant_message_id)

            # Structured cost log - one INFO line per chat turn carries the
            # full per-turn observability split. Operators tail this for
            # billing / abuse-detection without joining DB tables.
            logger.info(
                "erp_chat.turn user=%s session=%s project=%s provider=%s "
                "tokens_in=%d tokens_out=%d total=%d cache_hit=%s latency_ms=%d "
                "tool_calls=%d proposals=%d",
                user_id,
                str(chat_session.id),
                str(chat_session.project_id) if chat_session.project_id else "-",
                provider,
                self._last_turn.get("tokens_input") or 0,
                self._last_turn.get("tokens_output") or 0,
                total_tokens,
                self._last_turn.get("cache_hit"),
                self._last_turn.get("latency_ms") or 0,
                len(all_tool_calls),
                proposals_stored,
            )

            # Auto-title from first user message
            if chat_session.title == "New Chat" and request.message:
                title = request.message[:80]
                if len(request.message) > 80:
                    title += "..."
                chat_session.title = title
                await asyncio.shield(self.session.flush())

            if proposals_stored:
                # The proposals themselves were committed as they were made.
                # This commits the stored messages and the link to them before
                # ``done``, so a card the person applies right after the turn
                # already names its message.
                await self._commit_turn(chat_session)

            yield _sse(
                "done",
                {
                    "session_id": str(chat_session.id),
                    "tokens": total_tokens,
                    # Persisted assistant-turn id. The client swaps its
                    # optimistic bubble id for this so thumbs feedback POSTs
                    # against a real row instead of 404-ing on a client UUID.
                    "message_id": (str(assistant_message_id) if assistant_message_id else None),
                },
            )

        except Exception as exc:
            logger.exception("stream_response fatal error")
            yield _sse("error", {"message": f"Internal error: {exc}"})
            yield _sse("done", {})

    # ── Message building ─────────────────────────────────────────────────

    async def _build_messages(
        self,
        session_id: uuid.UUID,
        user_id: str,
        new_message: str,
        conversation_history: list[dict[str, Any]] | None,
    ) -> list[dict[str, Any]]:
        """Build the messages array for the AI call.

        Uses conversation_history if provided (from frontend), otherwise loads
        the last N messages from DB.
        """
        messages: list[dict[str, Any]] = []

        if conversation_history:
            # Hardening: client-supplied history is untrusted. Cap count,
            # per-message length, and reject roles outside the allow-list
            # so a malicious client can't smuggle a fake "system" turn or
            # blow the context window with a 1 MB message.
            trimmed = list(conversation_history)[-MAX_HISTORY_MESSAGES:]
            for msg in trimmed:
                if not isinstance(msg, dict):
                    continue
                role = msg.get("role", "user")
                content = msg.get("content", "")
                if role not in ALLOWED_HISTORY_ROLES or not content:
                    continue
                if not isinstance(content, str):
                    content = str(content)
                if len(content) > MAX_HISTORY_MESSAGE_CHARS:
                    content = content[:MAX_HISTORY_MESSAGE_CHARS] + "…[truncated]"
                messages.append({"role": role, "content": content})
        else:
            # Load last messages from DB
            db_messages = await self.get_session_messages(session_id, user_id)
            for msg in db_messages[-MAX_HISTORY_MESSAGES:]:
                if msg.role in ALLOWED_HISTORY_ROLES and msg.content:
                    content = msg.content
                    if len(content) > MAX_HISTORY_MESSAGE_CHARS:
                        content = content[:MAX_HISTORY_MESSAGE_CHARS] + "…[truncated]"
                    messages.append({"role": msg.role, "content": content})

        # Add new user message (capped)
        new_capped = new_message
        if len(new_capped) > MAX_HISTORY_MESSAGE_CHARS:
            new_capped = new_capped[:MAX_HISTORY_MESSAGE_CHARS] + "…[truncated]"
        messages.append({"role": "user", "content": new_capped})
        return messages

    # ── Per-user daily token budget ──────────────────────────────────────

    async def check_daily_token_budget(self, user_id: str) -> tuple[bool, int]:
        """Return ``(within_budget, tokens_used_24h)`` for a user.

        Counts persisted assistant-message ``tokens_used`` over the last
        24h. Cheap single-row aggregate on an indexed column. The caller
        is expected to short-circuit with a user-visible error when the
        budget is exceeded - see :meth:`stream_response`.
        """
        try:
            uid = uuid.UUID(user_id)
        except (TypeError, ValueError):
            return True, 0
        cutoff = datetime.now(UTC) - timedelta(hours=24)
        stmt = (
            select(func.coalesce(func.sum(ChatMessage.tokens_used), 0))
            .join(ChatSession, ChatMessage.session_id == ChatSession.id)
            .where(
                ChatSession.user_id == uid,
                ChatMessage.role == "assistant",
                ChatMessage.created_at >= cutoff,
            )
        )
        used = int((await self.session.execute(stmt)).scalar_one() or 0)
        return used < DAILY_TOKEN_BUDGET, used

    # ── Anthropic API ────────────────────────────────────────────────────

    async def _call_anthropic(
        self,
        api_key: str,
        messages: list[dict[str, Any]],
        preferred_model: str | None,
    ) -> tuple[dict[str, Any], int]:
        """Call Anthropic Messages API with tools.

        Side effect (T8 observability): the per-turn token split, prompt-cache
        hit flag, and wall-clock latency are stashed on ``self._last_turn``
        so :meth:`_persist_messages` can write them to ``ChatMessage``
        without changing the existing return-tuple shape every caller relies
        on.
        """
        from app.modules.ai.ai_client import resolve_anthropic_model

        # preferred_model is what Settings > AI holds for Anthropic: the
        # dropdown alias ("claude-sonnet") unless the user typed a model id.
        # The alias is not an API id, so it maps to one the way
        # ``ai_client.call_anthropic`` maps it; a typed id passes verbatim and
        # an empty one falls back to the default (issue #138).
        model = resolve_anthropic_model(preferred_model)

        t0 = time.perf_counter()
        async with httpx.AsyncClient(timeout=AI_TIMEOUT) as client:
            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": model,
                    "max_tokens": 4096,
                    "system": self._system_prompt,
                    "messages": messages,
                    "tools": _anthropic_tool_schema(),
                },
            )
            resp.raise_for_status()
            data = resp.json()
        latency_ms = int((time.perf_counter() - t0) * 1000)

        usage = data.get("usage", {})
        tokens_in = int(usage.get("input_tokens", 0) or 0)
        tokens_out = int(usage.get("output_tokens", 0) or 0)
        # Anthropic reports cache reads on ``cache_read_input_tokens``;
        # any non-zero value means at least part of the prompt was served
        # from the prefix cache.
        cache_read = int(usage.get("cache_read_input_tokens", 0) or 0)
        self._record_turn_metrics(
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cache_hit=cache_read > 0,
            latency_ms=latency_ms,
        )
        return data, tokens_in + tokens_out

    # ── OpenAI API ───────────────────────────────────────────────────────

    async def _call_openai(
        self,
        api_key: str,
        messages: list[dict[str, Any]],
        preferred_model: str | None,
    ) -> tuple[dict[str, Any], int]:
        """Call OpenAI ChatCompletions API with tools.

        Side effect (T8 observability) - see :meth:`_call_anthropic`.
        """
        from app.modules.ai.ai_client import OPENAI_MODEL

        # Honor the user's per-provider model id override verbatim (issue
        # #138); fall back to the built-in default only when unset.
        model = preferred_model.strip() if preferred_model and preferred_model.strip() else OPENAI_MODEL

        # Convert Anthropic tool format to OpenAI format
        openai_tools = _openai_tool_schema()

        openai_messages = [{"role": "system", "content": self._system_prompt}] + messages

        t0 = time.perf_counter()
        async with httpx.AsyncClient(timeout=AI_TIMEOUT) as client:
            resp = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "messages": openai_messages,
                    "tools": openai_tools,
                    "max_tokens": 4096,
                },
            )
            resp.raise_for_status()
            data = resp.json()
        latency_ms = int((time.perf_counter() - t0) * 1000)

        usage = data.get("usage", {})
        tokens_in = int(usage.get("prompt_tokens", 0) or 0)
        tokens_out = int(usage.get("completion_tokens", 0) or 0)
        total = int(usage.get("total_tokens", tokens_in + tokens_out) or 0)
        # OpenAI surfaces cache reads inside ``prompt_tokens_details``.
        details = usage.get("prompt_tokens_details") or {}
        cached = int(details.get("cached_tokens", 0) or 0)
        self._record_turn_metrics(
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cache_hit=cached > 0,
            latency_ms=latency_ms,
        )
        return data, total

    # ── OpenAI-compatible providers, with tools ──────────────────────────

    async def _call_openai_compat_tools(
        self,
        provider: str,
        api_key: str,
        messages: list[dict[str, Any]],
        preferred_model: str | None,
    ) -> tuple[dict[str, Any], int]:
        """Call an OpenAI-compatible provider with a tool schema (issue #424).

        Routed through ``ai_client.call_ai_tools`` instead of posting here, so
        this path keeps the two protections that live on the plain-text one and
        would otherwise be silently lost by moving a provider off it: the
        dead-slug self-heal (issue #148, which matters acutely for OpenRouter's
        dated slugs) and the hardened response reader (issue #138).

        ``SYSTEM_PROMPT_NO_TOOLS`` travels with the request as the prompt for
        the degraded retry: a provider that refuses the schema must not be left
        holding a prompt that advertises tools (issue #417).

        Args:
            provider: Provider id, one of :data:`TOOL_CAPABLE_OPENAI_COMPAT`.
            api_key: Provider API key.
            messages: Chat messages without the system turn.
            preferred_model: The user's per-provider model id override.

        Returns:
            Tuple of (raw response body, tokens_used).

        Side effect (T8 observability) - see :meth:`_call_anthropic`.
        """
        from app.modules.ai.ai_client import call_ai_tools, default_model_for

        # Honor the user's per-provider model id override verbatim (issue
        # #138); fall back to the provider's built-in default only when unset.
        model = preferred_model.strip() if preferred_model and preferred_model.strip() else default_model_for(provider)

        t0 = time.perf_counter()
        data, total = await call_ai_tools(
            provider=provider,
            api_key=api_key,
            system=self._system_prompt,
            system_without_tools=self._system_prompt_no_tools,
            messages=messages,
            tools=_openai_tool_schema(),
            model=model,
            max_tokens=4096,
        )
        latency_ms = int((time.perf_counter() - t0) * 1000)

        usage = data.get("usage") or {}
        tokens_in = int(usage.get("prompt_tokens", 0) or 0)
        tokens_out = int(usage.get("completion_tokens", 0) or 0)
        # OpenAI surfaces cache reads inside ``prompt_tokens_details``; the
        # compatible providers that report it use the same key.
        details = usage.get("prompt_tokens_details") or {}
        cached = int(details.get("cached_tokens", 0) or 0)
        self._record_turn_metrics(
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cache_hit=cached > 0,
            latency_ms=latency_ms,
        )
        return data, int(total or tokens_in + tokens_out)

    # ── Fallback (non-tool providers) ────────────────────────────────────

    async def _call_fallback(
        self,
        provider: str,
        api_key: str,
        message: str,
        model: str | None = None,
    ) -> tuple[str, int]:
        """Call a provider without tool support - return (text, tokens).

        ``model`` is the user's per-provider model id override (issue #138):
        without it, providers like OpenRouter silently used the hardcoded
        default model regardless of what the user picked in Settings > AI.

        Issue #417: this used to be an SSE generator that emitted its own
        ``text``/``error`` frames, which forced the caller to return early and
        so skipped persistence and token accounting. Returning the pair lets
        the caller reuse the one shared tail that every provider goes through.
        Exceptions propagate for the same reason - the caller already turns
        them into ``error`` + ``done`` frames exactly as it does for the
        Anthropic and OpenAI branches.

        ``SYSTEM_PROMPT_NO_TOOLS`` is deliberate: no tool schema goes on the
        wire here, so the model must not be told it has tools.
        """
        from app.modules.ai.ai_client import call_ai

        text, tokens = await call_ai(
            provider=provider,
            api_key=api_key,
            system=self._system_prompt_no_tools,
            prompt=message,
            model=model,
        )
        # No ``_record_turn_metrics`` call: ``call_ai`` reports only a total,
        # so the input/output split and the cache flag are genuinely unknown
        # here. ``_persist_messages`` maps the zeros to NULL rather than
        # recording a split we did not measure.
        return text, int(tokens or 0)

    # ── Response parsing ─────────────────────────────────────────────────

    def _extract_tool_calls(self, provider: str, result: dict[str, Any]) -> list[dict[str, Any]]:
        """Extract tool calls from AI response."""
        calls: list[dict[str, Any]] = []

        if provider == "anthropic":
            for block in result.get("content", []):
                if block.get("type") == "tool_use":
                    calls.append(
                        {
                            "id": block.get("id", str(uuid.uuid4())),
                            "name": block["name"],
                            "args": block.get("input", {}),
                        }
                    )

        elif provider in OPENAI_WIRE_PROVIDERS:
            # ``or [{}]`` rather than a dict default: an HTTP-200 carrying an
            # EMPTY choices array is one of the shapes issue #138 documents,
            # and a default only applies when the key is absent - indexing []
            # would raise IndexError before the reader below could name what
            # actually went wrong.
            choices = result.get("choices") or [{}]
            msg = choices[0].get("message") or {}
            for tc in msg.get("tool_calls", []) or []:
                func = tc.get("function", {})
                try:
                    args = json.loads(func.get("arguments", "{}"))
                except json.JSONDecodeError:
                    args = {}
                calls.append(
                    {
                        "id": tc.get("id", str(uuid.uuid4())),
                        "name": func.get("name", ""),
                        "args": args,
                    }
                )

        return calls

    def _extract_text(self, provider: str, result: dict[str, Any]) -> str:
        """Extract text content from an AI response.

        Args:
            provider: The provider that produced ``result``.
            result: The raw response body.

        Returns:
            The assistant text, or an empty string for a provider that does
            not reach this path.

        Raises:
            ValueError: When an OpenAI-shaped response carries no usable text.
                Deliberate: the naive read this replaced returned "" for an
                in-body error, an empty ``choices`` array, a list-typed
                ``content`` and a reasoning-only reply alike, which is issue
                #138's "billed tokens, no response" symptom. Callers decide
                whether that is fatal for the turn.
        """
        if provider == "anthropic":
            parts = []
            for block in result.get("content", []):
                if block.get("type") == "text":
                    parts.append(block.get("text", ""))
            return "\n".join(parts)

        elif provider in OPENAI_WIRE_PROVIDERS:
            # Reuse ai_client's hardened reader rather than re-implementing
            # it. It is the one that survived issue #138, and the tool path is
            # where a list-typed ``content`` shows up most.
            from app.modules.ai.ai_client import _extract_openai_message_text

            return _extract_openai_message_text(provider, result)

        return ""

    def _append_tool_results(
        self,
        provider: str,
        messages: list[dict[str, Any]],
        ai_result: dict[str, Any],
        tool_results: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Append tool results to messages for the next agent loop round."""
        if provider == "anthropic":
            # Add assistant message with tool_use blocks
            messages.append({"role": "assistant", "content": ai_result.get("content", [])})

            # Add tool results (truncated so large payloads do not blow the context window)
            tool_result_blocks = []
            for tr in tool_results:
                tool_result_blocks.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": tr["tool_id"],
                        "content": json.dumps(_truncate_tool_result(_result_for_model(tr["result"])), default=str),
                    }
                )
            messages.append({"role": "user", "content": tool_result_blocks})

        elif provider in OPENAI_WIRE_PROVIDERS:
            # Add assistant message (with tool_calls). Same empty-choices
            # guard as _extract_tool_calls above.
            choices = ai_result.get("choices") or [{}]
            msg = choices[0].get("message") or {}
            messages.append(msg)

            # Add tool result messages (truncated so large payloads do not blow the context window)
            for tr in tool_results:
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tr["tool_id"],
                        "content": json.dumps(_truncate_tool_result(_result_for_model(tr["result"])), default=str),
                    }
                )

        return messages

    # ── Persistence ──────────────────────────────────────────────────────

    async def _persist_messages(
        self,
        chat_session: ChatSession,
        user_id: str,
        user_message: str,
        assistant_text: str,
        tool_calls: list[dict[str, Any]],
        tool_results: list[dict[str, Any]],
        tokens_used: int,
    ) -> uuid.UUID | None:
        """Persist user message and assistant response to the database.

        Returns the persisted assistant ``ChatMessage.id`` (or ``None`` on
        failure) so the streaming endpoint can hand it to the client for
        feedback reconciliation.
        """
        try:
            # Save user message
            user_msg = ChatMessage(
                session_id=chat_session.id,
                role="user",
                content=user_message,
            )
            self.session.add(user_msg)

            # Build renderer/renderer_data from tool results
            renderer = None
            renderer_data = None
            if tool_results:
                # Use the last non-error tool result as the primary renderer
                for tr in reversed(tool_results):
                    result = tr.get("result", {})
                    if result.get("renderer") and result.get("renderer") != "error":
                        renderer = result["renderer"]
                        renderer_data = result.get("data")
                        break

            # Save assistant message (with T8 observability split)
            assistant_msg = ChatMessage(
                session_id=chat_session.id,
                role="assistant",
                content=assistant_text or None,
                tool_calls=tool_calls if tool_calls else None,
                tool_results=tool_results if tool_results else None,
                renderer=renderer,
                renderer_data=renderer_data,
                tokens_used=tokens_used,
                tokens_input=self._last_turn.get("tokens_input") or None,
                tokens_output=self._last_turn.get("tokens_output") or None,
                cache_hit=self._last_turn.get("cache_hit"),
                latency_ms=self._last_turn.get("latency_ms") or None,
            )
            self.session.add(assistant_msg)
            await asyncio.shield(self.session.flush())

            # Publish standardized events so the vector indexer can react.
            # Best-effort - failures must never break the chat persistence
            # path.  We pass the project_id from the parent session so the
            # handler doesn't have to do an extra lookup.
            try:
                from app.core.events import event_bus

                project_id = str(chat_session.project_id) if getattr(chat_session, "project_id", None) else None
                for msg, role in (
                    (user_msg, "user"),
                    (assistant_msg, "assistant"),
                ):
                    if msg.id is None:
                        continue
                    event_bus.publish_detached(
                        "erp_chat.message.created",
                        {
                            "message_id": str(msg.id),
                            "session_id": str(chat_session.id),
                            "project_id": project_id,
                            "role": role,
                        },
                        source_module="oe_erp_chat",
                    )
            except Exception:
                logger.debug(
                    "Failed to publish erp_chat.message.created events",
                    exc_info=True,
                )
            return assistant_msg.id
        except Exception:
            logger.exception("Failed to persist chat messages")
            return None

    # ── T8: Per-turn feedback + admin observability ─────────────────────

    async def submit_feedback(
        self,
        message_id: uuid.UUID,
        user_id: str,
        rating: int,
        comment: str | None = None,
    ) -> ChatTurnFeedback:
        """Upsert a thumbs up/down feedback row for ``(message_id, user_id)``.

        Re-submitting on the same pair flips the rating in place - there
        is at most one feedback row per user per message.

        Raises:
            ValueError: rating is outside {-1, +1}.
            LookupError: ``message_id`` does not exist or the requesting
                user doesn't own its parent session (IDOR guard).
        """
        if rating not in (-1, 1):
            raise ValueError("rating must be -1 or +1")

        try:
            uid = uuid.UUID(user_id)
        except (TypeError, ValueError) as exc:
            raise ValueError("user_id is not a valid UUID") from exc

        # IDOR guard: the message must belong to a session owned by the
        # current user. Treat ownership mismatch as 404 - same convention as
        # the ``/messages/{id}/similar`` endpoint.
        from sqlalchemy.orm import selectinload as _selectinload

        msg_stmt = select(ChatMessage).options(_selectinload(ChatMessage.session)).where(ChatMessage.id == message_id)
        message = (await self.session.execute(msg_stmt)).scalar_one_or_none()
        if message is None or message.session is None:
            raise LookupError("Chat message not found")
        if str(message.session.user_id) != str(uid):
            raise LookupError("Chat message not found")

        # Feedback is a thumbs up/down on an assistant turn only - rating a
        # user prompt (or a tool/system row) is meaningless and would poison
        # the admin observability rollups (top_negative_prompts joins assume
        # the rated message is the assistant reply).
        if message.role != "assistant":
            raise ValueError("Feedback can only be submitted on assistant messages")

        # Look up an existing row first; if present, flip the rating.
        stmt = select(ChatTurnFeedback).where(
            ChatTurnFeedback.message_id == message_id,
            ChatTurnFeedback.user_id == uid,
        )
        row = (await self.session.execute(stmt)).scalar_one_or_none()
        if row is not None:
            row.rating = rating
            row.comment = comment
            await asyncio.shield(self.session.flush())
            return row

        row = ChatTurnFeedback(
            message_id=message_id,
            user_id=uid,
            rating=rating,
            comment=comment,
        )
        self.session.add(row)
        try:
            await asyncio.shield(self.session.flush())
        except IntegrityError:
            # Lost a race against a concurrent submit - fetch + update.
            await self.session.rollback()
            row = (await self.session.execute(stmt)).scalar_one()
            row.rating = rating
            row.comment = comment
            await asyncio.shield(self.session.flush())
        return row

    async def get_admin_stats(self, window_days: int = 30) -> dict[str, Any]:
        """Roll up T8 observability metrics over the last ``window_days``.

        Counts only assistant messages - user prompts are counted via the
        ``top_negative_prompts`` join. ``feedback_rate_pct`` is the
        percentage of assistant messages that received any rating (up OR
        down). ``cache_hit_rate_pct`` is computed over assistant messages
        with a non-NULL ``cache_hit`` so old un-instrumented rows don't
        skew the denominator to zero.
        """
        window = max(1, int(window_days))
        cutoff = datetime.now(UTC) - timedelta(days=window)

        # ── Aggregate counts ────────────────────────────────────────────
        assistant_q = select(func.count(ChatMessage.id)).where(
            ChatMessage.role == "assistant",
            ChatMessage.created_at >= cutoff,
        )
        total_messages = int((await self.session.execute(assistant_q)).scalar_one() or 0)

        tokens_q = select(
            func.coalesce(func.sum(ChatMessage.tokens_input), 0),
            func.coalesce(func.sum(ChatMessage.tokens_output), 0),
        ).where(
            ChatMessage.role == "assistant",
            ChatMessage.created_at >= cutoff,
        )
        tin, tout = (await self.session.execute(tokens_q)).one()

        # Cache hit rate - denominator = rows with non-NULL cache_hit.
        cache_q = select(
            func.coalesce(
                func.sum(case((ChatMessage.cache_hit.is_(True), 1), else_=0)),
                0,
            ),
            func.coalesce(
                func.sum(case((ChatMessage.cache_hit.isnot(None), 1), else_=0)),
                0,
            ),
        ).where(
            ChatMessage.role == "assistant",
            ChatMessage.created_at >= cutoff,
        )
        cache_hits, cache_denom = (await self.session.execute(cache_q)).one()
        cache_hits = int(cache_hits or 0)
        cache_denom = int(cache_denom or 0)
        cache_hit_rate_pct = round(100.0 * cache_hits / cache_denom, 2) if cache_denom else 0.0

        # ── Feedback split ──────────────────────────────────────────────
        fb_q = (
            select(
                func.coalesce(
                    func.sum(case((ChatTurnFeedback.rating == 1, 1), else_=0)),
                    0,
                ),
                func.coalesce(
                    func.sum(case((ChatTurnFeedback.rating == -1, 1), else_=0)),
                    0,
                ),
                func.count(func.distinct(ChatTurnFeedback.message_id)),
            )
            .join(
                ChatMessage,
                ChatTurnFeedback.message_id == ChatMessage.id,
            )
            .where(
                ChatMessage.role == "assistant",
                ChatMessage.created_at >= cutoff,
            )
        )
        thumbs_up, thumbs_down, rated_messages = (await self.session.execute(fb_q)).one()
        thumbs_up = int(thumbs_up or 0)
        thumbs_down = int(thumbs_down or 0)
        rated_messages = int(rated_messages or 0)
        feedback_rate_pct = round(100.0 * rated_messages / total_messages, 2) if total_messages else 0.0

        # ── Top negative prompts ───────────────────────────────────────
        # The user-prompt that immediately *precedes* a thumbs-down
        # assistant turn is what we surface. We join the feedback row to
        # the assistant message, then look up the preceding user message
        # in the same session.
        neg_assistant = (
            select(
                ChatTurnFeedback.message_id.label("assistant_id"),
                func.count(ChatTurnFeedback.id).label("downs"),
            )
            .where(ChatTurnFeedback.rating == -1)
            .group_by(ChatTurnFeedback.message_id)
            .subquery()
        )
        neg_q = (
            select(
                ChatMessage.id,
                ChatMessage.session_id,
                ChatMessage.created_at,
                neg_assistant.c.downs,
            )
            .join(neg_assistant, neg_assistant.c.assistant_id == ChatMessage.id)
            .where(
                ChatMessage.role == "assistant",
                ChatMessage.created_at >= cutoff,
            )
            .order_by(neg_assistant.c.downs.desc(), ChatMessage.created_at.desc())
            .limit(5)
        )
        neg_rows = (await self.session.execute(neg_q)).all()
        top_negative_prompts: list[dict[str, Any]] = []
        for asst_id, sess_id, ts, downs in neg_rows:
            # Find the most-recent user message in the same session that
            # precedes this assistant message.
            preceding = (
                await self.session.execute(
                    select(ChatMessage)
                    .where(
                        ChatMessage.session_id == sess_id,
                        ChatMessage.role == "user",
                        ChatMessage.created_at <= ts,
                    )
                    .order_by(ChatMessage.created_at.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            snippet = ""
            if preceding is not None and preceding.content:
                snippet = preceding.content.strip()[:120]
            top_negative_prompts.append(
                {
                    "snippet": snippet or "(no prompt text)",
                    "thumbs_down": int(downs or 0),
                    "message_id": asst_id,
                }
            )

        # ── Daily breakdown ─────────────────────────────────────────────
        # We use a portable Python-side rollup rather than func.date() so
        # the same SQL works on SQLite + Postgres without dialect branches.
        daily: dict[str, dict[str, int]] = {}
        # seed every day in the window so the chart isn't gappy
        for offset in range(window):
            day = (datetime.now(UTC) - timedelta(days=window - 1 - offset)).date().isoformat()
            daily[day] = {
                "messages": 0,
                "thumbs_up": 0,
                "thumbs_down": 0,
                "tokens": 0,
            }

        msgs_q = select(
            ChatMessage.created_at,
            func.coalesce(ChatMessage.tokens_input, 0) + func.coalesce(ChatMessage.tokens_output, 0),
        ).where(
            ChatMessage.role == "assistant",
            ChatMessage.created_at >= cutoff,
        )
        for created_at, total_t in (await self.session.execute(msgs_q)).all():
            if created_at is None:
                continue
            d = created_at.date().isoformat()
            bucket = daily.setdefault(
                d,
                {"messages": 0, "thumbs_up": 0, "thumbs_down": 0, "tokens": 0},
            )
            bucket["messages"] += 1
            bucket["tokens"] += int(total_t or 0)

        fb_daily_q = (
            select(ChatMessage.created_at, ChatTurnFeedback.rating)
            .join(
                ChatTurnFeedback,
                ChatTurnFeedback.message_id == ChatMessage.id,
            )
            .where(
                ChatMessage.role == "assistant",
                ChatMessage.created_at >= cutoff,
            )
        )
        for created_at, rating in (await self.session.execute(fb_daily_q)).all():
            if created_at is None:
                continue
            d = created_at.date().isoformat()
            bucket = daily.setdefault(
                d,
                {"messages": 0, "thumbs_up": 0, "thumbs_down": 0, "tokens": 0},
            )
            if rating == 1:
                bucket["thumbs_up"] += 1
            elif rating == -1:
                bucket["thumbs_down"] += 1

        daily_breakdown = [{"date": d, **values} for d, values in sorted(daily.items())]

        return {
            "window_days": window,
            "total_messages": total_messages,
            "total_thumbs_up": thumbs_up,
            "total_thumbs_down": thumbs_down,
            "feedback_rate_pct": feedback_rate_pct,
            "total_tokens_input": int(tin or 0),
            "total_tokens_output": int(tout or 0),
            "cache_hit_rate_pct": cache_hit_rate_pct,
            "top_negative_prompts": top_negative_prompts,
            "daily_breakdown": daily_breakdown,
        }
