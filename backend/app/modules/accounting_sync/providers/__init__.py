# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Live​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ accounting API adapters, keyed by connection provider."""

from app.modules.accounting_sync.providers.base import ProviderAdapter
from app.modules.accounting_sync.providers.qbo import QBOAdapter
from app.modules.accounting_sync.providers.xero import XeroAdapter

#: Live adapters keyed by connection provider. Packs add theirs through :func:`register_provider`;
#: the dict object is shared, so importers see registrations.
API_PROVIDERS: dict[str, type[ProviderAdapter]] = {}
#: Providers without a live API: the connection produces files (formats stay in core).
FILE_PROVIDERS: tuple[str, ...] = ("datev", "journal", "saft")


def register_provider(key: str, adapter: type[ProviderAdapter], *, replace: bool = False) -> None:
    """Register a live API adapter under a provider key (packs call this at startup)."""
    if key in FILE_PROVIDERS:
        raise ValueError(f"{key} is a file format provider and cannot be replaced")
    if key in API_PROVIDERS and not replace:
        raise ValueError(f"Provider {key} is already registered")
    API_PROVIDERS[key] = adapter


def unregister_provider(key: str) -> None:
    """Remove an adapter (tests and pack unloading)."""
    API_PROVIDERS.pop(key, None)


def all_providers() -> tuple[str, ...]:
    """Every provider key currently usable on a connection."""
    return (*API_PROVIDERS, *FILE_PROVIDERS)


register_provider("xero", XeroAdapter)
register_provider("qbo", QBOAdapter)

__all__ = [
    "API_PROVIDERS",
    "FILE_PROVIDERS",
    "ProviderAdapter",
    "all_providers",
    "register_provider",
    "unregister_provider",
]
