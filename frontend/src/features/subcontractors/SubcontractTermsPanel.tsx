// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Deductions tab: levies, retention cap and payment discount on a subcontract.
 *
 * Every figure on screen comes from the server statement, computed in Decimal.
 * The try-it box runs the saved terms on any invoice amount, so the worked
 * example is always the user's own contract, not a canned one.
 */

import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Percent, Plus, Trash2 } from 'lucide-react';
import { Badge, Button, EmptyState } from '@/shared/ui';
import { MoneyDisplay } from '@/shared/ui/MoneyDisplay';
import { useToastStore } from '@/stores/useToastStore';
import { fmtList } from '@/shared/lib/formatters';
import { listPaymentApplications, type Agreement } from './api';
import {
  createLevy,
  deleteLevy,
  getAgreementTerms,
  getDeductions,
  getLevyCatalogue,
  importPackLevies,
  putAgreementTerms,
  recordDeductions,
  type DeductionStatement,
  type LevyCatalogueItem,
  type SubcontractLevy,
  type SubcontractTerms,
} from './termsApi';

const fieldCls =
  'h-9 w-full rounded-lg border border-border bg-surface-primary px-2 text-sm text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue/30';

/** Accepts "1.5" or "1,5"; returns a Decimal string, or null when empty. */
export function decimalInput(value: string): string | null {
  const v = value.trim().replace(',', '.');
  return v === '' ? null : v;
}

function levyFromCatalogue(item: LevyCatalogueItem): SubcontractLevy {
  return {
    catalogue_id: item.id,
    code: item.code,
    name: item.name,
    basis: item.basis,
    rate_percent: item.default_percent,
    fixed_amount: item.default_fixed_amount,
    applies_at: item.applies_at,
    levy_base: 'gross',
  };
}

export function StatementTable({ statement }: { statement: DeductionStatement }) {
  const { t } = useTranslation();
  const cur = statement.currency || undefined;
  const label = (kind: string, name?: string): string => {
    switch (kind) {
      case 'work_value':
        return t('subcontractors.terms_line_work', { defaultValue: 'Work value' });
      case 'levy':
        return name ?? '';
      case 'retention':
        return t('subcontractors.terms_line_retention', {
          defaultValue: 'Retention {{rate}}%',
          rate: statement.retention_percent,
        });
      case 'payable':
        return t('subcontractors.terms_line_payable', { defaultValue: 'Payable' });
      default:
        return t('subcontractors.terms_line_discount', {
          defaultValue: 'Payment discount {{rate}}% if paid by {{date}}',
          rate: statement.payment_discount_percent ?? '0',
          date: statement.discount_due_date ?? '',
        });
    }
  };
  const failed = statement.validation.filter((v) => !v.passed);
  return (
    <div className="space-y-2" data-testid="deduction-statement">
      <table className="w-full text-sm">
        <tbody className="divide-y divide-border-light">
          {statement.lines.map((line, i) => {
            const minus = line.kind === 'levy' || line.kind === 'retention' || line.kind === 'payment_discount';
            const strong = line.kind === 'payable';
            return (
              <tr key={i} className={strong ? 'font-semibold' : ''}>
                <td className={`py-1.5 ${line.kind === 'levy' ? 'pl-4 text-content-secondary' : ''}`}>
                  {label(line.kind, line.name)}
                </td>
                <td className="py-1.5 text-right tabular-nums">
                  {minus && '- '}
                  <MoneyDisplay amount={line.amount} currency={cur} />
                </td>
              </tr>
            );
          })}
          <tr className="font-semibold text-oe-blue">
            <td className="py-2">
              {statement.discount_applies === false
                ? t('subcontractors.terms_to_pay_late', { defaultValue: 'To pay (discount date missed)' })
                : t('subcontractors.terms_to_pay', { defaultValue: 'To pay' })}
            </td>
            <td className="py-2 text-right tabular-nums" data-testid="amount-to-pay">
              <MoneyDisplay
                amount={statement.discount_applies === null ? statement.payable_with_discount : statement.amount_to_pay}
                currency={cur}
              />
            </td>
          </tr>
        </tbody>
      </table>
      {statement.retention_capped && (
        <p className="text-xs text-content-tertiary">
          {t('subcontractors.terms_capped', { defaultValue: 'Retention stopped at the agreed cap.' })}
        </p>
      )}
      {failed.map((v) => (
        <p key={v.rule_id} className="text-xs text-amber-700 dark:text-amber-400">
          {v.message}
        </p>
      ))}
    </div>
  );
}

