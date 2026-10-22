# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The frozen record of the rules a procedure was set under, and its integrity digest.

Pure: the service passes the pinned catalogue and the facts, this module returns
plain JSON that is stored as is. Nothing here reads the catalogue again later, so
a catalogue that changes afterwards cannot change a stored snapshot.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from datetime import date
from typing import Any

from app.modules.procurement_concept import evaluator as ev
from app.modules.procurement_concept.catalogue import ProcurementCatalogue
from app.modules.procurement_concept.validators import RULE_CODES

# Rules whose outcome is part of a snapshot, and that a person may override.
OUTCOME_RULES = ("procedure_allowed_for_value", "lots_aggregated_for_threshold", "threshold_source_confirmed")
OUTCOMES = ("pass", "warn", "fail")


def _plain(value: Any) -> Any:
    """JSON-safe copy: decimals and dates become strings, tuples lists."""
    return json.loads(json.dumps(value, default=str))


def digest_of(content: dict[str, Any]) -> str:
    """sha256 of the canonical JSON of ``content``."""
    raw = json.dumps(_plain(content), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def content_of(row: Any) -> dict[str, Any]:
    """The part of a stored snapshot the digest covers."""
    return {
        "procedure_code": row.procedure_code,
        "catalogue": [row.catalogue_source, row.catalogue_id, row.catalogue_version],
        "checked_on": row.checked_on,
        "inputs": row.inputs,
        "rules": row.rules,
        "result": row.result,
    }


def _outcomes(findings: Sequence[dict[str, Any]]) -> list[dict[str, str]]:
    out = []
    for key in OUTCOME_RULES:
        mine = [f for f in findings if f.get("code") in RULE_CODES[key]]
        if not mine:
            outcome = "pass"
        else:
            outcome = "fail" if any(f.get("severity") != ev.WARNING for f in mine) else "warn"
        out.append({"rule_code": key, "outcome": outcome})
    return out


def build_snapshot(
    catalogue: ProcurementCatalogue,
    facts: ev.ConceptFacts,
    pkg: ev.PackageFacts,
    packages: Sequence[ev.PackageFacts],
    day: date,
    *,
    catalogue_pin: tuple[str, str, int],
) -> dict[str, Any]:
    """Everything the evaluator used and decided for ``pkg`` on ``day``, as plain JSON."""
    view = ev.threshold_view(catalogue, facts, pkg, packages, day)
    findings = ev.procedure_findings(catalogue, facts, pkg, packages, day)
    ck = ev.contract_kind_of(catalogue, pkg)
    rules: list[dict[str, Any]] = []
    for t in view.thresholds:
        rules.append(
            {
                "id": ":".join(
                    ["threshold", facts.jurisdiction, str(t["contract_kind"]), str(t["client_type"]), str(t["effect"])]
                    + [str(t["valid_from"] or "")]
                ),
                "kind": "threshold",
                **t,
            }
        )
    if pkg.small_lot_exemption and ck is not None:
        lot = ev._small_lot_rule(catalogue, facts, ck)
        if lot is not None:
            rules.append(
                {
                    "id": f"lot_rule:{lot.code}",
                    "kind": "lot_rule",
                    "rule_kind": lot.kind,
                    "contract_kind": lot.contract_kind,
                    "max_lot_value": lot.max_lot_value,
                    "max_share_pct": lot.max_share_pct,
                    "currency": lot.currency,
                    "source_url": lot.source_url,
                    "review_status": lot.review_status.value,
                    "valid_from": lot.valid_from.isoformat() if lot.valid_from else None,
                    "valid_to": lot.valid_to.isoformat() if lot.valid_to else None,
                }
            )
    proc = catalogue.procedure(pkg.procedure_code)
    if proc is not None:
        rules.append(
            {
                "id": f"procedure:{proc.code}",
                "kind": "procedure",
                "competition": proc.competition,
                "sector": proc.sector,
                "tender_basis_allowed": list(proc.tender_basis_allowed),
                "min_bidders": proc.min_bidders,
            }
        )
    codes = {f.get("code") for f in findings}
    procedure_allowed = not codes & set(
        RULE_CODES["procedure_allowed_for_value"] + RULE_CODES["lots_aggregated_for_threshold"]
    )
    inputs = {
        "jurisdiction": facts.jurisdiction,
        "client_type": facts.client_type,
        "public_client": facts.public_client,
        "vat_rate_pct": str(facts.vat_rate_pct),
        "package_code": pkg.code,
        "contract_kind": ck,
        "estimated_value": None if pkg.estimated_value is None else str(pkg.estimated_value),
        "aggregated_value": None if view.aggregated_value is None else str(view.aggregated_value),
        "currency": pkg.currency,
        "small_lot_exemption": pkg.small_lot_exemption,
        "tender_basis": pkg.tender_basis,
        "procedure_code": pkg.procedure_code,
    }
    result = {
        "status": view.status,
        "allowed": view.allowed,
        "small_lot_exempt": view.small_lot_exempt,
        "procedure_allowed": procedure_allowed,
        # The catalogue as a whole stays marked until someone confirms it on its sources.
        "catalogue_review_status": catalogue.review_status.value,
        "findings": findings,
        "outcomes": _outcomes(findings),
    }
    source, cid, version = catalogue_pin
    body = {
        "procedure_code": pkg.procedure_code,
        "catalogue_source": source,
        "catalogue_id": cid,
        "catalogue_version": version,
        "checked_on": day.isoformat(),
        "inputs": _plain(inputs),
        "rules": _plain(rules),
        "result": _plain(result),
    }
    body["digest"] = digest_of(
        {
            "procedure_code": body["procedure_code"],
            "catalogue": [source, cid, version],
            "checked_on": body["checked_on"],
            "inputs": body["inputs"],
            "rules": body["rules"],
            "result": body["result"],
        }
    )
    return body
