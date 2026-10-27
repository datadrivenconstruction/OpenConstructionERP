# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Live​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ accounting API adapters, keyed by connection provider."""

from app.modules.accounting_sync.providers.base import ProviderAdapter
from app.modules.accounting_sync.providers.qbo import QuickBooksAdapter
from app.modules.accounting_sync.providers.xero import XeroAdapter

API_PROVIDERS: dict[str, type[ProviderAdapter]] = {"xero": XeroAdapter, "qbo": QuickBooksAdapter}
#: Providers without a live API: the connection produces files.
FILE_PROVIDERS: tuple[str, ...] = ("datev", "journal", "saft")
ALL_PROVIDERS: tuple[str, ...] = (*API_PROVIDERS, *FILE_PROVIDERS)

__all__ = ["ALL_PROVIDERS", "API_PROVIDERS", "FILE_PROVIDERS", "ProviderAdapter"]
