# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Hook through which regional packs supply payment-application forms and lien-waiver rules.

Core owns the neutral billing records (progress claims, schedule of values,
retention, stored materials, lien-waiver records) and the figures a payment
application is made of (:mod:`app.modules.contracts.pay_application`). The
printed form those figures go on, and the law a lien waiver is signed under,
belong to a market. A regional pack registers them here from a
``billing_forms.py`` next to its manifest; core never names a country.

A form is served at ``/contracts/progress-claims/{claim_id}/{slug}`` (JSON)
and ``.../{slug}/pdf``. A project that is not eligible for a form gets 404,
as if the form did not exist.

Providers are discovered by scanning ``app/modules/*/billing_forms.py`` once,
whether or not the pack's module is switched on, so an install that used a
form before this hook existed keeps it.
"""

from __future__ import annotations

import importlib
import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

#: Signature of a project gate: ``(country_code, address) -> eligible``.
ProjectGate = Callable[[str | None, Any], bool]


@dataclass(frozen=True)
class PayApplicationForm:
    """A printed payment-application form a regional pack supplies.

    Attributes:
        slug: URL segment the form is served under; unique across packs.
        module: Module that supplies it (``oe_us_pack``).
        title: The form's own name, in the language it is printed in.
        markets: ISO 3166-1 alpha-2 markets the form belongs to.
        is_eligible: Project gate; False means the form does not exist for it.
        render_pdf: Draws the form from the neutral payment-application dict.
        filename_prefix: Prefix of the downloaded PDF's file name.
        language: Language the printed form is written in.
    """

    slug: str
    module: str
    title: str
    markets: tuple[str, ...]
    is_eligible: ProjectGate
    render_pdf: Callable[[dict[str, Any]], bytes]
    filename_prefix: str
    language: str = "en"


@dataclass(frozen=True)
class LienWaiverRules:
    """Lien-waiver law of one market, supplied by its regional pack.

    Attributes:
        module: Module that supplies the rules.
        markets: Markets the rules apply to.
        is_eligible: Project gate.
        statutory_form: ``(jurisdiction) -> form reference or None``; a
            reference is stored on the waiver record so the signed form
            can be checked against the one the law prescribes.
        templates: Template descriptors (id, waiver type, jurisdiction, title).
    """

    module: str
    markets: tuple[str, ...]
    is_eligible: ProjectGate
    statutory_form: Callable[[str | None, str], dict[str, Any] | None]
    templates: tuple[dict[str, Any], ...] = field(default_factory=tuple)


_FORMS: dict[str, PayApplicationForm] = {}
_WAIVER_RULES: list[LienWaiverRules] = []
_discovered = False
_lock = threading.Lock()


def register_form(form: PayApplicationForm) -> None:
    """Register a form; a second registration of the same slug replaces the first."""
    _FORMS[form.slug] = form


def register_lien_waiver_rules(rules: LienWaiverRules) -> None:
    """Register a market's lien-waiver rules (idempotent per module)."""
    _WAIVER_RULES[:] = [r for r in _WAIVER_RULES if r.module != rules.module]
    _WAIVER_RULES.append(rules)


def discover() -> None:
    """Import every ``app/modules/*/billing_forms.py`` once; each registers itself."""
    global _discovered
    if _discovered:
        return
    with _lock:
        if _discovered:
            return
        modules_dir = Path(__file__).resolve().parent.parent
        for provider in sorted(modules_dir.glob("*/billing_forms.py")):
            try:
                importlib.import_module(f"app.modules.{provider.parent.name}.billing_forms")
            except Exception:  # noqa: BLE001 - one broken pack must not hide every other form
                logger.warning("pay_application_forms: cannot import %s", provider, exc_info=True)
        _discovered = True


def forms() -> list[PayApplicationForm]:
    """Every registered form, by slug."""
    discover()
    return [_FORMS[k] for k in sorted(_FORMS)]


def get_form(slug: str) -> PayApplicationForm | None:
    """The form registered under ``slug``, or None."""
    discover()
    return _FORMS.get(slug)


def eligible_forms(country_code: str | None, address: Any = None) -> list[PayApplicationForm]:
    """Forms a project with this country / address may use."""
    return [f for f in forms() if f.is_eligible(country_code, address)]


def lien_waiver_rules_for(country_code: str | None, address: Any = None) -> LienWaiverRules | None:
    """The lien-waiver rules that govern a project, or None where no pack supplies any."""
    discover()
    for rules in _WAIVER_RULES:
        if rules.is_eligible(country_code, address):
            return rules
    return None
