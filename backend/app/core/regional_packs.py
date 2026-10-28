# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠app.core.regional_packs - resolve a project's regional pack at runtime.

A regional pack declares what a market expects: its currency, its date and
number formats, its standards, and - the part this module serves - its
``measurement_system``. Until now every one of those values was readable only
through the pack's own ``GET /config/`` endpoint, so a pack changed what an
API caller could *see* and never what the platform *did*.

This module is the lookup that closes that gap for the measurement system. It
reads the packs' own identity fields rather than a hand-written country table:
each pack declares ``countries`` (ISO 3166-1 alpha-2) and ``region_code``, and
a project carries ``country_code`` and ``region``. Country is tried first
because it is the explicit ISO-2 column; ``region`` is free text that the
schema deliberately leaves open to any market, so it is only ever matched as
an exact fallback against a pack's own ``region_code``.

Resolution is deliberately conservative. A country claimed by several packs
resolves only when those packs agree - the three US packs all declare
``imperial``, so ``"US"`` is unambiguous, while a disagreement would return
``None``. Anything unrecognised also returns ``None``, which callers must
treat as "not configured" rather than as a default.

The same lookup serves a pack's ``progress_billing`` figures (retention,
release events, stored materials, subcontractor payment evidence, billing
cycle, change-line codes) through :func:`resolve_progress_billing`. Those are
money figures, so that resolver is stricter still: it reads national packs
only and a block keyed by the exact country, so a pack that claims several
countries can never lend one country's figures to another.
"""

from __future__ import annotations

import copy
import importlib
from functools import lru_cache
from typing import Any

#: The regional packs consulted at runtime, listed rather than discovered from
#: the filesystem so the import set is explicit and stable. A pack added later
#: belongs here; the integration test
#: ``test_us_pack_measurement_system_governs_boq_validation`` fails when this
#: tuple drifts from the packs on disk.
PACK_CONFIG_MODULES: tuple[str, ...] = (
    "app.modules.asia_pac_pack.config",
    "app.modules.china_pack.config",
    "app.modules.dach_pack.config",
    "app.modules.india_pack.config",
    "app.modules.latam_pack.config",
    "app.modules.mexico_pack.config",
    "app.modules.middle_east_pack.config",
    "app.modules.russia_pack.config",
    "app.modules.sa_pack.config",
    "app.modules.uk_pack.config",
    "app.modules.us_ca_pack.config",
    "app.modules.us_pack.config",
    "app.modules.us_tx_pack.config",
)

#: The measurement systems a pack may declare. A pack naming anything else is
#: ignored rather than passed through, so a typo cannot reach a rule that
#: branches on the value.
_KNOWN_MEASUREMENT_SYSTEMS: frozenset[str] = frozenset({"metric", "imperial"})

#: The sub-keys of a country's ``progress_billing`` block that
#: :func:`resolve_progress_billing` returns. The answer always carries all of
#: them (``None`` where the pack writes nothing), and a key a pack adds beyond
#: these does not leak into the contract by accident.
PROGRESS_BILLING_KEYS: tuple[str, ...] = (
    "retention_policy",
    "release_events",
    "stored_materials",
    "sub_payment_requirements",
    "billing_cycle",
    "change_line_code_format",
)


@lru_cache(maxsize=1)
def pack_configs() -> tuple[dict[str, Any], ...]:
    """Return every regional pack configuration, imported once and cached.

    Returns:
        The ``PACK_CONFIG`` dict of each module in :data:`PACK_CONFIG_MODULES`,
        in that order. A module without a dict ``PACK_CONFIG`` is skipped.
    """
    configs: list[dict[str, Any]] = []
    for module_name in PACK_CONFIG_MODULES:
        config = getattr(importlib.import_module(module_name), "PACK_CONFIG", None)
        if isinstance(config, dict):
            configs.append(config)
    return tuple(configs)


def packs_for_country(country_code: str | None) -> tuple[dict[str, Any], ...]:
    """Return the packs that claim ``country_code`` in their ``countries`` list.

    Args:
        country_code: ISO 3166-1 alpha-2 code; case and surrounding space are
            ignored. ``None`` or blank matches nothing.

    Returns:
        The matching pack configurations, possibly empty. A country covered by
        both a national and a state pack matches all of them.
    """
    wanted = (country_code or "").strip().upper()
    if not wanted:
        return ()
    return tuple(
        config
        for config in pack_configs()
        if any(str(code).strip().upper() == wanted for code in config.get("countries") or ())
    )


def packs_for_region(region: str | None) -> tuple[dict[str, Any], ...]:
    """Return the packs whose ``region_code`` equals ``region``.

    Args:
        region: A project's region marker, for example ``"DACH"`` or ``"US"``.
            Case and surrounding space are ignored; ``None`` or blank matches
            nothing.

    Returns:
        The matching pack configurations, possibly empty. Only an exact match
        counts: ``region`` is an open free-text field, and guessing at
        near-misses would attach a market to a project that never chose one.
    """
    wanted = (region or "").strip().upper()
    if not wanted:
        return ()
    return tuple(config for config in pack_configs() if str(config.get("region_code") or "").strip().upper() == wanted)


def resolve_measurement_system(*, country_code: str | None = None, region: str | None = None) -> str | None:
    """Resolve the measurement system a project's regional pack declares.

    Country is tried first and region is used only when no pack claims the
    country, because ``country_code`` is a validated ISO-2 column while
    ``region`` is free text.

    Args:
        country_code: The project's ISO 3166-1 alpha-2 country code.
        region: The project's region marker, used as a fallback.

    Returns:
        ``"metric"`` or ``"imperial"`` when exactly one such value is declared
        by the matching packs, otherwise ``None``. ``None`` means "no pack
        answered"; it is not a default and callers must not substitute one.
    """
    candidates = packs_for_country(country_code) or packs_for_region(region)
    declared = {
        str(config.get("measurement_system") or "").strip().lower() for config in candidates
    } & _KNOWN_MEASUREMENT_SYSTEMS
    if len(declared) != 1:
        return None
    return declared.pop()


def _normalise_code(value: Any) -> str:
    return str(value or "").strip().upper()


def _is_national(config: dict[str, Any]) -> bool:
    """A state or provincial pack names its ``parent_pack``; a national one does not."""
    return not config.get("parent_pack")


def _progress_billing_block(config: dict[str, Any], country: str) -> dict[str, Any] | None:
    """Return the pack's ``progress_billing`` figures for exactly ``country``, or ``None``."""
    blocks = config.get("progress_billing")
    if not isinstance(blocks, dict):
        return None
    block = blocks.get(country)
    if not isinstance(block, dict):
        return None
    figures = {key: block.get(key) for key in PROGRESS_BILLING_KEYS}
    return figures if any(value is not None for value in figures.values()) else None


