# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Item state machine table, the shipped catalogues, and the approval target kind.

The catalogue tests read every shipped file through module 1's kind registry,
so a schedule that does not validate, bands that are not monotonic, a
statutory figure without a URL or review status, or a label key missing from
the English message bundle fails here, not on a customer's project.
"""

from __future__ import annotations

import itertools
import json
from typing import get_args

import pytest

from app.modules.commitment_release.catalogue import (
    ABORT_BASIS_KIND,
    AUTHORITY_SCHEDULE_KIND,
    CATALOGUE_ROOT,
    AuthoritySchedule,
    register_kinds,
    validate_abort_basis,
    validate_authority_schedule,
)
from app.modules.commitment_release.fsm import ITEM_FSM, ITEM_STATES
from app.modules.project_governance.catalogue_kinds import get_catalogue_kind

# The table, written out pair by pair. It is deliberately NOT built from the module's own tuples:
# a table derived from the code can only agree with the code.
ALLOWED: set[tuple[str, str]] = {
    # a release is requested (first release, next tranche, renewal)
    ("planned", "release_requested"),
    ("partially_released", "release_requested"),
    ("released", "release_requested"),
    ("committed", "release_requested"),
    ("re_release_required", "release_requested"),
    # decided, rejected or withdrawn
    ("release_requested", "planned"),
    ("release_requested", "partially_released"),
    ("release_requested", "released"),
    ("release_requested", "committed"),
    ("release_requested", "re_release_required"),
    # an approved abort request
    ("release_requested", "aborted"),
    # recompute from the linked documents: every pair of the five recomputed states
    ("released", "partially_released"),
    ("released", "committed"),
    ("released", "closed"),
    ("released", "re_release_required"),
    ("partially_released", "released"),
    ("partially_released", "committed"),
    ("partially_released", "closed"),
    ("partially_released", "re_release_required"),
    ("committed", "released"),
    ("committed", "partially_released"),
    ("committed", "closed"),
    ("committed", "re_release_required"),
    ("closed", "released"),
    ("closed", "partially_released"),
    ("closed", "committed"),
    ("closed", "re_release_required"),
    ("re_release_required", "released"),
    ("re_release_required", "partially_released"),
    ("re_release_required", "committed"),
    ("re_release_required", "closed"),
    # hold and resume
    ("planned", "on_hold"),
    ("released", "on_hold"),
    ("partially_released", "on_hold"),
    ("committed", "on_hold"),
    ("re_release_required", "on_hold"),
    ("on_hold", "planned"),
    ("on_hold", "released"),
    ("on_hold", "partially_released"),
    ("on_hold", "committed"),
    ("on_hold", "re_release_required"),
    # abort
    ("planned", "aborted"),
    ("released", "aborted"),
    ("partially_released", "aborted"),
    ("committed", "aborted"),
    ("re_release_required", "aborted"),
    ("on_hold", "aborted"),
    # transfer
    ("planned", "transferred"),
    ("released", "transferred"),
    ("partially_released", "transferred"),
    ("committed", "transferred"),
    ("re_release_required", "transferred"),
}
ALL_STATES = (
    "planned",
    "release_requested",
    "released",
    "partially_released",
    "committed",
    "closed",
    "re_release_required",
    "on_hold",
    "aborted",
    "transferred",
)


def test_the_literal_table_covers_exactly_the_declared_states() -> None:
    assert set(ALL_STATES) == set(ITEM_STATES)
    assert len(ALLOWED) == 52


def test_recompute_can_reach_every_recomputed_state_from_every_other() -> None:
    """Review finding 6: linking a completed contract to a released item, or removing the link that
    forced a re-release, must be a legal move and not a 409 on the user's own write."""
    for src, dst in (
        ("released", "closed"),
        ("partially_released", "closed"),
        ("re_release_required", "released"),
        ("re_release_required", "partially_released"),
        ("closed", "partially_released"),
        ("closed", "re_release_required"),
    ):
        assert ITEM_FSM.has_transition(src, dst), (src, dst)


@pytest.mark.parametrize(("src", "dst"), sorted(itertools.product(ALL_STATES, ALL_STATES)))
def test_item_transition_table(src: str, dst: str) -> None:
    assert ITEM_FSM.has_transition(src, dst) is ((src, dst) in ALLOWED)


def test_states_and_terminals() -> None:
    assert ITEM_FSM.all_states == set(ITEM_STATES)
    assert ITEM_FSM.initial == "planned"
    assert {s for s in ITEM_STATES if ITEM_FSM.is_terminal(s)} == {"aborted", "transferred"}
    # "rejected", "withdrawn" and "lapsed" are outcomes and flags, never states.
    assert not {"rejected", "withdrawn", "lapsed"} & set(ITEM_STATES)


# ── catalogues ─────────────────────────────────────────────────────────────


def _en_keys() -> dict:
    path = CATALOGUE_ROOT.parent / "messages" / "en.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _has(tree: dict, key: str) -> bool:
    node = tree
    for part in key.split("."):
        if not isinstance(node, dict) or part not in node:
            return False
        node = node[part]
    return isinstance(node, str)


