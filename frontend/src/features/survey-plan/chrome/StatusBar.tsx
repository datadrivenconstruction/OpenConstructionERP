// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/** Status bar: cursor coordinates in the project's axis order and units, snap, scale, CSF, CRS. */

import { useTranslation } from 'react-i18next';
import { AlertTriangle } from 'lucide-react';
import { axisLabelFor, csfMatters, formatCoord, toDisplayOrder } from '../units/linear';
import type { PlanConventions } from '../units/conventions';
import { RESIDUAL_WARN_MM } from '../engine/viewTransform';
import type { GridXY, SnapResult } from '../types';
import { SNAP_LABEL, SnapIcon } from './SnapGlyph';
import { fmtFixed } from '@/shared/lib/formatters';
import { useNumberLocale } from '@/stores/usePreferencesStore';

interface Props {
  cursor: GridXY | null;
  snap: SnapResult | null;
  snapOn: boolean;
  conventions: PlanConventions;
  scale: number | null;
  csf: number | null;
  crsName: string;
  residualMm: number | null;
  selected: number;
  dirty: boolean;
}

export function StatusBar({ cursor, snap, snapOn, conventions, scale, csf, crsName, residualMm, selected, dirty }: Props) {
  const { t } = useTranslation();
  useNumberLocale(); // re-render when the number locale moves
  const labels = axisLabelFor(conventions.axis);
  const ordered = cursor ? toDisplayOrder(cursor[0], cursor[1], conventions.axis) : null;
  const firstIsE = conventions.axis === 'EN' || conventions.axis === 'YX';
  const names = firstIsE ? [labels.e, labels.n] : [labels.n, labels.e];
  return (
    <div
      className="flex min-h-8 flex-wrap items-center gap-x-4 gap-y-1 border-t border-border-light bg-surface-elevated px-3 py-1 text-xs text-content-secondary"
      data-testid="plan-status-bar"
      role="status"
    >
      <span className="inline-flex min-w-[15rem] gap-3 font-mono tabular-nums" data-testid="plan-status-coords">
        {ordered ? (
          <bdi dir="ltr">
            {names[0]} {formatCoord(ordered[0], conventions)}
            {'   '}
            {names[1]} {formatCoord(ordered[1], conventions)}
          </bdi>
        ) : (
          <span className="text-content-tertiary">{t('plan.status.off_map', { defaultValue: 'Move over the plan' })}</span>
        )}
      </span>
      <span className="inline-flex items-center gap-1">
        {snap ? (
          <>
            <SnapIcon kind={snap.kind} size={12} />
            {t(SNAP_LABEL[snap.kind][0], { defaultValue: SNAP_LABEL[snap.kind][1] })}
            {snap.targetLabel ? ` ${snap.targetLabel}` : ''}
          </>
        ) : (
          <span className="text-content-tertiary">
            {snapOn ? t('plan.status.snap_on', { defaultValue: 'Snap on' }) : t('plan.status.snap_off', { defaultValue: 'Snap off (F3)' })}
          </span>
        )}
      </span>
      {selected > 0 && <span>{t('plan.status.selected', { defaultValue: '{{count}} selected', count: selected })}</span>}
      <span className="ms-auto inline-flex flex-wrap items-center gap-x-4">
        {dirty && <span className="font-medium text-semantic-warning">{t('plan.status.unsaved', { defaultValue: 'Unsaved changes' })}</span>}
        {scale != null && (
          <bdi dir="ltr" className="font-mono tabular-nums">
            1:{fmtFixed(Math.round(scale), 0)}
          </bdi>
        )}
        {csf != null && (
          <span title={t('plan.status.csf_hint', { defaultValue: 'Combined scale factor: grid distance = ground distance x CSF' })}>
            CSF <bdi dir="ltr" className={`font-mono tabular-nums ${csfMatters(csf) ? 'text-content-primary' : ''}`}>{fmtFixed(csf, 8)}</bdi>
          </span>
        )}
        {residualMm != null && residualMm > RESIDUAL_WARN_MM && (
          <span className="inline-flex items-center gap-1 text-semantic-warning" data-testid="plan-residual-warning">
            <AlertTriangle size={12} aria-hidden />
            {t('plan.status.residual', { defaultValue: 'Map display off by up to {{mm}} mm; coordinates stay exact', mm: fmtFixed(residualMm, 1) })}
          </span>
        )}
        <span className="max-w-[16rem] truncate" title={crsName}>
          {crsName || t('plan.status.local_grid', { defaultValue: 'Local grid' })}
        </span>
      </span>
    </div>
  );
}
