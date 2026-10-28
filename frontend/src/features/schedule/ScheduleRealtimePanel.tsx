// DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
//
// Real-time collaboration panel (T3.4). A self-contained view mode mounted in
// SchedulePage, modelled on the sibling schedule panels (ScheduleResourcePanel /
// ScheduleCodesPanel). Two stacked sections over the realtime backend (see the
// derived contract in features/schedule/api.ts):
//
//   - Presence roster: polls who is currently connected to this schedule's
//     presence room (GET /schedules/{id}/presence/) every ~10s and lists each
//     co-editor. The live channel is a WebSocket; this REST snapshot is the
//     lightweight "who is here" surface that needs no socket wiring.
//
//   - Guarded edit (optimistic concurrency): pick an activity, read its current
//     revision token (GET /activities/{id}/revision/), then submit a guarded
//     update (progress / status) carrying that base revision. The backend
//     applies it only if the base is still current; a concurrent edit returns
//     HTTP 409 (stale) and we render a clear reload-then-retry recovery, while a
//     malformed base / non-editable field returns HTTP 422 (shown inline). We
//     distinguish 409 vs 422 off the shared client's ApiError.status.
//
// Activity ids arrive as raw UUID strings; an optional ``activitiesById`` name
// map (the caller already holds the Gantt rows) renders readable labels.

