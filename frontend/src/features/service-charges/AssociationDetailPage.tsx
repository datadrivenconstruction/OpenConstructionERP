// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * One owners association: apportionment keys, yearly budgets, demands per period and
 * the year-end reconciliation. Every amount comes from the server as a decimal string.
 */
import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, useParams } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ArrowLeft, CheckCircle2, Download, Plus, Receipt, Scale, Trash2 } from 'lucide-react';
import { Badge, Button, Card, EmptyState, SkeletonTable } from '@/shared/ui';
import { PageHeader } from '@/shared/ui/PageHeader';
import { getErrorMessage } from '@/shared/lib/api';
import { fmtCurrency } from '@/shared/lib/formatters';
import { useToastStore } from '@/stores/useToastStore';
import {
  PERIODS,
  addBudgetLine,
  approveBudget,
  computeReconciliation,
  createBudget,
  createKey,
  deleteBudgetLine,
  deleteKey,
  downloadExport,
  fetchAssociation,
  fetchBudgets,
  fetchDemands,
  fetchKeys,
  fetchReconciliation,
  postReconciliation,
  runDemands,
  type ApportionmentKey,
  type Budget,
  type Frequency,
  type KeyMethod,
} from './api';
import { inputCls } from './ServiceChargesPage';

const STATUS_VARIANT = { draft: 'neutral', approved: 'success', closed: 'blue' } as const;

function useNotify() {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  return (e: unknown) =>
    addToast({
      type: 'error',
      title: t('service_charges.action_failed', { defaultValue: 'The action failed' }),
      message: getErrorMessage(e),
    });
}

function KeysSection({ associationId, keys }: { associationId: string; keys: ApportionmentKey[] }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const onError = useNotify();
  const [name, setName] = useState('');
  const [method, setMethod] = useState<KeyMethod>('permille');
  const [text, setText] = useState('');
  const methodLabel = (m: KeyMethod) =>
    ({
      area: t('service_charges.method_area', { defaultValue: 'By floor area' }),
      permille: t('service_charges.method_permille', { defaultValue: 'By permille (total 1000)' }),
      equal: t('service_charges.method_equal', { defaultValue: 'Equal shares' }),
      custom: t('service_charges.method_custom', { defaultValue: 'Agreed percent (total 100)' }),
    })[m];
  const lines = text
    .split('\n')
    .map((l) => l.trim())
    .filter(Boolean)
    .map((l) => {
      const [unit_ref = '', share = '0', payer = ''] = l.split(/[;,\t]/).map((x) => x.trim());
      return { unit_ref, share: share || '0', payer_contact_id: payer || null };
    });
  const create = useMutation({
    mutationFn: () => createKey(associationId, { name, method, lines }),
    onSuccess: () => {
      setName('');
      setText('');
      qc.invalidateQueries({ queryKey: ['service-charges'] });
    },
    onError,
  });
  const remove = useMutation({ mutationFn: deleteKey, onSuccess: () => qc.invalidateQueries({ queryKey: ['service-charges'] }), onError });
  return (
    <Card padding="sm">
      <h2 className="mb-2 text-sm font-semibold text-content-primary">
        {t('service_charges.keys_title', { defaultValue: 'Apportionment keys' })}
      </h2>
      {keys.length === 0 ? (
        <p className="text-xs text-content-tertiary">
          {t('service_charges.keys_empty', { defaultValue: 'No key yet. A key lists every unit and its share.' })}
        </p>
      ) : (
        <ul className="space-y-2">
          {keys.map((k) => (
            <li key={k.id} className="rounded-md border border-border-light p-2">
              <div className="flex items-center justify-between gap-2">
                <span className="text-sm font-medium">{k.name}</span>
                <span className="flex items-center gap-2 text-xs text-content-tertiary">
                  {methodLabel(k.method)}
                  <button
                    type="button"
                    aria-label={t('common.delete', { defaultValue: 'Delete' })}
                    className="text-content-tertiary hover:text-semantic-error"
                    onClick={() => remove.mutate(k.id)}
                  >
                    <Trash2 size={14} />
                  </button>
                </span>
              </div>
              <p className="mt-1 text-2xs text-content-tertiary" dir="ltr">
                {k.lines.map((l) => `${l.unit_ref}: ${l.share}`).join(' · ')}
              </p>
            </li>
          ))}
        </ul>
      )}
      <div className="mt-3 grid gap-2 border-t border-border-light pt-3 sm:grid-cols-3">
        <input
          className={inputCls}
          placeholder={t('service_charges.key_name', { defaultValue: 'Key name' })}
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
        <select className={inputCls} value={method} onChange={(e) => setMethod(e.target.value as KeyMethod)}>
          {(['permille', 'area', 'equal', 'custom'] as KeyMethod[]).map((m) => (
            <option key={m} value={m}>
              {methodLabel(m)}
            </option>
          ))}
        </select>
        <Button
          variant="secondary"
          size="sm"
          icon={<Plus size={14} />}
          disabled={!name.trim() || lines.length === 0 || create.isPending}
          onClick={() => create.mutate()}
        >
          {t('service_charges.add_key', { defaultValue: 'Add key' })}
        </Button>
        <textarea
          className={`${inputCls} sm:col-span-3`}
          rows={4}
          dir="ltr"
          placeholder={t('service_charges.key_lines_hint', {
            defaultValue: 'One unit per line: unit reference; share; payer contact id (optional)',
          })}
          value={text}
          onChange={(e) => setText(e.target.value)}
        />
      </div>
    </Card>
  );
}

