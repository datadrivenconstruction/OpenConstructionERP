// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Formwork strikes​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠: planned strikes per concrete sensor, the Strike action, the
 * reason the site must give when it strikes below the target strength, and the
 * pour record (CSV, PDF) of every strike.
 */
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { AlertTriangle, Download } from 'lucide-react';
import { Badge, Button, Card, CardContent, CardHeader } from '@/shared/ui';
import { DateDisplay } from '@/shared/ui/DateDisplay';
import { getErrorMessage } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import {
  createStrip,
  downloadPourRecord,
  fetchStrips,
  strikeStrip,
  type FormworkStrip,
  type SensorDevice,
} from '../api';
import { struckBelowTarget } from '../sensorData';
import { useSensorUnits } from '../useSensorUnits';

const FIELD = 'h-8 rounded-lg border border-border-light bg-surface-primary px-2 text-xs text-content-primary';

function StrikeDialog({
  strip,
  loading,
  onConfirm,
  onCancel,
}: {
  strip: FormworkStrip;
  loading: boolean;
  onConfirm: (reason: string) => void;
  onCancel: () => void;
}) {
  const { t } = useTranslation();
  const u = useSensorUnits(strip.project_id);
  const [reason, setReason] = useState('');
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={onCancel}>
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="strike-dialog-title"
        className="w-full max-w-md rounded-xl bg-surface-primary p-5 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 id="strike-dialog-title" className="flex items-center gap-2 text-base font-semibold text-content-primary">
          <AlertTriangle size={16} className="text-semantic-warning" />
          {t('site_sensors.strips.below_title', { defaultValue: 'Strike below target strength?' })}
        </h2>
        <p className="mt-2 text-sm text-content-secondary">
          {t('site_sensors.strips.below_message', {
            defaultValue:
              'The sensor has not shown {{target}} on {{element}} yet. Record why it is safe to strike, for example a cube result or back-propping.',
            target: u.show(strip.target_strength_mpa, 'mpa'),
            element: strip.element,
          })}
        </p>
        <label className="mt-3 block text-xs text-content-secondary">
          {t('site_sensors.strips.reason', { defaultValue: 'Reason' })}
          <textarea
            value={reason}
            maxLength={2000}
            rows={3}
            autoFocus
            onChange={(e) => setReason(e.target.value)}
            className="mt-1 w-full rounded-lg border border-border-light bg-surface-primary px-3 py-2 text-sm text-content-primary"
          />
        </label>
        <div className="mt-4 flex justify-end gap-2">
          <Button variant="secondary" size="sm" onClick={onCancel}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button
            variant="primary"
            size="sm"
            disabled={!reason.trim()}
            loading={loading}
            onClick={() => onConfirm(reason.trim())}
          >
            {t('site_sensors.strips.strike_anyway', { defaultValue: 'Record strike' })}
          </Button>
        </div>
      </div>
    </div>
  );
}

export function StripsPanel({ projectId, devices }: { projectId: string; devices: SensorDevice[] }) {
  const { t, i18n } = useTranslation();
  const qc = useQueryClient();
  const u = useSensorUnits(projectId);
  const addToast = useToastStore((s) => s.addToast);
  const concrete = devices.filter((d) => d.kind === 'concrete_maturity');
  const byId = new Map(devices.map((d) => [d.id, d]));
  const [deviceId, setDeviceId] = useState('');
  const [element, setElement] = useState('');
  const [target, setTarget] = useState('');
  const [asking, setAsking] = useState<FormworkStrip | null>(null);

  const q = useQuery({ queryKey: ['site-sensors', 'strips', projectId], queryFn: () => fetchStrips(projectId) });
  const refresh = () => qc.invalidateQueries({ queryKey: ['site-sensors'] });
  const onError = (e: unknown) =>
    addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: getErrorMessage(e) });

  const strikeMut = useMutation({
    mutationFn: ({ id, reason }: { id: string; reason: string }) => strikeStrip(id, reason),
    onSuccess: () => {
      setAsking(null);
      refresh();
    },
    onError,
  });
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
  const download = (s: FormworkStrip, format: 'csv' | 'pdf') =>
    downloadPourRecord(s.id, format, i18n.language, s.element || s.id).catch(onError);

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
                    {t('site_sensors.strips.target_with_unit', {
                      defaultValue: 'Target {{value}}',
                      value: u.show(s.target_strength_mpa, 'mpa'),
                    })}
                  </span>
                  {struck ? (
                    <>
                      <Badge variant={low ? 'error' : 'success'} size="sm">
                        {t('site_sensors.strips.struck', { defaultValue: 'Struck' })}
                      </Badge>
                      {s.strength_at_strike_mpa !== null && (
                        <span className="tabular-nums text-content-secondary">{u.show(s.strength_at_strike_mpa, 'mpa')}</span>
                      )}
                      {low && (
                        <span className="inline-flex items-center gap-1 text-xs font-medium text-semantic-error">
                          <AlertTriangle size={13} />
                          {t('site_sensors.strips.below_target', { defaultValue: 'Struck below target strength' })}
                        </span>
                      )}
                      {s.strike_reason && (
                        <span className="basis-full text-xs text-content-secondary">
                          {t('site_sensors.strips.reason_value', { defaultValue: 'Reason: {{reason}}', reason: s.strike_reason })}
                        </span>
                      )}
                      <span className="ml-auto flex items-center gap-2 text-xs text-content-tertiary">
                        <DateDisplay value={s.struck_at} format="datetime" />
                        <Button variant="ghost" size="sm" icon={<Download size={13} />} onClick={() => download(s, 'csv')}>
                          {t('site_sensors.strips.record_csv', { defaultValue: 'CSV' })}
                        </Button>
                        <Button variant="ghost" size="sm" icon={<Download size={13} />} onClick={() => download(s, 'pdf')}>
                          {t('site_sensors.strips.record_pdf', { defaultValue: 'PDF' })}
                        </Button>
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
                        loading={strikeMut.isPending && strikeMut.variables?.id === s.id}
                        onClick={() => (s.released_at ? strikeMut.mutate({ id: s.id, reason: '' }) : setAsking(s))}
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
      {asking && (
        <StrikeDialog
          strip={asking}
          loading={strikeMut.isPending}
          onCancel={() => setAsking(null)}
          onConfirm={(reason) => strikeMut.mutate({ id: asking.id, reason })}
        />
      )}
    </Card>
  );
}
