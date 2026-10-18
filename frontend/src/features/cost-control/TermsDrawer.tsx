// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// A supplier contract's payment terms in one form. The invoice mode and the
// interim retention are always there; warranty retention, the early payment
// discount and rounding are switches that stay off until a contract has them,
// and only show their fields once switched on. Saving recomputes every open
// release of the contract; confirmed releases keep their figures and the
// checks say where they would now differ.
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { Button, Skeleton } from '@/shared/ui';
import { SideDrawer } from '@/shared/ui/SideDrawer';
import { getErrorMessage } from '@/shared/lib/api';
import { stripCurrencySigns, toDecimalPayloadString } from '@/shared/lib/parseDecimal';
import { problemOf } from '@/features/costmodel/structureApi';
import { useToastStore } from '@/stores/useToastStore';
import {
  RELEASE_EVENTS,
  eventLabel,
  paymentProblem,
  paymentsApi,
  type PaymentTerms,
  type PaymentTermsBody,
} from './paymentsApi';

const INPUT = 'h-8 w-full rounded-lg border border-border bg-surface-primary px-2.5 text-sm disabled:opacity-60';

function bodyOf(terms: PaymentTerms): PaymentTermsBody {
  const { contract_id: _c, terms_set: _s, currency: _cur, ...body } = terms;
  return body;
}

/** Rates and the rounding step as the reader typed them (`5,5`, `100,00 €`), sent as dot-decimal strings. */
export function payloadOf(form: PaymentTermsBody): PaymentTermsBody {
  const dec = (raw: string) => toDecimalPayloadString(stripCurrencySigns(raw), '0');
  return {
    ...form,
    retention_percent: dec(form.retention_percent),
    warranty_percent: dec(form.warranty_percent),
    discount_percent: dec(form.discount_percent),
    rounding_step: dec(form.rounding_step),
  };
}

/** An empty or non-numeric field reads as null for the optional day counts. */
function intOrNull(value: string): number | null {
  const trimmed = value.trim();
  if (!trimmed) return null;
  const n = Number.parseInt(trimmed, 10);
  return Number.isFinite(n) ? n : null;
}

function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-medium text-content-secondary">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-2xs text-content-tertiary">{hint}</span>}
    </label>
  );
}

function Switch({
  checked,
  onChange,
  label,
  hint,
  disabled,
  testId,
}: {
  checked: boolean;
  onChange: (next: boolean) => void;
  label: string;
  hint: string;
  disabled: boolean;
  testId: string;
}) {
  return (
    <label className="flex items-start gap-3">
      <input
        type="checkbox"
        role="switch"
        aria-checked={checked}
        className="mt-1"
        checked={checked}
        disabled={disabled}
        onChange={(e) => onChange(e.target.checked)}
        data-testid={testId}
      />
      <span>
        <span className="block text-sm font-medium text-content-primary">{label}</span>
        <span className="block text-xs text-content-tertiary">{hint}</span>
      </span>
    </label>
  );
}

