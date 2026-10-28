# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The install endpoint's proof that a human reviewed what is being written.

These pin the property that matters: a token is only accepted for the exact
spec, the exact user and the time window it was issued for. Every test names the
hole it closes, because a review step nobody can bypass is the whole reason the
module builder is allowed to write Python at all.

Run:
    cd backend
    python -m pytest tests/test_module_builder_review_token.py -q
"""

from __future__ import annotations

import uuid

import pytest

from app.modules.module_builder.review_token import (
    REVIEW_TOKEN_TTL_SECONDS,
    ReviewTokenInvalid,
    issue,
    spec_digest,
    verify,
)
from app.modules.module_builder.spec import EntitySpec, FieldSpec, ModuleSpec, RuleSpec


def _spec(**overrides) -> ModuleSpec:
    payload = {
        "key": "pour_register",
        "display_name": "Pour Register",
        "entity": EntitySpec(
            name="pour",
            display_name="Pour",
            project_scoped=False,
            fields=[FieldSpec(name="title", label="Title", type="text", required=True)],
        ),
        "rules": [RuleSpec(code="TITLE_REQUIRED", message="A pour needs a title.", kind="required", field="title")],
    }
    payload.update(overrides)
    return ModuleSpec(**payload)  # type: ignore[arg-type]


def test_a_previewed_spec_installs():
    """The ordinary path: preview then install, same spec, same person."""
    spec, user = _spec(), uuid.uuid4()
    verify(issue(spec, user), spec, user)


def test_a_spec_edited_after_the_review_is_refused():
    """The hole the whole mechanism exists for.

    Reading the generated files and then installing something else is exactly
    what a review step has to prevent, so the token is bound to the spec that
    was rendered rather than merely to the fact that some preview happened.
    """
    user = uuid.uuid4()
    token = issue(_spec(), user)
    with pytest.raises(ReviewTokenInvalid, match="not the spec that was previewed"):
        verify(token, _spec(display_name="Something Else"), user)


def test_one_persons_review_does_not_authorise_anothers_install():
    token = issue(_spec(), uuid.uuid4())
    with pytest.raises(ReviewTokenInvalid, match="different user"):
        verify(token, _spec(), uuid.uuid4())


def test_an_install_without_a_real_token_is_refused():
    """A caller cannot mint its own: the signature is over a server-held secret,
    so a well-formed guess is worth no more than an empty string."""
    spec, user = _spec(), uuid.uuid4()
    for forged in ("", ".", "not-a-token", "abc.def", issue(spec, user)[:-4] + "AAAA"):
        with pytest.raises(ReviewTokenInvalid):
            verify(forged, spec, user)


def test_a_token_expires():
    spec, user = _spec(), uuid.uuid4()
    token = issue(spec, user, now=1_000_000)
    verify(token, spec, user, now=1_000_000 + REVIEW_TOKEN_TTL_SECONDS - 1)
    with pytest.raises(ReviewTokenInvalid, match="expired"):
        verify(token, spec, user, now=1_000_000 + REVIEW_TOKEN_TTL_SECONDS + 1)


def test_the_digest_reads_meaning_not_field_order():
    """Two requests that mean the same module must digest the same, or an
    ordinary round trip through JSON would look like tampering.

    The order is varied on the body rather than left to chance, because two
    specs built the same way would agree whatever the digest did with order.
    """
    payload = _spec().model_dump(mode="json")
    reordered = dict(reversed(list(payload.items())))
    assert list(reordered) != list(payload)
    assert spec_digest(ModuleSpec(**reordered)) == spec_digest(ModuleSpec(**payload))
    assert spec_digest(_spec()) != spec_digest(_spec(version="0.2.0"))