function TryItBox({ agreementId }: { agreementId: string }) {
  const { t } = useTranslation();
  const [amount, setAmount] = useState('120000.00');
  const workValue = decimalInput(amount) ?? '';
  const q = useQuery({
    queryKey: ['subcontractors', 'deductions-preview', agreementId, workValue],
    queryFn: () => getDeductions(agreementId, { work_value: workValue }),
    enabled: !!agreementId && /^\d+(\.\d+)?$/.test(workValue),
  });
  return (
    <div className="rounded-lg border border-border-light bg-surface-secondary p-3 space-y-2">
      <p className="text-xs font-semibold uppercase tracking-wide text-content-secondary">
        {t('subcontractors.terms_try_title', { defaultValue: 'Worked example on these terms' })}
      </p>
      <label className="flex items-center gap-2 text-sm">
        {t('subcontractors.terms_try_amount', { defaultValue: 'Invoice amount' })}
        <input
          value={amount}
          onChange={(e) => setAmount(e.target.value)}
          inputMode="decimal"
          className={`${fieldCls} max-w-[160px] text-right`}
        />
      </label>
      {q.data && <StatementTable statement={q.data} />}
    </div>
  );
}

function CatalogueSection() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const catQ = useQuery({ queryKey: ['subcontractors', 'levy-catalogue'], queryFn: getLevyCatalogue });
  const [code, setCode] = useState('');
  const [name, setName] = useState('');
  const [rate, setRate] = useState('');
  const refresh = () => qc.invalidateQueries({ queryKey: ['subcontractors', 'levy-catalogue'] });
  const create = useMutation({
    mutationFn: () =>
      createLevy({
        code: code.trim(),
        name: name.trim(),
        basis: 'percent',
        default_percent: decimalInput(rate),
        default_fixed_amount: null,
        applies_at: 'each_invoice',
        is_active: true,
        sort_order: (catQ.data?.items.length ?? 0) * 10,
        notes: null,
      }),
    onSuccess: () => {
      setCode('');
      setName('');
      setRate('');
      refresh();
    },
    onError: (e: Error) => addToast({ type: 'error', title: e.message }),
  });
  const remove = useMutation({ mutationFn: deleteLevy, onSuccess: refresh });
  const importPack = useMutation({
    mutationFn: importPackLevies,
    onSuccess: (r) => {
      addToast({
        type: 'success',
        title: t('subcontractors.terms_pack_imported', {
          defaultValue: '{{count}} levies added. Set the rates you agree with your clients.',
          count: r.added,
        }),
      });
      refresh();
    },
  });
  const packMissing = (catQ.data?.pack_defaults ?? []).filter((d) => !d.in_catalogue);
  return (
    <details className="rounded-lg border border-border-light p-3">
      <summary className="cursor-pointer text-sm font-medium text-content-primary">
        {t('subcontractors.terms_catalogue', { defaultValue: 'Company levy catalogue' })}
      </summary>
      <div className="mt-3 space-y-2">
        {(catQ.data?.items ?? []).map((item) => (
          <div key={item.id} className="flex items-center gap-2 text-sm">
            <span className="flex-1 truncate">{item.name}</span>
            <span className="tabular-nums text-content-secondary">
              {item.default_percent !== null ? `${item.default_percent}%` : '-'}
            </span>
            {!item.is_active && <Badge variant="neutral">{t('subcontractors.terms_inactive', { defaultValue: 'inactive' })}</Badge>}
            <button
              type="button"
              aria-label={t('common.delete', 'Delete')}
              onClick={() => remove.mutate(item.id)}
              className="text-content-tertiary hover:text-red-600"
            >
              <Trash2 size={14} />
            </button>
          </div>
        ))}
        <div className="grid grid-cols-[minmax(0,1fr)_minmax(0,2fr)_minmax(0,1fr)_auto] gap-2">
          <input
            value={code}
            onChange={(e) => setCode(e.target.value)}
            placeholder={t('subcontractors.terms_code', { defaultValue: 'Code' })}
            className={fieldCls}
          />
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder={t('subcontractors.terms_name', { defaultValue: 'Name' })}
            className={fieldCls}
          />
          <input
            value={rate}
            onChange={(e) => setRate(e.target.value)}
            placeholder="%"
            inputMode="decimal"
            className={fieldCls}
          />
          <Button size="sm" onClick={() => create.mutate()} disabled={!code.trim() || !name.trim()}>
            <Plus size={14} />
          </Button>
        </div>
        {packMissing.length > 0 && (
          <div className="rounded bg-surface-secondary p-2 text-xs text-content-secondary">
            <p>
              {t('subcontractors.terms_pack_offer', {
                defaultValue: 'Your market pack lists {{count}} usual levies without rates: {{names}}.',
                count: packMissing.length,
                names: fmtList(packMissing.map((d) => d.name)),
              })}
            </p>
            <Button size="sm" variant="ghost" onClick={() => importPack.mutate()}>
              {t('subcontractors.terms_pack_import', { defaultValue: 'Add them to the catalogue' })}
            </Button>
          </div>
        )}
      </div>
    </details>
  );
}

