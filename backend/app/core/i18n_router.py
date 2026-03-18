"""i18n API endpoints.

Serves translations to the frontend.
Module translations are merged with core translations.
"""


from fastapi import APIRouter

from app.core.i18n import get_all_translations, get_available_locales

router = APIRouter(prefix="/i18n", tags=["i18n"])


@router.get("/locales")
async def list_locales() -> dict:
    """List all available languages."""
    return {"locales": get_available_locales()}


@router.get("/{locale}")
async def get_translations(locale: str) -> dict[str, str]:
    """Get all translations for a locale (used by frontend i18next-http-backend)."""
    return get_all_translations(locale)
