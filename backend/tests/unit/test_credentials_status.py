# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Pure status derivation and label localization for the credentials registry.

Pins the jurisdiction-neutral status maths: a perpetual credential stays active,
the reminder window is inclusive on the boundary day, an expired window flips to
expired, and manual suspended/revoked states are preserved by the auto-derive
path. Also checks the /meta label lookups localise with an English fallback and
never leak a raw code. No DB, no clock.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

from app.modules.credentials import intl
from app.modules.credentials.models import Credential, CredentialRequirement
from app.modules.credentials.service import (
    RequirementService,
    _holder_key,
    recompute_status,
)

_TODAY = date(2026, 7, 21)


# ── recompute_status ───────────────────────────────────────────────────────


def test_perpetual_credential_is_active() -> None:
    assert recompute_status(_TODAY, None, 30) == "active"


def test_far_future_is_active() -> None:
    assert recompute_status(_TODAY, _TODAY + timedelta(days=200), 30) == "active"


def test_within_window_is_expiring_soon() -> None:
    assert recompute_status(_TODAY, _TODAY + timedelta(days=15), 30) == "expiring_soon"


def test_boundary_day_is_inclusive() -> None:
    # Exactly notify_days_before out already counts as expiring_soon.
    assert recompute_status(_TODAY, _TODAY + timedelta(days=30), 30) == "expiring_soon"


def test_past_valid_until_is_expired() -> None:
    assert recompute_status(_TODAY, _TODAY - timedelta(days=1), 30) == "expired"


def test_expiry_day_itself_is_expiring_not_expired() -> None:
    # today == valid_until: still valid today, so expiring_soon, not expired.
    assert recompute_status(_TODAY, _TODAY, 30) == "expiring_soon"


def test_manual_states_are_preserved() -> None:
    # Even with an expired window, a manual state is not auto-overwritten.
    assert recompute_status(_TODAY, _TODAY - timedelta(days=5), 30, current_status="suspended") == "suspended"
    assert recompute_status(_TODAY, _TODAY + timedelta(days=5), 30, current_status="revoked") == "revoked"


def test_zero_notify_window_only_flags_on_expiry_day() -> None:
    assert recompute_status(_TODAY, _TODAY + timedelta(days=1), 0) == "active"
    assert recompute_status(_TODAY, _TODAY, 0) == "expiring_soon"


# ── intl labels ────────────────────────────────────────────────────────────


def test_type_labels_localise() -> None:
    assert intl.describe_type("professional_license", "en") == "Professional licence"
    assert intl.describe_type("professional_license", "ru") == "Профессиональная лицензия"
    assert intl.describe_type("professional_license", "de") == "Berufszulassung"


def test_status_labels_localise() -> None:
    assert intl.describe_status("expiring_soon", "es") == "Vence pronto"
    assert intl.describe_status("revoked", "de") == "Widerrufen"


def test_unknown_locale_falls_back_to_english() -> None:
    assert intl.describe_type("certification", "zz") == "Certification"
    assert intl.describe_type("certification", None) == "Certification"


def test_unknown_code_is_humanised_not_raw() -> None:
    # A pack-introduced code with no translation degrades to a readable label.
    assert intl.describe_type("site_welfare_ticket", "en") == "Site Welfare Ticket"


# ── Compliance decisions (pure, no session) ──────────────────────────────────
#
# These drive the requirement-matching and gap-grading logic on unattached ORM
# instances. They live here rather than beside the module's other compliance
# tests because ``tests/unit`` is the lane CI actually gates, and the rules that
# decide whether somebody is turned away at the gate are the ones least
# affordable to leave uncovered.


def _credential(**fields: object) -> Credential:
    """An unattached credential with the columns these rules read."""
    defaults: dict[str, object] = {
        "holder_name": "Holder",
        "holder_kind": "person",
        "holder_user_id": None,
        "credential_type": "professional_license",
        "discipline": None,
        "valid_until": None,
        "notify_days_before": 30,
        "status": "active",
        "verified_at": None,
    }
    defaults.update(fields)
    return Credential(**defaults)  # type: ignore[arg-type]


def _requirement(**fields: object) -> CredentialRequirement:
    """An unattached requirement with the columns these rules read."""
    defaults: dict[str, object] = {
        "credential_type": "professional_license",
        "applies_to": "all",
        "holder_kind": "person",
        "is_blocking": True,
        "grace_days": 0,
    }
    defaults.update(fields)
    requirement = CredentialRequirement(**defaults)  # type: ignore[arg-type]
    requirement.id = uuid.uuid4()
    return requirement


