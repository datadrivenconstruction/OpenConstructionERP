// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Site sensors​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ page for a project: devices by kind with last value and limit,
 * concrete maturity cards, alerts, formwork strikes and rule results.
 */
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { Plus } from 'lucide-react';
import { Badge, Button, Card, CardContent, CardHeader, EmptyState, ErrorState, PageHeader } from '@/shared/ui';
import { RequiresProject } from '@/shared/auth/RequiresProject';
import { RuleResultsList } from '@/shared/ui/RuleResultsList';
import { DateDisplay } from '@/shared/ui/DateDisplay';
import { useActiveProjectId } from '@/shared/hooks/useActiveProjectId';
import { getErrorMessage } from '@/shared/lib/api';
import { fetchSensorDevices, fetchSensorValidation, fetchSparklines, type SensorDevice } from './api';
import { KIND_LABELS, groupByKind, isOnline, outsideLimits, sparkPath } from './sensorData';
import { unitKeyOf } from './units';
import { useSensorUnits } from './useSensorUnits';
import { MixForms } from './components/MixForms';
import { MaturityCard } from './components/MaturityCard';
import { AlertsPanel } from './components/AlertsPanel';
import { StripsPanel } from './components/StripsPanel';
import { DeviceForms } from './components/DeviceForms';
import { ReadingsPanel } from './components/ReadingsPanel';
import { HseModeSelect } from './components/HseModeSelect';

function Sparkline({ points, limit, label }: { points: (number | null)[]; limit: number | null; label: string }) {
  const { path, limitY } = sparkPath(points, limit);
  if (!path) return null;
  return (
    <svg width={96} height={24} viewBox="0 0 96 24" role="img" aria-label={label} className="shrink-0 overflow-visible">
      {limitY !== null && (
        <line x1={0} x2={96} y1={limitY} y2={limitY} stroke="currentColor" strokeDasharray="3 2" className="text-semantic-error" strokeWidth={1} />
      )}
      <path d={path} fill="none" stroke="var(--oe-blue, #0071e3)" strokeWidth={1.5} />
    </svg>
  );
}

