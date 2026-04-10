/**
 * BIMFilterPanel — fast element filter + group sidebar for the BIM viewer.
 *
 * Supports:
 * - Free-text search across name / type / category / storey
 * - Storey/level multi-select
 * - Type multi-select (model-format-aware)
 *     - Revit models  → Revit Categories (Walls, Doors, Floors, Furniture, …)
 *     - IFC models    → IFC Entities (IfcWall, IfcSlab, IfcDoor, …)
 * - Group-by selector (storey / type)
 *
 * Performance:
 * - All counts are memoized from the `elements` prop (O(n) once per change)
 * - Filter predicate is rebuilt only when filter state changes
 * - Parent applies the predicate via ElementManager.applyFilter() which
 *   just toggles mesh.visible — no re-render of Three.js scene
 * - 16k+ elements tested
 */

import { useMemo, useState, useCallback, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import {
  Search,
  Layers,
  Package,
  ChevronRight,
  ChevronDown,
  Eye,
  EyeOff,
  X,
} from 'lucide-react';
import type { BIMElementData } from '@/shared/ui/BIMViewer';
import {
  bucketOf,
  isNoiseCategory,
  BUCKETS,
  type BIMCategoryBucket,
} from './bimCategoryTaxonomy';

// ── Types ────────────────────────────────────────────────────────────────

export type GroupBy = 'storey' | 'type';

export type BIMModelFormat = 'rvt' | 'ifc' | 'other';

export interface BIMFilterState {
  search: string;
  storeys: Set<string>; // empty = show all
  types: Set<string>; // empty = show all
  /** When true, annotation/analytical categories are excluded from the
   *  viewport regardless of explicit type-filter selection. Defaults to
   *  true so first-time users see only real building elements. */
  buildingsOnly: boolean;
  groupBy: GroupBy;
}

interface BIMFilterPanelProps {
  elements: BIMElementData[];
  /** Raw model_format string from backend ("rvt" / "ifc" / …). */
  modelFormat?: string;
  onFilterChange: (
    predicate: (el: BIMElementData) => boolean,
    visibleCount: number,
  ) => void;
  onClose?: () => void;
  onElementClick?: (elementId: string) => void;
}

// ── Helpers ──────────────────────────────────────────────────────────────

/**
 * Detect whether the loaded model is Revit or IFC.
 * Priority: explicit `model_format` prop → element properties fallback.
 */
function detectModelFormat(
  modelFormat: string | undefined,
  elements: BIMElementData[],
): BIMModelFormat {
  const fmt = (modelFormat || '').toLowerCase();
  if (fmt.includes('rvt') || fmt.includes('revit')) return 'rvt';
  if (fmt.includes('ifc')) return 'ifc';

  // Fallback: inspect first element
  const first = elements[0];
  if (first) {
    if (first.element_type?.toLowerCase().startsWith('ifc')) return 'ifc';
    const props = first.properties as Record<string, unknown> | undefined;
    if (props) {
      const hasRevitKey = Object.keys(props).some((k) =>
        k.toLowerCase().includes('revit'),
      );
      if (hasRevitKey) return 'rvt';
    }
  }
  return 'other';
}

/**
 * Get the type/category label for an element depending on model format.
 * - Revit: prefer `category` (e.g. "Walls"), fall back to `element_type`
 * - IFC: use `element_type` which holds the IfcEntity name (e.g. "IfcWall")
 */
function getTypeKey(el: BIMElementData, format: BIMModelFormat): string {
  if (format === 'rvt') {
    return el.category || el.element_type || 'Unknown';
  }
  if (format === 'ifc') {
    return el.element_type || el.category || 'Unknown';
  }
  return el.category || el.element_type || 'Unknown';
}

// ── Component ────────────────────────────────────────────────────────────

export default function BIMFilterPanel({
  elements,
  modelFormat,
  onFilterChange,
  onClose,
  onElementClick,
}: BIMFilterPanelProps) {
  const { t } = useTranslation();

  const format = useMemo(
    () => detectModelFormat(modelFormat, elements),
    [modelFormat, elements],
  );

  const [state, setState] = useState<BIMFilterState>({
    search: '',
    storeys: new Set(),
    types: new Set(),
    buildingsOnly: true,
    groupBy: 'type',
  });

  const [expandedGroups, setExpandedGroups] = useState<Set<string>>(new Set());
  /** Which bucket sections in the Types panel are currently expanded.
   *  Real building buckets are open by default, noise buckets are closed. */
  const [expandedBuckets, setExpandedBuckets] = useState<Set<BIMCategoryBucket>>(
    () => new Set(['structure', 'envelope', 'openings', 'mep']),
  );

  // ── Derived: counts per dimension + bucket grouping ─────────────────
  const counts = useMemo(() => {
    const byStorey = new Map<string, number>();
    const byType = new Map<string, number>();
    /** bucket → ordered list of [typeName, count] */
    const byBucket = new Map<BIMCategoryBucket, Map<string, number>>();
    const bucketTotals = new Map<BIMCategoryBucket, number>();

    for (const el of elements) {
      const s = el.storey || '—';
      byStorey.set(s, (byStorey.get(s) ?? 0) + 1);

      const tpe = getTypeKey(el, format);
      byType.set(tpe, (byType.get(tpe) ?? 0) + 1);

      const bucket = bucketOf(tpe);
      let perBucket = byBucket.get(bucket);
      if (!perBucket) {
        perBucket = new Map();
        byBucket.set(bucket, perBucket);
      }
      perBucket.set(tpe, (perBucket.get(tpe) ?? 0) + 1);
      bucketTotals.set(bucket, (bucketTotals.get(bucket) ?? 0) + 1);
    }

    // Sort buckets by their semantic order, then build the ordered
    // (bucket → types[]) structure used by the renderer.
    const orderedBuckets: Array<{
      bucket: BIMCategoryBucket;
      total: number;
      types: Array<[string, number]>;
    }> = [];
    for (const meta of Object.values(BUCKETS).sort((a, b) => a.order - b.order)) {
      const types = byBucket.get(meta.id);
      if (!types || types.size === 0) continue;
      orderedBuckets.push({
        bucket: meta.id,
        total: bucketTotals.get(meta.id) ?? 0,
        types: Array.from(types.entries()).sort((a, b) => b[1] - a[1]),
      });
    }

    return {
      storeys: Array.from(byStorey.entries()).sort((a, b) =>
        a[0].localeCompare(b[0]),
      ),
      types: Array.from(byType.entries()).sort((a, b) => b[1] - a[1]),
      buckets: orderedBuckets,
    };
  }, [elements, format]);

  // ── Filter predicate ───────────────────────────────────────────────
  const applyFilters = useCallback(
    (s: BIMFilterState) => {
      const search = s.search.trim().toLowerCase();
      const predicate = (el: BIMElementData): boolean => {
        const tpe = getTypeKey(el, format);
        // Buildings-only toggle hides annotation/analytical noise
        if (s.buildingsOnly && isNoiseCategory(tpe)) return false;
        // Storey filter (empty set = show all)
        if (s.storeys.size > 0) {
          if (!s.storeys.has(el.storey || '—')) return false;
        }
        // Type filter
        if (s.types.size > 0) {
          if (!s.types.has(tpe)) return false;
        }
        // Search
        if (search) {
          const hay = (
            (el.name || '') +
            ' ' +
            (el.element_type || '') +
            ' ' +
            (el.category || '') +
            ' ' +
            (el.storey || '')
          ).toLowerCase();
          if (!hay.includes(search)) return false;
        }
        return true;
      };
      const count = elements.filter(predicate).length;
      onFilterChange(predicate, count);
    },
    [elements, onFilterChange, format],
  );

  // Re-apply whenever state changes
  useEffect(() => {
    applyFilters(state);
  }, [state, applyFilters]);

  // ── Handlers ───────────────────────────────────────────────────────
  const toggleSet = useCallback(
    (key: 'storeys' | 'types', value: string) => {
      setState((prev) => {
        const next = new Set(prev[key]);
        if (next.has(value)) next.delete(value);
        else next.add(value);
        return { ...prev, [key]: next };
      });
    },
    [],
  );

  const clearAll = useCallback(() => {
    setState((prev) => ({
      ...prev,
      search: '',
      storeys: new Set(),
      types: new Set(),
    }));
  }, []);

  const toggleBucket = useCallback((bucket: BIMCategoryBucket) => {
    setExpandedBuckets((prev) => {
      const next = new Set(prev);
      if (next.has(bucket)) next.delete(bucket);
      else next.add(bucket);
      return next;
    });
  }, []);

  /** Toggle every type chip in a bucket on or off in one click. */
  const toggleBucketSelection = useCallback((typesInBucket: string[]) => {
    setState((prev) => {
      const next = new Set(prev.types);
      const allSelected = typesInBucket.every((t) => next.has(t));
      if (allSelected) {
        for (const t of typesInBucket) next.delete(t);
      } else {
        for (const t of typesInBucket) next.add(t);
      }
      return { ...prev, types: next };
    });
  }, []);

  const toggleGroup = useCallback((id: string) => {
    setExpandedGroups((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  const hasActiveFilters =
    state.search.length > 0 || state.storeys.size > 0 || state.types.size > 0;

  // ── Grouped element tree (for element explorer) ─────────────────────
  const visibleElements = useMemo(() => {
    const search = state.search.trim().toLowerCase();
    return elements.filter((el) => {
      const tpe = getTypeKey(el, format);
      if (state.buildingsOnly && isNoiseCategory(tpe)) return false;
      if (state.storeys.size > 0 && !state.storeys.has(el.storey || '—'))
        return false;
      if (state.types.size > 0 && !state.types.has(tpe)) return false;
      if (search) {
        const hay = (
          (el.name || '') +
          ' ' +
          (el.element_type || '') +
          ' ' +
          (el.category || '')
        ).toLowerCase();
        if (!hay.includes(search)) return false;
      }
      return true;
    });
  }, [elements, state, format]);

  const groupedElements = useMemo(() => {
    const groups = new Map<string, BIMElementData[]>();
    for (const el of visibleElements) {
      const key: string =
        state.groupBy === 'storey' ? el.storey || '—' : getTypeKey(el, format);
      const arr = groups.get(key);
      if (arr) arr.push(el);
      else groups.set(key, [el]);
    }
    // Sort groups by size (biggest first)
    return Array.from(groups.entries()).sort((a, b) => b[1].length - a[1].length);
  }, [visibleElements, state.groupBy, format]);

  // Label for the types section changes depending on model format
  const typesSectionTitle =
    format === 'rvt'
      ? t('bim.filter_revit_categories', { defaultValue: 'Revit Categories' })
      : format === 'ifc'
        ? t('bim.filter_ifc_entities', { defaultValue: 'IFC Entities' })
        : t('bim.filter_types', { defaultValue: 'Element Types' });

  const typeGroupLabel =
    format === 'rvt'
      ? t('bim.filter_group_category', { defaultValue: 'by Category' })
      : format === 'ifc'
        ? t('bim.filter_group_entity', { defaultValue: 'by Entity' })
        : t('bim.filter_group_type', { defaultValue: 'by Type' });

  return (
    <div
      className="h-full flex flex-col bg-surface-primary border-e border-border-light"
      style={{ width: 320, minWidth: 320 }}
    >
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-border-light shrink-0">
        <div className="flex items-center gap-2">
          <Layers size={16} className="text-content-tertiary" />
          <h2 className="text-sm font-semibold text-content-primary">
            {t('bim.filter_title', { defaultValue: 'Filter & Group' })}
          </h2>
          {format !== 'other' && (
            <span className="text-[9px] font-bold uppercase tracking-wider px-1.5 py-0.5 rounded bg-surface-secondary text-content-tertiary border border-border-light">
              {format}
            </span>
          )}
        </div>
        {onClose && (
          <button
            onClick={onClose}
            className="p-1 rounded-md text-content-tertiary hover:text-content-primary hover:bg-surface-secondary"
            title={t('common.close', { defaultValue: 'Close' })}
          >
            <X size={14} />
          </button>
        )}
      </div>

      {/* Search */}
      <div className="px-4 py-3 border-b border-border-light shrink-0">
        <div className="relative">
          <Search
            size={14}
            className="absolute start-2.5 top-1/2 -translate-y-1/2 text-content-quaternary pointer-events-none"
          />
          <input
            type="text"
            value={state.search}
            onChange={(e) => setState((p) => ({ ...p, search: e.target.value }))}
            placeholder={t('bim.filter_search_placeholder', {
              defaultValue: 'Search name, type, storey…',
            })}
            className="w-full ps-8 pe-8 py-1.5 text-xs rounded-md bg-surface-secondary border border-border-light focus:outline-none focus:ring-1 focus:ring-oe-blue focus:border-oe-blue"
          />
          {state.search && (
            <button
              onClick={() => setState((p) => ({ ...p, search: '' }))}
              className="absolute end-2 top-1/2 -translate-y-1/2 text-content-quaternary hover:text-content-primary"
            >
              <X size={12} />
            </button>
          )}
        </div>

        {/* Visible count + clear */}
        <div className="flex items-center justify-between mt-2 text-[11px] text-content-tertiary">
          <span>
            {t('bim.filter_visible_count', {
              defaultValue: '{{visible}} of {{total}} visible',
              visible: visibleElements.length,
              total: elements.length,
            })}
          </span>
          {hasActiveFilters && (
            <button onClick={clearAll} className="text-oe-blue hover:underline">
              {t('bim.filter_clear', { defaultValue: 'Clear all' })}
            </button>
          )}
        </div>

        {/* Buildings-only toggle — hides annotation/analytical noise */}
        <label className="flex items-center justify-between mt-2 text-[11px] text-content-secondary cursor-pointer select-none">
          <span className="flex items-center gap-1.5">
            <Package size={11} className="text-content-tertiary" />
            {t('bim.filter_buildings_only', {
              defaultValue: 'Building elements only',
            })}
          </span>
          <button
            type="button"
            role="switch"
            aria-checked={state.buildingsOnly}
            onClick={() =>
              setState((p) => ({ ...p, buildingsOnly: !p.buildingsOnly }))
            }
            className={`relative inline-flex h-4 w-7 items-center rounded-full transition-colors ${
              state.buildingsOnly ? 'bg-oe-blue' : 'bg-surface-tertiary'
            }`}
          >
            <span
              className={`inline-block h-3 w-3 transform rounded-full bg-white transition-transform ${
                state.buildingsOnly ? 'translate-x-3.5' : 'translate-x-0.5'
              }`}
            />
          </button>
        </label>
      </div>

      {/* Scroll area: Storeys + Types */}
      <div className="flex-1 overflow-y-auto">
        {/* Storeys */}
        <FilterSection
          title={t('bim.filter_storeys', { defaultValue: 'Storeys' })}
          icon={<Layers size={12} />}
        >
          {counts.storeys.map(([name, count]) => {
            const active = state.storeys.has(name);
            return (
              <FilterChip
                key={name}
                label={name}
                count={count}
                active={active}
                onClick={() => toggleSet('storeys', name)}
              />
            );
          })}
          {counts.storeys.length === 0 && (
            <div className="text-[10px] text-content-quaternary italic">
              {t('bim.filter_no_storeys', { defaultValue: 'No storeys detected' })}
            </div>
          )}
        </FilterSection>

        {/* Types — grouped by semantic bucket (Structure / Envelope / MEP / …)
            Noise buckets (Annotations, Analytical) are hidden when
            buildingsOnly is on, otherwise shown collapsed at the bottom. */}
        <FilterSection title={typesSectionTitle} icon={<Package size={12} />}>
          <div className="space-y-1">
            {counts.buckets
              .filter(({ bucket }) =>
                state.buildingsOnly ? !BUCKETS[bucket].noise : true,
              )
              .map(({ bucket, total, types }) => {
                const meta = BUCKETS[bucket];
                const isOpen = expandedBuckets.has(bucket);
                const typeNames = types.map(([n]) => n);
                const allOn = typeNames.every((n) => state.types.has(n));
                return (
                  <div
                    key={bucket}
                    className="rounded border border-border-light/60 bg-surface-secondary/40"
                  >
                    <div className="flex items-center justify-between px-2 py-1">
                      <button
                        type="button"
                        onClick={() => toggleBucket(bucket)}
                        className="flex items-center gap-1.5 min-w-0 flex-1 text-left"
                      >
                        {isOpen ? (
                          <ChevronDown size={11} className="text-content-tertiary shrink-0" />
                        ) : (
                          <ChevronRight size={11} className="text-content-tertiary shrink-0" />
                        )}
                        <span className={`text-[11px] font-semibold ${meta.color} truncate`}>
                          {meta.label}
                        </span>
                        <span className="text-[10px] text-content-quaternary tabular-nums shrink-0">
                          {total.toLocaleString()}
                        </span>
                      </button>
                      <button
                        type="button"
                        onClick={() => toggleBucketSelection(typeNames)}
                        className="text-[10px] px-1.5 py-0.5 rounded text-content-tertiary hover:text-oe-blue hover:bg-surface-primary"
                        title={
                          allOn
                            ? t('bim.filter_bucket_clear', {
                                defaultValue: 'Clear bucket',
                              })
                            : t('bim.filter_bucket_select_all', {
                                defaultValue: 'Select all in bucket',
                              })
                        }
                      >
                        {allOn ? '✓' : '+'}
                      </button>
                    </div>
                    {isOpen && (
                      <div className="px-2 pb-1.5 pt-0.5 space-y-0.5">
                        {types.map(([name, count]) => {
                          const active = state.types.has(name);
                          return (
                            <FilterChip
                              key={name}
                              label={name}
                              count={count}
                              active={active}
                              onClick={() => toggleSet('types', name)}
                            />
                          );
                        })}
                      </div>
                    )}
                  </div>
                );
              })}
            {counts.buckets.length === 0 && (
              <div className="text-[10px] text-content-quaternary italic px-1">
                {t('bim.filter_no_types', { defaultValue: 'No element types detected' })}
              </div>
            )}
          </div>
        </FilterSection>

        {/* Element explorer (grouped) */}
        <div className="border-t border-border-light">
          <div className="px-4 py-2.5 flex items-center justify-between bg-surface-secondary">
            <span className="text-[10px] font-semibold uppercase tracking-wider text-content-tertiary">
              {t('bim.filter_explorer', { defaultValue: 'Element Explorer' })}
            </span>
            <select
              value={state.groupBy}
              onChange={(e) =>
                setState((p) => ({ ...p, groupBy: e.target.value as GroupBy }))
              }
              className="text-[10px] py-0.5 px-1.5 rounded border border-border-light bg-surface-primary text-content-secondary focus:outline-none focus:ring-1 focus:ring-oe-blue"
            >
              <option value="storey">
                {t('bim.filter_group_storey', { defaultValue: 'by Storey' })}
              </option>
              <option value="type">{typeGroupLabel}</option>
            </select>
          </div>

          {/* Only render first 200 items per group when expanded */}
          <div className="divide-y divide-border-light/50">
            {groupedElements.map(([groupName, items]) => {
              const isExpanded = expandedGroups.has(groupName);
              return (
                <div key={groupName}>
                  <button
                    onClick={() => toggleGroup(groupName)}
                    className="w-full flex items-center justify-between px-4 py-1.5 text-left hover:bg-surface-secondary transition-colors"
                  >
                    <div className="flex items-center gap-1.5 min-w-0">
                      {isExpanded ? (
                        <ChevronDown
                          size={12}
                          className="text-content-tertiary shrink-0"
                        />
                      ) : (
                        <ChevronRight
                          size={12}
                          className="text-content-tertiary shrink-0"
                        />
                      )}
                      <span className="text-xs font-medium text-content-primary truncate">
                        {groupName}
                      </span>
                    </div>
                    <span className="text-[10px] text-content-tertiary tabular-nums shrink-0 ms-2">
                      {items.length}
                    </span>
                  </button>

                  {isExpanded && (
                    <ul className="py-1">
                      {items.slice(0, 200).map((el) => (
                        <li key={el.id}>
                          <button
                            onClick={() => onElementClick?.(el.id)}
                            className="w-full text-left ps-9 pe-3 py-0.5 text-[11px] text-content-secondary hover:text-content-primary hover:bg-surface-secondary truncate block"
                            title={el.name}
                          >
                            {el.name || el.element_type || '—'}
                          </button>
                        </li>
                      ))}
                      {items.length > 200 && (
                        <li className="ps-9 py-0.5 text-[10px] text-content-quaternary italic">
                          + {items.length - 200} more…
                        </li>
                      )}
                    </ul>
                  )}
                </div>
              );
            })}
            {groupedElements.length === 0 && (
              <div className="px-4 py-4 text-[11px] text-content-quaternary text-center">
                {t('bim.filter_no_results', {
                  defaultValue: 'No elements match filters',
                })}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

// ── Sub-components ───────────────────────────────────────────────────────

function FilterSection({
  title,
  icon,
  children,
}: {
  title: string;
  icon: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <div className="border-b border-border-light py-3 px-4">
      <div className="flex items-center gap-1.5 mb-2">
        <span className="text-content-tertiary">{icon}</span>
        <span className="text-[10px] font-semibold uppercase tracking-wider text-content-tertiary">
          {title}
        </span>
      </div>
      <div className="space-y-1">{children}</div>
    </div>
  );
}

function FilterChip({
  label,
  count,
  active,
  onClick,
}: {
  label: string;
  count: number;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className={`w-full flex items-center justify-between gap-2 px-2 py-1 rounded text-[11px] transition-colors ${
        active
          ? 'bg-oe-blue/10 text-oe-blue font-medium'
          : 'text-content-secondary hover:bg-surface-secondary'
      }`}
    >
      <div className="flex items-center gap-1.5 min-w-0 flex-1">
        {active ? (
          <Eye size={10} className="shrink-0" />
        ) : (
          <EyeOff size={10} className="shrink-0 opacity-40" />
        )}
        <span className="truncate">{label}</span>
      </div>
      <span className="text-[10px] text-content-quaternary tabular-nums shrink-0">
        {count.toLocaleString()}
      </span>
    </button>
  );
}
