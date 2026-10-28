// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Permit conditions of module 2 shown as quality requirements: one check per
// condition, its state following the condition. Read only here; a condition is
// discharged in the permits module and is proven here the moment it is.

import { useTranslation } from 'react-i18next';

import { Badge, type BadgeVariant } from '@/shared/ui/Badge';
import { fmtDate } from '@/shared/lib/formatters';

import type { PermitConditionCheck } from './api';
import { usePermitConditionChecks } from './hooks';
import { Section } from './QualityBits';

const CHECK_TONE: Record<PermitConditionCheck['check_state'], BadgeVariant> = {
  to_prove: 'warning',
  in_verification: 'blue',
  failed: 'error',
  proven: 'success',
  not_required: 'neutral',
};

const CHECK_LABEL: Record<PermitConditionCheck['check_state'], string> = {
  to_prove: 'To prove',
  in_verification: 'In verification',
  failed: 'Failed',
  proven: 'Proven',
  not_required: 'Not required',
};

export function PermitConditionsSection({ projectId }: { projectId: string }) {
  const { t } = useTranslation();
  const checks = usePermitConditionChecks(projectId);
  const data = checks.data;
  // Nothing to show while loading, on an error, or when the project has no permit condition at all.
  if (!data || !data.available || data.items.length === 0) return null;

  return (
    <Section
      testId="permit-conditions"
      title={t('qualityConcept.permitConditions.title', { defaultValue: 'Permit conditions as quality checks' })}
      description={t('qualityConcept.permitConditions.body', {
        defaultValue:
          'Every condition of a permit is a requirement of the quality plan. Its check follows the condition in the permits module.',
      })}
    >
      <p className="mb-2 text-xs text-content-secondary" data-testid="permit-conditions-summary">
        {t('qualityConcept.permitConditions.summary', {
          defaultValue: '{{proven}} of {{total}} proven, {{blocking}} still block the start of construction.',
          proven: data.summary.proven,
          total: data.summary.total,
          blocking: data.summary.blocks_start,
        })}
      </p>
      <ul className="divide-y divide-border-light">
        {data.items.map((c) => (
          <li key={c.condition_id} className="py-2 text-sm" data-testid="permit-condition-row">
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-medium text-content-primary">
                {c.permit_reference} / {c.number}
              </span>
              <Badge variant={CHECK_TONE[c.check_state]} size="sm">
                {t(`qualityConcept.permitConditions.state_${c.check_state}`, { defaultValue: CHECK_LABEL[c.check_state] })}
              </Badge>
              {c.blocks_start && (
                <Badge variant="error" size="sm">
                  {t('qualityConcept.permitConditions.blocks_start', { defaultValue: 'Blocks start' })}
                </Badge>
              )}
              {c.due_date && <span className="text-xs text-content-tertiary">{fmtDate(c.due_date)}</span>}
            </div>
            <p className="mt-0.5 text-content-secondary">{c.requirement}</p>
            {(c.responsible_party || c.evidence_required) && (
              <p className="mt-0.5 text-xs text-content-tertiary">
                {[c.responsible_party, c.evidence_required].filter(Boolean).join(' - ')}
              </p>
            )}
          </li>
        ))}
      </ul>
    </Section>
  );
}
