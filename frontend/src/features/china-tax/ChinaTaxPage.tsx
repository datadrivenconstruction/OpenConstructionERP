// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * China tax page: the project's tax profile (method, election, edition,
 * regions), the GB/T 50500 tender summary, the cn_vat findings and a 预缴
 * calculator. Shown only where the China pack is installed.
 */

import { useEffect, useState } from 'react';
import type { ChangeEvent, ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { AlertTriangle, Calculator, Landmark, Receipt, ShieldCheck } from 'lucide-react';

import { ApiError, getErrorMessage } from '@/shared/lib/api';
import { Button } from '@/shared/ui/Button';
import { Card } from '@/shared/ui/Card';
import { CollapsibleSection } from '@/shared/ui/CollapsibleSection';
import { EmptyState } from '@/shared/ui/EmptyState';
import { MoneyDisplay } from '@/shared/ui/MoneyDisplay';
import { PageHeader } from '@/shared/ui/PageHeader';
import { StatCard } from '@/shared/ui/StatCard';
import { useProjectContextStore } from '@/stores/useProjectContextStore';

import {
  computePrepayment,
  fetchProfile,
  fetchProjectCheck,
  findingKey,
  saveProfile,
  toProfileFields,
} from './api';
import { ProvincialFeePanel } from './ProvincialFeePanel';
import type { Finding, PrepaymentPeriodInput, PrepaymentResult, ProfileFields, TaxProfile } from './api';

const INPUT = 'w-full rounded-md border border-border bg-surface-primary px-2 py-1.5 text-sm text-content-primary';

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="flex flex-col gap-1 text-xs text-content-secondary">
      <span>{label}</span>
      {children}
    </label>
  );
}

function FindingRow({ finding }: { finding: Finding }) {
  const { t } = useTranslation();
  const error = finding.severity === 'error';
  const params = Object.fromEntries(Object.entries(finding.details ?? {}).map(([k, v]) => [k, String(v)]));
  return (
    <li className="flex items-start gap-2 py-2 text-sm">
      <AlertTriangle size={14} className={error ? 'mt-0.5 text-semantic-error' : 'mt-0.5 text-semantic-warning'} />
      <div>
        <div className="text-content-primary">
          {t(findingKey(finding.rule_id), { ...params, defaultValue: finding.message })}
        </div>
        <div className="text-2xs text-content-tertiary">{finding.rule_id}</div>
      </div>
    </li>
  );
}

