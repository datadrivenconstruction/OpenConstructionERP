// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The contracts register's tab ids, as ?tab= carries them
 * (/contracts?tab=claims). Kept apart from ContractsPage so a menu row or a
 * guide test can check a link names a real tab without loading the page.
 */

export type ContractsTab = 'contracts' | 'claims' | 'final_accounts' | 'templates';

export const CONTRACTS_TABS: readonly ContractsTab[] = ['contracts', 'claims', 'final_accounts', 'templates'];

/** The tab shown for a missing or unknown ?tab= value. */
export const DEFAULT_CONTRACTS_TAB: ContractsTab = 'contracts';

export function isContractsTab(value: string | null): value is ContractsTab {
  return value !== null && (CONTRACTS_TABS as readonly string[]).includes(value);
}

/** The register opened on one tab, inside the project when there is one. */
export function contractsTabHref(tab: ContractsTab, projectId?: string | null): string {
  return `${projectId ? `/projects/${projectId}/contracts` : '/contracts'}?tab=${tab}`;
}
