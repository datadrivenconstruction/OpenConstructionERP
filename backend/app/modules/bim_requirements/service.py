"""BIM Requirements service -- business logic for import/export.

Handles file import orchestration, parser selection, DB persistence,
and export generation.
"""

import logging
import tempfile
import uuid
from pathlib import Path
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.bim_requirements.classifier import FormatClassifier
from app.modules.bim_requirements.models import BIMRequirement, BIMRequirementSet
from app.modules.bim_requirements.parsers.base import ParseResult, UniversalRequirement

logger = logging.getLogger(__name__)

_classifier = FormatClassifier()


def _get_parser(format_name: str) -> Any:
    """Return the appropriate parser instance for a detected format.

    The :class:`FormatClassifier` can emit *generic* labels for content it
    recognises only loosely (``GenericXML``, ``MVD``, ``ArchiCAD`` for any
    non-IDS XML; ``GenericJSON`` for non-BIMQ JSON; ``PlainText`` for a
    ``.txt`` that isn't a Revit shared-parameter file).  Previously every
    such label fell through to a blanket ``ValueError`` → HTTP 422, even
    when the payload was a perfectly valid generic requirements export
    (E-XMOD-019).  We now route those to the closest content-compatible
    parser as a best effort:

    * any XML  → :class:`IDSParser` (namespace-tolerant; degrades to a
      "no specifications found" warning rather than a hard error),
    * any JSON → :class:`BIMQParser` (handles ``concept_tree``/``elements``
      and bare requirement arrays),
    * plain text → :class:`RevitSPParser` (tab-separated parameter rows).

    A genuinely unknown label still raises ``ValueError`` so the caller can
    surface an actionable message.
    """
    if format_name == "IDS" or format_name in ("GenericXML", "MVD", "ArchiCAD"):
        from app.modules.bim_requirements.parsers.ids_parser import IDSParser

        return IDSParser()
    elif format_name in ("COBie",):
        from app.modules.bim_requirements.parsers.cobie_parser import COBieParser

        return COBieParser()
    elif format_name in ("Excel", "CSV"):
        from app.modules.bim_requirements.parsers.excel_parser import ExcelCSVParser

        return ExcelCSVParser()
    elif format_name in ("RevitSP", "PlainText"):
        from app.modules.bim_requirements.parsers.revit_sp_parser import RevitSPParser

        return RevitSPParser()
    elif format_name in ("BIMQ", "GenericJSON"):
        from app.modules.bim_requirements.parsers.bimq_parser import BIMQParser

        return BIMQParser()
    else:
        raise ValueError(
            f"No parser available for format: {format_name}. "
            f"Supported: IDS XML, COBie/BIMQ Excel, generic Excel/CSV, "
            f"Revit shared parameters (.txt), BIMQ JSON."
        )


