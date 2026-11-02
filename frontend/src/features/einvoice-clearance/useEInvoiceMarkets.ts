// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The tenant's e-invoicing markets: the visibility gate for the invoice card
 * and the Finance "E-invoices" tab. Today it reads the active registrations;
 * once market scoping lands this hook narrows to the tenant's markets and the
 * call sites stay unchanged.
 */
import { useQuery } from '@tanstack/react-query';
import { getEInvoiceSetup, type EInvoiceSetupRow } from './lifecycleApi';
import { einvoiceVisible } from './lifecycleView';

export const EINVOICE_SETUP_QUERY_KEY = ['einvoice-clearance', 'setup'] as const;

export function useEInvoiceMarkets(): {
  rows: EInvoiceSetupRow[];
  enabled: boolean;
  isVisibleFor: (country?: string | null) => boolean;
  isLoading: boolean;
} {
  const { data, isLoading } = useQuery({
    queryKey: EINVOICE_SETUP_QUERY_KEY,
    queryFn: getEInvoiceSetup,
    staleTime: 5 * 60 * 1000,
    // A missing module or permission reads as "no markets": nothing shows.
    retry: false,
  });
  const rows = data ?? [];
  return {
    rows,
    enabled: einvoiceVisible(rows),
    isVisibleFor: (country) => einvoiceVisible(rows, country),
    isLoading,
  };
}