function TermsForm({ agreement }: { agreement: Agreement }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const termsQ = useQuery({
    queryKey: ['subcontractors', 'terms', agreement.id],
    queryFn: () => getAgreementTerms(agreement.id),
  });
  const catQ = useQuery({ queryKey: ['subcontractors', 'levy-catalogue'], queryFn: getLevyCatalogue });
  const [draft, setDraft] = useState<SubcontractTerms | null>(null);
  useEffect(() => {
    if (termsQ.data) setDraft(termsQ.data);
  }, [termsQ.data]);

  const save = useMutation({
    mutationFn: (body: SubcontractTerms) => putAgreementTerms(agreement.id, body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['subcontractors', 'terms', agreement.id] });
      qc.invalidateQueries({ queryKey: ['subcontractors', 'deductions-preview', agreement.id] });
      addToast({ type: 'success', title: t('subcontractors.terms_saved', { defaultValue: 'Terms saved' }) });
    },
    onError: (e: Error) => addToast({ type: 'error', title: e.message }),
  });

  const unused = useMemo(
    () => (catQ.data?.items ?? []).filter((c) => c.is_active && !draft?.levies.some((l) => l.code === c.code)),
    [catQ.data, draft],
  );
  if (!draft) return null;
  const set = (patch: Partial<SubcontractTerms>) => setDraft({ ...draft, ...patch });
  const setLevy = (i: number, patch: Partial<SubcontractLevy>) =>
    set({ levies: draft.levies.map((l, j) => (j === i ? { ...l, ...patch } : l)) });

  return (
    <div className="space-y-3">
      <p className="text-xs text-content-secondary">
        {t('subcontractors.terms_basis_note', {
          defaultValue:
            'Retention and each levy are taken on the gross work value, so their order does not change the result. The payment discount comes last, on what remains payable.',
        })}
      </p>
      <div className="grid grid-cols-2 gap-2 text-sm">
        <label className="space-y-1">
          <span className="text-xs text-content-secondary">
            {t('subcontractors.terms_cap', { defaultValue: 'Retention cap, % of contract sum' })}
          </span>
          <input
            value={draft.retention_cap_percent ?? ''}
            onChange={(e) => set({ retention_cap_percent: decimalInput(e.target.value) })}
            inputMode="decimal"
            className={fieldCls}
          />
        </label>
        <label className="space-y-1">
          <span className="text-xs text-content-secondary">
            {t('subcontractors.terms_discount', { defaultValue: 'Payment discount %' })}
          </span>
          <input
            value={draft.payment_discount_percent ?? ''}
            onChange={(e) => set({ payment_discount_percent: decimalInput(e.target.value) })}
            inputMode="decimal"
            className={fieldCls}
          />
        </label>
        <label className="space-y-1">
          <span className="text-xs text-content-secondary">
            {t('subcontractors.terms_discount_days', { defaultValue: 'If paid within (days)' })}
          </span>
          <input
            value={draft.payment_discount_days ?? ''}
            onChange={(e) =>
              set({ payment_discount_days: e.target.value.trim() ? Number.parseInt(e.target.value, 10) || 0 : null })
            }
            inputMode="numeric"
            className={fieldCls}
          />
        </label>
      </div>
      <label className="inline-flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          checked={draft.payment_discount_agreed}
          onChange={(e) => set({ payment_discount_agreed: e.target.checked })}
        />
        {t('subcontractors.terms_discount_agreed', { defaultValue: 'Discount is agreed in the signed contract' })}
      </label>

      <div className="space-y-1">
        <p className="text-xs font-semibold uppercase tracking-wide text-content-secondary">
          {t('subcontractors.terms_levies', { defaultValue: 'Levies' })}
        </p>
        {draft.levies.length === 0 && (
          <p className="text-xs text-content-tertiary">
            {t('subcontractors.terms_no_levies', { defaultValue: 'No levies on this subcontract.' })}
          </p>
        )}
        {draft.levies.map((levy, i) => (
          <div key={levy.code} className="grid grid-cols-[minmax(0,2fr)_minmax(0,1fr)_minmax(0,1.4fr)_minmax(0,1.2fr)_auto] items-center gap-2 text-sm">
            <span className="truncate">{levy.name}</span>
            <input
              aria-label={t('subcontractors.terms_rate', { defaultValue: 'Rate %' })}
              value={(levy.basis === 'fixed' ? levy.fixed_amount : levy.rate_percent) ?? ''}
              onChange={(e) =>
                setLevy(
                  i,
                  levy.basis === 'fixed'
                    ? { fixed_amount: decimalInput(e.target.value) }
                    : { rate_percent: decimalInput(e.target.value) },
                )
              }
              placeholder={levy.basis === 'fixed' ? agreement.currency || '' : '%'}
              inputMode="decimal"
              className={`${fieldCls} text-right`}
            />
            <select
              value={levy.applies_at}
              onChange={(e) => setLevy(i, { applies_at: e.target.value as SubcontractLevy['applies_at'] })}
              className={fieldCls}
            >
              <option value="each_invoice">
                {t('subcontractors.terms_each_invoice', { defaultValue: 'Every invoice' })}
              </option>
              <option value="final_account">
                {t('subcontractors.terms_final_account', { defaultValue: 'Once, at final account' })}
              </option>
            </select>
            <select
              aria-label={t('subcontractors.terms_levy_base', { defaultValue: 'Taken on' })}
              value={levy.levy_base ?? 'gross'}
              onChange={(e) => setLevy(i, { levy_base: e.target.value as SubcontractLevy['levy_base'] })}
              className={fieldCls}
              disabled={levy.basis === 'fixed'}
            >
              <option value="gross">{t('subcontractors.terms_levy_on_gross', { defaultValue: 'Gross' })}</option>
              <option value="net_after_retention">
                {t('subcontractors.terms_levy_on_net', { defaultValue: 'Net after retention' })}
              </option>
            </select>
            <button
              type="button"
              aria-label={t('common.delete', 'Delete')}
              onClick={() => set({ levies: draft.levies.filter((_, j) => j !== i) })}
              className="text-content-tertiary hover:text-red-600"
            >
              <Trash2 size={14} />
            </button>
          </div>
        ))}
        {unused.length > 0 && (
          <select
            value=""
            onChange={(e) => {
              const item = unused.find((c) => c.id === e.target.value);
              if (item) set({ levies: [...draft.levies, levyFromCatalogue(item)] });
            }}
            className={`${fieldCls} max-w-xs`}
          >
            <option value="">{t('subcontractors.terms_add_levy', { defaultValue: 'Add a levy from the catalogue' })}</option>
            {unused.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
        )}
      </div>
      <Button size="sm" onClick={() => save.mutate(draft)} disabled={save.isPending}>
        {t('common.save', 'Save')}
      </Button>
    </div>
  );
}

