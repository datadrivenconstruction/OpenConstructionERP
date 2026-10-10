// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The payment certificate settings of a contract (`terms.hakedis`), editable
// while the contract is a draft.
//
// Only what the server defines is offered: the layout to start from, where the
// retention rate comes from, how the advance is recovered, the default choice
// for each tax and who signs. The entry can carry more than this screen edits
// (a custom line set, letters, columns, labels); those keys are kept exactly
// as they are when the rest is saved.
//
// The server judges the whole entry when the contract is saved and names the
// key at fault. Its sentence is shown under the form as it came.
//
// A default tax choice is only ever a suggestion on a certificate: there it
// still takes a person's click before it is saved.

import { useId, useState } from 'react';
import { useTranslation } from 'react-i18next';
import type { TFunction } from 'i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import clsx from 'clsx';
import { ArrowUp, PenLine, X } from 'lucide-react';

import { Button, Card } from '@/shared/ui';
import { toDecimalPayloadString } from '@/shared/lib/parseDecimal';
import { useToastStore } from '@/stores/useToastStore';
import { projectsApi } from '@/features/projects/api';
import { updateContract, type ContractItem } from '../api';
import {
  HAKEDIS_TAX_CHOICE_KINDS,
  listStatutoryCategories,
  type HakedisChoiceState,
  type HakedisTaxChoice,
  type HakedisTaxChoiceKind,
  type StatutoryCategory,
} from './api';
import { readRefusal, type HakedisRefusal } from './hakedisQueries';
import { RefusalNote, inputCls, textareaCls } from './hakedisParts';

/** `LAYOUT_PRESETS` in `backend/app/modules/contracts/hakedis_layout.py`. */
export const HAKEDIS_PRESETS = ['TR', 'TR_PRIVATE'] as const;
type HakedisPreset = (typeof HAKEDIS_PRESETS)[number];

/** The retention sources `resolve_settings` accepts. */
export const HAKEDIS_RETENTION_SOURCES = ['contract', 'fixed', 'none'] as const;
type RetentionSource = (typeof HAKEDIS_RETENTION_SOURCES)[number];

/** The signature roles the built-in label table knows (`role.*` in `HAKEDIS_LABELS`). */
export const HAKEDIS_SIGNATURE_ROLES = [
  'contractor',
  'prepared_by',
  'approved_by',
  'control_engineer',
  'control_chief',
  'control_organisation',
  'site_manager',
  'project_manager',
  'employer',
  'subcontractor',
  'cost_control',
  'quantity_surveyor',
] as const;
type SignatureRole = (typeof HAKEDIS_SIGNATURE_ROLES)[number];

/** The countries whose standard layout the server ships (`DEFAULT_LAYOUTS`). */
const LAYOUT_COUNTRIES: readonly string[] = ['TR'];

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function text(value: unknown): string {
  return typeof value === 'string' || typeof value === 'number' ? String(value) : '';
}

function presetLabel(t: TFunction, preset: HakedisPreset): string {
  return preset === 'TR'
    ? t('hakedis.terms.preset.TR', { defaultValue: 'Standard public works form' })
    : t('hakedis.terms.preset.TR_PRIVATE', { defaultValue: 'Private sector form' });
}

function retentionLabel(t: TFunction, source: RetentionSource): string {
  switch (source) {
    case 'contract':
      return t('hakedis.terms.retention.contract', { defaultValue: "The contract's retention rate" });
    case 'fixed':
      return t('hakedis.terms.retention.fixed', { defaultValue: 'A rate set for the certificate' });
    default:
      return t('hakedis.terms.retention.none', { defaultValue: 'No retention line' });
  }
}

export function signatureRoleLabel(t: TFunction, role: string): string {
  switch (role as SignatureRole) {
    case 'contractor':
      return t('hakedis.role.contractor', { defaultValue: 'Contractor' });
    case 'prepared_by':
      return t('hakedis.role.prepared_by', { defaultValue: 'Prepared by (Site Supervision Staff)' });
    case 'approved_by':
      return t('hakedis.role.approved_by', { defaultValue: 'Approved by' });
    case 'control_engineer':
      return t('hakedis.role.control_engineer', { defaultValue: 'Supervising Engineer' });
    case 'control_chief':
      return t('hakedis.role.control_chief', { defaultValue: 'Chief Supervisor' });
    case 'control_organisation':
      return t('hakedis.role.control_organisation', { defaultValue: 'Supervision Team' });
    case 'site_manager':
      return t('hakedis.role.site_manager', { defaultValue: 'Site Manager' });
    case 'project_manager':
      return t('hakedis.role.project_manager', { defaultValue: 'Project Manager' });
    case 'employer':
      return t('hakedis.role.employer', { defaultValue: 'Employer' });
    case 'subcontractor':
      return t('hakedis.role.subcontractor', { defaultValue: 'Subcontractor' });
    case 'cost_control':
      return t('hakedis.role.cost_control', { defaultValue: 'Cost Control' });
    case 'quantity_surveyor':
      return t('hakedis.role.quantity_surveyor', { defaultValue: 'Quantity Surveyor' });
    default:
      // A role the contract labels itself, under `labels`.
      return role;
  }
}

