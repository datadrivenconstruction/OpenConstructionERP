// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The change list of a stored compare and what can be done with each change:
 * mark it relevant or not, comment, raise an RFI or a revision cloud, and flag
 * the takeoff quantities and BOQ positions inside it for re-measure (after a
 * dry run the user confirms).
 */

import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import clsx from 'clsx';
import { Check, Cloud, Eraser, FileQuestion, Loader2, Ruler, X } from 'lucide-react';

import { Badge, Button, EmptyState } from '@/shared/ui';
import { getErrorMessage } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import {
  drawingCompareApi,
  type ChangeKind,
  type ChangeStatus,
  type Comparison,
  type DrawingChange,
  type RemeasureResult,
} from '../api';

const KIND_VARIANT: Record<ChangeKind, 'blue' | 'error' | 'warning' | 'purple'> = {
  added: 'blue',
  removed: 'error',
  modified: 'warning',
  text: 'purple',
};

export type ChangeFilter = 'all' | ChangeStatus;

const FILTER_DEFAULTS: Record<ChangeFilter, string> = {
  all: 'All',
  open: 'Open',
  relevant: 'Relevant',
  not_relevant: 'Not relevant',
};

export function filterChanges(changes: DrawingChange[], filter: ChangeFilter): DrawingChange[] {
  return filter === 'all' ? changes : changes.filter((c) => c.status === filter);
}

interface ChangeListProps {
  comparison: Comparison;
  selectedId: string | null;
  onSelect: (id: string) => void;
  canWrite: boolean;
}

export function ChangeList({ comparison, selectedId, onSelect, canWrite }: ChangeListProps) {
  const { t } = useTranslation();
  const [filter, setFilter] = useState<ChangeFilter>('all');
  const [remeasureFor, setRemeasureFor] = useState<DrawingChange | null>(null);
  const shown = useMemo(() => filterChanges(comparison.changes, filter), [comparison.changes, filter]);
  const counts = useMemo(() => {
    const c = { all: comparison.changes.length, open: 0, relevant: 0, not_relevant: 0 };
    comparison.changes.forEach((ch) => {
      c[ch.status] += 1;
    });
    return c;
  }, [comparison.changes]);

  if (comparison.changes.length === 0) {
    return (
      <EmptyState
        icon={<Check size={22} />}
        title={t('drawing_compare.no_changes_title', { defaultValue: 'No changes found' })}
        description={t('drawing_compare.no_changes_desc', {
          defaultValue: 'The two revisions match within the tolerance. Lower the tolerance to look closer.',
        })}
      />
    );
  }

  const filters: ChangeFilter[] = ['all', 'open', 'relevant', 'not_relevant'];
  return (
    <div className="flex flex-col gap-2" data-testid="drawing-compare-change-list">
      <div className="flex flex-wrap gap-1" role="tablist">
        {filters.map((f) => (
          <button
            key={f}
            type="button"
            role="tab"
            aria-selected={filter === f}
            onClick={() => setFilter(f)}
            className={clsx(
              'rounded-full border px-2.5 py-0.5 text-xs',
              filter === f ? 'border-oe-blue bg-oe-blue/10 text-oe-blue' : 'border-border text-content-secondary',
            )}
          >
            {t(`drawing_compare.filter_${f}`, { defaultValue: FILTER_DEFAULTS[f] })} ({counts[f]})
          </button>
        ))}
      </div>
      <ul className="flex max-h-[70vh] flex-col gap-2 overflow-y-auto pr-1">
        {shown.map((ch) => (
          <ChangeRow
            key={ch.id}
            change={ch}
            comparison={comparison}
            selected={ch.id === selectedId}
            onSelect={() => onSelect(ch.id)}
            canWrite={canWrite}
            onRemeasure={() => setRemeasureFor(ch)}
          />
        ))}
      </ul>
      {remeasureFor && (
        <RemeasureDialog change={remeasureFor} comparisonId={comparison.id} onClose={() => setRemeasureFor(null)} />
      )}
    </div>
  );
}

function useChangeMutation(comparisonId: string) {
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const { t } = useTranslation();
  return {
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['drawing-compare', 'comparison', comparisonId] });
      void qc.invalidateQueries({ queryKey: ['drawing-compare', 'validation', comparisonId] });
    },
    onError: (err: unknown) =>
      addToast({
        type: 'error',
        title: t('drawing_compare.action_failed', { defaultValue: 'The action did not go through' }),
        message: getErrorMessage(err),
      }),
  };
}

interface ChangeRowProps {
  change: DrawingChange;
  comparison: Comparison;
  selected: boolean;
  onSelect: () => void;
  canWrite: boolean;
  onRemeasure: () => void;
}

