// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Maturity card​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ for one concrete sensor: maturity, estimated strength against
 * the target, hours to target and a small line chart of the maturity series.
 */
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { Card, CardContent, CardHeader } from '@/shared/ui';
import { fmtNumber } from '@/shared/lib/formatters';
import { fetchMaturity, type SensorDevice } from '../api';
import { strengthProgressPct } from '../sensorData';

export function MaturityCard({ device }: { device: SensorDevice }) {
  const { t } = useTranslation();
  const q = useQuery({
    queryKey: ['site-sensors', 'maturity', device.id, device.last_seen_at],
    queryFn: () => fetchMaturity(device.id),
  });
  const m = q.data;
  const pct = strengthProgressPct(m?.strength_mpa, m?.target_strength_mpa);
  const series = (m?.series ?? []).map((p) => ({ ...p, label: new Date(p.t).toLocaleString() }));

  return (
    <Card>
      <CardHeader
        title={`${device.code}${device.pour_ref ? ` - ${device.pour_ref}` : ''}`}
        subtitle={t('site_sensors.maturity.subtitle', { defaultValue: 'Concrete maturity and estimated strength' })}
      />
      <CardContent>
        {q.isLoading ? (
          <p className="text-sm text-content-tertiary">{t('common.loading', { defaultValue: 'Loading...' })}</p>
        ) : !m || series.length === 0 ? (
          <p className="text-sm text-content-tertiary">
            {t('site_sensors.maturity.empty', {
              defaultValue: 'No temperature readings yet. Add readings or connect the sensor to see maturity.',
            })}
          </p>
        ) : (
          <div className="space-y-3">
            <div className="grid grid-cols-3 gap-3 text-sm">
              <div>
                <div className="text-2xs font-medium uppercase tracking-wide text-content-tertiary">
                  {t('site_sensors.maturity.maturity', { defaultValue: 'Maturity' })}
                </div>
                <div className="text-lg font-semibold tabular-nums">
                  {fmtNumber(m.maturity_c_h, 0)} <span className="text-xs font-normal text-content-tertiary">degC-h</span>
                </div>
              </div>
              <div>
                <div className="text-2xs font-medium uppercase tracking-wide text-content-tertiary">
                  {t('site_sensors.maturity.strength', { defaultValue: 'Strength' })}
                </div>
                <div className="text-lg font-semibold tabular-nums">
                  {m.strength_mpa === null ? '-' : fmtNumber(m.strength_mpa, 1)}
                  {m.target_strength_mpa !== null && (
                    <span className="text-xs font-normal text-content-tertiary">
                      {' / '}
                      {fmtNumber(m.target_strength_mpa, 1)} MPa
                    </span>
                  )}
                </div>
              </div>
              <div>
                <div className="text-2xs font-medium uppercase tracking-wide text-content-tertiary">
                  {t('site_sensors.maturity.hours_to_target', { defaultValue: 'Hours to target' })}
                </div>
                <div className="text-lg font-semibold tabular-nums">
                  {m.hours_to_target === null ? '-' : fmtNumber(m.hours_to_target, 1)}
                </div>
              </div>
            </div>
            {pct !== null && (
              <div
                className="h-2 overflow-hidden rounded-full bg-surface-secondary"
                role="progressbar"
                aria-valuemin={0}
                aria-valuemax={100}
                aria-valuenow={Math.round(pct)}
                aria-label={t('site_sensors.maturity.progress', { defaultValue: 'Strength against target' })}
              >
                <div
                  className={pct >= 100 ? 'h-full bg-semantic-success' : 'h-full bg-oe-blue'}
                  style={{ width: `${pct}%` }}
                />
              </div>
            )}
            {m.strength_mpa === null && (
              <p className="text-xs text-content-tertiary">
                {t('site_sensors.maturity.no_mix', {
                  defaultValue: 'Link a concrete mix to this sensor to estimate strength.',
                })}
              </p>
            )}
            <div className="h-36">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={series} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
                  <XAxis dataKey="label" hide />
                  <YAxis width={44} tick={{ fontSize: 11 }} />
                  <Tooltip
                    formatter={(v) => [fmtNumber(Number(v), 0), 'degC-h']}
                    labelStyle={{ fontSize: 11 }}
                    contentStyle={{ fontSize: 12 }}
                  />
                  <Line type="monotone" dataKey="maturity" stroke="var(--oe-blue, #0071e3)" strokeWidth={2} dot={false} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
