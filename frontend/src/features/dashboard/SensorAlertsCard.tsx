// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * SensorAlertsCard​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ - dashboard widget: open site sensor alerts by kind, devices
 * online, concrete pours against their target strength and the latest alerts.
 */

import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { ArrowRight } from 'lucide-react';
import { Card, CardContent, CardHeader } from '@/shared/ui';
import { DateDisplay } from '@/shared/ui/DateDisplay';
import { fmtNumber } from '@/shared/lib/formatters';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { fetchSensorSummary } from '@/features/site_sensors/api';
import { strengthProgressPct } from '@/features/site_sensors/sensorData';
import { KpiStrip } from './KpiStrip';

export function SensorAlertsCard() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const projectId = useProjectContextStore((s) => s.activeProjectId) ?? '';
  const q = useQuery({
    queryKey: ['site-sensors', 'summary', projectId],
    queryFn: () => fetchSensorSummary(projectId || undefined),
    staleTime: 60_000,
  });
  const s = q.data;

  if (q.isError) return null;

  const target = projectId ? `/projects/${projectId}/site-sensors` : '/site-sensors';
  const kinds = Object.entries(s?.open_by_kind ?? {});

  return (
    <Card className="h-full">
      <CardHeader
        title={t('dashboard.layout.w_sensor_alerts', { defaultValue: 'Sensor alerts' })}
        subtitle={t('dashboard.sensor_alerts.subtitle', { defaultValue: 'Limits, uptime and concrete strength on site' })}
        action={
          <button
            type="button"
            onClick={() => navigate(target)}
            className="inline-flex items-center gap-1.5 text-xs text-oe-blue hover:underline"
          >
            {t('dashboard.sensor_alerts.open', { defaultValue: 'Open sensors' })}
            <ArrowRight size={11} />
          </button>
        }
      />
      <CardContent>
        {!s || s.devices === 0 ? (
          <p className="text-sm text-content-tertiary">
            {q.isLoading
              ? t('common.loading', { defaultValue: 'Loading...' })
              : t('dashboard.sensor_alerts.empty', {
                  defaultValue:
                    'No site sensors yet. Add a concrete, noise, dust, vibration, weather or water level sensor to be alerted when a limit is passed.',
                })}
          </p>
        ) : (
          <div className="space-y-3">
            <KpiStrip
              stats={[
                {
                  label: t('dashboard.sensor_alerts.open_alerts', { defaultValue: 'Open alerts' }),
                  value: s.open_alerts,
                  tone: s.open_alerts > 0 ? 'text-semantic-error' : 'text-content-secondary',
                },
                {
                  label: t('dashboard.sensor_alerts.online', { defaultValue: 'Online' }),
                  value: `${s.online}/${s.devices}`,
                  tone: s.online < s.devices ? 'text-semantic-warning' : undefined,
                },
              ]}
            />
            {kinds.length > 0 && (
              <div className="flex flex-wrap gap-2 text-xs text-content-secondary">
                {kinds.map(([kind, count]) => (
                  <span key={kind} className="rounded-full border border-border-light px-2 py-0.5">
                    {kind === 'offline'
                      ? t('site_sensors.alerts.kind_offline', { defaultValue: 'Stopped reporting' })
                      : t('site_sensors.alerts.kind_exceedance', { defaultValue: 'Limit exceeded' })}{' '}
                    <span className="font-semibold tabular-nums text-content-primary">{count}</span>
                  </span>
                ))}
              </div>
            )}
            {s.pours.length > 0 && (
              <ul className="space-y-1 text-xs">
                {s.pours.slice(0, 4).map((p) => {
                  const pct = strengthProgressPct(p.strength_mpa, p.target_strength_mpa);
                  return (
                    <li key={`${p.code}-${p.pour_ref}`} className="flex items-center gap-2">
                      <span className="w-24 truncate font-medium text-content-primary">{p.pour_ref || p.code}</span>
                      <span className="h-1.5 flex-1 overflow-hidden rounded-full bg-surface-secondary">
                        <span
                          className={pct !== null && pct >= 100 ? 'block h-full bg-semantic-success' : 'block h-full bg-oe-blue'}
                          style={{ width: `${pct ?? 0}%` }}
                        />
                      </span>
                      <span className="w-28 text-right tabular-nums text-content-secondary">
                        {p.strength_mpa === null ? '-' : fmtNumber(p.strength_mpa, 1)}
                        {p.target_strength_mpa !== null && ` / ${fmtNumber(p.target_strength_mpa, 1)}`} MPa
                      </span>
                    </li>
                  );
                })}
              </ul>
            )}
            {s.latest_alerts.length > 0 && (
              <ul className="divide-y divide-border-light rounded-lg border border-border-light text-xs">
                {s.latest_alerts.map((a) => (
                  <li key={a.id} className="flex items-center gap-2 px-2.5 py-1.5">
                    <span className="text-content-primary">
                      {a.kind === 'offline'
                        ? t('site_sensors.alerts.kind_offline', { defaultValue: 'Stopped reporting' })
                        : t('site_sensors.alerts.kind_exceedance', { defaultValue: 'Limit exceeded' })}
                    </span>
                    {a.value !== null && a.limit !== null && (
                      <span className="tabular-nums text-content-secondary">
                        {a.value} / {a.limit}
                      </span>
                    )}
                    <span className="ml-auto text-content-tertiary">
                      <DateDisplay value={a.raised_at} format="relative" />
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

export default SensorAlertsCard;