function PaymentStatements({ agreement }: { agreement: Agreement }) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const [openId, setOpenId] = useState<string | null>(null);
  const paQ = useQuery({
    queryKey: ['subcontractors', 'payments', agreement.id],
    queryFn: () => listPaymentApplications({ agreement_id: agreement.id }),
  });
  const stQ = useQuery({
    queryKey: ['subcontractors', 'deductions', agreement.id, openId],
    queryFn: () => getDeductions(agreement.id, { payment_application_id: openId! }),
    enabled: !!openId,
  });
  const record = useMutation({
    mutationFn: (paId: string) => recordDeductions(agreement.id, paId),
    onSuccess: () =>
      addToast({ type: 'success', title: t('subcontractors.terms_recorded', { defaultValue: 'Statement recorded' }) }),
  });
  const pas = paQ.data ?? [];
  if (pas.length === 0) return null;
  return (
    <div className="space-y-1">
      <p className="text-xs font-semibold uppercase tracking-wide text-content-secondary">
        {t('subcontractors.terms_per_application', { defaultValue: 'Statement per payment application' })}
      </p>
      {pas.map((pa) => (
        <div key={pa.id} className="rounded border border-border-light p-2">
          <div className="flex items-center gap-2 text-sm">
            <button
              type="button"
              className="flex-1 text-left font-medium text-oe-blue"
              onClick={() => setOpenId(openId === pa.id ? null : pa.id)}
            >
              {pa.application_number}
            </button>
            <MoneyDisplay amount={pa.gross_amount} currency={pa.currency || undefined} />
            {openId === pa.id && (
              <Button size="sm" variant="ghost" onClick={() => record.mutate(pa.id)}>
                {t('subcontractors.terms_record', { defaultValue: 'Record' })}
              </Button>
            )}
          </div>
          {openId === pa.id && stQ.data && (
            <div className="mt-2">
              <StatementTable statement={stQ.data} />
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

export function SubcontractTermsPanel({ agreements }: { agreements: Agreement[] }) {
  const { t } = useTranslation();
  const [agreementId, setAgreementId] = useState(agreements[0]?.id ?? '');
  const agreement = agreements.find((a) => a.id === agreementId) ?? agreements[0];
  if (!agreement) {
    return (
      <EmptyState
        icon={<Percent size={20} />}
        title={t('subcontractors.terms_no_agreement', {
          defaultValue: 'Create an agreement first to set levies and payment discount.',
        })}
      />
    );
  }
  return (
    <div className="space-y-4" data-testid="subcontract-terms-panel">
      {agreements.length > 1 && (
        <select value={agreement.id} onChange={(e) => setAgreementId(e.target.value)} className={fieldCls}>
          {agreements.map((a) => (
            <option key={a.id} value={a.id}>
              {a.title}
            </option>
          ))}
        </select>
      )}
      <TermsForm key={agreement.id} agreement={agreement} />
      <TryItBox agreementId={agreement.id} />
      <PaymentStatements agreement={agreement} />
      <CatalogueSection />
    </div>
  );
}
