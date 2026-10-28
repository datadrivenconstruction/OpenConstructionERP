# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Pure workflow maths and provider abstraction for the e-signature registry.

Pins the jurisdiction-neutral, crypto-free logic without a DB or a clock:

    - session status recompute from attestations vs the signatory map;
    - the ``all_required_signatories_signed`` validation rule;
    - delta-by-hash (which signatures went stale when the content hash moved);
    - certificate-metadata expiry flagging;
    - the issued-set hash manifest;
    - the SignatureProvider / NullProvider abstraction (records attestations,
      never verifies cryptographically, never touches keys).
    - the /meta label lookups localise with an English fallback.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

from app.modules.signing import intl
from app.modules.signing.providers import (
    DEFAULT_PROVIDER,
    NullProvider,
    ProviderInitiation,
    ProviderStatus,
    SignatureProvider,
    SignedArtifact,
    get_provider,
    register_provider,
)
from app.modules.signing.schemas import CAPABILITIES, SigningSessionResponse
from app.modules.signing.service import (
    all_required_signatories_signed,
    cert_expiry_flags,
    delta_by_hash,
    issued_set_manifest,
    recompute_session_status,
)

_NOW = datetime(2026, 7, 21, tzinfo=UTC)
_TODAY = date(2026, 7, 21)


def _sig(
    role: str,
    *,
    status: str = "signed",
    content_hash: str = "h1",
    name: str | None = None,
    cert_valid_until: date | None = None,
    session_id: str = "s",
    sid: str = "sig",
):
    return SimpleNamespace(
        id=sid,
        session_id=session_id,
        signatory_name=name or f"{role}-person",
        signatory_role=role,
        status=status,
        content_hash=content_hash,
        cert_subject="CN=Signer",
        cert_valid_until=cert_valid_until,
    )


_MAP = [
    {"name": "A", "role": "contractor", "required": True},
    {"name": "B", "role": "client", "required": True},
    {"name": "C", "role": "witness", "required": False},
]


# ── recompute_session_status ────────────────────────────────────────────────


def test_no_signatures_awaiting() -> None:
    assert recompute_session_status(_MAP, []) == "awaiting_signatures"


def test_explicit_draft_with_nothing_signed_stays_draft() -> None:
    assert recompute_session_status(_MAP, [], current_status="draft") == "draft"


def test_some_required_signed_is_partial() -> None:
    sigs = [_sig("contractor")]
    assert recompute_session_status(_MAP, sigs) == "partially_signed"


def test_all_required_signed_is_fully_signed() -> None:
    sigs = [_sig("contractor"), _sig("client")]
    assert recompute_session_status(_MAP, sigs) == "fully_signed"


def test_optional_signatory_not_needed_for_fully_signed() -> None:
    # witness is required=False, so contractor + client alone are enough.
    sigs = [_sig("contractor"), _sig("client")]
    assert recompute_session_status(_MAP, sigs) == "fully_signed"


def test_decline_is_terminal() -> None:
    sigs = [_sig("contractor"), _sig("client", status="declined")]
    assert recompute_session_status(_MAP, sigs) == "declined"


def test_declined_current_status_preserved() -> None:
    assert recompute_session_status(_MAP, [], current_status="declined") == "declined"


def test_expiry_flips_to_expired_when_not_fully_signed() -> None:
    past = _NOW - timedelta(days=1)
    sigs = [_sig("contractor")]
    assert recompute_session_status(_MAP, sigs, expires_at=past, now=_NOW) == "expired"


def test_fully_signed_beats_expiry() -> None:
    past = _NOW - timedelta(days=1)
    sigs = [_sig("contractor"), _sig("client")]
    assert recompute_session_status(_MAP, sigs, expires_at=past, now=_NOW) == "fully_signed"


# ── all_required_signatories_signed (validation rule) ───────────────────────


def test_validation_rule_true_when_all_required_signed() -> None:
    sigs = [_sig("contractor"), _sig("client")]
    assert all_required_signatories_signed(_MAP, sigs) is True


def test_validation_rule_false_when_missing_required() -> None:
    assert all_required_signatories_signed(_MAP, [_sig("contractor")]) is False


def test_validation_rule_false_when_no_required_defined() -> None:
    only_optional = [{"name": "C", "role": "witness", "required": False}]
    assert all_required_signatories_signed(only_optional, [_sig("witness")]) is False


# ── delta_by_hash ───────────────────────────────────────────────────────────


def test_delta_by_hash_flags_stale_signatures() -> None:
    sigs = [
        _sig("contractor", content_hash="old", name="Alice"),
        _sig("client", content_hash="new", name="Bob"),
    ]
    session = SimpleNamespace(signatures=sigs, document_content_hash="new")
    assert delta_by_hash(session, "new") == {"Alice"}


