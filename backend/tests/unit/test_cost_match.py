"""Baseline shape tests for the ``cost_match`` module.

As of v4.2.2 the module is **scaffolding-only** — manifest + router with
a single ``_health`` endpoint + event-name constants + en/de/ru locale
bundle. The T12 work (three-tier matcher: exact → semantic → needs-
review, against CWICR for assembly material layers) has not landed yet.

This file pins the *current* surface so the eventual T12 implementation
will fail loudly when it changes any of:

  * manifest identity (name / category / dependencies / auto_install)
  * router prefix + ``_health`` response payload (used by the module
    loader and the dashboards health roll-up)
  * event-taxonomy constants emitted on the event bus (downstream
    subscribers in finance / dashboards / audit-log greppably bind to
    these strings)
  * locale-bundle parity en/de/ru (release gate: no missing
    translations slipping into a release)

Sister T00 wiring tests already live in ``test_dashboards_scaffolding``
(manifest fields, router importability, event source-module). This file
adds the missing module-scoped baselines: health-endpoint round-trip,
locale parity at the JSON-file level, and translate() fall-through
behaviour for the one user-facing message that already exists.

When the T12 matcher lands, this file should grow a happy-path test
(exact-match returns the CWICR row, semantic stage degrades to needs-
review when ``[semantic]`` isn't installed, Decimal-typed unit-rate +
currency are propagated from the source cost item, project-scope auth
is enforced on every endpoint). Until then, the scaffolding tests below
are the contract.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.modules.cost_match import events
from app.modules.cost_match.manifest import manifest
from app.modules.cost_match.messages import (
    DEFAULT_LOCALE,
    available_locales,
    is_key_present,
    translate,
)
from app.modules.cost_match.router import router

# ── Manifest identity ──────────────────────────────────────────────────────


class TestManifest:
    def test_module_identity(self) -> None:
        assert manifest.name == "oe_cost_match"
        assert manifest.display_name == "Cost Match"
        assert manifest.category == "core"
        assert manifest.enabled is True
        assert manifest.auto_install is True

    def test_dependencies_are_declared(self) -> None:
        # Hard deps: users (auth), projects (scoping), costs (CWICR data),
        # dashboards (snapshot infra reused by the matcher).
        for required in ("oe_users", "oe_projects", "oe_costs", "oe_dashboards"):
            assert required in manifest.depends, f"missing hard dep: {required}"
        # Semantic stage degrades gracefully when [semantic] extra is absent —
        # oe_ai stays optional, never required.
        assert "oe_ai" in manifest.optional_depends


# ── Router + health endpoint ───────────────────────────────────────────────


class TestRouter:
    def test_router_prefix_and_health_route_registered(self) -> None:
        paths = {route.path for route in router.routes}
        assert "/cost-match/_health" in paths

    def test_health_endpoint_returns_module_metadata(self) -> None:
        """End-to-end round-trip via TestClient — catches handler
        signature regressions (async/await, return-type) that a pure
        route-table inspection misses.
        """
        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)

        resp = client.get("/cost-match/_health")
        assert resp.status_code == 200
        body = resp.json()
        assert body == {
            "module": "oe_cost_match",
            "version": manifest.version,
            "status": "healthy",
        }


# ── Event taxonomy ─────────────────────────────────────────────────────────


class TestEvents:
    def test_source_module_matches_manifest(self) -> None:
        assert manifest.name == events.SOURCE_MODULE

    def test_lifecycle_event_names_are_stable(self) -> None:
        # Subscribers (finance roll-up, dashboards refresh, audit log)
        # bind to these literal strings — renaming is a breaking change.
        assert events.MATCH_COMPLETED == "cost.match.completed"
        assert events.MATCH_REVIEWED == "cost.match.reviewed"


# ── i18n bundle parity ─────────────────────────────────────────────────────


def _load_locale_keys(locale: str) -> set[str]:
    path = Path(__file__).resolve().parents[2] / "app" / "modules" / "cost_match" / "messages" / f"{locale}.json"
    with path.open(encoding="utf-8") as fh:
        return set(json.load(fh).keys())


class TestMessages:
    def test_default_locale_is_english(self) -> None:
        assert DEFAULT_LOCALE == "en"

    def test_en_de_ru_present(self) -> None:
        locales = set(available_locales())
        for required in ("en", "de", "ru"):
            assert required in locales, f"missing locale bundle: {required}"

    def test_locale_key_parity(self) -> None:
        """Release gate: every en key must also exist in de + ru."""
        en_keys = _load_locale_keys("en")
        de_keys = _load_locale_keys("de")
        ru_keys = _load_locale_keys("ru")
        assert en_keys == de_keys, f"DE missing: {en_keys - de_keys}; DE extra: {de_keys - en_keys}"
        assert en_keys == ru_keys, f"RU missing: {en_keys - ru_keys}; RU extra: {ru_keys - en_keys}"

    def test_translate_resolves_known_key(self) -> None:
        # The semantic-not-installed hint is the only user-facing
        # message that already exists. Verify it actually resolves and
        # carries different copy per locale (not just stub copies).
        en = translate("match.semantic.not_installed", locale="en")
        de = translate("match.semantic.not_installed", locale="de")
        ru = translate("match.semantic.not_installed", locale="ru")

        # Not falling back to the raw key.
        for value in (en, de, ru):
            assert value != "match.semantic.not_installed"
            assert "[semantic]" in value, "must keep the literal extra name"

        # Each locale is a distinct translation, not a copy of en.
        assert de != en
        assert ru != en

    def test_translate_unknown_key_is_detected(self) -> None:
        # is_key_present is the safe pre-flight check used by handlers
        # before they call translate() — verify it actually returns False
        # for a non-existent key (so future handler code doesn't ship
        # silent fall-backs to the raw key string).
        assert is_key_present("common.ok") is True
        assert is_key_present("cost_match.nonexistent.key") is False


# ── Documented stub state (pin until T12 lands) ─────────────────────────────


class TestStubState:
    """When T12 ships these will start failing — that's the trigger to
    expand this file with real matcher behaviour (exact + semantic +
    needs-review tiers, Decimal-typed money, project-scope auth)."""

    def test_no_business_routes_yet(self) -> None:
        """Only the loader health-check is wired today. Any new route
        must arrive alongside auth + Decimal-money + i18n + tests."""
        non_health = [route.path for route in router.routes if route.path != "/cost-match/_health"]
        assert non_health == [], f"new cost_match routes shipped without matching test coverage: {non_health}"

    def test_models_module_not_yet_present(self) -> None:
        """Once T12 lands this import will succeed and this test should
        be replaced with real model coverage."""
        with pytest.raises(ModuleNotFoundError):
            import app.modules.cost_match.models  # noqa: F401
