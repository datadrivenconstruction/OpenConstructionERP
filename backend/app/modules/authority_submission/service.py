# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Business logic and the pure XML/validation engine for authority submissions.

The three engine functions are pure (no session, no clock) so they unit-test
directly and produce byte-stable output:

- :func:`validate_payload` - check a payload against a profile's ``field_spec``
  (required fields present, types correct, nested item fields) and return a
  structured report reusing the platform's shared quality score.
- :func:`build_submission_xml` - walk the ``field_spec`` in order and emit a
  deterministic, fully escaped XML string via :mod:`xml.etree.ElementTree`. No
  external dependency; the field-spec order (not the payload dict order) fixes
  the element order so the same data always renders the same bytes.
- :func:`render_payload` - the same payload rendered for a human reviewer (the
  "one payload, two outputs" idea): a machine XML and a readable view from a
  single source.

The service classes wrap these with persistence, the ``draft -> validated ->
signed_pending -> submitted -> accepted | rejected`` lifecycle guard, and the
idempotent seeding of the built-in profiles.
"""

from __future__ import annotations

import logging
import uuid
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException
from fastapi import status as http_status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.validation.engine import SEVERITY_WEIGHTS, compute_quality_score
from app.modules.authority_submission.models import Submission, SubmissionProfile
from app.modules.authority_submission.profiles import BUILTIN_PROFILES
from app.modules.authority_submission.repository import (
    ProfileRepository,
    SubmissionRepository,
)
from app.modules.authority_submission.schemas import (
    STATUSES,
    SubmissionCreate,
    SubmissionUpdate,
)

logger = logging.getLogger(__name__)

# ── Lifecycle ───────────────────────────────────────────────────────────────
#
# The allowed forward/back transitions. Editing the payload always resets to
# ``draft`` (handled in update), so this map only governs explicit status moves.
_ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    "draft": frozenset({"validated"}),
    "validated": frozenset({"signed_pending", "submitted", "draft"}),
    "signed_pending": frozenset({"submitted", "validated", "draft"}),
    "submitted": frozenset({"accepted", "rejected"}),
    "accepted": frozenset(),
    "rejected": frozenset({"draft"}),
}

# A submission may only be sent from one of these states, and only with a clean
# validation report (rule authority_submission.schema_valid).
_SUBMITTABLE_FROM: frozenset[str] = frozenset({"validated", "signed_pending"})


# ── Pure engine: type checks ────────────────────────────────────────────────


def _type_ok(value: Any, ftype: str) -> bool:
    """Return True when ``value`` matches the field-spec ``type``.

    ``bool`` is explicitly excluded from the numeric types (in Python ``True``
    is an ``int``) so a checkbox value never passes as a quantity.
    """
    if ftype in ("string", "date"):
        return isinstance(value, str)
    if ftype == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if ftype == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if ftype == "boolean":
        return isinstance(value, bool)
    if ftype == "array":
        return isinstance(value, list)
    if ftype == "object":
        return isinstance(value, dict)
    # Unknown type: don't block, structure rules elsewhere can catch it.
    return True


# ── Pure engine: validation ─────────────────────────────────────────────────


def validate_payload(payload: dict[str, Any], field_spec: list[dict[str, Any]]) -> dict[str, Any]:
    """Validate ``payload`` against ``field_spec`` and return a report.

    The report mirrors the platform validation shape enough to be shown in the
    same traffic-light UI: an overall ``status`` (``passed`` / ``errors``), a
    0.0-1.0 ``score`` from the shared scorer, and a per-field ``results`` list.
    Missing required fields and type mismatches are also collected flat for the
    caller's convenience.
    """
    results: list[dict[str, Any]] = []
    missing_required: list[str] = []
    type_mismatches: list[dict[str, Any]] = []

    for spec in field_spec:
        name = str(spec.get("name", ""))
        ftype = str(spec.get("type", "string"))
        required = bool(spec.get("required"))
        present = name in payload and payload[name] is not None

        if not present:
            if required:
                missing_required.append(name)
                results.append(
                    {
                        "field": name,
                        "ok": False,
                        "severity": "error",
                        "message": f"Required field '{name}' is missing.",
                    }
                )
            continue

        value = payload[name]
        if not _type_ok(value, ftype):
            got = type(value).__name__
            type_mismatches.append({"field": name, "expected": ftype, "got": got})
            results.append(
                {
                    "field": name,
                    "ok": False,
                    "severity": "error",
                    "message": f"Field '{name}' expected {ftype}, got {got}.",
                }
            )
            continue

        nested_errors = _validate_nested(name, spec, value)
        if nested_errors:
            for err in nested_errors:
                missing_required.append(err["field"])
                results.append(err)
            continue

        results.append({"field": name, "ok": True, "severity": "info", "message": "OK"})

    total = len(results)
    n_errors = sum(1 for r in results if not r["ok"])
    n_pass = total - n_errors
    weight = SEVERITY_WEIGHTS["error"]
    score = compute_quality_score(n_pass * weight, total * weight, n_errors) if total else 1.0

    return {
        "status": "errors" if n_errors else "passed",
        "score": score,
        "checked": total,
        "errors": n_errors,
        "missing_required": missing_required,
        "type_mismatches": type_mismatches,
        "results": results,
    }


def _validate_nested(
    name: str,
    spec: dict[str, Any],
    value: Any,
) -> list[dict[str, Any]]:
    """Check required sub-fields of array-of-objects / object fields.

    Returns a list of error rows (empty when the nested shape is clean). Only
    required-presence is checked at depth - deep type checking is intentionally
    shallow so the report stays legible.
    """
    item_fields = spec.get("fields")
    if not item_fields:
        return []
    ftype = str(spec.get("type", "string"))
    errors: list[dict[str, Any]] = []

    if ftype == "array":
        for idx, item in enumerate(value):
            for sub in item_fields:
                if not sub.get("required"):
                    continue
                sub_name = str(sub.get("name", ""))
                if not isinstance(item, dict) or item.get(sub_name) in (None, ""):
                    errors.append(
                        {
                            "field": f"{name}[{idx}].{sub_name}",
                            "ok": False,
                            "severity": "error",
                            "message": f"Required field '{sub_name}' is missing in {name}[{idx}].",
                        }
                    )
    elif ftype == "object":
        for sub in item_fields:
            if not sub.get("required"):
                continue
            sub_name = str(sub.get("name", ""))
            if value.get(sub_name) in (None, ""):
                errors.append(
                    {
                        "field": f"{name}.{sub_name}",
                        "ok": False,
                        "severity": "error",
                        "message": f"Required field '{sub_name}' is missing in {name}.",
                    }
                )
    return errors


# ── Pure engine: XML generation ─────────────────────────────────────────────


def _coerce_text(value: Any) -> str:
    """Render a scalar as XML text. Booleans lower-case; None is empty."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return ""
    return str(value)


