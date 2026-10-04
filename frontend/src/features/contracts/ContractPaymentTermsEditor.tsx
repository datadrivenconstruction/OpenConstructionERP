// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The payment terms card on a contract, editable while the contract is a draft.
 *
 * A contract starts from its country's usual terms, and the person who
 * accepted them at create time had no way to correct one afterwards: the card
 * was read-only and the only edit the drawer offered was the code. The server
 * takes every payment term on a draft and drops the "Default for <country>"
 * mark from any figure that changes; once the contract leaves draft the terms
 * lock with the other financial terms, so the control is offered only on a
 * draft.
 *
 * Only what the person changed is sent. A figure left as it was keeps its
 * mark, because the server reads an unsent field as untouched.
 */

import { useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { PenLine } from 'lucide-react';

import { Button } from '@/shared/ui';
import { getErrorMessage } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import {
  updateContract,
  type ContractItem,
  type ContractUpdatePayload,
  type ValuationInterval,
} from './api';
import {
  ContractPaymentTermsSummary,
  RELEASE_SPLIT_PRESETS,
  VALUATION_INTERVALS,
  paymentTermsOf,
  releaseSplitText,
  splitPresetId,
  valuationIntervalLabel,
} from './ContractPaymentTerms';

/** The select value for a split no preset describes: keep it as it is. */
const CURRENT_SPLIT = '__current__';

const inputCls =
  'h-9 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';

interface TermsForm {
  retention_percent: string;
  retention_cap_percent: string;
  retention_release_split: string;
  payment_period_days: string;
  valuation_interval: string;
  certificate_name: string;
}

function formFrom(contract: ContractItem): TermsForm {
  const terms = paymentTermsOf(contract);
  const split = terms.retention_release_split ?? null;
  return {
    retention_percent: String(contract.retention_percent ?? ''),
    retention_cap_percent: terms.retention_cap_percent ?? '',
    retention_release_split: splitPresetId(split) ?? (split && split.length > 0 ? CURRENT_SPLIT : ''),
    payment_period_days: terms.payment_period_days != null ? String(terms.payment_period_days) : '',
    valuation_interval: terms.valuation_interval ?? '',
    certificate_name: terms.certificate_name ?? '',
  };
}

function samePercent(a: string, b: string): boolean {
  if (a.trim() === '' || b.trim() === '') return a.trim() === b.trim();
  return Number(a) === Number(b);
}

function percentOk(value: string, required: boolean): boolean {
  if (value.trim() === '') return !required;
  const n = Number(value);
  return Number.isFinite(n) && n >= 0 && n <= 100;
}

function daysOk(value: string): boolean {
  if (value.trim() === '') return true;
  const n = Number(value);
  return Number.isInteger(n) && n >= 0 && n <= 365;
}

/**
 * The PATCH body for what changed between `before` and `after`, or null when
 * nothing did. A cleared field is sent as null, which the server reads as
 * "this contract states none" (no cap, no period), never as "use the default".
 */
function paymentTermsChanges(before: TermsForm, after: TermsForm): ContractUpdatePayload | null {
  const payload: ContractUpdatePayload = {};
  if (!samePercent(before.retention_percent, after.retention_percent)) {
    payload.retention_percent = Number(after.retention_percent);
  }
  if (!samePercent(before.retention_cap_percent, after.retention_cap_percent)) {
    const cap = after.retention_cap_percent.trim();
    payload.retention_cap_percent = cap === '' ? null : Number(cap);
  }
  if (
    before.retention_release_split !== after.retention_release_split &&
    after.retention_release_split !== CURRENT_SPLIT
  ) {
    payload.retention_release_split =
      RELEASE_SPLIT_PRESETS.find((p) => p.id === after.retention_release_split)?.split ?? null;
  }
  if (before.payment_period_days.trim() !== after.payment_period_days.trim()) {
    const days = after.payment_period_days.trim();
    payload.payment_period_days = days === '' ? null : Number(days);
  }
  if (before.valuation_interval !== after.valuation_interval) {
    payload.valuation_interval = (after.valuation_interval || null) as ValuationInterval | null;
  }
  if (before.certificate_name.trim() !== after.certificate_name.trim()) {
    payload.certificate_name = after.certificate_name.trim() || null;
  }
  return Object.keys(payload).length > 0 ? payload : null;
}

function Labelled({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="block">
      <span className="block text-xs uppercase tracking-wide text-content-tertiary">{label}</span>
      <span className="mt-0.5 block">{children}</span>
    </label>
  );
}

function PaymentTermsEditor({ contract, onDone }: { contract: ContractItem; onDone: () => void }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [before] = useState<TermsForm>(() => formFrom(contract));
  const [form, setForm] = useState<TermsForm>(before);
  const set = (field: keyof TermsForm, value: string) => setForm((prev) => ({ ...prev, [field]: value }));
  const currentSplit = paymentTermsOf(contract).retention_release_split ?? null;

  const valid =
    percentOk(form.retention_percent, true) &&
    percentOk(form.retention_cap_percent, false) &&
    daysOk(form.payment_period_days);
  const changes = valid ? paymentTermsChanges(before, form) : null;

  const saveMut = useMutation({
    mutationFn: (payload: ContractUpdatePayload) => updateContract(contract.id, payload),
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: ['contracts'] });
      addToast({
        type: 'success',
        title: t('contracts.payment_terms.saved', { defaultValue: 'Payment terms saved' }),
      });
      onDone();
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  return (
    <div data-testid="contract-payment-terms-editor">
      <div className="grid grid-cols-2 gap-x-4 gap-y-3">
        <Labelled label={t('contracts.payment_terms.retention_rate', { defaultValue: 'Retention rate' })}>
          <input
            type="number"
            step="0.1"
            min={0}
            max={100}
            value={form.retention_percent}
            onChange={(e) => set('retention_percent', e.target.value)}
            onFocus={(e) => e.currentTarget.select()}
            data-testid="edit-retention-percent"
            className={inputCls}
          />
        </Labelled>
        <Labelled
          label={t('contracts.payment_terms.retention_cap', {
            defaultValue: 'Retention cap (% of contract sum)',
          })}
        >
          <input
            type="number"
            step="0.1"
            min={0}
            max={100}
            value={form.retention_cap_percent}
            onChange={(e) => set('retention_cap_percent', e.target.value)}
            placeholder={t('contracts.payment_terms.no_cap', { defaultValue: 'No cap' })}
            data-testid="edit-retention-cap"
            className={inputCls}
          />
        </Labelled>
        <div className="col-span-2">
          <Labelled label={t('contracts.payment_terms.release_split', { defaultValue: 'Retention release' })}>
            <select
              value={form.retention_release_split}
              onChange={(e) => set('retention_release_split', e.target.value)}
              data-testid="edit-release-split"
              className={inputCls}
            >
              <option value="">{t('contracts.payment_terms.not_stated', { defaultValue: 'Not stated' })}</option>
              {before.retention_release_split === CURRENT_SPLIT && (
                <option value={CURRENT_SPLIT}>{releaseSplitText(t, currentSplit)}</option>
              )}
              {RELEASE_SPLIT_PRESETS.map((preset) => (
                <option key={preset.id} value={preset.id}>
                  {releaseSplitText(t, preset.split)}
                </option>
              ))}
            </select>
          </Labelled>
        </div>
        <Labelled
          label={t('contracts.payment_terms.payment_period_days', { defaultValue: 'Payment period (days)' })}
        >
          <input
            type="number"
            step="1"
            min={0}
            max={365}
            value={form.payment_period_days}
            onChange={(e) => set('payment_period_days', e.target.value)}
            data-testid="edit-payment-days"
            className={inputCls}
          />
        </Labelled>
        <Labelled
          label={t('contracts.payment_terms.valuation_interval', { defaultValue: 'Valuation interval' })}
        >
          <select
            value={form.valuation_interval}
            onChange={(e) => set('valuation_interval', e.target.value)}
            data-testid="edit-valuation-interval"
            className={inputCls}
          >
            <option value="">{t('contracts.payment_terms.not_stated', { defaultValue: 'Not stated' })}</option>
            {VALUATION_INTERVALS.map((interval) => (
              <option key={interval} value={interval}>
                {valuationIntervalLabel(t, interval)}
              </option>
            ))}
          </select>
        </Labelled>
        <div className="col-span-2">
          <Labelled
            label={t('contracts.payment_terms.certificate_name', { defaultValue: 'Interim certificate' })}
          >
            <input
              value={form.certificate_name}
              onChange={(e) => set('certificate_name', e.target.value)}
              maxLength={200}
              data-testid="edit-certificate-name"
              className={inputCls}
            />
          </Labelled>
        </div>
      </div>
      {!valid && (
        <p className="mt-2 text-xs text-semantic-error" data-testid="payment-terms-invalid">
          {t('contracts.payment_terms.invalid', {
            defaultValue:
              'The retention rate and the cap are percentages from 0 to 100, and the payment period is a whole number of days up to 365.',
          })}
        </p>
      )}
      <div className="mt-3 flex justify-end gap-2">
        <Button variant="ghost" size="sm" onClick={onDone} disabled={saveMut.isPending}>
          {t('common.cancel', { defaultValue: 'Cancel' })}
        </Button>
        <Button
          size="sm"
          onClick={() => changes && saveMut.mutate(changes)}
          loading={saveMut.isPending}
          disabled={!changes}
          data-testid="payment-terms-save"
        >
          {t('common.save', { defaultValue: 'Save' })}
        </Button>
      </div>
    </div>
  );
}

/**
 * The payment terms on a contract, with an edit control on a draft. The
 * summary itself stays free of queries, so it renders on its own anywhere.
 */
export function ContractPaymentTermsCard({ contract }: { contract: ContractItem }) {
  const { t } = useTranslation();
  const [editing, setEditing] = useState(false);
  const draft = contract.status === 'draft';

  if (editing && draft) {
    return <PaymentTermsEditor key={contract.id} contract={contract} onDone={() => setEditing(false)} />;
  }
  return (
    <div>
      {draft && (
        <div className="-mt-1 mb-2 flex justify-end">
          <button
            type="button"
            data-testid="payment-terms-edit"
            onClick={() => setEditing(true)}
            className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-xs text-content-secondary hover:bg-surface-secondary hover:text-content-primary"
          >
            <PenLine size={12} />
            {t('contracts.payment_terms.edit', { defaultValue: 'Edit payment terms' })}
          </button>
        </div>
      )}
      <ContractPaymentTermsSummary contract={contract} />
    </div>
  );
}
