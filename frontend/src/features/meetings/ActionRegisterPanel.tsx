// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// ActionRegisterPanel — the tracked-action register shown inside a meeting's
// expanded row. Each action carries an owner, a due date and a status
// (open / in progress / done / cancelled). Open actions raised in an earlier
// meeting of the same recurring series surface here as "brought forward" until
// they are closed; closing one closes it for the whole series. A site engineer
// sees exactly what is still owed and by whom.

import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { AlertTriangle, ArrowUpRight, ListChecks, Loader2, Plus, Trash2 } from 'lucide-react';
import { Badge, Button } from '@/shared/ui';
import { useToastStore } from '@/stores/useToastStore';
import {
  ACTION_STATUSES,
  addMeetingAction,
  deleteMeetingAction,
  fetchMeetingActions,
  updateMeetingAction,
  type ActionRegisterItem,
  type ActionStatus,
  type MeetingActions,
} from './api';
import { SeriesActionRegisterDialog } from './SeriesActionRegisterDialog';

interface ActionRegisterPanelProps {
  meetingId: string;
  seriesId: string | null;
}

const inputCls =
  'h-8 rounded-md border border-border bg-surface-primary px-2 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';

function statusLabel(t: ReturnType<typeof useTranslation>['t'], status: ActionStatus): string {
  const fallback: Record<ActionStatus, string> = {
    open: 'Open',
    in_progress: 'In progress',
    done: 'Done',
    cancelled: 'Cancelled',
  };
  return t(`meetings.action_status_${status}`, { defaultValue: fallback[status] });
}

/** One editable action row: owner + due patch on blur, status via a select. */
function ActionRow({
  action,
  closingMeetingId,
  onPatch,
  onDelete,
  busy,
}: {
  action: ActionRegisterItem;
  closingMeetingId: string;
  onPatch: (id: string, payload: Parameters<typeof updateMeetingAction>[1]) => void;
  onDelete: (id: string) => void;
  busy: boolean;
}) {
  const { t } = useTranslation();
  const [owner, setOwner] = useState(action.owner_name ?? '');
  const [due, setDue] = useState(action.due_date ?? '');

  // Re-sync local fields when the server row changes (e.g. after a refetch).
  useEffect(() => {
    setOwner(action.owner_name ?? '');
    setDue(action.due_date ?? '');
  }, [action.owner_name, action.due_date]);

  const commitOwner = () => {
    const next = owner.trim();
    if (next !== (action.owner_name ?? '')) {
      onPatch(action.id, { owner_name: next || null });
    }
  };
  const commitDue = () => {
    if (due !== (action.due_date ?? '')) {
      onPatch(action.id, { due_date: due || null });
    }
  };

  const closed = action.status === 'done' || action.status === 'cancelled';

  return (
    <div className="flex flex-wrap items-center gap-2 rounded-md border border-border-light bg-surface-primary px-2.5 py-2">
      <div className="flex-1 min-w-[180px]">
        <p
          className={
            'text-sm text-content-primary' + (closed ? ' line-through text-content-tertiary' : '')
          }
        >
          {action.description}
        </p>
        <div className="mt-1 flex flex-wrap items-center gap-1.5">
          {action.brought_forward && (
            <Badge variant="warning" size="sm">
              <ArrowUpRight size={11} className="mr-0.5" />
              {t('meetings.brought_forward', { defaultValue: 'Brought forward' })}
              {action.origin_meeting_number ? ` · ${action.origin_meeting_number}` : ''}
            </Badge>
          )}
          {action.overdue && (
            <Badge variant="error" size="sm">
              <AlertTriangle size={11} className="mr-0.5" />
              {t('meetings.overdue', { defaultValue: 'Overdue' })}
            </Badge>
          )}
        </div>
      </div>

      <input
        value={owner}
        onChange={(e) => setOwner(e.target.value)}
        onBlur={commitOwner}
        placeholder={t('meetings.action_owner', { defaultValue: 'Owner' })}
        aria-label={t('meetings.action_owner', { defaultValue: 'Owner' })}
        className={inputCls + ' w-28'}
        disabled={busy}
      />
      <input
        type="date"
        value={due}
        onChange={(e) => setDue(e.target.value)}
        onBlur={commitDue}
        aria-label={t('meetings.action_due', { defaultValue: 'Due' })}
        className={inputCls + ' w-36'}
        disabled={busy}
      />
      <select
        value={action.status}
        onChange={(e) => {
          const next = e.target.value as ActionStatus;
          onPatch(action.id, {
            status: next,
            closing_meeting_id: next === 'done' || next === 'cancelled' ? closingMeetingId : null,
          });
        }}
        aria-label={t('meetings.action_status', { defaultValue: 'Status' })}
        className={inputCls}
        disabled={busy}
      >
        {ACTION_STATUSES.map((s) => (
          <option key={s} value={s}>
            {statusLabel(t, s)}
          </option>
        ))}
      </select>
      <button
        type="button"
        onClick={() => onDelete(action.id)}
        disabled={busy}
        aria-label={t('common.delete', { defaultValue: 'Delete' })}
        className="flex h-7 w-7 items-center justify-center rounded text-content-tertiary hover:text-semantic-error hover:bg-red-50 dark:hover:bg-red-950/30 transition-colors"
      >
        <Trash2 size={13} />
      </button>
    </div>
  );
}

