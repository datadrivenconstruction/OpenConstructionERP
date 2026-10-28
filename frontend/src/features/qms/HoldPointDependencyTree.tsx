// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Hold-point dependency visualization for an ITP plan (item 12).
 *
 * Renders the plan's control points in sequence order, drawing the
 * predecessor chain so a site engineer can see at a glance which hold points
 * gate which. Each row carries a traffic-light: a hold/witness point with an
 * unsatisfied predecessor is blocked (red), a hold/witness point is pending
 * (amber), and a review point or satisfied hold point is clear (grey/green).
 */

import { useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { Lock, Eye, FileText, ArrowDown, CircleDot } from 'lucide-react';
import { Badge } from '@/shared/ui';
import type { ITPItem, Inspection } from './api';

// English fallbacks for the computed `qms.hold_point.*` keys. The default used to be
// the raw value, so until the key lands in a locale the screen shows the bare
// enum token to every reader, English included. Unknown values still fall
// through to the previous default.
const HOLD_POINT_LABELS: Record<string, string> = {
  hold: 'Hold point', witness: 'Witness point', review: 'Review point'
};


type Light = 'blocked' | 'pending' | 'passed' | 'review';

const HOLD_ICON = {
  hold: Lock,
  witness: Eye,
  review: FileText,
} as const;

function itemPassed(item: ITPItem, inspections: Inspection[]): boolean {
  return inspections.some((i) => i.itp_item_id === item.id && i.status === 'passed');
}

export function HoldPointDependencyTree({
  items,
  inspections,
}: {
  items: ITPItem[];
  inspections: Inspection[];
}) {
  const { t } = useTranslation();

  const ordered = useMemo(
    () => [...items].sort((a, b) => a.sequence - b.sequence),
    [items],
  );
  const byId = useMemo(() => new Map(items.map((i) => [i.id, i])), [items]);

  if (ordered.length === 0) {
    return (
      <p className="py-4 text-center text-xs text-content-tertiary">
        {t('qms.no_control_points', { defaultValue: 'No control points defined yet.' })}
      </p>
    );
  }

  return (
    <ol className="space-y-0">
      {ordered.map((item, idx) => {
        const Icon = HOLD_ICON[item.hold_witness_point] ?? FileText;
        const passed = itemPassed(item, inspections);
        const isGate = item.hold_witness_point !== 'review';
        const predecessor = item.predecessor_itp_item_id
          ? byId.get(item.predecessor_itp_item_id)
          : undefined;
        const predecessorPassed = predecessor ? itemPassed(predecessor, inspections) : true;

        let light: Light;
        if (!isGate) light = 'review';
        else if (passed) light = 'passed';
        else if (!predecessorPassed) light = 'blocked';
        else light = 'pending';

        const lightColour: Record<Light, string> = {
          blocked: 'text-semantic-error',
          pending: 'text-semantic-warning',
          passed: 'text-semantic-success',
          review: 'text-content-tertiary',
        };
        const lightLabel: Record<Light, string> = {
          blocked: t('qms.hp_blocked', { defaultValue: 'Blocked' }),
          pending: t('qms.hp_pending', { defaultValue: 'Pending' }),
          passed: t('qms.hp_passed', { defaultValue: 'Passed' }),
          review: t('qms.hp_review', { defaultValue: 'Review' }),
        };

        return (
          <li key={item.id}>
            {idx > 0 && (
              <div className="ml-4 flex h-3 items-center">
                <ArrowDown size={12} className="text-border" />
              </div>
            )}
            <div className="flex items-start gap-2 rounded-lg border border-border-light bg-surface-secondary px-3 py-2">
              <Icon size={15} className="mt-0.5 shrink-0 text-content-secondary" />
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span className="truncate text-sm font-medium text-content-primary">
                    {item.sequence}. {item.control_point_name}
                  </span>
                  <Badge variant="neutral">
                    {t(`qms.hold_point.${item.hold_witness_point}`, {
                      defaultValue:
                        HOLD_POINT_LABELS[item.hold_witness_point] ?? item.hold_witness_point.charAt(0).toUpperCase() +
                        item.hold_witness_point.slice(1),
                    })}
                  </Badge>
                </div>
                {predecessor && (
                  <p className="mt-0.5 text-2xs text-content-tertiary">
                    {t('qms.depends_on', {
                      defaultValue: 'Depends on: {{name}}',
                      name: `${predecessor.sequence}. ${predecessor.control_point_name}`,
                    })}
                  </p>
                )}
                {(item.csi_section_ref || item.spec_drawing_ref || item.bim_element_id) && (
                  <p className="mt-0.5 truncate text-2xs text-content-tertiary">
                    {[item.csi_section_ref, item.spec_drawing_ref, item.bim_element_id]
                      .filter(Boolean)
                      .join(' · ')}
                  </p>
                )}
              </div>
              <span
                className={`flex shrink-0 items-center gap-1 text-2xs font-medium ${lightColour[light]}`}
                title={lightLabel[light]}
              >
                <CircleDot size={12} />
                {lightLabel[light]}
              </span>
            </div>
          </li>
        );
      })}
    </ol>
  );
}