def test_delta_by_hash_ignores_declined() -> None:
    sigs = [_sig("contractor", content_hash="old", name="Alice", status="declined")]
    assert delta_by_hash(sigs, "new") == set()


def test_delta_by_hash_none_stale_when_all_current() -> None:
    sigs = [_sig("contractor", content_hash="new", name="Alice")]
    assert delta_by_hash(sigs, "new") == set()


# ── cert_expiry_flags ───────────────────────────────────────────────────────


def test_cert_expiry_flags_expired_and_soon() -> None:
    sigs = [
        _sig("contractor", name="Expired", cert_valid_until=_TODAY - timedelta(days=2), sid="1"),
        _sig("client", name="Soon", cert_valid_until=_TODAY + timedelta(days=10), sid="2"),
        _sig("witness", name="Far", cert_valid_until=_TODAY + timedelta(days=400), sid="3"),
        _sig("extra", name="NoCert", cert_valid_until=None, sid="4"),
    ]
    flags = cert_expiry_flags(sigs, today=_TODAY, within_days=30)
    names = [f["signatory_name"] for f in flags]
    assert names == ["Expired", "Soon"]  # sorted ascending by days_until_expiry
    assert flags[0]["expired"] is True
    assert flags[1]["expired"] is False


def test_cert_expiry_ignores_declined() -> None:
    sigs = [_sig("contractor", name="D", status="declined", cert_valid_until=_TODAY - timedelta(days=1))]
    assert cert_expiry_flags(sigs, today=_TODAY) == []


# ── issued_set_manifest ─────────────────────────────────────────────────────


def test_issued_set_manifest_maps_ref_to_hash() -> None:
    sessions = [
        SimpleNamespace(document_ref="doc/a", document_content_hash="h1"),
        SimpleNamespace(document_ref="doc/b", document_content_hash="h2"),
    ]
    assert issued_set_manifest(sessions) == {"doc/a": "h1", "doc/b": "h2"}


def test_issued_set_manifest_later_hash_wins() -> None:
    sessions = [
        SimpleNamespace(document_ref="doc/a", document_content_hash="h1"),
        SimpleNamespace(document_ref="doc/a", document_content_hash="h2"),
    ]
    assert issued_set_manifest(sessions) == {"doc/a": "h2"}


# ── Provider abstraction ────────────────────────────────────────────────────


def test_null_provider_is_a_signature_provider() -> None:
    assert isinstance(DEFAULT_PROVIDER, SignatureProvider)
    assert isinstance(NullProvider(), SignatureProvider)


def test_null_provider_describe_declares_no_crypto_no_keys() -> None:
    desc = NullProvider().describe()
    assert desc["cryptographic_verification"] is False
    assert desc["accepts_keys_or_passwords"] is False
    assert desc["records_attestations"] is True


def test_null_provider_verify_is_metadata_only() -> None:
    good = NullProvider().verify_attestation({"signatory_name": "A", "signatory_role": "client", "content_hash": "h"})
    assert good.ok is True
    assert good.cryptographically_verified is False

    bad = NullProvider().verify_attestation({"signatory_name": "", "signatory_role": "", "content_hash": ""})
    assert bad.ok is False
    assert "missing content_hash" in bad.issues


def test_null_provider_initiate_accepts_with_no_external_reference() -> None:
    session = SimpleNamespace(signatory_map=[], expires_at=None, status="draft")
    result = NullProvider().initiate(session)
    assert isinstance(result, ProviderInitiation)
    assert result.accepted is True
    assert result.external_reference is None
    assert result.provider_name == "null"
    assert result.details["mode"] == "manual_attestation"
    # as_dict() round-trips into plain JSON-safe types.
    d = result.as_dict()
    assert d["accepted"] is True
    assert d["provider_name"] == "null"


def test_null_provider_check_status_matches_recompute_session_status() -> None:
    """The provider must not diverge from the pure function it delegates to."""
    signatory_map = [{"role": "client", "required": True}]
    signed = [_sig("client", status="signed")]
    session = SimpleNamespace(signatory_map=signatory_map, expires_at=None, status="awaiting_signatures")

    direct = recompute_session_status(
        signatory_map, signed, expires_at=None, now=_NOW, current_status="awaiting_signatures"
    )
    via_provider = NullProvider().check_status(session, signed)

    assert isinstance(via_provider, ProviderStatus)
    assert via_provider.status == direct == "fully_signed"
    assert via_provider.provider_name == "null"


def test_null_provider_fetch_artifact_unavailable_before_any_signature() -> None:
    session = SimpleNamespace(document_ref="doc/a", document_content_hash="h1")
    artifact = NullProvider().fetch_artifact(session, [])
    assert isinstance(artifact, SignedArtifact)
    assert artifact.available is False
    assert artifact.certificate is None
    assert artifact.manifest == {"doc/a": "h1"}


