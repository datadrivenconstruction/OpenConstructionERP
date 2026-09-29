// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The PPE register belongs to the company, not to a project: an issue record
// has no project and every project shows the same list. Without saying so the
// tab reads like the project's own register, and a user who switches projects
// wonders why the same hard hats follow them around.
import { useTranslation } from 'react-i18next';
import { Building2 } from 'lucide-react';

export function PPECompanyRegisterNote() {
  const { t } = useTranslation();
  return (
    <div
      data-testid="ppe-company-register-note"
      className="mb-4 flex items-start gap-2 rounded-lg border border-border-light bg-surface-secondary/50 px-3 py-2 text-xs text-content-secondary"
    >
      <Building2 size={14} className="mt-0.5 shrink-0 text-content-tertiary" aria-hidden="true" />
      <p>
        <span className="font-medium text-content-primary">{t('hse_advanced.ppe_company_register', { defaultValue: 'Company-wide register' })}</span>
        {' - '}
        {t('hse_advanced.ppe_company_register_desc', {
          defaultValue: 'PPE is issued to people, not to a project, so every project shows this same list.',
        })}
      </p>
    </div>
  );
}