def _append_field(parent: ET.Element, spec: dict[str, Any], value: Any) -> None:
    """Append one field's element(s) to ``parent``, driven by its spec."""
    tag = str(spec.get("xml_tag") or spec.get("name") or "field")
    ftype = str(spec.get("type", "string"))

    if ftype == "array":
        wrapper = ET.SubElement(parent, tag)
        item_tag = str(spec.get("item_tag") or "item")
        item_fields = spec.get("fields")
        for item in value or []:
            item_el = ET.SubElement(wrapper, item_tag)
            if item_fields and isinstance(item, dict):
                for sub in item_fields:
                    if sub.get("name") in item:
                        _append_field(item_el, sub, item.get(sub["name"]))
            else:
                item_el.text = _coerce_text(item)
        return

    if ftype == "object":
        obj_el = ET.SubElement(parent, tag)
        if isinstance(value, dict):
            for sub in spec.get("fields", []):
                if sub.get("name") in value:
                    _append_field(obj_el, sub, value.get(sub["name"]))
        return

    el = ET.SubElement(parent, tag)
    el.text = _coerce_text(value)


def build_submission_xml(
    root_element: str,
    field_spec: list[dict[str, Any]],
    payload: dict[str, Any],
    *,
    schema_version: str = "1.0",
    format_key: str = "generic_xml",
) -> str:
    """Build a deterministic, fully escaped XML string from a payload.

    The element order follows ``field_spec`` (never the payload dict order) so
    the output is byte-stable for a given payload; only fields present in the
    payload are emitted. ``ElementTree`` escapes all text and attribute values,
    so a payload can never inject markup.
    """
    root = ET.Element(str(root_element or "Document"))
    # Fixed attribute order for stable output.
    root.set("schemaVersion", str(schema_version))
    root.set("format", str(format_key))

    for spec in field_spec:
        name = spec.get("name")
        if name in payload:
            _append_field(root, spec, payload[name])

    body = ET.tostring(root, encoding="unicode")
    return f'<?xml version="1.0" encoding="UTF-8"?>\n{body}'


# ── Pure engine: human render ───────────────────────────────────────────────


def _field_label(spec: dict[str, Any]) -> str:
    return str(spec.get("label") or str(spec.get("name", "")).replace("_", " ").title())


