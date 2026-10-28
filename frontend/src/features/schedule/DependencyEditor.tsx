// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Plus, Trash2, GitBranch } from 'lucide-react';
import { Button } from '@/shared/ui';
import { useToastStore } from '@/stores/useToastStore';
import {
  scheduleApi,
  type Activity,
  type RelationshipType,
  type RelationshipUpdateBody,
} from './api';

/** Link types in the order they read most naturally in the picker. */
const REL_TYPES: RelationshipType[] = ['FS', 'SS', 'FF', 'SF'];

const SELECT_CLS =
  'rounded-md border border-border-light bg-surface-primary px-2 py-1.5 text-sm text-content-primary';

/**
 * Predecessor editor for a single activity.
 *
 * Lists the dependency edges that point at ``activity`` (its predecessors),
 * lets the planner pick another activity as a predecessor, choose the link
 * type (FS/SS/FF/SF) and a lag in days (negative = lead), and add / retype /
 * relag / remove each row. Every change writes through the relationship CRUD
 * API and then triggers a reschedule so the Gantt bars and dependency arrows
 * move; the gantt + relationship queries are invalidated to refetch.
 */
export function DependencyEditor({
  scheduleId,
  activity,
  activities,
}: {
  scheduleId: string;
  activity: Activity;
  activities: Activity[];
}) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);

  const [newPredId, setNewPredId] = useState('');
  const [newType, setNewType] = useState<RelationshipType>('FS');
  const [newLag, setNewLag] = useState('0');

  const relationshipsKey = ['schedule-relationships', scheduleId];

  const { data: relationships = [], isLoading } = useQuery({
    queryKey: relationshipsKey,
    queryFn: () => scheduleApi.listRelationships(scheduleId),
  });

  const predecessorRows = useMemo(
    () => relationships.filter((r) => r.successor_id === activity.id),
    [relationships, activity.id],
  );

  const nameById = useMemo(() => {
    const m = new Map<string, string>();
    for (const a of activities) m.set(a.id, a.name);
    return m;
  }, [activities]);

  // Candidate predecessors: every other activity that is not already a
  // predecessor of this one. The backend still rejects self-references and
  // cycles, so this is a convenience filter, not the guard.
  const candidates = useMemo(() => {
    const used = new Set(predecessorRows.map((r) => r.predecessor_id));
    return activities.filter((a) => a.id !== activity.id && !used.has(a.id));
  }, [activities, predecessorRows, activity.id]);

  const typeLabel = (type: RelationshipType): string =>
    ({
      FS: t('schedule.dep_fs', { defaultValue: 'Finish to Start (FS)' }),
      SS: t('schedule.dep_ss', { defaultValue: 'Start to Start (SS)' }),
      FF: t('schedule.dep_ff', { defaultValue: 'Finish to Finish (FF)' }),
      SF: t('schedule.dep_sf', { defaultValue: 'Start to Finish (SF)' }),
    })[type];

  const afterChange = async () => {
    // Recompute dates from the new network, then refetch the edges + bars.
    await scheduleApi.reschedule(scheduleId);
    await queryClient.invalidateQueries({ queryKey: relationshipsKey });
    await queryClient.invalidateQueries({ queryKey: ['gantt', scheduleId] });
  };

  const onError = (error: Error) =>
    addToast({
      type: 'error',
      title: t('toasts.error', { defaultValue: 'Error' }),
      message: error.message,
    });

  const addMutation = useMutation({
    mutationFn: () =>
      scheduleApi.createRelationship(scheduleId, {
        predecessor_id: newPredId,
        successor_id: activity.id,
        relationship_type: newType,
        lag_days: Number.parseInt(newLag, 10) || 0,
      }),
    onSuccess: async () => {
      setNewPredId('');
      setNewType('FS');
      setNewLag('0');
      await afterChange();
      addToast({
        type: 'success',
        title: t('schedule.dep_added', { defaultValue: 'Dependency added' }),
      });
    },
    onError,
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, body }: { id: string; body: RelationshipUpdateBody }) =>
      scheduleApi.updateRelationship(id, body),
    onSuccess: afterChange,
    onError,
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => scheduleApi.deleteRelationship(id),
    onSuccess: async () => {
      await afterChange();
      addToast({
        type: 'success',
        title: t('schedule.dep_removed', {
          defaultValue: 'Dependency removed',
        }),
      });
    },
    onError,
  });

  const busy = addMutation.isPending || updateMutation.isPending || deleteMutation.isPending;

  return (
    <div data-testid="dependency-editor" className="space-y-3">
      <div className="flex items-center gap-2 text-sm font-medium text-content-primary">
        <GitBranch size={15} className="text-oe-blue" />
        {t('schedule.predecessors', { defaultValue: 'Predecessors' })}
      </div>

      {isLoading ? (
        <p className="text-sm text-content-tertiary">
          {t('common.loading', { defaultValue: 'Loading...' })}
        </p>
      ) : predecessorRows.length === 0 ? (
        <p className="text-sm text-content-tertiary">
          {t('schedule.no_predecessors', {
            defaultValue: 'No predecessors yet. Add one below to drive this task from another.',
          })}
        </p>
      ) : (
        <ul className="space-y-2">
          {predecessorRows.map((r) => (
            <li
              key={r.id}
              data-testid={`dep-row-${r.id}`}
              className="flex flex-wrap items-center gap-2 rounded-lg border border-border-light bg-surface-secondary/40 p-2"
            >
              <span
                className="min-w-0 flex-1 truncate text-sm text-content-primary"
                title={nameById.get(r.predecessor_id) ?? r.predecessor_id}
              >
                {nameById.get(r.predecessor_id) ??
                  t('schedule.unknown_activity', {
                    defaultValue: 'Unknown activity',
                  })}
              </span>
              <select
                aria-label={t('schedule.dep_type', {
                  defaultValue: 'Dependency type',
                })}
                data-testid={`dep-type-${r.id}`}
                className={SELECT_CLS}
                value={r.relationship_type}
                disabled={busy}
                onChange={(e) =>
                  updateMutation.mutate({
                    id: r.id,
                    body: {
                      relationship_type: e.target.value as RelationshipType,
                    },
                  })
                }
              >
                {REL_TYPES.map((tp) => (
                  <option key={tp} value={tp}>
                    {tp}
                  </option>
                ))}
              </select>
              <label className="flex items-center gap-1 text-xs text-content-secondary">
                {t('schedule.lag_days', { defaultValue: 'Lag (days)' })}
                <input
                  type="number"
                  aria-label={t('schedule.lag_days', {
                    defaultValue: 'Lag (days)',
                  })}
                  data-testid={`dep-lag-${r.id}`}
                  className={`w-20 ${SELECT_CLS}`}
                  defaultValue={r.lag_days}
                  disabled={busy}
                  onBlur={(e) => {
                    const n = e.target.valueAsNumber;
                    if (Number.isNaN(n) || n === r.lag_days) return;
                    updateMutation.mutate({ id: r.id, body: { lag_days: n } });
                  }}
                />
              </label>
              <button
                type="button"
                aria-label={t('common.remove', { defaultValue: 'Remove' })}
                data-testid={`dep-remove-${r.id}`}
                disabled={busy}
                onClick={() => deleteMutation.mutate(r.id)}
                className="flex h-8 w-8 items-center justify-center rounded-lg text-content-tertiary transition-colors hover:bg-semantic-error-bg hover:text-semantic-error disabled:opacity-50"
              >
                <Trash2 size={15} />
              </button>
            </li>
          ))}
        </ul>
      )}

      {/* ── Add predecessor row ─────────────────────────────────────────── */}
      <div className="flex flex-wrap items-end gap-2 rounded-lg border border-dashed border-border-light p-2">
        <label className="flex min-w-[10rem] flex-1 flex-col gap-1 text-xs text-content-secondary">
          {t('schedule.predecessor', { defaultValue: 'Predecessor' })}
          <select
            aria-label={t('schedule.predecessor', {
              defaultValue: 'Predecessor',
            })}
            data-testid="dep-add-predecessor"
            className={SELECT_CLS}
            value={newPredId}
            disabled={busy || candidates.length === 0}
            onChange={(e) => setNewPredId(e.target.value)}
          >
            <option value="">
              {t('schedule.select_activity', {
                defaultValue: 'Select activity...',
              })}
            </option>
            {candidates.map((a) => (
              <option key={a.id} value={a.id}>
                {a.name}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-xs text-content-secondary">
          {t('schedule.dep_type', { defaultValue: 'Type' })}
          <select
            aria-label={t('schedule.dep_add_type', {
              defaultValue: 'New dependency type',
            })}
            data-testid="dep-add-type"
            className={SELECT_CLS}
            value={newType}
            disabled={busy}
            onChange={(e) => setNewType(e.target.value as RelationshipType)}
            title={typeLabel(newType)}
          >
            {REL_TYPES.map((tp) => (
              <option key={tp} value={tp}>
                {tp}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-xs text-content-secondary">
          {t('schedule.lag_days', { defaultValue: 'Lag (days)' })}
          <input
            type="number"
            aria-label={t('schedule.dep_add_lag', {
              defaultValue: 'New dependency lag in days',
            })}
            data-testid="dep-add-lag"
            className={`w-20 ${SELECT_CLS}`}
            value={newLag}
            disabled={busy}
            onChange={(e) => setNewLag(e.target.value)}
          />
        </label>
        <Button
          variant="secondary"
          size="sm"
          icon={<Plus size={15} />}
          data-testid="dep-add-submit"
          disabled={busy || !newPredId}
          loading={addMutation.isPending}
          onClick={() => addMutation.mutate()}
        >
          {t('schedule.add_predecessor', { defaultValue: 'Add predecessor' })}
        </Button>
      </div>
    </div>
  );
}
