// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The registers that back the plan: securities, insurance, the tax treatment and
// the set-up of the receivables, payables and administration processes. A gate
// asks whether each is in place; the check list at the top answers with the same
// data. The registers stay editable while the plan is proposed or approved.

import { useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { Check, Circle } from 'lucide-react';

import { Badge, type BadgeVariant } from '@/shared/ui/Badge';
import { fmtDate } from '@/shared/lib/formatters';

import {
  addInsurance,
  addSecurity,
  deleteInsurance,
  deleteSecurity,
  patchInsurance,
  patchSecurity,
  putProcess,
  putTax,
  type InsuranceKind,
  type InsuranceStatus,
  type ProcessRow,
  type Registers,
  type SecurityKind,
  type SecurityStatus,
  type VatTreatment,
} from './api';
import { AddRow, ConfirmDelete, Field, cleanDecimal, inputClass, isDecimal, orDash, useDay, useMoney } from './EconomicsBits';
import { useEconomicsAction } from './hooks';
import {
  INSURANCE_KIND,
  INSURANCE_STATUS,
  PROCESS_AREA,
  SECURITY_KIND,
  SECURITY_STATUS,
  VAT_TREATMENT,
  type KeyText,
} from './labels';

const SECURITY_KINDS = Object.keys(SECURITY_KIND) as SecurityKind[];
const SECURITY_STATUSES = Object.keys(SECURITY_STATUS) as SecurityStatus[];
const INSURANCE_KINDS = Object.keys(INSURANCE_KIND) as InsuranceKind[];
const INSURANCE_STATUSES = Object.keys(INSURANCE_STATUS) as InsuranceStatus[];
const VAT_TREATMENTS = Object.keys(VAT_TREATMENT) as VatTreatment[];

const STATUS_VARIANT: Record<string, BadgeVariant> = {
  requested: 'warning',
  in_place: 'success',
  released: 'neutral',
  expired: 'error',
  open: 'warning',
  set_up: 'success',
};

type Translate = (key: string, options?: Record<string, unknown>) => string;
const word = (t: Translate, entry: KeyText) => t(entry[0], { defaultValue: entry[1] });

function Section({ title, children, testId }: { title: string; children: ReactNode; testId: string }) {
  return (
    <section className="space-y-3" data-testid={testId}>
      <h2 className="text-base font-semibold text-content-primary">{title}</h2>
      {children}
    </section>
  );
}

function StatusSelect<T extends string>({
  value,
  options,
  labels,
  onChange,
  label,
}: {
  value: T;
  options: T[];
  labels: Record<T, KeyText>;
  onChange: (next: T) => void;
  label: string;
}) {
  const { t } = useTranslation();
  return (
    <select aria-label={label} className={`${inputClass} h-8`} value={value} onChange={(e) => onChange(e.target.value as T)}>
      {options.map((x) => (
        <option key={x} value={x}>
          {word(t, labels[x])}
        </option>
      ))}
    </select>
  );
}

function SecuritiesSection({ projectId, data, canEdit, currency }: { projectId: string; data: Registers; canEdit: boolean; currency: string }) {
  const { t } = useTranslation();
  const { money } = useMoney(currency);
  const day = useDay();
  const add = useEconomicsAction(projectId, (body: Record<string, unknown>) => addSecurity(projectId, body));
  const patch = useEconomicsAction(projectId, ({ id, body }: { id: string; body: Record<string, unknown> }) =>
    patchSecurity(projectId, id, body),
  );
  const remove = useEconomicsAction(projectId, (id: string) => deleteSecurity(projectId, id));
  const [kind, setKind] = useState<SecurityKind>('performance');
  const [description, setDescription] = useState('');
  const [amount, setAmount] = useState('');
  const [issuer, setIssuer] = useState('');
  const [until, setUntil] = useState('');

  return (
    <Section title={t('economics.registers.securities_title', { defaultValue: 'Securities' })} testId="economics-securities">
      <div className="overflow-x-auto rounded-lg border border-border">
        <table className="w-full text-sm">
          <thead className="bg-surface-secondary text-left text-xs text-content-secondary">
            <tr>
              <th className="px-3 py-2">{t('economics.registers.col_description', { defaultValue: 'Description' })}</th>
              <th className="px-3 py-2 text-right">{t('economics.registers.col_amount', { defaultValue: 'Amount' })}</th>
              <th className="px-3 py-2">{t('economics.registers.col_issuer', { defaultValue: 'Issuer' })}</th>
              <th className="px-3 py-2">{t('economics.registers.col_valid_until', { defaultValue: 'Valid until' })}</th>
              <th className="px-3 py-2">{t('economics.registers.col_status', { defaultValue: 'Status' })}</th>
              <th className="px-3 py-2" />
            </tr>
          </thead>
          <tbody>
            {data.securities.map((row) => (
              <tr key={row.id} className="border-t border-border" data-testid="economics-security">
                <td className="px-3 py-2">
                  <div>{row.description}</div>
                  <div className="text-xs text-content-secondary">
                    {word(t, SECURITY_KIND[row.kind])}
                    {row.reference && ` - ${row.reference}`}
                  </div>
                </td>
                <td className="px-3 py-2 text-right tabular-nums">{money(row.amount)}</td>
                <td className="px-3 py-2">{orDash(row.issuer)}</td>
                <td className={row.lapsed ? 'px-3 py-2 text-semantic-error' : 'px-3 py-2'}>{orDash(day(row.valid_until))}</td>
                <td className="px-3 py-2">
                  {canEdit ? (
                    <StatusSelect
                      value={row.status}
                      options={SECURITY_STATUSES}
                      labels={SECURITY_STATUS}
                      label={t('economics.registers.col_status', { defaultValue: 'Status' })}
                      onChange={(status) => patch({ id: row.id, body: { status } })}
                    />
                  ) : (
                    <Badge variant={STATUS_VARIANT[row.status] ?? 'neutral'}>{word(t, SECURITY_STATUS[row.status])}</Badge>
                  )}
                </td>
                <td className="px-3 py-2 text-right">
                  {canEdit && (
                    <ConfirmDelete
                      label={t('economics.registers.delete_security', { defaultValue: 'Delete the security' })}
                      title={t('economics.confirm.title', { defaultValue: 'Delete this entry?' })}
                      message={t('economics.confirm.security', {
                        defaultValue: 'The security {{name}} is removed from the register.',
                        name: row.description,
                      })}
                      onConfirm={() => remove(row.id)}
                    />
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {canEdit && (
        <div className="rounded-lg border border-border p-3">
          <AddRow
            submitLabel={t('economics.registers.add_security', { defaultValue: 'Add a security' })}
            disabled={description.trim() === '' || !isDecimal(amount || 'x')}
            onSubmit={async () => {
              await add({
                kind,
                description: description.trim(),
                amount: cleanDecimal(amount),
                issuer: issuer.trim(),
                valid_until: until || null,
              });
              setDescription('');
              setAmount('');
              setIssuer('');
              setUntil('');
            }}
          >
            <Field label={t('economics.registers.col_kind', { defaultValue: 'Kind' })}>
              <select className={inputClass} value={kind} onChange={(e) => setKind(e.target.value as SecurityKind)}>
                {SECURITY_KINDS.map((x) => (
                  <option key={x} value={x}>
                    {word(t, SECURITY_KIND[x])}
                  </option>
                ))}
              </select>
            </Field>
            <Field label={t('economics.registers.col_description', { defaultValue: 'Description' })}>
              <input className={`${inputClass} w-64`} value={description} onChange={(e) => setDescription(e.target.value)} />
            </Field>
            <Field label={t('economics.registers.col_amount', { defaultValue: 'Amount' })}>
              <input className={`${inputClass} w-32 text-right`} inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} />
            </Field>
            <Field label={t('economics.registers.col_issuer', { defaultValue: 'Issuer' })}>
              <input className={`${inputClass} w-48`} value={issuer} onChange={(e) => setIssuer(e.target.value)} />
            </Field>
            <Field label={t('economics.registers.col_valid_until', { defaultValue: 'Valid until' })}>
              <input className={inputClass} type="date" value={until} onChange={(e) => setUntil(e.target.value)} />
            </Field>
          </AddRow>
        </div>
      )}
    </Section>
  );
}

function InsuranceSection({ projectId, data, canEdit, currency }: { projectId: string; data: Registers; canEdit: boolean; currency: string }) {
  const { t } = useTranslation();
  const { money } = useMoney(currency);
  const day = useDay();
  const add = useEconomicsAction(projectId, (body: Record<string, unknown>) => addInsurance(projectId, body));
  const patch = useEconomicsAction(projectId, ({ id, body }: { id: string; body: Record<string, unknown> }) =>
    patchInsurance(projectId, id, body),
  );
  const remove = useEconomicsAction(projectId, (id: string) => deleteInsurance(projectId, id));
  const [kind, setKind] = useState<InsuranceKind>('builders_all_risk');
  const [insurer, setInsurer] = useState('');
  const [policy, setPolicy] = useState('');
  const [sum, setSum] = useState('');
  const [until, setUntil] = useState('');

  return (
    <Section title={t('economics.registers.insurance_title', { defaultValue: 'Insurance' })} testId="economics-insurance">
      <div className="overflow-x-auto rounded-lg border border-border">
        <table className="w-full text-sm">
          <thead className="bg-surface-secondary text-left text-xs text-content-secondary">
            <tr>
              <th className="px-3 py-2">{t('economics.registers.col_policy', { defaultValue: 'Policy' })}</th>
              <th className="px-3 py-2 text-right">{t('economics.registers.col_sum_insured', { defaultValue: 'Sum insured' })}</th>
              <th className="px-3 py-2 text-right">{t('economics.registers.col_deductible', { defaultValue: 'Deductible' })}</th>
              <th className="px-3 py-2">{t('economics.registers.col_period', { defaultValue: 'Period' })}</th>
              <th className="px-3 py-2">{t('economics.registers.col_status', { defaultValue: 'Status' })}</th>
              <th className="px-3 py-2" />
            </tr>
          </thead>
          <tbody>
            {data.insurances.map((row) => (
              <tr key={row.id} className="border-t border-border" data-testid="economics-insurance-row">
                <td className="px-3 py-2">
                  <div>{word(t, INSURANCE_KIND[row.kind])}</div>
                  <div className="text-xs text-content-secondary">
                    {row.insurer}
                    {row.policy_number && ` - ${row.policy_number}`}
                  </div>
                </td>
                <td className="px-3 py-2 text-right tabular-nums">{money(row.sum_insured)}</td>
                <td className="px-3 py-2 text-right tabular-nums">{money(row.deductible)}</td>
                <td className={row.lapsed ? 'px-3 py-2 text-semantic-error' : 'px-3 py-2'}>
                  {orDash(day(row.period_from))} - {orDash(day(row.period_to))}
                </td>
                <td className="px-3 py-2">
                  {canEdit ? (
                    <StatusSelect
                      value={row.status}
                      options={INSURANCE_STATUSES}
                      labels={INSURANCE_STATUS}
                      label={t('economics.registers.col_status', { defaultValue: 'Status' })}
                      onChange={(status) => patch({ id: row.id, body: { status } })}
                    />
                  ) : (
                    <Badge variant={STATUS_VARIANT[row.status] ?? 'neutral'}>{word(t, INSURANCE_STATUS[row.status])}</Badge>
                  )}
                </td>
                <td className="px-3 py-2 text-right">
                  {canEdit && (
                    <ConfirmDelete
                      label={t('economics.registers.delete_insurance', { defaultValue: 'Delete the insurance' })}
                      title={t('economics.confirm.title', { defaultValue: 'Delete this entry?' })}
                      message={t('economics.confirm.insurance', {
                        defaultValue: 'The policy {{name}} is removed from the register.',
                        name: row.policy_number || row.insurer,
                      })}
                      onConfirm={() => remove(row.id)}
                    />
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {canEdit && (
        <div className="rounded-lg border border-border p-3">
          <AddRow
            submitLabel={t('economics.registers.add_insurance', { defaultValue: 'Add an insurance' })}
            disabled={insurer.trim() === '' || !isDecimal(sum || 'x')}
            onSubmit={async () => {
              await add({
                kind,
                insurer: insurer.trim(),
                policy_number: policy.trim(),
                sum_insured: cleanDecimal(sum),
                period_to: until || null,
              });
              setInsurer('');
              setPolicy('');
              setSum('');
              setUntil('');
            }}
          >
            <Field label={t('economics.registers.col_kind', { defaultValue: 'Kind' })}>
              <select className={inputClass} value={kind} onChange={(e) => setKind(e.target.value as InsuranceKind)}>
                {INSURANCE_KINDS.map((x) => (
                  <option key={x} value={x}>
                    {word(t, INSURANCE_KIND[x])}
                  </option>
                ))}
              </select>
            </Field>
            <Field label={t('economics.registers.col_insurer', { defaultValue: 'Insurer' })}>
              <input className={`${inputClass} w-56`} value={insurer} onChange={(e) => setInsurer(e.target.value)} />
            </Field>
            <Field label={t('economics.registers.col_policy_number', { defaultValue: 'Policy number' })}>
              <input className={`${inputClass} w-36`} value={policy} onChange={(e) => setPolicy(e.target.value)} />
            </Field>
            <Field label={t('economics.registers.col_sum_insured', { defaultValue: 'Sum insured' })}>
              <input className={`${inputClass} w-32 text-right`} inputMode="decimal" value={sum} onChange={(e) => setSum(e.target.value)} />
            </Field>
            <Field label={t('economics.registers.col_period_to', { defaultValue: 'Ends on' })}>
              <input className={inputClass} type="date" value={until} onChange={(e) => setUntil(e.target.value)} />
            </Field>
          </AddRow>
        </div>
      )}
    </Section>
  );
}

function TaxSection({ projectId, data, canEdit }: { projectId: string; data: Registers; canEdit: boolean }) {
  const { t } = useTranslation();
  const tax = data.tax;
  const save = useEconomicsAction(projectId, (body: Record<string, unknown>) => putTax(projectId, body));
  const [vat, setVat] = useState<VatTreatment>(tax?.vat_treatment ?? 'standard');
  const [deduction, setDeduction] = useState<'yes' | 'no' | 'unknown'>(
    tax?.input_tax_deduction === true ? 'yes' : tax?.input_tax_deduction === false ? 'no' : 'unknown',
  );
  const [notes, setNotes] = useState(tax?.notes ?? '');
  const [confirm, setConfirm] = useState(false);
  const deductionText = (value: boolean | null | undefined) =>
    value === true
      ? t('economics.registers.deduction_yes', { defaultValue: 'Input tax can be deducted' })
      : value === false
        ? t('economics.registers.deduction_no', { defaultValue: 'No input tax deduction' })
        : t('economics.registers.deduction_unknown', { defaultValue: 'Not clarified' });
  const confirmedOn = tax?.confirmed_at ? fmtDate(tax.confirmed_at) : '';

  return (
    <Section title={t('economics.registers.tax_title', { defaultValue: 'Tax treatment' })} testId="economics-tax">
      <div className="space-y-1 rounded-lg border border-border p-3 text-sm">
        {tax ? (
          <>
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-medium">{word(t, VAT_TREATMENT[tax.vat_treatment])}</span>
              <span className="text-content-secondary">{deductionText(tax.input_tax_deduction)}</span>
              <Badge variant={tax.confirmed ? 'success' : 'warning'}>
                {tax.confirmed
                  ? t('economics.registers.tax_confirmed', { defaultValue: 'Confirmed' })
                  : t('economics.registers.tax_unconfirmed', { defaultValue: 'Not confirmed' })}
              </Badge>
            </div>
            {tax.notes && <p className="text-content-secondary">{tax.notes}</p>}
            {tax.confirmed && (
              <p className="text-xs text-content-secondary">
                {t('economics.registers.tax_confirmed_by', {
                  defaultValue: 'Confirmed by {{name}} on {{date}}',
                  name: orDash(tax.confirmed_by_name),
                  date: confirmedOn,
                })}
              </p>
            )}
          </>
        ) : (
          <p className="text-content-secondary">
            {t('economics.registers.tax_none', { defaultValue: 'The tax treatment of the project is not recorded yet.' })}
          </p>
        )}
      </div>
      {canEdit && (
        <div className="rounded-lg border border-border p-3">
          <AddRow
            submitLabel={t('economics.registers.save_tax', { defaultValue: 'Save the tax treatment' })}
            onSubmit={async () => {
              await save({
                vat_treatment: vat,
                input_tax_deduction: deduction === 'unknown' ? null : deduction === 'yes',
                notes: notes.trim(),
                confirm,
              });
              setConfirm(false);
            }}
          >
            <Field label={t('economics.registers.vat_treatment', { defaultValue: 'Value added tax' })}>
              <select className={inputClass} value={vat} onChange={(e) => setVat(e.target.value as VatTreatment)}>
                {VAT_TREATMENTS.map((x) => (
                  <option key={x} value={x}>
                    {word(t, VAT_TREATMENT[x])}
                  </option>
                ))}
              </select>
            </Field>
            <Field label={t('economics.registers.input_tax', { defaultValue: 'Input tax deduction' })}>
              <select className={inputClass} value={deduction} onChange={(e) => setDeduction(e.target.value as 'yes' | 'no' | 'unknown')}>
                <option value="yes">{t('economics.registers.deduction_yes', { defaultValue: 'Input tax can be deducted' })}</option>
                <option value="no">{t('economics.registers.deduction_no', { defaultValue: 'No input tax deduction' })}</option>
                <option value="unknown">{t('economics.registers.deduction_unknown', { defaultValue: 'Not clarified' })}</option>
              </select>
            </Field>
            <Field label={t('economics.registers.notes', { defaultValue: 'Notes' })}>
              <input className={`${inputClass} w-96`} value={notes} onChange={(e) => setNotes(e.target.value)} />
            </Field>
            <label className="flex items-center gap-2 pb-2 text-sm text-content-secondary">
              <input type="checkbox" checked={confirm} onChange={(e) => setConfirm(e.target.checked)} />
              {t('economics.registers.confirm_tax', { defaultValue: 'I confirm this treatment' })}
            </label>
          </AddRow>
        </div>
      )}
    </Section>
  );
}

function ProcessCard({ projectId, row, canEdit }: { projectId: string; row: ProcessRow; canEdit: boolean }) {
  const { t } = useTranslation();
  const day = useDay();
  const save = useEconomicsAction(projectId, (body: Record<string, unknown>) => putProcess(projectId, row.area, body));
  const [owner, setOwner] = useState(row.owner);
  const [description, setDescription] = useState(row.description);
  const [done, setDone] = useState(row.status === 'set_up');
  return (
    <div className="space-y-2 rounded-lg border border-border p-3" data-testid="economics-process">
      <div className="flex items-center justify-between gap-2">
        <span className="font-medium">{word(t, PROCESS_AREA[row.area])}</span>
        <Badge variant={STATUS_VARIANT[row.status] ?? 'neutral'}>
          {row.status === 'set_up'
            ? t('economics.registers.process_set_up', { defaultValue: 'Set up' })
            : t('economics.registers.process_open', { defaultValue: 'Open' })}
        </Badge>
      </div>
      {!canEdit && (
        <>
          <p className="text-sm text-content-secondary">{orDash(row.description)}</p>
          <p className="text-xs text-content-secondary">
            {t('economics.registers.owner', { defaultValue: 'Responsible' })}: {orDash(row.owner)}
            {row.set_up_on && ` - ${day(row.set_up_on)}`}
          </p>
        </>
      )}
      {canEdit && (
        <AddRow
          submitLabel={t('economics.registers.save_process', { defaultValue: 'Save' })}
          onSubmit={() => save({ owner: owner.trim(), description: description.trim(), status: done ? 'set_up' : 'open' })}
        >
          <Field label={t('economics.registers.owner', { defaultValue: 'Responsible' })}>
            <input className={`${inputClass} w-56`} value={owner} onChange={(e) => setOwner(e.target.value)} />
          </Field>
          <Field label={t('economics.registers.col_description', { defaultValue: 'Description' })}>
            <input className={`${inputClass} w-full min-w-64`} value={description} onChange={(e) => setDescription(e.target.value)} />
          </Field>
          <label className="flex items-center gap-2 pb-2 text-sm text-content-secondary">
            <input type="checkbox" checked={done} onChange={(e) => setDone(e.target.checked)} />
            {t('economics.registers.process_is_set_up', { defaultValue: 'The process is set up' })}
          </label>
        </AddRow>
      )}
    </div>
  );
}

function Checklist({ state }: { state: Registers['state'] }) {
  const { t } = useTranslation();
  const items: [boolean, string][] = [
    [state.securities, t('economics.registers.check_securities', { defaultValue: 'Securities are in place and valid' })],
    [state.insurance, t('economics.registers.check_insurance', { defaultValue: 'Insurance is in place and valid' })],
    [state.tax, t('economics.registers.check_tax', { defaultValue: 'Tax treatment is confirmed' })],
    [state.receivables_payables, t('economics.registers.check_receivables_payables', { defaultValue: 'Receivables and payables are set up' })],
    [state.administration, t('economics.registers.check_administration', { defaultValue: 'Project administration is set up' })],
  ];
  return (
    <ul className="grid gap-2 rounded-lg border border-border p-3 text-sm md:grid-cols-2 xl:grid-cols-3" data-testid="economics-checklist">
      {items.map(([ok, label]) => (
        <li key={label} className="flex items-center gap-2">
          {ok ? <Check className="h-4 w-4 text-semantic-success" /> : <Circle className="h-4 w-4 text-content-tertiary" />}
          <span className={ok ? 'text-content-primary' : 'text-content-secondary'}>{label}</span>
        </li>
      ))}
    </ul>
  );
}

export function RegistersPanel({
  projectId,
  data,
  canEdit,
  currency,
}: {
  projectId: string;
  data: Registers;
  canEdit: boolean;
  currency: string;
}) {
  const { t } = useTranslation();
  return (
    <div className="space-y-6" data-testid="economics-registers">
      <p className="text-sm text-content-secondary">
        {t('economics.registers.intro', {
          defaultValue: 'What backs the plan: guarantees, insurance, the tax treatment and the administrative processes. A gate asks whether each is in place.',
        })}
      </p>
      <Checklist state={data.state} />
      <SecuritiesSection projectId={projectId} data={data} canEdit={canEdit} currency={currency} />
      <InsuranceSection projectId={projectId} data={data} canEdit={canEdit} currency={currency} />
      <TaxSection projectId={projectId} data={data} canEdit={canEdit} />
      <Section title={t('economics.registers.process_title', { defaultValue: 'Processes' })} testId="economics-processes">
        <div className="grid gap-3 xl:grid-cols-3">
          {data.process.map((row) => (
            <ProcessCard key={`${row.area}:${row.status}:${row.owner}:${row.description}`} projectId={projectId} row={row} canEdit={canEdit} />
          ))}
        </div>
      </Section>
    </div>
  );
}