function taxLabel(t: TFunction, kind: HakedisTaxChoiceKind): string {
  switch (kind) {
    case 'vat_withholding':
      return t('hakedis.taxes.kind.vat_withholding', { defaultValue: 'VAT withholding' });
    case 'income_withholding':
      return t('hakedis.taxes.kind.income_withholding', { defaultValue: 'Income tax withholding' });
    default:
      return t('hakedis.taxes.kind.stamp_duty', { defaultValue: 'Stamp duty' });
  }
}

export interface HakedisTermsForm {
  preset: string;
  retentionSource: string;
  retentionPct: string;
  advanceRecoveryPct: string;
  advanceAmount: string;
  taxes: Record<HakedisTaxChoiceKind, HakedisTaxChoice>;
  /** Null while the country's default signers stand. */
  roles: string[] | null;
}

function choiceFrom(value: unknown): HakedisTaxChoice {
  if (!isRecord(value)) return { state: 'unset', code: '', reason: '' };
  const state = text(value.state);
  return {
    state: state === 'selected' || state === 'not_applicable' ? state : 'unset',
    code: text(value.code),
    reason: text(value.reason),
  };
}

/** The contract's own entry, or an empty one. */
export function hakedisTermsOf(contract: ContractItem): Record<string, unknown> {
  const raw = contract.terms.hakedis;
  return isRecord(raw) ? raw : {};
}

function formFrom(raw: Record<string, unknown>): HakedisTermsForm {
  const retention = isRecord(raw.retention) ? raw.retention : {};
  const taxes = isRecord(raw.taxes) ? raw.taxes : {};
  return {
    preset: text(raw.preset),
    // The server reads a rate with no source as a fixed rate.
    retentionSource: text(retention.source) || (text(retention.pct) !== '' ? 'fixed' : ''),
    retentionPct: text(retention.pct),
    advanceRecoveryPct: text(raw.advance_recovery_pct),
    advanceAmount: text(raw.advance_amount),
    taxes: {
      vat_withholding: choiceFrom(taxes.vat_withholding),
      income_withholding: choiceFrom(taxes.income_withholding),
      stamp_duty: choiceFrom(taxes.stamp_duty),
    },
    roles: Array.isArray(raw.signature_roles) ? raw.signature_roles.map((role) => text(role)) : null,
  };
}

/**
 * The entry to store: what the form states over what the contract already
 * carried. A field left empty removes its key, so the country's standard
 * applies again; every key this screen does not edit is passed through.
 */
export function hakedisTermsFrom(form: HakedisTermsForm, existing: Record<string, unknown>): Record<string, unknown> {
  const next: Record<string, unknown> = { ...existing };
  const put = (key: string, value: unknown, present: boolean) => {
    if (present) next[key] = value;
    else delete next[key];
  };
  put('preset', form.preset, form.preset !== '');

  // The retention base is a list of line keys this screen does not edit.
  const retention: Record<string, unknown> = {};
  const before = isRecord(existing.retention) ? existing.retention : {};
  if (before.base !== undefined) retention.base = before.base;
  if (form.retentionSource !== '') retention.source = form.retentionSource;
  if (form.retentionSource === 'fixed' && form.retentionPct.trim() !== '') {
    retention.pct = toDecimalPayloadString(form.retentionPct, '');
  }
  put('retention', retention, Object.keys(retention).length > 0);

  put(
    'advance_recovery_pct',
    toDecimalPayloadString(form.advanceRecoveryPct, ''),
    form.advanceRecoveryPct.trim() !== '',
  );
  put('advance_amount', toDecimalPayloadString(form.advanceAmount, ''), form.advanceAmount.trim() !== '');

  const taxes: Record<string, HakedisTaxChoice> = {};
  for (const kind of HAKEDIS_TAX_CHOICE_KINDS) {
    const choice = form.taxes[kind];
    if (choice.state === 'selected') taxes[kind] = { state: 'selected', code: choice.code, reason: '' };
    if (choice.state === 'not_applicable') {
      taxes[kind] = { state: 'not_applicable', code: '', reason: choice.reason.trim() };
    }
  }
  put('taxes', taxes, Object.keys(taxes).length > 0);
  put('signature_roles', form.roles, form.roles !== null && form.roles.length > 0);
  return next;
}