export function TermsDrawer({
  contractId,
  contractLabel,
  canEdit,
  onClose,
}: {
  contractId: string | null;
  contractLabel: string;
  canEdit: boolean;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const terms = useQuery({
    queryKey: ['payment-release', 'terms', contractId],
    queryFn: () => paymentsApi.terms(contractId!),
    enabled: !!contractId,
  });
  const [form, setForm] = useState<PaymentTermsBody | null>(null);

  useEffect(() => {
    setForm(terms.data ? bodyOf(terms.data) : null);
  }, [terms.data]);

  const save = useMutation({
    mutationFn: (body: PaymentTermsBody) => paymentsApi.putTerms(contractId!, body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['payment-release'] });
      queryClient.invalidateQueries({ queryKey: ['cost-control'] });
      addToast({ type: 'success', title: t('cost_control.pay.terms_saved', { defaultValue: 'Payment terms saved' }) });
      onClose();
    },
    onError: (err: unknown) => {
      const problem = problemOf(err);
      addToast({
        type: 'error',
        title: t('cost_control.pay.terms_save_failed', { defaultValue: 'Could not save the payment terms' }),
        message: (problem && paymentProblem(t, problem.problem, problem.params)) || getErrorMessage(err),
      });
    },
  });

  const set = <K extends keyof PaymentTermsBody>(key: K, value: PaymentTermsBody[K]) =>
    setForm((f) => (f ? { ...f, [key]: value } : f));
  const disabled = !canEdit || save.isPending;
  const currency = terms.data?.currency ?? '';

  return (
    <SideDrawer
      open={!!contractId}
      onClose={onClose}
      busy={save.isPending}
      title={t('cost_control.pay.terms_title', { defaultValue: 'Payment terms' })}
      subtitle={contractLabel}
      widthClass="w-full max-w-xl"
    >
      <div className="px-5 py-4">
      {terms.isLoading || !form ? (
        terms.error ? (
          <p className="text-sm text-semantic-error">{getErrorMessage(terms.error)}</p>
        ) : (
          <Skeleton className="h-64 w-full" />
        )
      ) : (
        <form
          className="space-y-5"
          data-testid="payment-terms-form"
          onSubmit={(e) => {
            e.preventDefault();
            if (canEdit) save.mutate(payloadOf(form));
          }}
        >
          {!terms.data?.terms_set && (
            <p className="rounded-lg bg-surface-secondary/60 px-3 py-2 text-xs text-content-secondary">
              {t('cost_control.pay.terms_defaults', {
                defaultValue:
                  'No terms are set for this contract yet. It runs on the defaults: each invoice for new work only, no discount, no rounding.',
              })}
            </p>
          )}

          <section className="space-y-3">
            <h3 className="text-sm font-semibold text-content-primary">
              {t('cost_control.pay.terms_invoicing', { defaultValue: 'Invoicing' })}
            </h3>
            <Field
              label={t('cost_control.pay.terms_mode', { defaultValue: 'How the supplier invoices' })}
              hint={
                form.invoice_mode === 'cumulative'
                  ? t('cost_control.pay.terms_mode_cumulative_hint', {
                      defaultValue:
                        'Each invoice states the total to date. The release takes off everything released before.',
                    })
                  : t('cost_control.pay.terms_mode_incremental_hint', {
                      defaultValue: 'Each invoice states only the work since the last one.',
                    })
              }
            >
              <select
                className={INPUT}
                value={form.invoice_mode}
                disabled={disabled}
                onChange={(e) => set('invoice_mode', e.target.value as PaymentTermsBody['invoice_mode'])}
              >
                <option value="incremental">
                  {t('cost_control.pay.mode_incremental', { defaultValue: 'Each invoice for new work only' })}
                </option>
                <option value="cumulative">
                  {t('cost_control.pay.mode_cumulative', { defaultValue: 'Cumulative invoices' })}
                </option>
              </select>
            </Field>
            <div className="grid grid-cols-2 gap-3">
              <Field label={t('cost_control.pay.terms_interim_due', { defaultValue: 'Interim invoice due after (days)' })}>
                <input
                  className={INPUT}
                  inputMode="numeric"
                  value={form.interim_due_days ?? ''}
                  disabled={disabled}
                  onChange={(e) => set('interim_due_days', intOrNull(e.target.value))}
                />
              </Field>
              <Field label={t('cost_control.pay.terms_final_due', { defaultValue: 'Final invoice due after (days)' })}>
                <input
                  className={INPUT}
                  inputMode="numeric"
                  value={form.final_due_days ?? ''}
                  disabled={disabled}
                  onChange={(e) => set('final_due_days', intOrNull(e.target.value))}
                />
              </Field>
            </div>
          </section>

          <section className="space-y-3">
            <h3 className="text-sm font-semibold text-content-primary">
              {t('cost_control.pay.terms_retention', { defaultValue: 'Retention on interim invoices' })}
            </h3>
            <div className="grid grid-cols-2 gap-3">
              <Field label={t('cost_control.pay.terms_retention_percent', { defaultValue: 'Rate (%)' })}>
                <input
                  className={INPUT}
                  inputMode="decimal"
                  value={form.retention_percent}
                  disabled={disabled}
                  onChange={(e) => set('retention_percent', e.target.value)}
                  data-testid="terms-retention-percent"
                />
              </Field>
              <Field label={t('cost_control.pay.terms_retention_basis', { defaultValue: 'Taken on' })}>
                <select
                  className={INPUT}
                  value={form.retention_basis}
                  disabled={disabled}
                  onChange={(e) => set('retention_basis', e.target.value as PaymentTermsBody['retention_basis'])}
                >
                  <option value="net">{t('cost_control.pay.basis_net', { defaultValue: 'The net amount' })}</option>
                  <option value="gross">
                    {t('cost_control.pay.basis_gross', { defaultValue: 'The amount with VAT' })}
                  </option>
                </select>
              </Field>
            </div>
            <Field label={t('cost_control.pay.terms_retention_event', { defaultValue: 'Paid back at' })}>
              <select
                className={INPUT}
                value={form.retention_release_event}
                disabled={disabled}
                onChange={(e) => set('retention_release_event', e.target.value)}
              >
                {RELEASE_EVENTS.map((ev) => (
                  <option key={ev} value={ev}>
                    {eventLabel(t, ev)}
                  </option>
                ))}
              </select>
            </Field>
          </section>

          <section className="space-y-3 border-t border-border-light pt-4">
            <Switch
              checked={form.warranty_enabled}
              onChange={(v) => set('warranty_enabled', v)}
              disabled={disabled}
              testId="terms-warranty-switch"
              label={t('cost_control.pay.terms_warranty', { defaultValue: 'Warranty retention on the final invoice' })}
              hint={t('cost_control.pay.terms_warranty_hint', {
                defaultValue: 'Without it, the final invoice releases everything and holds nothing back.',
              })}
            />
            {form.warranty_enabled && (
              <div className="grid grid-cols-2 gap-3 ps-7">
                <Field label={t('cost_control.pay.terms_retention_percent', { defaultValue: 'Rate (%)' })}>
                  <input
                    className={INPUT}
                    inputMode="decimal"
                    value={form.warranty_percent}
                    disabled={disabled}
                    onChange={(e) => set('warranty_percent', e.target.value)}
                  />
                </Field>
                <Field label={t('cost_control.pay.terms_warranty_months', { defaultValue: 'Defects period (months)' })}>
                  <input
                    className={INPUT}
                    inputMode="numeric"
                    value={form.warranty_period_months ?? ''}
                    disabled={disabled}
                    onChange={(e) => set('warranty_period_months', intOrNull(e.target.value))}
                  />
                </Field>
                <div className="col-span-2">
                  <Field label={t('cost_control.pay.terms_retention_event', { defaultValue: 'Paid back at' })}>
                    <select
                      className={INPUT}
                      value={form.warranty_release_event}
                      disabled={disabled}
                      onChange={(e) => set('warranty_release_event', e.target.value)}
                    >
                      {RELEASE_EVENTS.map((ev) => (
                        <option key={ev} value={ev}>
                          {eventLabel(t, ev)}
                        </option>
                      ))}
                    </select>
                  </Field>
                </div>
              </div>
            )}
          </section>

          <section className="space-y-3 border-t border-border-light pt-4">
            <Switch
              checked={form.discount_enabled}
              onChange={(v) => set('discount_enabled', v)}
              disabled={disabled}
              testId="terms-discount-switch"
              label={t('cost_control.pay.terms_discount', { defaultValue: 'Early payment discount' })}
              hint={t('cost_control.pay.terms_discount_hint', {
                defaultValue: 'Paid within the days agreed, the amount to pay drops by the rate.',
              })}
            />
            {form.discount_enabled && (
              <div className="grid grid-cols-3 gap-3 ps-7">
                <Field label={t('cost_control.pay.terms_retention_percent', { defaultValue: 'Rate (%)' })}>
                  <input
                    className={INPUT}
                    inputMode="decimal"
                    value={form.discount_percent}
                    disabled={disabled}
                    onChange={(e) => set('discount_percent', e.target.value)}
                  />
                </Field>
                <Field label={t('cost_control.pay.terms_discount_days', { defaultValue: 'Within (days)' })}>
                  <input
                    className={INPUT}
                    inputMode="numeric"
                    value={form.discount_days}
                    disabled={disabled}
                    onChange={(e) => set('discount_days', intOrNull(e.target.value) ?? 0)}
                  />
                </Field>
                <Field label={t('cost_control.pay.terms_discount_scope', { defaultValue: 'On' })}>
                  <select
                    className={INPUT}
                    value={form.discount_applies_to}
                    disabled={disabled}
                    onChange={(e) =>
                      set('discount_applies_to', e.target.value as PaymentTermsBody['discount_applies_to'])
                    }
                  >
                    <option value="both">{t('cost_control.pay.scope_both', { defaultValue: 'All invoices' })}</option>
                    <option value="interim">
                      {t('cost_control.pay.scope_interim', { defaultValue: 'Interim invoices' })}
                    </option>
                    <option value="final">{t('cost_control.pay.scope_final', { defaultValue: 'The final invoice' })}</option>
                  </select>
                </Field>
              </div>
            )}
          </section>

          <section className="space-y-3 border-t border-border-light pt-4">
            <Switch
              checked={form.rounding_enabled}
              onChange={(v) => set('rounding_enabled', v)}
              disabled={disabled}
              testId="terms-rounding-switch"
              label={t('cost_control.pay.terms_rounding', { defaultValue: 'Round interim releases down' })}
              hint={t('cost_control.pay.terms_rounding_hint', {
                defaultValue: 'The rest is not lost: the next cumulative or the final invoice pays it.',
              })}
            />
            {form.rounding_enabled && (
              <div className="ps-7">
                <Field
                  label={t('cost_control.pay.terms_rounding_step', {
                    defaultValue: 'To a multiple of ({{currency}})',
                    currency,
                  })}
                >
                  <input
                    className={INPUT}
                    inputMode="decimal"
                    value={form.rounding_step}
                    disabled={disabled}
                    onChange={(e) => set('rounding_step', e.target.value)}
                  />
                </Field>
              </div>
            )}
          </section>

          <div className="flex justify-end gap-2 border-t border-border-light pt-4">
            <Button type="button" variant="ghost" size="sm" onClick={onClose}>
              {canEdit
                ? t('cost_control.pay.cancel', { defaultValue: 'Cancel' })
                : t('cost_control.pay.close', { defaultValue: 'Close' })}
            </Button>
            {canEdit && (
              <Button type="submit" variant="primary" size="sm" loading={save.isPending} data-testid="terms-save">
                {t('cost_control.pay.terms_save', { defaultValue: 'Save terms' })}
              </Button>
            )}
          </div>
        </form>
      )}
      </div>
    </SideDrawer>
  );
}
