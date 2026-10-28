"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Regression suite locking in the GitHub issue #138 fix.

Issue #138
~~~~~~~~~~
A user configured OpenRouter with a chosen model id in Settings > AI.
Tokens were billed upstream (confirmed on the provider dashboard) yet the
chat returned no answer. Root cause: the AI handlers resolved the provider
via ``resolve_provider_and_key`` (a 2-tuple, no model id) and called
``call_ai()`` with **no** ``model=``, so every request silently used the
hardcoded ``OPENROUTER_MODEL`` default — a model the user's key may not
fund. The fix switched the handlers to ``resolve_provider_key_model``
(reads ``AISettings.metadata_["model_overrides"][provider]``) and threads
``model=model_override`` into ``call_ai``.

What this suite pins
~~~~~~~~~~~~~~~~~~~~~
1. ``resolve_provider_key_model`` — provider/key/override resolution incl.
   the real Fernet crypto round-trip used for the stored key field.
2. ``call_ai`` routing — the JSON body sent to OpenRouter / OpenAI /
   Anthropic carries the OVERRIDE model id when ``model=`` is passed and
   the built-in default when ``model=None``.
3. End-to-end-ish — ``ERPChatService._call_fallback`` (the OpenRouter
   path from the bug report) and ``BOQService._call_llm`` actually deliver
   the user's model id to the provider request.