function BudgetCard({ budget, keys, currency }: { budget: Budget; keys: ApportionmentKey[]; currency: string }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const onError = useNotify();
  const addToast = useToastStore((s) => s.addToast);
  const [category, setCategory] = useState('');
  const [amount, setAmount] = useState('');
  const [keyId, setKeyId] = useState(keys[0]?.id ?? '');
  const [period, setPeriod] = useState(1);
  const refresh = () => qc.invalidateQueries({ queryKey: ['service-charges'] });
  const demandsQ = useQuery({
    queryKey: ['service-charges', 'demands', budget.id],
    queryFn: () => fetchDemands(budget.id),
    enabled: budget.status !== 'draft',
  });
  const recQ = useQuery({
    queryKey: ['service-charges', 'rec', budget.id],
    queryFn: () => fetchReconciliation(budget.id),
    enabled: budget.status !== 'draft',
  });
  const add = useMutation({
    mutationFn: () => addBudgetLine(budget.id, { category, amount, key_id: keyId }),
    onSuccess: () => {
      setCategory('');
      setAmount('');
      refresh();
    },
    onError,
  });
  const removeLine = useMutation({ mutationFn: deleteBudgetLine, onSuccess: refresh, onError });
  const approve = useMutation({ mutationFn: () => approveBudget(budget.id), onSuccess: refresh, onError });
  const run = useMutation({
    mutationFn: () => runDemands(budget.id, period),
    onSuccess: (r) => {
      addToast({
        type: 'success',
        title: t('service_charges.run_done', {
          defaultValue: 'Demands raised as draft invoices: {{n}}, already raised: {{skipped}}',
          n: r.created,
          skipped: r.skipped,
        }),
      });
      refresh();
    },
    onError,
  });
  const compute = useMutation({ mutationFn: () => computeReconciliation(budget.id), onSuccess: refresh, onError });
  const post = useMutation({ mutationFn: () => postReconciliation(budget.id), onSuccess: refresh, onError });
  const keyName = (id: string) => keys.find((k) => k.id === id)?.name ?? '';
  const demanded = useMemo(
    () => (demandsQ.data ?? []).filter((d) => d.period === period).length,
    [demandsQ.data, period],
  );
  const rec = recQ.data;
  const statusLabel = {
    draft: t('service_charges.status_draft', { defaultValue: 'Draft' }),
    approved: t('service_charges.status_approved', { defaultValue: 'Approved' }),
    closed: t('service_charges.status_closed', { defaultValue: 'Closed' }),
  }[budget.status];

  return (
    <Card padding="sm" data-testid={`service-charges-budget-${budget.year}`}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-sm font-semibold text-content-primary">
          {t('service_charges.budget_year', { defaultValue: 'Budget {{year}}', year: budget.year })}
        </h3>
        <div className="flex items-center gap-2">
          <Badge variant={STATUS_VARIANT[budget.status]}>{statusLabel}</Badge>
          <span className="text-sm font-semibold tabular-nums">{fmtCurrency(budget.total, currency)}</span>
        </div>
      </div>
      <table className="mt-2 w-full text-xs">
        <thead className="text-content-tertiary">
          <tr>
            <th className="py-1 text-start font-medium">{t('service_charges.col_category', { defaultValue: 'Cost category' })}</th>
            <th className="py-1 text-start font-medium">{t('service_charges.col_key', { defaultValue: 'Split by' })}</th>
            <th className="py-1 text-end font-medium">{t('service_charges.col_amount', { defaultValue: 'Amount' })}</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {budget.lines.map((l) => (
            <tr key={l.id} className="border-t border-border-light">
              <td className="py-1">{l.category}</td>
              <td className="py-1">{keyName(l.key_id)}</td>
              <td className="py-1 text-end tabular-nums">{fmtCurrency(l.amount, currency)}</td>
              <td className="py-1 text-end">
                {budget.status === 'draft' && (
                  <button
                    type="button"
                    aria-label={t('common.delete', { defaultValue: 'Delete' })}
                    className="text-content-tertiary hover:text-semantic-error"
                    onClick={() => removeLine.mutate(l.id)}
                  >
                    <Trash2 size={13} />
                  </button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {budget.status === 'draft' && (
        <div className="mt-3 grid gap-2 border-t border-border-light pt-3 sm:grid-cols-4">
          <input
            className={inputCls}
            placeholder={t('service_charges.col_category', { defaultValue: 'Cost category' })}
            value={category}
            onChange={(e) => setCategory(e.target.value)}
          />
          <input
            className={inputCls}
            inputMode="decimal"
            dir="ltr"
            placeholder={t('service_charges.col_amount', { defaultValue: 'Amount' })}
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
          />
          <select className={inputCls} value={keyId} onChange={(e) => setKeyId(e.target.value)}>
            {keys.map((k) => (
              <option key={k.id} value={k.id}>
                {k.name}
              </option>
            ))}
          </select>
          <div className="flex gap-2">
            <Button
              variant="secondary"
              size="sm"
              icon={<Plus size={14} />}
              disabled={!category.trim() || !amount || !keyId || add.isPending}
              onClick={() => add.mutate()}
            >
              {t('service_charges.add_line', { defaultValue: 'Add line' })}
            </Button>
            <Button
              variant="primary"
              size="sm"
              icon={<CheckCircle2 size={14} />}
              disabled={budget.lines.length === 0 || approve.isPending}
              onClick={() => approve.mutate()}
            >
              {t('service_charges.approve', { defaultValue: 'Approve' })}
            </Button>
          </div>
        </div>
      )}
      {budget.status === 'approved' && (
        <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-border-light pt-3 text-xs">
          <span>{t('service_charges.period', { defaultValue: 'Period' })}</span>
          <select className={`${inputCls} w-24`} value={period} onChange={(e) => setPeriod(Number(e.target.value))}>
            {Array.from({ length: PERIODS[budget.demand_frequency as Frequency] }, (_, i) => i + 1).map((p) => (
              <option key={p} value={p}>
                {p}
              </option>
            ))}
          </select>
          <span className="text-content-tertiary">
            {t('service_charges.demanded_units', { defaultValue: 'Units demanded: {{n}}', n: demanded })}
          </span>
          <Button variant="secondary" size="sm" icon={<Receipt size={14} />} disabled={run.isPending} onClick={() => run.mutate()}>
            {t('service_charges.run', { defaultValue: 'Raise demands' })}
          </Button>
          <Button variant="secondary" size="sm" icon={<Scale size={14} />} disabled={compute.isPending} onClick={() => compute.mutate()}>
            {t('service_charges.compute', { defaultValue: 'Compare with actual costs' })}
          </Button>
        </div>
      )}
      {rec && (
        <div className="mt-3 border-t border-border-light pt-3">
          <div className="flex flex-wrap items-center justify-between gap-2 text-xs">
            <span className="font-semibold text-content-primary">
              {t('service_charges.rec_title', { defaultValue: 'Year-end settlement' })}
            </span>
            <span className="text-content-tertiary">
              {t('service_charges.rec_totals', {
                defaultValue: 'Actual costs {{actual}}, demanded {{demanded}}',
                actual: fmtCurrency(rec.total_actual, currency),
                demanded: fmtCurrency(rec.total_demanded, currency),
              })}
            </span>
          </div>
          <table className="mt-2 w-full text-xs">
            <thead className="text-content-tertiary">
              <tr>
                <th className="py-1 text-start font-medium">{t('service_charges.col_unit', { defaultValue: 'Unit' })}</th>
                <th className="py-1 text-end font-medium">{t('service_charges.col_demanded', { defaultValue: 'Demanded' })}</th>
                <th className="py-1 text-end font-medium">{t('service_charges.col_actual', { defaultValue: 'Actual share' })}</th>
                <th className="py-1 text-end font-medium">{t('service_charges.col_balance', { defaultValue: 'Refund (+) / to pay (-)' })}</th>
              </tr>
            </thead>
            <tbody>
              {rec.unit_balances.map((u) => (
                <tr key={u.unit_ref} className="border-t border-border-light">
                  <td className="py-1" dir="ltr">{u.unit_ref}</td>
                  <td className="py-1 text-end tabular-nums">{fmtCurrency(u.demanded, currency)}</td>
                  <td className="py-1 text-end tabular-nums">{fmtCurrency(u.actual_share, currency)}</td>
                  <td className="py-1 text-end font-medium tabular-nums">{fmtCurrency(u.balance, currency)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {Object.keys(rec.unallocated).length > 0 && (
            <p className="mt-2 text-2xs text-semantic-warning">
              {t('service_charges.unallocated', {
                defaultValue: 'Costs without a budget line or default key, charged to nobody: {{list}}',
                list: Object.entries(rec.unallocated)
                  .map(([c, v]) => `${c} ${fmtCurrency(v, currency)}`)
                  .join(', '),
              })}
            </p>
          )}
          {rec.status === 'draft' ? (
            <div className="mt-2 flex justify-end">
              <Button variant="primary" size="sm" disabled={post.isPending} onClick={() => post.mutate()}>
                {t('service_charges.post', { defaultValue: 'Post bills and refunds to finance' })}
              </Button>
            </div>
          ) : (
            <p className="mt-2 text-2xs text-content-tertiary">
              {t('service_charges.posted', {
                defaultValue: 'Posted: {{invoices}} bills and {{credits}} refunds in finance.',
                invoices: rec.posted_invoice_ids.length,
                credits: rec.posted_credit_ids.length,
              })}
            </p>
          )}
        </div>
      )}
    </Card>
  );
}

export function AssociationDetailPage() {
  const { t } = useTranslation();
  const { associationId = '' } = useParams();
  const qc = useQueryClient();
  const onError = useNotify();
  const [year, setYear] = useState(new Date().getFullYear());
  const [frequency, setFrequency] = useState<Frequency>('quarterly');
  const assocQ = useQuery({ queryKey: ['service-charges', 'assoc', associationId], queryFn: () => fetchAssociation(associationId) });
  const keysQ = useQuery({ queryKey: ['service-charges', 'keys', associationId], queryFn: () => fetchKeys(associationId) });
  const budgetsQ = useQuery({ queryKey: ['service-charges', 'budgets', associationId], queryFn: () => fetchBudgets(associationId) });
  const newBudget = useMutation({
    mutationFn: () => createBudget(associationId, { year, demand_frequency: frequency }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['service-charges'] }),
    onError,
  });
  const assoc = assocQ.data;
  const keys = keysQ.data ?? [];
  const freqLabel = (f: Frequency) =>
    ({
      annual: t('service_charges.freq_annual', { defaultValue: 'Once a year' }),
      semiannual: t('service_charges.freq_semiannual', { defaultValue: 'Twice a year' }),
      quarterly: t('service_charges.freq_quarterly', { defaultValue: 'Quarterly' }),
      monthly: t('service_charges.freq_monthly', { defaultValue: 'Monthly' }),
    })[f];

  if (assocQ.isLoading) return <SkeletonTable rows={5} columns={3} />;
  if (!assoc)
    return <EmptyState title={t('service_charges.not_found', { defaultValue: 'Association not found' })} />;

  return (
    <div className="space-y-5 animate-fade-in">
      <PageHeader
        srTitle={assoc.name}
        subtitle={
          <>
            <span className="font-semibold text-content-primary">{assoc.name}</span>{' '}
            {t('service_charges.detail_subtitle', {
              defaultValue: 'Currency {{currency}}, financial year starts in month {{month}}',
              currency: assoc.currency,
              month: assoc.fiscal_year_start_month,
            })}
          </>
        }
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <Link to="/service-charges" className="flex items-center gap-1 text-xs text-oe-blue hover:underline">
              <ArrowLeft size={14} className="rtl:rotate-180" />
              {t('service_charges.back', { defaultValue: 'All associations' })}
            </Link>
            <Button variant="ghost" size="sm" icon={<Download size={14} />} onClick={() => void downloadExport(assoc.id, 'csv')}>
              CSV
            </Button>
            <Button variant="ghost" size="sm" icon={<Download size={14} />} onClick={() => void downloadExport(assoc.id, 'json')}>
              JSON
            </Button>
          </div>
        }
      />
      <KeysSection associationId={assoc.id} keys={keys} />
      <Card padding="sm">
        <h2 className="mb-2 text-sm font-semibold text-content-primary">
          {t('service_charges.budgets_title', { defaultValue: 'Budgets' })}
        </h2>
        <div className="flex flex-wrap items-center gap-2">
          <input
            type="number"
            className={`${inputCls} w-28`}
            value={year}
            onChange={(e) => setYear(Number(e.target.value) || new Date().getFullYear())}
          />
          <select className={`${inputCls} w-40`} value={frequency} onChange={(e) => setFrequency(e.target.value as Frequency)}>
            {(['annual', 'semiannual', 'quarterly', 'monthly'] as Frequency[]).map((f) => (
              <option key={f} value={f}>
                {freqLabel(f)}
              </option>
            ))}
          </select>
          <Button
            variant="secondary"
            size="sm"
            icon={<Plus size={14} />}
            disabled={keys.length === 0 || newBudget.isPending}
            onClick={() => newBudget.mutate()}
          >
            {t('service_charges.new_budget', { defaultValue: 'New budget' })}
          </Button>
        </div>
      </Card>
      {(budgetsQ.data ?? []).map((b) => (
        <BudgetCard key={b.id} budget={b} keys={keys} currency={assoc.currency} />
      ))}
    </div>
  );
}
