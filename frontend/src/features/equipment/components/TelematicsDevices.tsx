// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Telematics devices per machine: create a device token (shown once) and revoke it.
 */
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Copy, KeyRound } from 'lucide-react';
import { Badge, Button, Card, CardContent, CardHeader } from '@/shared/ui';
import { DateDisplay } from '@/shared/ui/DateDisplay';
import { getErrorMessage } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import { listEquipment } from '../api';
import {
  createTelematicsDevice,
  fetchTelematicsDevices,
  revokeTelematicsDevice,
  type TelematicsDevice,
} from '../telematicsApi';

export function TelematicsDevices() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [equipmentId, setEquipmentId] = useState('');
  const [label, setLabel] = useState('');
  const [fresh, setFresh] = useState<TelematicsDevice | null>(null);

  const eqQ = useQuery({
    queryKey: ['equipment', 'list', 'telematics-picker'],
    queryFn: () => listEquipment({ limit: 200 }),
  });
  const devQ = useQuery({ queryKey: ['equipment', 'telematics', 'devices'], queryFn: fetchTelematicsDevices });
  const equipment = eqQ.data?.items ?? [];
  const byId = new Map(equipment.map((e) => [e.id, e]));

  const onError = (e: unknown) =>
    addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: getErrorMessage(e) });

  const createMut = useMutation({
    mutationFn: () => createTelematicsDevice(equipmentId, label.trim()),
    onSuccess: (d) => {
      setFresh(d);
      setLabel('');
      qc.invalidateQueries({ queryKey: ['equipment', 'telematics', 'devices'] });
    },
    onError,
  });
  const revokeMut = useMutation({
    mutationFn: (id: string) => revokeTelematicsDevice(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['equipment', 'telematics', 'devices'] }),
    onError,
  });

  const copy = async (text: string) => {
    try {
      await navigator.clipboard.writeText(text);
      addToast({ type: 'success', title: t('common.copied', { defaultValue: 'Copied' }) });
    } catch {
      /* clipboard blocked: the token stays selectable on screen */
    }
  };

  const devices = devQ.data ?? [];

  return (
    <Card>
      <CardHeader
        title={t('equipment.telematics.devices_title', { defaultValue: 'Devices' })}
        subtitle={t('equipment.telematics.devices_subtitle', {
          defaultValue: 'A device token lets one machine post its own readings without a user login.',
        })}
      />
      <CardContent>
        <div className="mb-4 flex flex-wrap items-end gap-2">
          <label className="text-xs text-content-secondary">
            <span className="mb-1 block">{t('equipment.telematics.device_machine', { defaultValue: 'Machine' })}</span>
            <select
              value={equipmentId}
              onChange={(e) => setEquipmentId(e.target.value)}
              className="h-9 min-w-[200px] rounded-lg border border-border-light bg-surface-primary px-3 text-sm text-content-primary"
            >
              <option value="">{t('equipment.telematics.device_pick', { defaultValue: 'Choose a machine' })}</option>
              {equipment.map((e) => (
                <option key={e.id} value={e.id}>
                  {e.code} - {e.name}
                </option>
              ))}
            </select>
          </label>
          <label className="text-xs text-content-secondary">
            <span className="mb-1 block">{t('equipment.telematics.device_label', { defaultValue: 'Label' })}</span>
            <input
              type="text"
              value={label}
              maxLength={200}
              onChange={(e) => setLabel(e.target.value)}
              className="h-9 w-48 rounded-lg border border-border-light bg-surface-primary px-3 text-sm text-content-primary"
            />
          </label>
          <Button
            variant="primary"
            size="md"
            icon={<KeyRound size={14} />}
            disabled={!equipmentId}
            loading={createMut.isPending}
            onClick={() => createMut.mutate()}
          >
            {t('equipment.telematics.device_create', { defaultValue: 'Create device token' })}
          </Button>
        </div>

        {fresh?.token && (
          <div className="mb-4 rounded-lg border border-semantic-warning/40 bg-semantic-warning/5 p-3">
            <p className="text-sm font-medium text-content-primary">
              {t('equipment.telematics.token_title', { defaultValue: 'Copy this token now' })}
            </p>
            <p className="text-xs text-content-secondary">
              {t('equipment.telematics.token_note', {
                defaultValue: 'It will not be shown again. Send it as the X-Device-Token header.',
              })}
            </p>
            <div className="mt-2 flex items-center gap-2">
              <code className="min-w-0 flex-1 select-all break-all rounded bg-surface-secondary px-2 py-1.5 text-xs">
                {fresh.token}
              </code>
              <Button variant="secondary" size="sm" icon={<Copy size={14} />} onClick={() => copy(fresh.token ?? '')}>
                {t('common.copy', { defaultValue: 'Copy' })}
              </Button>
              <Button variant="ghost" size="sm" onClick={() => setFresh(null)}>
                {t('common.done', { defaultValue: 'Done' })}
              </Button>
            </div>
          </div>
        )}

        {devices.length === 0 ? (
          <p className="text-sm text-content-tertiary">
            {t('equipment.telematics.devices_empty', {
              defaultValue: 'No devices yet. Choose a machine above and create its token.',
            })}
          </p>
        ) : (
          <ul className="divide-y divide-border-light rounded-lg border border-border-light">
            {devices.map((d) => {
              const eq = byId.get(d.equipment_id);
              return (
                <li key={d.id} className="flex flex-wrap items-center gap-3 px-3 py-2 text-sm">
                  <span className="font-medium text-content-primary">{eq ? eq.code : d.equipment_id.slice(0, 8)}</span>
                  <span className="text-content-secondary">{d.label}</span>
                  <code className="text-xs text-content-tertiary">{d.token_prefix}...</code>
                  <Badge variant={d.active ? 'success' : 'neutral'} size="sm">
                    {d.active
                      ? t('equipment.telematics.device_active', { defaultValue: 'Active' })
                      : t('equipment.telematics.device_revoked', { defaultValue: 'Revoked' })}
                  </Badge>
                  <span className="ml-auto text-xs text-content-tertiary">
                    {d.last_seen_at ? (
                      <>
                        {t('equipment.telematics.device_last_seen', { defaultValue: 'Last seen' })}{' '}
                        <DateDisplay value={d.last_seen_at} />
                      </>
                    ) : (
                      t('equipment.telematics.device_never_seen', { defaultValue: 'Never reported' })
                    )}
                  </span>
                  {d.active && (
                    <Button
                      variant="danger"
                      size="sm"
                      loading={revokeMut.isPending && revokeMut.variables === d.id}
                      onClick={() => revokeMut.mutate(d.id)}
                    >
                      {t('equipment.telematics.device_revoke', { defaultValue: 'Revoke' })}
                    </Button>
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
