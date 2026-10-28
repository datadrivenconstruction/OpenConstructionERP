// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Stage-5 ("Grouping") panel for the /match-elements wizard.
//
// Splits the previously-read-only stage into three controls + a live
// preview, so the user can CHOOSE how their BIM elements roll up into
// estimable groups before the matcher runs:
//
//   A. Preset bar     — one-click common keys (IFC class, level+class,
//                       material…). Writes ``group_by`` and lets the
//                       backend's ``rebuild_groups`` regenerate the
//                       MatchGroup rows.
//   B. 3-slot picker  — ordered custom composite key. Driven by the
//                       attribute list the wizard prefetched.
//   C. Filter chips   — one toggleable chip per IfcCategory actually
//                       present in the data (count badge included).
//                       Toggling a chip narrows the grouping preview to
//                       the selected categories by writing the session's
//                       ``filters`` JSON ({"ifc_class": [...]}); the
//                       backend's ``rebuild_groups`` honours it. No chip
//                       selected = all categories included.
//   D. Count table    — live element count + sample names per group,
//                       with inline warnings when the chosen key is
//                       too granular or has high missingness.
//
// The component owns the picker state and debounces PATCH /sessions/{id}
// by 300 ms so a user spinning the slot dropdowns doesn't fire a request
// per keystroke; the resulting one PATCH triggers ``rebuild_groups``
// server-side and the cached groups query is invalidated.

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from '@tanstack/react-query';
import clsx from 'clsx';
import { AlertTriangle, Loader2, RefreshCw } from 'lucide-react';

import { Button } from '@/shared/ui/Button';
import { useToastStore } from '@/stores/useToastStore';

import {
  matchElementsApi,
  type AttributeKey,
  type CategoryCount,
  type GroupListResponse,
  type MatchSession,
} from './api';
import { ifcClassLabel } from './ifcClassLabels';
import { fmtList } from '@/shared/lib/formatters';

// Canonical attribute keys that are always offered even if the
// 200-row sample didn't surface them (e.g. an all-walls model that
// happens to share one IFC class but still has Levels and Materials).
// The bim_adapter already prepends these but the boq/text adapters
// don't, so the union here is the safest UI default.
const ALWAYS_AVAILABLE_KEYS = ['ifc_class', 'type_name', 'level', 'material', 'discipline'];

type PresetId =
  | 'ifc'
  | 'ifc_type'
  | 'level_ifc'
  | 'material'
  | 'level_ifc_material'
  | 'custom';

interface Preset {
  id: PresetId;
  i18nKey: string;
  label: string;
  groupBy: string[];
}

const PRESETS: readonly Preset[] = [
  {
    id: 'ifc',
    i18nKey: 'match.wizard.grouping.preset.ifc',
    label: 'By IFC class',
    groupBy: ['ifc_class'],
  },
  {
    id: 'ifc_type',
    i18nKey: 'match.wizard.grouping.preset.ifcType',
    label: 'By IFC class + Type',
    groupBy: ['ifc_class', 'type_name'],
  },
  {
    id: 'level_ifc',
    i18nKey: 'match.wizard.grouping.preset.levelIfc',
    label: 'By Level + IFC class',
    groupBy: ['level', 'ifc_class'],
  },
  {
    id: 'material',
    i18nKey: 'match.wizard.grouping.preset.material',
    label: 'By Material',
    groupBy: ['material'],
  },
  {
    id: 'level_ifc_material',
    i18nKey: 'match.wizard.grouping.preset.levelIfcMaterial',
    label: 'By Level + IFC class + Material',
    groupBy: ['level', 'ifc_class', 'material'],
  },
];

function arraysEqual(a: readonly string[], b: readonly string[]): boolean {
  if (a.length !== b.length) return false;
  for (let i = 0; i < a.length; i += 1) {
    if (a[i] !== b[i]) return false;
  }
  return true;
}

function presetForGroupBy(groupBy: readonly string[]): PresetId {
  for (const p of PRESETS) {
    if (arraysEqual(p.groupBy, groupBy)) return p.id;
  }
  return 'custom';
}

