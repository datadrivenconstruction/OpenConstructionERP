"""ERP Chat service — agent loop with SSE streaming and tool calling.

Supports Anthropic and OpenAI APIs with tool-calling (function calling).
Other providers fall back to plain text via the shared ai_client.call_ai().
"""

import json
import logging
import uuid
from collections.abc import AsyncGenerator
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.erp_chat.models import ChatMessage, ChatSession
from app.modules.erp_chat.prompts import SYSTEM_PROMPT
from app.modules.erp_chat.schemas import StreamChatRequest
from app.modules.erp_chat.tools import TOOL_DEFINITIONS, TOOL_HANDLER_MAP

logger = logging.getLogger(__name__)

# Maximum tool-calling rounds to prevent infinite loops
MAX_AGENT_ROUNDS = 5

# Timeout for AI API calls
AI_TIMEOUT = 120.0


def _sse(event_type: str, data: dict[str, Any]) -> str:
    """Format a Server-Sent Event string."""
    return f"event: {event_type}\ndata: {json.dumps(data)}\n\n"


class ERPChatService:
    """Orchestrates AI chat with tool-calling over SSE."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ── Session management ───────────────────────────────────────────────

    async def get_or_create_session(
        self, user_id: str, session_id: uuid.UUID | None, project_id: uuid.UUID | None
    ) -> ChatSession:
        """Get an existing chat session or create a new one."""
        if session_id:
            stmt = select(ChatSession).where(
                ChatSession.id == session_id, ChatSession.user_id == uuid.UUID(user_id)
            )
            result = await self.session.execute(stmt)
            chat_session = result.scalar_one_or_none()
            if chat_session:
                return chat_session

        # Create new session
        chat_session = ChatSession(
            user_id=uuid.UUID(user_id),
            project_id=project_id,
            title="New Chat",
        )
        self.session.add(chat_session)
        await self.session.flush()
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

    async def get_session_messages(
        self, session_id: uuid.UUID, user_id: str
    ) -> list[ChatMessage]:
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
        stmt = select(ChatSession).where(
            ChatSession.id == session_id, ChatSession.user_id == uuid.UUID(user_id)
        )
        result = await self.session.execute(stmt)
        chat_session = result.scalar_one_or_none()
        if not chat_session:
            return False
        await self.session.delete(chat_session)
        await self.session.flush()
        return True

    # ── AI provider resolution ───────────────────────────────────────────

    async def _resolve_ai(self, user_id: str) -> tuple[str, str, str | None]:
        """Resolve AI provider, API key, and optional model.

        Returns:
            Tuple of (provider, api_key, model_or_none).
        """
        from app.modules.ai.ai_client import resolve_provider_and_key
        from app.modules.ai.repository import AISettingsRepository

        repo = AISettingsRepository(self.session)
        settings = await repo.get_by_user_id(uuid.UUID(user_id))
        provider, api_key = resolve_provider_and_key(settings)
        model = getattr(settings, "preferred_model", None) if settings else None
        return provider, api_key, model

    # ── Main streaming entry point ───────────────────────────────────────

    async def stream_response(
        self, user_id: str, request: StreamChatRequest
    ) -> AsyncGenerator[str, None]:
        """Main SSE streaming generator.

        Yields SSE-formatted strings: session_id, tool_start, tool_result, text, done events.
        """
        try:
            # 1. Get or create session
            chat_session = await self.get_or_create_session(
                user_id, request.session_id, request.project_id
            )
            yield _sse("session_id", {"session_id": str(chat_session.id)})

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
                        result, tokens = await self._call_anthropic(
                            api_key, messages, preferred_model
                        )
                    elif provider == "openai":
                        result, tokens = await self._call_openai(
                            api_key, messages, preferred_model
                        )
                    else:
                        # Fallback: no tool support — plain text
                        async for chunk in self._call_fallback(
                            provider, api_key, request.message
                        ):
                            yield chunk
                        yield _sse("done", {})
                        return
                except Exception as exc:
                    logger.exception("AI API call failed (round %d)", _round)
                    yield _sse("error", {"message": f"AI API error: {exc}"})
                    yield _sse("done", {})
                    return

                total_tokens += tokens

                # Parse response for tool calls
                tool_calls = self._extract_tool_calls(provider, result)

                if not tool_calls:
                    # No tool calls — extract text and finish
                    assistant_text = self._extract_text(provider, result)
                    break

                # Execute tools and yield events
                tool_results_for_round: list[dict[str, Any]] = []
                for tc in tool_calls:
                    tool_name = tc["name"]
                    tool_args = tc["args"]
                    tool_id = tc.get("id", str(uuid.uuid4()))

                    yield _sse("tool_start", {"tool": tool_name, "args": tool_args})

                    handler = TOOL_HANDLER_MAP.get(tool_name)
                    if handler:
                        try:
                            tool_result = await handler(self.session, tool_args, user_id)
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

                    yield _sse("tool_result", {
                        "tool": tool_name,
                        "result": tool_result,
                    })

                    all_tool_calls.append({"name": tool_name, "args": tool_args, "id": tool_id})
                    all_tool_results.append({
                        "tool": tool_name,
                        "id": tool_id,
                        "result": tool_result,
                    })
                    tool_results_for_round.append({
                        "tool_name": tool_name,
                        "tool_id": tool_id,
                        "result": tool_result,
                    })

                # Add tool results to messages for next round
                messages = self._append_tool_results(
                    provider, messages, result, tool_results_for_round
                )
            else:
                # Hit max rounds — extract whatever text we have
                assistant_text = self._extract_text(provider, result) if result else ""  # type: ignore[possibly-undefined]
                if not assistant_text:
                    assistant_text = "I've gathered the data above. Let me know if you need further analysis."

            # 5. Stream text to client in chunks for smooth UX
            if assistant_text:
                chunk_size = 50
                for i in range(0, len(assistant_text), chunk_size):
                    yield _sse("text", {"content": assistant_text[i : i + chunk_size]})

            # 6. Persist messages
            await self._persist_messages(
                chat_session,
                user_id,
                request.message,
                assistant_text,
                all_tool_calls,
                all_tool_results,
                total_tokens,
            )

            # Auto-title from first user message
            if chat_session.title == "New Chat" and request.message:
                title = request.message[:80]
                if len(request.message) > 80:
                    title += "..."
                chat_session.title = title
                await self.session.flush()

            yield _sse("done", {"session_id": str(chat_session.id), "tokens": total_tokens})

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
            for msg in conversation_history:
                role = msg.get("role", "user")
                content = msg.get("content", "")
                if role in ("user", "assistant") and content:
                    messages.append({"role": role, "content": content})
        else:
            # Load last messages from DB
            db_messages = await self.get_session_messages(session_id, user_id)
            for msg in db_messages[-20:]:  # Last 20 messages for context
                if msg.role in ("user", "assistant") and msg.content:
                    messages.append({"role": msg.role, "content": msg.content})

        # Add new user message
        messages.append({"role": "user", "content": new_message})
        return messages

    # ── Anthropic API ────────────────────────────────────────────────────

    async def _call_anthropic(
        self,
        api_key: str,
        messages: list[dict[str, Any]],
        preferred_model: str | None,
    ) -> tuple[dict[str, Any], int]:
        """Call Anthropic Messages API with tools."""
        from app.modules.ai.ai_client import ANTHROPIC_MODEL

        model = ANTHROPIC_MODEL
        if preferred_model and "claude" in preferred_model:
            # Use preferred model if it looks like a Claude model
            pass  # Keep default — the preferred_model field is a preference hint

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
                    "system": SYSTEM_PROMPT,
                    "messages": messages,
                    "tools": TOOL_DEFINITIONS,
                },
            )
            resp.raise_for_status()
            data = resp.json()

        usage = data.get("usage", {})
        tokens = usage.get("input_tokens", 0) + usage.get("output_tokens", 0)
        return data, tokens

    # ── OpenAI API ───────────────────────────────────────────────────────

    async def _call_openai(
        self,
        api_key: str,
        messages: list[dict[str, Any]],
        preferred_model: str | None,
    ) -> tuple[dict[str, Any], int]:
        """Call OpenAI ChatCompletions API with tools."""
        from app.modules.ai.ai_client import OPENAI_MODEL

        model = OPENAI_MODEL
        if preferred_model and ("gpt" in preferred_model or "o1" in preferred_model):
            pass  # Keep default

        # Convert Anthropic tool format to OpenAI format
        openai_tools = [
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

        openai_messages = [{"role": "system", "content": SYSTEM_PROMPT}] + messages

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

        tokens = data.get("usage", {}).get("total_tokens", 0)
        return data, tokens

    # ── Fallback (non-tool providers) ────────────────────────────────────

    async def _call_fallback(
        self, provider: str, api_key: str, message: str
    ) -> AsyncGenerator[str, None]:
        """Call a provider without tool support — yield SSE text events."""
        from app.modules.ai.ai_client import call_ai

        try:
            text, tokens = await call_ai(
                provider=provider,
                api_key=api_key,
                system=SYSTEM_PROMPT,
                prompt=message,
            )
            chunk_size = 50
            for i in range(0, len(text), chunk_size):
                yield _sse("text", {"content": text[i : i + chunk_size]})
        except Exception as exc:
            yield _sse("error", {"message": f"AI error ({provider}): {exc}"})

    # ── Response parsing ─────────────────────────────────────────────────

    def _extract_tool_calls(
        self, provider: str, result: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """Extract tool calls from AI response."""
        calls: list[dict[str, Any]] = []

        if provider == "anthropic":
            for block in result.get("content", []):
                if block.get("type") == "tool_use":
                    calls.append({
                        "id": block.get("id", str(uuid.uuid4())),
                        "name": block["name"],
                        "args": block.get("input", {}),
                    })

        elif provider == "openai":
            msg = result.get("choices", [{}])[0].get("message", {})
            for tc in msg.get("tool_calls", []) or []:
                func = tc.get("function", {})
                try:
                    args = json.loads(func.get("arguments", "{}"))
                except json.JSONDecodeError:
                    args = {}
                calls.append({
                    "id": tc.get("id", str(uuid.uuid4())),
                    "name": func.get("name", ""),
                    "args": args,
                })

        return calls

    def _extract_text(self, provider: str, result: dict[str, Any]) -> str:
        """Extract text content from AI response."""
        if provider == "anthropic":
            parts = []
            for block in result.get("content", []):
                if block.get("type") == "text":
                    parts.append(block.get("text", ""))
            return "\n".join(parts)

        elif provider == "openai":
            msg = result.get("choices", [{}])[0].get("message", {})
            return msg.get("content", "") or ""

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

            # Add tool results
            tool_result_blocks = []
            for tr in tool_results:
                tool_result_blocks.append({
                    "type": "tool_result",
                    "tool_use_id": tr["tool_id"],
                    "content": json.dumps(tr["result"], default=str),
                })
            messages.append({"role": "user", "content": tool_result_blocks})

        elif provider == "openai":
            # Add assistant message (with tool_calls)
            msg = ai_result.get("choices", [{}])[0].get("message", {})
            messages.append(msg)

            # Add tool result messages
            for tr in tool_results:
                messages.append({
                    "role": "tool",
                    "tool_call_id": tr["tool_id"],
                    "content": json.dumps(tr["result"], default=str),
                })

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
    ) -> None:
        """Persist user message and assistant response to the database."""
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

            # Save assistant message
            assistant_msg = ChatMessage(
                session_id=chat_session.id,
                role="assistant",
                content=assistant_text or None,
                tool_calls=tool_calls if tool_calls else None,
                tool_results=tool_results if tool_results else None,
                renderer=renderer,
                renderer_data=renderer_data,
                tokens_used=tokens_used,
            )
            self.session.add(assistant_msg)
            await self.session.flush()
        except Exception:
            logger.exception("Failed to persist chat messages")
