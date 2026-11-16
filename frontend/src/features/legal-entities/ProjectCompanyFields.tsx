// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Company and Site pickers for a project.
 *
 * Renders nothing until the install has two active companies. Returns two
 * sibling cells, so it drops into a two-column form grid as one row.
 */

import { useEffect } from 'react';
import { useTranslation } from 'react-i18next';

import { defaultCompanyFor, useCompanies, useCompaniesUi } from './useCompanies';

export interface ProjectCompanyValue {
  entityId: string | null;
  branchId: string | null;
}

interface Props {
  value: ProjectCompanyValue;
  onChange: (next: ProjectCompanyValue) => void;
  /** Prefill the person's own company (or the default) when the value is empty. */
  prefill?: boolean;
  disabled?: boolean;
}

export function ProjectCompanyFields({ value, onChange, prefill = false, disabled = false }: Props) {
  const { t } = useTranslation();
  const ui = useCompaniesUi();
  const companiesQ = useCompanies(ui.multiCompany);
  const companies = (companiesQ.data ?? []).filter((c) => c.is_active || c.id === value.entityId);
  const effective = value.entityId ?? ui.defaultEntityId;
  const sites = (companies.find((c) => c.id === effective)?.branches ?? []).filter(
    (b) => b.is_active || b.id === value.branchId,
  );

  useEffect(() => {
    if (prefill && ui.multiCompany && value.entityId === null) {
      const id = defaultCompanyFor(ui.myEntityIds, ui.defaultEntityId);
      if (id) onChange({ entityId: id, branchId: null });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [prefill, ui.multiCompany, ui.defaultEntityId, ui.myEntityIds.join(',')]);

  if (!ui.multiCompany) return null;

  return (
    <>
      <label className="block text-sm" data-testid="project-company">
        <span className="mb-1 block font-medium text-content-primary">
          {t('projects.company', { defaultValue: 'Company' })}
        </span>
        <select
          className="oe-select w-full"
          value={effective ?? ''}
          disabled={disabled}
          onChange={(e) => onChange({ entityId: e.target.value || null, branchId: null })}
        >
          {companies.map((c) => (
            <option key={c.id} value={c.id}>
              {c.code} · {c.legal_name || c.name}
            </option>
          ))}
        </select>
      </label>
      <label className="block text-sm" data-testid="project-site">
        <span className="mb-1 block font-medium text-content-primary">
          {t('projects.site', { defaultValue: 'Site' })}
        </span>
        <select
          className="oe-select w-full"
          value={value.branchId ?? ''}
          disabled={disabled || sites.length === 0}
          onChange={(e) => onChange({ entityId: effective, branchId: e.target.value || null })}
        >
          <option value="">{t('projects.no_site', { defaultValue: 'No site' })}</option>
          {sites.map((b) => (
            <option key={b.id} value={b.id}>
              {b.code} · {b.name}
            </option>
          ))}
        </select>
      </label>
    </>
  );
}
