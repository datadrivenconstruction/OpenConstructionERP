# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Procurement profile, schema v2: the legal values of one jurisdiction, each sourced and dated.

A profile is pure data (``profiles/<code>.json``). Its header names the
jurisdiction (``EU``, an ISO 3166-1 country, an ISO 3166-2 subdivision), the
parent it overrides, and the authority types it knows. Its sections hold the
values: thresholds, procedures (minimum deadlines, invitations, justification),
publication channels, requirements, award, notification (standstill),
signature level and locale. Every legal value is a :class:`ProfileValue`:
value, unit, source, retrieval date, confidence, review status and an
effective window.

Resolution (:func:`resolve`) walks the parent chain root first (EU, then the
country, then a subdivision) and lets the most specific level that has a value
for a path win; a child holds only its overrides. On a day, the value whose
window covers it is taken; if only an expired one exists it is taken and marked
``stale``. A value is ``confirmed`` only when this instance confirmed exactly
that value (path + hash); everything else is advisory and never blocks.

The v1 catalogues stay what the evaluator reads; :func:`migrate_v1` derives v2
profiles from them and lists every value it could not carry (no source or no
effective date) instead of inventing one.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.modules.procurement_concept.catalogue import (
    CODE_PATTERN,
    ProcurementCatalogue,
    parse_amount,
)
from app.modules.procurement_concept.profile_codes import is_known_jurisdiction
from app.modules.project_governance.catalogue import ReviewStatus

PROFILE_SCHEMA_VERSION = 2
PROFILE_DIR = Path(__file__).with_name("profiles")

STATUS_CONFIRMED = "confirmed"
STATUS_UNCONFIRMED = "unconfirmed"
STATUS_STALE = "stale"

SIGNATURE_LEVELS = ("text_form", "advanced", "qualified")
REQUIREMENT_STAGES = ("submission", "selection", "award", "contract", "execution")
PUBLICATION_WHEN = ("always", "above_threshold", "below_threshold", "never")

# v1 jurisdiction code -> (v2 jurisdiction, parent). A company catalogue with other codes passes its own map.
V1_JURISDICTIONS: dict[str, tuple[str, str | None]] = {
    "eu": ("EU", None),
    "de_national": ("DE", "EU"),
    "uk": ("GB", None),
    "us_federal": ("US", None),
}


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ProfileValue(_Frozen):
    """One legal value with where it comes from and when it holds."""

    value: Any
    unit: str | None = Field(default=None, max_length=20)
    source_url: str | None = None
    source_ref: str | None = Field(default=None, max_length=300)
    retrieved_at: date | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    review_status: ReviewStatus = ReviewStatus.unconfirmed
    confirmed_by: str | None = None
    confirmed_at: datetime | None = None
    effective_from: date | None = None
    effective_to: date | None = None

    def valid_on(self, day: date) -> bool:
        return (self.effective_from is None or self.effective_from <= day) and (
            self.effective_to is None or day <= self.effective_to
        )

    def value_hash(self) -> str:
        """sha256 of what a confirmation vouches for: the figure, its unit, its source and its window."""
        body = {
            "value": self.value,
            "unit": self.unit,
            "source_url": self.source_url,
            "source_ref": self.source_ref,
            "effective_from": self.effective_from,
            "effective_to": self.effective_to,
        }
        raw = json.dumps(body, sort_keys=True, separators=(",", ":"), default=str, ensure_ascii=False)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class ProfileHeader(_Frozen):
    jurisdiction: str = Field(min_length=2, max_length=6)
    parent: str | None = None
    name_key: str = ""
    # v1 jurisdiction codes this profile answers for (``ConceptFacts.jurisdiction``).
    legacy_codes: tuple[str, ...] = ()
    authority_types: tuple[str, ...] = ()
    private_authority_type: str = Field(default="private", pattern=CODE_PATTERN, max_length=20)


