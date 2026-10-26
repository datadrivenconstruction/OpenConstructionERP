// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Clock approvals - the supervisor's list of taps that landed outside every​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
 * site area. Each shows how far out it was and, on request, a map pin. Approve
 * and Reject both need a written reason: the decision goes on the record.
 */

import { Suspense, lazy, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { CheckCircle2, Loader2, MapPin, XCircle } from 'lucide-react';
import { getErrorMessage } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import { mapSupported } from './GeofenceMap';
import { useClockEvents, useDecideClockEvent, useGeofences, type ClockEvent } from './clockApi';

const GeofenceMap = lazy(() => import('./GeofenceMap'));

export const MIN_REASON_LENGTH = 3;

function when(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString([], { dateStyle: 'short', timeStyle: 'short' });
}

function ApprovalCard({ event, projectId }: { event: ClockEvent; projectId: string }) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const decide = useDecideClockEvent();
  const fencesQ = useGeofences(projectId);
  const [reason, setReason] = useState('');
  const [showMap, setShowMap] = useState(false);

  const reasonOk = reason.trim().length >= MIN_REASON_LENGTH;
  const hasPos = event.latitude != null && event.longitude != null && !event.position_purged;

  const act = async (approve: boolean) => {
    if (!reasonOk) return;
    try {
      await decide.mutateAsync({ id: event.id, approve, reason: reason.trim() });
    } catch (e) {
      addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: getErrorMessage(e) });
    }
  };

  return (
    <li className="space-y-3 rounded-xl border border-border-light bg-surface-primary p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <p className="text-sm font-semibold text-content-primary">{event.resource_name}</p>
          <p className="text-xs text-content-tertiary">
            {event.kind === 'in'
              ? t('field_clock.event_in', { defaultValue: 'Clock in' })
              : t('field_clock.event_out', { defaultValue: 'Clock out' })}
            {' · '}
            {when(event.occurred_at)}
          </p>
        </div>
        <p className="text-sm font-medium text-semantic-warning">
          {event.distance_m != null
            ? t('field_clock.outside_by', {
                defaultValue: '{{meters}} m outside the site area',
                meters: Math.round(event.distance_m),
              })
            : t('field_clock.no_position_flag', { defaultValue: 'No position from the phone' })}
        </p>
      </div>

      {hasPos && mapSupported() && (
        <div>
          <button
            type="button"
            onClick={() => setShowMap((v) => !v)}
            className="inline-flex min-h-[44px] items-center gap-1.5 text-sm text-oe-blue-text"
          >
            <MapPin size={14} />
            {showMap
              ? t('field_clock.hide_map', { defaultValue: 'Hide map' })
              : t('field_clock.show_map', { defaultValue: 'Show on map' })}
          </button>
          {showMap && (
            <div className="mt-2 h-56 overflow-hidden rounded-lg border border-border-light">
              <Suspense fallback={<Loader2 size={16} className="m-4 animate-spin" />}>
                <GeofenceMap
                  fences={fencesQ.data ?? []}
                  pins={[
                    {
                      id: event.id,
                      lat: event.latitude as number,
                      lng: event.longitude as number,
                      label: event.resource_name,
                      tone: 'warn',
                    },
                  ]}
                />
              </Suspense>
            </div>
          )}
        </div>
      )}

      <div>
        <label htmlFor={`reason-${event.id}`} className="mb-1 block text-xs font-medium text-content-secondary">
          {t('field_clock.reason', { defaultValue: 'Reason (required)' })}
        </label>
        <textarea
          id={`reason-${event.id}`}
          rows={2}
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          className="w-full rounded-lg border border-border-light bg-surface-primary p-3 text-sm text-content-primary"
        />
      </div>

      <div className="flex flex-col gap-2 sm:flex-row">
        <button
          type="button"
          disabled={!reasonOk || decide.isPending}
          onClick={() => void act(true)}
          className="inline-flex min-h-[44px] flex-1 items-center justify-center gap-2 rounded-lg bg-semantic-success px-4 text-sm font-semibold text-content-inverse disabled:opacity-50"
        >
          <CheckCircle2 size={16} />
          {t('field_clock.approve', { defaultValue: 'Approve' })}
        </button>
        <button
          type="button"
          disabled={!reasonOk || decide.isPending}
          onClick={() => void act(false)}
          className="inline-flex min-h-[44px] flex-1 items-center justify-center gap-2 rounded-lg border border-semantic-error px-4 text-sm font-semibold text-semantic-error disabled:opacity-50"
        >
          <XCircle size={16} />
          {t('field_clock.reject', { defaultValue: 'Reject' })}
        </button>
      </div>
    </li>
  );
}

export function ClockApprovals({ projectId }: { projectId: string }) {
  const { t } = useTranslation();
  const q = useClockEvents(projectId, { approval_status: 'pending' });

  if (q.isLoading) {
    return (
      <div className="flex items-center justify-center gap-2 py-12 text-sm text-content-tertiary">
        <Loader2 size={16} className="animate-spin" />
        {t('common.loading', { defaultValue: 'Loading...' })}
      </div>
    );
  }
  if (q.isError) {
    return <p className="py-8 text-center text-sm text-semantic-error">{getErrorMessage(q.error)}</p>;
  }
  const items = q.data?.items ?? [];
  if (items.length === 0) {
    return (
      <p className="rounded-xl border border-dashed border-border p-6 text-center text-sm text-content-tertiary">
        {t('field_clock.approvals_empty', { defaultValue: 'Nothing waiting for approval.' })}
      </p>
    );
  }
  return (
    <ul className="flex flex-col gap-3">
      {items.map((e) => (
        <ApprovalCard key={e.id} event={e} projectId={projectId} />
      ))}
    </ul>
  );
}