def test_an_all_requirement_binds_every_holder_of_its_kind() -> None:
    requirement = _requirement(applies_to="all")
    assert RequirementService._applies(requirement, None, "person") is True
    assert RequirementService._applies(requirement, "joiner", "person") is True
    # A different holder kind is a different obligation.
    assert RequirementService._applies(requirement, "joiner", "company") is False


def test_a_discipline_requirement_binds_only_that_discipline() -> None:
    requirement = _requirement(applies_to="supervisor")
    assert RequirementService._applies(requirement, "supervisor", "person") is True
    # Case and padding are how a real roster is typed, not a different trade.
    assert RequirementService._applies(requirement, " Supervisor ", "person") is True
    assert RequirementService._applies(requirement, "bricklayer", "person") is False
    # A holder with no discipline cannot be shown to meet a scoped rule.
    assert RequirementService._applies(requirement, None, "person") is False


def test_a_missing_credential_is_a_blocking_gap() -> None:
    gap, satisfying = RequirementService(None)._assess(_requirement(), [], today=_TODAY)
    assert satisfying is None
    assert gap is not None
    assert gap.reason == "missing"
    assert gap.is_blocking is True
    assert gap.within_grace is False


def test_a_current_credential_satisfies_and_produces_no_gap() -> None:
    credential = _credential(valid_until=_TODAY + timedelta(days=200))
    gap, satisfying = RequirementService(None)._assess(_requirement(), [credential], today=_TODAY)
    assert gap is None
    assert satisfying is credential


def test_the_grace_window_boundary_is_inclusive() -> None:
    """Day 14 of a 14-day grace is still inside it; day 15 is not.

    The boundary is the whole point of the setting, so it is pinned on both
    sides rather than sampled in the middle.
    """
    service = RequirementService(None)
    requirement = _requirement(grace_days=14)

    inside, _ = service._assess(
        requirement,
        [_credential(valid_until=_TODAY - timedelta(days=14))],
        today=_TODAY,
    )
    outside, _ = service._assess(
        requirement,
        [_credential(valid_until=_TODAY - timedelta(days=15))],
        today=_TODAY,
    )

    assert inside is not None and inside.within_grace is True
    assert outside is not None and outside.within_grace is False


def test_a_future_expiry_is_a_warning_gap_not_a_lapse() -> None:
    """Valid until Friday is valid today, so it never sits in the grace logic."""
    gap, _ = RequirementService(None)._assess(
        _requirement(grace_days=14),
        [_credential(valid_until=_TODAY + timedelta(days=5))],
        today=_TODAY,
    )
    assert gap is not None
    assert gap.reason == "expiring_soon"
    assert gap.within_grace is False


def test_the_healthiest_credential_of_several_is_the_one_judged() -> None:
    """A renewal beside a lapsed row satisfies the requirement."""
    lapsed = _credential(valid_until=_TODAY - timedelta(days=100))
    renewed = _credential(valid_until=_TODAY + timedelta(days=365))
    gap, satisfying = RequirementService(None)._assess(_requirement(), [lapsed, renewed], today=_TODAY)
    assert gap is None
    assert satisfying is renewed


def test_a_perpetual_credential_outranks_a_dated_one() -> None:
    """Neither is lapsing, so the one that never will is the one to report."""
    dated = _credential(valid_until=_TODAY + timedelta(days=400))
    perpetual = _credential(valid_until=None)
    _gap, satisfying = RequirementService(None)._assess(_requirement(), [dated, perpetual], today=_TODAY)
    assert satisfying is perpetual


def test_a_revoked_credential_blocks_regardless_of_its_dates() -> None:
    gap, satisfying = RequirementService(None)._assess(
        _requirement(),
        [_credential(valid_until=_TODAY + timedelta(days=900), status="revoked")],
        today=_TODAY,
    )
    assert satisfying is None
    assert gap is not None
    assert gap.reason == "revoked"


def test_one_person_under_two_names_is_one_holder_when_linked() -> None:
    """The user link is the identity; the typed name is not."""
    user_id = uuid.uuid4()
    a = _credential(holder_name="Jo Smith", holder_user_id=user_id)
    b = _credential(holder_name="Josephine Smith", holder_user_id=user_id)
    assert _holder_key(a) == _holder_key(b)


def test_two_unlinked_holders_are_told_apart_by_name_not_case() -> None:
    """Without a user link the case-folded name is the best available key."""
    assert _holder_key(_credential(holder_name="jo smith")) == _holder_key(_credential(holder_name="Jo Smith"))
    assert _holder_key(_credential(holder_name="Jo Smith")) != _holder_key(_credential(holder_name="Sam Reed"))
