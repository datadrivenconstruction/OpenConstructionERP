/**
 * "Subcontract changes" panel for an owner variation order / change order:
 * owner value vs subcontract cost strip, the linked sub changes with their
 * lifecycle actions, and a form that splits the owner change across agreements.
 */
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQueries, useQuery } from '@tanstack/react-query';
import clsx from 'clsx';
import { Plus, Trash2 } from 'lucide-react';
import { Badge, Button } from '@/shared/ui';
import type { BadgeVariant } from '@/shared/ui/Badge';
import { useToastStore } from '@/stores/useToastStore';
import { getErrorMessage } from '@/shared/lib/api';
import { fmtCurrency, fmtPercent } from '@/shared/lib/formatters';
import { listAgreements, type Agreement } from './api';
import {
  useOwnerRollup,
  useSubChangeMutations,
  validateSubChange,
  type OwnerChangeType,
  type SubChangeAction,
  type SubChangeStatus,
  type SubcontractChange,
} from './changesApi';

const STATUS_VARIANT: Record<SubChangeStatus, BadgeVariant> = {
  draft: 'neutral',
  submitted: 'blue',
  approved: 'success',
  rejected: 'error',
  withdrawn: 'warning',
};

const ACTIONS: Record<SubChangeStatus, SubChangeAction[]> = {
  draft: ['submit', 'withdraw'],
  submitted: ['approve', 'reject', 'withdraw'],
  approved: [],
  rejected: [],
  withdrawn: [],
};

interface Row {
  agreementId: string;
  amount: string;
  title: string;
  backToBack: boolean;
  markup: string;
  days: string;
}

