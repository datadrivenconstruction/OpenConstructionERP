# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Tests for the Data & Security posture builder (#4, pure, py3.11-safe).

The builder backs the in-product trust panel. These tests pin the contract the
frontend renders: AI status is derived from the configured provider names, the
database managed flag tracks whether an external database was configured, the
data always reports as staying on the operator's own infrastructure, and the
payload carries no secret-bearing field.

Placement note: these are pure tests (no database, no I/O, no await), but they
live here under ``tests/integration/core`` rather than ``tests/unit`` on
purpose. The unit suite is fanned across six shards by pytest-split with no
committed durations file, so the partition is decided by collected-test order.
Adding a brand new file to ``tests/unit`` shifts every later test's shard and
can re-expose pre-existing order-dependent flakes in the shared-event-loop PG
fixtures. Keeping these here runs them in the single, non-sharded
``pytest tests/integration tests/modules`` job without perturbing that
partition. Do not move them back into ``tests/unit`` without first giving the
unit suite a stable, duration-based split.
"""

from __future__ import annotations

from app.core.deployment_posture import build_data_security_posture


def _posture(**overrides):
    base = dict(
        self_hosted=True,
        deployment_mode="server",
        demo_instance=False,
        version="8.10.1",
        environment="production",
        database_engine="postgresql",
        database_external=False,
        storage_backend="local",
        ai_providers=[],
        registration_mode="admin-approve",
        analytics_bundled=False,
        license_name="AGPL-3.0",
        repository="https://github.com/datadrivenconstruction/OpenConstructionERP",
    )
    base.update(overrides)
    return build_data_security_posture(**base)


def test_offline_posture_reports_no_external_ai() -> None:
    posture = _posture(ai_providers=[])
    assert posture["ai"]["enabled"] is False
    assert posture["ai"]["external_calls"] is False
    assert posture["ai"]["offline_capable"] is True
    assert posture["ai"]["providers"] == []


def test_configured_ai_reports_external_calls_by_name() -> None:
    posture = _posture(ai_providers=["Anthropic", "OpenAI"])
    assert posture["ai"]["enabled"] is True
    assert posture["ai"]["external_calls"] is True
    # Names pass through verbatim, in order, with nothing added or transformed.
    assert posture["ai"]["providers"] == ["Anthropic", "OpenAI"]


def test_external_database_is_flagged_but_still_yours() -> None:
    external = _posture(database_external=True)
    assert external["database"]["managed"] == "external"
    assert external["database"]["on_your_infrastructure"] is True

    embedded = _posture(database_external=False)
    assert embedded["database"]["managed"] == "embedded"
    assert embedded["database"]["on_your_infrastructure"] is True


def test_storage_always_reports_on_your_infrastructure() -> None:
    assert _posture(storage_backend="local")["storage"]["on_your_infrastructure"] is True
    s3 = _posture(storage_backend="s3")["storage"]
    assert s3["backend"] == "s3"
    assert s3["on_your_infrastructure"] is True


def test_payload_carries_every_section() -> None:
    posture = _posture()
    for key in (
        "self_hosted",
        "deployment_mode",
        "demo_instance",
        "version",
        "environment",
        "database",
        "storage",
        "ai",
        "registration_mode",
        "analytics_bundled",
        "source",
    ):
        assert key in posture
    assert posture["source"]["license"] == "AGPL-3.0"
    assert posture["source"]["repository"].startswith("https://github.com/")


def test_payload_has_no_secret_bearing_field() -> None:
    """The trust panel must never carry a key/secret/password/token field."""
    posture = _posture(ai_providers=["Anthropic"])

    banned = ("key", "secret", "password", "token", "credential")

    def _walk(node: object) -> None:
        if isinstance(node, dict):
            for name, value in node.items():
                lowered = name.lower()
                assert not any(word in lowered for word in banned), f"secret-like field: {name}"
                _walk(value)
        elif isinstance(node, list):
            for item in node:
                _walk(item)

    _walk(posture)


def test_returned_provider_list_is_a_copy() -> None:
    """Mutating the caller's list after the call must not change the payload."""
    providers = ["Anthropic"]
    posture = build_data_security_posture(
        self_hosted=True,
        deployment_mode="server",
        demo_instance=False,
        version="1.0.0",
        environment="production",
        database_engine="postgresql",
        database_external=False,
        storage_backend="local",
        ai_providers=providers,
        registration_mode="closed",
        analytics_bundled=False,
        license_name="AGPL-3.0",
        repository="https://github.com/datadrivenconstruction/OpenConstructionERP",
    )
    providers.append("OpenAI")
    assert posture["ai"]["providers"] == ["Anthropic"]
