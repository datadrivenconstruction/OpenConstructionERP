// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Formwork strikes: planned strikes per concrete sensor, the Strike action and a
 * warning when formwork was struck below the target strength.
 */
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { AlertTriangle } from 'lucide-react';
import { Badge, Button, Card, CardContent, CardHeader } from '@/shared/ui';
import { DateDisplay } from '@/shared/ui/DateDisplay';
import { fmtNumber } from '@/shared/lib/formatters';
import { getErrorMessage } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import { createStrip, fetchStrips, strikeStrip, type SensorDevice } from '../api';
import { struckBelowTarget } from '../sensorData';

const FIELD = 'h-8 rounded-lg border border-border-light bg-surface-primary px-2 text-xs text-content-primary';

export function StripsPanel({ projectId, devices }: { projectId: string; devices: SensorDevice[] }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const concrete = devices.filter((d) => d.kind === 'concrete_maturity');
  const byId = new Map(devices.map((d) => [d.id, d]));
  const [deviceId, setDeviceId] = useState('');
  const [element, setElement] = useState('');
  const [target, setTarget] = useState('');

  const q = useQuery({ queryKey: ['site-sensors', 'strips', projectId], queryFn: () => fetchStrips(projectId) });
  const refresh = () => qc.invalidateQueries({ queryKey: ['site-sensors'] });
  const onError = (e: unknown) =>
    addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: getErrorMessage(e) });

  const strikeMut = useMutation({ mutationFn: (id: string) => strikeStrip(id), onSuccess: refresh, onError });
  const createMut = useMutation({
    mutationFn: () =>
      createStrip({
        device_id: deviceId,
        element: element.trim(),
        ...(target.trim() ? { target_strength_mpa: target.trim() } : {}),
      }),
    onSuccess: () => {
      setElement('');
      setTarget('');
      refresh();
    },
    onError,
  });

  const strips = q.data ?? [];

  return (
    <Card>
      <CardHeader
        title={t('site_sensors.strips.title', { defaultValue: 'Formwork strikes' })}
        subtitle={t('site_sensors.strips.subtitle', {
          defaultValue: 'Strike formwork once the sensor shows the target strength.',
        })}
      />
      <CardContent>
        {concrete.length > 0 && (
          <div className="mb-3 flex flex-wrap items-end gap-2">
            <select
              value={deviceId}
              onChange={(e) => setDeviceId(e.target.value)}
              aria-label={t('site_sensors.strips.sensor', { defaultValue: 'Concrete sensor' })}
              className={`${FIELD} min-w-[160px]`}
            >
              <option value="">{t('site_sensors.strips.pick_sensor', { defaultValue: 'Choose a sensor' })}</option>
              {concrete.map((d) => (
                <option key={d.id} value={d.id}>
                  {d.code}
                </option>
              ))}
            </select>
            <input
              type="text"
              value={element}
              maxLength={200}
              onChange={(e) => setElement(e.target.value)}
              placeholder={t('site_sensors.strips.element', { defaultValue: 'Element (e.g. slab L3)' })}
              aria-label={t('site_sensors.strips.element', { defaultValue: 'Element (e.g. slab L3)' })}
              className={`${FIELD} w-48`}
            />
            <input
              type="number"
              min="0"
              step="0.5"
              value={target}
              onChange={(e) => setTarget(e.target.value)}
              placeholder={t('site_sensors.strips.target', { defaultValue: 'Target MPa' })}
              aria-label={t('site_sensors.strips.target', { defaultValue: 'Target MPa' })}
              className={`${FIELD} w-28`}
            />
            <Button
              variant="secondary"
              size="sm"
              disabled={!deviceId}
              loading={createMut.isPending}
              onClick={() => createMut.mutate()}
            >
              {t('site_sensors.strips.plan', { defaultValue: 'Plan strike' })}
            </Button>
          </div>
        )}
        {strips.length === 0 ? (
          <p className="text-sm text-content-tertiary">
            {t('site_sensors.strips.empty', {
              defaultValue: 'No strikes planned. Plan one for a concrete sensor to be told when the target strength is reached.',
            })}
          </p>
        ) : (
          <ul className="divide-y divide-border-light rounded-lg border border-border-light">
            {strips.map((s) => {
              const struck = s.struck_at !== null;
              const low = struckBelowTarget(s);
              return (
                <li key={s.id} className="flex flex-wrap items-center gap-3 px-3 py-2 text-sm">
                  <span className="font-medium text-content-primary">{s.element || byId.get(s.device_id)?.code}</span>
                  <span className="text-xs text-content-tertiary">{byId.get(s.device_id)?.code}</span>
                  <span className="tabular-nums text-content-secondary">
                    {t('site_sensors.strips.target_value', {
                      defaultValue: 'Target {{mpa}} MPa',
                      mpa: fmtNumber(s.target_strength_mpa, 1),
                    })}
                  </span>
                  {struck ? (
                    <>
                      <Badge variant={low ? 'error' : 'success'} size="sm">
                        {t('site_sensors.strips.struck', { defaultValue: 'Struck' })}
                      </Badge>
                      {s.strength_at_strike_mpa !== null && (
                        <span className="tabular-nums text-content-secondary">
                          {fmtNumber(s.strength_at_strike_mpa, 1)} MPa
                        </span>
                      )}
                      {low && (
                        <span className="inline-flex items-center gap-1 text-xs font-medium text-semantic-error">
                          <AlertTriangle size={13} />
                          {t('site_sensors.strips.below_target', { defaultValue: 'Struck below target strength' })}
                        </span>
                      )}
                      <span className="ml-auto text-xs text-content-tertiary">
                        <DateDisplay value={s.struck_at} format="datetime" />
                      </span>
                    </>
                  ) : (
                    <>
                      <Badge variant={s.released_at ? 'success' : 'neutral'} size="sm">
                        {s.released_at
                          ? t('site_sensors.strips.ready', { defaultValue: 'Ready to strike' })
                          : t('site_sensors.strips.curing', { defaultValue: 'Curing' })}
                      </Badge>
                      <Button
                        variant={s.released_at ? 'primary' : 'secondary'}
                        size="sm"
                        className="ml-auto"
                        loading={strikeMut.isPending && strikeMut.variables === s.id}
                        onClick={() => strikeMut.mutate(s.id)}
                      >
                        {t('site_sensors.strips.strike', { defaultValue: 'Strike' })}
                      </Button>
                    </>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