export function ChinaTaxPage() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const projectId = useProjectContextStore((s) => s.activeProjectId);

  const profileQuery = useQuery({
    queryKey: ['china-tax', 'profile', projectId],
    queryFn: () => fetchProfile(projectId as string),
    enabled: !!projectId,
  });
  const checkQuery = useQuery({
    queryKey: ['china-tax', 'check', projectId],
    queryFn: () => fetchProjectCheck(projectId as string),
    enabled: !!projectId,
  });

  const [form, setForm] = useState<ProfileFields | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  useEffect(() => {
    if (profileQuery.data) setForm(toProfileFields(profileQuery.data));
  }, [profileQuery.data]);

  const save = useMutation({
    mutationFn: (body: ProfileFields) => saveProfile(projectId as string, toProfileFields(body)),
    onSuccess: () => {
      setSaveError(null);
      void queryClient.invalidateQueries({ queryKey: ['china-tax'] });
    },
    onError: (err) => {
      if (err instanceof ApiError && err.status === 409) {
        const body = err.body as { detail?: { lock_ends_on?: string } } | null;
        setSaveError(
          t('china_tax.locked', {
            date: body?.detail?.lock_ends_on ?? '',
            defaultValue: 'The tax method is locked until {{date}}.',
          }),
        );
        return;
      }
      setSaveError(getErrorMessage(err));
    },
  });

  const [periods, setPeriods] = useState<PrepaymentPeriodInput[]>([{ period: '1', receipts: '', subcontract_paid: '' }]);
  const [prepay, setPrepay] = useState<PrepaymentResult | null>(null);
  const prepayMutation = useMutation({
    mutationFn: () =>
      computePrepayment(
        form?.tax_method ?? 'general',
        periods.filter((p) => p.receipts.trim() !== '').map((p) => ({ ...p, subcontract_paid: p.subcontract_paid || '0' })),
      ),
    onSuccess: setPrepay,
  });

  const header = (
    <>
      <PageHeader
        srTitle={t('nav.china_tax', { defaultValue: 'China VAT' })}
        subtitle={t('china_tax.subtitle', {
          defaultValue: 'Tax method, bill edition, VAT base and site prepayment of a Chinese project',
        })}
      />
      <CollapsibleSection
        storageKey="china_tax.how"
        icon={<Receipt size={16} className="text-oe-blue" />}
        title={t('china_tax.flow_title', { defaultValue: 'How VAT on a Chinese bill is checked here' })}
      >
        <ol className="list-decimal space-y-1 pl-5 text-xs text-content-tertiary">
          <li>{t('china_tax.flow_step1', { defaultValue: 'State the tax method and the day it was elected. A simplified election is locked for 36 months.' })}</li>
          <li>{t('china_tax.flow_step2', { defaultValue: 'Confirm the bill edition. GB/T 50500-2024 has four heads and no separate statutory charges head.' })}</li>
          <li>{t('china_tax.flow_step3', { defaultValue: 'The specialist prime-cost sum already includes VAT and stays out of the VAT base.' })}</li>
          <li>{t('china_tax.flow_step4', { defaultValue: 'Where the site is in another region, the prepayment is computed per period; the filing stays in the tax e-bureau.' })}</li>
        </ol>
      </CollapsibleSection>
    </>
  );

  if (!projectId) {
    return (
      <div className="space-y-5 animate-fade-in">
        {header}
        <EmptyState
          icon={<Landmark className="h-8 w-8" />}
          title={t('china_tax.no_project', { defaultValue: 'Pick a project first' })}
          description={t('china_tax.no_project_body', {
            defaultValue: 'The tax method and the bill edition belong to one project.',
          })}
        />
      </div>
    );
  }

  const profile: TaxProfile | undefined = profileQuery.data;
  const check = checkQuery.data;
  const findings = check?.findings ?? [];
  const errors = findings.filter((f) => f.severity === 'error').length;
  const set = <K extends keyof ProfileFields>(key: K) => (e: ChangeEvent<HTMLInputElement | HTMLSelectElement>) => {
    if (!form) return;
    const target = e.target as HTMLInputElement;
    const raw = target.type === 'checkbox' ? target.checked : target.value;
    const value = key === 'lock_months' ? (raw === '' ? null : Number(raw)) : raw;
    setForm({ ...form, [key]: value } as ProfileFields);
  };

  return (
    <div className="space-y-5 animate-fade-in">
      {header}

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <StatCard
          label={t('china_tax.vat_base', { defaultValue: 'VAT base' })}
          value={<MoneyDisplay amount={check?.summary.vat_base ?? null} currency="CNY" />}
          icon={Calculator}
        />
        <StatCard
          label={t('china_tax.vat', { defaultValue: 'VAT' })}
          value={<MoneyDisplay amount={check?.summary.vat ?? null} currency="CNY" />}
          icon={Receipt}
        />
        <StatCard
          label={t('china_tax.tender_total', { defaultValue: 'Tender total' })}
          value={<MoneyDisplay amount={check?.summary.tender_total ?? null} currency="CNY" />}
          icon={Landmark}
          tone="blue"
        />
        <StatCard
          label={t('china_tax.findings', { defaultValue: 'Findings' })}
          value={findings.length}
          icon={ShieldCheck}
          tone={errors > 0 ? 'danger' : findings.length > 0 ? 'warning' : 'success'}
          tintValue
        />
      </div>

      <Card>
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-sm font-semibold text-content-primary">
            {t('china_tax.profile', { defaultValue: 'Tax profile' })}
          </h2>
          {profile && !profile.stored && (
            <span className="text-xs text-semantic-warning">
              {t('china_tax.proposal', { defaultValue: 'Proposal, not saved yet' })}
            </span>
          )}
          {profile?.lock_ends_on && (
            <span className="text-xs text-content-tertiary">
              {t('china_tax.lock_until', { date: profile.lock_ends_on, defaultValue: 'Locked until {{date}}' })}
            </span>
          )}
        </div>
        {form && (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <Field label={t('china_tax.method', { defaultValue: 'Tax method' })}>
              <select className={INPUT} value={form.tax_method} onChange={set('tax_method')}>
                <option value="general">{t('china_tax.method_general', { defaultValue: 'General (一般计税)' })}</option>
                <option value="simplified">{t('china_tax.method_simplified', { defaultValue: 'Simplified 3% (简易计税)' })}</option>
                <option value="exempt">{t('china_tax.method_exempt', { defaultValue: 'Exempt' })}</option>
              </select>
            </Field>
            {form.tax_method === 'simplified' && (
              <Field label={t('china_tax.basis', { defaultValue: 'Basis of the election' })}>
                <select className={INPUT} value={form.simplified_basis ?? ''} onChange={set('simplified_basis')}>
                  <option value="">-</option>
                  <option value="labour_only">清包工</option>
                  <option value="old_project">老项目</option>
                  <option value="employer_supplied">甲供工程</option>
                </select>
              </Field>
            )}
            <Field label={t('china_tax.election_date', { defaultValue: 'Election date' })}>
              <input type="date" className={INPUT} value={form.election_date ?? ''} onChange={set('election_date')} />
            </Field>
            <Field label={t('china_tax.lock_months', { defaultValue: 'Lock (months)' })}>
              <input type="number" min={0} className={INPUT} value={form.lock_months ?? ''} onChange={set('lock_months')} />
            </Field>
            <Field label={t('china_tax.edition', { defaultValue: 'Bill edition' })}>
              <select className={INPUT} value={form.standard_edition ?? ''} onChange={set('standard_edition')}>
                <option value="">-</option>
                {(profile?.editions ?? []).map((e) => (
                  <option key={e.key} value={e.key}>
                    {e.label}
                  </option>
                ))}
              </select>
            </Field>
            <Field label={t('china_tax.contract_date', { defaultValue: 'Contract date' })}>
              <input type="date" className={INPUT} value={form.contract_date ?? ''} onChange={set('contract_date')} />
            </Field>
            <Field label={t('china_tax.tender_date', { defaultValue: 'Tender date' })}>
              <input type="date" className={INPUT} value={form.tender_date ?? ''} onChange={set('tender_date')} />
            </Field>
            <Field label={t('china_tax.taxpayer_size', { defaultValue: 'Taxpayer' })}>
              <select className={INPUT} value={form.taxpayer_size} onChange={set('taxpayer_size')}>
                <option value="general">{t('china_tax.taxpayer_general', { defaultValue: 'General taxpayer' })}</option>
                <option value="small">{t('china_tax.taxpayer_small', { defaultValue: 'Small-scale taxpayer' })}</option>
              </select>
            </Field>
            <Field label={t('china_tax.site_city', { defaultValue: 'Site city' })}>
              <input className={INPUT} value={form.site_city ?? ''} onChange={set('site_city')} />
            </Field>
            <Field label={t('china_tax.home_city', { defaultValue: 'Home city' })}>
              <input className={INPUT} value={form.home_city ?? ''} onChange={set('home_city')} />
            </Field>
            <label className="flex items-center gap-2 text-xs text-content-secondary">
              <input type="checkbox" checked={form.employer_supplied} onChange={set('employer_supplied')} />
              {t('china_tax.employer_supplied', { defaultValue: 'Employer supplies materials (甲供)' })}
            </label>
            <label className="flex items-center gap-2 text-xs text-content-secondary">
              <input type="checkbox" checked={form.grandfathered} onChange={set('grandfathered')} />
              {t('china_tax.grandfathered', { defaultValue: 'Elected before 2026-01-01 (grandfathered)' })}
            </label>
          </div>
        )}
        <div className="mt-3 flex items-center gap-3">
          <Button size="sm" onClick={() => form && save.mutate(form)} disabled={!form || save.isPending}>
            {t('common.save', { defaultValue: 'Save' })}
          </Button>
          {saveError && <span className="text-xs text-semantic-error">{saveError}</span>}
        </div>
      </Card>

      <Card>
        <h2 className="mb-2 text-sm font-semibold text-content-primary">
          {t('china_tax.summary', { defaultValue: 'Tender summary' })}
        </h2>
        <table className="w-full text-sm">
          <tbody>
            {(check?.summary.heads ?? []).map((h) => (
              <tr key={h.key} className="border-b border-border-light">
                <td className="py-1.5 text-content-secondary">{h.label_zh}</td>
                <td className="py-1.5 text-right tabular-nums">
                  <MoneyDisplay amount={h.amount} currency="CNY" />
                </td>
              </tr>
            ))}
            <tr className="border-b border-border-light">
              <td className="py-1.5 text-content-secondary">
                {t('china_tax.pc_sum', { defaultValue: 'Specialist prime-cost sums, VAT included' })}
              </td>
              <td className="py-1.5 text-right tabular-nums">
                <MoneyDisplay amount={check?.summary.tax_inclusive_total ?? null} currency="CNY" />
              </td>
            </tr>
            <tr>
              <td className="py-1.5 text-content-secondary">
                {t('china_tax.employer_deduction', { defaultValue: 'Employer-supplied materials, deducted on payment' })}
              </td>
              <td className="py-1.5 text-right tabular-nums">
                <MoneyDisplay amount={check?.summary.employer_supplied_net ?? null} currency="CNY" />
              </td>
            </tr>
          </tbody>
        </table>
      </Card>

      <ProvincialFeePanel projectId={projectId} edition={profile?.standard_edition ?? null} />

      <Card>
        <h2 className="mb-2 text-sm font-semibold text-content-primary">
          {t('china_tax.findings', { defaultValue: 'Findings' })}
        </h2>
        {findings.length === 0 ? (
          <p className="text-xs text-content-tertiary">
            {t('china_tax.no_findings', { defaultValue: 'No findings on this project.' })}
          </p>
        ) : (
          <ul className="divide-y divide-border-light">
            {findings.map((f, i) => (
              <FindingRow key={`${f.rule_id}-${f.element_ref ?? i}`} finding={f} />
            ))}
          </ul>
        )}
      </Card>

      <Card>
        <h2 className="mb-1 text-sm font-semibold text-content-primary">
          {t('china_tax.prepayment', { defaultValue: 'Site prepayment (预缴)' })}
        </h2>
        <p className="mb-3 text-xs text-content-tertiary">
          {t('china_tax.prepayment_hint', {
            defaultValue: '(Receipts - subcontract payments) / (1 + rate) x prepayment rate. A shortfall carries forward.',
          })}
        </p>
        <div className="space-y-2">
          {periods.map((p, i) => (
            <div key={i} className="grid grid-cols-3 gap-2">
              <input className={INPUT} value={p.period} aria-label={t('china_tax.period', { defaultValue: 'Period' })}
                onChange={(e) => setPeriods(periods.map((q, j) => (j === i ? { ...q, period: e.target.value } : q)))} />
              <input className={INPUT} inputMode="decimal" value={p.receipts}
                placeholder={t('china_tax.receipts', { defaultValue: 'Receipts incl. VAT' })}
                onChange={(e) => setPeriods(periods.map((q, j) => (j === i ? { ...q, receipts: e.target.value } : q)))} />
              <input className={INPUT} inputMode="decimal" value={p.subcontract_paid}
                placeholder={t('china_tax.subcontract', { defaultValue: 'Subcontract paid' })}
                onChange={(e) => setPeriods(periods.map((q, j) => (j === i ? { ...q, subcontract_paid: e.target.value } : q)))} />
            </div>
          ))}
        </div>
        <div className="mt-3 flex gap-2">
          <Button size="sm" variant="secondary"
            onClick={() => setPeriods([...periods, { period: String(periods.length + 1), receipts: '', subcontract_paid: '' }])}>
            {t('china_tax.add_period', { defaultValue: 'Add period' })}
          </Button>
          <Button size="sm" onClick={() => prepayMutation.mutate()} disabled={prepayMutation.isPending}>
            {t('china_tax.compute', { defaultValue: 'Compute' })}
          </Button>
        </div>
        {prepay && (
          <table className="mt-3 w-full text-sm">
            <tbody>
              {prepay.periods.map((r) => (
                <tr key={r.period} className="border-b border-border-light">
                  <td className="py-1.5 text-content-secondary">{r.period}</td>
                  <td className="py-1.5 text-right tabular-nums"><MoneyDisplay amount={r.prepaid} currency="CNY" /></td>
                  <td className="py-1.5 text-right text-xs text-content-tertiary">
                    {Number(r.carried_out) > 0 &&
                      t('china_tax.carried', { amount: r.carried_out, defaultValue: 'Carried forward {{amount}}' })}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </div>
  );
}
