// DDC-CWICR-OE: DataDrivenConstruction​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Mapping tab: which ledger account each kind of posting lands on, and which
 * tax code of the books each project tax code becomes. Rows still without an
 * account code are marked, because a document that needs one cannot be posted.
 */
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { AlertTriangle } from 'lucide-react';
import { Button, Card, ConfirmDialog } from '@/shared/ui';
import { useConfirm } from '@/shared/hooks/useConfirm';
import { useToastStore } from '@/stores/useToastStore';
import { getErrorMessage } from '@/shared/lib/api';
import {
  applyTemplate,
  saveMappings,
  unmappedAccounts,
  unmappedTaxes,
  useMappings,
  useSyncMutation,
  type AccountMapping,
  type TaxMapping,
} from './api';
import { categoryLabel, directionLabel } from './labels';
import { compactInputCls, inputCls, warnInputCls } from './ui';

export function MappingTab({ connectionId, canEdit }: { connectionId: string; canEdit: boolean }) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const { confirm, ...confirmProps } = useConfirm();
  const q = useMappings(connectionId);
  const [accounts, setAccounts] = useState<AccountMapping[]>([]);
  const [taxes, setTaxes] = useState<TaxMapping[]>([]);
  const [template, setTemplate] = useState('');

  useEffect(() => {
    if (q.data) {
      setAccounts(q.data.accounts);
      setTaxes(q.data.taxes);
      setTemplate(q.data.chart_template ?? '');
    }
  }, [q.data]);

  const onError = (err: unknown) =>
    addToast({ type: 'error', title: t('accountingSync.error', { defaultValue: 'Error' }), message: getErrorMessage(err) });

  const saveMut = useSyncMutation(() => saveMappings(connectionId, { accounts, taxes }));
  const applyMut = useSyncMutation((key: string) => applyTemplate(connectionId, key));

  const missingAccounts = unmappedAccounts(accounts);
  const missingTaxes = unmappedTaxes(taxes);
  const templates = q.data?.templates ?? [];

  const handleApply = async () => {
    if (!template) return;
    const ok = await confirm({
      title: t('accountingSync.mapping.apply_title', { defaultValue: 'Apply this template?' }),
      message: t('accountingSync.mapping.apply_msg', {
        defaultValue: 'The account codes below are replaced by the template. Unsaved edits are lost.',
      }),
      confirmLabel: t('accountingSync.mapping.apply', { defaultValue: 'Apply template' }),
      variant: 'warning',
    });
    if (ok) {
      applyMut.mutate(template, {
        onSuccess: () => addToast({ type: 'success', title: t('accountingSync.mapping.applied', { defaultValue: 'Template applied' }) }),
        onError,
      });
    }
  };

  if (q.isLoading) {
    return <Card padding="lg" className="text-center text-sm text-content-tertiary">{t('accountingSync.loading', { defaultValue: 'Loading...' })}</Card>;
  }

  return (
    <div className="space-y-4" data-testid="accounting-sync-mapping">
      <Card padding="md">
        <div className="flex flex-wrap items-end gap-3">
          <label className="min-w-[14rem] flex-1 text-sm">
            <span className="mb-1 block text-xs font-medium text-content-secondary">
              {t('accountingSync.mapping.template', { defaultValue: 'Start from a chart of accounts' })}
            </span>
            <select className={inputCls} value={template} onChange={(e) => setTemplate(e.target.value)} disabled={!canEdit}>
              <option value="">{t('accountingSync.field.template_none', { defaultValue: 'None yet' })}</option>
              {templates.map((tpl) => (
                <option key={tpl.key} value={tpl.key}>{tpl.label}</option>
              ))}
            </select>
          </label>
          <Button variant="secondary" onClick={handleApply} disabled={!canEdit || !template} loading={applyMut.isPending}>
            {t('accountingSync.mapping.apply', { defaultValue: 'Apply template' })}
          </Button>
        </div>
      </Card>

      {(missingAccounts.length > 0 || missingTaxes.length > 0) && (
        <div
          data-testid="accounting-sync-mapping-warning"
          className="flex items-start gap-2 rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800 dark:border-amber-900 dark:bg-amber-950/30 dark:text-amber-300"
        >
          <AlertTriangle size={16} className="mt-0.5 shrink-0" />
          <span>
            {t('accountingSync.mapping.incomplete', {
              defaultValue: 'Some rows have no code yet ({{accounts}} accounts, {{taxes}} tax codes). Documents that need them cannot be posted.',
              accounts: missingAccounts.length,
              taxes: missingTaxes.length,
            })}
          </span>
        </div>
      )}

      <Card padding="md">
        <h3 className="mb-3 text-sm font-semibold text-content-primary">{t('accountingSync.mapping.accounts', { defaultValue: 'Accounts' })}</h3>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[32rem] text-sm">
            <thead>
              <tr className="text-left text-2xs uppercase tracking-wide text-content-tertiary">
                <th className="pb-2 pr-3 font-medium">{t('accountingSync.mapping.category', { defaultValue: 'Posting' })}</th>
                <th className="pb-2 pr-3 font-medium">{t('accountingSync.mapping.account_code', { defaultValue: 'Account code' })}</th>
                <th className="pb-2 font-medium">{t('accountingSync.mapping.account_name', { defaultValue: 'Account name' })}</th>
              </tr>
            </thead>
            <tbody>
              {accounts.map((a, i) => (
                <tr key={a.category} className="border-t border-border-light" data-testid={`account-row-${a.category}`}>
                  <td className="py-1.5 pr-3 text-content-primary">{categoryLabel(t, a.category)}</td>
                  <td className="py-1.5 pr-3">
                    <input
                      className={a.account_code.trim() === '' ? warnInputCls : compactInputCls}
                      value={a.account_code}
                      disabled={!canEdit}
                      aria-invalid={a.account_code.trim() === ''}
                      aria-label={t('accountingSync.mapping.account_code_for', { defaultValue: 'Account code for {{category}}', category: categoryLabel(t, a.category) })}
                      onChange={(e) => setAccounts((rows) => rows.map((r, j) => (j === i ? { ...r, account_code: e.target.value } : r)))}
                    />
                  </td>
                  <td className="py-1.5">
                    <input
                      className={compactInputCls}
                      value={a.account_name}
                      disabled={!canEdit}
                      onChange={(e) => setAccounts((rows) => rows.map((r, j) => (j === i ? { ...r, account_name: e.target.value } : r)))}
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      <Card padding="md">
        <h3 className="mb-3 text-sm font-semibold text-content-primary">{t('accountingSync.mapping.taxes', { defaultValue: 'Tax codes' })}</h3>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[32rem] text-sm">
            <thead>
              <tr className="text-left text-2xs uppercase tracking-wide text-content-tertiary">
                <th className="pb-2 pr-3 font-medium">{t('accountingSync.mapping.tax_code', { defaultValue: 'Tax code' })}</th>
                <th className="pb-2 pr-3 font-medium">{t('accountingSync.mapping.direction', { defaultValue: 'Direction' })}</th>
                <th className="pb-2 pr-3 text-right font-medium">{t('accountingSync.mapping.rate', { defaultValue: 'Rate' })}</th>
                <th className="pb-2 font-medium">{t('accountingSync.mapping.external_code', { defaultValue: 'Code in your books' })}</th>
              </tr>
            </thead>
            <tbody>
              {taxes.map((x, i) => (
                <tr key={`${x.tax_code}-${x.direction}`} className="border-t border-border-light" data-testid={`tax-row-${x.tax_code}-${x.direction}`}>
                  <td className="py-1.5 pr-3 font-medium text-content-primary">{x.tax_code}</td>
                  <td className="py-1.5 pr-3 text-content-secondary">{directionLabel(t, x.direction)}</td>
                  <td className="py-1.5 pr-3 text-right tabular-nums text-content-secondary">{x.rate_pct === null ? '—' : `${x.rate_pct}%`}</td>
                  <td className="py-1.5">
                    <input
                      className={x.external_code.trim() === '' ? warnInputCls : compactInputCls}
                      value={x.external_code}
                      disabled={!canEdit}
                      aria-invalid={x.external_code.trim() === ''}
                      aria-label={t('accountingSync.mapping.external_code_for', { defaultValue: 'Code in your books for {{taxCode}}', taxCode: x.tax_code })}
                      onChange={(e) => setTaxes((rows) => rows.map((r, j) => (j === i ? { ...r, external_code: e.target.value } : r)))}
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      {canEdit && (
        <div className="flex justify-end">
          <Button
            variant="primary"
            loading={saveMut.isPending}
            onClick={() =>
              saveMut.mutate(undefined, {
                onSuccess: () => addToast({ type: 'success', title: t('accountingSync.mapping.saved', { defaultValue: 'Mapping saved' }) }),
                onError,
              })
            }
          >
            {t('accountingSync.mapping.save', { defaultValue: 'Save mapping' })}
          </Button>
        </div>
      )}
      <ConfirmDialog {...confirmProps} />
    </div>
  );
}