def test_null_provider_fetch_artifact_available_once_signed() -> None:
    session = SimpleNamespace(document_ref="doc/a", document_content_hash="h1")
    signed = [_sig("client", status="signed")]
    artifact = NullProvider().fetch_artifact(session, signed)
    assert artifact.available is True
    assert artifact.certificate is None  # attestation-only: never a certificate file
    d = artifact.as_dict()
    assert d["manifest"] == {"doc/a": "h1"}


def test_get_provider_defaults_to_null_provider_for_unknown_capability() -> None:
    # A capability outside CAPABILITIES entirely - a typo, or a vocabulary a
    # future pack introduces. This is what the test name has always claimed to
    # cover; until 2026-08-30 the body passed "qualified_electronic", a known,
    # documented, pattern-validated tier, so the name read as "a typo must not
    # crash" while the body quietly blessed "the highest legal tier downgrades".
    # The known-tier case now has its own test below, which is where it belongs.
    provider = get_provider("mobile_id_signature")
    assert provider is DEFAULT_PROVIDER

    provider_no_capability = get_provider(None)
    assert provider_no_capability is DEFAULT_PROVIDER


def test_a_known_capability_with_no_adapter_resolves_to_a_weaker_provider() -> None:
    """Every declared tier resolves, and three of the four resolve to less.

    ``CAPABILITIES`` is the vocabulary the API accepts and validates against.
    Core ships one provider, which delivers ``simple_electronic``. So for every
    tier except that one, ``get_provider`` hands back something that delivers
    less than was asked for, and it does so without raising - which is the
    intended behaviour (refusing would break sessions on upgrade) and exactly
    why the difference has to be legible on the object rather than swallowed.
    """
    for capability in CAPABILITIES:
        provider = get_provider(capability)
        assert provider is DEFAULT_PROVIDER
        if capability == "simple_electronic":
            assert provider.capability == capability
        else:
            assert provider.capability != capability, f"{capability} resolved to a provider claiming to deliver it"

    # The discriminator this fix rests on: asking for the strongest tier gets a
    # provider that says, on itself, that it delivers the weakest one and
    # performs no cryptography. Nothing has to guess.
    resolved = get_provider("qualified_electronic")
    assert resolved.capability == "simple_electronic"
    assert resolved.describe()["cryptographic_verification"] is False


def test_an_unstamped_session_reports_no_delivered_capability() -> None:
    """NULL must survive serialisation as NULL, never as the requirement.

    Every session row written before ``delivered_capability`` existed has NULL
    in it. The one change that would quietly undo this whole fix is a
    ``delivered or required`` anywhere between the column and the screen: the
    two values would then agree, every other test would still pass, and the
    response would be back to reporting a tier nothing delivered. So assert the
    absence, not just the presence.
    """
    unstamped = SimpleNamespace(
        id=uuid4(),
        project_id=uuid4(),
        document_ref="contract/legacy",
        document_content_hash="h",
        provider_capability="qualified_electronic",
        delivered_capability=None,
        signatory_map=[],
        status="fully_signed",
        expires_at=None,
        metadata_={},
        created_by=None,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    payload = SigningSessionResponse.model_validate(unstamped).model_dump()
    assert payload["provider_capability"] == "qualified_electronic"
    assert payload["delivered_capability"] is None


def test_register_provider_overrides_resolution_for_its_capability() -> None:
    class _StubProvider(NullProvider):
        name = "stub_adapter"

    stub = _StubProvider()
    try:
        register_provider("digital_certificate", stub)
        assert get_provider("digital_certificate") is stub
        # Unrelated capabilities are unaffected.
        assert get_provider("simple_electronic") is DEFAULT_PROVIDER
    finally:
        # Don't leak state into other tests in the process.
        from app.modules.signing.providers import _PROVIDER_REGISTRY

        _PROVIDER_REGISTRY.pop("digital_certificate", None)


# ── intl labels ─────────────────────────────────────────────────────────────


def test_capability_labels_localise() -> None:
    assert intl.describe_capability("qualified_electronic", "en") == "Qualified electronic signature"
    assert intl.describe_capability("qualified_electronic", "ru") == "Квалифицированная электронная подпись"
    assert intl.describe_capability("digital_certificate", "de") == "Signatur mit digitalem Zertifikat"


def test_status_labels_localise() -> None:
    assert intl.describe_status("fully_signed", "es") == "Totalmente firmado"
    assert intl.describe_status("declined", "de") == "Abgelehnt"


def test_unknown_locale_falls_back_to_english() -> None:
    assert intl.describe_capability("advanced_electronic", "zz") == "Advanced electronic signature"
    assert intl.describe_capability("advanced_electronic", None) == "Advanced electronic signature"


def test_unknown_code_is_humanised_not_raw() -> None:
    assert intl.describe_capability("mobile_id_signature", "en") == "Mobile Id Signature"
