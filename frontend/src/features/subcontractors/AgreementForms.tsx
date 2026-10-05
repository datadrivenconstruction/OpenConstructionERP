// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The subcontract's own paperwork on the Subcontractors page: drawing up an
 * agreement, signing it, and entering a payment application against it.
 *
 * Until these existed an agreement and its payment applications could be made
 * only through the API or the contracts module, so a site team working from
 * this page had nothing to press. The money rules stay on the server: signing
 * commits the agreement value to the budget, the server works out retention
 * and net on a payment application, and approval and payment go through the
 * actions already on the payments list.
 */

import { useState, type FocusEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { FileSignature, Loader2, Plus } from 'lucide-react';
import { Button, WideModal, WideModalField, WideModalSection } from '@/shared/ui';
import { MoneyDisplay } from '@/shared/ui/MoneyDisplay';
import { useToastStore } from '@/stores/useToastStore';
import { projectsApi } from '@/features/projects/api';
import { listContracts, type ContractItem, type CountryDefaultField } from '@/features/contracts/api';
import {
  DefaultHint,
  paymentTermsOf,
  useContractCountryDefaults,
} from '@/features/contracts/ContractPaymentTerms';
import {
  createAgreement,
  submitPaymentApplication,
  updateAgreement,
  type Agreement,
} from './api';
import { gateErrorMessage } from './complianceReasons';

const inputCls =
  'h-9 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';

/**
 * Select the whole value when a number field takes focus, so what is typed
 * replaces the default instead of being appended to it. Typing 5 over a
 * prefilled 5 used to give 55.
 */
export function selectOnFocus(e: FocusEvent<HTMLInputElement>): void {
  e.currentTarget.select();
}

function toNum(value: string | number | null | undefined): number {
  const n = Number(value);
  return Number.isFinite(n) ? n : 0;
}

function round2(n: number): number {
  return Math.round(n * 100) / 100;
}

/**
 * The retention an agreement takes from the contract it is linked to.
 *
 * A contract may hold its rate until its cap stops it (FIDIC: 10% until 5%
 * of the sum is held). An agreement holds every payment at one rate and has
 * no cap, so copying the 10% would hold twice the limit by the end of the
 * job. Where the contract states a cap below its rate, the agreement takes
 * the cap.
 */
export function agreementRetentionFrom(
  contract: Pick<ContractItem, 'retention_percent' | 'terms'>,
): string {
  const rate = toNum(contract.retention_percent);
  const capRaw = paymentTermsOf(contract).retention_cap_percent;
  const cap = capRaw == null || capRaw === '' ? null : Number(capRaw);
  if (cap !== null && Number.isFinite(cap) && cap >= 0 && cap < rate) return String(cap);
  return String(rate);
}

/* ─── New agreement ─── */

interface AgreementFormState {
  title: string;
  project_id: string;
  total_value: string;
  currency: string;
  retention_percent: string;
  start_date: string;
  end_date: string;
  contract_id: string;
}

export function AgreementFormModal({
  subcontractorId,
  onClose,
}: {
  subcontractorId: string;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const projectsQ = useQuery({ queryKey: ['projects', 'list'], queryFn: () => projectsApi.list() });
  const projects = projectsQ.data ?? [];
  const [form, setForm] = useState<AgreementFormState>({
    title: '',
    project_id: '',
    total_value: '',
    currency: '',
    // Empty until typed: an untouched field is left to the server, which
    // starts the agreement from the project's country's usual retention.
    retention_percent: '',
    start_date: '',
    end_date: '',
    contract_id: '',
  });
  const set = <K extends keyof AgreementFormState>(key: K, value: AgreementFormState[K]) =>
    setForm((prev) => ({ ...prev, [key]: value }));
  const [retentionTouched, setRetentionTouched] = useState(false);

  const projectId = form.project_id || projects[0]?.id || '';
  const currency = form.currency || projects.find((p) => p.id === projectId)?.currency || '';

  // The project's subcontracts in the contracts module. Linking one says the
  // agreement and that contract are the same subcontract, so the budget
  // commitment is counted once.
  const contractsQ = useQuery({
    queryKey: ['contracts', 'list', projectId, 'subcontractor'],
    queryFn: () => listContracts({ project_id: projectId, counterparty_type: 'subcontractor', limit: 200 }),
    enabled: Boolean(projectId),
  });
  const subcontracts = contractsQ.data?.items ?? [];

  // The retention a subcontract in this country usually carries, shown until
  // the person types or links a contract. It is shown, not sent: the server
  // applies the same figure and records it as the country's default. An
  // agreement holds every payment at one rate with no ceiling, so where the
  // country's rate runs above its cap (FIDIC: 10% until 5% is held) the
  // server starts the agreement from the cap and says which figure it is.
  const defaultsQ = useContractCountryDefaults(projectId, 'subcontractor');
  const knownDefaults = defaultsQ.data?.has_defaults ? defaultsQ.data : null;
  const countryRetention =
    knownDefaults?.subcontract_retention_percent ?? knownDefaults?.values.retention_percent ?? '';
  const countryRetentionField: CountryDefaultField =
    knownDefaults?.subcontract_retention_from ?? 'retention_percent';
  const retentionValue = retentionTouched ? form.retention_percent : countryRetention;

  const linkContract = (id: string) => {
    const picked = subcontracts.find((c) => c.id === id);
    // Take the figures from the contract where nothing was typed yet. The
    // contract's rate may run until its cap stops it; the agreement has no
    // cap, so it takes the lower of the two and never holds past the limit.
    const pickedRetention = picked ? agreementRetentionFrom(picked) : '';
    setForm((prev) => ({
      ...prev,
      contract_id: id,
      title: prev.title || picked?.title || '',
      total_value: prev.total_value || (picked ? String(picked.total_value ?? '') : ''),
      currency: prev.currency || picked?.currency || '',
      retention_percent: picked ? pickedRetention : prev.retention_percent,
    }));
    if (picked) setRetentionTouched(true);
  };

  const mutation = useMutation({
    mutationFn: () =>
      createAgreement({
        subcontractor_id: subcontractorId,
        project_id: projectId,
        title: form.title.trim(),
        total_value: String(toNum(form.total_value)),
        currency: currency.trim().toUpperCase(),
        retention_percent:
          retentionTouched && form.retention_percent.trim() !== ''
            ? String(toNum(form.retention_percent))
            : undefined,
        start_date: form.start_date || undefined,
        end_date: form.end_date || undefined,
        contract_id: form.contract_id || undefined,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['subcontractors'] });
      addToast({ type: 'success', title: t('subcontractors.agreement_created') });
      onClose();
    },
    onError: (err) => addToast({ type: 'error', title: gateErrorMessage(err, t) }),
  });

  const retention = toNum(retentionValue);
  // With no usual figure for the country the rate has to come from the
  // person. Left blank, the server would store its platform fallback, and a
  // blank read as "no retention" would then withhold 5% from every payment.
  // While the defaults are loading, or could not be read, a blank is left to
  // the server, which applies the same table this form would have shown.
  const retentionRequired = defaultsQ.isSuccess && retentionValue.trim() === '';
  const invalid =
    !form.title.trim() ||
    !projectId ||
    toNum(form.total_value) <= 0 ||
    retention < 0 ||
    retention > 100 ||
    retentionRequired;

  return (
    <WideModal
      open
      onClose={onClose}
      busy={mutation.isPending}
      title={t('subcontractors.new_agreement')}
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={mutation.isPending}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button
            variant="primary"
            onClick={() => mutation.mutate()}
            loading={mutation.isPending}
            disabled={invalid}
            icon={mutation.isPending ? <Loader2 size={14} /> : <Plus size={14} />}
          >
            {t('common.create', { defaultValue: 'Create' })}
          </Button>
        </>
      }
    >
      <WideModalSection title={t('subcontractors.section_agreement')} columns={2}>
        <WideModalField label={t('subcontractors.agreement_title')} required span={2}>
          <input
            value={form.title}
            onChange={(e) => set('title', e.target.value)}
            className={inputCls}
            data-testid="agreement-title"
          />
        </WideModalField>
        <WideModalField label={t('subcontractors.agreement_project')} required span={2}>
          <select
            value={projectId}
            onChange={(e) => set('project_id', e.target.value)}
            className={inputCls}
            data-testid="agreement-project"
          >
            {projects.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </WideModalField>
        <WideModalField
          label={t('subcontractors.agreement_contract')}
          hint={t('subcontractors.agreement_contract_hint')}
          span={2}
        >
          <select
            value={form.contract_id}
            onChange={(e) => linkContract(e.target.value)}
            className={inputCls}
            data-testid="agreement-contract"
          >
            <option value="">{t('subcontractors.agreement_contract_none')}</option>
            {subcontracts.map((c) => (
              <option key={c.id} value={c.id}>
                {c.code} {c.title}
              </option>
            ))}
          </select>
        </WideModalField>
        <WideModalField label={t('subcontractors.agreement_value')} required>
          <input
            type="number"
            min="0"
            step="0.01"
            value={form.total_value}
            onChange={(e) => set('total_value', e.target.value)}
            onFocus={selectOnFocus}
            className={inputCls}
            data-testid="agreement-value"
          />
        </WideModalField>
        <WideModalField label={t('subcontractors.agreement_currency')}>
          <input
            value={currency}
            onChange={(e) => set('currency', e.target.value)}
            className={inputCls}
            maxLength={3}
          />
        </WideModalField>
        <WideModalField
          label={t('subcontractors.agreement_retention')}
          hint={t('subcontractors.agreement_retention_hint')}
          required={defaultsQ.isSuccess && countryRetention === ''}
        >
          <input
            type="number"
            min="0"
            max="100"
            step="0.1"
            value={retentionValue}
            onChange={(e) => {
              set('retention_percent', e.target.value);
              setRetentionTouched(true);
            }}
            onFocus={selectOnFocus}
            className={inputCls}
            data-testid="agreement-retention"
          />
          {!retentionTouched && knownDefaults && countryRetention !== '' && (
            <DefaultHint
              field="retention_percent"
              noteField={countryRetentionField}
              country={knownDefaults.country_code}
              source={knownDefaults.sources[countryRetentionField]}
            />
          )}
          {retentionRequired && (
            <p className="mt-1 text-xs text-content-secondary" data-testid="agreement-retention-required">
              {t('subcontractors.agreement_retention_required', {
                defaultValue: 'Enter the retention this agreement states (0 if none).',
              })}
            </p>
          )}
        </WideModalField>
        <div />
        <WideModalField label={t('subcontractors.agreement_start')}>
          <input
            type="date"
            value={form.start_date}
            onChange={(e) => set('start_date', e.target.value)}
            className={inputCls}
          />
        </WideModalField>
        <WideModalField label={t('subcontractors.agreement_end')}>
          <input
            type="date"
            value={form.end_date}
            onChange={(e) => set('end_date', e.target.value)}
            className={inputCls}
          />
        </WideModalField>
      </WideModalSection>
    </WideModal>
  );
}

/* ─── Sign a draft agreement ─── */

export function SignAgreementButton({ agreement }: { agreement: Agreement }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const mutation = useMutation({
    mutationFn: () => updateAgreement(agreement.id, { status: 'active' }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['subcontractors'] });
      qc.invalidateQueries({ queryKey: ['finance'] });
      addToast({ type: 'success', title: t('subcontractors.agreement_signed') });
    },
    onError: (err) => addToast({ type: 'error', title: gateErrorMessage(err, t) }),
  });
  if (agreement.status !== 'draft') return null;
  return (
    <Button
      size="sm"
      variant="secondary"
      onClick={() => mutation.mutate()}
      loading={mutation.isPending}
      icon={<FileSignature size={13} />}
      title={t('subcontractors.sign_agreement_hint')}
    >
      {t('subcontractors.sign_agreement')}
    </Button>
  );
}

