// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Finance's tab ids, as ?tab= carries them (/finance?tab=retention). Kept
 * apart from FinancePage so a menu row or a guide test can check a link
 * names a real tab without loading the page.
 */

export type FinanceTab = 'budgets' | 'invoices' | 'inbox' | 'payments' | 'payment_runs' | 'statements' | 'ageing' | 'payee_totals' | 'retention' | 'evm' | 'connectors';

export const FINANCE_TABS: readonly FinanceTab[] = ['budgets', 'invoices', 'inbox', 'payments', 'payment_runs', 'statements', 'ageing', 'payee_totals', 'retention', 'evm', 'connectors'];

/** The tab shown for a missing or unknown ?tab= value. */
export const DEFAULT_FINANCE_TAB: FinanceTab = 'budgets';

export function isFinanceTab(value: string | null): value is FinanceTab {
  return value !== null && (FINANCE_TABS as readonly string[]).includes(value);
}
