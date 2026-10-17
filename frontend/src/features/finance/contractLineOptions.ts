// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The contract lines a supplier invoice line can bill: the priced lines of
 * the project's signed subcontracts, grouped by contract. An invoice line that
 * names one takes that line's cost line on the server, so the bill lands where
 * the contract was costed.
 */
import { useQuery } from '@tanstack/react-query';

import type { SearchableSelectOption } from '@/shared/ui/SearchableSelect';
import { listContractLines, listContracts, type ContractLine } from '@/features/contracts/api';

/** Contracts whose lines can be billed: signed and not ended in termination. */
export const BILLABLE_CONTRACT_STATUSES = ['active', 'suspended', 'completed'];
/** Contracts read per project; enough for the invoice form of any real project. */
const MAX_CONTRACTS = 200;

/** The lines no other line names as its parent: the ones money is billed on. */
export function leafLines(lines: ContractLine[]): ContractLine[] {
  const parents = new Set(lines.map((l) => l.parent_line_id).filter((id): id is string => !!id));
  return lines.filter((l) => !parents.has(l.id));
}

export async function contractLineOptions(projectId: string): Promise<SearchableSelectOption[]> {
  const page = await listContracts({ project_id: projectId, counterparty_type: 'subcontractor', limit: MAX_CONTRACTS });
  const bound = page.items.filter((c) => BILLABLE_CONTRACT_STATUSES.includes(c.status));
  const perContract = await Promise.all(
    bound.map(async (c) => {
      const lines = leafLines(await listContractLines(c.id));
      const group = `${c.code} ${c.title}`.trim();
      return lines.map((l) => ({
        value: l.id,
        label: `${l.code} ${l.description}`.trim() || l.id,
        group,
        keywords: `${c.code} ${c.title} ${l.code} ${l.description}`,
      }));
    }),
  );
  return perContract.flat();
}

export function useContractLineOptions(projectId: string | null | undefined, enabled: boolean) {
  return useQuery({
    queryKey: ['finance', 'contract-line-options', projectId],
    queryFn: () => contractLineOptions(projectId!),
    enabled: enabled && !!projectId,
    staleTime: 60_000,
  });
}
