# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Pure builder for the in-product Data & Security posture (#4).

No I/O and no settings access: the caller resolves every fact (deployment mode,
whether an external database is configured, which AI providers are present) and
hands them in as primitives. That keeps this unit-testable on its own and means
it can never accidentally read or echo a secret - it only ever receives provider
*names*, never keys. The HTTP endpoint in :mod:`app.main` is a thin wrapper that
resolves those inputs and calls :func:`build_data_security_posture`.
"""

from __future__ import annotations

from typing import Any


def build_data_security_posture(
    *,
    self_hosted: bool,
    deployment_mode: str,
    demo_instance: bool,
    version: str,
    environment: str,
    database_engine: str,
    database_external: bool,
    storage_backend: str,
    ai_providers: list[str],
    registration_mode: str,
    analytics_bundled: bool,
    license_name: str,
    repository: str,
) -> dict[str, Any]:
    """Assemble the read-only deployment-posture payload.

    ``ai_providers`` is a list of provider *names* (never keys); AI ``enabled``
    and ``external_calls`` are both derived from whether that list is non-empty,
    so a deployment with no provider configured truthfully reports that it makes
    no external AI calls. ``managed`` is ``"external"`` when the operator pointed
    the app at their own database, otherwise ``"embedded"`` (the bundled engine);
    either way the data stays on the operator's own infrastructure.
    """
    providers = list(ai_providers)
    return {
        "self_hosted": self_hosted,
        "deployment_mode": deployment_mode,
        "demo_instance": demo_instance,
        "version": version,
        "environment": environment,
        "database": {
            "engine": database_engine,
            "managed": "external" if database_external else "embedded",
            "on_your_infrastructure": True,
        },
        "storage": {
            "backend": storage_backend,
            "on_your_infrastructure": True,
        },
        "ai": {
            "enabled": bool(providers),
            "providers": providers,
            "offline_capable": True,
            "external_calls": bool(providers),
        },
        "registration_mode": registration_mode,
        "analytics_bundled": analytics_bundled,
        "source": {
            "license": license_name,
            "repository": repository,
        },
    }
