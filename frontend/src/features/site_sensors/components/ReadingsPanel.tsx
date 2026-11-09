// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Readings of one device: a chart where hand-entered points have their own
 * marker, a form to add a reading, a CSV paste or import with a row preview,
 * the hand-entered readings with edit and delete for their author or a
 * manager, the audit trail, and the device limits with the reason for an override.
 */
import { useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Pencil, Trash2, Upload } from 'lucide-react';
import { Button, Card, CardContent, CardHeader } from '@/shared/ui';
import { DateDisplay } from '@/shared/ui/DateDisplay';
import { getErrorMessage } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import { useAuthStore } from '@/stores/useAuthStore';
import {
  addSensorReadings,
  deleteReading,
  editReading,
  fetchReadingAudit,
  fetchReadings,
  updateSensorDevice,
  type RawReading,
  type SensorDevice,
  type UserReadingsReport,
} from '../api';
import { parseReadingsCsv, validReadings, type CsvRowError } from '../readingsCsv';
import { isoFromLocal, localDateTimeValue, outsideLimits } from '../sensorData';

const FIELD = 'h-9 rounded-lg border border-border-light bg-surface-primary px-3 text-sm text-content-primary';
const LABEL = 'text-xs text-content-secondary';
const W = 560;
const H = 160;
const WINDOW_DAYS = 14;

function ReadingsChart({ rows, upper, lower, label }: { rows: RawReading[]; upper: number | null; lower: number | null; label: string }) {
  const geo = useMemo(() => {
    if (rows.length === 0) return null;
    const ts = rows.map((r) => Date.parse(r.t));
    const vs = rows.map((r) => r.v);
    const t0 = Math.min(...ts);
    const t1 = Math.max(...ts);
    const lo = Math.min(...vs, lower ?? Infinity, upper ?? Infinity);
    const hi = Math.max(...vs, upper ?? -Infinity, lower ?? -Infinity);
    const x = (t: number) => (t1 === t0 ? W / 2 : ((t - t0) / (t1 - t0)) * (W - 8) + 4);
    const y = (v: number) => H - 6 - ((v - lo) / (hi - lo || 1)) * (H - 12);
    const device = rows.map((r, i) => ({ r, cx: x(ts[i] ?? t0), cy: y(r.v) }));
    const line = device
      .filter((p) => p.r.source === 'device')
      .map((p, i) => `${i ? 'L' : 'M'}${Math.round(p.cx * 10) / 10},${Math.round(p.cy * 10) / 10}`)
      .join(' ');
    return { device, line, upperY: upper === null ? null : y(upper), lowerY: lower === null ? null : y(lower) };
  }, [rows, upper, lower]);
  if (!geo) return null;
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="h-40 w-full" role="img" aria-label={label}>
      {geo.upperY !== null && <line x1={0} x2={W} y1={geo.upperY} y2={geo.upperY} stroke="currentColor" strokeDasharray="4 3" className="text-semantic-error" />}
      {geo.lowerY !== null && <line x1={0} x2={W} y1={geo.lowerY} y2={geo.lowerY} stroke="currentColor" strokeDasharray="4 3" className="text-semantic-warning" />}
      {geo.line && <path d={geo.line} fill="none" stroke="var(--oe-blue, #0071e3)" strokeWidth={1.5} />}
      {geo.device
        .filter((p) => p.r.source !== 'device')
        .map((p) =>
          p.r.source === 'manual' ? (
            <circle key={p.r.t} cx={p.cx} cy={p.cy} r={4.5} className="fill-semantic-warning stroke-surface-primary" strokeWidth={1.5}>
              <title>{p.r.note || p.r.entered_by_name}</title>
            </circle>
          ) : (
            <rect key={p.r.t} x={p.cx - 4} y={p.cy - 4} width={8} height={8} className="fill-content-secondary stroke-surface-primary" strokeWidth={1.5}>
              <title>{p.r.note || p.r.entered_by_name}</title>
            </rect>
          ),
        )}
    </svg>
  );
}

