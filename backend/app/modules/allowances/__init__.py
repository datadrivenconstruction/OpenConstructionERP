# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Allowances & contingency register module.

Carries the money an estimate holds but has not yet measured - provisional sums,
prime-cost sums and design / construction contingencies - and tracks the drawdown
against each as scope firms up, so the remaining allowances roll into the estimate
total honestly (per currency, never blended).

The decision logic lives in the dependency-free :mod:`allowance_math` engine that
unit-tests on the local runner; the service and router are a thin database / HTTP
layer on top. The module loader discovers and mounts the ``router`` submodule at
``/api/v1/allowances`` and calls :func:`on_startup` once at boot. This package
``__init__`` deliberately does not import the router at top level so the pure
engine stays importable without the database / framework stack.
"""

__all__ = ["on_startup"]


async def on_startup() -> None:
    """Module startup hook - register the module's permissions."""
    from app.modules.allowances.permissions import register_allowances_permissions

    register_allowances_permissions()
    from app.modules.allowances.validators import register_allowances_validation_rules

    register_allowances_validation_rules()
