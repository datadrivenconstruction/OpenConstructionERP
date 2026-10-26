// DDC-CWICR-OE: DataDrivenConstruction​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Create dialog for a guarantee. Type-specific fields only appear for the type
 * they belong to; percent, claim period, defects period and recovery percent are
 * prefilled from the country defaults for the chosen type until the user edits
 * the field, and the defaults' origin is shown as a hint.
 */
import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { Button, WideModal, WideModalField, WideModalSection } from '@/shared/ui';
import { apiGet } from '@/shared/lib/api';
import {
  GUARANTEE_DIRECTIONS,
  GUARANTEE_TYPES,
  compactBody,
  useFacilities,
  useGuaranteeDefaults,
  type GuaranteeCreate,
  type GuaranteeDirection,
  type GuaranteeType,
} from './api';
import { directionLabel, typeLabel } from './labels';
import { inputCls, selectCls, textareaCls } from './ui';

interface ProjectLite {
  country_code?: string | null;
  country?: string | null;
  currency?: string | null;
}

interface FormState {
  reference: string;
  guarantee_type: GuaranteeType;
  direction: GuaranteeDirection;
  issuer_bank: string;
  bank_reference: string;
  beneficiary: string;
  applicant: string;
  amount: string;
  currency: string;
  percent_of_contract: string;
  contract_value: string;
  issue_date: string;
  expiry_date: string;
  auto_extend: boolean;
  extension_months: string;
  claim_period_days: string;
  defects_period_months: string;
  advance_amount: string;
  advance_recovery_pct: string;
  replaces_cash_retention: boolean;
  commission_rate_pct: string;
  form_code: string;
  contract_id: string;
  subcontractor_id: string;
  tender_id: string;
  bid_id: string;
  facility_id: string;
  notes: string;
}

const EMPTY: FormState = {
  reference: '',
  guarantee_type: 'performance_bond',
  direction: 'given',
  issuer_bank: '',
  bank_reference: '',
  beneficiary: '',
  applicant: '',
  amount: '',
  currency: '',
  percent_of_contract: '',
  contract_value: '',
  issue_date: '',
  expiry_date: '',
  auto_extend: false,
  extension_months: '',
  claim_period_days: '',
  defects_period_months: '',
  advance_amount: '',
  advance_recovery_pct: '',
  replaces_cash_retention: false,
  commission_rate_pct: '',
  form_code: '',
  contract_id: '',
  subcontractor_id: '',
  tender_id: '',
  bid_id: '',
  facility_id: '',
  notes: '',
};

const AMOUNT_RE = /^\d+(\.\d+)?$/;

function toInt(v: string): number | undefined {
  if (v === '') return undefined;
  const n = Number.parseInt(v, 10);
  return Number.isFinite(n) ? n : undefined;
}