/* ─── New payment application ─── */

export function PaymentApplicationFormModal({
  agreement,
  onClose,
}: {
  agreement: Agreement;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [gross, setGross] = useState('');
  const [periodStart, setPeriodStart] = useState('');
  const [periodEnd, setPeriodEnd] = useState('');

  // What the server will book, shown before it is sent: retention at the
  // agreement's rate on the gross, and the net after it.
  const grossNum = toNum(gross);
  const retention = round2((grossNum * toNum(agreement.retention_percent)) / 100);
  const net = round2(grossNum - retention);

  const mutation = useMutation({
    mutationFn: () =>
      submitPaymentApplication({
        agreement_id: agreement.id,
        gross_amount: String(grossNum),
        period_start: periodStart || undefined,
        period_end: periodEnd || undefined,
        currency: agreement.currency || undefined,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['subcontractors'] });
      addToast({ type: 'success', title: t('subcontractors.pay_app_created') });
      onClose();
    },
    onError: (err) => addToast({ type: 'error', title: gateErrorMessage(err, t) }),
  });

  return (
    <WideModal
      open
      onClose={onClose}
      busy={mutation.isPending}
      title={t('subcontractors.new_pay_app_title', { title: agreement.title })}
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={mutation.isPending}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button
            variant="primary"
            onClick={() => mutation.mutate()}
            loading={mutation.isPending}
            disabled={grossNum <= 0}
            icon={mutation.isPending ? <Loader2 size={14} /> : <Plus size={14} />}
          >
            {t('subcontractors.submit_pay_app')}
          </Button>
        </>
      }
    >
      <WideModalSection title={t('subcontractors.section_pay_app')} columns={2}>
        <WideModalField label={t('subcontractors.pay_app_period_start')}>
          <input
            type="date"
            value={periodStart}
            onChange={(e) => setPeriodStart(e.target.value)}
            className={inputCls}
          />
        </WideModalField>
        <WideModalField label={t('subcontractors.pay_app_period_end')}>
          <input
            type="date"
            value={periodEnd}
            onChange={(e) => setPeriodEnd(e.target.value)}
            className={inputCls}
          />
        </WideModalField>
        <WideModalField
          label={t('subcontractors.pay_app_gross')}
          hint={t('subcontractors.pay_app_gross_hint')}
          required
          span={2}
        >
          <input
            type="number"
            min="0"
            step="0.01"
            value={gross}
            onChange={(e) => setGross(e.target.value)}
            onFocus={selectOnFocus}
            className={inputCls}
            data-testid="pay-app-gross"
          />
        </WideModalField>
      </WideModalSection>
      <dl className="mt-2 space-y-1 text-sm" data-testid="pay-app-preview">
        <div className="flex justify-between">
          <dt className="text-content-secondary">
            {t('subcontractors.pay_app_retention_at', { percent: toNum(agreement.retention_percent) })}
          </dt>
          <dd>
            <MoneyDisplay amount={retention} currency={agreement.currency || undefined} />
          </dd>
        </div>
        <div className="flex justify-between font-semibold">
          <dt>{t('subcontractors.pay_app_net_due')}</dt>
          <dd>
            <MoneyDisplay amount={net} currency={agreement.currency || undefined} />
          </dd>
        </div>
      </dl>
    </WideModal>
  );
}
