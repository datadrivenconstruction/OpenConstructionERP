// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * "Applies to" on the e-invoice seller settings: all companies (the default)
 * or one company. A company without its own row prints the group's bank and
 * contact details under its own name and tax id; the chip says so.
 */

import { useTranslation } from 'react-i18next';

import { Badge } from '@/shared/ui';

import { useCompanies, useCompaniesUi } from './useCompanies';

export function EInvoiceScopeSelect({ value, onChange }: { value: string; onChange: (next: string) => void }) {
  const { t } = useTranslation();
  const ui = useCompaniesUi();
  const companiesQ = useCompanies(ui.multiCompany);
  if (!ui.multiCompany) return null;
  const companies = companiesQ.data ?? [];
  const picked = companies.find((c) => `entity:${c.id}` === value);
  return (
    <div className="flex flex-wrap items-center gap-2 text-sm" data-testid="einvoice-scope">
      <label className="flex items-center gap-2">
        <span className="text-content-secondary">{t('einvoice.applies_to', { defaultValue: 'Applies to' })}</span>
        <select className="oe-select" value={value} onChange={(e) => onChange(e.target.value)}>
          <option value="default">{t('einvoice.all_companies', { defaultValue: 'All companies (default)' })}</option>
          {companies.map((c) => (
            <option key={c.id} value={`entity:${c.id}`}>
              {c.code} · {c.legal_name || c.name}
            </option>
          ))}
        </select>
      </label>
      {picked && !picked.has_own_einvoice_settings && (
        <Badge variant="neutral" size="sm">
          {t('legal_entities.uses_defaults', { defaultValue: 'Uses defaults' })}
        </Badge>
      )}
    </div>
  );
}