class ThresholdRule(_Frozen):
    contract_type: Literal["works", "supplies", "services", "design_services", "concession", "light_touch"]
    authority_type: str = Field(pattern=CODE_PATTERN, max_length=20)
    effect: Literal["above_requires_publication", "below_allows_direct", "below_allows_simplified"]
    vat_basis: Literal["net", "gross"] = "net"
    # all_lots: the estimated value of every lot counts against the threshold.
    lot_aggregation: Literal["all_lots", "per_lot"] = "all_lots"
    allowed_above: tuple[str, ...] = ()
    allowed_below: tuple[str, ...] = ()
    amount: ProfileValue


class Deadline(_Frozen):
    # tender, request_to_participate, tender_urgent, tender_electronic, ...
    variant: str = Field(pattern=CODE_PATTERN, max_length=40)
    days: ProfileValue


class ProcedureRule(_Frozen):
    code: str = Field(pattern=CODE_PATTERN, max_length=64)
    min_deadlines: tuple[Deadline, ...] = ()
    min_invitations: ProfileValue | None = None
    justification_required: ProfileValue | None = None


class PublicationRule(_Frozen):
    channel: str = Field(pattern=CODE_PATTERN, max_length=40)
    format: str = Field(pattern=CODE_PATTERN, max_length=40)
    format_version: str = Field(default="", max_length=20)
    # value: one of PUBLICATION_WHEN
    mandatory: ProfileValue


class RequirementRule(_Frozen):
    code: str = Field(pattern=CODE_PATTERN, max_length=64)
    stage: Literal["submission", "selection", "award", "contract", "execution"]
    required: ProfileValue


class AwardRules(_Frozen):
    criteria: ProfileValue | None = None
    weights_published: ProfileValue | None = None
    abnormally_low_rule: ProfileValue | None = None


class Standstill(_Frozen):
    channel: str = Field(pattern=CODE_PATTERN, max_length=40)
    days: ProfileValue


class NotificationRules(_Frozen):
    standstill: tuple[Standstill, ...] = ()


class SignatureRules(_Frozen):
    framework: Literal["eidas", "local"] = "eidas"
    # value: one of SIGNATURE_LEVELS
    bid_level: ProfileValue | None = None


class LocaleRules(_Frozen):
    languages: ProfileValue | None = None
    currency: ProfileValue | None = None
    vat_basis: ProfileValue | None = None


class ProcurementProfile(_Frozen):
    schema_version: Literal[2] = 2
    header: ProfileHeader
    thresholds: tuple[ThresholdRule, ...] = ()
    procedures: tuple[ProcedureRule, ...] = ()
    publication: tuple[PublicationRule, ...] = ()
    requirements: tuple[RequirementRule, ...] = ()
    award: AwardRules = AwardRules()
    notification: NotificationRules = NotificationRules()
    signature: SignatureRules = SignatureRules()
    locale: LocaleRules = LocaleRules()

    @property
    def code(self) -> str:
        return self.header.jurisdiction


@dataclass(frozen=True)
class Entry:
    """One value of a profile at its path, with the plain attributes of the item that holds it."""

    path: str
    value: ProfileValue
    attrs: dict[str, Any] = field(default_factory=dict)


def entries(profile: ProcurementProfile) -> list[Entry]:
    """Every value of ``profile`` as ``(path, value, attrs)``; time slices of one path repeat the path."""
    out: list[Entry] = []
    for t in profile.thresholds:
        attrs = t.model_dump(mode="json", exclude={"amount"})
        out.append(Entry(f"thresholds/{t.contract_type}/{t.authority_type}/{t.effect}", t.amount, attrs))
    for p in profile.procedures:
        for d in p.min_deadlines:
            out.append(Entry(f"procedures/{p.code}/min_deadline/{d.variant}", d.days))
        if p.min_invitations is not None:
            out.append(Entry(f"procedures/{p.code}/min_invitations", p.min_invitations))
        if p.justification_required is not None:
            out.append(Entry(f"procedures/{p.code}/justification_required", p.justification_required))
    for pub in profile.publication:
        attrs = {"format": pub.format, "format_version": pub.format_version}
        out.append(Entry(f"publication/{pub.channel}/mandatory", pub.mandatory, attrs))
    for r in profile.requirements:
        out.append(Entry(f"requirements/{r.code}/{r.stage}", r.required))
    for name in ("criteria", "weights_published", "abnormally_low_rule"):
        v = getattr(profile.award, name)
        if v is not None:
            out.append(Entry(f"award/{name}", v))
    for s in profile.notification.standstill:
        out.append(Entry(f"notification/standstill/{s.channel}", s.days))
    if profile.signature.bid_level is not None:
        out.append(
            Entry("signature/bid_level", profile.signature.bid_level, {"framework": profile.signature.framework})
        )
    for name in ("languages", "currency", "vat_basis"):
        v = getattr(profile.locale, name)
        if v is not None:
            out.append(Entry(f"locale/{name}", v))
    return out


