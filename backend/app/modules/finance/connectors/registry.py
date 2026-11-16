# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Process-wide registry of available connector types.

The registry is the single place the router (catalogue endpoint) and the
service (instantiating a connector for a run) look up connector classes by
their ``connector_type`` key. Built-in connectors register at module
startup via :func:`register_builtin_connectors`; third-party packages can
register their own classes the same way.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from app.modules.finance.connectors.base import Connector, ConnectorConfigError

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.core.storage import StorageBackend
    from app.modules.finance.connector_models import AccountingConnectorConfig

logger = logging.getLogger(__name__)


class ConnectorRegistry:
    """Maps ``connector_type`` -> :class:`Connector` subclass."""

    def __init__(self) -> None:
        self._types: dict[str, type[Connector]] = {}

    def register(self, cls: type[Connector]) -> type[Connector]:
        """Register a connector class.

        Re-registering the same ``connector_type`` silently overrides,
        matching the Pythonic "last write wins" convention used by
        :func:`app.core.job_runner.register_handler` so repeated module
        loads (e.g. in tests) stay idempotent.
        """
        if not cls.connector_type:
            raise ValueError(f"{cls.__name__} must define a non-empty connector_type")
        self._types[cls.connector_type] = cls
        logger.debug("Registered connector type: %s -> %s", cls.connector_type, cls.__name__)
        return cls

    def get(self, connector_type: str) -> type[Connector]:
        """Return the class for a type, or raise :class:`ConnectorConfigError`."""
        try:
            return self._types[connector_type]
        except KeyError as exc:
            known = ", ".join(sorted(self._types)) or "(none)"
            raise ConnectorConfigError(f"Unknown connector_type {connector_type!r}. Known types: {known}.") from exc

    def has(self, connector_type: str) -> bool:
        return connector_type in self._types

    def list_types(self, markets: list[str] | None = None) -> list[dict[str, Any]]:
        """Return the catalogue of registered types for the UI.

        With ``markets`` given, a type that declares ``required_markets`` is listed only when
        one of those markets is active for the company.
        """
        from app.core.active_markets import pack_active

        return [
            cls.describe()
            for cls in sorted(self._types.values(), key=lambda c: c.display_name)
            if markets is None or not cls.required_markets or pack_active(markets, cls.required_markets)
        ]

    def create(
        self,
        config: AccountingConnectorConfig,
        *,
        storage: StorageBackend,
        session: AsyncSession,
    ) -> Connector:
        """Instantiate the connector for a config row."""
        cls = self.get(config.connector_type)
        return cls(config, storage=storage, session=session)


# Process-wide singleton.
connector_registry = ConnectorRegistry()


def register_builtin_connectors() -> None:
    """Register the connectors shipped with the platform.

    Idempotent - safe to call on every module startup.
    """
    from app.modules.finance.connectors.file_connector import FileConnector

    connector_registry.register(FileConnector)
    logger.info("Finance: registered %d built-in connector type(s)", len(connector_registry.list_types()))
