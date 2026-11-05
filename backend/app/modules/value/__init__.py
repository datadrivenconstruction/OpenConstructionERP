# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Value Realized module.

A thin composition layer over the change-and-AI value question. It owns no
records: it reads figures the rest of the platform already computes - the cost
and schedule approved changes have committed, the cost-recovery ledger, the
admin hours assisted actions gave back - and composes them into a single project
and portfolio "value realized" summary, plus an adoption-vs-non-adoption
benchmark on the firm's own projects.

The decision logic lives in dependency-free engines (``value_math``,
``time_saved``, ``adoption_benchmark``) that unit-test on the local runner; the
service and router are a thin database / HTTP layer on top.

The module loader discovers and mounts the ``router`` submodule at
``/api/v1/value`` and calls :func:`on_startup` once at boot. This package
``__init__`` deliberately does not import the router at top level so the pure
engines remain importable without the database / framework stack.
"""

__all__ = ["on_startup"]


async def on_startup() -> None:
    """Module startup hook - register the module's permissions."""
    from app.modules.value.permissions import register_value_permissions

    register_value_permissions()
    from app.modules.value.validators import register_value_validation_rules

    register_value_validation_rules()