export function SubcontractChangesPanel({
  ownerType,
  ownerId,
  projectId,
  ownerTitle,
}: {
  ownerType: OwnerChangeType;
  ownerId: string;
  projectId: string;
  ownerTitle?: string;
}) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const rollupQ = useOwnerRollup(ownerType, ownerId);
  const agreementsQ = useQuery({
    queryKey: ['subcontractors', 'agreements', 'project', projectId],
    queryFn: () => listAgreements({ project_id: projectId }),
    enabled: !!projectId,
  });
  const { act, split } = useSubChangeMutations((e) =>
    addToast({ type: 'error', title: getErrorMessage(e) }),
  );

  const agreements: Agreement[] = agreementsQ.data ?? [];
  const agreementTitle = (id: string) => agreements.find((a) => a.id === id)?.title ?? '—';
  const rollup = rollupQ.data;
  const changes = rollup?.changes ?? [];

  const open = changes.filter((c) => c.status === 'draft' || c.status === 'submitted');
  const validations = useQueries({
    queries: open.map((c) => ({
      queryKey: ['subcontractors', 'changes', 'validate', c.id, c.status, c.amount],
      queryFn: () => validateSubChange(c.id),
    })),
  });
  const failedById = new Map<string, { rule_id: string; message: string }[]>();
  open.forEach((c, i) => {
    const failed = (validations[i]?.data?.results ?? []).filter((r) => !r.passed);
    if (failed.length) failedById.set(c.id, failed);
  });

  /** A back-to-back change cannot be approved before the owner change it mirrors is. */
  const awaitingOwner = (c: SubcontractChange) =>
    c.status === 'submitted' && c.back_to_back && !!c.owner_change_id && rollup?.owner_approved === false;

  const emptyRow = (): Row => ({
    agreementId: '',
    amount: '',
    title: ownerTitle ?? '',
    backToBack: true,
    markup: '0',
    days: '0',
  });
  const [rows, setRows] = useState<Row[]>([emptyRow()]);
  const patchRow = (i: number, p: Partial<Row>) =>
    setRows((rs) => rs.map((r, j) => (j === i ? { ...r, ...p } : r)));
  // A lone back-to-back line may leave the amount empty: the server passes the owner value down less the markup.
  const canSplit = rows.every(
    (r) =>
      r.agreementId &&
      r.title.trim() &&
      (Number(r.amount) > 0 || (rows.length === 1 && r.backToBack && !r.amount.trim())),
  );

  const submitSplit = () => {
    split.mutate(
      {
        type: ownerType,
        id: ownerId,
        lines: rows.map((r) => ({
          agreement_id: r.agreementId,
          amount: r.amount.trim() || undefined,
          title: r.title.trim(),
          back_to_back: r.backToBack,
          markup_pct: Number(r.markup) || 0,
          time_impact_days: Math.trunc(Number(r.days)) || 0,
        })),
      },
      { onSuccess: () => setRows([emptyRow()]) },
    );
  };

  const ccy = rollup?.currency;
  const negative = rollup ? Number(rollup.margin) < 0 : false;
  const leakageNum = rollup?.leakage != null ? Number(rollup.leakage) : null;
  const label = 'text-xs uppercase tracking-wide text-content-tertiary';
  const valueCls = clsx(
    'text-sm font-medium tabular-nums',
    negative ? 'text-semantic-error' : 'text-content-primary',
  );
  const inputCls =
    'h-8 rounded-md border border-border bg-surface-primary px-2 text-sm text-content-primary';

  return (
    <section className="space-y-3" data-testid="sub-changes-panel">
      <h3 className="text-sm font-semibold text-content-primary">
        {t('subcontractors.changes_title', { defaultValue: 'Subcontract changes' })}
      </h3>

      {rollup && (
        <div className="grid grid-cols-2 gap-2 rounded-lg border border-border-light p-3 sm:grid-cols-4">
          <div>
            <div className={label}>
              {t('subcontractors.changes_owner_value', { defaultValue: 'Owner value' })}
            </div>
            <div className="text-sm font-medium tabular-nums" data-testid="sc-owner-value">
              {fmtCurrency(rollup.owner_value, ccy)}
            </div>
          </div>
          <div>
            <div className={label}>
              {t('subcontractors.changes_sub_cost', { defaultValue: 'Subcontract cost' })}
            </div>
            <div className="text-sm font-medium tabular-nums" data-testid="sc-sub-cost">
              {fmtCurrency(rollup.sub_cost_total, ccy)}
            </div>
            <div className="text-xs text-content-tertiary tabular-nums">
              {t('subcontractors.changes_approved_pending', {
                defaultValue: '{{approved}} approved, {{pending}} pending',
                approved: fmtCurrency(rollup.sub_cost_approved, ccy),
                pending: fmtCurrency(rollup.sub_cost_pending, ccy),
              })}
            </div>
          </div>
          <div>
            <div className={label}>
              {t('subcontractors.changes_margin', { defaultValue: 'Margin' })}
            </div>
            <div className={valueCls} data-testid="sc-margin">
              {fmtCurrency(rollup.margin, ccy)}
            </div>
          </div>
          <div>
            <div className={label}>
              {t('subcontractors.changes_margin_pct', { defaultValue: 'Margin %' })}
            </div>
            <div className={valueCls} data-testid="sc-margin-pct">
              {rollup.margin_percent == null ? '—' : fmtPercent(Number(rollup.margin_percent))}
            </div>
          </div>
        </div>
      )}

      {rollup && rollup.leakage != null && (
        <div
          className="flex flex-wrap items-center gap-x-4 gap-y-1 rounded-lg border border-border-light px-3 py-2 text-sm"
          data-testid="sc-leakage-strip"
        >
          <span className={label}>{t('subcontractors.changes_leakage', { defaultValue: 'Leakage' })}</span>
          <span
            className={clsx(
              'font-medium tabular-nums',
              leakageNum != null && leakageNum < 0 ? 'text-semantic-error' : 'text-content-primary',
            )}
            data-testid="sc-leakage"
          >
            {fmtCurrency(rollup.leakage, ccy)}
          </span>
          <span className="text-xs text-content-tertiary tabular-nums" data-testid="sc-markup-retained">
            {t('subcontractors.changes_markup_retained', { defaultValue: 'Markup kept' })}:{' '}
            {fmtCurrency(rollup.markup_retained ?? '0', ccy)}
          </span>
          <span className="text-xs text-content-tertiary tabular-nums" data-testid="sc-days">
            {t('subcontractors.changes_days_owner_vs_sub', {
              defaultValue: 'Days: owner {{owner}}, subcontract {{sub}}',
              owner: rollup.days_owner ?? '—',
              sub: rollup.days_sub_total ?? 0,
            })}
          </span>
        </div>
      )}

      {rollupQ.isError && (
        <p className="text-sm text-semantic-error">{getErrorMessage(rollupQ.error)}</p>
      )}

      {rollup && changes.length === 0 && (
        <p className="text-sm text-content-tertiary">
          {t('subcontractors.changes_none', {
            defaultValue: 'No subcontract changes are linked to this change yet.',
          })}
        </p>
      )}

      {changes.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-content-tertiary">
                <th className="py-1 pr-2">{t('subcontractors.changes_code', { defaultValue: 'Code' })}</th>
                <th className="py-1 pr-2">{t('subcontractors.changes_agreement', { defaultValue: 'Agreement' })}</th>
                <th className="py-1 pr-2 text-right">{t('subcontractors.changes_amount', { defaultValue: 'Amount' })}</th>
                <th className="py-1 pr-2 text-right">{t('subcontractors.changes_markup_pct', { defaultValue: 'Markup %' })}</th>
                <th className="py-1 pr-2 text-right">{t('subcontractors.changes_days', { defaultValue: 'Days' })}</th>
                <th className="py-1 pr-2">{t('subcontractors.changes_status', { defaultValue: 'Status' })}</th>
                <th className="py-1" />
              </tr>
            </thead>
            <tbody>
              {changes.map((c: SubcontractChange) => (
                <tr key={c.id} className="border-t border-border-light align-top">
                  <td className="py-1.5 pr-2 font-mono text-xs">{c.code}</td>
                  <td className="py-1.5 pr-2">
                    <div className="truncate">{agreementTitle(c.agreement_id)}</div>
                    {failedById.get(c.id)?.map((f) => (
                      <div key={f.rule_id} className="text-xs text-semantic-warning" role="alert">
                        {f.message}
                      </div>
                    ))}
                  </td>
                  <td className="py-1.5 pr-2 text-right tabular-nums">
                    {fmtCurrency(c.amount, c.currency)}
                  </td>
                  <td className="py-1.5 pr-2 text-right tabular-nums" data-testid={`sc-markup-${c.code}`}>
                    {c.markup_pct ?? '0'}
                  </td>
                  <td className="py-1.5 pr-2 text-right tabular-nums" data-testid={`sc-days-${c.code}`}>
                    {c.time_impact_days ?? 0}
                  </td>
                  <td className="py-1.5 pr-2">
                    <Badge variant={STATUS_VARIANT[c.status]} size="sm" dot>
                      {t(`subcontractors.change_status_${c.status}`, { defaultValue: c.status })}
                    </Badge>
                  </td>
                  <td className="py-1.5 text-right">
                    <div className="flex flex-wrap justify-end gap-1">
                      {awaitingOwner(c) && (
                        <span data-testid={`sc-blocker-${c.code}`}>
                          <Badge variant="warning" size="sm">
                            {t('subcontractors.changes_owner_not_approved', { defaultValue: 'Owner not approved yet' })}
                          </Badge>
                        </span>
                      )}
                      {ACTIONS[c.status].map((a) => (
                        <Button
                          key={a}
                          size="sm"
                          variant={a === 'reject' || a === 'withdraw' ? 'secondary' : 'primary'}
                          disabled={act.isPending || (a === 'approve' && awaitingOwner(c))}
                          onClick={() => act.mutate({ id: c.id, action: a })}
                        >
                          {t(`subcontractors.change_action_${a}`, { defaultValue: a })}
                        </Button>
                      ))}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="space-y-2 rounded-lg border border-border-light p-3">
        <div className="text-xs font-medium text-content-secondary">
          {t('subcontractors.changes_split_title', { defaultValue: 'Split to subcontracts' })}
        </div>
        {rows.map((r, i) => (
          <div key={i} className="flex flex-wrap items-center gap-2">
            <select
              aria-label={t('subcontractors.changes_agreement', { defaultValue: 'Agreement' })}
              value={r.agreementId}
              onChange={(e) => patchRow(i, { agreementId: e.target.value })}
              className={inputCls}
            >
              <option value="">
                {t('subcontractors.changes_pick_agreement', { defaultValue: 'Select agreement' })}
              </option>
              {agreements.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.title}
                </option>
              ))}
            </select>
            <input
              type="number"
              min="0"
              step="0.01"
              aria-label={t('subcontractors.changes_amount', { defaultValue: 'Amount' })}
              placeholder={t('subcontractors.changes_amount', { defaultValue: 'Amount' })}
              value={r.amount}
              onChange={(e) => patchRow(i, { amount: e.target.value })}
              className={clsx(inputCls, 'w-28')}
            />
            <input
              type="text"
              aria-label={t('subcontractors.changes_title_field', { defaultValue: 'Title' })}
              placeholder={t('subcontractors.changes_title_field', { defaultValue: 'Title' })}
              value={r.title}
              onChange={(e) => patchRow(i, { title: e.target.value })}
              className={clsx(inputCls, 'min-w-[8rem] flex-1')}
            />
            <input
              type="number"
              min="0"
              max="100"
              step="0.1"
              aria-label={t('subcontractors.changes_markup_pct', { defaultValue: 'Markup %' })}
              placeholder={t('subcontractors.changes_markup_pct', { defaultValue: 'Markup %' })}
              value={r.markup}
              onChange={(e) => patchRow(i, { markup: e.target.value })}
              className={clsx(inputCls, 'w-20')}
            />
            <input
              type="number"
              step="1"
              aria-label={t('subcontractors.changes_days', { defaultValue: 'Days' })}
              placeholder={t('subcontractors.changes_days', { defaultValue: 'Days' })}
              value={r.days}
              onChange={(e) => patchRow(i, { days: e.target.value })}
              className={clsx(inputCls, 'w-16')}
            />
            <label className="flex items-center gap-1 text-xs text-content-secondary">
              <input
                type="checkbox"
                checked={r.backToBack}
                onChange={(e) => patchRow(i, { backToBack: e.target.checked })}
              />
              {t('subcontractors.changes_back_to_back', { defaultValue: 'Back-to-back' })}
            </label>
            {rows.length > 1 && (
              <button
                type="button"
                aria-label={t('subcontractors.changes_remove_row', { defaultValue: 'Remove row' })}
                onClick={() => setRows((rs) => rs.filter((_, j) => j !== i))}
                className="text-content-tertiary hover:text-semantic-error"
              >
                <Trash2 size={14} />
              </button>
            )}
          </div>
        ))}
        <div className="flex items-center justify-between">
          <Button
            size="sm"
            variant="secondary"
            icon={<Plus size={14} />}
            onClick={() => setRows((rs) => [...rs, emptyRow()])}
          >
            {t('subcontractors.changes_add_row', { defaultValue: 'Add row' })}
          </Button>
          <Button size="sm" disabled={!canSplit || split.isPending} onClick={submitSplit}>
            {t('subcontractors.changes_split_submit', { defaultValue: 'Create subcontract changes' })}
          </Button>
        </div>
      </div>
    </section>
  );
}
