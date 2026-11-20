// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Excavated against hauled: the loose m3 a volume (cut x swell) or the last
 * stockpile survey measured, next to the m3 its linked haul tickets carried
 * (weighbridge tonnes / density, or loads x truck capacity). Hidden when the
 * haul tickets module is off or no ticket is linked.
 */

import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { AlertTriangle, CheckCircle2 } from 'lucide-react';
import { Card } from '@/shared/ui';
import { fmtFixed } from '@/shared/lib/formatters';
import { hauledVsExcavated } from './volumesApi';

interface Props {
  projectId: string;
  volumeId?: string;
  stockpileId?: string;
}

const m3 = (v: string | null | undefined) => (v == null ? '-' : `${fmtFixed(Number(v), 1)} m³`);

export function HauledVsExcavatedPanel({ projectId, volumeId, stockpileId }: Props) {
  const { t } = useTranslation();
  const target = volumeId ? { volume_id: volumeId } : { stockpile_id: stockpileId! };
  const q = useQuery({
    queryKey: ['haul', 'hauled-vs-excavated', projectId, volumeId ?? stockpileId],
    queryFn: () => hauledVsExcavated(projectId, target),
    retry: false,
    staleTime: 30_000,
  });
  const d = q.data;
  if (!d || d.tickets === 0) return null;
  const over = d.within_threshold === false;
  const pct = d.difference_pct == null ? '-' : `${Number(d.difference_pct) > 0 ? '+' : ''}${fmtFixed(Number(d.difference_pct), 2)} %`;
  return (
    <Card className="space-y-2 p-3" data-testid="hauled-vs-excavated">
      <h3 className="oe-card-title">{t('haulvx.title', { defaultValue: 'Excavated vs hauled' })}</h3>
      <dl className="grid grid-cols-3 gap-2">
        <div>
          <dt className="text-xs text-content-tertiary">
            {t(`haulvx.basis.${d.excavated_basis}`, { defaultValue: 'Excavated' })}
          </dt>
          <dd className="font-mono" data-testid="haulvx-excavated">
            <bdi dir="ltr">{m3(d.excavated_m3)}</bdi>
          </dd>
        </div>
        <div>
          <dt className="text-xs text-content-tertiary">
            {t('haulvx.hauled', { defaultValue: 'Hauled (tickets: {{tickets}}, loads: {{loads}})', tickets: d.tickets, loads: d.loads })}
          </dt>
          <dd className="font-mono" data-testid="haulvx-hauled">
            <bdi dir="ltr">{m3(d.hauled_m3)}</bdi>
          </dd>
        </div>
        <div>
          <dt className="text-xs text-content-tertiary">{t('haulvx.difference', { defaultValue: 'Difference' })}</dt>
          <dd className={`font-mono ${over ? 'text-semantic-warning' : ''}`} data-testid="haulvx-difference">
            <bdi dir="ltr">
              {m3(d.difference_m3)} ({pct})
            </bdi>
          </dd>
        </div>
      </dl>
      <ul className="text-xs text-content-tertiary">
        {d.by_basis.map((b) => (
          <li key={b.basis}>
            {t(`haulvx.from.${b.basis}`, { defaultValue: b.basis })}: <bdi dir="ltr">{m3(b.hauled_m3)}</bdi>{' '}
            {t('haulvx.tickets_n', { defaultValue: '(tickets: {{n}})', n: b.tickets })}
          </li>
        ))}
      </ul>
      {d.within_threshold != null && (
      <p className={`flex items-start gap-2 text-xs ${over ? 'text-semantic-warning' : 'text-semantic-success'}`}>
        {over ? <AlertTriangle size={14} className="mt-0.5" /> : <CheckCircle2 size={14} className="mt-0.5" />}
        {over
          ? t('haulvx.over', {
              defaultValue: 'The difference passes the {{threshold}} % threshold: check tickets, truck capacity and the swell factor.',
              threshold: d.threshold_pct,
            })
          : t('haulvx.within', { defaultValue: 'Within the {{threshold}} % threshold.', threshold: d.threshold_pct })}
      </p>
      )}
    </Card>
  );
}
