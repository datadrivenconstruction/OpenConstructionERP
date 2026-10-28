// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Device forms for site sensors: add a device and add readings by hand.
 */
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Plus } from 'lucide-react';
import { Button, Card, CardContent, CardHeader } from '@/shared/ui';
import { getErrorMessage } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import {
  addSensorReadings,
  createSensorDevice,
  fetchSensorMixes,
  type SensorDevice,
  type SensorKind,
} from '../api';
import { KIND_LABELS, KIND_ORDER, isoFromLocal, localDateTimeValue } from '../sensorData';

const FIELD = 'h-9 rounded-lg border border-border-light bg-surface-primary px-3 text-sm text-content-primary';
const LABEL = 'text-xs text-content-secondary';

export function DeviceForms({ projectId, devices }: { projectId: string; devices: SensorDevice[] }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const refresh = () => qc.invalidateQueries({ queryKey: ['site-sensors'] });
  const onError = (e: unknown) =>
    addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: getErrorMessage(e) });

  const [code, setCode] = useState('');
  const [name, setName] = useState('');
  const [kind, setKind] = useState<SensorKind>('concrete_maturity');
  const [limit, setLimit] = useState('');
  const [mixId, setMixId] = useState('');
  const [pourRef, setPourRef] = useState('');
  const [castAt, setCastAt] = useState('');

  const mixQ = useQuery({
    queryKey: ['site-sensors', 'mixes', projectId],
    queryFn: () => fetchSensorMixes(projectId),
    enabled: kind === 'concrete_maturity',
  });

  const createMut = useMutation({
    mutationFn: () =>
      createSensorDevice({
        project_id: projectId,
        code: code.trim(),
        name: name.trim(),
        kind,
        limit_value: limit.trim() || null,
        ...(kind === 'concrete_maturity'
          ? { mix_id: mixId || null, pour_ref: pourRef.trim(), cast_at: isoFromLocal(castAt) }
          : {}),
      }),
    onSuccess: () => {
      setCode('');
      setName('');
      setLimit('');
      setPourRef('');
      refresh();
    },
    onError,
  });

  const [deviceId, setDeviceId] = useState('');
  const [value, setValue] = useState('');
  const [at, setAt] = useState(() => localDateTimeValue());
  const readingMut = useMutation({
    mutationFn: () => {
      const iso = isoFromLocal(at);
      if (!iso) throw new Error(t('site_sensors.forms.bad_time', { defaultValue: 'Enter a valid date and time.' }));
      return addSensorReadings(deviceId, [{ recorded_at: iso, value: Number(value) }]);
    },
    onSuccess: (r) => {
      setValue('');
      refresh();
      if (r.exceedances > 0) {
        addToast({
          type: 'warning',
          title: t('site_sensors.forms.limit_exceeded', { defaultValue: 'Limit exceeded' }),
        });
      }
    },
    onError,
  });

  return (
    <div className="grid gap-5 lg:grid-cols-2">
      <Card>
        <CardHeader title={t('site_sensors.forms.add_device', { defaultValue: 'Add device' })} />
        <CardContent>
          <div className="grid grid-cols-2 gap-3">
            <label className={LABEL}>
              {t('site_sensors.forms.code', { defaultValue: 'Code' })}
              <input type="text" value={code} maxLength={50} onChange={(e) => setCode(e.target.value)} className={`${FIELD} mt-1 w-full`} />
            </label>
            <label className={LABEL}>
              {t('site_sensors.forms.name', { defaultValue: 'Name' })}
              <input type="text" value={name} maxLength={200} onChange={(e) => setName(e.target.value)} className={`${FIELD} mt-1 w-full`} />
            </label>
            <label className={LABEL}>
              {t('site_sensors.forms.kind', { defaultValue: 'Kind' })}
              <select value={kind} onChange={(e) => setKind(e.target.value as SensorKind)} className={`${FIELD} mt-1 w-full`}>
                {KIND_ORDER.map((k) => (
                  <option key={k} value={k}>
                    {t(`site_sensors.kind.${k}`, { defaultValue: KIND_LABELS[k] })}
                  </option>
                ))}
              </select>
            </label>
            <label className={LABEL}>
              {t('site_sensors.forms.limit', { defaultValue: 'Limit (blank = country default)' })}
              <input type="number" step="any" value={limit} onChange={(e) => setLimit(e.target.value)} className={`${FIELD} mt-1 w-full`} />
            </label>
            {kind === 'concrete_maturity' && (
              <>
                <label className={LABEL}>
                  {t('site_sensors.forms.mix', { defaultValue: 'Concrete mix' })}
                  <select value={mixId} onChange={(e) => setMixId(e.target.value)} className={`${FIELD} mt-1 w-full`}>
                    <option value="">{t('site_sensors.forms.no_mix', { defaultValue: 'None' })}</option>
                    {(mixQ.data ?? []).map((m) => (
                      <option key={m.id} value={m.id}>
                        {m.code}
                      </option>
                    ))}
                  </select>
                </label>
                <label className={LABEL}>
                  {t('site_sensors.forms.pour_ref', { defaultValue: 'Pour reference' })}
                  <input type="text" value={pourRef} maxLength={200} onChange={(e) => setPourRef(e.target.value)} className={`${FIELD} mt-1 w-full`} />
                </label>
                <label className={`${LABEL} col-span-2`}>
                  {t('site_sensors.forms.cast_at', { defaultValue: 'Cast at' })}
                  <input type="datetime-local" value={castAt} onChange={(e) => setCastAt(e.target.value)} className={`${FIELD} mt-1 w-full`} />
                </label>
              </>
            )}
          </div>
          <Button
            className="mt-3"
            variant="primary"
            size="md"
            icon={<Plus size={14} />}
            disabled={!code.trim()}
            loading={createMut.isPending}
            onClick={() => createMut.mutate()}
          >
            {t('site_sensors.forms.add_device', { defaultValue: 'Add device' })}
          </Button>
        </CardContent>
      </Card>

      <Card>
        <CardHeader
          title={t('site_sensors.forms.add_readings', { defaultValue: 'Add readings' })}
          subtitle={t('site_sensors.forms.add_readings_hint', {
            defaultValue: 'For manual readings. Connected sensors post their own with a device token.',
          })}
        />
        <CardContent>
          <div className="grid grid-cols-2 gap-3">
            <label className={`${LABEL} col-span-2`}>
              {t('site_sensors.forms.device', { defaultValue: 'Device' })}
              <select value={deviceId} onChange={(e) => setDeviceId(e.target.value)} className={`${FIELD} mt-1 w-full`}>
                <option value="">{t('site_sensors.forms.pick_device', { defaultValue: 'Choose a device' })}</option>
                {devices.map((d) => (
                  <option key={d.id} value={d.id}>
                    {d.code} {d.unit ? `(${d.unit})` : ''}
                  </option>
                ))}
              </select>
            </label>
            <label className={LABEL}>
              {t('site_sensors.forms.value', { defaultValue: 'Value' })}
              <input type="number" step="any" value={value} onChange={(e) => setValue(e.target.value)} className={`${FIELD} mt-1 w-full`} />
            </label>
            <label className={LABEL}>
              {t('site_sensors.forms.recorded_at', { defaultValue: 'Recorded at' })}
              <input type="datetime-local" value={at} onChange={(e) => setAt(e.target.value)} className={`${FIELD} mt-1 w-full`} />
            </label>
          </div>
          <Button
            className="mt-3"
            variant="primary"
            size="md"
            disabled={!deviceId || value.trim() === '' || !Number.isFinite(Number(value))}
            loading={readingMut.isPending}
            onClick={() => readingMut.mutate()}
          >
            {t('site_sensors.forms.save_reading', { defaultValue: 'Save reading' })}
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}
