# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""i18n API endpoints.

Serves the backend catalogue, backend/locales/*.json, to any HTTP consumer.

It does NOT serve this product's own UI, despite what the route names suggest.
The frontend builds its i18next store from bundled resources and lazy-loaded
locale chunks (frontend/src/app/i18n.ts, the ``resources: { en: enResource }``
init at line 264); there is no i18next-http-backend plugin, no ``loadPath``,
and nothing under frontend/src fetches these routes. So the two catalogues are
separate: roughly four hundred backend keys here, tens of thousands of UI keys
in frontend/src/app/locales/*.ts, and a key belongs to whichever side renders it.

That matters because reading this the other way invites someone to translate
the whole UI into these files to close a gap that does not exist. What the
backend catalogue is actually for is the strings the backend itself renders
through ``t()`` - validation messages, error text - plus any external client
that wants them.

Module translations are merged with core translations.
"""

from fastapi import APIRouter, HTTPException, status

from app.core.document_forms_i18n import document_form_locales
from app.core.i18n import (
    SUPPORTED_LOCALES,
    get_all_translations,
    get_available_locales,
    locale_candidates,
    resolve_locale,
)

router = APIRouter(prefix="/i18n", tags=["i18n"])


def _supported_code(locale: str) -> str | None:
    """The supported code this request is asking for, or None.

    A regional code counts as asking for its base language. Both routes here
    used to test membership of SUPPORTED_LOCALES directly, which holds base
    codes only, so pt-BR came back 404 while the Accept-Language middleware
    two files away was resolving the very same tag to pt without comment. The
    convention these routes are shaped for sends regional codes as a matter of
    course, so the 404 was answering a question nobody asked.

    This asks whether the platform claims the language, which is not the
    question ``_meta_for`` asks; that one asks whether a catalogue will really
    answer. The two are deliberately separate and today they agree on every
    code, because ``SUPPORTED_LOCALES`` is held equal to the files on disk by
    test_backend_locale_catalogue.py. If that ever stops being true, a code
    listed without a file is exactly the case the fallback flag exists for, and
    it has to reach the flag rather than be turned into a 404 here.
    """
    for candidate in locale_candidates(locale):
        if candidate in SUPPORTED_LOCALES:
            return candidate
    return None


def _meta_for(locale: str) -> dict[str, object]:
    """Describe what is actually being served, which is not always what was asked.

    ``fallback`` keeps its meaning: you are reading English instead of the
    language you named. It is not the same as "there is no file called
    pt-BR.json", and reporting the second under the name of the first told a
    Brazilian client its Portuguese was English.
    """
    served = resolve_locale(locale)
    meta: dict[str, object] = {"locale": locale, "fallback": served is None}
    if served is None:
        meta["fallback_locale"] = "en"
    elif served != locale:
        meta["resolved_locale"] = served
    return meta


@router.get("/locales")
async def list_locales() -> dict:
    """List all available languages."""
    return {"locales": get_available_locales()}


@router.get("/document-locales")
async def list_document_locales() -> dict:
    """The languages each printed document form can be rendered in.

    ``forms`` maps a form name (``submittals``, ``variations``, ``procurement``
    and so on) to the language codes its PDF and workbook exist in; every code
    is a member of ``SUPPORTED_LOCALES``. A request for any other language, or
    for a supported one a form does not list, is rendered in English.
    """
    return {"forms": {name: list(codes) for name, codes in document_form_locales().items()}}


@router.get("/locales/{locale}/messages")
@router.get("/locales/{locale}/messages/")
async def get_locale_messages(locale: str) -> dict:
    """Get translation messages for a locale (BUG-API13).

    Mirrors the ``GET /i18n/{locale}`` endpoint but at the
    ``/i18n/locales/{code}/messages/`` path expected by
    ``i18next-http-backend`` and consumers that follow the
    ``/locales/{code}/messages`` convention. Returns 404 for unsupported
    locale codes; supplies the English fallback (with ``_meta.fallback``)
    for supported but unloaded locales. A regional code is served by its
    base language, which the same client would already have received from
    the Accept-Language path.
    """
    if _supported_code(locale) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"Locale '{locale}' is not supported. Supported codes: {', '.join(SUPPORTED_LOCALES)}. "
                f"A regional code is accepted when its base language is on that list."
            ),
        )
    return {"_meta": _meta_for(locale), **get_all_translations(locale)}


@router.get("/{locale}")
async def get_translations(locale: str) -> dict:
    """Get all backend translations for a locale.

    Shaped for an i18next-http-backend style client, though this product's own
    frontend does not use one - see the module docstring.

    Returns 404 for unsupported locale codes. For supported locales whose
    bundle hasn't been loaded yet we still serve the English fallback but
    flag it explicitly via ``_meta.fallback`` so the client can surface a
    "translation incomplete" indicator instead of pretending the target
    language is complete. A regional code is served by its base language and
    says so in ``_meta.resolved_locale``, which is not a fallback: the reader
    gets the language asked for, from the catalogue that has it.
    """
    if _supported_code(locale) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Locale '{locale}' is not supported",
        )
    return {"_meta": _meta_for(locale), **get_all_translations(locale)}