function ChangeRow({ change, comparison, selected, onSelect, canWrite, onRemeasure }: ChangeRowProps) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const handlers = useChangeMutation(comparison.id);
  const [comment, setComment] = useState(change.comment ?? '');
  useEffect(() => setComment(change.comment ?? ''), [change.comment]);

  const update = useMutation({
    mutationFn: (body: { status?: ChangeStatus; comment?: string | null }) => drawingCompareApi.updateChange(change.id, body),
    ...handlers,
  });
  const rfi = useMutation({
    mutationFn: () => drawingCompareApi.createRfi(change.id),
    ...handlers,
    onSuccess: (res) => {
      handlers.onSuccess();
      addToast({
        type: 'success',
        title: t('drawing_compare.rfi_created', { defaultValue: 'RFI {{number}} raised as a draft', number: res.label }),
      });
    },
  });
  const markup = useMutation({
    mutationFn: () => drawingCompareApi.createMarkup(change.id),
    ...handlers,
    onSuccess: () => {
      handlers.onSuccess();
      addToast({ type: 'success', title: t('drawing_compare.markup_created', { defaultValue: 'Revision cloud added to the newer revision' }) });
    },
  });
  const clear = useMutation({ mutationFn: () => drawingCompareApi.clearRemeasure(change.id), ...handlers });

  const kindLabel = t(`drawing_compare.kind_${change.kind}`, { defaultValue: change.kind });
  const location =
    comparison.source_kind === 'pdf'
      ? t('drawing_compare.on_page', { defaultValue: 'Page {{page}}', page: change.page ?? comparison.new_page ?? 1 })
      : change.layer
        ? t('drawing_compare.on_layer', { defaultValue: 'Layer {{layer}}', layer: change.layer })
        : '';
  const flaggedCount = change.flagged_measurement_ids.length + change.flagged_annotation_ids.length;

  return (
    <li
      className={clsx(
        'rounded-lg border bg-surface-primary p-2 text-sm transition',
        selected ? 'border-oe-blue ring-2 ring-oe-blue/30' : 'border-border',
      )}
      data-testid={`drawing-compare-change-${change.seq}`}
    >
      <div className="flex gap-2">
        <button type="button" onClick={onSelect} className="shrink-0" aria-label={t('drawing_compare.show_change', { defaultValue: 'Show change {{seq}}', seq: change.seq })}>
          {change.thumbnail ? (
            <img src={change.thumbnail} alt="" className="h-16 w-24 rounded border border-border object-contain bg-white" />
          ) : (
            <span className="flex h-16 w-24 items-center justify-center rounded border border-dashed border-border text-xs text-content-tertiary">
              #{change.seq}
            </span>
          )}
        </button>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="font-semibold">#{change.seq}</span>
            <Badge variant={KIND_VARIANT[change.kind]} size="sm">{kindLabel}</Badge>
            {location && <span className="text-xs text-content-secondary">{location}</span>}
            {change.status !== 'open' && (
              <Badge variant={change.status === 'relevant' ? 'success' : 'neutral'} size="sm">
                {t(`drawing_compare.status_${change.status}`, { defaultValue: change.status })}
              </Badge>
            )}
          </div>
          {(change.old_text || change.new_text) && (
            <p className="mt-0.5 truncate text-xs">
              <span className="text-red-600 line-through">{change.old_text}</span>
              {change.old_text && change.new_text ? ' ' : ''}
              <span className="text-blue-600">{change.new_text}</span>
            </p>
          )}
          <div className="mt-1 flex flex-wrap gap-1 text-xs">
            {change.rfi_id && (
              <a className="text-oe-blue underline" href={`/rfi/${change.rfi_id}`}>
                {t('drawing_compare.open_rfi', { defaultValue: 'Open RFI' })}
              </a>
            )}
            {change.markup_id && (
              <span className="text-content-secondary">{t('drawing_compare.has_markup', { defaultValue: 'Clouded' })}</span>
            )}
            {change.flagged_at && (
              <span className="text-amber-700">
                {t('drawing_compare.flagged_summary', {
                  defaultValue: '{{items}} quantities and {{positions}} BOQ positions flagged for re-measure',
                  items: flaggedCount,
                  positions: change.flagged_position_ids.length,
                })}
              </span>
            )}
          </div>
        </div>
      </div>
      {canWrite && (
        <div className="mt-2 flex flex-col gap-1.5">
          <div className="flex flex-wrap gap-1">
            <Button
              size="sm"
              variant={change.status === 'relevant' ? 'primary' : 'secondary'}
              onClick={() => update.mutate({ status: 'relevant' })}
              icon={<Check size={13} />}
            >
              {t('drawing_compare.mark_relevant', { defaultValue: 'Relevant' })}
            </Button>
            <Button
              size="sm"
              variant={change.status === 'not_relevant' ? 'primary' : 'secondary'}
              onClick={() => update.mutate({ status: 'not_relevant' })}
              icon={<X size={13} />}
            >
              {t('drawing_compare.mark_not_relevant', { defaultValue: 'Not relevant' })}
            </Button>
            <Button size="sm" variant="ghost" disabled={!!change.rfi_id || rfi.isPending} onClick={() => rfi.mutate()} icon={rfi.isPending ? <Loader2 size={13} className="animate-spin" /> : <FileQuestion size={13} />}>
              {t('drawing_compare.raise_rfi', { defaultValue: 'RFI' })}
            </Button>
            <Button size="sm" variant="ghost" disabled={!!change.markup_id || markup.isPending} onClick={() => markup.mutate()} icon={<Cloud size={13} />}>
              {t('drawing_compare.add_cloud', { defaultValue: 'Cloud' })}
            </Button>
            {change.flagged_at ? (
              <Button size="sm" variant="ghost" onClick={() => clear.mutate()} icon={<Eraser size={13} />}>
                {t('drawing_compare.clear_flags', { defaultValue: 'Re-measured' })}
              </Button>
            ) : (
              <Button size="sm" variant="ghost" onClick={onRemeasure} icon={<Ruler size={13} />}>
                {t('drawing_compare.remeasure', { defaultValue: 'Re-measure' })}
              </Button>
            )}
          </div>
          <textarea
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            onBlur={() => {
              if ((change.comment ?? '') !== comment) update.mutate({ comment });
            }}
            rows={1}
            maxLength={5000}
            placeholder={t('drawing_compare.comment_placeholder', { defaultValue: 'Comment for the team' })}
            className="w-full resize-y rounded-md border border-border bg-surface-primary px-2 py-1 text-xs"
          />
        </div>
      )}
      {!canWrite && change.comment && <p className="mt-1 text-xs text-content-secondary">{change.comment}</p>}
    </li>
  );
}

