"""i18n API endpoints.

Serves translations to the frontend.
Module translations are merged with core translations.
"""

from fastapi import APIRouter, HTTPException, status

from app.core.i18n import (
    SUPPORTED_LOCALES,
    get_all_translations,
    get_available_locales,
    is_locale_loaded,
)

router = APIRouter(prefix="/i18n", tags=["i18n"])


@router.get("/locales")
async def list_locales() -> dict:
    """List all available languages."""
    return {"locales": get_available_locales()}


@router.get("/{locale}")
async def get_translations(locale: str) -> dict:
    """Get all translations for a locale (used by frontend i18next-http-backend).

    Returns 404 for unsupported locale codes. For supported locales whose
    bundle hasn't been loaded yet we still serve the English fallback but
    flag it explicitly via ``_meta.fallback`` so the client can surface a
    "translation incomplete" indicator instead of pretending the target
    language is complete.
    """
    if locale not in SUPPORTED_LOCALES:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Locale '{locale}' is not supported",
        )
    translations = get_all_translations(locale)
    meta: dict[str, object] = {"locale": locale, "fallback": not is_locale_loaded(locale)}
    if meta["fallback"]:
        meta["fallback_locale"] = "en"
    return {"_meta": meta, **translations}
