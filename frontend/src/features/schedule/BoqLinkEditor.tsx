// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Link2, Plus, Trash2 } from 'lucide-react';
import { Button } from '@/shared/ui';
import { useToastStore } from '@/stores/useToastStore';
import { scheduleApi, type Activity, type BoqPositionLite } from './api';

const SELECT_CLS =
  'rounded-md border border-border-light bg-surface-primary px-2 py-1.5 text-sm text-content-primary';

/** Enough rows to find a position by eye; the search narrows the rest. */
const MAX_OPTIONS = 200;

function positionLabel(p: BoqPositionLite): string {
  return p.ordinal ? `${p.ordinal}  ${p.description}` : p.description;
}

/**
 * One linked position. Its label comes from the BOQ open in the picker when it
 * is there, and is fetched by id otherwise, so a link made from another BOQ
 * still reads as a position rather than as a bare id.
 */
function LinkedPositionRow({
  positionId,
  known,
  busy,
  onRemove,
}: {
  positionId: string;
  known: BoqPositionLite | undefined;
  busy: boolean;
  onRemove: () => void;
}) {
  const { t } = useTranslation();
  const { data: fetched, isError } = useQuery({
    queryKey: ['boq-position', positionId],
    queryFn: () => scheduleApi.getBoqPosition(positionId),
    enabled: !known,
    retry: false,
  });
  const position = known ?? fetched;
  const label = position
    ? positionLabel(position)
    : isError
      ? t('schedule.boq_links_unknown', { defaultValue: 'Position not found' })
      : t('common.loading', { defaultValue: 'Loading...' });

  return (
    <li
      data-testid={`boq-link-row-${positionId}`}
      className="flex items-center gap-2 rounded-lg border border-border-light bg-surface-secondary/40 p-2"
    >
      <span className="min-w-0 flex-1 truncate text-sm text-content-primary" title={label}>
        {label}
      </span>
      {position?.unit && (
        <span className="shrink-0 text-xs text-content-tertiary">
          {String(position.quantity)} {position.unit}
        </span>
      )}
      <button
        type="button"
        aria-label={t('common.remove', { defaultValue: 'Remove' })}
        data-testid={`boq-link-remove-${positionId}`}
        disabled={busy}
        onClick={onRemove}
        className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-content-tertiary transition-colors hover:bg-semantic-error-bg hover:text-semantic-error disabled:opacity-50"
      >
        <Trash2 size={15} />
      </button>
    </li>
  );
}

/**
 * BOQ position links for a single activity.
 *
 * Generated activities carry the positions they came from; an activity the
 * planner adds by hand starts with none. This lists the links, and lets the
 * planner pick a BOQ of the project, search its positions and link one, or
 * remove a link. The server checks that a position belongs to the schedule's
 * project, so this list is a convenience, not the guard. Section headers are
 * left out of the choice: a section is the sum of its positions, and linking
 * both would count the work twice.
 */