export interface GroupingPanelProps {
  sessionId: string;
  groupsQ: UseQueryResult<GroupListResponse, Error>;
  /**
   * The wizard's scope-knob session-update mutation. Surfaced here so the
   * panel can show a "syncing" badge while either mutation is in flight,
   * but the actual group_by PATCH happens through a local mutation
   * (different payload, debounced).
   */
  updateSessionM: UseMutationResult<MatchSession, Error, string>;
}

export function GroupingPanel({ sessionId, groupsQ, updateSessionM }: GroupingPanelProps) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);

  // ── Available attribute keys (prefetched in MatchWizardFlow). ─────────
  const attrsQ = useQuery({
    enabled: !!sessionId,
    queryKey: ['match-attributes', sessionId],
    queryFn: () => matchElementsApi.listAttributes(sessionId),
    staleTime: 60_000,
  });

  const attrs: AttributeKey[] = attrsQ.data ?? [];

  const availableKeys = useMemo(() => {
    const fromAttrs = attrs.map((a) => a.key);
    const merged = new Set<string>([...ALWAYS_AVAILABLE_KEYS, ...fromAttrs]);
    return Array.from(merged);
  }, [attrs]);

  // ── Available categories for the filter-chip row. ─────────────────────
  // Real counts straight from the source adapter (BIM: GROUP BY
  // element_type). Drives one toggle chip per IfcCategory present.
  const categoriesQ = useQuery({
    enabled: !!sessionId,
    queryKey: ['match-categories', sessionId],
    queryFn: () => matchElementsApi.listCategories(sessionId),
    staleTime: 60_000,
  });

  const categories: CategoryCount[] = categoriesQ.data ?? [];

  // ── Current session group_by, hydrated from the cached session. ───────
  // The session is the source of truth; we use the cached value if
  // present so the picker reflects the wizard's last write without an
  // extra round-trip.
  const sessionData = qc.getQueryData<MatchSession>(['match-session', sessionId]);
  const initialGroupBy = useMemo(() => {
    const fromSession = sessionData?.group_by;
    if (Array.isArray(fromSession) && fromSession.length > 0) return fromSession;
    // Fall back to the backend's default — ifc_class + type_name — so the
    // picker isn't visibly empty on first paint.
    return ['ifc_class', 'type_name'];
  }, [sessionData]);

  // Slot state: exactly three slots. Empty string = unset.
  const [slots, setSlots] = useState<[string, string, string]>(() => {
    const [s1 = '', s2 = '', s3 = ''] = initialGroupBy;
    return [s1, s2, s3];
  });

  // Rehydrate when the session's group_by changes from outside (e.g.
  // after a preset click invalidates and refetches the session). Only
  // overwrite if the new value really differs to avoid clobbering an
  // in-progress edit.
  useEffect(() => {
    const next: [string, string, string] = [
      initialGroupBy[0] ?? '',
      initialGroupBy[1] ?? '',
      initialGroupBy[2] ?? '',
    ];
    if (next[0] !== slots[0] || next[1] !== slots[1] || next[2] !== slots[2]) {
      setSlots(next);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialGroupBy.join('|')]);

  // ── Local mutation for group_by writes ────────────────────────────────
  // Separate from updateSessionM (which carries scope knobs) so the two
  // can't race each other and so the debounce can target only this
  // payload.
  const groupByM = useMutation({
    mutationFn: (groupBy: string[]) =>
      matchElementsApi.updateSession(sessionId, { group_by: groupBy }),
    onSuccess: (s: MatchSession) => {
      qc.setQueryData(['match-session', sessionId], s);
      qc.invalidateQueries({ queryKey: ['match-groups', sessionId] });
    },
    onError: (e: Error) =>
      addToast({
        type: 'error',
        title: t('match.wizard.grouping.updateFailed', {
          defaultValue: 'Could not update grouping',
        }),
        message: e.message,
      }),
  });

  // ── Category filter (session.filters["ifc_class"]). ───────────────────
  // The session is the source of truth — hydrate the active set from the
  // cached session's ``filters`` so a Back/Next round-trip keeps the
  // user's selection. Empty set = no filter = every category included.
  const initialFilterCats = useMemo(() => {
    const raw = sessionData?.filters?.ifc_class;
    if (!Array.isArray(raw)) return new Set<string>();
    return new Set<string>(raw.filter((v): v is string => typeof v === 'string'));
  }, [sessionData]);

  const [selectedCats, setSelectedCats] = useState<Set<string>>(initialFilterCats);

  // Rehydrate when the session's filters change from outside (e.g. after a
  // PATCH invalidates and the cache is replaced). Compare by sorted
  // contents so we don't clobber an in-progress toggle with an identical
  // server echo.
  const initialFilterKey = useMemo(
    () => Array.from(initialFilterCats).sort().join('|'),
    [initialFilterCats],
  );
  useEffect(() => {
    setSelectedCats((prev) => {
      const prevKey = Array.from(prev).sort().join('|');
      return prevKey === initialFilterKey ? prev : new Set(initialFilterCats);
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialFilterKey]);

  // Mutation for filter writes. Mirrors groupByM (same cache write +
  // group invalidation) so the preview re-groups server-side on toggle.
  const filtersM = useMutation({
    mutationFn: (filters: Record<string, unknown[]>) =>
      matchElementsApi.updateSession(sessionId, { filters }),
    onSuccess: (s: MatchSession) => {
      qc.setQueryData(['match-session', sessionId], s);
      qc.invalidateQueries({ queryKey: ['match-groups', sessionId] });
    },
    onError: (e: Error) =>
      addToast({
        type: 'error',
        title: t('match.wizard.grouping.updateFailed', {
          defaultValue: 'Could not update grouping',
        }),
        message: e.message,
      }),
  });

  const toggleCategory = useCallback(
    (category: string) => {
      setSelectedCats((prev) => {
        const next = new Set(prev);
        if (next.has(category)) {
          next.delete(category);
        } else {
          next.add(category);
        }
        // Empty set clears the filter entirely (show everything); a
        // non-empty set pins ``ifc_class`` to the chosen categories.
        const filters: Record<string, unknown[]> =
          next.size > 0 ? { ifc_class: Array.from(next) } : {};
        filtersM.mutate(filters);
        return next;
      });
    },
    [filtersM],
  );

  const clearCategoryFilter = useCallback(() => {
    setSelectedCats((prev) => {
      if (prev.size === 0) return prev;
      filtersM.mutate({});
      return new Set<string>();
    });
  }, [filtersM]);

  // ── Debounced PATCH ───────────────────────────────────────────────────
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const writeGroupBy = useCallback(
    (groupBy: string[]) => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
      debounceRef.current = setTimeout(() => {
        groupByM.mutate(groupBy);
      }, 300);
    },
    [groupByM],
  );

  useEffect(() => {
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, []);

  // ── Preset click handler. Immediate (no debounce). ────────────────────
  const applyPreset = useCallback(
    (preset: Preset) => {
      const next: [string, string, string] = [
        preset.groupBy[0] ?? '',
        preset.groupBy[1] ?? '',
        preset.groupBy[2] ?? '',
      ];
      setSlots(next);
      if (debounceRef.current) clearTimeout(debounceRef.current);
      groupByM.mutate(preset.groupBy);
    },
    [groupByM],
  );

  const updateSlot = useCallback(
    (idx: 0 | 1 | 2, value: string) => {
      const next: [string, string, string] = [...slots] as [string, string, string];
      next[idx] = value;
      // Clear any downstream slot whose parent just became empty so the
      // backend never gets a sparse key like ["", "level"].
      if (idx === 0 && !value) {
        next[1] = '';
        next[2] = '';
      } else if (idx === 1 && !value) {
        next[2] = '';
      }
      setSlots(next);
      const compact = next.filter(Boolean);
      // Don't PATCH an empty key — the backend would 422 and groups
      // would collapse to a single bucket. Show the picker as "Custom"
      // until the user fills slot 1.
      if (compact.length === 0) return;
      writeGroupBy(compact);
    },
    [slots, writeGroupBy],
  );

  const currentGroupBy = slots.filter(Boolean);
  const activePreset = presetForGroupBy(currentGroupBy);

  const groups = groupsQ.data?.groups ?? [];
  const totalElements = groups.reduce((a, g) => a + g.element_count, 0);

  // ── Inline validation heuristics ──────────────────────────────────────
  const tooGranular = groups.length > 0 && groups.length > totalElements * 0.5;
  const singletonGroups = groups.filter((g) => g.element_count === 1).length;
  const highMissingness =
    groups.length > 0 &&
    singletonGroups >= 1 &&
    singletonGroups / groups.length > 0.2;

  const isWriting = groupByM.isPending || filtersM.isPending;
  const isUpdatingScope = updateSessionM.isPending;

  return (
    <div className="space-y-5" data-testid="grouping-panel">
      <p className="text-sm text-content-secondary">
        {t('match.wizard.grouping.help', {
          defaultValue:
            'Group elements by the attribute(s) that define a priceable thing. Identical groups get one matched rate. Pick a preset, or build a custom 1–3 key composite below.',
        })}
      </p>

      {/* ── A. Preset bar ────────────────────────────────────────────── */}
      <div>
        <div className="mb-2 text-xs font-medium uppercase tracking-wide text-content-tertiary">
          {t('match.wizard.grouping.presets', { defaultValue: 'Common groupings' })}
        </div>
        <div className="flex flex-wrap gap-2">
          {PRESETS.map((preset) => {
            const active = activePreset === preset.id;
            return (
              <button
                key={preset.id}
                type="button"
                data-testid={`grouping-preset-${preset.id}`}
                onClick={() => applyPreset(preset)}
                disabled={isWriting}
                className={clsx(
                  'rounded-full border px-3 py-1.5 text-sm transition-colors',
                  active
                    ? 'border-oe-blue bg-oe-blue/10 text-oe-blue'
                    : 'border-border-light bg-surface-secondary text-content-primary hover:bg-surface-primary',
                  isWriting && 'opacity-60',
                )}
              >
                {t(preset.i18nKey, { defaultValue: preset.label })}
              </button>
            );
          })}
          <span
            className={clsx(
              'rounded-full border px-3 py-1.5 text-sm',
              activePreset === 'custom'
                ? 'border-oe-blue bg-oe-blue/10 text-oe-blue'
                : 'border-border-light bg-surface-secondary text-content-tertiary',
            )}
          >
            {t('match.wizard.grouping.preset.custom', { defaultValue: 'Custom' })}
          </span>
        </div>
      </div>

      {/* ── B. 3-slot ordered key picker ─────────────────────────────── */}
      <div>
        <div className="mb-2 flex items-center gap-2">
          <span className="text-xs font-medium uppercase tracking-wide text-content-tertiary">
            {t('match.wizard.grouping.customKey', {
              defaultValue: 'Custom grouping key',
            })}
          </span>
          {attrsQ.isLoading && (
            <Loader2 className="h-3 w-3 animate-spin text-content-tertiary" />
          )}
          {(isWriting || isUpdatingScope) && (
            <span className="text-xs text-content-tertiary">
              {t('match.wizard.grouping.syncing', { defaultValue: 'Syncing…' })}
            </span>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {([0, 1, 2] as const).map((idx) => {
            const disabled =
              attrsQ.isLoading ||
              (idx === 1 && !slots[0]) ||
              (idx === 2 && !slots[1]);
            return (
              <select
                key={idx}
                value={slots[idx]}
                onChange={(e) => updateSlot(idx, e.target.value)}
                disabled={disabled}
                data-testid={`grouping-slot-${idx + 1}`}
                className={clsx(
                  'rounded-lg border border-border-light bg-surface-primary px-3 py-1.5 text-sm',
                  'focus:border-oe-blue focus:outline-none focus:ring-1 focus:ring-oe-blue',
                  disabled && 'opacity-50',
                )}
              >
                <option value="">
                  {idx === 0
                    ? t('match.wizard.grouping.slot1', { defaultValue: 'Primary key…' })
                    : idx === 1
                      ? t('match.wizard.grouping.slot2', { defaultValue: 'Secondary…' })
                      : t('match.wizard.grouping.slot3', { defaultValue: 'Tertiary…' })}
                </option>
                {availableKeys.map((k) => (
                  <option key={k} value={k}>
                    {k}
                  </option>
                ))}
              </select>
            );
          })}
        </div>
      </div>

      {/* ── C. Filter-chip row (per-category include filter) ─────────── */}
      <div>
        <div className="mb-2 flex items-center gap-2">
          <span className="text-xs font-medium uppercase tracking-wide text-content-tertiary">
            {t('match.wizard.grouping.filters', { defaultValue: 'Filters' })}
          </span>
          {categoriesQ.isLoading && (
            <Loader2 className="h-3 w-3 animate-spin text-content-tertiary" />
          )}
          {selectedCats.size > 0 && (
            <button
              type="button"
              onClick={clearCategoryFilter}
              disabled={isWriting}
              data-testid="grouping-filters-clear"
              className={clsx(
                'text-xs text-oe-blue hover:underline',
                isWriting && 'opacity-60',
              )}
            >
              {t('match.wizard.grouping.filtersClear', {
                defaultValue: 'Clear ({{count}})',
                count: selectedCats.size,
              })}
            </button>
          )}
        </div>

        {categoriesQ.isLoading ? (
          <div className="flex items-center gap-2 text-xs text-content-tertiary">
            <Loader2 className="h-3 w-3 animate-spin" />
            {t('match.wizard.grouping.filtersLoading', {
              defaultValue: 'Loading categories…',
            })}
          </div>
        ) : categories.length === 0 ? (
          <div
            className="rounded-lg border border-border-light bg-surface-secondary px-3 py-2 text-xs text-content-tertiary"
            data-testid="grouping-filters-empty"
          >
            {t('match.wizard.grouping.filtersEmpty', {
              defaultValue: 'No categories to filter.',
            })}
          </div>
        ) : (
          <div className="flex flex-wrap gap-2" data-testid="grouping-filters">
            {categories.map((cat) => {
              const active = selectedCats.has(cat.category);
              const label = ifcClassLabel(t, cat.category);
              return (
                <button
                  key={cat.category}
                  type="button"
                  aria-pressed={active}
                  data-testid={`grouping-filter-${cat.category}`}
                  onClick={() => toggleCategory(cat.category)}
                  disabled={isWriting}
                  className={clsx(
                    'inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-sm transition-colors',
                    active
                      ? 'border-oe-blue bg-oe-blue/10 text-oe-blue'
                      : 'border-border-light bg-surface-secondary text-content-primary hover:bg-surface-primary',
                    isWriting && 'opacity-60',
                  )}
                  title={cat.category}
                >
                  <span>{label}</span>
                  <span
                    className={clsx(
                      'rounded-full px-1.5 text-xs tabular-nums',
                      active
                        ? 'bg-oe-blue/20 text-oe-blue'
                        : 'bg-surface-primary text-content-tertiary',
                    )}
                  >
                    {cat.count}
                  </span>
                </button>
              );
            })}
          </div>
        )}

        <p className="mt-2 text-xs text-content-tertiary">
          {selectedCats.size > 0
            ? t('match.wizard.grouping.filtersActiveHint', {
                defaultValue:
                  'Showing only the {{count}} selected categories in the preview below.',
                count: selectedCats.size,
              })
            : t('match.wizard.grouping.filtersAllHint', {
                defaultValue:
                  'All categories included. Pick one or more to narrow the preview.',
              })}
        </p>
      </div>

      {/* ── D. Live count-table ──────────────────────────────────────── */}
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <div className="text-xs font-medium uppercase tracking-wide text-content-tertiary">
            {t('match.wizard.grouping.preview', { defaultValue: 'Preview' })}
          </div>
          <Button
            variant="ghost"
            size="sm"
            icon={<RefreshCw className="h-3.5 w-3.5" />}
            onClick={() => groupsQ.refetch()}
            disabled={groupsQ.isFetching}
          >
            {t('common.refresh', { defaultValue: 'Refresh' })}
          </Button>
        </div>

        {groupsQ.isLoading || isWriting ? (
          <div className="flex items-center gap-2 text-sm text-content-secondary">
            <Loader2 className="h-4 w-4 animate-spin" />
            {t('match.wizard.buildingGroups', { defaultValue: 'Building groups…' })}
          </div>
        ) : groupsQ.isError ? (
          <div className="rounded-lg border border-rose-200 bg-rose-50 p-4 text-sm text-rose-800 dark:border-rose-900/50 dark:bg-rose-900/20 dark:text-rose-200">
            <div className="font-medium">
              {t('match.wizard.groupsError', {
                defaultValue: 'Could not build groups',
              })}
            </div>
            <p className="mt-1 text-xs opacity-90 break-words">
              {String((groupsQ.error as Error | null)?.message ?? '')}
            </p>
          </div>
        ) : groups.length === 0 ? (
          <div className="rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800 dark:border-amber-900/50 dark:bg-amber-900/20 dark:text-amber-200">
            {t('match.wizard.noGroups', {
              defaultValue: 'No estimable groups for the current key.',
            })}
          </div>
        ) : (
          <>
            <div className="grid gap-3 sm:grid-cols-3">
              <SummaryTile
                label={t('match.wizard.groups', { defaultValue: 'Groups' })}
                value={groups.length}
              />
              <SummaryTile
                label={t('match.wizard.elements', { defaultValue: 'Elements' })}
                value={totalElements}
              />
              <SummaryTile
                label={t('match.wizard.grouping.singletons', {
                  defaultValue: 'Singleton groups',
                })}
                value={singletonGroups}
                tone={highMissingness ? 'warn' : 'default'}
              />
            </div>

            <div className="max-h-80 overflow-auto rounded-lg border border-border-light">
              <table className="w-full text-sm">
                <thead className="sticky top-0 bg-surface-secondary text-content-secondary">
                  <tr>
                    <th className="px-3 py-2 text-left font-medium">
                      {t('match.wizard.group', { defaultValue: 'Group' })}
                    </th>
                    <th className="px-3 py-2 text-right font-medium">
                      {t('match.wizard.count', { defaultValue: 'Count' })}
                    </th>
                    <th className="px-3 py-2 text-left font-medium">
                      {t('match.wizard.grouping.unit', { defaultValue: 'Unit' })}
                    </th>
                    <th className="px-3 py-2 text-left font-medium">
                      {t('match.wizard.grouping.samples', { defaultValue: 'Samples' })}
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {groups.map((g) => (
                    <tr key={g.id} className="border-t border-border-light/60">
                      <td className="px-3 py-2 text-content-primary">
                        <div className="font-medium">{g.display_label}</div>
                        <div className="text-xs text-content-tertiary">{g.trade}</div>
                      </td>
                      <td className="px-3 py-2 text-right tabular-nums text-content-primary">
                        {g.element_count}
                      </td>
                      <td className="px-3 py-2 text-content-secondary">
                        {g.chosen_unit ?? '—'}
                      </td>
                      <td className="px-3 py-2 text-content-secondary">
                        {g.sample_names.length > 0 ? (
                          <span
                            className="block max-w-[280px] truncate"
                            title={fmtList(g.sample_names)}
                          >
                            {fmtList(g.sample_names.slice(0, 3))}
                          </span>
                        ) : (
                          <span className="text-content-tertiary">—</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {tooGranular && (
              <div
                className="flex items-start gap-2 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800 dark:border-amber-900/50 dark:bg-amber-900/20 dark:text-amber-200"
                data-testid="grouping-warn-too-granular"
              >
                <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                <div>
                  {t('match.wizard.grouping.warnTooGranular', {
                    defaultValue:
                      'Too granular - most groups have a single element. Drop the last key.',
                  })}
                </div>
              </div>
            )}
            {highMissingness && !tooGranular && (
              <div
                className="flex items-start gap-2 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800 dark:border-amber-900/50 dark:bg-amber-900/20 dark:text-amber-200"
                data-testid="grouping-warn-missingness"
              >
                <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                <div>
                  {t('match.wizard.grouping.warnMissingness', {
                    defaultValue: 'Key has high missingness.',
                  })}
                </div>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}

function SummaryTile({
  label,
  value,
  tone = 'default',
}: {
  label: string;
  value: string | number;
  tone?: 'default' | 'warn';
}) {
  return (
    <div
      className={clsx(
        'rounded-lg border px-4 py-3',
        tone === 'warn'
          ? 'border-amber-200 bg-amber-50 dark:border-amber-900/50 dark:bg-amber-900/20'
          : 'border-border-light bg-surface-secondary',
      )}
    >
      <div className="text-2xl font-semibold text-content-primary tabular-nums">{value}</div>
      <div className="text-xs text-content-secondary">{label}</div>
    </div>
  );
}
