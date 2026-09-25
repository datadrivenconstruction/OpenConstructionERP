// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import type { QueryClient, QueryKey } from '@tanstack/react-query';

/**
 * Whether a cached query holds a figure that money moving can change.
 *
 * The summary cards, the budget rows, the invoice register, the payments list
 * and the statements all read the same records under different keys
 * (`['finance', 'dashboard', id]`, `['finance-invoices', id, tab]`,
 * `['finance-stmt-cashflow', ...]`), and a purchase order's invoiced figure
 * lives under `['procurement-po', id]`. Matching on the head of the key keeps
 * a new tab from being forgotten the day it is added.
 */
export function isFinanceFigureKey(queryKey: QueryKey): boolean {
  const head = queryKey[0];
  if (typeof head !== 'string') return false;
  return head === 'finance' || head.startsWith('finance-') || head === 'procurement-po';
}

/**
 * Refresh every finance figure after an invoice, payment, order or goods
 * receipt changes, so the KPIs move without a reload.
 */
export function invalidateFinanceFigures(queryClient: Pick<QueryClient, 'invalidateQueries'>): Promise<void> {
  return queryClient.invalidateQueries({ predicate: (query) => isFinanceFigureKey(query.queryKey) });
}
