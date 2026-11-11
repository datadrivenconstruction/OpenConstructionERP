// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Net cost, tax folded into cost, recoverable tax and gross outlay of one
// assembly (issue #559), with the explicit recalculation and the approval that
// freezes prices. Shown only when the project uses component tax.

import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Lock, RefreshCw, Unlock } from 'lucide-react';
import { Button, Card } from '@/shared/ui';
import { useToastStore } from '@/stores/useToastStore';
import { getErrorMessage } from '@/shared/lib/api';
import { assembliesApi, type AssemblyWithComponents } from './api';
import { assemblyTaxTotals, isAssemblyApproved } from './componentTax';

const SEVERITY_CLASS: Record<string, string> = {
  error: 'text-semantic-error',
  warning: 'text-semantic-warning',
  info: 'text-content-tertiary',
};

export function AssemblyTaxPanel({
  assembly,
  canEdit,
  fmt,
}: {
  assembly: AssemblyWithComponents;
  canEdit: boolean;
  fmt: (n: number) => string;
}) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const totals = assemblyTaxTotals(assembly);
  const approved = isAssemblyApproved(assembly);

  const findings = useQuery({
    queryKey: ['assembly-tax-findings', assembly.id, assembly.updated_at],
    queryFn: () => assembliesApi.taxFindings(assembly.id),
  });

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ['assembly', assembly.id] });
    queryClient.invalidateQueries({ queryKey: ['assembly-tax-findings', assembly.id] });
  };

  const recalc = useMutation({
    mutationFn: () => assembliesApi.recalculateTax(assembly.id),
    onSuccess: () => {
      refresh();
      addToast({ type: 'success', title: t('assemblies.tax.recalculated', { defaultValue: 'Tax recalculated' }) });
    },
    onError: (err) =>
      addToast({
        type: 'error',
        title: t('assemblies.tax.recalc_failed', { defaultValue: 'Recalculation failed' }),
        message: getErrorMessage(err),
      }),
  });

  const approve = useMutation({
    mutationFn: (next: boolean) =>
      assembliesApi.update(assembly.id, { metadata: { status: next ? 'approved' : 'draft', approved: next } }),
    onSuccess: refresh,
    onError: (err) =>
      addToast({ type: 'error', title: t('toasts.error', { defaultValue: 'Error' }), message: getErrorMessage(err) }),
  });

  const rows: Array<[string, string, string | undefined]> = totals
    ? [
        ['net', t('assemblies.tax.net', { defaultValue: 'Net cost' }), totals.net],
        ['tax_in_cost', t('assemblies.tax.tax_in_cost', { defaultValue: 'Tax included in cost' }), totals.tax_in_cost],
        ['cost', t('assemblies.tax.cost', { defaultValue: 'Cost (used in the bill)' }), totals.cost],
        ['tax_recoverable', t('assemblies.tax.tax_recoverable', { defaultValue: 'Recoverable tax' }), totals.tax_recoverable],
        ['gross_outlay', t('assemblies.tax.gross_outlay', { defaultValue: 'Gross cash outlay' }), totals.gross_outlay],
      ]
    : [];

  return (
    <Card padding="md" data-testid="assembly-tax-panel">
      <div className="flex items-start justify-between gap-2">
        <h3 className="text-sm font-semibold text-content-primary">
          {t('assemblies.tax.panel_title', { defaultValue: 'Cost and input tax' })}
        </h3>
        {approved && (
          <span className="inline-flex items-center gap-1 text-2xs text-content-tertiary">
            <Lock size={11} />
            {t('assemblies.tax.approved', { defaultValue: 'Approved, prices frozen' })}
          </span>
        )}
      </div>

      {totals ? (
        <dl className="mt-3 space-y-1.5 text-sm">
          {rows.map(([key, label, value]) => (
            <div key={key} className="flex justify-between gap-3" data-testid={`tax-total-${key}`}>
              <dt className="text-content-secondary">{label}</dt>
              <dd className="tabular-nums text-content-primary">{fmt(Number(value ?? 0))}</dd>
            </div>
          ))}
        </dl>
      ) : (
        <p className="mt-3 text-xs text-content-tertiary">
          {t('assemblies.tax.no_totals', {
            defaultValue: 'Set a tax status on a component to see the split.',
          })}
        </p>
      )}

      <div className="mt-3 flex flex-wrap gap-2">
        <Button
          variant="secondary"
          size="sm"
          icon={<RefreshCw size={13} />}
          loading={recalc.isPending}
          disabled={!canEdit || approved}
          title={t('assemblies.tax.recalc_hint', {
            defaultValue:
              'Take the current master prices and apply the tax rules once. Approved assemblies are never changed.',
          })}
          onClick={() => recalc.mutate()}
        >
          {t('assemblies.tax.recalc', { defaultValue: 'Recalculate tax' })}
        </Button>
        <Button
          variant="ghost"
          size="sm"
          icon={approved ? <Unlock size={13} /> : <Lock size={13} />}
          disabled={!canEdit}
          loading={approve.isPending}
          onClick={() => approve.mutate(!approved)}
        >
          {approved
            ? t('assemblies.tax.reopen', { defaultValue: 'Reopen' })
            : t('assemblies.tax.approve', { defaultValue: 'Approve and freeze prices' })}
        </Button>
      </div>

      {(findings.data ?? []).length > 0 && (
        <ul className="mt-3 space-y-1.5 text-xs" data-testid="tax-findings">
          {(findings.data ?? []).map((f, i) => (
            <li key={`${f.rule_id}-${f.component_id}-${i}`} className={SEVERITY_CLASS[f.severity] ?? ''}>
              {f.message}
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