class BIMRequirementService:
    """Business logic for BIM requirements import/export."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ── Import ─────────────────────────────────────────────────────────────

    async def import_file(
        self,
        project_id: uuid.UUID,
        file_content: bytes,
        filename: str,
        *,
        name: str | None = None,
        user_id: str = "",
    ) -> tuple[BIMRequirementSet, ParseResult]:
        """Import a BIM requirements file: detect format, parse, persist.

        Args:
            project_id: Project to associate the requirement set with.
            file_content: Raw file content as bytes.
            filename: Original filename (used for format detection).
            name: Optional name for the requirement set.
            user_id: ID of the importing user.

        Returns:
            Tuple of (created BIMRequirementSet, ParseResult with details).

        Raises:
            HTTPException: If file format is unsupported or parsing fails completely.
        """
        # Write to temp file for classifier and parser
        suffix = Path(filename).suffix
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(file_content)
            tmp_path = Path(tmp.name)

        try:
            # Classify format
            try:
                format_name = _classifier.classify(tmp_path)
            except ValueError as exc:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=str(exc),
                ) from exc

            # Get parser and parse
            try:
                parser = _get_parser(format_name)
            except ValueError as exc:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=str(exc),
                ) from exc

            parse_result: ParseResult = parser.parse(tmp_path)
            parse_result.metadata["format_detected"] = format_name

        finally:
            # Clean up temp file
            try:
                tmp_path.unlink()
            except OSError:
                pass

        if not parse_result.success:
            # A rejected XXE / DTD / entity-expansion payload is a *malicious
            # input* (400), not an unprocessable-but-honest file (422). The
            # IDS parser tags these with field="xml_security" (E-SEC-016).
            security_errors = [e for e in parse_result.errors if e.get("field") == "xml_security"]
            if security_errors:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=security_errors[0].get("msg", "XML rejected for security reasons."),
                )
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"No requirements could be parsed from '{filename}' "
                    f"(format: {format_name}). "
                    f"Errors: {parse_result.errors}"
                ),
            )

        # Create the requirement set
        set_name = name or f"{Path(filename).stem} ({format_name})"
        req_set = BIMRequirementSet(
            project_id=project_id,
            name=set_name,
            description=f"Imported from {filename}",
            source_format=format_name,
            source_filename=filename,
            created_by=user_id,
            metadata_=parse_result.metadata,
        )
        self.session.add(req_set)
        await self.session.flush()

        # Persist individual requirements
        for req in parse_result.requirements:
            db_req = BIMRequirement(
                requirement_set_id=req_set.id,
                element_filter=req.element_filter,
                property_group=req.property_group,
                property_name=req.property_name,
                constraint_def=req.constraint_def,
                context=req.context,
                source_format=format_name,
                is_active=True,
            )
            self.session.add(db_req)

        await self.session.flush()

        logger.info(
            "Imported %d BIM requirements from '%s' (format=%s) into set %s",
            len(parse_result.requirements),
            filename,
            format_name,
            req_set.id,
        )
        return req_set, parse_result

    # ── CRUD ───────────────────────────────────────────────────────────────

    async def list_sets(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
    ) -> list[BIMRequirementSet]:
        """List requirement sets for a project."""
        stmt = (
            select(BIMRequirementSet)
            .where(BIMRequirementSet.project_id == project_id)
            .order_by(BIMRequirementSet.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_set(self, set_id: uuid.UUID) -> BIMRequirementSet:
        """Get a requirement set by ID. Raises 404 if not found."""
        item = await self.session.get(BIMRequirementSet, set_id)
        if item is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="BIM requirement set not found",
            )
        return item

    async def list_requirements(
        self,
        set_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> list[BIMRequirement]:
        """List requirements for a set."""
        stmt = (
            select(BIMRequirement)
            .where(BIMRequirement.requirement_set_id == set_id)
            .order_by(BIMRequirement.created_at)
            .offset(offset)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def delete_set(self, set_id: uuid.UUID) -> None:
        """Delete a requirement set and all its requirements (cascade)."""
        item = await self.get_set(set_id)
        await self.session.delete(item)
        await self.session.flush()
        logger.info("BIM requirement set deleted: %s", set_id)

    # ── Export ─────────────────────────────────────────────────────────────

    async def export_excel(
        self,
        set_id: uuid.UUID,
        language: str = "en",
    ) -> bytes:
        """Export a requirement set as a formatted Excel file."""
        from app.modules.bim_requirements.exporters.excel_exporter import export_excel

        req_set = await self.get_set(set_id)
        reqs = await self._load_requirements_as_universal(set_id)
        return export_excel(reqs, title=req_set.name, language=language)

    async def export_ids(
        self,
        set_id: uuid.UUID,
    ) -> str:
        """Export a requirement set as IDS XML."""
        from app.modules.bim_requirements.exporters.ids_exporter import export_ids_xml

        req_set = await self.get_set(set_id)
        reqs = await self._load_requirements_as_universal(set_id)
        return export_ids_xml(reqs, title=req_set.name)

    async def _load_requirements_as_universal(self, set_id: uuid.UUID) -> list[UniversalRequirement]:
        """Load DB requirements and convert to UniversalRequirement objects."""
        stmt = (
            select(BIMRequirement)
            .where(BIMRequirement.requirement_set_id == set_id)
            .order_by(BIMRequirement.created_at)
        )
        result = await self.session.execute(stmt)
        rows = result.scalars().all()

        return [
            UniversalRequirement(
                element_filter=row.element_filter or {},
                property_group=row.property_group,
                property_name=row.property_name,
                constraint_def=row.constraint_def or {},
                context=row.context,
            )
            for row in rows
        ]

    # ── Validation (compliance check against BIM model) ──────────────────

    async def validate_against_model(
        self,
        set_id: uuid.UUID,
        model_id: uuid.UUID,
        *,
        user_id: str,
    ) -> dict:
        """Check if BIM elements in a model satisfy the requirements in a set.

        For each requirement:
        1. Use ``element_filter`` to find matching elements (by ifc_class,
           element_type, or classification).
        2. Check if matching elements have the required ``property_name``
           (optionally in the specified ``property_group``).
        3. Evaluate the ``constraint_def`` against the actual property value.

        The ``model_id`` is caller-supplied, so the model's project must be
        re-authorised here even though the router already verified access to
        the requirement set's project: without this a caller who owns a set
        in project A could validate against a model from another tenant's
        project B, turning the attacker-controlled ``element_filter`` /
        ``constraint_def`` into a cross-tenant property-value oracle. Both a
        foreign model and one the caller cannot reach collapse to 404 so the
        model's existence is never leaked - mirroring the ``preview-yaml``
        endpoint which already gates the model the same way.

        Returns a compliance report dict suitable for ``RequirementValidationResponse``.
        """
        from app.dependencies import verify_project_access
        from app.modules.bim_hub.models import BIMModel
        from app.modules.bim_hub.repository import BIMElementRepository

        # Load requirement set
        req_set = await self.get_set(set_id)
        reqs = req_set.requirements

        # Load BIM model and its elements
        model = await self.session.get(BIMModel, model_id)
        if model is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="BIM model not found",
            )
        # IDOR guard: the caller must be able to access the MODEL's project,
        # not just the requirement set's. 404 (not 403) on denial keeps a
        # foreign model indistinguishable from a missing one.
        await verify_project_access(model.project_id, str(user_id), self.session)
        # Defence in depth: a validation only makes sense within one project,
        # so reject a model that belongs to a different project than the set
        # even when the caller happens to be able to reach both (again 404 so
        # the cross-project pairing is not confirmed).
        if model.project_id != req_set.project_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="BIM model not found",
            )
        elem_repo = BIMElementRepository(self.session)
        elements, _total = await elem_repo.list_for_model(model_id, offset=0, limit=50_000)

        results: list[dict] = []
        passed = failed = not_applicable = 0

        for req in reqs:
            if not req.is_active:
                continue

            ef = req.element_filter or {}
            matched = self._filter_elements(elements, ef)
            prop_name = req.property_name
            prop_group = req.property_group
            constraint = req.constraint_def or {}

            if not matched:
                results.append(
                    {
                        "requirement_id": str(req.id),
                        "property_group": prop_group,
                        "property_name": prop_name,
                        "element_filter": ef,
                        "constraint_def": constraint,
                        "status": "not_applicable",
                        "matched_elements": 0,
                        "compliant_elements": 0,
                        "non_compliant_elements": 0,
                        "details": "No elements match the element_filter",
                    }
                )
                not_applicable += 1
                continue

            compliant = 0
            non_compliant = 0
            for elem in matched:
                val = self._get_property_value(elem, prop_name, prop_group)
                if self._check_constraint(val, constraint):
                    compliant += 1
                else:
                    non_compliant += 1

            req_status = "pass" if non_compliant == 0 else "fail"
            if req_status == "pass":
                passed += 1
            else:
                failed += 1

            results.append(
                {
                    "requirement_id": str(req.id),
                    "property_group": prop_group,
                    "property_name": prop_name,
                    "element_filter": ef,
                    "constraint_def": constraint,
                    "status": req_status,
                    "matched_elements": len(matched),
                    "compliant_elements": compliant,
                    "non_compliant_elements": non_compliant,
                    "details": (
                        f"{compliant}/{len(matched)} elements compliant"
                        if req_status == "pass"
                        else f"{non_compliant}/{len(matched)} elements non-compliant"
                    ),
                }
            )

        total = passed + failed + not_applicable
        return {
            "requirement_set_id": str(req_set.id),
            "requirement_set_name": req_set.name,
            "model_id": str(model_id),
            "total_requirements": total,
            "passed": passed,
            "failed": failed,
            "not_applicable": not_applicable,
            "compliance_ratio": round(passed / max(passed + failed, 1), 3),
            "results": results,
        }

    @staticmethod
    def _filter_elements(
        elements: list,
        element_filter: dict,
    ) -> list:
        """Filter BIM elements by the requirement's element_filter spec.

        Supports:
        - ``ifc_class``: glob match against element_type (e.g. "Wall*", "IfcWall")
        - ``classification``: dict of code → pattern (e.g. {"din276": "300*"})
        - ``properties``: dict of key → pattern (e.g. {"material": "concrete*"})
        """
        from fnmatch import fnmatch as _fnmatch

        if not element_filter:
            return list(elements)

        result = []
        ifc_class = element_filter.get("ifc_class") or element_filter.get("entity")
        classification = element_filter.get("classification", {})
        prop_filters = element_filter.get("properties", {})

        for elem in elements:
            # ifc_class / entity filter
            if ifc_class:
                etype = (elem.element_type or "").lower()
                if not _fnmatch(etype, ifc_class.lower()):
                    continue

            # classification filter
            skip = False
            if classification:
                # BIMElement has no dedicated classification column; per the
                # canonical format spec the codes live under
                # ``properties["classification"]`` (e.g. {"din276": "330"}).
                # Mirror bim_hub.smart_views / vector_adapter which read the
                # same nested dict. Fall back to {} so a missing key never
                # raises AttributeError.
                _props = getattr(elem, "properties", None) or {}
                elem_class = _props.get("classification") if isinstance(_props, dict) else None
                if not isinstance(elem_class, dict):
                    elem_class = {}
                for code_sys, pattern in classification.items():
                    actual = str(elem_class.get(code_sys, "")).lower()
                    if not _fnmatch(actual, str(pattern).lower()):
                        skip = True
                        break
            if skip:
                continue

            # property filter
            if prop_filters:
                props = elem.properties or {}
                for pk, pv in prop_filters.items():
                    actual = str(props.get(pk, "")).lower()
                    if not _fnmatch(actual, str(pv).lower()):
                        skip = True
                        break
            if skip:
                continue

            result.append(elem)
        return result

    @staticmethod
    def _get_property_value(
        elem: object,
        prop_name: str,
        prop_group: str | None,
    ) -> object:
        """Extract a property value from a BIM element."""
        props = getattr(elem, "properties", None) or {}
        quantities = getattr(elem, "quantities", None) or {}

        # Check quantities first (Area, Volume, Length, etc.)
        val = quantities.get(prop_name)
        if val is not None:
            return val

        # Check properties (flat or nested by group)
        if prop_group:
            group_data = props.get(prop_group)
            if isinstance(group_data, dict):
                return group_data.get(prop_name)
        return props.get(prop_name)

    @staticmethod
    def _check_constraint(actual: object, constraint_def: dict) -> bool:
        """Evaluate a constraint against an actual value.

        Constraint types supported:
        - ``{"type": "exists"}`` -- property must be present (not None)
        - ``{"type": "enumeration", "values": [...]}`` -- value must be in list
        - ``{"type": "pattern", "pattern": "..."}`` -- fnmatch pattern match
        - ``{"type": "range", "min": N, "max": N}`` -- numeric range
        - ``{"type": "value", "value": X}`` -- exact match
        - Empty constraint or unknown type: pass if value exists.
        """
        from fnmatch import fnmatch as _fnmatch

        ctype = constraint_def.get("type", "exists")

        if ctype == "exists":
            return actual is not None and str(actual).strip() != ""

        if ctype == "enumeration":
            values = constraint_def.get("values", [])
            if not values:
                return actual is not None
            return str(actual).lower() in [str(v).lower() for v in values]

        if ctype == "pattern":
            pattern = constraint_def.get("pattern", "*")
            if actual is None:
                return False
            return _fnmatch(str(actual).lower(), pattern.lower())

        if ctype == "range":
            if actual is None:
                return False
            try:
                num = float(actual)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                return False
            lo = constraint_def.get("min")
            hi = constraint_def.get("max")
            if lo is not None and num < float(lo):
                return False
            return not (hi is not None and num > float(hi))

        if ctype == "value":
            expected = constraint_def.get("value")
            if expected is None:
                return actual is None
            return str(actual).lower() == str(expected).lower()

        # Unknown constraint type - pass if value exists
        return actual is not None

    # ── Rules-as-Code (YAML) install ──────────────────────────────────────
    #
    # The YAML pack carries a richer schema than the 5-column universal
    # ``BIMRequirement`` row (severity, rationale, selector predicates,
    # assertion predicates, failure_message). We persist each rule as one
    # row, mapping the rule's *primary* assertion to the row's
    # ``property_name`` + ``constraint_def`` and stashing the full
    # source YAML rule in ``context`` so the runtime can rehydrate it
    # losslessly. Pack-level metadata (id, version, applies_to) goes
    # onto the ``BIMRequirementSet.metadata_`` JSON blob.

    async def install_rules_from_yaml(
        self,
        *,
        project_id: uuid.UUID,
        yaml_text: str,
        user_id: str = "",
    ) -> tuple[BIMRequirementSet, list[BIMRequirement]]:
        """Parse a YAML rule pack and persist it as a project-scoped set.

        Args:
            project_id: Owner project for the new requirement set.
            yaml_text: Raw YAML source - typically pasted into the
                ``/install-from-yaml`` endpoint body.
            user_id: Importing user (for audit).

        Returns:
            Tuple of (created ``BIMRequirementSet``, list of created
            ``BIMRequirement`` rows).

        Raises:
            HTTPException 422: on any parse/validation failure. The
                detail string is the verbatim error from the YAML loader
                so the operator can see file/line context.
        """
        from app.modules.bim_requirements.yaml_loader import (
            PropertyAssertion,
            RulePackParseError,
            SetVsSetAssertion,
            load_rule_pack,
        )

        try:
            pack = load_rule_pack(f"<inline:{project_id}>", text=yaml_text)
        except RulePackParseError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(exc),
            ) from exc

        req_set = BIMRequirementSet(
            project_id=project_id,
            name=pack.pack.name,
            description=pack.pack.description or f"YAML rule pack {pack.pack.id}",
            source_format="YAML",
            source_filename=f"{pack.pack.id}.yaml",
            created_by=user_id,
            metadata_={
                "pack_id": pack.pack.id,
                "pack_version": pack.pack.version,
                "schema_version": pack.schema_version,
                "applies_to": pack.pack.applies_to.model_dump(),
                "source": pack.pack.source,
            },
        )
        self.session.add(req_set)
        await self.session.flush()

        created: list[BIMRequirement] = []
        for rule in pack.rules:
            # Project the rich YAML rule onto the 5-column row. The full
            # rule is preserved in ``context['yaml_rule']`` so runtime can
            # round-trip it through :func:`rule_runtime.evaluate_rule`.
            if isinstance(rule.assertion, PropertyAssertion):
                primary = rule.assertion.property
                property_name = primary.key
                constraint_def = {
                    "type": "yaml_predicate",
                    "op": primary.op,
                    "value": primary.value,
                    "unit": primary.unit,
                }
            elif isinstance(rule.assertion, SetVsSetAssertion):
                primary = rule.assertion.set_vs_set.property
                property_name = primary.key
                constraint_def = {
                    "type": "yaml_set_vs_set",
                    "op": primary.op,
                    "value": primary.value,
                    "unit": primary.unit,
                    "metric": rule.assertion.set_vs_set.metric,
                }
            else:  # pragma: no cover - schema-validated
                continue

            element_filter: dict[str, object] = {}
            if rule.selector.ifc_class is not None:
                element_filter["ifc_class"] = rule.selector.ifc_class
            if rule.selector.classification:
                element_filter["classification"] = dict(rule.selector.classification)
            if rule.selector.properties:
                element_filter["properties"] = [p.model_dump(exclude_none=True) for p in rule.selector.properties]

            db_req = BIMRequirement(
                requirement_set_id=req_set.id,
                element_filter=element_filter,
                property_group=None,
                property_name=property_name,
                constraint_def=constraint_def,
                context={
                    "rule_id": rule.id,
                    "severity": rule.severity,
                    "rationale": rule.rationale,
                    "failure_message": rule.failure_message,
                    "yaml_rule": rule.model_dump(),
                },
                source_format="YAML",
                source_ref=f"{pack.pack.id}#{rule.id}",
                is_active=True,
            )
            self.session.add(db_req)
            created.append(db_req)

        await self.session.flush()

        logger.info(
            "Installed YAML rule pack '%s' (v%s) - %d rules - into set %s",
            pack.pack.id,
            pack.pack.version,
            len(created),
            req_set.id,
        )
        return req_set, created
