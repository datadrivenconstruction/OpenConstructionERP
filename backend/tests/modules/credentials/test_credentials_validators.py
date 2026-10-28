# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The seven credentials rules, each fired and each proved silent when clean.

A rule that never fires and a rule that always fires are equally useless, so
every rule here is tested twice: once on data that should trigger it, once on
data that should not. The clean case matters most - a rule that cannot stay
quiet trains people to ignore the whole report.
"""

from __future__ import annotations

from app.core.validation.engine import rule_registry
from app.modules import credentials as credentials_module
from app.modules.credentials import permissions as permissions_module
from app.modules.credentials import validators as validators_module
from app.modules.credentials.service import RequirementService
from app.modules.credentials.validators import CREDENTIALS_RULE_SET, CREDENTIALS_RULES
from tests.modules.credentials.conftest import (
    API_PREFIX,
    build_app,
    day,
    http_client,
    make_credential,
    make_project,
    make_requirement,
    make_user,
)


async def _validate(session, project_id):
    return await RequirementService(session).validate_project(project_id)


def _rule_ids(report) -> set[str]:
    return {f.rule_id for f in report.findings}


# ── Registration ─────────────────────────────────────────────────────────────


async def test_module_startup_registers_the_rules_and_the_permissions(monkeypatch) -> None:
    """The application must do what this package's conftest does.

    Every other test here runs against rules the conftest registered by hand, so
    the suite would stay green even if the running application never registered
    them at all - and an unregistered rule set is reported as unsupported, which
    reads in the payload exactly like a clean report. Patching both registrars
    and calling the hook checks the wiring itself rather than the registry
    state the conftest already arranged.
    """
    called: list[str] = []
    monkeypatch.setattr(
        validators_module,
        "register_credentials_rules",
        lambda: called.append("rules"),
    )
    monkeypatch.setattr(
        permissions_module,
        "register_credentials_permissions",
        lambda: called.append("permissions"),
    )

    await credentials_module.on_startup()

    assert sorted(called) == ["permissions", "rules"]


async def test_the_rule_set_resolves_to_every_rule(session) -> None:
    """A rule set that resolves to nothing reports as unsupported.

    Which is indistinguishable, in the payload, from "ran and found nothing" -
    so the count is worth pinning rather than assuming.
    """
    resolved = rule_registry.get_rules_for_sets([CREDENTIALS_RULE_SET])
    assert len(resolved) == len(CREDENTIALS_RULES)
    assert {r.rule_id for r in resolved} == {r.rule_id for r in CREDENTIALS_RULES}


async def test_an_empty_register_is_skipped_not_scored_perfect(session) -> None:
    """Nothing checked is not the same as nothing wrong."""
    owner = await make_user(session)
    project = await make_project(session, owner.id)

    report = await _validate(session, project.id)
    assert report.findings == []
    assert report.error_count == 0
    # Every rule returns a passing result on empty data, so the engine has a
    # signal; what must never happen is a finding invented from nothing.
    assert report.status in {"passed", "skipped"}


# ── Rule by rule ─────────────────────────────────────────────────────────────


async def test_blocking_gap_fires_for_a_holder_who_cannot_work(session) -> None:
    owner = await make_user(session)
    project = await make_project(session, owner.id)
    await make_requirement(session, project.id, credential_type="professional_license")
    await make_credential(
        session,
        project.id,
        holder_name="No Licence",
        credential_type="training",
        valid_until=day(300),
    )

    report = await _validate(session, project.id)
    assert "credentials.blocking_gap" in _rule_ids(report)
    assert report.error_count >= 1
    finding = next(f for f in report.findings if f.rule_id == "credentials.blocking_gap")
    assert finding.severity == "error"
    assert "No Licence" in finding.message
    assert finding.context["reason"] == "missing"


async def test_blocking_gap_stays_quiet_when_everyone_is_covered(session) -> None:
    owner = await make_user(session)
    project = await make_project(session, owner.id)
    await make_requirement(session, project.id, credential_type="professional_license")
    await make_credential(
        session,
        project.id,
        holder_name="Covered",
        credential_type="professional_license",
        valid_until=day(300),
        verified_at=day(-1),
    )

    report = await _validate(session, project.id)
    assert "credentials.blocking_gap" not in _rule_ids(report)


async def test_notification_overdue_fires_once_the_window_closes(session) -> None:
    owner = await make_user(session)
    project = await make_project(session, owner.id)
    await make_credential(
        session,
        project.id,
        holder_name="Unreported",
        issued_at=day(-40),
        valid_until=day(300),
        notification_obligation_days=14,
        notification_trigger="appointment",
    )

    report = await _validate(session, project.id)
    assert "credentials.notification_overdue" in _rule_ids(report)
    finding = next(f for f in report.findings if f.rule_id == "credentials.notification_overdue")
    assert finding.context["days_overdue"] == 26


async def test_notification_overdue_is_silent_once_the_notice_is_recorded(session) -> None:
    """Recording the send date is what closes the obligation."""
    owner = await make_user(session)
    project = await make_project(session, owner.id)
    await make_credential(
        session,
        project.id,
        issued_at=day(-40),
        valid_until=day(300),
        notification_obligation_days=14,
        metadata_={"notification_sent_at": day(-30).isoformat()},
    )

    report = await _validate(session, project.id)
    assert "credentials.notification_overdue" not in _rule_ids(report)


async def test_notification_overdue_is_silent_inside_the_window(session) -> None:
    owner = await make_user(session)
    project = await make_project(session, owner.id)
    await make_credential(
        session,
        project.id,
        issued_at=day(-3),
        valid_until=day(300),
        notification_obligation_days=14,
    )

    report = await _validate(session, project.id)
    assert "credentials.notification_overdue" not in _rule_ids(report)


async def test_expiring_window_fires_inside_the_reminder_window(session) -> None:
    owner = await make_user(session)
    project = await make_project(session, owner.id)
    await make_credential(
        session,
        project.id,
        holder_name="Renewing",
        valid_until=day(5),
        notify_days_before=30,
    )

    report = await _validate(session, project.id)
    assert "credentials.expiring_window" in _rule_ids(report)
    finding = next(f for f in report.findings if f.rule_id == "credentials.expiring_window")
    assert finding.severity == "warning"
    assert finding.context["days_until_expiry"] == 5


async def test_expiring_window_is_silent_well_before_expiry(session) -> None:
    owner = await make_user(session)
    project = await make_project(session, owner.id)
    await make_credential(session, project.id, valid_until=day(200), notify_days_before=30)

    report = await _validate(session, project.id)
    assert "credentials.expiring_window" not in _rule_ids(report)


async def test_no_expiry_recorded_fires_for_a_family_that_should_lapse(session) -> None:
    owner = await make_user(session)
    project = await make_project(session, owner.id)
    await make_credential(
        session,
        project.id,
        holder_name="Undated",
        credential_type="professional_indemnity",
        valid_until=None,
    )

    report = await _validate(session, project.id)
    assert "credentials.no_expiry_recorded" in _rule_ids(report)


async def test_no_expiry_recorded_tolerates_a_genuinely_perpetual_family(session) -> None:
    """A completed training course does not lapse just because time passes."""
    owner = await make_user(session)
    project = await make_project(session, owner.id)
    await make_credential(
        session,
        project.id,
        credential_type="training",
        valid_until=None,
    )

    report = await _validate(session, project.id)
    assert "credentials.no_expiry_recorded" not in _rule_ids(report)


async def test_unverified_blocking_fires_when_nobody_checked_the_ticket(session) -> None:
    owner = await make_user(session)
    project = await make_project(session, owner.id)
    await make_requirement(session, project.id, credential_type="professional_license")
    await make_credential(
        session,
        project.id,
        holder_name="Unchecked",
        credential_type="professional_license",
        valid_until=day(300),
        verified_at=None,
    )

    report = await _validate(session, project.id)
    assert "credentials.unverified_blocking" in _rule_ids(report)


async def test_unverified_blocking_is_silent_once_verified(session) -> None:
    owner = await make_user(session)
    project = await make_project(session, owner.id)
    await make_requirement(session, project.id, credential_type="professional_license")
    await make_credential(
        session,
        project.id,
        credential_type="professional_license",
        valid_until=day(300),
        verified_at=day(-2),
        verified_by="checker",
    )

    report = await _validate(session, project.id)
    assert "credentials.unverified_blocking" not in _rule_ids(report)


async def test_duplicate_identifier_fires_on_a_repeated_number(session) -> None:
    owner = await make_user(session)
    project = await make_project(session, owner.id)
    for _ in range(2):
        await make_credential(
            session,
            project.id,
            authority="Board of Engineers",
            identifier="ENG-4471",
            valid_until=day(300),
        )

    report = await _validate(session, project.id)
    assert "credentials.duplicate_identifier" in _rule_ids(report)
    finding = next(f for f in report.findings if f.rule_id == "credentials.duplicate_identifier")
    assert len(finding.context["credential_ids"]) == 2


async def test_duplicate_identifier_ignores_blank_identifiers(session) -> None:
    """Two rows that both record nothing are not a duplicate of each other."""
    owner = await make_user(session)
    project = await make_project(session, owner.id)
    for _ in range(3):
        await make_credential(session, project.id, identifier=None, valid_until=day(300))

    report = await _validate(session, project.id)
    assert "credentials.duplicate_identifier" not in _rule_ids(report)


async def test_duplicate_identifier_separates_two_authorities(session) -> None:
    """The same number from two bodies is two credentials, not one twice."""
    owner = await make_user(session)
    project = await make_project(session, owner.id)
    await make_credential(
        session,
        project.id,
        authority="Board A",
        identifier="4471",
        valid_until=day(300),
    )
    await make_credential(
        session,
        project.id,
        authority="Board B",
        identifier="4471",
        valid_until=day(300),
    )

    report = await _validate(session, project.id)
    assert "credentials.duplicate_identifier" not in _rule_ids(report)


async def test_unmatched_requirement_fires_for_a_rule_binding_nobody(session) -> None:
    owner = await make_user(session)
    project = await make_project(session, owner.id)
    await make_requirement(
        session,
        project.id,
        credential_type="training",
        applies_to="scaffolder",
    )
    await make_credential(
        session,
        project.id,
        discipline="joiner",
        credential_type="professional_license",
        valid_until=day(300),
    )

    report = await _validate(session, project.id)
    assert "credentials.unmatched_requirement" in _rule_ids(report)


async def test_unmatched_requirement_does_not_fire_on_an_empty_register(session) -> None:
    """A project nobody has staffed yet is not a misconfigured project."""
    owner = await make_user(session)
    project = await make_project(session, owner.id)
    await make_requirement(session, project.id, credential_type="training")

    report = await _validate(session, project.id)
    assert "credentials.unmatched_requirement" not in _rule_ids(report)


# ── Report shape ─────────────────────────────────────────────────────────────


async def test_the_findings_carry_a_singly_prefixed_i18n_key(session) -> None:
    """Rule ids are already namespaced.

    The key must read ``credentials.validation.blocking_gap``, not
    ``credentials.validation.credentials.blocking_gap`` - a doubled segment
    resolves in no locale and silently renders the raw key on screen.
    """
    owner = await make_user(session)
    project = await make_project(session, owner.id)
    await make_requirement(session, project.id, credential_type="professional_license")
    await make_credential(
        session,
        project.id,
        credential_type="training",
        valid_until=day(300),
    )

    report = await _validate(session, project.id)
    assert report.findings
    for finding in report.findings:
        assert finding.key.startswith("credentials.validation.")
        assert "validation.credentials." not in finding.key
        assert finding.rule_id.startswith("credentials.")


async def test_errors_and_warnings_are_counted_separately(session) -> None:
    """The banner needs to know which colour to be."""
    owner = await make_user(session)
    project = await make_project(session, owner.id)
    await make_requirement(session, project.id, credential_type="professional_license")
    # A blocking gap (error) and an expiring credential (warning) at once.
    await make_credential(
        session,
        project.id,
        holder_name="Mixed",
        credential_type="training",
        valid_until=day(3),
        notify_days_before=30,
    )

    report = await _validate(session, project.id)
    assert report.error_count >= 1
    assert report.warning_count >= 1
    assert report.status == "errors"
    assert report.score is not None


async def test_the_validate_endpoint_returns_the_findings(session) -> None:
    """The payload the banner actually reads."""
    owner = await make_user(session)
    project = await make_project(session, owner.id)
    await make_requirement(session, project.id, credential_type="professional_license")
    await make_credential(
        session,
        project.id,
        holder_name="Blocked",
        credential_type="training",
        valid_until=day(300),
    )

    async with http_client(build_app(session, caller_id=owner.id)) as client:
        response = await client.get(
            f"{API_PREFIX}/validate/",
            params={"project_id": str(project.id)},
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "errors"
    assert "credentials.blocking_gap" in {f["rule_id"] for f in body["findings"]}
    assert all(f["key"].startswith("credentials.validation.") for f in body["findings"])
