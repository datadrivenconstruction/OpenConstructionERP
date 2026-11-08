// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Maturity card​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ for one concrete sensor: maturity, estimated strength against
 * the target, hours to target as a range, the datum or activation energy the
 * index uses and a small line chart of the series.
 */
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { Card, CardContent, CardHeader } from '@/shared/ui';
import { fmtNumber, formatDateValue } from '@/shared/lib/formatters';
import { fetchMaturity, type SensorDevice } from '../api';
import { hoursRange, strengthProgressPct } from '../sensorData';
import { useSensorUnits } from '../useSensorUnits';
import { toDisplay } from '../units';

export function MaturityCard({ device }: { device: SensorDevice }) {
  const { t } = useTranslation();
  const u = useSensorUnits(device.project_id);
  const q = useQuery({
    queryKey: ['site-sensors', 'maturity', device.id, device.last_seen_at],
    queryFn: () => fetchMaturity(device.id),
  });
  const m = q.data;
  const pct = strengthProgressPct(m?.strength_mpa, m?.target_strength_mpa);
  const indexKey = m?.index_unit === 'h' ? 'h' : 'degC_h';
  const indexUnit = u.unitFor(indexKey);
  const series = (m?.series ?? []).map((p) => ({
    ...p,
    maturity: toDisplay(p.maturity, indexKey, u.system).value,
    label: formatDateValue(p.t, { dateStyle: 'short', timeStyle: 'medium' }),
  }));
  const range = hoursRange(m?.hours_to_target_range);
  const status = m?.strength_status;

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
                  {m.index_unit === 'h'
                    ? t('site_sensors.maturity.equivalent_age', { defaultValue: 'Equivalent age' })
                    : t('site_sensors.maturity.maturity', { defaultValue: 'Maturity' })}
                </div>
                <div className="text-lg font-semibold tabular-nums">
                  {u.num(m.maturity_c_h, indexKey)} <span className="text-xs font-normal text-content-tertiary">{indexUnit}</span>
                </div>
              </div>
              <div>
                <div className="text-2xs font-medium uppercase tracking-wide text-content-tertiary">
                  {t('site_sensors.maturity.strength', { defaultValue: 'Strength' })}
                </div>
                <div className="text-lg font-semibold tabular-nums">
                  {u.num(m.strength_mpa, 'mpa')}
                  <span className="text-xs font-normal text-content-tertiary">
                    {m.target_strength_mpa !== null ? ` / ${u.show(m.target_strength_mpa, 'mpa')}` : ` ${u.unitFor('mpa')}`}
                  </span>
                </div>
              </div>
              <div>
                <div className="text-2xs font-medium uppercase tracking-wide text-content-tertiary">
                  {t('site_sensors.maturity.hours_to_target', { defaultValue: 'Hours to target' })}
                </div>
                <div className="text-lg font-semibold tabular-nums">
                  {range === null
                    ? '-'
                    : range[0] === range[1]
                      ? `${fmtNumber(range[0], 0)} ${u.label('h')}`
                      : `${fmtNumber(range[0], 0)}-${fmtNumber(range[1], 0)} ${u.label('h')}`}
                </div>
              </div>
            </div>
            <p className="text-xs text-content-tertiary">
              {m.method === 'equivalent_age'
                ? t('site_sensors.maturity.arrhenius', {
                    defaultValue: 'Equivalent age, activation energy {{ea}} kJ/mol, reference {{tr}}',
                    ea: fmtNumber(m.activation_energy_kj_mol ?? 40, 0),
                    tr: u.show(m.reference_temp_c ?? 20, 'degC'),
                  })
                : t('site_sensors.maturity.datum', {
                    defaultValue: 'Nurse-Saul, datum temperature {{datum}}',
                    datum: u.show(m.datum_temp_c, 'degC'),
                  })}
            </p>
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
            {m.mix_id === null ? (
              <p className="text-xs text-content-tertiary">
                {t('site_sensors.maturity.no_mix', {
                  defaultValue: 'Link a concrete mix to this sensor to estimate strength.',
                })}
              </p>
            ) : status === 'below_range' ? (
              <p className="text-xs text-content-tertiary">
                {t('site_sensors.maturity.below_range', {
                  defaultValue: 'Below the first calibration cube: no strength estimate yet.',
                })}
              </p>
            ) : status === 'above_range' ? (
              <p className="text-xs font-medium text-semantic-warning">
                {t('site_sensors.maturity.above_range', {
                  defaultValue: 'Past the last calibration cube: the strength is extrapolated.',
                })}
              </p>
            ) : status === 'uncalibrated' ? (
              <p className="text-xs text-content-tertiary">
                {t('site_sensors.maturity.uncalibrated', {
                  defaultValue: 'The mix curve has no calibration cubes yet.',
                })}
              </p>
            ) : null}
            <div className="h-36">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={series} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
                  <XAxis dataKey="label" hide />
                  <YAxis width={44} tick={{ fontSize: 11 }} />
                  <Tooltip
                    formatter={(v) => [fmtNumber(Number(v), 0), indexUnit]}
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