/**
 * The certificate settings of a contract. Shown for a contract whose project
 * is in a country with a certificate layout, or that already carries an entry;
 * nothing is rendered for any other contract.
 */
export function HakedisTermsCard({ contract }: { contract: ContractItem }) {
  const { t } = useTranslation();
  const [editing, setEditing] = useState(false);
  const raw = hakedisTermsOf(contract);
  const configured = Object.keys(raw).length > 0;
  const projectQ = useQuery({
    queryKey: ['projects', 'detail', contract.project_id],
    queryFn: () => projectsApi.get(contract.project_id),
    enabled: contract.project_id !== '',
    staleTime: 5 * 60_000,
  });
  const country = (projectQ.data?.country_code ?? '').toUpperCase();
  if (!configured && !LAYOUT_COUNTRIES.includes(country)) return null;

  const draft = contract.status === 'draft';
  const form = formFrom(raw);

  return (
    <Card padding="sm" data-testid="hakedis-terms">
      <div className="mb-2 flex items-start justify-between gap-2">
        <p className="text-xs font-semibold uppercase tracking-wide text-content-secondary">
          {t('hakedis.terms.title', { defaultValue: 'Payment certificate settings' })}
        </p>
        {draft && !editing && (
          <button
            type="button"
            data-testid="hakedis-terms-edit"
            onClick={() => setEditing(true)}
            className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-xs text-content-secondary hover:bg-surface-secondary hover:text-content-primary"
          >
            <PenLine size={12} aria-hidden="true" />
            {t('hakedis.terms.edit', { defaultValue: 'Edit certificate settings' })}
          </button>
        )}
      </div>
      {editing && draft ? (
        <TermsEditor
          key={contract.id}
          contract={contract}
          country={country || 'TR'}
          onDone={() => setEditing(false)}
        />
      ) : (
        <TermsSummary form={form} />
      )}
      {!draft && (
        <p className="mt-2 text-xs text-content-tertiary">
          {t('hakedis.terms.locked', {
            defaultValue: 'These settings lock with the other financial terms once the contract leaves draft.',
          })}
        </p>
      )}
    </Card>
  );
}

function TermsSummary({ form }: { form: HakedisTermsForm }) {
  const { t } = useTranslation();
  const standard = t('hakedis.terms.standard', { defaultValue: 'Country standard' });
  const rows: { key: string; label: string; value: string }[] = [
    {
      key: 'preset',
      label: t('hakedis.terms.preset.label', { defaultValue: 'Layout' }),
      value: HAKEDIS_PRESETS.includes(form.preset as HakedisPreset)
        ? presetLabel(t, form.preset as HakedisPreset)
        : form.preset || standard,
    },
    {
      key: 'retention',
      label: t('hakedis.terms.retention.label', { defaultValue: 'Retention' }),
      value: HAKEDIS_RETENTION_SOURCES.includes(form.retentionSource as RetentionSource)
        ? form.retentionSource === 'fixed' && form.retentionPct
          ? t('hakedis.terms.retention.fixed_value', { defaultValue: 'Fixed at {{pct}}%', pct: form.retentionPct })
          : retentionLabel(t, form.retentionSource as RetentionSource)
        : standard,
    },
    {
      key: 'advance_pct',
      label: t('hakedis.terms.advance_recovery_pct', { defaultValue: 'Advance recovery, percent' }),
      value: form.advanceRecoveryPct || t('hakedis.terms.entered_each_time', { defaultValue: 'Entered on each certificate' }),
    },
    {
      key: 'advance_amount',
      label: t('hakedis.terms.advance_amount', { defaultValue: 'Advance paid' }),
      value: form.advanceAmount || t('hakedis.terms.not_stated', { defaultValue: 'Not stated' }),
    },
    ...HAKEDIS_TAX_CHOICE_KINDS.map((kind) => {
      const choice = form.taxes[kind];
      return {
        key: kind,
        label: taxLabel(t, kind),
        value:
          choice.state === 'selected'
            ? t('hakedis.taxes.stored_selected', { defaultValue: 'Category {{code}}', code: choice.code })
            : choice.state === 'not_applicable'
              ? t('hakedis.taxes.stored_not_applicable', {
                  defaultValue: 'Does not apply: {{reason}}',
                  reason: choice.reason,
                })
              : t('hakedis.terms.tax_no_default', { defaultValue: 'No default, decided on each certificate' }),
      };
    }),
    {
      key: 'roles',
      label: t('hakedis.terms.signature_roles', { defaultValue: 'Signed by' }),
      value: form.roles ? form.roles.map((role) => signatureRoleLabel(t, role)).join(', ') : standard,
    },
  ];
  return (
    <dl className="grid grid-cols-1 gap-x-4 gap-y-1 text-sm sm:grid-cols-[minmax(10rem,auto)_1fr]">
      {rows.map((row) => (
        <div key={row.key} className="contents">
          <dt className="break-words text-content-tertiary">{row.label}</dt>
          <dd className="min-w-0 break-words text-content-primary" data-testid={`hakedis-terms-value-${row.key}`}>
            {row.value}
          </dd>
        </div>
      ))}
    </dl>
  );
}