interface RemeasureDialogProps {
  change: DrawingChange;
  comparisonId: string;
  onClose: () => void;
}

export function RemeasureDialog({ change, comparisonId, onClose }: RemeasureDialogProps) {
  const { t } = useTranslation();
  const handlers = useChangeMutation(comparisonId);
  const [preview, setPreview] = useState<RemeasureResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    drawingCompareApi
      .remeasure(change.id, true)
      .then((r) => alive && setPreview(r))
      .catch((e) => alive && setError(getErrorMessage(e)));
    return () => {
      alive = false;
    };
  }, [change.id]);

  const confirm = useMutation({
    mutationFn: () => drawingCompareApi.remeasure(change.id, false),
    ...handlers,
    onSuccess: () => {
      handlers.onSuccess();
      onClose();
    },
  });

  const empty = preview && preview.items.length === 0;
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="dc-remeasure-title"
      onKeyDown={(e) => e.key === 'Escape' && onClose()}
    >
      <div className="w-full max-w-lg rounded-xl bg-surface-primary p-4 shadow-xl">
        <h2 id="dc-remeasure-title" className="text-base font-semibold">
          {t('drawing_compare.remeasure_title', { defaultValue: 'Flag quantities in change {{seq}} for re-measure', seq: change.seq })}
        </h2>
        <p className="mt-1 text-sm text-content-secondary">
          {t('drawing_compare.remeasure_intro', {
            defaultValue:
              'These takeoff measurements and markups sit inside the changed area. Confirm to flag them and the BOQ positions they feed.',
          })}
        </p>
        <div className="mt-3 max-h-72 overflow-y-auto text-sm">
          {!preview && !error && <Loader2 className="animate-spin" size={18} />}
          {error && <p className="text-red-600">{error}</p>}
          {empty && <p className="text-content-secondary">{t('drawing_compare.remeasure_none', { defaultValue: 'Nothing measured inside this change.' })}</p>}
          {preview && preview.items.length > 0 && (
            <ul className="space-y-1">
              {preview.items.map((i) => (
                <li key={i.id} className="flex items-center justify-between gap-2 rounded border border-border px-2 py-1">
                  <span className="truncate">{i.label || t(`drawing_compare.source_${i.source}`, { defaultValue: i.source })}</span>
                  <Badge variant={i.revision === 'new' ? 'blue' : 'error'} size="sm">
                    {i.revision === 'new'
                      ? t('drawing_compare.on_new', { defaultValue: 'newer revision' })
                      : t('drawing_compare.on_old', { defaultValue: 'older revision' })}
                  </Badge>
                </li>
              ))}
            </ul>
          )}
          {preview && preview.positions.length > 0 && (
            <>
              <h3 className="mt-3 text-xs font-semibold uppercase text-content-tertiary">
                {t('drawing_compare.remeasure_positions', { defaultValue: 'BOQ positions' })}
              </h3>
              <ul className="mt-1 space-y-1">
                {preview.positions.map((p) => (
                  <li key={p.id} className="truncate">
                    <span className="font-mono text-xs">{p.ordinal}</span> {p.description}
                  </li>
                ))}
              </ul>
            </>
          )}
        </div>
        <div className="mt-4 flex justify-end gap-2">
          <Button variant="secondary" onClick={onClose}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button
            variant="primary"
            disabled={!preview || empty || confirm.isPending}
            onClick={() => confirm.mutate()}
            data-testid="drawing-compare-remeasure-confirm"
          >
            {t('drawing_compare.remeasure_confirm', { defaultValue: 'Flag for re-measure' })}
          </Button>
        </div>
      </div>
    </div>
  );
}
