// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Links a subcontract work package to the GC schedule-of-values line its
 * billing rolls up to.
 *
 * The link is a default: each line of a sub's pay application lands on this
 * SOV line unless that pay-application line carries its own override (set on
 * the claim page). Only lines of the project's client contracts are offered,
 * the one the agreement names when it names one, and never a grouping line
 * (a line other lines hang under), because a grouping line is not billed
 * directly and the rollup would report the amount as unmapped.
 */

import { useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { useToastStore } from '@/stores/useToastStore';
import { getErrorMessage } from '@/shared/lib/api';
import {
  listContractLines,
  listContracts,
  type ContractItem,
  type ContractLine,
} from '@/features/contracts/api';

import { updateWorkPackage, type Agreement, type WorkPackage } from './api';

interface WorkPackageSovPickerProps {
  agreement: Agreement;
  workPackage: WorkPackage;
}

/** Billable lines: every line that no other line on the contract hangs under. */
export function billableLines(lines: ContractLine[]): ContractLine[] {
  const parents = new Set(lines.map((ln) => ln.parent_line_id).filter(Boolean));
  return lines.filter((ln) => !parents.has(ln.id));
}

export function WorkPackageSovPicker({ agreement, workPackage }: WorkPackageSovPickerProps) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);

  const contractsQ = useQuery({
    queryKey: ['subcontractors', 'prime-contracts', agreement.project_id],
    queryFn: () => listContracts({ project_id: agreement.project_id, counterparty_type: 'client' }),
  });

  const contracts: ContractItem[] = useMemo(() => {
    const all = contractsQ.data?.items ?? [];
    return agreement.prime_contract_id
      ? all.filter((c) => c.id === agreement.prime_contract_id)
      : all;
  }, [contractsQ.data, agreement.prime_contract_id]);

  const linesQ = useQuery({
    queryKey: ['subcontractors', 'prime-contract-line-groups', contracts.map((c) => c.id).join(',')],
    queryFn: async () => {
      const perContract = await Promise.all(contracts.map((c) => listContractLines(c.id)));
      return contracts.map((contract, i) => ({ contract, lines: billableLines(perContract[i] ?? []) }));
    },
    enabled: contracts.length > 0,
  });

  const mutation = useMutation({
    mutationFn: (lineId: string | null) =>
      updateWorkPackage(workPackage.id, { contract_line_id: lineId }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['subcontractors', 'workPackages', agreement.id] });
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  const groups = linesQ.data ?? [];
  const current = workPackage.contract_line_id ?? '';
  const known = groups.some((g) => g.lines.some((ln) => ln.id === current));

  if (!contractsQ.isLoading && contracts.length === 0) {
    return (
      <span className="text-2xs text-content-tertiary" data-testid="wp-sov-no-contract">
        {t('subcontractors.sov_link_no_prime_contract', {
          defaultValue: 'No client contract to bill against',
        })}
      </span>
    );
  }

  return (
    <select
      value={current}
      onChange={(e) => mutation.mutate(e.target.value || null)}
      disabled={mutation.isPending || linesQ.isLoading || contractsQ.isLoading}
      className="h-7 max-w-[220px] truncate rounded-md border border-border-light bg-surface-primary px-1.5 text-xs"
      aria-label={t('subcontractors.sov_link_label', {
        name: workPackage.name,
        defaultValue: 'Schedule-of-values line for {{name}}',
      })}
      data-testid="wp-sov-picker"
    >
      <option value="">
        {t('subcontractors.sov_link_none', { defaultValue: 'Not linked to an SOV line' })}
      </option>
      {current && !known && !linesQ.isLoading && (
        <option value={current}>
          {t('subcontractors.sov_link_unavailable', {
            defaultValue: 'Linked line is not billable here',
          })}
        </option>
      )}
      {groups.map(({ contract, lines }) => (
        <optgroup key={contract.id} label={`${contract.code} · ${contract.title}`}>
          {lines.map((ln) => (
            <option key={ln.id} value={ln.id}>
              {ln.code ? `${ln.code} · ${ln.description}` : ln.description}
            </option>
          ))}
        </optgroup>
      ))}
    </select>
  );
}