export function ActionRegisterPanel({ meetingId, seriesId }: ActionRegisterPanelProps) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [showSeries, setShowSeries] = useState(false);

  const [desc, setDesc] = useState('');
  const [owner, setOwner] = useState('');
  const [due, setDue] = useState('');

  const actionsQ = useQuery<MeetingActions>({
    queryKey: ['meeting-actions', meetingId],
    queryFn: () => fetchMeetingActions(meetingId),
    staleTime: 15_000,
  });

  const invalidate = () => {
    void qc.invalidateQueries({ queryKey: ['meeting-actions', meetingId] });
    if (seriesId) void qc.invalidateQueries({ queryKey: ['series-actions', seriesId] });
  };

  const addMut = useMutation({
    mutationFn: () =>
      addMeetingAction(meetingId, {
        description: desc.trim(),
        owner_name: owner.trim() || null,
        due_date: due || null,
        status: 'open',
      }),
    onSuccess: () => {
      setDesc('');
      setOwner('');
      setDue('');
      invalidate();
    },
    onError: (e: Error) =>
      addToast({
        type: 'error',
        title: t('meetings.action_add_failed', { defaultValue: 'Could not add action item' }),
        message: e.message,
      }),
  });

  const patchMut = useMutation({
    mutationFn: ({ id, payload }: { id: string; payload: Parameters<typeof updateMeetingAction>[1] }) =>
      updateMeetingAction(id, payload),
    onSuccess: () => invalidate(),
    onError: (e: Error) =>
      addToast({
        type: 'error',
        title: t('meetings.action_update_failed', { defaultValue: 'Could not update action item' }),
        message: e.message,
      }),
  });

  const deleteMut = useMutation({
    mutationFn: (id: string) => deleteMeetingAction(id),
    onSuccess: () => invalidate(),
    onError: (e: Error) =>
      addToast({
        type: 'error',
        title: t('meetings.action_delete_failed', { defaultValue: 'Could not delete action item' }),
        message: e.message,
      }),
  });

  const busy = patchMut.isPending || deleteMut.isPending;
  const brought = actionsQ.data?.brought_forward ?? [];
  const own = actionsQ.data?.own ?? [];
  const canAdd = desc.trim().length > 0 && owner.trim().length > 0 && due.length === 10;

  const handlePatch = (id: string, payload: Parameters<typeof updateMeetingAction>[1]) =>
    patchMut.mutate({ id, payload });

  return (
    <div
      className="rounded-lg bg-blue-50 dark:bg-blue-950/20 border border-blue-200 dark:border-blue-800 p-3"
      data-testid="meeting-action-register"
    >
      <div className="flex items-center justify-between gap-2 mb-2 flex-wrap">
        <p className="text-xs text-blue-700 dark:text-blue-400 font-medium uppercase tracking-wide flex items-center gap-1.5">
          <ListChecks size={12} />
          {t('meetings.tracked_actions', { defaultValue: 'Tracked actions' })}
          {own.length + brought.length > 0 && (
            <span className="text-content-secondary normal-case font-normal">
              ({own.length + brought.length})
            </span>
          )}
        </p>
        {seriesId && (
          <Button
            variant="secondary"
            size="sm"
            onClick={(e) => {
              e.stopPropagation();
              setShowSeries(true);
            }}
            data-testid="meeting-series-register-open"
          >
            {t('meetings.series_register', { defaultValue: 'Series register' })}
          </Button>
        )}
      </div>

      {actionsQ.isLoading ? (
        <p className="text-xs text-content-tertiary">
          <Loader2 size={12} className="inline animate-spin mr-1" />
          {t('common.loading', { defaultValue: 'Loading…' })}
        </p>
      ) : (
        <div className="space-y-3">
          {/* Brought forward from earlier meetings in the series */}
          {brought.length > 0 && (
            <div className="space-y-1.5">
              <p className="text-2xs font-medium text-amber-700 dark:text-amber-400 uppercase tracking-wide">
                {t('meetings.brought_forward_heading', {
                  defaultValue: 'Brought forward ({{count}})',
                  count: brought.length,
                })}
              </p>
              {brought.map((a) => (
                <ActionRow
                  key={a.id}
                  action={a}
                  closingMeetingId={meetingId}
                  onPatch={handlePatch}
                  onDelete={(id) => deleteMut.mutate(id)}
                  busy={busy}
                />
              ))}
            </div>
          )}

          {/* This meeting's own actions */}
          <div className="space-y-1.5">
            {brought.length > 0 && (
              <p className="text-2xs font-medium text-content-tertiary uppercase tracking-wide">
                {t('meetings.raised_here', { defaultValue: 'Raised in this meeting' })}
              </p>
            )}
            {own.length === 0 ? (
              <p className="text-xs text-content-tertiary italic">
                {t('meetings.no_actions_yet', {
                  defaultValue: 'No action items raised in this meeting yet.',
                })}
              </p>
            ) : (
              own.map((a) => (
                <ActionRow
                  key={a.id}
                  action={a}
                  closingMeetingId={meetingId}
                  onPatch={handlePatch}
                  onDelete={(id) => deleteMut.mutate(id)}
                  busy={busy}
                />
              ))
            )}
          </div>

          {/* Add a new action */}
          <div className="flex flex-wrap items-center gap-2 border-t border-blue-200 dark:border-blue-800 pt-2.5">
            <input
              value={desc}
              onChange={(e) => setDesc(e.target.value)}
              placeholder={t('meetings.action_desc_placeholder', {
                defaultValue: 'New action item…',
              })}
              aria-label={t('meetings.action_description', { defaultValue: 'Action item' })}
              className={inputCls + ' flex-1 min-w-[180px]'}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && canAdd && !addMut.isPending) addMut.mutate();
              }}
            />
            <input
              value={owner}
              onChange={(e) => setOwner(e.target.value)}
              placeholder={t('meetings.action_owner', { defaultValue: 'Owner' })}
              aria-label={t('meetings.action_owner', { defaultValue: 'Owner' })}
              className={inputCls + ' w-28'}
            />
            <input
              type="date"
              value={due}
              onChange={(e) => setDue(e.target.value)}
              aria-label={t('meetings.action_due', { defaultValue: 'Due' })}
              className={inputCls + ' w-36'}
            />
            <Button
              variant="primary"
              size="sm"
              onClick={(e) => {
                e.stopPropagation();
                addMut.mutate();
              }}
              disabled={!canAdd || addMut.isPending}
              data-testid="meeting-action-add"
            >
              {addMut.isPending ? (
                <Loader2 size={14} className="mr-1.5 animate-spin" />
              ) : (
                <Plus size={14} className="mr-1.5" />
              )}
              {t('common.add', { defaultValue: 'Add' })}
            </Button>
          </div>
          <p className="text-2xs text-content-tertiary">
            {t('meetings.action_owner_due_hint', {
              defaultValue: 'An action item needs an owner and a due date so it can be followed up.',
            })}
          </p>
        </div>
      )}

      {showSeries && seriesId && (
        <SeriesActionRegisterDialog seriesId={seriesId} onClose={() => setShowSeries(false)} />
      )}
    </div>
  );
}