export function GuaranteeFormModal({
  projectId,
  isPending,
  onClose,
  onSubmit,
}: {
  projectId: string;
  isPending: boolean;
  onClose: () => void;
  onSubmit: (body: GuaranteeCreate) => void;
}) {
  const { t } = useTranslation();
  const [form, setForm] = useState<FormState>(EMPTY);
  const touched = useRef(new Set<keyof FormState>());

  const projectQ = useQuery({
    queryKey: ['guarantees', 'project-lite', projectId],
    queryFn: () => apiGet<ProjectLite>(`/v1/projects/${projectId}`),
    enabled: !!projectId,
    staleTime: 5 * 60 * 1000,
  });
  const country = (projectQ.data?.country_code || projectQ.data?.country || '').trim().toUpperCase();
  const defaultsQ = useGuaranteeDefaults(country);
  const facilitiesQ = useFacilities();

  const set = <K extends keyof FormState>(key: K, value: FormState[K]) => {
    touched.current.add(key);
    setForm((f) => ({ ...f, [key]: value }));
  };

  // Currency follows the project until the user picks one.
  useEffect(() => {
    const c = projectQ.data?.currency;
    if (c && !touched.current.has('currency')) setForm((f) => ({ ...f, currency: c }));
  }, [projectQ.data]);

  // Country defaults for the chosen type, applied to fields the user has not touched.
  const entry = defaultsQ.data?.types?.[form.guarantee_type];
  useEffect(() => {
    if (!entry) return;
    const patch: Partial<FormState> = {};
    const fill = (key: keyof FormState, v: string | number | null | undefined) => {
      if (v !== null && v !== undefined && !touched.current.has(key)) (patch as Record<string, unknown>)[key] = String(v);
    };
    fill('percent_of_contract', entry.percent_of_contract);
    fill('claim_period_days', entry.claim_period_days);
    fill('defects_period_months', entry.defects_period_months);
    fill('advance_recovery_pct', entry.advance_recovery_pct);
    fill('form_code', entry.form_code);
    if (entry.replaces_cash_retention !== null && entry.replaces_cash_retention !== undefined && !touched.current.has('replaces_cash_retention')) {
      patch.replaces_cash_retention = entry.replaces_cash_retention;
    }
    if (Object.keys(patch).length) setForm((f) => ({ ...f, ...patch }));
  }, [entry]);

  const type = form.guarantee_type;
  const refMissing = form.reference.trim() === '';
  const amountBad = !AMOUNT_RE.test(form.amount.trim());
  const currencyBad = !/^[A-Za-z]{3}$/.test(form.currency.trim());
  const canSubmit = !refMissing && !amountBad && !currencyBad;

  const submit = () => {
    if (!canSubmit) return;
    const body: GuaranteeCreate = {
      ...compactBody({
        issuer_bank: form.issuer_bank.trim(),
        bank_reference: form.bank_reference.trim(),
        beneficiary: form.beneficiary.trim(),
        applicant: form.applicant.trim(),
        percent_of_contract: form.percent_of_contract.trim(),
        contract_value: form.contract_value.trim(),
        issue_date: form.issue_date,
        expiry_date: form.expiry_date,
        extension_months: toInt(form.extension_months),
        claim_period_days: toInt(form.claim_period_days),
        defects_period_months: toInt(form.defects_period_months),
        commission_rate_pct: form.commission_rate_pct.trim(),
        form_code: form.form_code.trim(),
        contract_id: form.contract_id.trim(),
        facility_id: form.facility_id,
        notes: form.notes.trim(),
        ...(type === 'advance_payment'
          ? { advance_amount: form.advance_amount.trim(), advance_recovery_pct: form.advance_recovery_pct.trim() }
          : {}),
        ...(type === 'bid_bond' ? { tender_id: form.tender_id.trim(), bid_id: form.bid_id.trim() } : {}),
        ...(form.direction === 'received' ? { subcontractor_id: form.subcontractor_id.trim() } : {}),
      }),
      reference: form.reference.trim(),
      guarantee_type: type,
      direction: form.direction,
      amount: form.amount.trim(),
      currency: form.currency.trim().toUpperCase(),
      auto_extend: form.auto_extend,
      ...(type === 'retention_bond' ? { replaces_cash_retention: form.replaces_cash_retention } : {}),
    };
    onSubmit(body);
  };

  return (
    <WideModal
      open
      onClose={onClose}
      busy={isPending}
      size="xl"
      title={t('guarantees.modal_new', { defaultValue: 'New guarantee' })}
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={isPending}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button variant="primary" onClick={submit} disabled={!canSubmit || isPending} loading={isPending}>
            {t('guarantees.create', { defaultValue: 'Create guarantee' })}
          </Button>
        </>
      }
    >
      <WideModalSection title={t('guarantees.section_basics', { defaultValue: 'Guarantee' })}>
        <WideModalField label={t('guarantees.field_reference', { defaultValue: 'Reference' })} required>
          <input className={inputCls} value={form.reference} onChange={(e) => set('reference', e.target.value)} autoFocus />
        </WideModalField>
        <WideModalField label={t('guarantees.field_type', { defaultValue: 'Type' })}>
          <select className={selectCls} value={type} onChange={(e) => set('guarantee_type', e.target.value as GuaranteeType)}>
            {GUARANTEE_TYPES.map((v) => (
              <option key={v} value={v}>{typeLabel(t, v)}</option>
            ))}
          </select>
        </WideModalField>
        <WideModalField label={t('guarantees.field_direction', { defaultValue: 'Direction' })}>
          <select className={selectCls} value={form.direction} onChange={(e) => set('direction', e.target.value as GuaranteeDirection)}>
            {GUARANTEE_DIRECTIONS.map((v) => (
              <option key={v} value={v}>{directionLabel(t, v)}</option>
            ))}
          </select>
        </WideModalField>
        <WideModalField label={t('guarantees.field_amount', { defaultValue: 'Amount' })} required>
          <input className={inputCls} inputMode="decimal" value={form.amount} onChange={(e) => set('amount', e.target.value)} />
        </WideModalField>
        <WideModalField label={t('guarantees.field_currency', { defaultValue: 'Currency' })} required hint={t('guarantees.field_currency_hint', { defaultValue: 'Three-letter code, e.g. EUR' })}>
          <input className={inputCls} maxLength={3} value={form.currency} onChange={(e) => set('currency', e.target.value)} />
        </WideModalField>
        <WideModalField label={t('guarantees.field_form_code', { defaultValue: 'Standard form' })}>
          <input className={inputCls} value={form.form_code} onChange={(e) => set('form_code', e.target.value)} />
        </WideModalField>
      </WideModalSection>

      {entry && (defaultsQ.data?.origin || entry.source) && (
        <p className="text-2xs text-content-tertiary" data-testid="guarantees-defaults-hint">
          {t('guarantees.defaults_hint', {
            defaultValue: 'Prefilled from {{origin}} defaults. Source: {{source}}.',
            origin: defaultsQ.data?.origin ?? '',
            source: entry.source ?? '',
          })}
          {entry.note ? ` ${entry.note}` : ''}
        </p>
      )}

      <WideModalSection title={t('guarantees.section_parties', { defaultValue: 'Parties' })}>
        <WideModalField label={t('guarantees.field_issuer_bank', { defaultValue: 'Issuing bank' })}>
          <input className={inputCls} value={form.issuer_bank} onChange={(e) => set('issuer_bank', e.target.value)} />
        </WideModalField>
        <WideModalField label={t('guarantees.field_bank_reference', { defaultValue: 'Bank reference' })}>
          <input className={inputCls} value={form.bank_reference} onChange={(e) => set('bank_reference', e.target.value)} />
        </WideModalField>
        <WideModalField label={t('guarantees.field_beneficiary', { defaultValue: 'Beneficiary' })}>
          <input className={inputCls} value={form.beneficiary} onChange={(e) => set('beneficiary', e.target.value)} />
        </WideModalField>
        <WideModalField label={t('guarantees.field_applicant', { defaultValue: 'Applicant' })}>
          <input className={inputCls} value={form.applicant} onChange={(e) => set('applicant', e.target.value)} />
        </WideModalField>
        <WideModalField label={t('guarantees.field_facility', { defaultValue: 'Bank credit line' })}>
          <select className={selectCls} value={form.facility_id} onChange={(e) => set('facility_id', e.target.value)}>
            <option value="">{t('guarantees.no_facility', { defaultValue: 'None' })}</option>
            {(facilitiesQ.data ?? []).map((f) => (
              <option key={f.id} value={f.id}>{`${f.name} (${f.bank_name}, ${f.currency})`}</option>
            ))}
          </select>
        </WideModalField>
        <WideModalField label={t('guarantees.field_commission', { defaultValue: 'Commission rate % p.a.' })}>
          <input className={inputCls} inputMode="decimal" value={form.commission_rate_pct} onChange={(e) => set('commission_rate_pct', e.target.value)} />
        </WideModalField>
      </WideModalSection>

      <WideModalSection title={t('guarantees.section_terms', { defaultValue: 'Terms' })}>
        <WideModalField label={t('guarantees.field_issue_date', { defaultValue: 'Issue date' })}>
          <input type="date" className={inputCls} value={form.issue_date} onChange={(e) => set('issue_date', e.target.value)} />
        </WideModalField>
        <WideModalField label={t('guarantees.field_expiry_date', { defaultValue: 'Expiry date' })}>
          <input type="date" className={inputCls} value={form.expiry_date} onChange={(e) => set('expiry_date', e.target.value)} />
        </WideModalField>
        <WideModalField label={t('guarantees.field_percent', { defaultValue: '% of contract' })}>
          <input className={inputCls} inputMode="decimal" value={form.percent_of_contract} onChange={(e) => set('percent_of_contract', e.target.value)} />
        </WideModalField>
        <WideModalField label={t('guarantees.field_contract_value', { defaultValue: 'Contract value' })}>
          <input className={inputCls} inputMode="decimal" value={form.contract_value} onChange={(e) => set('contract_value', e.target.value)} />
        </WideModalField>
        <WideModalField label={t('guarantees.field_claim_period', { defaultValue: 'Claim period (days)' })}>
          <input className={inputCls} inputMode="numeric" value={form.claim_period_days} onChange={(e) => set('claim_period_days', e.target.value)} />
        </WideModalField>
        <WideModalField label={t('guarantees.field_defects_period', { defaultValue: 'Defects period (months)' })}>
          <input className={inputCls} inputMode="numeric" value={form.defects_period_months} onChange={(e) => set('defects_period_months', e.target.value)} />
        </WideModalField>
        <WideModalField label={t('guarantees.field_auto_extend', { defaultValue: 'Auto-extend' })}>
          <label className="flex h-10 items-center gap-2 text-sm text-content-primary">
            <input type="checkbox" checked={form.auto_extend} onChange={(e) => set('auto_extend', e.target.checked)} />
            {t('guarantees.field_auto_extend_label', { defaultValue: 'Renews automatically unless cancelled' })}
          </label>
        </WideModalField>
        {form.auto_extend && (
          <WideModalField label={t('guarantees.field_extension_months', { defaultValue: 'Extension (months)' })}>
            <input className={inputCls} inputMode="numeric" value={form.extension_months} onChange={(e) => set('extension_months', e.target.value)} />
          </WideModalField>
        )}
      </WideModalSection>

      <WideModalSection title={t('guarantees.section_links', { defaultValue: 'Links and type-specific fields' })}>
        <WideModalField label={t('guarantees.field_contract_id', { defaultValue: 'Contract ID' })}>
          <input className={inputCls} value={form.contract_id} onChange={(e) => set('contract_id', e.target.value)} />
        </WideModalField>
        {type === 'bid_bond' && (
          <>
            <WideModalField label={t('guarantees.field_tender_id', { defaultValue: 'Tender ID' })}>
              <input className={inputCls} value={form.tender_id} onChange={(e) => set('tender_id', e.target.value)} />
            </WideModalField>
            <WideModalField label={t('guarantees.field_bid_id', { defaultValue: 'Bid ID' })}>
              <input className={inputCls} value={form.bid_id} onChange={(e) => set('bid_id', e.target.value)} />
            </WideModalField>
          </>
        )}
        {form.direction === 'received' && (
          <WideModalField label={t('guarantees.field_subcontractor_id', { defaultValue: 'Subcontractor ID' })}>
            <input className={inputCls} value={form.subcontractor_id} onChange={(e) => set('subcontractor_id', e.target.value)} />
          </WideModalField>
        )}
        {type === 'advance_payment' && (
          <>
            <WideModalField label={t('guarantees.field_advance_amount', { defaultValue: 'Advance amount' })}>
              <input className={inputCls} inputMode="decimal" value={form.advance_amount} onChange={(e) => set('advance_amount', e.target.value)} />
            </WideModalField>
            <WideModalField label={t('guarantees.field_advance_recovery_pct', { defaultValue: 'Recovery % per claim' })}>
              <input className={inputCls} inputMode="decimal" value={form.advance_recovery_pct} onChange={(e) => set('advance_recovery_pct', e.target.value)} />
            </WideModalField>
          </>
        )}
        {type === 'retention_bond' && (
          <WideModalField label={t('guarantees.field_replaces_retention', { defaultValue: 'Replaces cash retention' })}>
            <label className="flex h-10 items-center gap-2 text-sm text-content-primary">
              <input type="checkbox" checked={form.replaces_cash_retention} onChange={(e) => set('replaces_cash_retention', e.target.checked)} />
              {t('guarantees.field_replaces_retention_label', { defaultValue: 'No cash is withheld while this bond is live' })}
            </label>
          </WideModalField>
        )}
        <WideModalField label={t('guarantees.field_notes', { defaultValue: 'Notes' })} span={3}>
          <textarea className={textareaCls} rows={3} value={form.notes} onChange={(e) => set('notes', e.target.value)} />
        </WideModalField>
      </WideModalSection>
    </WideModal>
  );
}
