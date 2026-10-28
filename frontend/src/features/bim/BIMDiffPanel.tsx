// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * BIMDiffPanel — model-version diff review UI.
 *
 * Read-only consumer of the backend's per-element diff (`bim_hub`
 * `compute_diff`): the user picks an older model version to compare the
 * active model against, the panel fetches the diff, colours the scene by
 * change type (via the parent's `onDiffChange` → BIMViewer overlay) and
 * lists the changes grouped by category/trade with the per-element field
 * deltas. Clicking a present element (added / modified) selects + frames it
 * in the 3D scene. Deleted elements don't exist in the active model so they
 * are listed for the record but not selectable.
 *
 * No diff math happens here — `groupModelDiff` is a pure transform over the
 * exact API payload and the backend logic is untouched.
 */
import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import {
  GitCompare,
  Plus,
  Minus,
  PencilRuler,
  ChevronDown,
  ChevronRight,
  Loader2,
  X,
} from 'lucide-react';
import type { BIMElementData, BIMModelData } from '@/shared/ui/BIMViewer';
import { computeBIMModelDiff } from './api';
import {
  groupModelDiff,
  type DiffChangeType,
  type DiffElementRow,
} from './diffGrouping';

interface BIMDiffPanelProps {
  /** The active (newer) model being viewed. */
  activeModelId: string;
  /** All ready models in the project — diff candidates (excludes active). */
  models: BIMModelData[];
  /** Elements currently loaded for the active model — used to resolve a
   *  diff `stable_id` to a viewer element id for selection. */
  elements: BIMElementData[];
  /** Push the change-by-stable-id map up so the BIMViewer colours the scene
   *  (null clears the overlay). */
  onDiffChange: (
    map: Map<string, DiffChangeType> | null,
  ) => void;
  /** Select + frame an element in the 3D scene by its viewer id. */
  onSelectElement: (elementId: string) => void;
  onClose: () => void;
}

const TYPE_META: Record<
  DiffChangeType,
  { icon: typeof Plus; cls: string; key: string; fallback: string }
> = {
  added: {
    icon: Plus,
    cls: 'text-emerald-600 dark:text-emerald-400',
    key: 'bim.diff_added',
    fallback: 'Added',
  },
  deleted: {
    icon: Minus,
    cls: 'text-rose-600 dark:text-rose-400',
    key: 'bim.diff_deleted',
    fallback: 'Deleted',
  },
  modified: {
    icon: PencilRuler,
    cls: 'text-amber-600 dark:text-amber-400',
    key: 'bim.diff_modified',
    fallback: 'Modified',
  },
};

export default function BIMDiffPanel({
  activeModelId,
  models,
  elements,
  onDiffChange,
  onSelectElement,
  onClose,
}: BIMDiffPanelProps) {
  const { t } = useTranslation();
  const [oldModelId, setOldModelId] = useState<string>('');
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  const candidates = useMemo(
    () =>
      models.filter(
        (m) => m.id !== activeModelId && m.status === 'ready',
      ),
    [models, activeModelId],
  );

  const diffQuery = useQuery({
    queryKey: ['bim-model-diff', activeModelId, oldModelId],
    queryFn: () => computeBIMModelDiff(activeModelId, oldModelId),
    enabled: !!oldModelId,
  });

  const grouped = useMemo(
    () => (diffQuery.data ? groupModelDiff(diffQuery.data) : null),
    [diffQuery.data],
  );

  // Map stable_id → viewer element id for selection on row click.
  const elementByStableId = useMemo(() => {
    const m = new Map<string, string>();
    for (const el of elements) {
      if (el.stable_id) m.set(el.stable_id, el.id);
    }
    return m;
  }, [elements]);

  // Drive the scene colour overlay whenever the grouped diff changes; clear
  // it when the panel unmounts or the comparison is cleared.
  useEffect(() => {
    onDiffChange(grouped ? grouped.changeByStableId : null);
    return () => onDiffChange(null);
  }, [grouped, onDiffChange]);

  const toggleGroup = (category: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(category)) next.delete(category);
      else next.add(category);
      return next;
    });
  };

  const handleRowClick = (row: DiffElementRow) => {
    if (row.changeType === 'deleted') return;
    const elId = elementByStableId.get(row.stableId);
    if (elId) onSelectElement(elId);
  };

  return (
    <div className="flex flex-col h-full" data-testid="bim-diff-panel">
      <div className="flex items-center justify-between px-3 py-2 border-b border-border-light bg-surface-secondary">
        <h3 className="inline-flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-content-primary">
          <GitCompare size={13} className="text-oe-blue" />
          {t('bim.diff_title', { defaultValue: 'Compare versions' })}
        </h3>
        <button
          type="button"
          onClick={onClose}
          aria-label={t('common.close', { defaultValue: 'Close' })}
          className="flex h-6 w-6 items-center justify-center rounded text-content-tertiary hover:bg-surface-tertiary"
        >
          <X size={14} />
        </button>
      </div>

      <div className="px-3 py-2 border-b border-border-light">
        <label
          htmlFor="bim-diff-old-model"
          className="block text-[10px] font-semibold uppercase tracking-wider text-content-tertiary mb-1"
        >
          {t('bim.diff_compare_against', {
            defaultValue: 'Compare against (older version)',
          })}
        </label>
        <select
          id="bim-diff-old-model"
          value={oldModelId}
          onChange={(e) => setOldModelId(e.target.value)}
          disabled={candidates.length === 0}
          data-testid="bim-diff-old-model"
          className="w-full px-2 py-1 text-xs rounded border border-border-light bg-surface-primary focus:outline-none focus:ring-1 focus:ring-oe-blue"
        >
          <option value="">
            {candidates.length === 0
              ? t('bim.diff_no_candidates', {
                  defaultValue: 'No other model versions in this project',
                })
              : t('bim.diff_pick_model', {
                  defaultValue: 'Select a model to compare…',
                })}
          </option>
          {candidates.map((m) => (
            <option key={m.id} value={m.id}>
              {m.name}
            </option>
          ))}
        </select>
      </div>

      <div className="flex-1 min-h-0 overflow-y-auto">
        {!oldModelId ? (
          <p className="px-3 py-4 text-[11px] text-content-tertiary italic">
            {t('bim.diff_prompt', {
              defaultValue:
                'Pick an older version above to see what changed. Added elements turn green, modified amber, deleted red.',
            })}
          </p>
        ) : diffQuery.isLoading ? (
          <div className="flex items-center gap-2 px-3 py-4 text-[11px] text-content-tertiary">
            <Loader2 size={13} className="animate-spin text-oe-blue" />
            {t('bim.diff_loading', { defaultValue: 'Computing diff…' })}
          </div>
        ) : diffQuery.error ? (
          <p
            className="px-3 py-4 text-[11px] text-rose-600"
            data-testid="bim-diff-error"
          >
            {t('bim.diff_error', {
              defaultValue: 'Could not compute the diff for these models.',
            })}
          </p>
        ) : grouped ? (
          <>
            {/* Summary strip */}
            <div className="flex items-center gap-3 px-3 py-2 border-b border-border-light text-[11px]">
              <span className="inline-flex items-center gap-1 text-emerald-600 dark:text-emerald-400">
                <Plus size={11} />
                {grouped.totals.added}
              </span>
              <span className="inline-flex items-center gap-1 text-amber-600 dark:text-amber-400">
                <PencilRuler size={11} />
                {grouped.totals.modified}
              </span>
              <span className="inline-flex items-center gap-1 text-rose-600 dark:text-rose-400">
                <Minus size={11} />
                {grouped.totals.deleted}
              </span>
            </div>

            {grouped.groups.length === 0 ? (
              <p className="px-3 py-4 text-[11px] text-content-tertiary italic">
                {t('bim.diff_no_changes', {
                  defaultValue:
                    'No element-level changes between these versions.',
                })}
              </p>
            ) : (
              <ul className="divide-y divide-border-light">
                {grouped.groups.map((g) => {
                  const isOpen = expanded.has(g.category);
                  return (
                    <li key={g.category}>
                      <button
                        type="button"
                        onClick={() => toggleGroup(g.category)}
                        aria-expanded={isOpen}
                        data-testid={`diff-group-${g.category}`}
                        className="w-full flex items-center gap-2 px-3 py-2 text-left hover:bg-surface-secondary transition-colors"
                      >
                        {isOpen ? (
                          <ChevronDown size={13} className="shrink-0 text-content-tertiary" />
                        ) : (
                          <ChevronRight size={13} className="shrink-0 text-content-tertiary" />
                        )}
                        <span className="flex-1 min-w-0 truncate text-[11px] font-medium text-content-primary">
                          {g.category}
                        </span>
                        <span className="flex items-center gap-1.5 text-[10px] tabular-nums shrink-0">
                          {g.added > 0 && (
                            <span className="text-emerald-600 dark:text-emerald-400">
                              +{g.added}
                            </span>
                          )}
                          {g.modified > 0 && (
                            <span className="text-amber-600 dark:text-amber-400">
                              ~{g.modified}
                            </span>
                          )}
                          {g.deleted > 0 && (
                            <span className="text-rose-600 dark:text-rose-400">
                              −{g.deleted}
                            </span>
                          )}
                        </span>
                      </button>
                      {isOpen && (
                        <ul className="bg-surface-secondary/40">
                          {g.rows.map((row) => {
                            const meta = TYPE_META[row.changeType];
                            const Icon = meta.icon;
                            const selectable =
                              row.changeType !== 'deleted' &&
                              elementByStableId.has(row.stableId);
                            return (
                              <li
                                key={`${row.stableId}-${row.changeType}`}
                                className="px-3 py-1.5 border-t border-border-light/60"
                              >
                                <button
                                  type="button"
                                  onClick={() => handleRowClick(row)}
                                  disabled={!selectable}
                                  data-testid="diff-element-row"
                                  className={`w-full flex items-start gap-1.5 text-left ${
                                    selectable
                                      ? 'hover:text-oe-blue cursor-pointer'
                                      : 'cursor-default'
                                  }`}
                                >
                                  <Icon
                                    size={11}
                                    className={`mt-0.5 shrink-0 ${meta.cls}`}
                                  />
                                  <span className="flex-1 min-w-0">
                                    <span className="block truncate text-[11px] text-content-primary">
                                      {row.name ?? row.stableId}
                                    </span>
                                    <span className="text-[9px] uppercase tracking-wider text-content-tertiary">
                                      {t(meta.key, { defaultValue: meta.fallback })}
                                    </span>
                                  </span>
                                </button>
                                {row.fieldDeltas.length > 0 && (
                                  <dl className="mt-1 ml-4 grid grid-cols-[auto_1fr] gap-x-2 gap-y-0.5">
                                    {row.fieldDeltas.map((d) => (
                                      <div key={d.field} className="contents">
                                        <dt
                                          className="text-[10px] text-content-tertiary truncate"
                                          title={d.field}
                                        >
                                          {d.field}
                                        </dt>
                                        <dd className="text-[10px] text-content-secondary min-w-0">
                                          <span
                                            className="line-through text-rose-500/80 break-words"
                                            title={d.oldText}
                                          >
                                            {d.oldText}
                                          </span>
                                          {' → '}
                                          <span
                                            className="text-emerald-600 dark:text-emerald-400 break-words"
                                            title={d.newText}
                                          >
                                            {d.newText}
                                          </span>
                                        </dd>
                                      </div>
                                    ))}
                                  </dl>
                                )}
                              </li>
                            );
                          })}
                        </ul>
                      )}
                    </li>
                  );
                })}
              </ul>
            )}
          </>
        ) : null}
      </div>
    </div>
  );
}
