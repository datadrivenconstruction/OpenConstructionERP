// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * One point: its readings against the profile bands, the alerts it opened and
 * the Acknowledge note. Acknowledging needs the survey confirm permission.
 */

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Check } from 'lucide-react';
import { Badge, Button, Skeleton, WideModal } from '@/shared/ui';
import { getErrorMessage } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import { acknowledge, getPoint, type Level } from './api';
import { LEVEL_DEFAULT, bandLines, chartGeometry, fmtMm, fmtRate, levelVariant } from './levels';

const W = 560;
const H = 220;
const BAND_COLOUR = { alert: '#d97706', action: '#ea580c', alarm: '#dc2626' } as const;

export function LevelBadge({ level }: { level: Level }) {
  const { t } = useTranslation();
  return (
    <Badge variant={levelVariant(level)} size="sm">
      {level === 'none'
        ? t('survey.monitoring.profile.none', { defaultValue: LEVEL_DEFAULT.none })
        : t(`survey.monitoring.level.${level}`, { defaultValue: LEVEL_DEFAULT[level] })}
    </Badge>
  );
}

interface Props {
  pointId: string | null;
  onClose: () => void;
}

export function PointDrawer({ pointId, onClose }: Props) {
  const { t, i18n } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [note, setNote] = useState('');
  const [asking, setAsking] = useState(false);

  const detail = useQuery({ queryKey: ['monitoring', 'point', pointId], queryFn: () => getPoint(pointId!), enabled: !!pointId });
  const ack = useMutation({
    mutationFn: () => acknowledge(pointId!, note, i18n.language),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['monitoring'] });
      setAsking(false);
      setNote('');
    },
    onError: (e) => addToast({ type: 'error', title: getErrorMessage(e) }),
  });

  const d = detail.data;
  const bands = bandLines(d?.thresholds ?? null);
  const geo = d && d.series.length > 0 ? chartGeometry(d.series, bands, W, H) : null;
  const title = d ? `${d.code}${d.name ? ` ${d.name}` : ''}` : '';

  return (
    <WideModal
      open={!!pointId}
      onClose={onClose}
      size="lg"
      title={title || t('survey.monitoring.drawer.title', { defaultValue: 'Monitoring point' })}
      subtitle={d?.profile_label || undefined}
      footer={
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            {t('common.close', { defaultValue: 'Close' })}
          </Button>
          {d?.ack_state === 'pending' && (
            <Button variant="primary" icon={<Check size={16} />} onClick={() => setAsking(true)} data-testid="mon-ack">
              {t('survey.monitoring.action.acknowledge', { defaultValue: 'Acknowledge' })}
            </Button>
          )}
        </div>
      }
    >
      {detail.isLoading || !d ? (
        <Skeleton className="h-48" />
      ) : (
        <div className="space-y-4" data-testid="mon-drawer">
          <div className="flex flex-wrap items-center gap-3 text-sm">
            <LevelBadge level={d.level} />
            <span>
              <bdi dir="ltr">{fmtMm(d.displacement_mm)}</bdi> {t('survey.monitoring.unit.mm', { defaultValue: 'mm' })}
            </span>
            <span className="text-content-secondary">
              <bdi dir="ltr">{fmtRate(d.rate_mm_day)}</bdi> {t('survey.monitoring.unit.mm_day', { defaultValue: 'mm/day' })}
            </span>
          </div>

          {geo && (
            <svg
              viewBox={`0 0 ${W} ${H}`}
              className="w-full rounded-lg border border-border-light bg-surface-primary"
              role="img"
              aria-label={t('survey.monitoring.drawer.chart', { defaultValue: 'Displacement against the alert bands' })}
              data-testid="mon-chart"
            >
              <line x1={28} x2={W - 28} y1={geo.yOf(0)} y2={geo.yOf(0)} stroke="currentColor" strokeOpacity={0.3} />
              {bands.map((b) => (
                <g key={b.level}>
                  <line
                    x1={28}
                    x2={W - 28}
                    y1={geo.yOf(geo.sign * b.mm)}
                    y2={geo.yOf(geo.sign * b.mm)}
                    stroke={BAND_COLOUR[b.level]}
                    strokeDasharray="4 3"
                  />
                  <text x={W - 26} y={geo.yOf(geo.sign * b.mm) + 3} fontSize={10} fill={BAND_COLOUR[b.level]}>
                    {t(`survey.monitoring.level.${b.level}`, { defaultValue: LEVEL_DEFAULT[b.level] })}
                  </text>
                </g>
              ))}
              <polyline fill="none" stroke="currentColor" strokeWidth={1.5} points={geo.points.map((p) => `${p.x},${p.y}`).join(' ')} />
              {geo.points.map((p, i) => (
                <circle key={i} cx={p.x} cy={p.y} r={4} fill={p.level === 'ok' || p.level === 'none' ? '#16a34a' : BAND_COLOUR[p.level]} />
              ))}
            </svg>
          )}

          <table className="oe-table w-full text-sm">
            <thead>
              <tr>
                <th>{t('survey.monitoring.col.epoch', { defaultValue: 'Epoch' })}</th>
                <th className="text-right">{t('survey.monitoring.col.displacement', { defaultValue: 'Displacement (mm)' })}</th>
                <th className="text-right">{t('survey.monitoring.col.rate', { defaultValue: 'Rate (mm/day)' })}</th>
                <th>{t('survey.monitoring.col.level', { defaultValue: 'Level' })}</th>
              </tr>
            </thead>
            <tbody>
              {d.series.map((s) => (
                <tr key={s.at}>
                  <td>{new Date(s.at).toLocaleDateString(i18n.language)}</td>
                  <td className="text-right"><bdi dir="ltr" className="font-mono">{fmtMm(s.displacement_mm)}</bdi></td>
                  <td className="text-right"><bdi dir="ltr" className="font-mono">{fmtRate(s.rate_mm_day)}</bdi></td>
                  <td><LevelBadge level={s.level} /></td>
                </tr>
              ))}
            </tbody>
          </table>

          {d.alerts.length > 0 && (
            <ul className="space-y-1 text-sm" data-testid="mon-alerts">
              {d.alerts.map((a) => (
                <li key={a.id} className="flex flex-wrap items-center gap-2">
                  <LevelBadge level={a.level} />
                  <span>{new Date(a.observed_at).toLocaleDateString(i18n.language)}</span>
                  <span className="text-content-secondary">
                    {a.acknowledged_at
                      ? t('survey.monitoring.ack.by', {
                          defaultValue: 'Acknowledged by {{name}}: {{note}}',
                          name: a.acknowledged_by_name,
                          note: a.note,
                        })
                      : t('survey.monitoring.ack.open', { defaultValue: 'Not acknowledged yet' })}
                  </span>
                </li>
              ))}
            </ul>
          )}

          {asking && (
            <div className="space-y-2 rounded-lg border border-border-light p-3">
              <label className="oe-label" htmlFor="mon-ack-note">
                {t('survey.monitoring.ack.note', { defaultValue: 'What did you do about it?' })}
              </label>
              <textarea id="mon-ack-note" className="oe-input w-full" rows={3} value={note} onChange={(e) => setNote(e.target.value)} />
              <div className="flex justify-end gap-2">
                <Button size="sm" variant="ghost" onClick={() => setAsking(false)}>
                  {t('common.cancel', { defaultValue: 'Cancel' })}
                </Button>
                <Button size="sm" variant="primary" loading={ack.isPending} onClick={() => ack.mutate()} data-testid="mon-ack-confirm">
                  {t('survey.monitoring.action.acknowledge', { defaultValue: 'Acknowledge' })}
                </Button>
              </div>
            </div>
          )}
        </div>
      )}
    </WideModal>
  );
}