4. A static guard — none of the six fixed handler call sites may invoke
   ``call_ai(`` without threading a ``model=`` argument, nor regress to a
   bare ``resolve_provider_and_key`` resolver, so a future refactor cannot
   silently reintroduce #138.

No network calls. ``httpx.AsyncClient.post`` is monkeypatched to a fake
that records the request and returns a canned provider-shaped response.
Per the project rule, modules are refreshed with ``importlib.reload`` —
never ``del sys.modules``.
"""

from __future__ import annotations

import importlib
import re
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from app.core.crypto import encrypt_secret
from app.modules.ai import ai_client as ai_client_module
from app.modules.ai.ai_client import (
    DEEPSEEK_MODEL,
    OPENAI_MODEL,
    OPENROUTER_MODEL,
    resolve_provider_key_model,
)

# ── repo layout ──────────────────────────────────────────────────────────────
# tests/unit/<this file>  →  parents[2] == backend/
_BACKEND_ROOT = Path(__file__).resolve().parents[2]
_APP = _BACKEND_ROOT / "app"


# ── Fake httpx layer (records the outgoing request) ──────────────────────────


class _FakeResponse:
    """Minimal stand-in for ``httpx.Response`` used by the ai_client paths."""

    def __init__(self, payload: dict[str, Any], status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def json(self) -> dict[str, Any]:
        return self._payload

    def raise_for_status(self) -> None:  # all fakes return 200
        return None


def _provider_response(provider: str) -> dict[str, Any]:
    """A successful, provider-shaped response body the extractors accept."""
    if provider == "anthropic":
        return {
            "content": [{"type": "text", "text": "ok-answer"}],
            "usage": {"input_tokens": 3, "output_tokens": 5},
        }
    # OpenAI + every OpenAI-compatible provider (openrouter, deepseek, ...)
    return {
        "choices": [{"message": {"content": "ok-answer"}, "finish_reason": "stop"}],
        "usage": {"total_tokens": 8},
    }


class _PostRecorder:
    """Captures every ``AsyncClient.post`` call so assertions can read the
    exact JSON body (and therefore the ``model`` id) sent to the provider."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import httpx

        recorder = self

        async def _fake_post(self_client, url, *args, **kwargs):  # noqa: ANN001
            json_body = kwargs.get("json")
            # Infer provider from the destination URL so we can return a
            # body the matching extractor will accept.
            if "anthropic.com" in url:
                provider = "anthropic"
            elif "generativelanguage.googleapis.com" in url:
                provider = "gemini"
            else:
                provider = "openai"  # openai + all OpenAI-compatible
            recorder.calls.append({"url": url, "json": json_body, "headers": kwargs.get("headers")})
            if provider == "gemini":
                body = {
                    "candidates": [{"content": {"parts": [{"text": "ok-answer"}]}}],
                    "usageMetadata": {"promptTokenCount": 2, "candidatesTokenCount": 4},
                }
            else:
                body = _provider_response(provider)
            return _FakeResponse(body)

        monkeypatch.setattr(httpx.AsyncClient, "post", _fake_post, raising=True)

    @property
    def last_model(self) -> Any:
        assert self.calls, "no AI HTTP call was recorded"
        return self.calls[-1]["json"].get("model")


@pytest.fixture
def post_recorder(monkeypatch: pytest.MonkeyPatch) -> _PostRecorder:
    rec = _PostRecorder()
    rec.install(monkeypatch)
    return rec


# ── AISettings-like fixture helper ───────────────────────────────────────────

_ALL_KEY_ATTRS = (
    "anthropic_api_key",
    "openai_api_key",
    "gemini_api_key",
    "openrouter_api_key",
    "mistral_api_key",
    "groq_api_key",
    "deepseek_api_key",
    "together_api_key",
    "fireworks_api_key",
    "perplexity_api_key",
    "cohere_api_key",
    "ai21_api_key",
    "xai_api_key",
)


def make_ai_settings(
    *,
    preferred_model: str = "claude-sonnet",
    overrides: dict[str, str] | None = None,
    **keys: str,
) -> SimpleNamespace:
    """Build an AISettings-like object.

    Key values are run through the REAL ``encrypt_secret`` (Fernet) so the
    resolver's ``decrypt_secret`` round-trip is exercised end-to-end, exactly
    as production stores them — not a monkeypatched decrypt.
    """
    fields: dict[str, Any] = dict.fromkeys(_ALL_KEY_ATTRS, None)
    for attr, raw in keys.items():
        fields[attr] = encrypt_secret(raw)
    fields["preferred_model"] = preferred_model
    fields["metadata_"] = {"model_overrides": overrides} if overrides is not None else {}
    return SimpleNamespace(**fields)


# ════════════════════════════════════════════════════════════════════════════
# 1. resolve_provider_key_model — provider/key/override resolution
# ════════════════════════════════════════════════════════════════════════════


class TestResolveProviderKeyModel:
    """The exact bug-report scenario plus the override edge cases."""

    def test_openrouter_override_returns_decrypted_key_and_model(self):
        # The literal #138 repro: OpenRouter key + a chosen model id.
        settings = make_ai_settings(
            preferred_model="openrouter",
            openrouter_api_key="sk-or-v1-REALKEY-abcdef",
            overrides={"openrouter": "deepseek/deepseek-chat"},
        )
        provider, key, model = resolve_provider_key_model(settings)
        assert provider == "openrouter"
        assert key == "sk-or-v1-REALKEY-abcdef"  # decrypted via real Fernet
        assert model == "deepseek/deepseek-chat"

    def test_blank_override_resolves_to_none(self):
        settings = make_ai_settings(
            preferred_model="openrouter",
            openrouter_api_key="sk-or-blank",
            overrides={"openrouter": "   \t  "},
        )
        provider, _key, model = resolve_provider_key_model(settings)
        assert provider == "openrouter"
        assert model is None  # whitespace → built-in default downstream

    def test_no_override_key_resolves_to_none(self):
        settings = make_ai_settings(
            preferred_model="openrouter",
            openrouter_api_key="sk-or-noov",
            overrides={"openai": "gpt-4o-mini"},  # different provider
        )
        provider, _key, model = resolve_provider_key_model(settings)
        assert provider == "openrouter"
        assert model is None

    def test_missing_metadata_resolves_to_none(self):
        settings = make_ai_settings(
            preferred_model="openrouter",
            openrouter_api_key="sk-or-nometa",
        )
        provider, _key, model = resolve_provider_key_model(settings)
        assert provider == "openrouter"
        assert model is None

    @pytest.mark.parametrize(
        ("preferred", "key_attr", "key_val", "expected_provider"),
        [
            ("openrouter", "openrouter_api_key", "sk-or-1", "openrouter"),
            ("gpt-4o", "openai_api_key", "sk-openai-1", "openai"),
            ("claude-sonnet", "anthropic_api_key", "sk-ant-1", "anthropic"),
            ("gemini-2.5-flash", "gemini_api_key", "AIza-1", "gemini"),
        ],
    )
    def test_provider_resolves_by_preferred_model(self, preferred, key_attr, key_val, expected_provider):
        settings = make_ai_settings(
            preferred_model=preferred,
            overrides={expected_provider: "user/custom-model"},
            **{key_attr: key_val},
        )
        provider, key, model = resolve_provider_key_model(settings)
        assert provider == expected_provider
        assert key == key_val  # real decrypt round-trip
        assert model == "user/custom-model"

    def test_real_crypto_round_trip_is_exercised(self):
        """Guard: the key really is encrypted at rest and decrypted by the
        resolver. If decryption silently broke, the bug (#138-adjacent —
        encrypted garbage sent as a key) would resurface."""
        from app.core.crypto import decrypt_secret, is_encrypted

        stored = encrypt_secret("sk-or-v1-secret")
        assert is_encrypted(stored)  # genuinely Fernet-wrapped
        assert decrypt_secret(stored) == "sk-or-v1-secret"

        settings = make_ai_settings(
            preferred_model="openrouter",
            openrouter_api_key="sk-or-v1-secret",
            overrides={"openrouter": "x/y"},
        )
        _provider, key, _model = resolve_provider_key_model(settings)
        assert key == "sk-or-v1-secret"


# ════════════════════════════════════════════════════════════════════════════
# 2. call_ai routing — the OVERRIDE model id reaches the provider request
# ════════════════════════════════════════════════════════════════════════════


class TestCallAIRoutesModelOverride:
    async def test_openrouter_uses_override_model(self, post_recorder):
        text, _tokens = await ai_client_module.call_ai(
            provider="openrouter",
            api_key="sk-or-test",
            system="s",
            prompt="p",
            model="deepseek/deepseek-chat",
        )
        assert text == "ok-answer"
        # The exact regression assertion: the OVERRIDE id is on the wire,
        # NOT the OPENROUTER_MODEL default.
        assert post_recorder.last_model == "deepseek/deepseek-chat"
        assert post_recorder.last_model != OPENROUTER_MODEL

    async def test_openrouter_falls_back_to_default_when_model_none(self, post_recorder):
        await ai_client_module.call_ai(
            provider="openrouter",
            api_key="sk-or-test",
            system="s",
            prompt="p",
            model=None,
        )
        assert post_recorder.last_model == OPENROUTER_MODEL

    async def test_openai_uses_override_model(self, post_recorder):
        await ai_client_module.call_ai(
            provider="openai",
            api_key="sk-openai-test",
            system="s",
            prompt="p",
            model="gpt-4o-mini",
        )
        assert post_recorder.last_model == "gpt-4o-mini"
        assert post_recorder.last_model != OPENAI_MODEL

    async def test_openai_falls_back_to_default_when_model_none(self, post_recorder):
        await ai_client_module.call_ai(
            provider="openai",
            api_key="sk-openai-test",
            system="s",
            prompt="p",
            model=None,
        )
        assert post_recorder.last_model == OPENAI_MODEL

    async def test_anthropic_uses_override_model(self, post_recorder):
        await ai_client_module.call_ai(
            provider="anthropic",
            api_key="sk-ant-test",
            system="s",
            prompt="p",
            model="claude-3-5-haiku-latest",
        )
        assert post_recorder.last_model == "claude-3-5-haiku-latest"

    async def test_anthropic_falls_back_to_default_when_model_none(self, post_recorder):
        from app.modules.ai.ai_client import ANTHROPIC_MODEL

        await ai_client_module.call_ai(
            provider="anthropic",
            api_key="sk-ant-test",
            system="s",
            prompt="p",
            model=None,
        )
        assert post_recorder.last_model == ANTHROPIC_MODEL

    async def test_deepseek_uses_override_model(self, post_recorder):
        await ai_client_module.call_ai(
            provider="deepseek",
            api_key="sk-ds-test",
            system="s",
            prompt="p",
            model="deepseek-reasoner",
        )
        assert post_recorder.last_model == "deepseek-reasoner"
        assert post_recorder.last_model != DEEPSEEK_MODEL

    async def test_importlib_reload_keeps_routing_intact(self, post_recorder):
        """Per project rule we reload (never ``del sys.modules``). After a
        reload the override must still reach the provider request."""
        reloaded = importlib.reload(ai_client_module)
        await reloaded.call_ai(
            provider="openrouter",
            api_key="sk-or-test",
            system="s",
            prompt="p",
            model="qwen/qwen-2.5-72b-instruct",
        )
        assert post_recorder.last_model == "qwen/qwen-2.5-72b-instruct"


# ════════════════════════════════════════════════════════════════════════════
# 3. End-to-end-ish — the handler layer delivers the user's model id
# ════════════════════════════════════════════════════════════════════════════


class TestErpChatFallbackDeliversOverride:
    """``ERPChatService._resolve_ai`` → ``_call_fallback`` is the exact path
    that was blank in the #138 bug report (OpenRouter = non-tool provider →
    fallback). The user's model id must reach the provider request."""

    async def test_resolve_ai_returns_override(self, post_recorder):
        from app.modules.erp_chat.service import ERPChatService

        settings = make_ai_settings(
            preferred_model="openrouter",
            openrouter_api_key="sk-or-e2e",
            overrides={"openrouter": "deepseek/deepseek-chat"},
        )

        class _Repo:
            def __init__(self, _session):
                pass

            async def get_by_user_id(self, _uid):
                return settings

        import app.modules.ai.repository as ai_repo

        svc = ERPChatService(session=object())
        # Patch only the repo lookup; the resolver + HTTP layer stay real.
        import unittest.mock as _mock

        with _mock.patch.object(ai_repo, "AISettingsRepository", _Repo):
            provider, key, model_override = await svc._resolve_ai(str(uuid.uuid4()))
        assert provider == "openrouter"
        assert key == "sk-or-e2e"
        assert model_override == "deepseek/deepseek-chat"

    # Issue #417 turned ``_call_fallback`` from an SSE generator into a plain
    # coroutine returning ``(text, tokens)``, so the caller can run the one
    # shared tail that persists the reply and counts tokens. These two tests
    # drive it the way the caller now does. What they are checking is
    # unchanged: the model id the user picked has to reach the provider.
    async def test_call_fallback_sends_override_model_to_openrouter(self, post_recorder):
        from app.modules.erp_chat.service import ERPChatService

        svc = ERPChatService(session=object())
        text, tokens = await svc._call_fallback(
            provider="openrouter",
            api_key="sk-or-e2e",
            message="estimate a wall",
            model="deepseek/deepseek-chat",
        )
        # Failure is an exception now rather than an error frame in the stream,
        # so reaching this line at all is the "no error" assertion.
        assert "ok-answer" in text
        assert isinstance(tokens, int)
        assert post_recorder.last_model == "deepseek/deepseek-chat"
        assert post_recorder.last_model != OPENROUTER_MODEL

    async def test_call_fallback_none_model_uses_default(self, post_recorder):
        from app.modules.erp_chat.service import ERPChatService

        svc = ERPChatService(session=object())
        await svc._call_fallback(
            provider="openrouter",
            api_key="sk-or-e2e",
            message="hi",
            model=None,
        )
        assert post_recorder.last_model == OPENROUTER_MODEL


class TestBoqCallLlmDeliversOverride:
    """``BOQService._get_ai_client`` (3-tuple) → ``_call_llm`` must pass the
    resolved override into ``call_ai``."""

    async def test_call_llm_threads_override_into_call_ai(self, post_recorder):
        from app.modules.boq.service import BOQService

        settings = make_ai_settings(
            preferred_model="openrouter",
            openrouter_api_key="sk-or-boq",
            overrides={"openrouter": "anthropic/claude-3.7-sonnet"},
        )

        svc = BOQService.__new__(BOQService)  # skip __init__/DB wiring

        async def _fake_get_ai_client(_user_id):
            from app.modules.ai.ai_client import resolve_provider_key_model

            return resolve_provider_key_model(settings)

        svc._get_ai_client = _fake_get_ai_client  # type: ignore[method-assign]

        raw_text, provider, _tokens = await svc._call_llm(
            user_id=str(uuid.uuid4()),
            system="sys",
            prompt="describe concrete works",
        )
        assert provider == "openrouter"
        assert raw_text == "ok-answer"
        assert post_recorder.last_model == "anthropic/claude-3.7-sonnet"
        assert post_recorder.last_model != OPENROUTER_MODEL


# ════════════════════════════════════════════════════════════════════════════
# 4. Static guard — a future refactor cannot silently reintroduce #138
# ════════════════════════════════════════════════════════════════════════════

# Every handler file changed by the #138 fix. Each must (a) resolve via
# resolve_provider_key_model and (b) thread model= into every call_ai(...).
_HANDLER_FILES = [
    _APP / "modules" / "boq" / "router.py",
    _APP / "modules" / "boq" / "service.py",
    _APP / "modules" / "erp_chat" / "service.py",
    _APP / "modules" / "meetings" / "router.py",
    _APP / "modules" / "takeoff" / "router.py",
    _APP / "modules" / "compliance" / "router.py",
]


def _iter_call_ai_invocations(src: str) -> list[str]:
    """Return the full argument text of every real ``call_ai(...)`` call.

    ``call_ai_tools(...)`` counts too. It is the tool-carrying sibling added
    for issue #424 and it takes the same ``model=`` argument, so forgetting it
    there is the identical #138 regression - and a pattern anchored on
    ``call_ai(`` alone would not see it.

    Brackets are balanced so nested parentheses inside arguments are
    captured whole. Non-invocations are skipped:

    * import lines (``from ... import call_ai``);
    * attribute / prose references such as the module docstring's
      ``ai_client.call_ai()`` (preceded by ``.``);
    * empty-argument ``call_ai()`` — every genuine handler invocation
      passes provider/api_key/etc., so a zero-arg span is documentation.
    """
    invocations: list[str] = []
    for m in re.finditer(r"\bcall_ai(?:_tools)?\s*\(", src):
        # Exclude the symbol appearing in an import statement.
        line_start = src.rfind("\n", 0, m.start()) + 1
        line = src[line_start : src.find("\n", m.start())]
        if "import" in line:
            continue
        # Exclude attribute-style prose refs like ``ai_client.call_ai()``.
        prefix = src[: m.start()].rstrip()
        if prefix.endswith("."):
            continue
        i = m.end()
        depth = 1
        while i < len(src) and depth:
            ch = src[i]
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
            i += 1
        args = src[m.end() : i - 1]
        # A real handler call_ai() always carries arguments; an empty span
        # is a doc reference / no-arg mention, not an invocation.
        if not args.strip():
            continue
        invocations.append(args)
    return invocations


class TestNoUnmodeledCallAI:
    @pytest.mark.parametrize("path", _HANDLER_FILES, ids=lambda p: p.relative_to(_APP).as_posix())
    def test_handler_file_exists(self, path: Path):
        assert path.is_file(), f"expected handler file missing: {path}"

    @pytest.mark.parametrize("path", _HANDLER_FILES, ids=lambda p: p.relative_to(_APP).as_posix())
    def test_every_call_ai_threads_a_model_argument(self, path: Path):
        """The core anti-regression check. Every real ``call_ai(...)`` in a
        fixed handler must pass ``model=`` — the absence of which IS #138."""
        src = path.read_text(encoding="utf-8")
        invocations = _iter_call_ai_invocations(src)
        assert invocations, (
            f"{path.relative_to(_APP).as_posix()}: expected at least one "
            f"call_ai(...) invocation — the fix wires one here"
        )
        for idx, args in enumerate(invocations):
            assert re.search(r"\bmodel\s*=", args), (
                f"{path.relative_to(_APP).as_posix()}: call_ai() invocation "
                f"#{idx + 1} does not thread a `model=` argument — this is "
                f"exactly the GitHub #138 regression. Args were: {args!r}"
            )

    @pytest.mark.parametrize("path", _HANDLER_FILES, ids=lambda p: p.relative_to(_APP).as_posix())
    def test_handler_resolves_via_resolve_provider_key_model(self, path: Path):
        """The handler must use the 3-tuple resolver. A regression to a bare
        ``resolve_provider_and_key`` (no model id) is what caused #138."""
        src = path.read_text(encoding="utf-8")
        assert "resolve_provider_key_model" in src, (
            f"{path.relative_to(_APP).as_posix()}: must resolve the AI "
            f"provider via resolve_provider_key_model (3-tuple incl. the "
            f"user's model override) — issue #138"
        )
        # If the legacy 2-tuple resolver is referenced at all, it must only
        # be as the documented internal delegate, never the handler's own
        # resolution call. We assert the 3-tuple resolver is the one whose
        # result feeds call_ai by checking `model_override` is bound.
        if "resolve_provider_and_key(" in src:
            # Acceptable only inside ai_client itself; handlers must not.
            assert "model_override" in src, (
                f"{path.relative_to(_APP).as_posix()}: references the legacy "
                f"2-tuple resolver but never binds a model_override — "
                f"potential #138 regression"
            )

    def test_resolve_provider_key_model_is_a_three_tuple(self):
        """The resolver contract itself: provider, key, AND model override."""
        settings = make_ai_settings(
            preferred_model="openrouter",
            openrouter_api_key="sk-or-contract",
            overrides={"openrouter": "z/z"},
        )
        result = resolve_provider_key_model(settings)
        assert isinstance(result, tuple)
        assert len(result) == 3
        provider, key, model = result
        assert (provider, key, model) == ("openrouter", "sk-or-contract", "z/z")
