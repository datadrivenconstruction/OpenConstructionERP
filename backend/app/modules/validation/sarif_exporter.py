"""SARIF v2.1.0 exporter for OpenConstructionERP validation reports.

Translates a :class:`ValidationReport` (from :mod:`app.core.validation.engine`
OR the persisted :class:`app.modules.validation.models.ValidationReport` ORM
row) into a SARIF v2.1.0 JSON-serialisable dict.

Why SARIF?
    SARIF is the OASIS-standard JSON schema for static-analysis tool output.
    GitHub Code Scanning, Azure DevOps, GitLab, VS Code's "Problems" panel
    and many enterprise security stacks consume SARIF directly.  Exporting
    validation reports as SARIF lets users plug OpenConstructionERP into the
    same pipelines they already use for code analysis.

Spec reference: https://docs.oasis-open.org/sarif/sarif/v2.1.0/sarif-v2.1.0.html

Public API:
    * :func:`report_to_sarif` — convert a report → SARIF dict.

Schema-completeness note:  We emit a *minimal-valid* SARIF document.  Optional
features (codeFlows, fixes, taxonomies, suppressions, conversion provenance)
are intentionally omitted — see the report at the bottom of the task.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from app.core.validation.engine import (
    RuleResult,
    Severity,
)
from app.core.validation.engine import (
    ValidationReport as EngineReport,
)

logger = logging.getLogger(__name__)

SARIF_VERSION = "2.1.0"
SARIF_SCHEMA = "https://json.schemastore.org/sarif-2.1.0.json"

TOOL_NAME = "OpenConstructionERP"
TOOL_INFORMATION_URI = "https://datadrivenconstruction.io/openconstructionerp"
TOOL_ORG = "DataDrivenConstruction"


# ── Severity mapping ────────────────────────────────────────────────────────


_SEVERITY_TO_LEVEL: dict[str, str] = {
    "error": "error",
    "warning": "warning",
    "info": "note",
}


def _level_for(severity: str | Severity) -> str:
    """Map our :class:`Severity` to a SARIF ``level`` string."""
    if isinstance(severity, Severity):
        severity = severity.value
    return _SEVERITY_TO_LEVEL.get(str(severity).lower(), "none")


def _get_tool_version() -> str:
    """Read the package version from pyproject — fall back to '0.0.0'."""
    try:
        from importlib.metadata import PackageNotFoundError, version

        try:
            return version("openconstructionerp")
        except PackageNotFoundError:
            pass
    except Exception:  # noqa: BLE001
        pass
    # Fallback: try to read pyproject.toml directly.
    try:
        from pathlib import Path

        pyproject = Path(__file__).resolve().parents[3] / "pyproject.toml"
        if pyproject.is_file():
            for line in pyproject.read_text(encoding="utf-8").splitlines():
                stripped = line.strip()
                if stripped.startswith("version") and "=" in stripped:
                    return stripped.split("=", 1)[1].strip().strip('"').strip("'")
    except Exception:  # noqa: BLE001
        pass
    return "0.0.0"


# ── Coercion helpers — accept both dataclass + ORM reports ─────────────────


def _normalize_report(report: Any) -> dict[str, Any]:
    """Pull the fields we need out of either an EngineReport or an ORM row.

    Both shapes are supported because callers may pass a fresh in-memory
    :class:`EngineReport` (from the engine) OR a hydrated ORM model
    :class:`app.modules.validation.models.ValidationReport`.
    """
    if isinstance(report, EngineReport):
        return {
            "id": report.id,
            "target_type": report.target_type,
            "target_id": report.target_id,
            "rule_sets": list(report.rule_sets_applied),
            "results": [
                {
                    "rule_id": r.rule_id,
                    "rule_name": r.rule_name,
                    "severity": (
                        r.severity.value if isinstance(r.severity, Severity) else str(r.severity)
                    ),
                    "category": (
                        r.category.value if hasattr(r.category, "value") else str(r.category)
                    ),
                    "passed": r.passed,
                    "message": r.message,
                    "element_ref": r.element_ref,
                    "details": dict(r.details or {}),
                    "suggestion": r.suggestion,
                }
                for r in report.results
            ],
            "timestamp": report.timestamp,
        }

    # ORM-row path (or any duck-typed dict-like)
    results_attr = getattr(report, "results", []) or []
    normalized_results: list[dict[str, Any]] = []
    for r in results_attr:
        if isinstance(r, RuleResult):
            normalized_results.append(
                {
                    "rule_id": r.rule_id,
                    "rule_name": r.rule_name,
                    "severity": (
                        r.severity.value if isinstance(r.severity, Severity) else str(r.severity)
                    ),
                    "category": (
                        r.category.value if hasattr(r.category, "value") else str(r.category)
                    ),
                    "passed": r.passed,
                    "message": r.message,
                    "element_ref": r.element_ref,
                    "details": dict(r.details or {}),
                    "suggestion": r.suggestion,
                }
            )
        elif isinstance(r, dict):
            severity = r.get("severity") or (
                "error"
                if (r.get("status") == "error")
                else "warning"
                if (r.get("status") == "warning")
                else "info"
                if (r.get("status") == "info")
                else "info"
            )
            normalized_results.append(
                {
                    "rule_id": r.get("rule_id", ""),
                    "rule_name": r.get("rule_name") or r.get("rule_id", ""),
                    "severity": severity,
                    "category": r.get("category", "compliance"),
                    "passed": r.get("passed", r.get("status") == "pass"),
                    "message": r.get("message", ""),
                    "element_ref": r.get("element_ref"),
                    "details": dict(r.get("details") or {}),
                    "suggestion": r.get("suggestion"),
                }
            )

    rule_set_str = getattr(report, "rule_set", "") or ""
    rule_sets = [s for s in rule_set_str.split("+") if s] if rule_set_str else []

    timestamp = getattr(report, "created_at", None) or datetime.now(UTC)

    return {
        "id": str(getattr(report, "id", "")),
        "target_type": getattr(report, "target_type", "") or "",
        "target_id": str(getattr(report, "target_id", "")) or "",
        "rule_sets": rule_sets,
        "results": normalized_results,
        "timestamp": timestamp,
    }


# ── Result/rule builders ────────────────────────────────────────────────────


def _build_rule_descriptor(rule_id: str, rule_name: str, severity: str) -> dict[str, Any]:
    """Build a SARIF ``reportingDescriptor`` (entry in ``tool.driver.rules``)."""
    return {
        "id": rule_id,
        "name": rule_name or rule_id,
        "shortDescription": {"text": rule_name or rule_id},
        "fullDescription": {"text": rule_name or rule_id},
        "defaultConfiguration": {"level": _level_for(severity)},
    }


def _build_locations(element_ref: str | None, target_type: str, target_id: str) -> list[dict[str, Any]]:
    """Build SARIF ``locations`` for a single result.

    Strategy:
        * If we have ``element_ref`` (e.g. a CAD element id or BOQ position id)
          we emit a ``logicalLocations`` entry — these IDs are not file paths.
        * We always include a synthetic ``physicalLocation`` whose URI is
          ``<target_type>:<target_id>`` (URI scheme follows the SARIF guidance
          for non-file artifacts).  Consumers like GitHub will render this as
          a non-clickable annotation, but the document stays schema-valid.
    """
    location: dict[str, Any] = {
        "physicalLocation": {
            "artifactLocation": {
                "uri": f"{target_type or 'target'}:{target_id or 'unknown'}",
                "uriBaseId": "%SRCROOT%",
            }
        }
    }
    if element_ref:
        location["logicalLocations"] = [
            {
                "name": element_ref,
                "kind": "element",
                "fullyQualifiedName": f"{target_type}/{target_id}/{element_ref}",
            }
        ]
    return [location]


def _build_result(item: dict[str, Any], target_type: str, target_id: str) -> dict[str, Any]:
    """Build a single SARIF ``result`` from a normalised rule-result dict."""
    sarif_result: dict[str, Any] = {
        "ruleId": item["rule_id"],
        "level": _level_for(item["severity"]),
        "message": {"text": item["message"] or "(no message)"},
        "locations": _build_locations(
            item.get("element_ref"),
            target_type,
            target_id,
        ),
        "kind": "fail" if not item.get("passed", False) else "pass",
    }

    # Optional suggestion → SARIF ``fixes`` placeholder is fix metadata-heavy
    # (artifact changes), so we instead surface it as a property-bag entry.
    properties: dict[str, Any] = {
        "category": item.get("category", ""),
        "passed": bool(item.get("passed", False)),
    }
    if item.get("suggestion"):
        properties["suggestion"] = item["suggestion"]
    if item.get("details"):
        properties["details"] = item["details"]
    sarif_result["properties"] = properties
    return sarif_result


# ── Public API ──────────────────────────────────────────────────────────────


def report_to_sarif(report: Any) -> dict[str, Any]:
    """Convert a validation report → SARIF v2.1.0 dict.

    Args:
        report: Either an :class:`EngineReport` (in-memory) or an ORM
            :class:`ValidationReport` row.

    Returns:
        A JSON-serialisable dict that conforms to SARIF v2.1.0.  Encode it
        with :func:`json.dumps` (``ensure_ascii=False`` is recommended) and
        serve it with the ``application/sarif+json`` content type.
    """
    norm = _normalize_report(report)

    # Build the rule registry — one entry per unique rule that produced a result.
    rules_by_id: dict[str, dict[str, Any]] = {}
    sarif_results: list[dict[str, Any]] = []

    for item in norm["results"]:
        rule_id = item["rule_id"]
        if rule_id and rule_id not in rules_by_id:
            rules_by_id[rule_id] = _build_rule_descriptor(
                rule_id=rule_id,
                rule_name=item.get("rule_name") or rule_id,
                severity=item.get("severity", "info"),
            )
        # Emit results only for failing rules — SARIF idiom.  Passing rules
        # are still captured via properties.run.invocations.passingChecks.
        if item.get("passed", False):
            continue
        sarif_results.append(
            _build_result(item, norm["target_type"], norm["target_id"])
        )

    timestamp = norm["timestamp"]
    if isinstance(timestamp, datetime):
        ts_iso = timestamp.astimezone(UTC).isoformat().replace("+00:00", "Z")
    else:
        ts_iso = datetime.now(UTC).isoformat().replace("+00:00", "Z")

    invocation = {
        "executionSuccessful": True,
        "endTimeUtc": ts_iso,
        "properties": {
            "passingChecks": sum(1 for r in norm["results"] if r.get("passed")),
            "totalChecks": len(norm["results"]),
            "ruleSets": norm["rule_sets"],
        },
    }

    run: dict[str, Any] = {
        "tool": {
            "driver": {
                "name": TOOL_NAME,
                "organization": TOOL_ORG,
                "version": _get_tool_version(),
                "informationUri": TOOL_INFORMATION_URI,
                "rules": list(rules_by_id.values()),
            }
        },
        "results": sarif_results,
        "invocations": [invocation],
        "originalUriBaseIds": {
            "%SRCROOT%": {
                "uri": f"openestimate://{norm['target_type']}/{norm['target_id']}/",
                "description": {
                    "text": f"OpenConstructionERP {norm['target_type']} {norm['target_id']}"
                },
            }
        },
        "properties": {
            "reportId": norm["id"],
            "targetType": norm["target_type"],
            "targetId": norm["target_id"],
        },
    }

    return {
        "$schema": SARIF_SCHEMA,
        "version": SARIF_VERSION,
        "runs": [run],
    }