function DeviceRow({ device, spark }: { device: SensorDevice; spark?: { points: (number | null)[]; limit: number | null } }) {
  const { t } = useTranslation();
  const u = useSensorUnits(device.project_id);
  const online = isOnline(device);
  const limit = device.effective_limit ?? (device.limit_value === null ? null : Number(device.limit_value));
  const over = !device.record_only && outsideLimits(device.last_value, limit, device.lower_limit);
  const key = unitKeyOf(device.unit);
  const source = device.limit_source === 'device'
    ? t('site_sensors.devices.source_device', { defaultValue: 'set on the device' })
    : device.limit_source;
  return (
    <li className="flex flex-wrap items-center gap-3 px-3 py-2 text-sm">
      <span className="font-medium text-content-primary">{device.code}</span>
      <span className="text-content-secondary">{device.name}</span>
      <span className={`tabular-nums ${over ? 'font-semibold text-semantic-error' : 'text-content-primary'}`}>
        {u.show(device.last_value, key, device.unit)}
      </span>
      {spark && (
        <Sparkline
          points={spark.points}
          limit={spark.limit}
          label={t('site_sensors.devices.sparkline', { defaultValue: 'Last 24 hours against the limit' })}
        />
      )}
      {(limit !== null || device.lower_limit !== null) && (
        <span className="text-xs text-content-tertiary">
          {limit !== null &&
            t('site_sensors.devices.limit_value', { defaultValue: 'Limit {{value}}', value: u.show(limit, key, device.unit) })}
          {device.kind === 'dust_pm10' && ` ${t('site_sensors.devices.rolling_24h', { defaultValue: '(24 h mean)' })}`}
          {device.lower_limit !== null &&
            ` ${t('site_sensors.limits.lower_value', { defaultValue: 'min {{value}}', value: u.show(Number(device.lower_limit), key, device.unit) })}`}
          {device.limit_note ? (
            <span className="ml-1 italic">({device.limit_note})</span>
          ) : (
            source && <span className="ml-1 italic">({source})</span>
          )}
          {device.country_limit !== null && device.limit_value !== null && (
            <span className="ml-1">
              {t('site_sensors.limits.country_was', { defaultValue: 'country {{value}}', value: u.show(device.country_limit, key, device.unit) })}
            </span>
          )}
        </span>
      )}
      {device.record_only && (
        <span className="text-xs text-content-tertiary">
          {t('site_sensors.custom.record_only', { defaultValue: 'Record only, no limit check' })}
        </span>
      )}
      {device.night_limit_by_ordinance && (
        <span className="text-xs text-content-tertiary">
          {t('site_sensors.devices.night_ordinance', { defaultValue: 'Night: local ordinance' })}
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
  const sparkQ = useQuery({
    queryKey: ['site-sensors', 'sparklines', projectId],
    queryFn: () => fetchSparklines(projectId),
    enabled: !!projectId,
    refetchInterval: 300_000,
  });
  const u = useSensorUnits(projectId);
  const devices = devQ.data ?? [];
  const groups = groupByKind(devices);
  const concrete = devices.filter((d) => d.kind === 'concrete_maturity' && d.active);
  const ready = u.context?.strike_ready ?? [];

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
      {ready.length > 0 && (
        <div role="status" className="rounded-xl border border-semantic-success/40 bg-semantic-success/10 px-4 py-3 text-sm">
          <div className="font-semibold text-content-primary">
            {t('site_sensors.ready.title', { defaultValue: 'Strike-ready: reached the target strength' })}
          </div>
          <ul className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-content-secondary">
            {ready.map((r) => (
              <li key={r.strip_id}>
                <span className="font-medium text-content-primary">{r.element || r.device_code}</span>{' '}
                {u.show(r.strength_mpa, 'mpa')} / {u.show(r.target_strength_mpa, 'mpa')}
              </li>
            ))}
          </ul>
        </div>
      )}
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
                  <DeviceRow key={d.id} device={d} spark={sparkQ.data?.[d.id]} />
                ))}
              </ul>
            </CardContent>
          </Card>
        ))
      )}

      {concrete.length > 0 ? (
        <div className="grid gap-5 lg:grid-cols-2">
          {concrete.map((d) => (
            <MaturityCard key={d.id} device={d} />
          ))}
        </div>
      ) : (
        devices.length > 0 && (
          <p className="text-sm text-content-tertiary">
            {t('site_sensors.maturity.none', {
              defaultValue: 'No concrete sensors yet. Add one with a mix to follow strength and plan strikes.',
            })}
          </p>
        )
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
          {(rulesQ.data?.results ?? []).length === 0 ? (
            <p className="text-sm text-content-tertiary">
              {t('site_sensors.rules.empty', { defaultValue: 'Nothing to check yet: checks run once devices report.' })}
            </p>
          ) : (
            <RuleResultsList results={rulesQ.data?.results ?? []} />
          )}
        </CardContent>
      </Card>

      <ReadingsPanel devices={devices} />
      <DeviceForms projectId={projectId} />
      <MixForms projectId={projectId} />
    </div>
  );
}

const scrollTo = (id: string) => document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' });

export function SiteSensorsPage() {
  const { t } = useTranslation();
  const projectId = useActiveProjectId();
  return (
    <div className="space-y-5">
      <PageHeader
        actions={
          <div className="flex items-center gap-2">
            {projectId && <HseModeSelect projectId={projectId} />}
            <Button variant="secondary" size="sm" icon={<Plus size={14} />} onClick={() => scrollTo('sensor-add-mix')}>
              {t('site_sensors.mixes.add', { defaultValue: 'Add mix' })}
            </Button>
            <Button variant="primary" size="sm" icon={<Plus size={14} />} onClick={() => scrollTo('sensor-add-device')}>
              {t('site_sensors.forms.add_device', { defaultValue: 'Add device' })}
            </Button>
          </div>
        }
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