def render_payload(
    field_spec: list[dict[str, Any]],
    payload: dict[str, Any],
    *,
    title: str,
    root_element: str,
) -> dict[str, Any]:
    """Render the same payload for a human reviewer (rows + a text block)."""

    def render_value(spec: dict[str, Any], value: Any) -> Any:
        ftype = str(spec.get("type", "string"))
        if ftype == "array":
            item_fields = spec.get("fields")
            items: list[Any] = []
            for item in value or []:
                if item_fields and isinstance(item, dict):
                    items.append({_field_label(s): item.get(s["name"]) for s in item_fields})
                else:
                    items.append(item)
            return items
        if ftype == "object" and isinstance(value, dict):
            return {_field_label(s): value.get(s["name"]) for s in spec.get("fields", [])}
        if isinstance(value, bool):
            return "Yes" if value else "No"
        return value

    rows: list[dict[str, Any]] = []
    for spec in field_spec:
        name = spec.get("name")
        if name not in payload:
            continue
        rows.append(
            {
                "field": name,
                "label": _field_label(spec),
                "type": str(spec.get("type", "string")),
                "value": render_value(spec, payload[name]),
            }
        )

    text_lines = [str(title), f"({root_element})", ""]
    for row in rows:
        value = row["value"]
        if isinstance(value, list):
            text_lines.append(f"{row['label']}:")
            for i, item in enumerate(value, 1):
                text_lines.append(f"  {i}. {item}")
        else:
            text_lines.append(f"{row['label']}: {value}")

    return {
        "title": title,
        "root_element": root_element,
        "fields": rows,
        "text": "\n".join(text_lines),
    }


# ── Profile service ─────────────────────────────────────────────────────────


