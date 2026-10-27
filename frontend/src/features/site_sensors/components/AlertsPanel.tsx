// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Alerts panel​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠: sensor alerts with acknowledge (note) and links to the daily
 * diary, an inspection or a punch list item.
 */
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Badge, Button, Card, CardContent, CardHeader } from '@/shared/ui';
import { DateDisplay } from '@/shared/ui/DateDisplay';
import { getErrorMessage } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import { acknowledgeAlert, fetchSensorAlerts, linkAlert, type SensorAlert, type SensorDevice } from '../api';

const FIELD = 'h-8 rounded-lg border border-border-light bg-surface-primary px-2 text-xs text-content-primary';

function AlertRow({ alert, device }: { alert: SensorAlert; device?: SensorDevice }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [note, setNote] = useState('');
  const [diary, setDiary] = useState(alert.diary_id ?? '');
  const [inspection, setInspection] = useState(alert.inspection_id ?? '');
  const [punch, setPunch] = useState(alert.punch_item_id ?? '');
  const refresh = () => qc.invalidateQueries({ queryKey: ['site-sensors'] });
  const onError = (e: unknown) =>
    addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: getErrorMessage(e) });

  const ackMut = useMutation({ mutationFn: () => acknowledgeAlert(alert.id, note.trim()), onSuccess: refresh, onError });
  const linkMut = useMutation({
    mutationFn: () =>
      linkAlert(alert.id, {
        diary_id: diary.trim() || null,
        inspection_id: inspection.trim() || null,
        punch_item_id: punch.trim() || null,
      }),
    onSuccess: () => {
      refresh();
      addToast({ type: 'success', title: t('site_sensors.alerts.linked', { defaultValue: 'Links saved' }) });
    },
    onError,
  });

  const open = alert.status === 'open';
  const kindLabel =
    alert.kind === 'offline'
      ? t('site_sensors.alerts.kind_offline', { defaultValue: 'Stopped reporting' })
      : t('site_sensors.alerts.kind_exceedance', { defaultValue: 'Limit exceeded' });

  return (
    <li className="space-y-2 px-3 py-3 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant={open ? 'error' : 'neutral'} size="sm">
          {open
            ? t('site_sensors.alerts.status_open', { defaultValue: 'Open' })
            : t('site_sensors.alerts.status_done', { defaultValue: 'Acknowledged' })}
        </Badge>
        <span className="font-medium text-content-primary">{device?.code ?? alert.device_id.slice(0, 8)}</span>
        <span className="text-content-secondary">{kindLabel}</span>
        {alert.value !== null && alert.limit_value !== null && (
          <span className="tabular-nums text-content-secondary">
            {alert.value} / {alert.limit_value} {device?.unit}
          </span>
        )}
        <span className="ml-auto text-xs text-content-tertiary">
          <DateDisplay value={alert.raised_at} format="datetime" />
        </span>
      </div>
      {open ? (
        <div className="flex flex-wrap items-center gap-2">
          <input
            type="text"
            value={note}
            maxLength={2000}
            onChange={(e) => setNote(e.target.value)}
            placeholder={t('site_sensors.alerts.note', { defaultValue: 'Note (what was done)' })}
            aria-label={t('site_sensors.alerts.note', { defaultValue: 'Note (what was done)' })}
            className={`${FIELD} min-w-[220px] flex-1`}
          />
          <Button variant="primary" size="sm" loading={ackMut.isPending} onClick={() => ackMut.mutate()}>
            {t('site_sensors.alerts.acknowledge', { defaultValue: 'Acknowledge' })}
          </Button>
        </div>
      ) : (
        alert.note && <p className="text-xs text-content-secondary">{alert.note}</p>
      )}
      <div className="flex flex-wrap items-center gap-2">
        <input
          type="text"
          value={diary}
          onChange={(e) => setDiary(e.target.value)}
          placeholder={t('site_sensors.alerts.diary_id', { defaultValue: 'Daily diary ID' })}
          aria-label={t('site_sensors.alerts.diary_id', { defaultValue: 'Daily diary ID' })}
          className={`${FIELD} w-44`}
        />
        <input
          type="text"
          value={inspection}
          onChange={(e) => setInspection(e.target.value)}
          placeholder={t('site_sensors.alerts.inspection_id', { defaultValue: 'Inspection ID' })}
          aria-label={t('site_sensors.alerts.inspection_id', { defaultValue: 'Inspection ID' })}
          className={`${FIELD} w-44`}
        />
        <input
          type="text"
          value={punch}
          onChange={(e) => setPunch(e.target.value)}
          placeholder={t('site_sensors.alerts.punch_id', { defaultValue: 'Punch list item ID' })}
          aria-label={t('site_sensors.alerts.punch_id', { defaultValue: 'Punch list item ID' })}
          className={`${FIELD} w-44`}
        />
        <Button variant="secondary" size="sm" loading={linkMut.isPending} onClick={() => linkMut.mutate()}>
          {t('site_sensors.alerts.save_links', { defaultValue: 'Save links' })}
        </Button>
      </div>
    </li>
  );
}

export function AlertsPanel({ projectId, devices }: { projectId: string; devices: SensorDevice[] }) {
  const { t } = useTranslation();
  const q = useQuery({
    queryKey: ['site-sensors', 'alerts', projectId],
    queryFn: () => fetchSensorAlerts(projectId),
  });
  const byId = new Map(devices.map((d) => [d.id, d]));
  const alerts = q.data ?? [];

  return (
    <Card>
      <CardHeader
        title={t('site_sensors.alerts.title', { defaultValue: 'Alerts' })}
        subtitle={t('site_sensors.alerts.subtitle', {
          defaultValue: 'Readings above a limit and sensors that stopped reporting.',
        })}
      />
      <CardContent>
        {alerts.length === 0 ? (
          <p className="text-sm text-content-tertiary">
            {t('site_sensors.alerts.empty', {
              defaultValue: 'No alerts. A reading above a sensor limit raises one here and notifies the project team.',
            })}
          </p>
        ) : (
          <ul className="divide-y divide-border-light rounded-lg border border-border-light">
            {alerts.map((a) => (
              <AlertRow key={a.id} alert={a} device={byId.get(a.device_id)} />
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
