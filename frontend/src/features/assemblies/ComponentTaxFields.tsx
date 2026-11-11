// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Input-tax profile of one assembly component (issue #559). Rendered only for
// a project that switched component tax on; empty fields inherit the catalog
// resource's profile, and an empty treatment follows the project default.

import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import type { InputTaxTreatment, TaxProfile, TaxStatus } from './api';

const fieldClass =
  'w-full rounded-md border border-border-light bg-surface-primary px-2 py-1 text-sm focus:outline-none focus:ring-1 focus:ring-oe-blue/40';
const labelClass = 'text-2xs uppercase tracking-wider text-content-tertiary font-semibold mb-1';

function TextCommit({
  label,
  value,
  onCommit,
  placeholder,
  inputMode,
  testId,
}: {
  label: string;
  value: string;
  onCommit: (v: string) => void;
  placeholder?: string;
  inputMode?: 'decimal' | 'text';
  testId: string;
}) {
  const [draft, setDraft] = useState(value);
  useEffect(() => setDraft(value), [value]);
  return (
    <label className="block">
      <div className={labelClass}>{label}</div>
      <input
        type="text"
        inputMode={inputMode}
        data-testid={testId}
        value={draft}
        placeholder={placeholder}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={() => {
          if (draft.trim() !== value) onCommit(draft.trim());
        }}
        onKeyDown={(e) => {
          if (e.key === 'Enter') (e.target as HTMLInputElement).blur();
        }}
        className={fieldClass}
      />
    </label>
  );
}

export interface ComponentTaxFieldsProps {
  profile: TaxProfile;
  onChange: (patch: TaxProfile) => void;
}

export function ComponentTaxFields({ profile, onChange }: ComponentTaxFieldsProps) {
  const { t } = useTranslation();
  return (
    <>
      <label className="block">
        <div className={labelClass}>{t('assemblies.tax.status', { defaultValue: 'Tax status' })}</div>
        <select
          data-testid="tax-status"
          value={profile.tax_status ?? ''}
          onChange={(e) => onChange({ tax_status: (e.target.value || null) as TaxStatus | null })}
          className={fieldClass}
        >
          <option value="">{t('assemblies.tax.status_unset', { defaultValue: 'Not set (from resource)' })}</option>
          <option value="taxable">{t('assemblies.tax.status_taxable', { defaultValue: 'Taxable' })}</option>
          <option value="exempt">{t('assemblies.tax.status_exempt', { defaultValue: 'Exempt' })}</option>
          <option value="out_of_scope">{t('assemblies.tax.status_out_of_scope', { defaultValue: 'Out of scope' })}</option>
        </select>
      </label>
      <TextCommit
        testId="tax-rate"
        label={t('assemblies.tax.rate', { defaultValue: 'Tax rate %' })}
        value={profile.tax_rate ?? ''}
        inputMode="decimal"
        placeholder={t('assemblies.tax.rate_placeholder', { defaultValue: 'From tax code' })}
        onCommit={(v) => onChange({ tax_rate: v === '' ? null : v })}
      />
      <TextCommit
        testId="tax-code"
        label={t('assemblies.tax.code', { defaultValue: 'Tax code' })}
        value={profile.tax_code ?? ''}
        placeholder={t('assemblies.tax.code_placeholder', { defaultValue: 'Registry code' })}
        onCommit={(v) => onChange({ tax_code: v === '' ? null : v })}
      />
      <label className="block">
        <div className={labelClass}>{t('assemblies.tax.treatment', { defaultValue: 'Input tax treatment' })}</div>
        <select
          data-testid="tax-treatment"
          value={profile.input_tax_treatment ?? ''}
          onChange={(e) =>
            onChange({ input_tax_treatment: (e.target.value || null) as InputTaxTreatment | null })
          }
          className={fieldClass}
        >
          <option value="">{t('assemblies.tax.treatment_default', { defaultValue: 'Project default' })}</option>
          <option value="recoverable">
            {t('assemblies.tax.treatment_recoverable', { defaultValue: 'Recoverable (not part of the cost)' })}
          </option>
          <option value="cost_incorporated">
            {t('assemblies.tax.treatment_cost_incorporated', { defaultValue: 'Incorporated into the cost' })}
          </option>
        </select>
      </label>
      <label className="flex items-center gap-2 text-sm text-content-primary sm:col-span-2 lg:col-span-4">
        <input
          type="checkbox"
          data-testid="tax-inclusive"
          checked={profile.price_includes_tax === true}
          onChange={(e) => onChange({ price_includes_tax: e.target.checked ? true : null })}
          className="h-4 w-4 rounded border-border"
        />
        {t('assemblies.tax.price_includes', { defaultValue: 'The unit cost already includes the tax' })}
      </label>
    </>
  );
}