class ProfileService:
    """Read access and idempotent seeding for global submission profiles."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = ProfileRepository(session)

    async def ensure_builtins(self) -> None:
        """Seed the built-in profiles once. Idempotent on (name, format_key)."""
        for spec in BUILTIN_PROFILES:
            if await self.repo.find_builtin(spec["name"], spec["format_key"]) is not None:
                continue
            self.repo.add(
                SubmissionProfile(
                    name=spec["name"],
                    jurisdiction=spec.get("jurisdiction"),
                    format_key=spec["format_key"],
                    schema_version=spec.get("schema_version", "1.0"),
                    root_element=spec.get("root_element", "Document"),
                    field_spec=spec.get("field_spec", []),
                    description=spec.get("description", ""),
                    is_builtin=True,
                )
            )
        await self.session.flush()

    async def list_profiles(self, *, format_key: str | None = None) -> list[SubmissionProfile]:
        await self.ensure_builtins()
        return await self.repo.list_all(format_key=format_key)

    async def get_profile(self, profile_id: uuid.UUID) -> SubmissionProfile:
        row = await self.repo.get_by_id(profile_id)
        if row is None:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail="Submission profile not found.",
            )
        return row


# ── Submission service ──────────────────────────────────────────────────────


class SubmissionService:
    """Business logic for the project-scoped submissions."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = SubmissionRepository(session)
        self.profiles = ProfileService(session)

    @staticmethod
    def _now() -> datetime:
        return datetime.now(UTC)

    async def get_submission(self, submission_id: uuid.UUID) -> Submission:
        row = await self.repo.get_by_id(submission_id)
        if row is None:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail="Submission not found.",
            )
        return row

    async def list_submissions(
        self,
        project_id: uuid.UUID,
        *,
        status: str | None = None,
        profile_id: uuid.UUID | None = None,
    ) -> list[Submission]:
        return await self.repo.list_for_project(project_id, status=status, profile_id=profile_id)

    async def create_submission(
        self,
        data: SubmissionCreate,
        *,
        user_id: str | None = None,
    ) -> Submission:
        # A submission must reference a real profile.
        await self.profiles.get_profile(data.profile_id)

        submission = Submission(
            project_id=data.project_id,
            profile_id=data.profile_id,
            title=data.title,
            payload=data.payload,
            status="draft",
            metadata_=data.metadata,
            created_by=user_id,
        )
        self.repo.add(submission)
        await self.session.flush()
        logger.info(
            "Authority submission created: %s (profile %s) for project %s",
            submission.id,
            submission.profile_id,
            submission.project_id,
        )
        return submission

    async def update_submission(
        self,
        submission_id: uuid.UUID,
        data: SubmissionUpdate,
        *,
        user_id: str | None = None,
    ) -> Submission:
        submission = await self.get_submission(submission_id)
        fields = data.model_dump(exclude_unset=True)

        # Editing the payload invalidates any prior XML / validation and resets
        # the lifecycle to draft - the document has to be re-validated.
        if "payload" in fields and fields["payload"] != submission.payload:
            submission.payload = fields.pop("payload")
            submission.generated_xml = None
            submission.validation_report = None
            submission.status = "draft"
        else:
            fields.pop("payload", None)

        if "title" in fields:
            submission.title = fields.pop("title")

        if "metadata" in fields:
            incoming = fields.pop("metadata")
            merged = dict(submission.metadata_ or {})
            if isinstance(incoming, dict):
                merged.update(incoming)
            submission.metadata_ = merged

        # Explicit status move, guarded by the transition map.
        new_status = fields.pop("status", None)
        if new_status is not None and new_status != submission.status:
            self._assert_transition(submission.status, new_status)
            if new_status == "submitted":
                self._assert_submittable(submission)
                submission.submitted_at = self._now()
            submission.status = new_status

        if user_id is not None:
            meta = dict(submission.metadata_ or {})
            meta["updated_by"] = user_id
            meta["updated_at"] = self._now().isoformat()
            submission.metadata_ = meta

        await self.session.flush()
        await self.session.refresh(submission)
        return submission

    async def delete_submission(self, submission_id: uuid.UUID) -> None:
        submission = await self.get_submission(submission_id)
        await self.repo.delete(submission)

    # ── Engine actions ─────────────────────────────────────────────────────

    async def validate_submission(self, submission_id: uuid.UUID) -> dict[str, Any]:
        """Validate the payload against its profile, store and return the report.

        A clean report advances a ``draft`` to ``validated``; a report with
        errors pulls a non-terminal submission back to ``draft`` so it can't be
        submitted on a stale pass.
        """
        submission = await self.get_submission(submission_id)
        profile = await self.profiles.get_profile(submission.profile_id)

        report = validate_payload(submission.payload, profile.field_spec)
        submission.validation_report = report

        if report["status"] == "passed":
            if submission.status == "draft":
                submission.status = "validated"
        elif submission.status in ("validated", "signed_pending"):
            submission.status = "draft"

        await self.session.flush()
        await self.session.refresh(submission)
        return report

    async def generate_submission_xml(self, submission_id: uuid.UUID) -> str:
        """Build and persist the deterministic XML for a submission."""
        submission = await self.get_submission(submission_id)
        profile = await self.profiles.get_profile(submission.profile_id)

        xml = build_submission_xml(
            profile.root_element,
            profile.field_spec,
            submission.payload,
            schema_version=profile.schema_version,
            format_key=profile.format_key,
        )
        submission.generated_xml = xml
        await self.session.flush()
        return xml

    async def render_submission(self, submission_id: uuid.UUID) -> dict[str, Any]:
        """Render the payload for human review (no persistence)."""
        submission = await self.get_submission(submission_id)
        profile = await self.profiles.get_profile(submission.profile_id)
        return render_payload(
            profile.field_spec,
            submission.payload,
            title=submission.title,
            root_element=profile.root_element,
        )

    async def submit_submission(self, submission_id: uuid.UUID) -> Submission:
        """Mark a validated submission as submitted to the authority.

        Enforces rule ``authority_submission.schema_valid``: the stored
        validation report must be clean and the submission in a submittable
        state.
        """
        submission = await self.get_submission(submission_id)
        self._assert_submittable(submission)
        submission.status = "submitted"
        submission.submitted_at = self._now()
        await self.session.flush()
        await self.session.refresh(submission)
        return submission

    # ── Guards ─────────────────────────────────────────────────────────────

    @staticmethod
    def _assert_transition(current: str, target: str) -> None:
        if target not in STATUSES:
            raise HTTPException(
                status_code=http_status.HTTP_400_BAD_REQUEST,
                detail=f"Unknown status '{target}'.",
            )
        allowed = _ALLOWED_TRANSITIONS.get(current, frozenset())
        if target not in allowed:
            raise HTTPException(
                status_code=http_status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot move a submission from '{current}' to '{target}'.",
            )

    @staticmethod
    def _assert_submittable(submission: Submission) -> None:
        if submission.status not in _SUBMITTABLE_FROM:
            raise HTTPException(
                status_code=http_status.HTTP_400_BAD_REQUEST,
                detail="A submission must be validated before it can be submitted.",
            )
        report = submission.validation_report
        if not report or report.get("status") != "passed":
            raise HTTPException(
                status_code=http_status.HTTP_400_BAD_REQUEST,
                detail="A submission must validate cleanly before it can be submitted.",
            )


__all__ = [
    "ProfileService",
    "SubmissionService",
    "build_submission_xml",
    "render_payload",
    "validate_payload",
]
