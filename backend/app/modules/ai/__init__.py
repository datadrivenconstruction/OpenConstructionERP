"""AI Estimation module.

Provides AI-powered construction cost estimation from text descriptions
and building photos. Supports Anthropic Claude, OpenAI, and Google Gemini
backends with per-user API key configuration.
"""


async def on_startup() -> None:
    """Module startup hook — register permissions."""
    from app.modules.ai.permissions import register_ai_permissions

    register_ai_permissions()
