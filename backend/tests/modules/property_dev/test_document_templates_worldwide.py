"""Worldwide parameterization tests for /document-templates endpoints.

The historical contract whitelisted 18 doc_type / 11 entity slugs that
were biased toward UAE / RU / DE / IN jurisdictions. Tenants in
Brazil / Japan / Mexico who needed ``escritura_publica`` /
``juyo_jiko_setsumeisho`` / ``acta_de_entrega`` couldn't save a custom
template against their actual doc_type. v4.7 relaxes the constraint:

  * ``doc_type`` / ``entity`` are now SHAPE-validated, not membership-
    validated. Any reasonably-formatted slug (1-40 chars, lowercase
    letters / digits / dots / dashes / underscores, leading alnum) is
    accepted. The settings page surfaces a preset list as combobox
    suggestions but no longer constrains the user to it.
  * The GET /document-templates/ catalogue response now exposes a
    ``has_pdf_renderer`` flag per entry plus ``doc_type_presets`` /
    ``entity_presets`` lists so the frontend can drop its own
    hardcoded slug tables.

These tests assert the relaxed contract and the new fields without
regressing the existing slug-validation safety net (oversize, invalid
characters, path-traversal, etc.).
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import AsyncClient

from .conftest import _register_user


@pytest_asyncio.fixture(scope="module")
async def admin(client: AsyncClient) -> dict:
    """Admin owning a project — author for the worldwide-parameterization
    happy-path tests."""
    _uid, _email, headers = await _register_user(client, role="admin", tag="ww")
    proj = await client.post(
        "/api/v1/projects/",
        json={
            "name": f"PropDev-WW-{uuid.uuid4().hex[:6]}",
            "description": "worldwide doc_type parameterization",
            "currency": "EUR",
        },
        headers=headers,
    )
    assert proj.status_code in (200, 201), proj.text
    return {"headers": headers, "project_id": proj.json()["id"]}


# ── Catalogue exposes worldwide-parameterization fields ────────────────


@pytest.mark.asyncio
async def test_catalogue_includes_has_pdf_renderer_per_entry(client: AsyncClient, admin: dict) -> None:
    """Every built-in catalogue entry must declare whether the backend
    can render a PDF for it. The frontend used to gate the Preview
    button on a hardcoded ``BUILTIN_DOC_TYPES`` slug set; the
    ``has_pdf_renderer`` flag replaces that with backend-authoritative
    truth so jurisdictions added after the FE release inherit the
    correct gating for free."""
    res = await client.get(
        "/api/v1/property-dev/document-templates/",
        headers=admin["headers"],
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["templates"], "catalogue must include built-ins"
    for tpl in body["templates"]:
        if not tpl.get("is_custom"):
            assert "has_pdf_renderer" in tpl, f"built-in {tpl['doc_type']} missing has_pdf_renderer"
            # Every built-in shipped today has a reportlab renderer.
            assert tpl["has_pdf_renderer"] is True


@pytest.mark.asyncio
async def test_catalogue_exposes_doc_type_and_entity_presets(client: AsyncClient, admin: dict) -> None:
    """The combobox suggestions are now backend-driven. The frontend
    falls back to a bundled list when the field is absent (old API
    contract), but the v4.7 backend MUST emit them — otherwise the
    user's preset dropdown will stagnate against the bundled list at
    install time."""
    res = await client.get(
        "/api/v1/property-dev/document-templates/",
        headers=admin["headers"],
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert isinstance(body.get("doc_type_presets"), list)
    assert isinstance(body.get("entity_presets"), list)
    # Sanity: the legacy 18-slug presets must still be present (we
    # didn't drop them — they became suggestions, not constraints).
    assert "reservation_receipt" in body["doc_type_presets"]
    assert "sales_contract" in body["doc_type_presets"]
    assert "custom" in body["entity_presets"]


# ── Save-text accepts jurisdiction-specific slugs (NEW behaviour) ──────


@pytest.mark.parametrize(
    ("doc_type", "entity"),
    [
        # Brazil — notarial deed for a sales contract.
        ("escritura_publica", "sales_contract"),
        # Japan — Important Matters Explanation document.
        ("juyo_jiko_setsumeisho", "sales_contract"),
        # Mexico — handover act.
        ("acta_de_entrega", "handover"),
        # Vietnam — pink book registration request.
        ("so_hong", "plot"),
        # Australia — vendor's statement (Section 32).
        ("section_32_statement", "sales_contract"),
        # Slug with dots and dashes (allowed shape).
        ("kyc.v2-2026", "buyer"),
    ],
)
@pytest.mark.asyncio
async def test_save_text_accepts_worldwide_doc_type_slugs(
    client: AsyncClient, admin: dict, doc_type: str, entity: str
) -> None:
    """The 18-slug whitelist is gone — any reasonably-shaped slug
    (1-40 chars, ``[a-z0-9_.-]``, leading alnum) lands a row."""
    res = await client.post(
        "/api/v1/property-dev/document-templates/save-text",
        json={
            "name": f"{doc_type} template",
            "doc_type": doc_type,
            "entity": entity,
            "content_type": "text/html",
            "content_text": f"<p>{doc_type}</p>",
            "project_id": admin["project_id"],
        },
        headers=admin["headers"],
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["doc_type"] == doc_type
    assert body["entity"] == entity
    assert body["is_custom"] is True
    # Custom text rows are always renderable in-browser → flag is true.
    assert body.get("has_pdf_renderer") is True


# ── Slug-shape safety net (kept after the whitelist was removed) ───────


@pytest.mark.parametrize(
    "bad_slug",
    [
        # Path-traversal / shell-injection signatures.
        "../etc/passwd",
        "doc;DROP TABLE",
        # Special characters that survive lowercasing.
        "doc with spaces",
        # Leading non-alnum (dot / dash / underscore). These rules
        # mirror the regex anchor (``^[a-z0-9]``).
        ".hidden_doc",
        "-leading-dash",
        "_leading_under",
        # Overlong (>40 chars — matches the DB column cap).
        "a" * 41,
        # Note: whitespace-only / empty strings fall back to the
        # default "custom" slug (legacy behaviour preserved), so
        # they're tested separately as positive cases via the upload
        # text-template happy-path tests, not here.
    ],
)
@pytest.mark.asyncio
async def test_save_text_rejects_malformed_slug(client: AsyncClient, admin: dict, bad_slug: str) -> None:
    res = await client.post(
        "/api/v1/property-dev/document-templates/save-text",
        json={
            "name": "Bad slug",
            "doc_type": bad_slug,
            "entity": "custom",
            "content_type": "text/html",
            "content_text": "<p>x</p>",
            "project_id": admin["project_id"],
        },
        headers=admin["headers"],
    )
    assert res.status_code == 422, f"slug {bad_slug!r} should be rejected: {res.status_code} {res.text}"


# ── Catalogue surfaces the custom row with the right has_pdf_renderer ──


@pytest.mark.asyncio
async def test_catalogue_marks_text_custom_template_renderable(client: AsyncClient, admin: dict) -> None:
    """A custom HTML upload should appear in the catalogue with
    ``has_pdf_renderer: True`` so the frontend can keep the editor /
    preview affordances enabled."""
    # Save a text template against a brand-new jurisdiction-specific
    # slug — verifies the listing path doesn't fall back to the legacy
    # built-in slug set when deciding renderability.
    save = await client.post(
        "/api/v1/property-dev/document-templates/save-text",
        json={
            "name": "Mexican entrega acta",
            "doc_type": "acta_de_entrega_v2",
            "entity": "handover",
            "content_type": "text/html",
            "content_text": "<p>acta</p>",
            "project_id": admin["project_id"],
        },
        headers=admin["headers"],
    )
    assert save.status_code == 201, save.text
    saved_id = save.json()["id"]

    listing = await client.get(
        "/api/v1/property-dev/document-templates/",
        headers=admin["headers"],
    )
    assert listing.status_code == 200, listing.text
    body = listing.json()
    matches = [t for t in body["templates"] if t.get("id") == saved_id]
    assert matches, "saved custom template missing from catalogue"
    assert matches[0]["has_pdf_renderer"] is True
    assert matches[0]["doc_type"] == "acta_de_entrega_v2"