# ── chain and validation ────────────────────────────────────────────────


class ProfileChainError(ValueError):
    """A parent that does not exist, or a chain that returns to itself."""


def chain_of(code: str, profiles: Mapping[str, ProcurementProfile]) -> list[str]:
    """Codes from the root to ``code`` (``["EU", "DE", "DE-BY"]``)."""
    out: list[str] = []
    cur: str | None = code
    while cur is not None:
        if cur in out:
            raise ProfileChainError(f"parent_cycle: {' -> '.join([*out, cur])}")
        prof = profiles.get(cur)
        if prof is None:
            raise ProfileChainError(f"unknown_profile: {cur}")
        out.append(cur)
        cur = prof.header.parent
    return list(reversed(out))


def _check_value(errors: list[str], where: str, v: ProfileValue) -> None:
    if not v.source_url:
        errors.append(f"value_without_source: {where}")
    if v.effective_from is None:
        errors.append(f"value_without_effective_from: {where}")
    if v.effective_from and v.effective_to and v.effective_to < v.effective_from:
        errors.append(f"value_window_inverted: {where}")


def validate_profiles(profiles: Mapping[str, ProcurementProfile]) -> list[str]:
    """Rules every profile set must pass (the CI gate); empty list = valid."""
    errors: list[str] = []
    for key, prof in sorted(profiles.items()):
        h = prof.header
        if key != h.jurisdiction:
            errors.append(f"profile_key_mismatch: {key}/{h.jurisdiction}")
        if not is_known_jurisdiction(h.jurisdiction):
            errors.append(f"unknown_jurisdiction: {h.jurisdiction}")
        if h.parent is not None and not is_known_jurisdiction(h.parent):
            errors.append(f"unknown_jurisdiction: {h.parent}")
        known_authorities = set(h.authority_types)
        try:
            for level in chain_of(key, profiles):
                known_authorities |= set(profiles[level].header.authority_types)
        except ProfileChainError as exc:
            errors.append(f"{exc}" if "cycle" in str(exc) else f"unknown_parent: {key}/{h.parent}")
        slices: dict[str, list[ProfileValue]] = {}
        for e in entries(prof):
            where = f"{key}/{e.path}"
            _check_value(errors, where, e.value)
            slices.setdefault(e.path, []).append(e.value)
            if e.path.startswith("thresholds/"):
                if e.attrs["authority_type"] not in known_authorities:
                    errors.append(f"threshold_unknown_authority_type: {where}")
                try:
                    if parse_amount(e.value.value) <= 0:
                        errors.append(f"threshold_amount_not_positive: {where}")
                except ValueError:
                    errors.append(f"threshold_amount_invalid: {where}")
            if e.path == "signature/bid_level" and e.value.value not in SIGNATURE_LEVELS:
                errors.append(f"signature_level_unknown: {where}")
            if e.path.startswith("publication/") and e.value.value not in PUBLICATION_WHEN:
                errors.append(f"publication_when_unknown: {where}")
        for path, rows in slices.items():
            rows = sorted(rows, key=lambda v: v.effective_from or date.min)
            for a, b in zip(rows, rows[1:], strict=False):
                if a.effective_to is None or (b.effective_from and b.effective_from <= a.effective_to):
                    errors.append(f"value_window_overlap: {key}/{path}")
    return errors


