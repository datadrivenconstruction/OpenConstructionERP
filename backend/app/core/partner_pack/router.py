"""HTTP surface for the active partner pack."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from importlib import resources
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Request, Response, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.core.partner_pack._safe_extract import has_zip_magic
from app.core.partner_pack.apply import (
    apply_pack,
    build_preview,
    get_applied_info,
    unapply,
)
from app.core.partner_pack.discovery import (
    discover_packs,
    get_active_pack,
    get_active_pack_module_name,
    get_pack_by_slug,
    read_pack_file,
    reset_cache,
)
from app.core.partner_pack.full_install import (
    FullInstallRequest,
    FullInstallResponse,
    full_install,
    full_install_stream,
)
from app.dependencies import RequirePermission

_IMAGE_MEDIA_TYPES = {
    "svg": "image/svg+xml",
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "webp": "image/webp",
}

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/partner-pack", tags=["partner-pack"])


@router.get("/current", summary="Active partner pack manifest")
def current_pack() -> dict[str, Any]:
    """Return the active pack's public manifest, or ``{"active": false}``.

    Frontend calls this on app boot to decide whether to mount the
    PartnerLogoBadge + adjust theme colours + load extra locales.
    """
    active = get_active_pack()
    if not active:
        return {"active": False}
    return {"active": True, "manifest": active.to_public_dict()}


@router.get("/installed", summary="All discovered packs (admin view)")
def list_installed() -> dict[str, Any]:
    """Return the list of all installed packs and which one is active."""
    active = get_active_pack()
    return {
        "active_slug": active.slug if active else None,
        "installed": [m.to_public_dict() for m in discover_packs()],
    }


# ── In-app apply / update / un-apply ────────────────────────────────────────


class ApplyRequest(BaseModel):
    """Body for POST /apply."""

    slug: str = Field(..., description="Pack slug to apply.")
    confirm_disables: bool = Field(
        default=False,
        description="Allow the apply to DISABLE modules the pack wants hidden.",
    )
    install_demo: bool = Field(
        default=True,
        description="Also install the pack's flagship country demo project (idempotent).",
    )


@router.get("/applied", summary="Currently applied pack + update status")
def applied_status() -> dict[str, Any]:
    """Return which pack is applied in-app and whether a newer version exists."""
    return get_applied_info()


@router.get("/apply-preview/{slug}", summary="Dry-run preview of applying a pack")
def apply_preview(slug: str) -> dict[str, Any]:
    """Return the field-by-field effect plan without changing anything."""
    try:
        return build_preview(slug)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post(
    "/apply",
    summary="Apply a pack to this installation (admin)",
    dependencies=[Depends(RequirePermission("admin"))],
)
async def apply(body: ApplyRequest, request: Request) -> dict[str, Any]:
    """Apply the pack: enable its modules, co-brand, record defaults."""
    try:
        return await apply_pack(
            body.slug,
            confirm_disables=body.confirm_disables,
            install_demo=body.install_demo,
            app=request.app,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post(
    "/full-install",
    summary="One-click install an entire localized workspace for a pack (admin)",
    dependencies=[Depends(RequirePermission("admin"))],
    response_model=FullInstallResponse,
)
async def full_install_pack(body: FullInstallRequest, request: Request) -> FullInstallResponse:
    """Install a complete localized workspace for a partner pack in one call.

    Runs the five-step orchestration from ``docs/country-pack-oneclick/DESIGN.md``
    §5: apply the pack (modules + branding), surface its locale, load the CWICR
    relational cost DB and build the vector DB for the pack's region(s), and
    install up to ``demo_count`` fully-worked country demo projects. Every step
    is fail-soft - a failed step is reported in the response and never aborts the
    rest, so this endpoint does not 404/500 for an unknown-region or
    embedding-model gap (it reports them as skipped). An unknown pack slug yields
    a single ``apply_pack`` step with ``status="error"``.
    """
    return await full_install(body, app=request.app)


@router.post(
    "/full-install-stream",
    summary="One-click install a pack's workspace with live SSE progress (admin)",
    dependencies=[Depends(RequirePermission("admin"))],
)
async def full_install_pack_stream(body: FullInstallRequest, request: Request) -> StreamingResponse:
    """Stream a pack activation step-by-step as Server-Sent Events.

    Same orchestration as ``POST /full-install`` (apply preset, install language,
    load the work catalog + its embedded resource database, build the vector
    index, create demo projects) but emits one ``start`` / ``step_start`` /
    ``step_done`` / ``done`` frame per step so the Modules-page activate dialog
    can render a live, determinate progress bar with named steps and item counts.
    Every step is fail-soft; the stream always reaches ``done``.

    The generator opens its own DB sessions (the ``_step_*`` helpers do). It does
    NOT depend on the request-scoped session: Starlette's BaseHTTPMiddleware
    cancels that session between streamed chunks, which would kill the loaders
    mid-import (see the same note on ``erp_chat.stream_chat``).
    """
    app = request.app

    async def _gen() -> AsyncIterator[str]:
        async for frame in full_install_stream(body, app=app):
            yield frame

    return StreamingResponse(
        _gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post(
    "/unapply",
    summary="Remove the applied pack (admin)",
    dependencies=[Depends(RequirePermission("admin"))],
)
async def unapply_pack(request: Request) -> dict[str, Any]:
    """Drop co-branding and restore any modules the apply disabled."""
    return await unapply(app=request.app)


@router.post(
    "/rescan",
    summary="Re-scan installed packs without a restart (admin)",
    dependencies=[Depends(RequirePermission("admin"))],
)
def rescan() -> dict[str, Any]:
    """Bust the discovery cache so on-disk packs are re-read.

    Note: brand-new pip-installed (entry-point) packs may still need a restart;
    this reliably picks up source-checkout packs under ``packs/`` and dropped
    packs under ``<data_dir>/packs/``.
    """
    reset_cache()
    packs = discover_packs()
    return {"count": len(packs), "slugs": [m.slug for m in packs]}


# Cap an uploaded pack at 25 MiB. A declarative pack is a tiny JSON manifest
# plus a logo/favicon and a few locale files; anything larger is almost
# certainly wrong (or hostile), and rejecting early bounds memory use.
_MAX_PACK_UPLOAD_BYTES = 100 * 1024 * 1024


@router.post(
    "/install",
    summary="Upload and install a partner-pack .zip into the data dir (admin)",
    dependencies=[Depends(RequirePermission("admin"))],
)
async def install_pack(file: UploadFile = File(...)) -> dict[str, Any]:
    """Install a declarative partner pack from an uploaded ``.zip``.

    The archive must contain a ``manifest.json`` (a serialized
    ``PartnerPackManifest``) at its root or in a single wrapping folder, plus
    its assets (logo, favicon, locales, onboarding script). The pack ships NO
    code and is never executed: the manifest is parsed as JSON and validated
    against the schema. The archive is safely extracted (staged, every member
    validated against Zip Slip / symlink / absolute / drive-letter / backslash)
    into ``<data_dir>/packs/<slug>/`` and the discovery cache is busted so the
    new pack is immediately listable. The pack is NOT activated by this call -
    apply it separately from the Partner Packs tab.

    Returns:
        ``{"installed": true, "slug", "partner_name", "pack_version"}`` on
        success.

    Raises:
        HTTPException: 400 if the upload is not a zip, exceeds the size cap,
            contains an unsafe member, or has no valid ``manifest.json``.
    """
    # Read with a hard cap so a huge upload cannot exhaust memory. Read one byte
    # past the limit to detect an over-size body deterministically.
    raw = await file.read(_MAX_PACK_UPLOAD_BYTES + 1)
    if len(raw) > _MAX_PACK_UPLOAD_BYTES:
        raise HTTPException(
            status_code=400,
            detail=f"Pack archive too large (limit {_MAX_PACK_UPLOAD_BYTES // (1024 * 1024)} MiB).",
        )
    if not raw:
        raise HTTPException(status_code=400, detail="Empty upload.")

    # Cheap magic-byte gate before the structural zip parse.
    if not has_zip_magic(raw[:4]):
        raise HTTPException(status_code=400, detail="Uploaded file is not a .zip archive.")

    # Local import keeps the install path (and its PackInstallError type) out of
    # the module import graph at boot; discovery is always importable here.
    from app.core.partner_pack.discovery import PackInstallError, install_dropped_zip

    try:
        manifest = install_dropped_zip(raw)
    except PackInstallError as exc:
        raise HTTPException(status_code=400, detail=exc.reason) from exc

    # Make the freshly installed pack visible to discovery immediately.
    reset_cache()
    logger.info("Partner pack uploaded and installed: %s v%s", manifest.slug, manifest.pack_version)
    return {
        "installed": True,
        "slug": manifest.slug,
        "partner_name": manifest.partner_name,
        "pack_version": manifest.pack_version,
    }


def _read_pack_resource(filename: str) -> bytes | None:
    """Read a file from inside the active pack package via importlib.resources.

    Returns None if the active pack is missing or the file does not exist.
    """
    mod_name = get_active_pack_module_name()
    if not mod_name:
        return None
    try:
        files = resources.files(mod_name)
        target = files.joinpath(filename)
        if not target.is_file():
            return None
        return target.read_bytes()
    except (ModuleNotFoundError, FileNotFoundError, AttributeError):
        return None


@router.get("/logo", summary="Stream the partner logo")
def partner_logo() -> Response:
    """Stream the partner logo SVG/PNG out of the installed pack package.

    Returns 404 if no pack is active or the pack does not ship a logo.
    Content-Type sniffed from the filename extension.
    """
    active = get_active_pack()
    if not active:
        raise HTTPException(status_code=404, detail="No active partner pack")
    # Use the universal by-slug reader, not the pip-only _read_pack_resource.
    # In-app one-click installs activate *source-checkout* packs under packs/,
    # which have no importable entry-point module - _read_pack_resource would
    # return None and the co-brand badge's <img> would 404 on every page.
    # read_pack_file resolves both pip-installed and filesystem packs.
    data = read_pack_file(active.slug, active.branding.logo_path)
    if data is None:
        raise HTTPException(
            status_code=404,
            detail=f"Active pack '{active.slug}' has no logo at {active.branding.logo_path!r}",
        )
    ext = active.branding.logo_path.rsplit(".", 1)[-1].lower()
    media_type = {
        "svg": "image/svg+xml",
        "png": "image/png",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "webp": "image/webp",
    }.get(ext, "application/octet-stream")
    return Response(
        content=data,
        media_type=media_type,
        # Logos rarely change; cache aggressively but allow revalidation.
        headers={"Cache-Control": "public, max-age=86400"},
    )


@router.get("/logo/{slug}", summary="Stream a specific pack's logo by slug")
def partner_logo_by_slug(slug: str) -> Response:
    """Stream any discovered pack's logo (not just the active one).

    The /modules Partner Packs grid uses this to render each company's real
    logo. Returns 404 if the pack is not installed or ships no logo file.
    """
    m = get_pack_by_slug(slug)
    if not m:
        raise HTTPException(status_code=404, detail=f"Pack '{slug}' not installed")
    data = read_pack_file(slug, m.branding.logo_path)
    if data is None:
        raise HTTPException(
            status_code=404,
            detail=f"Pack '{slug}' has no logo at {m.branding.logo_path!r}",
        )
    ext = m.branding.logo_path.rsplit(".", 1)[-1].lower()
    return Response(
        content=data,
        media_type=_IMAGE_MEDIA_TYPES.get(ext, "application/octet-stream"),
        headers={"Cache-Control": "public, max-age=86400"},
    )


@router.get("/favicon", summary="Stream the partner favicon")
def partner_favicon() -> Response:
    """Stream the partner favicon if one is shipped."""
    active = get_active_pack()
    if not active or not active.branding.favicon_path:
        raise HTTPException(status_code=404, detail="No partner favicon")
    data = read_pack_file(active.slug, active.branding.favicon_path)
    if data is None:
        raise HTTPException(status_code=404, detail="Favicon file missing in pack")
    return Response(content=data, media_type="image/x-icon")


@router.get("/onboarding-script", summary="Partner onboarding script (YAML/JSON)")
def partner_onboarding_script() -> Response:
    """Stream the onboarding YAML/JSON shipped by the active pack.

    Frontend OnboardingWizard fetches this and renders partner-specific
    steps instead of the default sequence.
    """
    active = get_active_pack()
    if not active or not active.onboarding_script_path:
        raise HTTPException(status_code=404, detail="No partner onboarding script")
    data = read_pack_file(active.slug, active.onboarding_script_path)
    if data is None:
        raise HTTPException(status_code=404, detail="Onboarding script file missing in pack")
    ext = active.onboarding_script_path.rsplit(".", 1)[-1].lower()
    media_type = "application/json" if ext == "json" else "text/yaml"
    return Response(content=data, media_type=media_type)


@router.get("/locale/{code}", summary="Partner-shipped locale JSON")
def partner_locale(code: str) -> Response:
    """Stream an additional locale file shipped by the active pack."""
    active = get_active_pack()
    if not active:
        raise HTTPException(status_code=404, detail="No active partner pack")
    path = active.additional_locales.get(code)
    if not path:
        raise HTTPException(
            status_code=404,
            detail=f"Pack '{active.slug}' does not ship locale '{code}'",
        )
    data = read_pack_file(active.slug, path)
    if data is None:
        raise HTTPException(status_code=404, detail="Locale file missing in pack")
    return Response(content=data, media_type="application/json")


@router.get("/by-slug/{slug}", summary="Inspect a non-active pack (admin / pre-install preview)")
def inspect_pack(slug: str) -> dict[str, Any]:
    """Return the public manifest of any installed pack by slug."""
    m = get_pack_by_slug(slug)
    if not m:
        raise HTTPException(status_code=404, detail=f"Pack '{slug}' not installed")
    return m.to_public_dict()