export function ReadingsPanel({ devices }: { devices: SensorDevice[] }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const userId = useAuthStore((s) => s.userId);
  const role = useAuthStore((s) => s.userRole);
  const isManager = role === 'admin' || role === 'manager';
  const onError = (e: unknown) =>
    addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: getErrorMessage(e) });

  const [deviceId, setDeviceId] = useState('');
  const device = devices.find((d) => d.id === deviceId) ?? null;
  const since = useMemo(() => new Date(Date.now() - WINDOW_DAYS * 86_400_000).toISOString(), [deviceId]);
  const readQ = useQuery({
    queryKey: ['site-sensors', 'readings', deviceId],
    queryFn: () => fetchReadings(deviceId, since),
    enabled: !!deviceId,
  });
  const [showAudit, setShowAudit] = useState(false);
  const auditQ = useQuery({
    queryKey: ['site-sensors', 'reading-audit', deviceId],
    queryFn: () => fetchReadingAudit(deviceId),
    enabled: !!deviceId && showAudit,
  });
  const refresh = () => qc.invalidateQueries({ queryKey: ['site-sensors'] });
  const raw = readQ.data?.raw ?? [];
  const hand = raw.filter((r) => r.source !== 'device').slice(-20).reverse();
  const upper = device?.effective_limit ?? null;
  const lower = device?.lower_limit === null || device?.lower_limit === undefined ? null : Number(device.lower_limit);

  const report = (r: UserReadingsReport) => {
    refresh();
    if (r.skipped > 0) {
      addToast({
        type: 'warning',
        title: t('site_sensors.readings.skipped', {
          defaultValue: 'Readings skipped, a reading already exists at that time: {{n}}',
          n: r.skipped,
        }),
      });
    }
    if (r.exceedances > 0) {
      addToast({ type: 'warning', title: t('site_sensors.forms.limit_exceeded', { defaultValue: 'Limit exceeded' }) });
    }
  };

  // One reading by hand.
  const [value, setValue] = useState('');
  const [note, setNote] = useState('');
  const [at, setAt] = useState(() => localDateTimeValue());
  const addMut = useMutation({
    mutationFn: () => {
      const iso = isoFromLocal(at);
      if (!iso) throw new Error(t('site_sensors.forms.bad_time', { defaultValue: 'Enter a valid date and time.' }));
      return addSensorReadings(deviceId, [{ recorded_at: iso, value: Number(value), note: note.trim() }]);
    },
    onSuccess: (r) => {
      setValue('');
      setNote('');
      setAt(localDateTimeValue());
      report(r);
    },
    onError,
  });

  // Paste or import CSV.
  const [csv, setCsv] = useState('');
  const fileRef = useRef<HTMLInputElement>(null);
  const preview = useMemo(() => parseReadingsCsv(csv), [csv]);
  const good = validReadings(preview);
  const bad = preview.filter((r) => r.error);
  const errorText = (e: CsvRowError) =>
    ({
      bad_time: t('site_sensors.import.bad_time', { defaultValue: 'Time not recognised' }),
      bad_value: t('site_sensors.import.bad_value', { defaultValue: 'Value is not a number' }),
      duplicate_time: t('site_sensors.import.duplicate_time', { defaultValue: 'Same time twice' }),
      too_many: t('site_sensors.import.too_many', { defaultValue: 'More than 5000 rows' }),
    })[e];
  const importMut = useMutation({
    mutationFn: () => addSensorReadings(deviceId, good, 'import'),
    onSuccess: (r) => {
      setCsv('');
      report(r);
    },
    onError,
  });

  // Edit and delete hand-entered readings.
  const [editing, setEditing] = useState<{ t: string; value: string; note: string } | null>(null);
  const editMut = useMutation({
    mutationFn: () =>
      editReading(deviceId, { recorded_at: editing?.t ?? '', value: Number(editing?.value), note: editing?.note.trim() ?? '' }),
    onSuccess: () => {
      setEditing(null);
      refresh();
    },
    onError,
  });
  const delMut = useMutation({ mutationFn: (when: string) => deleteReading(deviceId, when), onSuccess: refresh, onError });
  const mayChange = (r: RawReading) => isManager || (!!userId && r.entered_by === userId);

  // Device limits and the reason for them.
  const [limitEdit, setLimitEdit] = useState<{ upper: string; lower: string; reason: string } | null>(null);
  const limitMut = useMutation({
    mutationFn: () =>
      updateSensorDevice(deviceId, {
        limit_value: limitEdit?.upper.trim() || null,
        lower_limit: limitEdit?.lower.trim() || null,
        limit_note: limitEdit?.reason.trim() ?? '',
      }),
    onSuccess: () => {
      setLimitEdit(null);
      refresh();
    },
    onError,
  });
  const overridesCountry = !!device && device.country_limit !== null && device.limit_value !== null;
  const needsReason = !!limitEdit && !!device && device.kind !== 'custom' && limitEdit.upper.trim() !== '' && !limitEdit.reason.trim();

  const sourceLabel = (r: RawReading) =>
    r.source === 'manual'
      ? t('site_sensors.readings.source_manual', { defaultValue: 'Entered by hand' })
      : t('site_sensors.readings.source_import', { defaultValue: 'Imported' });

  return (
    <Card id="sensor-readings">
      <CardHeader
        title={t('site_sensors.readings.title', { defaultValue: 'Readings' })}
        subtitle={t('site_sensors.readings.subtitle', {
          defaultValue: 'Add readings by hand or from a CSV on any device. Connected sensors post their own with a device token.',
        })}
      />
      <CardContent>
        <select
          value={deviceId}
          onChange={(e) => {
            setDeviceId(e.target.value);
            setEditing(null);
            setLimitEdit(null);
          }}
          aria-label={t('site_sensors.forms.device', { defaultValue: 'Device' })}
          className={`${FIELD} w-full`}
        >
          <option value="">{t('site_sensors.forms.pick_device', { defaultValue: 'Choose a device' })}</option>
          {devices.map((d) => (
            <option key={d.id} value={d.id}>
              {d.code} {d.name} {d.unit ? `(${d.unit})` : ''}
            </option>
          ))}
        </select>

        {device && (
          <div className="mt-4 space-y-5">
            <div>
              <ReadingsChart
                rows={raw}
                upper={upper}
                lower={lower}
                label={t('site_sensors.readings.chart', { defaultValue: 'Readings of the last 14 days against the limits' })}
              />
              <div className="mt-1 flex flex-wrap gap-4 text-2xs text-content-tertiary">
                <span>
                  <span className="mr-1 inline-block h-0.5 w-4 align-middle" style={{ background: 'var(--oe-blue, #0071e3)' }} />
                  {t('site_sensors.readings.legend_device', { defaultValue: 'From the device' })}
                </span>
                <span>
                  <span className="mr-1 inline-block h-2 w-2 rounded-full bg-semantic-warning align-middle" />
                  {t('site_sensors.readings.source_manual', { defaultValue: 'Entered by hand' })}
                </span>
                <span>
                  <span className="mr-1 inline-block h-2 w-2 bg-content-secondary align-middle" />
                  {t('site_sensors.readings.source_import', { defaultValue: 'Imported' })}
                </span>
              </div>
              {raw.length === 0 && !readQ.isLoading && (
                <p className="text-sm text-content-tertiary">{t('site_sensors.devices.never', { defaultValue: 'No readings yet' })}</p>
              )}
            </div>

            <div className="rounded-lg border border-border-light p-3 text-sm">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-medium text-content-primary">{t('site_sensors.limits.title', { defaultValue: 'Limits' })}</span>
                {device.record_only ? (
                  <span className="text-content-secondary">{t('site_sensors.custom.record_only', { defaultValue: 'Record only, no limit check' })}</span>
                ) : (
                  <span className="tabular-nums text-content-secondary">
                    {lower !== null && t('site_sensors.limits.lower_value', { defaultValue: 'min {{value}}', value: lower })}
                    {lower !== null && upper !== null && ' / '}
                    {upper !== null && t('site_sensors.limits.upper_value', { defaultValue: 'max {{value}}', value: upper })}
                    {device.unit ? ` ${device.unit}` : ''}
                  </span>
                )}
                {device.limit_note && <span className="italic text-content-tertiary">({device.limit_note})</span>}
                {overridesCountry && (
                  <span className="text-xs text-content-tertiary">
                    {t('site_sensors.limits.overrides', {
                      defaultValue: 'Replaces the country limit of {{value}} ({{source}})',
                      value: device.country_limit,
                      source: device.country_limit_source,
                    })}
                  </span>
                )}
                {isManager && !limitEdit && (
                  <Button
                    variant="ghost"
                    size="sm"
                    icon={<Pencil size={13} />}
                    onClick={() =>
                      setLimitEdit({ upper: device.limit_value ?? '', lower: device.lower_limit ?? '', reason: device.limit_note })
                    }
                  >
                    {t('site_sensors.limits.edit', { defaultValue: 'Change limits' })}
                  </Button>
                )}
              </div>
              {limitEdit && (
                <div className="mt-3 grid grid-cols-2 gap-3">
                  <label className={LABEL}>
                    {t('site_sensors.custom.upper', { defaultValue: 'Upper limit' })}
                    <input type="number" step="any" value={limitEdit.upper} onChange={(e) => setLimitEdit({ ...limitEdit, upper: e.target.value })} className={`${FIELD} mt-1 w-full`} />
                  </label>
                  <label className={LABEL}>
                    {t('site_sensors.custom.lower', { defaultValue: 'Lower limit' })}
                    <input type="number" step="any" value={limitEdit.lower} onChange={(e) => setLimitEdit({ ...limitEdit, lower: e.target.value })} className={`${FIELD} mt-1 w-full`} />
                  </label>
                  <label className={`${LABEL} col-span-2`}>
                    {t('site_sensors.limits.reason', { defaultValue: 'Reason or source of the limit' })}
                    <input type="text" maxLength={300} value={limitEdit.reason} onChange={(e) => setLimitEdit({ ...limitEdit, reason: e.target.value })} className={`${FIELD} mt-1 w-full`} />
                    <span className="mt-1 block text-2xs text-content-tertiary">
                      {t('site_sensors.limits.reason_hint', {
                        defaultValue: 'Blank upper limit uses the country default. A limit that replaces it needs a reason.',
                      })}
                    </span>
                  </label>
                  <div className="col-span-2 flex gap-2">
                    <Button variant="primary" size="sm" disabled={needsReason} loading={limitMut.isPending} onClick={() => limitMut.mutate()}>
                      {t('common.save', { defaultValue: 'Save' })}
                    </Button>
                    <Button variant="ghost" size="sm" onClick={() => setLimitEdit(null)}>
                      {t('common.cancel', { defaultValue: 'Cancel' })}
                    </Button>
                  </div>
                </div>
              )}
            </div>

            <div className="grid gap-5 lg:grid-cols-2">
              <div>
                <h4 className="text-sm font-semibold text-content-primary">{t('site_sensors.readings.add', { defaultValue: 'Add reading' })}</h4>
                <div className="mt-2 grid grid-cols-2 gap-3">
                  <label className={LABEL}>
                    {t('site_sensors.forms.recorded_at', { defaultValue: 'Recorded at' })}
                    <input type="datetime-local" value={at} onChange={(e) => setAt(e.target.value)} className={`${FIELD} mt-1 w-full`} />
                  </label>
                  <label className={LABEL}>
                    {t('site_sensors.forms.value', { defaultValue: 'Value' })} {device.unit ? `(${device.unit})` : ''}
                    <input type="number" step="any" value={value} onChange={(e) => setValue(e.target.value)} className={`${FIELD} mt-1 w-full`} />
                  </label>
                  <label className={`${LABEL} col-span-2`}>
                    {t('site_sensors.readings.note', { defaultValue: 'Note' })}
                    <input type="text" maxLength={500} value={note} onChange={(e) => setNote(e.target.value)} className={`${FIELD} mt-1 w-full`} />
                  </label>
                </div>
                <Button
                  className="mt-3"
                  variant="primary"
                  size="sm"
                  disabled={value.trim() === '' || !Number.isFinite(Number(value))}
                  loading={addMut.isPending}
                  onClick={() => addMut.mutate()}
                >
                  {t('site_sensors.forms.save_reading', { defaultValue: 'Save reading' })}
                </Button>
              </div>

              <div>
                <h4 className="text-sm font-semibold text-content-primary">{t('site_sensors.import.title', { defaultValue: 'Paste or import CSV' })}</h4>
                <textarea
                  value={csv}
                  onChange={(e) => setCsv(e.target.value)}
                  rows={4}
                  placeholder={t('site_sensors.import.placeholder', { defaultValue: 'time,value,note per line, e.g. 2026-11-02 08:00,42.5,meter check' })}
                  aria-label={t('site_sensors.import.title', { defaultValue: 'Paste or import CSV' })}
                  className="mt-2 w-full rounded-lg border border-border-light bg-surface-primary px-3 py-2 font-mono text-xs text-content-primary"
                />
                <input
                  ref={fileRef}
                  type="file"
                  accept=".csv,.txt,text/csv,text/plain"
                  className="hidden"
                  onChange={(e) => {
                    const f = e.target.files?.[0];
                    if (f) void f.text().then(setCsv);
                    e.target.value = '';
                  }}
                />
                <div className="mt-2 flex flex-wrap items-center gap-2">
                  <Button variant="secondary" size="sm" icon={<Upload size={13} />} onClick={() => fileRef.current?.click()}>
                    {t('site_sensors.import.choose_file', { defaultValue: 'Choose file' })}
                  </Button>
                  <Button variant="primary" size="sm" disabled={good.length === 0} loading={importMut.isPending} onClick={() => importMut.mutate()}>
                    {t('site_sensors.import.save', { defaultValue: 'Save readings: {{n}}', n: good.length })}
                  </Button>
                  {preview.length > 0 && (
                    <span className="text-xs text-content-secondary">
                      {t('site_sensors.import.summary', {
                        defaultValue: '{{good}} ready, {{bad}} with errors',
                        good: good.length,
                        bad: bad.length,
                      })}
                    </span>
                  )}
                </div>
                {preview.length > 0 && (
                  <table className="mt-2 w-full text-xs">
                    <tbody>
                      {preview.slice(0, 50).map((r) => (
                        <tr key={r.line} className={r.error ? 'text-semantic-error' : 'text-content-secondary'}>
                          <td className="pr-2 tabular-nums">{r.line}</td>
                          <td className="pr-2 tabular-nums">{r.reading ? <DateDisplay value={r.reading.recorded_at} format="datetime" /> : r.raw}</td>
                          <td className="pr-2 tabular-nums">{r.reading?.value}</td>
                          <td>{r.error ? errorText(r.error) : (r.reading?.note ?? '')}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>
            </div>

            <div>
              <div className="flex items-center gap-2">
                <h4 className="text-sm font-semibold text-content-primary">{t('site_sensors.readings.hand_title', { defaultValue: 'Readings entered by people' })}</h4>
                <Button variant="ghost" size="sm" onClick={() => setShowAudit(!showAudit)}>
                  {showAudit
                    ? t('site_sensors.readings.hide_audit', { defaultValue: 'Hide history' })
                    : t('site_sensors.readings.show_audit', { defaultValue: 'Show history' })}
                </Button>
              </div>
              {hand.length === 0 ? (
                <p className="mt-1 text-sm text-content-tertiary">{t('site_sensors.readings.hand_empty', { defaultValue: 'None in the last 14 days.' })}</p>
              ) : (
                <ul className="mt-2 divide-y divide-border-light rounded-lg border border-border-light">
                  {hand.map((r) => {
                    const out = !device.record_only && outsideLimits(r.v, upper, lower);
                    const isEditing = editing?.t === r.t;
                    return (
                      <li key={r.t} className="flex flex-wrap items-center gap-3 px-3 py-2 text-sm">
                        <span className="text-xs text-content-tertiary"><DateDisplay value={r.t} format="datetime" /></span>
                        {isEditing && editing ? (
                          <>
                            <input type="number" step="any" value={editing.value} aria-label={t('site_sensors.forms.value', { defaultValue: 'Value' })} onChange={(e) => setEditing({ ...editing, value: e.target.value })} className={`${FIELD} w-24`} />
                            <input type="text" maxLength={500} value={editing.note} aria-label={t('site_sensors.readings.note', { defaultValue: 'Note' })} onChange={(e) => setEditing({ ...editing, note: e.target.value })} className={`${FIELD} flex-1`} />
                            <Button variant="primary" size="sm" disabled={!Number.isFinite(Number(editing.value)) || editing.value.trim() === ''} loading={editMut.isPending} onClick={() => editMut.mutate()}>
                              {t('common.save', { defaultValue: 'Save' })}
                            </Button>
                            <Button variant="ghost" size="sm" onClick={() => setEditing(null)}>
                              {t('common.cancel', { defaultValue: 'Cancel' })}
                            </Button>
                          </>
                        ) : (
                          <>
                            <span className={`tabular-nums ${out ? 'font-semibold text-semantic-error' : 'text-content-primary'}`}>
                              {r.v} {device.unit}
                            </span>
                            <span className="text-xs text-content-secondary">{sourceLabel(r)}{r.entered_by_name ? `, ${r.entered_by_name}` : ''}</span>
                            {r.note && <span className="text-xs italic text-content-tertiary">{r.note}</span>}
                            {mayChange(r) && (
                              <span className="ml-auto flex gap-1">
                                <Button variant="ghost" size="sm" aria-label={t('common.edit', { defaultValue: 'Edit' })} icon={<Pencil size={13} />} onClick={() => setEditing({ t: r.t, value: String(r.v), note: r.note })} />
                                <Button variant="ghost" size="sm" aria-label={t('common.delete', { defaultValue: 'Delete' })} icon={<Trash2 size={13} />} loading={delMut.isPending && delMut.variables === r.t} onClick={() => delMut.mutate(r.t)} />
                              </span>
                            )}
                          </>
                        )}
                      </li>
                    );
                  })}
                </ul>
              )}
              {showAudit && (
                <ul className="mt-2 space-y-1 text-xs text-content-secondary">
                  {(auditQ.data?.items ?? []).length === 0 && <li>{t('site_sensors.readings.audit_empty', { defaultValue: 'No changes recorded yet.' })}</li>}
                  {(auditQ.data?.items ?? []).map((a) => (
                    <li key={a.id} className="tabular-nums">
                      <DateDisplay value={a.created_at} format="datetime" />{' '}
                      {t(`site_sensors.readings.audit_${a.action}`, {
                        defaultValue: a.action === 'create' ? 'added {{after}}' : a.action === 'update' ? 'changed {{before}} to {{after}}' : 'deleted {{before}}',
                        before: a.value_before ?? '',
                        after: a.value_after ?? '',
                      })}{' '}
                      ({<DateDisplay value={a.recorded_at} format="datetime" />}){a.user_name ? `, ${a.user_name}` : ''}
                      {a.note ? `: ${a.note}` : ''}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