import { useEffect, useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import {
  Users,
  Radio,
  RefreshCw,
  Loader2,
  Check,
  AlertTriangle,
  ShieldCheck,
} from 'lucide-react';

import { Button, Card, Badge, EmptyState, RecoveryCard, SkeletonTable } from '@/shared/ui';
import { useToastStore } from '@/stores/useToastStore';
import { ApiError, getErrorMessage } from '@/shared/lib/api';
import {
  scheduleApi,
  type RevisionConflict,
  type GuardedUpdateFields,
} from './api';

interface ScheduleRealtimePanelProps {
  scheduleId: string;
  projectId: string;
  /** Optional id -> display name map so the activity picker shows names, not UUIDs. */
  activitiesById?: Record<string, string>;
}

const inputCls =
  'h-9 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';
const labelCls =
  'block text-2xs font-medium uppercase tracking-wide text-content-secondary mb-1';

/** Poll the presence roster on this cadence (ms) so "who is here" stays fresh. */
const PRESENCE_REFETCH_MS = 10_000;

const STATUS_OPTIONS = ['not_started', 'in_progress', 'completed', 'on_hold'] as const;

export function ScheduleRealtimePanel({
  scheduleId,
  projectId: _projectId,
  activitiesById,
}: ScheduleRealtimePanelProps) {
  const { t } = useTranslation();

  return (
    <div className="space-y-4" data-testid="schedule-realtime-panel">
      {/* Header */}
      <div className="flex flex-wrap items-center gap-2">
        <Radio size={18} className="text-content-secondary" />
        <h3 className="text-base font-semibold text-content-primary">
          {t('schedule.realtime.title', { defaultValue: 'Real-time collaboration' })}
        </h3>
      </div>
      <p className="-mt-2 text-xs text-content-secondary">
        {t('schedule.realtime.subtitle', {
          defaultValue:
            'See who is editing this schedule right now, and make a lost-update-safe change to an activity. A guarded edit only applies when no one has changed the activity since you loaded it.',
        })}
      </p>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[320px_1fr]">
        <PresenceRoster scheduleId={scheduleId} />
        <GuardedEdit scheduleId={scheduleId} activitiesById={activitiesById} />
      </div>
    </div>
  );
}

/* ── Presence roster ─────────────────────────────────────────────────────── */

function PresenceRoster({ scheduleId }: { scheduleId: string }) {
  const { t } = useTranslation();

  const presenceQ = useQuery({
    queryKey: ['schedule', 'presence', scheduleId],
    queryFn: () => scheduleApi.getPresence(scheduleId),
    refetchInterval: PRESENCE_REFETCH_MS,
  });

  const users = presenceQ.data?.users ?? [];

  return (
    <Card padding="md" data-testid="realtime-presence">
      <div className="mb-3 flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <Users size={16} className="text-content-secondary" />
          <h4 className="text-sm font-semibold text-content-primary">
            {t('schedule.realtime.presence_title', { defaultValue: 'Currently editing' })}
          </h4>
        </div>
        {!presenceQ.isLoading && !presenceQ.isError && (
          <Badge variant={users.length > 0 ? 'success' : 'neutral'} size="sm">
            {users.length}
          </Badge>
        )}
      </div>

      {presenceQ.isLoading ? (
        <div data-testid="realtime-presence-loading">
          <SkeletonTable rows={3} columns={1} />
        </div>
      ) : presenceQ.isError ? (
        <RecoveryCard error={presenceQ.error} onRetry={() => presenceQ.refetch()} />
      ) : users.length === 0 ? (
        <EmptyState
          icon={<Users size={28} strokeWidth={1.5} />}
          title={t('schedule.realtime.presence_empty', { defaultValue: 'No one else is here' })}
          description={t('schedule.realtime.presence_empty_desc', {
            defaultValue:
              'You are the only person on this schedule right now. When teammates open it, they appear here so you can avoid stepping on each other.',
          })}
        />
      ) : (
        <ul className="space-y-1.5" data-testid="realtime-presence-list">
          {users.map((u) => (
            <li
              key={u.user_id}
              className="flex items-center gap-2.5 rounded-lg border border-border-light bg-surface-secondary/40 px-3 py-2"
            >
              <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-oe-blue/10 text-2xs font-semibold uppercase text-oe-blue">
                {initials(u.user_name || u.user_id)}
              </span>
              <span className="min-w-0 flex-1 truncate text-sm text-content-primary">
                {u.user_name || u.user_id}
              </span>
              <span className="inline-flex h-2 w-2 shrink-0 rounded-full bg-semantic-success" aria-hidden />
            </li>
          ))}
        </ul>
      )}

      <p className="mt-3 text-2xs text-content-tertiary">
        {t('schedule.realtime.presence_hint', {
          defaultValue: 'Updates automatically every few seconds.',
        })}
      </p>
    </Card>
  );
}

/* ── Guarded edit (optimistic concurrency) ───────────────────────────────── */

function GuardedEdit({
  scheduleId,
  activitiesById,
}: {
  scheduleId: string;
  activitiesById?: Record<string, string>;
}) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const queryClient = useQueryClient();

  const activityOptions = useMemo(
    () => Object.entries(activitiesById ?? {}).sort((a, b) => a[1].localeCompare(b[1])),
    [activitiesById],
  );

  const [activityId, setActivityId] = useState<string>('');
  const [field, setField] = useState<'progress_pct' | 'status'>('progress_pct');
  const [progress, setProgress] = useState<string>('');
  const [status, setStatus] = useState<string>('in_progress');

  // The base revision the client last read; the guarded update carries it so a
  // concurrent edit is detected (409). Refreshed by the revision query.
  const [baseRevision, setBaseRevision] = useState<number | null>(null);
  // A detected stale conflict (set on 409); cleared on reload / successful apply.
  const [conflict, setConflict] = useState<RevisionConflict | null>(null);
  // An inline validation message (set on 422).
  const [validationError, setValidationError] = useState<string | null>(null);

  // Default the picker to the first activity once names are available.
  const resolvedActivityId =
    activityId || (activityOptions.length > 0 ? activityOptions[0]![0] : '');

  const revisionQ = useQuery({
    queryKey: ['schedule', 'activity-revision', resolvedActivityId],
    queryFn: () => scheduleApi.getActivityRevision(resolvedActivityId),
    enabled: !!resolvedActivityId,
  });

  // Adopt the freshly-read revision as the client base, and clear any prior
  // conflict/validation state, whenever a new revision loads (initial load,
  // activity switch, or an explicit reload after a conflict).
  useEffect(() => {
    if (revisionQ.data) {
      setBaseRevision(revisionQ.data.revision);
      setConflict(null);
      setValidationError(null);
    }
  }, [revisionQ.data]);

  const buildFields = (): GuardedUpdateFields => {
    if (field === 'progress_pct') {
      return { progress_pct: Number(progress) };
    }
    return { status };
  };

  const progressValid =
    field !== 'progress_pct' ||
    (progress.trim() !== '' &&
      Number.isFinite(Number(progress)) &&
      Number(progress) >= 0 &&
      Number(progress) <= 100);

  const updateMut = useMutation({
    mutationFn: () =>
      scheduleApi.guardedUpdateActivity(resolvedActivityId, baseRevision, buildFields()),
    onSuccess: (data) => {
      setBaseRevision(data.revision);
      setConflict(null);
      setValidationError(null);
      // The activity changed, so other schedule surfaces (Gantt, grouped grid)
      // should refetch to reflect the new value.
      queryClient.invalidateQueries({ queryKey: ['gantt', scheduleId] });
      queryClient.invalidateQueries({
        queryKey: ['schedule', 'activity-revision', resolvedActivityId],
      });
      addToast({
        type: 'success',
        title: t('schedule.realtime.update_applied', { defaultValue: 'Change saved' }),
        message: t('schedule.realtime.update_applied_detail', {
          defaultValue: 'The activity is now at revision {{revision}}.',
          revision: data.revision,
        }),
      });
    },
    onError: (err) => {
      // Distinguish the optimistic-concurrency conflict (409) from a validation
      // failure (422) off the shared client's ApiError.status.
      if (err instanceof ApiError && err.status === 409) {
        const body = err.body as RevisionConflict | undefined;
        setConflict(
          body && typeof body.current_revision === 'number'
            ? body
            : {
                detail: 'Activity was modified by another user',
                current_revision: baseRevision ?? 0,
                current_state: {},
              },
        );
        setValidationError(null);
        return;
      }
      if (err instanceof ApiError && err.status === 422) {
        setValidationError(getErrorMessage(err));
        setConflict(null);
        return;
      }
      // Anything else (network, 401/403, 5xx) -> toast via the shared message.
      addToast({
        type: 'error',
        title: t('common.error', { defaultValue: 'Error' }),
        message: getErrorMessage(err),
      });
    },
  });

  /** Reload the authoritative revision after a conflict, then let the user retry. */
  const onReload = () => {
    revisionQ.refetch();
  };

  const canSubmit =
    !!resolvedActivityId &&
    baseRevision !== null &&
    !revisionQ.isLoading &&
    !updateMut.isPending &&
    progressValid &&
    conflict === null;

  return (
    <Card padding="md" data-testid="realtime-guarded-edit">
      <div className="mb-1 flex items-center gap-2">
        <ShieldCheck size={16} className="text-content-secondary" />
        <h4 className="text-sm font-semibold text-content-primary">
          {t('schedule.realtime.guarded_title', { defaultValue: 'Guarded activity edit' })}
        </h4>
      </div>
      <p className="mb-3 text-2xs text-content-tertiary">
        {t('schedule.realtime.guarded_hint', {
          defaultValue:
            'Your change is tagged with the revision you loaded. If someone edits this activity first, we will not overwrite their work - you will be asked to reload and retry.',
        })}
      </p>

      {activityOptions.length === 0 ? (
        <EmptyState
          icon={<AlertTriangle size={28} strokeWidth={1.5} />}
          title={t('schedule.realtime.no_activities', { defaultValue: 'No activities yet' })}
          description={t('schedule.realtime.no_activities_desc', {
            defaultValue:
              'Add activities to this schedule first, then come back to make a lost-update-safe edit.',
          })}
        />
      ) : (
        <div className="space-y-3">
          {/* Activity picker + current revision */}
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-[1fr_auto] sm:items-end">
            <div>
              <label htmlFor="rt-activity" className={labelCls}>
                {t('schedule.realtime.activity', { defaultValue: 'Activity' })}
              </label>
              <select
                id="rt-activity"
                value={resolvedActivityId}
                onChange={(e) => setActivityId(e.target.value)}
                className={inputCls}
              >
                {activityOptions.map(([id, name]) => (
                  <option key={id} value={id}>
                    {name}
                  </option>
                ))}
              </select>
            </div>
            <div className="rounded-lg border border-border-light bg-surface-secondary/40 px-3 py-2 text-center">
              <div className="text-2xs uppercase tracking-wide text-content-tertiary">
                {t('schedule.realtime.revision', { defaultValue: 'Revision' })}
              </div>
              <div
                className="mt-0.5 text-lg font-bold tabular-nums text-content-primary"
                data-testid="realtime-revision"
              >
                {revisionQ.isLoading ? (
                  <Loader2 size={16} className="mx-auto animate-spin text-content-tertiary" />
                ) : revisionQ.isError ? (
                  '-'
                ) : (
                  (baseRevision ?? '-')
                )}
              </div>
            </div>
          </div>

          {revisionQ.isError && (
            <RecoveryCard error={revisionQ.error} onRetry={() => revisionQ.refetch()} />
          )}

          {/* Field selector */}
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div>
              <label htmlFor="rt-field" className={labelCls}>
                {t('schedule.realtime.field', { defaultValue: 'Field to change' })}
              </label>
              <select
                id="rt-field"
                value={field}
                onChange={(e) => setField(e.target.value as 'progress_pct' | 'status')}
                className={inputCls}
              >
                <option value="progress_pct">
                  {t('schedule.realtime.field_progress', { defaultValue: 'Progress (%)' })}
                </option>
                <option value="status">
                  {t('schedule.realtime.field_status', { defaultValue: 'Status' })}
                </option>
              </select>
            </div>
            <div>
              {field === 'progress_pct' ? (
                <>
                  <label htmlFor="rt-progress" className={labelCls}>
                    {t('schedule.realtime.new_progress', { defaultValue: 'New progress (%)' })}
                  </label>
                  <input
                    id="rt-progress"
                    type="number"
                    min={0}
                    max={100}
                    step={1}
                    value={progress}
                    onChange={(e) => setProgress(e.target.value)}
                    placeholder="0 - 100"
                    className={inputCls}
                  />
                </>
              ) : (
                <>
                  <label htmlFor="rt-status" className={labelCls}>
                    {t('schedule.realtime.new_status', { defaultValue: 'New status' })}
                  </label>
                  <select
                    id="rt-status"
                    value={status}
                    onChange={(e) => setStatus(e.target.value)}
                    className={inputCls}
                  >
                    {STATUS_OPTIONS.map((s) => (
                      <option key={s} value={s}>
                        {t(`schedule.status_${s}`, {
                          defaultValue: s.replace(/_/g, ' '),
                        })}
                      </option>
                    ))}
                  </select>
                </>
              )}
            </div>
          </div>

          {/* Stale-conflict recovery (HTTP 409) */}
          {conflict && (
            <div
              className="rounded-lg border border-semantic-warning/40 bg-semantic-warning/5 p-4"
              data-testid="realtime-conflict"
              role="alert"
            >
              <div className="flex items-start gap-2.5">
                <AlertTriangle size={18} className="mt-0.5 shrink-0 text-semantic-warning" />
                <div className="min-w-0 flex-1">
                  <h5 className="text-sm font-semibold text-content-primary">
                    {t('schedule.realtime.conflict_title', {
                      defaultValue: 'This activity changed since you loaded it',
                    })}
                  </h5>
                  <p className="mt-1 text-xs text-content-secondary">
                    {t('schedule.realtime.conflict_desc', {
                      defaultValue:
                        'Another user saved a change first (now at revision {{revision}}). To avoid overwriting their work, reload to get the latest, then retry your edit.',
                      revision: conflict.current_revision,
                    })}
                  </p>
                  <div className="mt-3">
                    <Button
                      variant="secondary"
                      size="sm"
                      onClick={onReload}
                      loading={revisionQ.isFetching}
                      icon={<RefreshCw size={14} />}
                    >
                      {t('schedule.realtime.reload_retry', {
                        defaultValue: 'Reload latest',
                      })}
                    </Button>
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* Inline validation error (HTTP 422) */}
          {validationError && (
            <p
              className="flex items-center gap-1.5 text-2xs text-semantic-error"
              data-testid="realtime-validation"
              role="alert"
            >
              <AlertTriangle size={12} className="shrink-0" />
              {validationError}
            </p>
          )}

          {/* Submit */}
          <div className="flex flex-wrap items-center gap-2 border-t border-border-light pt-3">
            <Button
              variant="primary"
              size="sm"
              onClick={() => updateMut.mutate()}
              disabled={!canSubmit}
              icon={
                updateMut.isPending ? (
                  <Loader2 size={14} className="animate-spin" />
                ) : (
                  <Check size={14} />
                )
              }
            >
              {t('schedule.realtime.save_guarded', { defaultValue: 'Save change' })}
            </Button>
            {!progressValid && (
              <span className="text-2xs text-semantic-warning">
                {t('schedule.realtime.progress_range', {
                  defaultValue: 'Enter a progress value between 0 and 100.',
                })}
              </span>
            )}
          </div>
        </div>
      )}
    </Card>
  );
}

/* ── helpers ─────────────────────────────────────────────────────────────── */

/** Up to two uppercase initials from a name / id, for the presence avatar. */
function initials(nameOrId: string): string {
  const parts = nameOrId.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return '?';
  if (parts.length === 1) return parts[0]!.slice(0, 2).toUpperCase();
  return (parts[0]![0]! + parts[parts.length - 1]![0]!).toUpperCase();
}

export default ScheduleRealtimePanel;