# ── resolution ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ResolvedValue:
    path: str
    value: ProfileValue
    attrs: dict[str, Any]
    origin: str
    status: str
    value_hash: str

    def as_json(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "origin": self.origin,
            "status": self.status,
            "value_hash": self.value_hash,
            "attrs": self.attrs,
            **self.value.model_dump(mode="json"),
        }


@dataclass(frozen=True)
class ResolvedProfile:
    jurisdiction: str
    chain: tuple[str, ...]
    day: date
    values: dict[str, ResolvedValue]

    def under(self, *prefixes: str) -> list[ResolvedValue]:
        return [v for p, v in sorted(self.values.items()) if any(p.startswith(x) for x in prefixes)]


def _pick(rows: list[Entry], day: date) -> tuple[Entry, bool] | None:
    """The slice valid on ``day``, else the latest expired one (stale); future slices never count."""
    current = [e for e in rows if e.value.valid_on(day)]
    if current:
        return max(current, key=lambda e: e.value.effective_from or date.min), False
    expired = [e for e in rows if e.value.effective_to is not None and e.value.effective_to < day]
    if expired:
        return max(expired, key=lambda e: e.value.effective_to or date.min), True
    return None


def resolve(
    code: str,
    profiles: Mapping[str, ProcurementProfile],
    day: date,
    confirmed: Iterable[tuple[str, str]] = (),
) -> ResolvedProfile:
    """Merge the chain of ``code`` for ``day``; ``confirmed`` = this instance's ``(path, value_hash)`` pairs."""
    chain = chain_of(code, profiles)
    ok = set(confirmed)
    values: dict[str, ResolvedValue] = {}
    for level in chain:
        by_path: dict[str, list[Entry]] = {}
        for e in entries(profiles[level]):
            by_path.setdefault(e.path, []).append(e)
        for path, rows in by_path.items():
            picked = _pick(rows, day)
            if picked is None:
                continue
            e, stale = picked
            h = e.value.value_hash()
            status = STATUS_STALE if stale else STATUS_CONFIRMED if (path, h) in ok else STATUS_UNCONFIRMED
            values[path] = ResolvedValue(path, e.value, e.attrs, level, status, h)
    return ResolvedProfile(code, tuple(chain), day, values)


def load_shipped(directory: Path = PROFILE_DIR) -> dict[str, ProcurementProfile]:
    """Every shipped profile by jurisdiction code (v1-shaped files are refused: migrate them first)."""
    out: dict[str, ProcurementProfile] = {}
    for f in sorted(directory.glob("*.json")):
        prof = ProcurementProfile.model_validate(json.loads(f.read_text(encoding="utf-8")))
        out[prof.code] = prof
    return out


def profile_for_legacy(code: str | None, profiles: Mapping[str, ProcurementProfile]) -> str | None:
    """The v2 jurisdiction a v1 code (``de_national``) maps to, if any profile claims it."""
    if not code:
        return None
    if code in profiles:
        return code
    return next((p.code for p in profiles.values() if code in p.header.legacy_codes), None)


# ── v1 -> v2 migrator ───────────────────────────────────────────────────


@dataclass
class Migration:
    profiles: dict[str, ProcurementProfile]
    # Values v1 holds that v2 cannot carry without inventing a source or a date.
    gaps: list[str]


def _pv(value: Any, unit: str | None, src: Any) -> ProfileValue:
    return ProfileValue(
        value=value,
        unit=unit,
        source_url=src.source_url,
        # An upstream v1 review is no confirmation for an instance: every migrated value starts unconfirmed.
        review_status=ReviewStatus.unconfirmed,
        effective_from=getattr(src, "valid_from", None),
        effective_to=getattr(src, "valid_to", None),
    )