def _subdivision_retainage(country: str, subdivision_code: str | None) -> dict[str, Any] | None:
    """Return the retainage rules of the one subdivision pack matching the code, or ``None``."""
    wanted = _normalise_code(subdivision_code)
    if not wanted:
        return None
    matches = [
        config
        for config in pack_configs()
        if not _is_national(config)
        and _normalise_code(config.get("subdivision_code")) == wanted
        and any(_normalise_code(code) == country for code in config.get("countries") or ())
    ]
    if len(matches) != 1:
        return None
    pack = matches[0]
    state_rules = pack.get("state_rules")
    rules = state_rules.get("retainage") if isinstance(state_rules, dict) else None
    return {
        "subdivision_code": pack.get("subdivision_code"),
        "region_code": pack.get("region_code"),
        "retainage": copy.deepcopy(rules) if isinstance(rules, list) else [],
    }


def resolve_progress_billing(
    *,
    country_code: str | None = None,
    region: str | None = None,
    subdivision_code: str | None = None,
) -> dict[str, Any] | None:
    """Resolve the progress billing figures a project's national pack declares.

    Only national packs answer (a pack with a ``parent_pack`` is a state or
    province and never votes), and only from the block keyed by the exact
    country, so a pack that claims DE, AT and CH answers for DE alone when
    only DE is written. ``region`` is consulted only when no country is given,
    and then only when the matching packs claim exactly one country between
    them: a region such as ``"DACH"`` names a market, not a country, and
    picking one of its countries would be a guess. Packs that write nothing
    for the country stay silent; packs that write different figures for it
    cancel each other out and the answer is ``None``.

    Args:
        country_code: The project's ISO 3166-1 alpha-2 country code.
        region: The project's region marker, used only when ``country_code``
            is blank.
        subdivision_code: ISO 3166-2 code such as ``"US-CA"``. When exactly
            one subdivision pack of the resolved country carries it, that
            pack's retainage rules are attached; nothing else changes.

    Returns:
        ``None`` when no national pack answers. Otherwise a new dict (a deep
        copy, safe to mutate) with ``country_code`` (the country whose block
        answered), one entry per :data:`PROGRESS_BILLING_KEYS` holding the
        pack's value or ``None``, and ``subdivision``: ``None`` when no
        subdivision was given or none matched, else ``{"subdivision_code",
        "region_code", "retainage": [<the subdivision pack's retainage
        rules>]}``. ``None`` is not a default and callers must not substitute
        another country's figures for it.

    Inside the figures, ``retention_policy.stored_materials_rate`` of ``None``
    means stored materials are retained at the tier rate, with no separate
    rate; ``cap`` of ``None`` means the pack suggests no cap and the contract's
    agreed security sum governs. A figure under a ``public_client_`` key binds
    public awarding authorities only and must not be applied to every
    contract.
    """
    country = _normalise_code(country_code)
    if country:
        candidates = [config for config in packs_for_country(country) if _is_national(config)]
    else:
        candidates = [config for config in packs_for_region(region) if _is_national(config)]
        claimed = {_normalise_code(code) for config in candidates for code in config.get("countries") or ()}
        claimed.discard("")
        if len(claimed) != 1:
            return None
        country = claimed.pop()

    answers = [
        block for block in (_progress_billing_block(config, country) for config in candidates) if block is not None
    ]
    if not answers or any(answer != answers[0] for answer in answers[1:]):
        return None
    return {
        "country_code": country,
        **copy.deepcopy(answers[0]),
        "subdivision": _subdivision_retainage(country, subdivision_code),
    }
