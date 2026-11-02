// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The tenant's e-invoicing markets: the visibility gate for the invoice card,
 * the setup card and the Finance "E-invoices" tab. The market scope decides
 * (the tenant profile must include a market whose pack ships a mandate); the
 * setup rows then list the registrations within those markets.
 */
import { useQuery } from '@tanstack/react-query';
import { useMarketScope, type MarketScope } from '@/features/market/api';
import { getEInvoiceSetup, type EInvoiceSetupRow } from './lifecycleApi';
import { einvoiceVisible } from './lifecycleView';

export const EINVOICE_SETUP_QUERY_KEY = ['einvoice-clearance', 'setup'] as const;
/** The scope API names modules without the `oe_` prefix. */
export const EINVOICE_MODULE = 'einvoice_clearance';

/** Mandate markets of the module that the tenant's profile covers. */
export function einvoiceScopeMarkets(scope: MarketScope | undefined): string[] {
  if (!scope || scope.hidden_modules?.includes(EINVOICE_MODULE)) return [];
  const mandates = scope.module_markets?.[EINVOICE_MODULE] ?? [];
  if (scope.all_markets) return mandates;
  const tenant = new Set((scope.expanded_markets ?? scope.markets ?? []).map((m) => m.toUpperCase()));
  return mandates.filter((m) => tenant.has(m.toUpperCase()));
}

export function useEInvoiceMarkets(): {
  rows: EInvoiceSetupRow[];
  enabled: boolean;
  markets: string[];
  isVisibleFor: (country?: string | null) => boolean;
  isLoading: boolean;
} {
  const scopeQuery = useMarketScope();
  const scopeMarkets = einvoiceScopeMarkets(scopeQuery.data);
  const inScope = scopeMarkets.length > 0;
  const { data, isLoading } = useQuery({
    queryKey: EINVOICE_SETUP_QUERY_KEY,
    queryFn: getEInvoiceSetup,
    staleTime: 5 * 60 * 1000,
    enabled: inScope,
    // A missing module or permission reads as "no markets": nothing shows.
    retry: false,
  });
  const allowed = new Set(scopeMarkets);
  const rows = inScope ? (data ?? []).filter((r) => allowed.has(r.country.toUpperCase())) : [];
  return {
    rows,
    enabled: einvoiceVisible(rows),
    markets: scopeMarkets,
    isVisibleFor: (country) => einvoiceVisible(rows, country),
    isLoading: scopeQuery.isLoading || (inScope && isLoading),
  };
}