function TermsEditor({
  contract,
  country,
  onDone,
}: {
  contract: ContractItem;
  country: string;
  onDone: () => void;
}) {
  const { t, i18n } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const formId = useId();
  const existing = hakedisTermsOf(contract);
  const [form, setForm] = useState<HakedisTermsForm>(() => formFrom(existing));
  const [refusal, setRefusal] = useState<HakedisRefusal | null>(null);
  const [roleToAdd, setRoleToAdd] = useState('');
  const today = new Date().toISOString().slice(0, 10);

  const categoriesQ = useQuery({
    queryKey: ['hakedis', 'tax-categories', country, today],
    queryFn: () => listStatutoryCategories(country, today),
    retry: false,
    staleTime: 10 * 60_000,
  });
  const categoriesOf = (kind: HakedisTaxChoiceKind): StatutoryCategory[] =>
    (categoriesQ.data?.items ?? []).filter((item) => item.kind === kind);
  const categoryLabel = (category: StatutoryCategory): string => {
    const language = (i18n.language || 'en').split('-')[0] ?? 'en';
    const label = category.labels[language] ?? category.labels.en ?? category.labels.tr ?? '';
    return label ? `${category.code} ${label}` : category.code;
  };

  const saveMut = useMutation({
    // The refusal is shown where the person acted, in its own words.
    meta: { suppressGlobalErrorToast: true },
    mutationFn: () => {
      const hakedis = hakedisTermsFrom(form, existing);
      const terms: Record<string, unknown> = { ...contract.terms };
      if (Object.keys(hakedis).length > 0) terms.hakedis = hakedis;
      else delete terms.hakedis;
      return updateContract(contract.id, { terms });
    },
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: ['contracts'] });
      addToast({
        type: 'success',
        title: t('hakedis.terms.saved', { defaultValue: 'Certificate settings saved' }),
      });
      onDone();
    },
    onError: (err) => setRefusal(readRefusal(err)),
  });

  const set = <K extends keyof HakedisTermsForm>(key: K, value: HakedisTermsForm[K]) =>
    setForm((current) => ({ ...current, [key]: value }));
  const setTax = (kind: HakedisTaxChoiceKind, choice: HakedisTaxChoice) =>
    setForm((current) => ({ ...current, taxes: { ...current.taxes, [kind]: choice } }));
  const incomplete = HAKEDIS_TAX_CHOICE_KINDS.some(
    (kind) => form.taxes[kind].state === 'not_applicable' && form.taxes[kind].reason.trim() === '',
  );
  const roles = form.roles ?? [];
  const addable = HAKEDIS_SIGNATURE_ROLES.filter((role) => !roles.includes(role));
  const fieldCls = 'block text-xs uppercase tracking-wide text-content-tertiary';

  return (
    <form
      className="space-y-3"
      onSubmit={(e) => {
        e.preventDefault();
        if (!incomplete) saveMut.mutate();
      }}
      data-testid="hakedis-terms-form"
    >
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="block">
          <span className={fieldCls}>{t('hakedis.terms.preset.label', { defaultValue: 'Layout' })}</span>
          <select
            value={form.preset}
            onChange={(e) => set('preset', e.target.value)}
            className={clsx(inputCls, 'mt-0.5')}
            data-testid="hakedis-terms-preset"
          >
            <option value="">{t('hakedis.terms.standard', { defaultValue: 'Country standard' })}</option>
            {HAKEDIS_PRESETS.map((preset) => (
              <option key={preset} value={preset}>
                {presetLabel(t, preset)}
              </option>
            ))}
          </select>
        </label>
        <label className="block">
          <span className={fieldCls}>{t('hakedis.terms.retention.label', { defaultValue: 'Retention' })}</span>
          <select
            value={form.retentionSource}
            onChange={(e) => set('retentionSource', e.target.value)}
            className={clsx(inputCls, 'mt-0.5')}
            data-testid="hakedis-terms-retention-source"
          >
            <option value="">{t('hakedis.terms.standard', { defaultValue: 'Country standard' })}</option>
            {HAKEDIS_RETENTION_SOURCES.map((source) => (
              <option key={source} value={source}>
                {retentionLabel(t, source)}
              </option>
            ))}
          </select>
        </label>
        {form.retentionSource === 'fixed' && (
          <label className="block">
            <span className={fieldCls}>
              {t('hakedis.terms.retention.pct', { defaultValue: 'Retention rate, percent' })}
            </span>
            <input
              type="text"
              inputMode="decimal"
              autoComplete="off"
              value={form.retentionPct}
              onChange={(e) => set('retentionPct', e.target.value)}
              className={clsx(inputCls, 'mt-0.5 text-right tabular-nums')}
              data-testid="hakedis-terms-retention-pct"
            />
          </label>
        )}
        <label className="block">
          <span className={fieldCls}>
            {t('hakedis.terms.advance_recovery_pct', { defaultValue: 'Advance recovery, percent' })}
          </span>
          <input
            type="text"
            inputMode="decimal"
            autoComplete="off"
            value={form.advanceRecoveryPct}
            onChange={(e) => set('advanceRecoveryPct', e.target.value)}
            className={clsx(inputCls, 'mt-0.5 text-right tabular-nums')}
            data-testid="hakedis-terms-advance-pct"
          />
        </label>
        <label className="block">
          <span className={fieldCls}>{t('hakedis.terms.advance_amount', { defaultValue: 'Advance paid' })}</span>
          <input
            type="text"
            inputMode="decimal"
            autoComplete="off"
            value={form.advanceAmount}
            onChange={(e) => set('advanceAmount', e.target.value)}
            className={clsx(inputCls, 'mt-0.5 text-right tabular-nums')}
            data-testid="hakedis-terms-advance-amount"
          />
        </label>
      </div>

      <fieldset className="space-y-2">
        <legend className={fieldCls}>
          {t('hakedis.terms.taxes', { defaultValue: 'Default tax choices' })}
        </legend>
        <p className="text-xs text-content-secondary">
          {t('hakedis.terms.taxes_hint', {
            defaultValue: 'A default is suggested on each certificate. It still has to be accepted there.',
          })}
        </p>
        {HAKEDIS_TAX_CHOICE_KINDS.map((kind) => {
          const choice = form.taxes[kind];
          const options = categoriesOf(kind);
          const known = options.some((category) => category.code === choice.code);
          const value = choice.state === 'selected' ? `code:${choice.code}` : choice.state;
          return (
            <div key={kind} className="grid gap-2 sm:grid-cols-2">
              <label className="block">
                <span className="block text-xs text-content-tertiary">{taxLabel(t, kind)}</span>
                <select
                  value={value}
                  onChange={(e) => {
                    const picked = e.target.value;
                    if (picked.startsWith('code:')) {
                      setTax(kind, { state: 'selected', code: picked.slice(5), reason: '' });
                    } else {
                      const state: HakedisChoiceState = picked === 'not_applicable' ? 'not_applicable' : 'unset';
                      setTax(kind, { state, code: '', reason: state === 'not_applicable' ? choice.reason : '' });
                    }
                  }}
                  className={clsx(inputCls, 'mt-0.5')}
                  data-testid={`hakedis-terms-tax-${kind}`}
                >
                  <option value="unset">
                    {t('hakedis.terms.tax_no_default', { defaultValue: 'No default, decided on each certificate' })}
                  </option>
                  {choice.state === 'selected' && !known && (
                    <option value={`code:${choice.code}`}>{choice.code}</option>
                  )}
                  {options.map((category) => (
                    <option key={category.code} value={`code:${category.code}`}>
                      {categoryLabel(category)}
                    </option>
                  ))}
                  <option value="not_applicable">
                    {t('hakedis.line.not_applicable', { defaultValue: 'Does not apply' })}
                  </option>
                </select>
              </label>
              {choice.state === 'not_applicable' && (
                <label className="block">
                  <span className="block text-xs text-content-tertiary">
                    {t('hakedis.taxes.not_applicable_reason', { defaultValue: 'Why it does not apply (required)' })}
                  </span>
                  <textarea
                    rows={2}
                    maxLength={2000}
                    required
                    value={choice.reason}
                    onChange={(e) => setTax(kind, { state: 'not_applicable', code: '', reason: e.target.value })}
                    className={clsx(textareaCls, 'mt-0.5')}
                    data-testid={`hakedis-terms-tax-reason-${kind}`}
                  />
                </label>
              )}
            </div>
          );
        })}
      </fieldset>

      <fieldset className="space-y-2">
        <legend className={fieldCls}>{t('hakedis.terms.signature_roles', { defaultValue: 'Signed by' })}</legend>
        {roles.length === 0 ? (
          <p className="text-xs text-content-secondary">
            {t('hakedis.terms.roles_standard', {
              defaultValue: 'The country standard signers are printed. Add a role to set your own order.',
            })}
          </p>
        ) : (
          <ol className="space-y-1" data-testid="hakedis-terms-roles">
            {roles.map((role, index) => {
              const name = signatureRoleLabel(t, role);
              return (
                <li key={role} className="flex items-center gap-2 text-sm">
                  <span className="w-5 shrink-0 text-right tabular-nums text-content-tertiary">{index + 1}.</span>
                  <span className="min-w-0 flex-1 break-words text-content-primary">{name}</span>
                  <button
                    type="button"
                    disabled={index === 0}
                    onClick={() => {
                      const next = [...roles];
                      const above = next[index - 1];
                      if (above === undefined) return;
                      next[index - 1] = role;
                      next[index] = above;
                      set('roles', next);
                    }}
                    aria-label={t('hakedis.terms.role_up', { defaultValue: 'Move {{role}} up', role: name })}
                    className="rounded p-1 text-content-secondary hover:bg-surface-secondary disabled:opacity-40"
                  >
                    <ArrowUp size={13} aria-hidden="true" />
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      const next = roles.filter((item) => item !== role);
                      set('roles', next.length > 0 ? next : null);
                    }}
                    aria-label={t('hakedis.terms.role_remove', { defaultValue: 'Remove {{role}}', role: name })}
                    className="rounded p-1 text-content-secondary hover:bg-surface-secondary"
                    data-testid={`hakedis-terms-role-remove-${role}`}
                  >
                    <X size={13} aria-hidden="true" />
                  </button>
                </li>
              );
            })}
          </ol>
        )}
        {addable.length > 0 && (
          <div className="flex flex-wrap items-end gap-2">
            <label className="block min-w-0 flex-1" htmlFor={`${formId}-role`}>
              <span className="block text-xs text-content-tertiary">
                {t('hakedis.terms.role_add_label', { defaultValue: 'Role to add' })}
              </span>
              <select
                id={`${formId}-role`}
                value={roleToAdd}
                onChange={(e) => setRoleToAdd(e.target.value)}
                className={clsx(inputCls, 'mt-0.5')}
                data-testid="hakedis-terms-role-select"
              >
                <option value="">{t('hakedis.terms.role_pick', { defaultValue: 'Choose a role' })}</option>
                {addable.map((role) => (
                  <option key={role} value={role}>
                    {signatureRoleLabel(t, role)}
                  </option>
                ))}
              </select>
            </label>
            <Button
              type="button"
              variant="secondary"
              size="sm"
              disabled={roleToAdd === ''}
              onClick={() => {
                set('roles', [...roles, roleToAdd]);
                setRoleToAdd('');
              }}
              data-testid="hakedis-terms-role-add"
            >
              {t('hakedis.terms.role_add', { defaultValue: 'Add' })}
            </Button>
          </div>
        )}
      </fieldset>

      {refusal && <RefusalNote t={t} refusal={refusal} testId="hakedis-terms-refusal" />}

      <div className="flex flex-wrap justify-end gap-2">
        <Button type="button" variant="ghost" size="sm" onClick={onDone} disabled={saveMut.isPending}>
          {t('hakedis.line.cancel', { defaultValue: 'Cancel' })}
        </Button>
        <Button
          type="submit"
          size="sm"
          loading={saveMut.isPending}
          disabled={incomplete}
          data-testid="hakedis-terms-save"
        >
          {t('hakedis.terms.save', { defaultValue: 'Save certificate settings' })}
        </Button>
      </div>
    </form>
  );
}
