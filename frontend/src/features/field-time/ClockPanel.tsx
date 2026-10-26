// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Clock panel - the phone screen of the geofenced time clock​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠.
 *
 * One big Clock in / Clock out button. The position is read ONCE, inside the
 * tap handler, with getCurrentPosition; nothing here watches or tracks. An
 * outside-the-fence tap is recorded and flagged for a supervisor, never
 * blocked: a gate on the wrong side of the fence must not cost a man his shift.
 * With no signal the tap is queued on the device with its own timestamp.
 */

import { useCallback, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { AlertTriangle, CheckCircle2, CloudOff, Loader2, LogIn, LogOut, ShieldCheck } from 'lucide-react';
import clsx from 'clsx';
import { ApiError, getErrorMessage } from '@/shared/lib/api';
import { listResources } from '@/features/resources/api';
import { newClientOpId } from '@/shared/lib/offline';
import { useOnlineStatus } from '@/shared/hooks/useOnlineStatus';
import { useToastStore } from '@/stores/useToastStore';
import {
  useClockConsent,
  useClockEventMutation,
  useClockSettings,
  useClockStatus,
  useSetClockConsent,
  type ClockEventPayload,
  type ClockKind,
} from './clockApi';
import { enqueueClockEvent } from './clockOffline';
import { useClockStore } from './clockStore';

interface Fix {
  latitude: number;
  longitude: number;
  accuracy_m: number;
}

/** One position read, taken at the tap. Resolves to null when the device gives none. */
export function readPositionOnce(): Promise<Fix | null> {
  return new Promise((resolve) => {
    if (typeof navigator === 'undefined' || !navigator.geolocation) {
      resolve(null);
      return;
    }
    navigator.geolocation.getCurrentPosition(
      (pos) =>
        resolve({
          latitude: pos.coords.latitude,
          longitude: pos.coords.longitude,
          accuracy_m: Math.round(pos.coords.accuracy),
        }),
      () => resolve(null),
      { enableHighAccuracy: true, timeout: 15000, maximumAge: 0 },
    );
  });
}

/** The machine-readable code the server puts in `detail.code`, if any. */
export function errorCode(err: unknown): string {
  if (err instanceof ApiError) {
    const detail = (err.body as { detail?: { code?: unknown } } | null)?.detail;
    if (detail && typeof detail === 'object' && typeof detail.code === 'string') return detail.code;
  }
  return '';
}

function ConsentDialog({
  retentionDays,
  busy,
  onAgree,
  onCancel,
}: {
  retentionDays: number;
  busy: boolean;
  onAgree: () => void;
  onCancel: () => void;
}) {
  const { t } = useTranslation();
  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={t('field_clock.consent_title', { defaultValue: 'Location consent' })}
      className="fixed inset-0 z-50 flex items-end justify-center bg-black/50 p-0 sm:items-center sm:p-4"
    >
      <div className="max-h-[90vh] w-full overflow-y-auto rounded-t-2xl bg-surface-primary p-5 shadow-xl sm:max-w-md sm:rounded-2xl">
        <div className="flex items-center gap-2 text-content-primary">
          <ShieldCheck size={20} className="text-oe-blue" />
          <h2 className="text-base font-semibold">
            {t('field_clock.consent_title', { defaultValue: 'Location consent' })}
          </h2>
        </div>
        <ul className="mt-3 list-disc space-y-2 pl-5 text-sm text-content-secondary">
          <li>
            {t('field_clock.consent_purpose', {
              defaultValue:
                'Purpose: to record when you start and finish work on this site, so your hours can be put on the timesheet.',
            })}
          </li>
          <li>
            {t('field_clock.consent_what', {
              defaultValue:
                'Only your position at the moment you tap Clock in or Clock out is stored. Your position is never tracked in between.',
            })}
          </li>
          <li>
            {t('field_clock.consent_retention', {
              defaultValue_one:
                'The stored position is deleted automatically after {{count}} day; the times stay on the timesheet.',
              defaultValue_other:
                'The stored position is deleted automatically after {{count}} days; the times stay on the timesheet.',
              count: retentionDays,
            })}
          </li>
          <li>
            {t('field_clock.consent_withdraw', {
              defaultValue:
                'You can withdraw this consent at any time on this screen. You can then still record your hours by hand.',
            })}
          </li>
        </ul>
        <div className="mt-5 flex flex-col gap-2 sm:flex-row-reverse">
          <button
            type="button"
            disabled={busy}
            onClick={onAgree}
            className="inline-flex min-h-[44px] flex-1 items-center justify-center gap-2 rounded-lg bg-oe-blue px-4 text-sm font-semibold text-content-inverse disabled:opacity-60"
          >
            {busy && <Loader2 size={15} className="animate-spin" />}
            {t('field_clock.consent_agree', { defaultValue: 'I agree' })}
          </button>
          <button
            type="button"
            onClick={onCancel}
            className="min-h-[44px] flex-1 rounded-lg border border-border-light px-4 text-sm font-medium text-content-secondary"
          >
            {t('field_clock.consent_cancel', { defaultValue: 'Not now' })}
          </button>
        </div>
      </div>
    </div>
  );
}