export function BoqLinkEditor({
  scheduleId,
  projectId,
  activity,
}: {
  scheduleId: string;
  projectId: string;
  activity: Activity;
}) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);

  const [pickedBoqId, setPickedBoqId] = useState('');
  const [search, setSearch] = useState('');
  const [newPositionId, setNewPositionId] = useState('');

  const linkedIds = activity.boq_position_ids ?? [];

  const { data: boqs = [], isLoading: boqsLoading } = useQuery({
    queryKey: ['boqs', projectId],
    queryFn: () => scheduleApi.listProjectBoqs(projectId),
    enabled: !!projectId,
  });
  const boqId = pickedBoqId || boqs[0]?.id || '';

  const { data: positions = [], isLoading: positionsLoading } = useQuery({
    queryKey: ['boq-positions-lite', boqId],
    queryFn: () => scheduleApi.getBoqPositions(boqId),
    enabled: !!boqId,
  });

  const byId = useMemo(() => new Map(positions.map((p) => [p.id, p] as const)), [positions]);

  const candidates = useMemo(() => {
    const parents = new Set(positions.map((p) => p.parent_id).filter(Boolean));
    const linked = new Set(linkedIds);
    const needle = search.trim().toLowerCase();
    return positions.filter(
      (p) =>
        !parents.has(p.id) &&
        !linked.has(p.id) &&
        (!needle || positionLabel(p).toLowerCase().includes(needle)),
    );
  }, [positions, linkedIds, search]);

  const afterChange = async () => {
    await queryClient.invalidateQueries({ queryKey: ['gantt', scheduleId] });
  };

  const onError = (error: Error) =>
    addToast({
      type: 'error',
      title: t('toasts.error', { defaultValue: 'Error' }),
      message: error.message,
    });

  const linkMutation = useMutation({
    mutationFn: (positionId: string) => scheduleApi.linkPosition(activity.id, positionId),
    onSuccess: async () => {
      setNewPositionId('');
      await afterChange();
      addToast({
        type: 'success',
        title: t('schedule.boq_links_added', { defaultValue: 'Position linked' }),
      });
    },
    onError,
  });

  const unlinkMutation = useMutation({
    mutationFn: (positionId: string) => scheduleApi.unlinkPosition(activity.id, positionId),
    onSuccess: async () => {
      await afterChange();
      addToast({
        type: 'success',
        title: t('schedule.boq_links_removed', { defaultValue: 'Position unlinked' }),
      });
    },
    onError,
  });

  const busy = linkMutation.isPending || unlinkMutation.isPending;

  return (
    <div data-testid="boq-link-editor" className="space-y-3">
      <div className="flex items-center gap-2 text-sm font-medium text-content-primary">
        <Link2 size={15} className="text-oe-blue" />
        {t('schedule.boq_links_title', { defaultValue: 'BOQ positions' })}
      </div>

      {linkedIds.length === 0 ? (
        <p className="text-sm text-content-tertiary">
          {t('schedule.boq_links_empty', {
            defaultValue: 'No BOQ positions linked yet. Link the positions this activity builds.',
          })}
        </p>
      ) : (
        <ul className="space-y-2">
          {linkedIds.map((id) => (
            <LinkedPositionRow
              key={id}
              positionId={id}
              known={byId.get(id)}
              busy={busy}
              onRemove={() => unlinkMutation.mutate(id)}
            />
          ))}
        </ul>
      )}

      {boqsLoading ? (
        <p className="text-sm text-content-tertiary">
          {t('common.loading', { defaultValue: 'Loading...' })}
        </p>
      ) : boqs.length === 0 ? (
        <p className="text-sm text-content-tertiary">
          {t('schedule.boq_links_no_boqs', { defaultValue: 'This project has no BOQ yet.' })}
        </p>
      ) : (
        <div className="flex flex-wrap items-end gap-2 rounded-lg border border-dashed border-border-light p-2">
          {boqs.length > 1 && (
            <label className="flex min-w-[8rem] flex-col gap-1 text-xs text-content-secondary">
              {t('schedule.boq_links_boq', { defaultValue: 'BOQ' })}
              <select
                data-testid="boq-link-boq"
                className={SELECT_CLS}
                value={boqId}
                disabled={busy}
                onChange={(e) => {
                  setPickedBoqId(e.target.value);
                  setNewPositionId('');
                }}
              >
                {boqs.map((b) => (
                  <option key={b.id} value={b.id}>
                    {b.name}
                  </option>
                ))}
              </select>
            </label>
          )}
          <label className="flex min-w-[8rem] flex-1 flex-col gap-1 text-xs text-content-secondary">
            {t('schedule.boq_links_search', { defaultValue: 'Search positions' })}
            <input
              type="search"
              data-testid="boq-link-search"
              className={SELECT_CLS}
              value={search}
              disabled={busy}
              onChange={(e) => {
                setSearch(e.target.value);
                setNewPositionId('');
              }}
            />
          </label>
          <label className="flex min-w-[10rem] flex-[2] flex-col gap-1 text-xs text-content-secondary">
            {t('schedule.boq_links_position', { defaultValue: 'Position' })}
            <select
              data-testid="boq-link-position"
              className={SELECT_CLS}
              value={newPositionId}
              disabled={busy || positionsLoading || candidates.length === 0}
              onChange={(e) => setNewPositionId(e.target.value)}
            >
              <option value="">
                {candidates.length === 0 && !positionsLoading
                  ? t('schedule.boq_links_no_match', { defaultValue: 'No positions match the search.' })
                  : t('schedule.boq_links_select', { defaultValue: 'Select position...' })}
              </option>
              {candidates.slice(0, MAX_OPTIONS).map((p) => (
                <option key={p.id} value={p.id}>
                  {positionLabel(p)}
                </option>
              ))}
            </select>
          </label>
          <Button
            variant="secondary"
            size="sm"
            icon={<Plus size={15} />}
            data-testid="boq-link-submit"
            disabled={busy || !newPositionId}
            loading={linkMutation.isPending}
            onClick={() => linkMutation.mutate(newPositionId)}
          >
            {t('schedule.boq_links_add', { defaultValue: 'Link position' })}
          </Button>
        </div>
      )}
    </div>
  );
}