def test_every_shipped_catalogue_validates_through_the_registry() -> None:
    register_kinds()
    schedules = get_catalogue_kind(AUTHORITY_SCHEDULE_KIND).shipped()
    bases = get_catalogue_kind(ABORT_BASIS_KIND).shipped()
    assert {s.id for s in schedules} == {"neutral", "de_public_owner", "uk_public_body", "us_federal_owner"}
    assert {b.id for b in bases} == {
        "de_bgb_648",
        "de_vob_b_8_1",
        "nec4_ecc_client_reason",
        "far_49_convenience",
        "supply_cancellation_schedule",
        "none_free_cancellation",
        "custom",
    }


def test_neutral_has_three_tiers_and_no_statutory_figure() -> None:
    register_kinds()
    neutral = get_catalogue_kind(AUTHORITY_SCHEDULE_KIND).get_shipped("neutral")
    assert len(neutral.tiers) == 3
    assert neutral.currency is None
    assert not [b for b in neutral.bands if b.statutory]


def test_every_statutory_figure_carries_a_source_and_a_review_status() -> None:
    register_kinds()
    figures = []
    for s in get_catalogue_kind(AUTHORITY_SCHEDULE_KIND).shipped():
        figures += [*s.bands, *s.novelty_flags]
    for b in get_catalogue_kind(ABORT_BASIS_KIND).shipped():
        figures += list(b.parameters.values())
    statutory = [f for f in figures if f.statutory]
    assert statutory
    assert all(f.source_url and f.review_status is not None for f in statutory)


def test_statutory_abort_bases_ship_unconfirmed() -> None:
    register_kinds()
    for b in get_catalogue_kind(ABORT_BASIS_KIND).shipped():
        if any(p.statutory for p in b.parameters.values()):
            assert str(b.review_status) == "unconfirmed", b.id


def test_every_label_key_of_every_shipped_catalogue_is_in_the_english_bundle() -> None:
    register_kinds()
    en = _en_keys()
    keys: set[str] = set()
    for s in get_catalogue_kind(AUTHORITY_SCHEDULE_KIND).shipped():
        keys |= {s.name_key, s.description_key}
        keys |= {t.name_key for t in s.commitment_types} | {t.name_key for t in s.tiers}
        keys |= {f.name_key for f in s.novelty_flags} | {b.note_key for b in s.bands if b.note_key}
    for b in get_catalogue_kind(ABORT_BASIS_KIND).shipped():
        keys |= {b.name_key, b.description_key} | {p.note_key for p in b.parameters.values() if p.note_key}
    missing = sorted(k for k in keys if k and not _has(en, k))
    assert not missing


def _raw(name: str) -> dict:
    return json.loads((CATALOGUE_ROOT / AUTHORITY_SCHEDULE_KIND / f"{name}.json").read_text(encoding="utf-8"))


def test_non_monotonic_bands_are_refused() -> None:
    body = _raw("neutral")
    body["bands"][1]["max_amount"] = "40000"  # sponsor below project manager
    errors = validate_authority_schedule(AuthoritySchedule.model_validate(body), "shipped")
    assert any(e.startswith("bands_not_monotonic") for e in errors)
    assert not validate_authority_schedule(AuthoritySchedule.model_validate(_raw("neutral")), "shipped")


def test_an_open_band_below_the_top_is_refused() -> None:
    body = _raw("neutral")
    body["bands"][0]["max_amount"] = None
    errors = validate_authority_schedule(AuthoritySchedule.model_validate(body), "shipped")
    assert any(e.startswith("bands_not_monotonic") for e in errors)


def test_a_statutory_band_without_source_is_refused() -> None:
    body = _raw("us_federal_owner")
    body["bands"][0].pop("source_url")
    errors = validate_authority_schedule(AuthoritySchedule.model_validate(body), "shipped")
    assert any(e.startswith("statutory_figure_without_source") for e in errors)


def test_a_user_approver_is_tenant_only() -> None:
    body = _raw("neutral")
    body["tiers"][0]["approver"] = {"kind": "user", "ref": "00000000-0000-0000-0000-000000000001"}
    obj = AuthoritySchedule.model_validate(body)
    assert any(e.startswith("user_approver_in_shipped_schedule") for e in validate_authority_schedule(obj, "shipped"))
    assert not validate_authority_schedule(obj, "tenant")


def test_a_statutory_basis_marked_verified_is_refused() -> None:
    register_kinds()
    b = get_catalogue_kind(ABORT_BASIS_KIND).get_shipped("de_bgb_648")
    forged = b.model_copy(update={"review_status": "verified"})
    assert "statutory_basis_must_be_unconfirmed" in validate_abort_basis(forged, "shipped")


def test_the_store_diff_keys_bands_by_code() -> None:
    from app.modules.project_governance.catalogue_store import diff_bodies

    register_kinds()
    old = _raw("neutral")
    new = _raw("neutral")
    new["bands"][2]["max_amount"] = "6000000"
    groups = get_catalogue_kind(AUTHORITY_SCHEDULE_KIND).diff_groups
    assert diff_bodies(old, new, groups)["bands"]["changed"] == ["any_board"]


def test_approval_routes_accepts_the_commitment_release_kind_in_model_and_schema() -> None:
    from app.modules.approval_routes.models import TARGET_KINDS
    from app.modules.approval_routes.schemas import TargetKindLiteral

    assert "commitment_release" in TARGET_KINDS
    assert "commitment_release" in get_args(TargetKindLiteral)
