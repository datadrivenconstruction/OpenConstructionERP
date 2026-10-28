// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The readiness criteria of one area on one gate, as a checklist the area
// owner ticks. It helps the owner get to an answer and does not give it: the
// readiness the gate reads stays the status the owner confirms. Who may tick
// is the server's answer (`can_tick`), not a rule worked out here.

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation } from '@tanstack/react-query';

import { fmtDate } from '@/shared/lib/formatters';
import { useToastStore } from '@/stores/useToastStore';

import { setCriterion, type GateArea, type GateCriterion } from './api';
import { catalogueName, refusalText, type LabelContext } from './labels';

export function ReadinessCriteria({
  projectId,
  gateId,
  area,
  labels,
  catalogueId,
  personName,
  onChanged,
}: {
  projectId: string;
  gateId: string;
  area: GateArea;
  labels: LabelContext;
  catalogueId: string;
  personName: (id: string | null | undefined) => string | null;
  onChanged: () => void;
}) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const [saving, setSaving] = useState<string | null>(null);
  const tick = useMutation({
    mutationFn: (c: GateCriterion) =>
      setCriterion(projectId, gateId, area.area_id, c.code, { met: !c.met, note: c.note ?? '' }),
    onMutate: (c) => setSaving(c.code),
    onSuccess: () => onChanged(),
    onError: (err) => addToast({ type: 'error', title: refusalText(t, err) }),
    onSettled: () => setSaving(null),
  });

  const criteria = area.criteria ?? [];
  if (criteria.length === 0) return null;
  const met = criteria.filter((c) => c.met).length;

  return (
    <div className="mt-2 border-t border-border-light pt-2" data-testid="readiness-criteria">
      <p className="flex flex-wrap items-baseline gap-2 text-xs font-semibold text-content-secondary">
        {t('governance.project.gate.criteria', { defaultValue: 'Readiness criteria' })}
        <span className="font-normal text-content-tertiary" data-testid="criteria-progress">
          {t('governance.project.gate.criteria_progress', {
            defaultValue: '{{met}} of {{total}} met',
            met,
            total: criteria.length,
          })}
        </span>
      </p>
      <ul className="mt-1 space-y-1">
        {criteria.map((c) => (
          <li key={c.code} className="text-xs" data-testid="criterion">
            <label className="flex items-start gap-1.5 text-content-primary">
              <input
                type="checkbox"
                className="mt-0.5"
                checked={c.met}
                disabled={!area.can_tick || tick.isPending}
                aria-busy={saving === c.code}
                onChange={() => tick.mutate(c)}
              />
              <span>
                {catalogueName(labels, { kind: 'criterion', code: c.code, catalogueId, label: c.name })}
                {c.note && <span className="block text-content-secondary">{c.note}</span>}
                {c.met && c.ticked_at && (
                  <span className="block text-2xs text-content-tertiary">
                    {t('governance.project.gate.criterion_ticked_by', {
                      defaultValue: 'Ticked by {{name}} on {{date}}',
                      name:
                        personName(c.ticked_by) ??
                        t('governance.project.unknown_person', { defaultValue: 'Project member' }),
                      date: fmtDate(c.ticked_at),
                    })}
                  </span>
                )}
              </span>
            </label>
          </li>
        ))}
      </ul>
      <p className="mt-1 text-2xs text-content-tertiary">
        {t('governance.project.gate.criteria_hint', {
          defaultValue: 'A checklist for the area owner. Readiness still has to be confirmed below.',
        })}
      </p>
    </div>
  );
}