def migrate_v1(
    catalogue: ProcurementCatalogue,
    mapping: Mapping[str, tuple[str, str | None]] = V1_JURISDICTIONS,
    parents: Mapping[str, ProcurementProfile] | None = None,
) -> Migration:
    """v2 profiles from a v1 catalogue; a child keeps only what differs from its parent.

    ``parents`` are profiles already migrated (e.g. ``EU`` from ``eu.json``) that a
    child may override; a parent produced from the same catalogue is used too.
    """
    gaps: list[str] = []
    made: dict[str, ProcurementProfile] = {}
    lot_aggregated = {
        (j.code, r.contract_kind) for j in catalogue.jurisdictions for r in j.lot_rules if r.kind == "aggregation"
    }
    for j in catalogue.jurisdictions:
        if j.code not in mapping:
            if j.thresholds or j.lot_rules or j.min_periods:
                gaps.append(f"jurisdiction_not_mapped: {catalogue.id}/{j.code}")
            continue
        code, parent = mapping[j.code]
        thresholds = []
        for t in j.thresholds:
            where = f"{catalogue.id}/{j.code}/thresholds/{t.contract_kind}/{t.client_type}/{t.effect}"
            if not t.source_url or t.valid_from is None:
                gaps.append(f"value_without_source_or_date: {where}")
                continue
            thresholds.append(
                ThresholdRule(
                    contract_type=t.contract_kind,
                    authority_type=t.client_type,
                    effect=t.effect,
                    vat_basis=t.vat_basis,
                    lot_aggregation="all_lots" if (j.code, t.contract_kind) in lot_aggregated else "per_lot",
                    allowed_above=t.allowed_above,
                    allowed_below=t.allowed_below,
                    amount=_pv(t.amount, t.currency, t),
                )
            )
        deadlines: dict[str, list[Deadline]] = {}
        for m in j.min_periods:
            where = f"{catalogue.id}/{j.code}/procedures/{m.procedure}/min_deadline/{m.stage}"
            if not m.source_url or m.valid_from is None:
                gaps.append(f"value_without_source_or_date: {where}")
                continue
            deadlines.setdefault(m.procedure, []).append(Deadline(variant=m.stage, days=_pv(m.days, "days", m)))
        for r in j.lot_rules:
            if r.kind != "aggregation":
                gaps.append(f"lot_rule_stays_in_v1: {catalogue.id}/{j.code}/{r.code}")
        made[code] = ProcurementProfile(
            header=ProfileHeader(
                jurisdiction=code,
                parent=parent,
                name_key=j.name_key,
                legacy_codes=(j.code,),
                authority_types=j.client_types,
                private_authority_type=j.private_client_type,
            ),
            thresholds=tuple(thresholds),
            procedures=tuple(ProcedureRule(code=c, min_deadlines=tuple(d)) for c, d in sorted(deadlines.items())),
        )
    known = {**(parents or {}), **made}
    for code, prof in list(made.items()):
        parent = prof.header.parent
        if parent is not None and parent in known:
            made[code] = _overrides_only(prof, known[parent])
    return Migration(made, gaps)


def _overrides_only(child: ProcurementProfile, parent: ProcurementProfile) -> ProcurementProfile:
    """``child`` without the values (and authority types) it shares with ``parent`` unchanged."""

    def sig(e: Entry) -> tuple[str, str, str]:
        return e.path, e.value.value_hash(), json.dumps(e.attrs, sort_keys=True)

    inherited = {sig(e) for e in entries(parent)}
    thresholds = tuple(
        t
        for t in child.thresholds
        if sig(
            Entry(
                f"thresholds/{t.contract_type}/{t.authority_type}/{t.effect}",
                t.amount,
                t.model_dump(mode="json", exclude={"amount"}),
            )
        )
        not in inherited
    )
    procedures = []
    for p in child.procedures:
        kept = tuple(
            d
            for d in p.min_deadlines
            if sig(Entry(f"procedures/{p.code}/min_deadline/{d.variant}", d.days)) not in inherited
        )
        if kept:
            procedures.append(p.model_copy(update={"min_deadlines": kept}))
    own_authorities = tuple(a for a in child.header.authority_types if a not in parent.header.authority_types)
    header = child.header.model_copy(update={"authority_types": own_authorities})
    return child.model_copy(update={"header": header, "thresholds": thresholds, "procedures": tuple(procedures)})


def dump_profile(profile: ProcurementProfile) -> str:
    """Canonical JSON text of a profile (the shipped file form)."""
    body = profile.model_dump(mode="json", exclude_defaults=False)
    return json.dumps(body, indent=2, ensure_ascii=False) + "\n"
