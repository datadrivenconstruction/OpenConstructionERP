// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Open permit conditions of module 2 as requirements every lot still to be
// awarded inherits. Read only: the conditions are kept in the permits module.

import { useTranslation } from 'react-i18next';

import { Badge } from '@/shared/ui/Badge';
import { fmtDate } from '@/shared/lib/formatters';

import { usePermitLotRequirements } from './hooks';

export function PermitLotRequirementsSection({ projectId }: { projectId: string }) {
  const { t } = useTranslation();
  const reqs = usePermitLotRequirements(projectId);
  const data = reqs.data;
  if (!data || !data.available || data.items.length === 0) return null;

  return (
    <section className="rounded-lg border border-border bg-surface-elevated shadow-sm p-4" data-testid="permit-lot-requirements">
      <h3 className="text-sm font-semibold text-content-primary">
        {t('procurement_concept.ui.permit_conditions.title', { defaultValue: 'Permit conditions for every lot' })}
      </h3>
      <p className="mt-1 text-xs text-content-secondary">
        {t('procurement_concept.ui.permit_conditions.body', {
          defaultValue: 'Open conditions of the permits bind the works. Every lot still to be awarded inherits them as a requirement.',
        })}{' '}
        {t('procurement_concept.ui.permit_conditions.tender_count', {
          defaultValue: '{{count}} go into the tender documents.',
          count: data.tender_count,
        })}
      </p>
      <ul className="mt-3 divide-y divide-border-light">
        {data.items.map((r) => (
          <li key={r.condition_id} className="py-2 text-sm" data-testid="permit-lot-requirement">
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-medium text-content-primary">
                {r.permit_reference} / {r.number}
              </span>
              <Badge variant={r.for_tender_documents ? 'blue' : 'neutral'} size="sm">
                {r.for_tender_documents
                  ? t('procurement_concept.ui.permit_conditions.in_tender', { defaultValue: 'In tender documents' })
                  : t('procurement_concept.ui.permit_conditions.owner_only', { defaultValue: 'Owner only' })}
              </Badge>
              {r.due_date && <span className="text-xs text-content-tertiary">{fmtDate(r.due_date)}</span>}
            </div>
            <p className="mt-0.5 text-content-secondary">{r.requirement}</p>
            {r.responsible_party && <p className="mt-0.5 text-xs text-content-tertiary">{r.responsible_party}</p>}
          </li>
        ))}
      </ul>
    </section>
  );
}
