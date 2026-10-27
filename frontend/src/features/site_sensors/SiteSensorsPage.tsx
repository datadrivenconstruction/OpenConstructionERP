// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Site sensors​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ page for a project: devices by kind with last value and limit,
 * concrete maturity cards, alerts, formwork strikes and rule results.
 */
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { Badge, Card, CardContent, CardHeader, EmptyState, ErrorState, PageHeader } from '@/shared/ui';
import { RequiresProject } from '@/shared/auth/RequiresProject';
import { RuleResultsList } from '@/shared/ui/RuleResultsList';
import { DateDisplay } from '@/shared/ui/DateDisplay';
import { useActiveProjectId } from '@/shared/hooks/useActiveProjectId';
import { fmtNumber } from '@/shared/lib/formatters';
import { getErrorMessage } from '@/shared/lib/api';
import { fetchSensorDevices, fetchSensorValidation, type SensorDevice } from './api';
import { KIND_LABELS, groupByKind, isOnline, overLimit } from './sensorData';
import { MaturityCard } from './components/MaturityCard';
import { AlertsPanel } from './components/AlertsPanel';
import { StripsPanel } from './components/StripsPanel';
import { DeviceForms } from './components/DeviceForms';

function DeviceRow({ device }: { device: SensorDevice }) {
  const { t } = useTranslation();
  const online = isOnline(device);
  const over = overLimit(device.last_value, device.limit_value);
  return (
    <li className="flex flex-wrap items-center gap-3 px-3 py-2 text-sm">
      <span className="font-medium text-content-primary">{device.code}</span>
      <span className="text-content-secondary">{device.name}</span>
      <span className={`tabular-nums ${over ? 'font-semibold text-semantic-error' : 'text-content-primary'}`}>
        {device.last_value === null ? '-' : fmtNumber(device.last_value, 1)} {device.unit}
      </span>
      {device.limit_value !== null && (
        <span className="text-xs text-content-tertiary">
          {t('site_sensors.devices.limit', {
            defaultValue: 'Limit {{limit}} {{unit}}',
            limit: fmtNumber(device.limit_value, 1),
            unit: device.unit,
          })}
        </span>
      )}
      <Badge variant={online ? 'success' : 'neutral'} size="sm" dot>
        {online
          ? t('site_sensors.devices.online', { defaultValue: 'Online' })
          : t('site_sensors.devices.offline', { defaultValue: 'Offline' })}
      </Badge>
      <span className="ml-auto text-xs text-content-tertiary">
        {device.last_seen_at ? (
          <DateDisplay value={device.last_seen_at} format="relative" />
        ) : (
          t('site_sensors.devices.never', { defaultValue: 'No readings yet' })
        )}
      </span>
    </li>
  );
}

function Content() {
  const { t } = useTranslation();
  const projectId = useActiveProjectId();
  const devQ = useQuery({
    queryKey: ['site-sensors', 'devices', projectId],
    queryFn: () => fetchSensorDevices(projectId),
    enabled: !!projectId,
    refetchInterval: 60_000,
  });
  const rulesQ = useQuery({
    queryKey: ['site-sensors', 'validation', projectId],
    queryFn: () => fetchSensorValidation(projectId),
    enabled: !!projectId,
  });
  const devices = devQ.data ?? [];
  const groups = groupByKind(devices);
  const concrete = devices.filter((d) => d.kind === 'concrete_maturity' && d.active);

  if (devQ.isError) {
    return (
      <ErrorState
        title={t('site_sensors.load_failed', { defaultValue: 'Could not load the sensors' })}
        hint={getErrorMessage(devQ.error)}
        onRetry={() => devQ.refetch()}
      />
    );
  }

  return (
    <div className="space-y-5">
      {devQ.isLoading ? (
        <p className="py-8 text-center text-sm text-content-tertiary">{t('common.loading', { defaultValue: 'Loading...' })}</p>
      ) : devices.length === 0 ? (
        <EmptyState
          title={t('site_sensors.empty_title', { defaultValue: 'No sensors on this project yet' })}
          description={t('site_sensors.empty_hint', {
            defaultValue:
              'Add a device below: concrete maturity, noise, dust, vibration, weather or water level. Readings above its limit raise an alert.',
          })}
        />
      ) : (
        groups.map((g) => (
          <Card key={g.kind}>
            <CardHeader
              title={t(`site_sensors.kind.${g.kind}`, { defaultValue: KIND_LABELS[g.kind] })}
              subtitle={t('site_sensors.devices.group_count', {
                defaultValue_one: '{{count}} device',
                defaultValue_other: '{{count}} devices',
                count: g.devices.length,
              })}
            />
            <CardContent>
              <ul className="divide-y divide-border-light rounded-lg border border-border-light">
                {g.devices.map((d) => (
                  <DeviceRow key={d.id} device={d} />
                ))}
              </ul>
            </CardContent>
          </Card>
        ))
      )}

      {concrete.length > 0 && (
        <div className="grid gap-5 lg:grid-cols-2">
          {concrete.map((d) => (
            <MaturityCard key={d.id} device={d} />
          ))}
        </div>
      )}

      <AlertsPanel projectId={projectId} devices={devices} />
      <StripsPanel projectId={projectId} devices={devices} />

      <Card>
        <CardHeader
          title={t('site_sensors.rules.title', { defaultValue: 'Sensor checks' })}
          subtitle={t('site_sensors.rules.subtitle', {
            defaultValue: 'Sensors online, exceedances acknowledged, formwork struck at strength.',
          })}
        />
        <CardContent>
          <RuleResultsList results={rulesQ.data?.results ?? []} />
        </CardContent>
      </Card>

      <DeviceForms projectId={projectId} devices={devices} />
    </div>
  );
}

export function SiteSensorsPage() {
  const { t } = useTranslation();
  return (
    <div className="space-y-5">
      <PageHeader
        srTitle={t('site_sensors.title', { defaultValue: 'Site sensors' })}
        subtitle={t('site_sensors.subtitle', {
          defaultValue: 'Concrete strength, noise, dust, vibration, weather and water level, with limits and alerts.',
        })}
      />
      <RequiresProject>
        <Content />
      </RequiresProject>
    </div>
  );
}
