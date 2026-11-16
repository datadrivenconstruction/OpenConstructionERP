// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/** Company filter for project lists; renders nothing on a single-company install. */

import { useTranslation } from 'react-i18next';

import { useCompanies, useCompaniesUi } from './useCompanies';

export function CompanyFilterSelect({ value, onChange }: { value: string; onChange: (next: string) => void }) {
  const { t } = useTranslation();
  const ui = useCompaniesUi();
  const companiesQ = useCompanies(ui.multiCompany);
  if (!ui.multiCompany) return null;
  return (
    <div className="relative">
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        aria-label={t('projects.filter_company', { defaultValue: 'Filter projects by company' })}
        className="oe-select sm:w-44"
        data-testid="projects-company-filter"
      >
        <option value="all">{t('projects.filter_all_companies', { defaultValue: 'All companies' })}</option>
        {(companiesQ.data ?? []).map((c) => (
          <option key={c.id} value={c.id}>
            {c.code} · {c.name}
          </option>
        ))}
      </select>
    </div>
  );
}