function timeOfDayLocal(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

export function ClockPanel({ projectId }: { projectId: string }) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const online = useOnlineStatus();
  const { resourceId, lastKind, result, setResourceId, setLastKind, setResult } = useClockStore();
  const [consentOpen, setConsentOpen] = useState(false);
  const [busy, setBusy] = useState(false);

  const settingsQ = useClockSettings(projectId);
  const statusQ = useClockStatus(projectId);
  const consentQ = useClockConsent(projectId, resourceId);
  const consentMut = useSetClockConsent();
  const eventMut = useClockEventMutation();

  const resourcesQ = useQuery({
    queryKey: ['resources', 'list', 'field-time', projectId],
    queryFn: () => listResources({ limit: 500, project_id: projectId }),
    enabled: !!projectId,
  });
  const workers = (resourcesQ.data?.items ?? []).filter((r) => r.resource_type !== 'equipment');

  const settings = settingsQ.data;
  const retentionDays = settings?.retention_days ?? 30;
  const textVersion = settings?.consent_text_version ?? '';
  const granted = consentQ.data?.granted === true;

  const serverIn = (statusQ.data?.on_site ?? []).find((w) => w.resource_id === resourceId);
  const state: ClockKind | null = resourceId ? (lastKind[resourceId] ?? (serverIn ? 'in' : 'out')) : null;
  const isCrew = workers.find((w) => w.id === resourceId)?.resource_type === 'crew';
  const nextKind: ClockKind = state === 'in' ? 'out' : 'in';

  const sendConsent = useCallback(
    async (grant: boolean) => {
      try {
        await consentMut.mutateAsync({
          project_id: projectId,
          resource_id: resourceId,
          granted: grant,
          text_version: textVersion,
        });
        setConsentOpen(false);
      } catch (e) {
        addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: getErrorMessage(e) });
      }
    },
    [consentMut, projectId, resourceId, textVersion, addToast, t],
  );

  const onTap = async () => {
    if (!resourceId || busy) return;
    // Consent is checked before the position is touched: no consent, no read.
    if (consentQ.data && !granted) {
      setConsentOpen(true);
      return;
    }
    setBusy(true);
    try {
      const fix = await readPositionOnce();
      const payload: ClockEventPayload = {
        project_id: projectId,
        resource_id: resourceId,
        kind: nextKind,
        latitude: fix?.latitude ?? null,
        longitude: fix?.longitude ?? null,
        accuracy_m: fix?.accuracy_m ?? null,
        occurred_at: new Date().toISOString(),
        client_op_id: newClientOpId(),
      };
      const queue = async () => {
        await enqueueClockEvent(payload);
        setLastKind(resourceId, nextKind);
        setResult({
          kind: nextKind,
          inside: null,
          distanceM: null,
          geofenceName: null,
          queued: true,
          positionMissing: !fix,
          at: payload.occurred_at ?? '',
        });
      };
      if (!online) {
        await queue();
        return;
      }
      try {
        const ev = await eventMut.mutateAsync({ ...payload, crew: isCrew });
        setLastKind(resourceId, nextKind);
        setResult({
          kind: ev.kind,
          inside: ev.inside,
          distanceM: ev.distance_m,
          geofenceName: ev.geofence_name,
          queued: false,
          positionMissing: !fix,
          at: ev.occurred_at,
          skipped: (ev as unknown as { skipped?: { resource_id: string; code: string }[] }).skipped,
        });
      } catch (e) {
        const code = errorCode(e);
        if (code === 'consent_required') {
          setConsentOpen(true);
        } else if (e instanceof ApiError) {
          addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: getErrorMessage(e) });
          if (code === 'already_clocked_in') setLastKind(resourceId, 'in');
          if (code === 'not_clocked_in') setLastKind(resourceId, 'out');
        } else {
          // The link dropped between the check and the send: keep the tap.
          await queue();
        }
      }
    } finally {
      setBusy(false);
    }
  };

  if (settingsQ.isSuccess && !settings?.enabled) {
    return (
      <div className="rounded-xl border border-border-light bg-surface-primary p-5 text-sm text-content-secondary">
        {t('field_clock.disabled', {
          defaultValue: 'The time clock is switched off for this project. A manager can turn it on under Settings.',
        })}
      </div>
    );
  }

  const isIn = state === 'in';

  return (
    <div className="mx-auto flex max-w-md flex-col gap-4">
      <div>
        <label htmlFor="clock-worker" className="mb-1 block text-xs font-medium text-content-secondary">
          {t('field_clock.worker', { defaultValue: 'Who is clocking?' })}
        </label>
        <select
          id="clock-worker"
          value={resourceId}
          onChange={(e) => setResourceId(e.target.value)}
          className="h-11 w-full rounded-lg border border-border-light bg-surface-primary px-3 text-sm text-content-primary"
        >
          <option value="">{t('field_clock.pick_worker', { defaultValue: 'Choose a worker' })}</option>
          {workers.map((r) => (
            <option key={r.id} value={r.id}>
              {r.name}
            </option>
          ))}
        </select>
      </div>

      {resourceId && (
        <p className="text-center text-sm text-content-secondary">
          {isIn
            ? serverIn
              ? t('field_clock.state_in_since', {
                  defaultValue: 'Clocked in since {{time}}',
                  time: timeOfDayLocal(serverIn.clocked_in_at),
                })
              : t('field_clock.state_in', { defaultValue: 'Clocked in' })
            : t('field_clock.state_out', { defaultValue: 'Not clocked in' })}
        </p>
      )}

      <button
        type="button"
        disabled={!resourceId || busy}
        onClick={onTap}
        className={clsx(
          'flex min-h-[96px] w-full items-center justify-center gap-3 rounded-2xl text-xl font-bold text-content-inverse shadow-sm transition-opacity disabled:opacity-50',
          isIn ? 'bg-semantic-error' : 'bg-oe-blue',
        )}
      >
        {busy ? <Loader2 size={26} className="animate-spin" /> : isIn ? <LogOut size={26} /> : <LogIn size={26} />}
        {isCrew
          ? nextKind === 'in'
            ? t('field_clock.clock_in_crew', { defaultValue: 'Clock in whole crew' })
            : t('field_clock.clock_out_crew', { defaultValue: 'Clock out whole crew' })
          : nextKind === 'in'
            ? t('field_clock.clock_in', { defaultValue: 'Clock in' })
            : t('field_clock.clock_out', { defaultValue: 'Clock out' })}
      </button>

      <p className="text-center text-xs text-content-tertiary">
        {t('field_clock.privacy_note', {
          defaultValue:
            'Your position is read once when you tap. It is not tracked in the background.',
        })}
      </p>

      {!online && (
        <p className="flex items-center justify-center gap-1.5 text-xs text-content-tertiary">
          <CloudOff size={13} />
          {t('field_clock.offline_note', {
            defaultValue: 'No signal. The tap is saved on this device and sent when you are back online.',
          })}
        </p>
      )}

      {result && (
        <div
          role="status"
          className={clsx(
            'flex items-start gap-2 rounded-xl border p-3 text-sm',
            result.queued || result.inside === false || result.positionMissing
              ? 'border-semantic-warning bg-semantic-warning-bg text-content-primary'
              : 'border-semantic-success bg-semantic-success-bg text-content-primary',
          )}
        >
          {result.inside === true && !result.positionMissing ? (
            <CheckCircle2 size={18} className="mt-0.5 shrink-0 text-semantic-success" />
          ) : (
            <AlertTriangle size={18} className="mt-0.5 shrink-0 text-semantic-warning" />
          )}
          <div className="space-y-1">
            <p className="font-medium">
              {result.kind === 'in'
                ? t('field_clock.result_in', { defaultValue: 'Clocked in at {{time}}', time: timeOfDayLocal(result.at) })
                : t('field_clock.result_out', { defaultValue: 'Clocked out at {{time}}', time: timeOfDayLocal(result.at) })}
            </p>
            {result.queued && (
              <p>
                {t('field_clock.result_queued', {
                  defaultValue: 'Saved on this device. It is sent when you are online; the site area is checked then.',
                })}
              </p>
            )}
            {!result.queued && result.inside === true && (
              <p>
                {result.geofenceName
                  ? t('field_clock.result_inside_named', {
                      defaultValue: 'Inside the site area: {{name}}.',
                      name: result.geofenceName,
                    })
                  : t('field_clock.result_inside', { defaultValue: 'Inside the site area.' })}
              </p>
            )}
            {!result.queued && result.inside === false && (
              <p>
                {result.distanceM != null
                  ? t('field_clock.result_outside_distance', {
                      defaultValue:
                        'Outside the site area, about {{meters}} m away. Recorded and flagged for supervisor approval.',
                      meters: Math.round(result.distanceM),
                    })
                  : t('field_clock.result_outside', {
                      defaultValue: 'Outside the site area. Recorded and flagged for supervisor approval.',
                    })}
              </p>
            )}
            {result.skipped && result.skipped.length > 0 && (
              <div>
                <p>
                  {t('field_clock.crew_skipped', {
                    defaultValue_one: '{{count}} crew member was not clocked:',
                    defaultValue_other: '{{count}} crew members were not clocked:',
                    count: result.skipped.length,
                  })}
                </p>
                <ul className="list-disc pl-5">
                  {result.skipped.map((s) => (
                    <li key={s.resource_id}>
                      {workers.find((w) => w.id === s.resource_id)?.name ?? s.resource_id}
                      {' - '}
                      {t(`field_clock.skip_${s.code}`, { defaultValue: s.code.replace(/_/g, ' ') })}
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {result.positionMissing && (
              <p>
                {t('field_clock.result_no_position', {
                  defaultValue:
                    'Your phone gave no position, so the tap is flagged for supervisor approval. Check that location is allowed for this app.',
                })}
              </p>
            )}
          </div>
        </div>
      )}

      {resourceId && granted && (
        <button
          type="button"
          onClick={() => {
            if (window.confirm(t('field_clock.withdraw_confirm', { defaultValue: 'Withdraw your location consent?' }))) {
              void sendConsent(false);
            }
          }}
          className="min-h-[44px] text-center text-xs text-content-tertiary underline"
        >
          {t('field_clock.withdraw_link', { defaultValue: 'Withdraw my location consent' })}
        </button>
      )}

      {consentOpen && (
        <ConsentDialog
          retentionDays={retentionDays}
          busy={consentMut.isPending}
          onAgree={() => void sendConsent(true)}
          onCancel={() => setConsentOpen(false)}
        />
      )}
    </div>
  );
}
