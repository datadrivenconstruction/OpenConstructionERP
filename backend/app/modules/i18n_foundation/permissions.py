# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Internationalization Foundation permission definitions.

Eight routes in this module write. The ECB exchange-rate fetch reaches out to
the European Central Bank and stores every new daily reference rate it finds;
the other seven create, update and delete exchange rates, work calendars and
tax configurations by hand. Everything else here reads.

The fetch used to be gated on the bare literal ``"admin"``, which no module
ever registers. ``RequirePermission`` returns False for an unknown key and
admin short-circuits above that check, so the route behaved as admin-only and
no test could see the difference, because the fixtures authenticate as an
admin. The cost was invisible in the same way: the admin permission matrix
could never delegate this route, since ``set_min_role`` on an unregistered key
raises.

The other seven had the opposite defect and it lasted longer. They asked for
authentication and never for authorisation - each took a ``CurrentUserId`` it
underscore-prefixed and never read - so any account of any role could rewrite
them. Authentication was never the missing piece.

ADMIN throughout rather than MANAGER, because none of these three tables has a
tenant, owner or project column: every row is global to the install, so the
permission is the whole guard and there is no ownership check underneath it to
fall back on. Changing a VAT rate here changes what every tenant's estimates
and invoices are computed from, which makes it an install-level administrative
act rather than an ordinary write.

The reference data update adds two more, preview and apply, both ADMIN for the
same reason: applying it writes shipped countries, calendars and tax rates into
those same global tables, and the preview is the first half of that write.
"""

from app.core.permissions import Role, permission_registry


def register_i18n_foundation_permissions() -> None:
    """Register permissions for the Internationalization Foundation module."""
    permission_registry.register_module_permissions(
        "i18n_foundation",
        {
            "i18n_foundation.exchange_rates.fetch": Role.ADMIN,
            "i18n_foundation.exchange_rates.create": Role.ADMIN,
            "i18n_foundation.exchange_rates.update": Role.ADMIN,
            "i18n_foundation.exchange_rates.delete": Role.ADMIN,
            "i18n_foundation.work_calendars.create": Role.ADMIN,
            "i18n_foundation.work_calendars.update": Role.ADMIN,
            "i18n_foundation.tax_configs.create": Role.ADMIN,
            "i18n_foundation.tax_configs.update": Role.ADMIN,
            "i18n_foundation.tax_configs.confirm": Role.ADMIN,
            "i18n_foundation.reference_data.preview": Role.ADMIN,
            "i18n_foundation.reference_data.apply": Role.ADMIN,
        },
    )
