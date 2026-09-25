# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Onboarding module - non-blocking first-run provisioning.

A new user picks a region and a sample project in the wizard. Importing a
regional cost base and installing a sample project each take tens of seconds,
which is too long to make someone stare at a spinner. This module exposes a
tiny API (`/api/v1/onboarding/provision`, plus `/jobs/` and `/status` to read
the caller's jobs) that turns those loads
into background jobs, so the wizard can hand them off and let the user carry on
while a progress banner tracks the work to completion.

The heavy lifting reuses the platform job runner (`app.core.job_runner`), which
degrades to an in-process asyncio task when no Redis/Celery worker is present,
so this works on the lightweight single-process deploy too.
"""


async def on_startup() -> None:
    """Module startup hook - register the background job handlers.

    The module loader auto-calls this when the package is discovered.
    """
    from app.modules.onboarding.handlers import register_onboarding_job_handlers

    register_onboarding_job_handlers()
