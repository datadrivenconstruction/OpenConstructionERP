import { useId } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery } from '@tanstack/react-query';
import { listContracts, type ContractItem } from '@/features/contracts/api';
import { useHasPermission } from '@/shared/lib/permissionGates';
import { useToastStore } from '@/stores/useToastStore';
import { updatePunchItem, type PunchItem } from './api';

async function contractOptions(projectId: string): Promise<ContractItem[]> {
  const result: ContractItem[] = [];
  for (let offset = 0; ; ) {
    const page = await listContracts({ project_id: projectId, offset, limit: 100 });
    result.push(...page.items);
    offset += page.items.length;
    if (!page.items.length || offset >= page.total) return result;
  }
}

export function PunchContractField({ projectId, value, onChange, disabled = false }: {
  projectId: string; value: string | null; onChange: (value: string | null) => void; disabled?: boolean;
}) {
  const { t } = useTranslation();
  const id = useId();
  const { data: contracts = [], isLoading, isError } = useQuery({
    queryKey: ['punch-contract-options', projectId],
    queryFn: () => contractOptions(projectId),
    enabled: Boolean(projectId),
  });
  return <div className="space-y-1.5">
    <label htmlFor={id} className="text-sm font-medium text-content-secondary">{t('contracts.contract')}</label>
    <select id={id} value={value ?? ''} disabled={disabled || isLoading || isError}
      className="w-full rounded-lg border border-border bg-surface-primary px-3 py-2 text-sm"
      onChange={event => onChange(event.target.value || null)}>
      <option value="">{t('common.not_set')}</option>
      {value && !contracts.some(contract => contract.id === value) && <option value={value}>{value}</option>}
      {contracts.map(contract => <option key={contract.id} value={contract.id}>
        {contract.code} — {contract.title}
      </option>)}
    </select>
    {isError && <p role="alert" className="text-sm text-semantic-error">{t('common.error')}</p>}
  </div>;
}

export function PunchContractAssignment({ item, onSaved }: { item: PunchItem; onSaved: () => unknown }) {
  const { t } = useTranslation();
  const canEdit = useHasPermission('punchlist.update');
  const toast = useToastStore(s => s.addToast);
  const mutation = useMutation({
    mutationFn: (contractId: string | null) => updatePunchItem(item.id, { contract_id: contractId }),
    onSuccess: async () => { await onSaved(); },
    onError: (error: Error) => toast({ type: 'error', title: t('common.error'), message: error.message }),
  });
  return <PunchContractField projectId={item.project_id} value={item.contract_id ?? null}
    disabled={!canEdit || mutation.isPending} onChange={value => mutation.mutate(value)} />;
}
