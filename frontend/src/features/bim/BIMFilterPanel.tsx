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
  Link2,
  Bookmark,
  Trash2,
} from 'lucide-react';
import type { BIMElementGroup } from './api';
import type { BIMElementData } from '@/shared/ui/BIMViewer';
import {
  bucketOf,
  isNoiseCategory,
  prettifyCategoryName,
  BUCKETS,
  type BIMCategoryBucket,
} from './bimCategoryTaxonomy';

// ── Types ────────────────────────────────────────────────────────────────

export type GroupBy = 'storey' | 'type';

/** Top-level grouping mode for the type filter section.
 *
 *   • category — flat list of every unique element_type / IfcEntity,
 *                sorted by count.  Best matches "show me all the
 *                Revit categories / all the IfcEntities".  This is
 *                the default because it works for BOTH Revit and IFC
 *                without any noise / curation.
 *   • typename — hierarchical Category → Type Name (Revit Browser
 *                style: "Walls > Generic - 200mm").  Best for picking
 *                a single type out of a complex model.
 *   • buckets  — semantic buckets (Structure / Envelope / MEP / …)
 *                that aggregate categories into estimator-friendly
 *                groups.  Useful when you want a quick overview but
 *                hides the raw category names.
 */
export type GroupingMode = 'category' | 'typename' | 'buckets';

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
  /** When set, the panel shows a "Link to BOQ" button that opens the
   *  AddToBOQ modal populated with the current filtered subset. */
  onQuickTakeoff?: () => void;
  /** Current visible-element count from the parent (after applyFilter). */
  visibleElementCount?: number | null;
  /** When set, the panel shows a "Save as group" button that opens the
   *  SaveGroupModal pre-filled with the current filter criteria. */
  onSaveAsGroup?: (filter: BIMFilterState, visibleElementIds: string[]) => void;
  /** Saved element groups for the current model — rendered at the top of
   *  the panel as a one-click apply / link / delete row. */
  savedGroups?: BIMElementGroup[];
  /** User clicked a saved group → apply its filter_criteria to the panel. */
  onApplyGroup?: (group: BIMElementGroup) => void;
  /** User clicked the link icon on a saved group → link it to BOQ. */
  onLinkGroupToBOQ?: (group: BIMElementGroup) => void;
  /** User clicked the delete icon on a saved group. */
  onDeleteGroup?: (group: BIMElementGroup) => void;
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
 * Get the top-level category label for an element depending on model format.
 *
 *   • Revit  →  the Category (Walls, Doors, Curtain Wall Mullions, …).
 *               Stored on `el.category` if the converter populated it,
 *               otherwise we fall back to `el.element_type` which the
 *               Excel/parquet conversion uses as the category column.
 *   • IFC    →  the IfcEntity (IfcWall, IfcSlab, IfcDoor, …) which is
 *               always on `el.element_type`.
 *
 * Both formats end up using `element_type` as the primary axis when
 * `category` isn't populated — that's the "Category" view in the
 * filter panel grouping selector.
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

/**
 * Get the second-level Type Name for an element — e.g. "Generic - 200mm"
 * for a Wall, "0915 x 1220mm" for a Door, "L Mullion 1" for a curtain
 * wall mullion.  This is the Revit "Family/Type Name" axis.
 *
 * Source preference order:
 *   1. `el.name` (always populated by the parquet ingestion path)
 *   2. `el.properties.family` (Revit Family parameter)
 *   3. `el.properties["family and type"]` (combined Revit param)
 *   4. `el.properties.type` (Revit Type parameter)
 *   5. fallback to "Unspecified"
 */
function getTypeNameKey(el: BIMElementData): string {
  if (el.name && el.name !== 'None' && el.name !== '') return el.name;
  const props = (el.properties || {}) as Record<string, unknown>;
  const cand =
    props['family'] ??
    props['family and type'] ??
    props['type'] ??
    props['Family'] ??
    props['Type'];
  if (typeof cand === 'string' && cand !== '' && cand !== 'None') return cand;
  return 'Unspecified';
}

/**
 * Parse a raw storey string into a structured form for sorting and
 * display.  Revit / IFC level names typically look like:
 *
 *   "01 - Entry Level"     →  level = 1, label = "Entry Level"
 *   "02 - Floor 1"         →  level = 2, label = "Floor 1"
 *   "Level 03"             →  level = 3, label = "Level 03"
 *   "Roof"                 →  level = null, label = "Roof"
 *   "B1 - Basement"        →  level = -1, label = "Basement"
 *
 * The leading number (or B1/B2 basement notation) is extracted as
 * `level` so that storeys can be ordered ground-up regardless of how
 * the originating CAD tool formatted the string.
 */
export interface ParsedStorey {
  raw: string;
  /** Numeric level extracted from the prefix; null if no prefix found. */
  level: number | null;
  /** Display label with the prefix stripped. */
  label: string;
  /** Element count on this storey. */
  count: number;
}

function parseStorey(raw: string, count: number): ParsedStorey {
  const trimmed = raw.trim();
  // Basement: "B1", "B2", "BSMT", "Basement 1"
  const basement = /^(?:b|bsmt|basement)\s*0*(\d+)/i.exec(trimmed);
  if (basement) {
    return {
      raw,
      level: -Number(basement[1]),
      label: trimmed.replace(/^[^-]*-\s*/, '') || trimmed,
      count,
    };
  }
  // "Ground Floor" / "Ground"
  if (/^ground/i.test(trimmed)) {
    return { raw, level: 0, label: trimmed, count };
  }
  // "Roof" / "Penthouse" — keep label, no level (sort to end)
  // Numeric prefix: "01 - Entry Level", "12 Foo", "Level 03"
  const numberMatch =
    /^(\d{1,3})(?:\s*[-–:.]\s*(.*))?$/.exec(trimmed) ||
    /^level\s+(\d{1,3})(?:\s*[-–:.]\s*(.*))?$/i.exec(trimmed) ||
    /^(?:floor|fl|etage|stockwerk)\s+(\d{1,3})(?:\s*[-–:.]\s*(.*))?$/i.exec(trimmed);
  if (numberMatch) {
    const level = Number(numberMatch[1]);
    const labelPart = numberMatch[2]?.trim();
    return {
      raw,
      level,
      label: labelPart && labelPart.length > 0 ? labelPart : trimmed,
      count,
    };
  }
  return { raw, level: null, label: trimmed, count };
}

/** Format a level number for display in the chip badge. */
function formatLevelBadge(level: number | null): string {
  if (level === null) return '';
  if (level < 0) return `B${Math.abs(level)}`;
  if (level === 0) return 'G';
  return String(level).padStart(2, '0');
}

// ── Component ────────────────────────────────────────────────────────────

export default function BIMFilterPanel({
  elements,
  modelFormat,
  onFilterChange,
  onClose,
  onElementClick,
  onQuickTakeoff,
  visibleElementCount: _visibleElementCount,
  onSaveAsGroup,
  savedGroups,
  onApplyGroup,
  onLinkGroupToBOQ,
  onDeleteGroup,
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
  /** Top-level grouping selector — defaults to "By Category" because
   *  it works equally well for Revit (categories) and IFC (entities)
   *  with zero curation. */
  const [groupingMode, setGroupingMode] = useState<GroupingMode>('category');
  /** Which Category headers in the "By Type Name" view are expanded. */
  const [expandedCategories, setExpandedCategories] = useState<Set<string>>(
    () => new Set(),
  );

  const [expandedGroups, setExpandedGroups] = useState<Set<string>>(new Set());
  /** Which bucket sections in the Types panel are currently expanded.
   *  Real building buckets are open by default, noise buckets are closed. */
  const [expandedBuckets, setExpandedBuckets] = useState<Set<BIMCategoryBucket>>(
    () => new Set(['structure', 'envelope', 'openings', 'mep']),
  );
  /** Whether the "Saved Groups" section at the top of the panel is expanded. */
  const [groupsExpanded, setGroupsExpanded] = useState(true);
  /** ID of the saved group whose filter is currently applied (if any) — used
   *  to highlight the active group row. */
  const [activeGroupId, setActiveGroupId] = useState<string | null>(null);

  /** Apply a saved group's `filter_criteria` to the panel state.  Converts
   *  the BIMGroupFilterCriteria array shape into the panel's Set shape. */
  const applyGroupAsFilter = useCallback((group: BIMElementGroup) => {
    const fc = group.filter_criteria || {};
    const toSet = (v: string | string[] | undefined): Set<string> => {
      if (!v) return new Set();
      return new Set(Array.isArray(v) ? v : [v]);
    };
    setState((prev) => ({
      ...prev,
      search: typeof fc.name_contains === 'string' ? fc.name_contains : '',
      storeys: toSet(fc.storey),
      types: toSet(fc.element_type),
    }));
    setActiveGroupId(group.id);
    onApplyGroup?.(group);
  }, [onApplyGroup]);

  // ── Derived: counts per dimension + bucket grouping ─────────────────
  //
  // Storey counts are scoped by the buildingsOnly toggle: when ON, the
  // ~10 000 annotation/analytical elements with `storey: null` are
  // EXCLUDED from the storey list, so the user sees a clean list of
  // real building levels instead of an overwhelming "—" entry that
  // dominates the panel.
  const counts = useMemo(() => {
    const byStorey = new Map<string, number>();
    const byType = new Map<string, number>();
    /** bucket → ordered list of [typeName, count] */
    const byBucket = new Map<BIMCategoryBucket, Map<string, number>>();
    const bucketTotals = new Map<BIMCategoryBucket, number>();
    /** Category → (TypeName → count) — Revit Browser hierarchy */
    const byCategoryThenType = new Map<string, Map<string, number>>();

    for (const el of elements) {
      const tpe = getTypeKey(el, format);
      const isNoise = isNoiseCategory(tpe);

      // Storey counts skip noise when buildingsOnly is on, AND skip
      // null storeys entirely (an annotation row with no level isn't
      // a useful "—" filter target).
      if (!(state.buildingsOnly && isNoise) && el.storey) {
        byStorey.set(el.storey, (byStorey.get(el.storey) ?? 0) + 1);
      }

      // ALL categories go into the byType map regardless of the
      // buildingsOnly toggle — the split into "building" vs "other" now
      // happens in the render layer (CategoryFlatList) so the user always
      // sees what's available, with annotations collapsed by default.
      byType.set(tpe, (byType.get(tpe) ?? 0) + 1);

      // Hierarchical Category → Type Name (Revit Browser style)
      const typeName = getTypeNameKey(el);
      let perCat = byCategoryThenType.get(tpe);
      if (!perCat) {
        perCat = new Map();
        byCategoryThenType.set(tpe, perCat);
      }
      perCat.set(typeName, (perCat.get(typeName) ?? 0) + 1);

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

    // Storey list — parse the leading number (if any) so "10 - Roof"
    // sorts after "02 - Entry Level" and not before it. Extract a
    // short label without the numeric prefix for cleaner display.
    const storeysOrdered = Array.from(byStorey.entries())
      .map(([raw, count]) => parseStorey(raw, count))
      .sort((a, b) => {
        // Numbered storeys first (sorted numerically), then unnamed.
        if (a.level !== null && b.level !== null) return a.level - b.level;
        if (a.level !== null) return -1;
        if (b.level !== null) return 1;
        return a.raw.localeCompare(b.raw);
      });

    // Hierarchical Category → Type Name list, sorted by category total
    // descending then by type-name count descending.  Filters out noise
    // categories when buildingsOnly is on.
    const categoriesWithTypes: Array<{
      category: string;
      total: number;
      types: Array<[string, number]>;
    }> = [];
    for (const [cat, typeMap] of byCategoryThenType.entries()) {
      const total = Array.from(typeMap.values()).reduce((s, n) => s + n, 0);
      categoriesWithTypes.push({
        category: cat,
        total,
        types: Array.from(typeMap.entries()).sort((a, b) => b[1] - a[1]),
      });
    }
    categoriesWithTypes.sort((a, b) => b.total - a.total);

    return {
      storeys: storeysOrdered,
      types: Array.from(byType.entries()).sort((a, b) => b[1] - a[1]),
      buckets: orderedBuckets,
      categoriesWithTypes,
    };
  }, [elements, format, state.buildingsOnly]);

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
      // Manual filter change drops the "applied group" highlight — the
      // filter is no longer 1:1 with the group's filter_criteria.
      setActiveGroupId(null);
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

        {/* Quick-takeoff button + Save as group button — both act on the
            currently filtered subset.  Quick takeoff opens AddToBOQ; Save
            as group opens SaveGroupModal so the user can name the
            selection and reuse it later. */}
        {visibleElements.length > 0 && visibleElements.length < elements.length && (
          <div className="mt-2 flex gap-1">
            {onQuickTakeoff && (
              <button
                type="button"
                onClick={onQuickTakeoff}
                className="flex-1 inline-flex items-center justify-center gap-1.5 px-2 py-1.5 text-[11px] font-medium rounded-md bg-oe-blue text-white hover:bg-oe-blue-dark transition-colors"
                title={t('bim.quick_takeoff_title', {
                  defaultValue: 'Create a BOQ position from the current filter',
                })}
              >
                <Link2 size={11} />
                {t('bim.quick_takeoff', {
                  defaultValue: 'Link {{count}} to BOQ',
                  count: visibleElements.length,
                })}
              </button>
            )}
            {onSaveAsGroup && (
              <button
                type="button"
                onClick={() =>
                  onSaveAsGroup(
                    state,
                    visibleElements.map((el) => el.id),
                  )
                }
                className="inline-flex items-center justify-center gap-1.5 px-2 py-1.5 text-[11px] font-medium rounded-md border border-oe-blue/40 text-oe-blue bg-oe-blue/5 hover:bg-oe-blue/10 transition-colors"
                title={t('bim.save_as_group_title', {
                  defaultValue: 'Save the current filter as a named group',
                })}
              >
                <Bookmark size={11} />
                {t('bim.save_as_group', { defaultValue: 'Save as group' })}
              </button>
            )}
          </div>
        )}

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
        {/* Saved Groups — appears at the top of the scroll area when the
            project has any saved BIMElementGroup rows.  Each row is a
            one-click "apply this filter", with link-to-BOQ + delete
            actions on hover. */}
        {savedGroups && savedGroups.length > 0 && (
          <div className="border-b border-border-light py-3 px-4">
            <button
              type="button"
              onClick={() => setGroupsExpanded((v) => !v)}
              className="w-full flex items-center justify-between gap-1.5 mb-2"
            >
              <div className="flex items-center gap-1.5">
                <Bookmark size={12} className="text-oe-blue" />
                <span className="text-[10px] font-semibold uppercase tracking-wider text-content-tertiary">
                  {t('bim.saved_groups', { defaultValue: 'Saved groups' })}
                </span>
                <span className="text-[10px] text-content-quaternary tabular-nums">
                  {savedGroups.length}
                </span>
              </div>
              {groupsExpanded ? (
                <ChevronDown size={11} className="text-content-tertiary" />
              ) : (
                <ChevronRight size={11} className="text-content-tertiary" />
              )}
            </button>
            {groupsExpanded && (
              <div className="space-y-1">
                {savedGroups.map((g) => {
                  const active = activeGroupId === g.id;
                  return (
                    <div
                      key={g.id}
                      className={`group flex items-center gap-1 px-1.5 py-1 rounded transition-colors ${
                        active
                          ? 'bg-oe-blue/10 border border-oe-blue/40'
                          : 'border border-transparent hover:bg-surface-secondary'
                      }`}
                    >
                      <button
                        type="button"
                        onClick={() => applyGroupAsFilter(g)}
                        className="flex-1 flex items-center gap-1.5 min-w-0 text-left"
                        title={
                          g.description ||
                          t('bim.apply_group_title', {
                            defaultValue: 'Apply this group as a filter',
                          })
                        }
                      >
                        <span
                          className="inline-block h-2 w-2 rounded-full shrink-0"
                          style={{ background: g.color || '#2979ff' }}
                        />
                        <span
                          className={`text-[11px] truncate ${
                            active ? 'font-medium text-oe-blue' : 'text-content-primary'
                          }`}
                        >
                          {g.name}
                        </span>
                        <span className="text-[10px] text-content-quaternary tabular-nums shrink-0 ms-auto">
                          {g.element_count.toLocaleString()}
                        </span>
                      </button>
                      {onLinkGroupToBOQ && (
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation();
                            onLinkGroupToBOQ(g);
                          }}
                          className="opacity-0 group-hover:opacity-100 p-1 rounded text-content-tertiary hover:text-oe-blue hover:bg-surface-primary"
                          title={t('bim.group_link_boq', {
                            defaultValue: 'Link this group to BOQ',
                          })}
                        >
                          <Link2 size={10} />
                        </button>
                      )}
                      {onDeleteGroup && (
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation();
                            onDeleteGroup(g);
                          }}
                          className="opacity-0 group-hover:opacity-100 p-1 rounded text-content-tertiary hover:text-rose-600 hover:bg-rose-50"
                          title={t('bim.group_delete', { defaultValue: 'Delete group' })}
                        >
                          <Trash2 size={10} />
                        </button>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        )}

        {/* Storeys — sorted by parsed level number (B2 → G → 01 → 02 → …)
            with a small level badge on each chip. */}
        <FilterSection
          title={t('bim.filter_storeys', { defaultValue: 'Storeys' })}
          icon={<Layers size={12} />}
          action={
            counts.storeys.length > 0 && state.storeys.size > 0 ? (
              <button
                type="button"
                onClick={() => setState((p) => ({ ...p, storeys: new Set() }))}
                className="text-[10px] text-content-tertiary hover:text-oe-blue"
              >
                {t('bim.filter_all_levels', { defaultValue: 'All levels' })}
              </button>
            ) : null
          }
        >
          {counts.storeys.map((s) => {
            const active = state.storeys.has(s.raw);
            const badge = formatLevelBadge(s.level);
            return (
              <button
                key={s.raw}
                type="button"
                onClick={() => toggleSet('storeys', s.raw)}
                className={`w-full flex items-center gap-2 px-2 py-1 rounded text-[11px] transition-colors ${
                  active
                    ? 'bg-oe-blue/10 text-oe-blue font-medium'
                    : 'text-content-secondary hover:bg-surface-secondary'
                }`}
                title={s.raw}
              >
                <span
                  className={`inline-flex items-center justify-center min-w-[22px] h-[18px] px-1 rounded text-[9px] font-bold tabular-nums ${
                    active
                      ? 'bg-oe-blue text-white'
                      : 'bg-surface-secondary text-content-tertiary border border-border-light'
                  }`}
                >
                  {badge || '·'}
                </span>
                <span className="flex-1 truncate text-left">{s.label}</span>
                <span className="text-[10px] text-content-quaternary tabular-nums shrink-0">
                  {s.count.toLocaleString()}
                </span>
              </button>
            );
          })}
          {counts.storeys.length === 0 && (
            <div className="text-[10px] text-content-quaternary italic">
              {t('bim.filter_no_storeys', { defaultValue: 'No levels detected in this model' })}
            </div>
          )}
        </FilterSection>

        {/* Type filter — three grouping modes:
              By Category   → flat list of every element_type / IfcEntity
              By Type Name  → hierarchical Category → TypeName (Revit Browser)
              Buckets       → semantic buckets (Structure/Envelope/MEP/…)
            The segmented control at the top lets the user pick. */}
        <FilterSection
          title={typesSectionTitle}
          icon={<Package size={12} />}
          action={
            counts.types.length > 0 && state.types.size > 0 ? (
              <button
                type="button"
                onClick={() => setState((p) => ({ ...p, types: new Set() }))}
                className="text-[10px] text-content-tertiary hover:text-oe-blue"
              >
                {t('bim.filter_clear_types', { defaultValue: 'Clear types' })}
              </button>
            ) : null
          }
        >
          {/* Segmented mode picker */}
          <div className="flex items-center gap-0.5 mb-2 p-0.5 rounded bg-surface-secondary border border-border-light">
            {(
              [
                {
                  id: 'category' as const,
                  label: t('bim.group_by_category', { defaultValue: 'Category' }),
                  title: t('bim.group_by_category_title', {
                    defaultValue:
                      'Flat list of every Revit category / IFC entity, sorted by count',
                  }),
                },
                {
                  id: 'typename' as const,
                  label: t('bim.group_by_typename', { defaultValue: 'Type Name' }),
                  title: t('bim.group_by_typename_title', {
                    defaultValue: 'Category → Type Name hierarchy (Revit Browser style)',
                  }),
                },
                {
                  id: 'buckets' as const,
                  label: t('bim.group_by_bucket', { defaultValue: 'Buckets' }),
                  title: t('bim.group_by_bucket_title', {
                    defaultValue: 'Semantic buckets (Structure / Envelope / MEP / …)',
                  }),
                },
              ] as const
            ).map((opt) => (
              <button
                key={opt.id}
                type="button"
                onClick={() => setGroupingMode(opt.id)}
                title={opt.title}
                className={`flex-1 py-0.5 text-[10px] font-medium rounded transition-colors ${
                  groupingMode === opt.id
                    ? 'bg-oe-blue text-white'
                    : 'text-content-tertiary hover:text-content-primary'
                }`}
              >
                {opt.label}
              </button>
            ))}
          </div>

          {/* ── Mode 1: By Category — split into "Building" + "Other" ──
              Universal logic: every category is bucketed via bucketOf()
              and we split by whether the bucket is `noise`. Building
              chips render at top in normal style; annotation/analytical
              chips render below in a collapsed "Other" section so they're
              visible but never crowd out the real building elements.
              Works across every project regardless of which categories
              the source CAD tool emits. */}
          {groupingMode === 'category' && (
            <CategoryFlatList
              types={counts.types}
              activeSet={state.types}
              onToggle={(n) => toggleSet('types', n)}
              t={t}
            />
          )}

          {/* ── Mode 2: By Type Name — Category → Type Name hierarchy ─ */}
          {groupingMode === 'typename' && (
            <div className="space-y-1">
              {counts.categoriesWithTypes.length === 0 ? (
                <div className="text-[10px] text-content-quaternary italic px-1">
                  {t('bim.filter_no_types', { defaultValue: 'No element types detected' })}
                </div>
              ) : (
                counts.categoriesWithTypes.map(({ category, total, types }) => {
                  const isOpen = expandedCategories.has(category);
                  const active = state.types.has(category);
                  return (
                    <div
                      key={category}
                      className="rounded border border-border-light/60 bg-surface-secondary/40"
                    >
                      <div className="flex items-center justify-between gap-1 px-2 py-1">
                        <button
                          type="button"
                          onClick={() =>
                            setExpandedCategories((prev) => {
                              const next = new Set(prev);
                              if (next.has(category)) next.delete(category);
                              else next.add(category);
                              return next;
                            })
                          }
                          className="flex items-center gap-1 min-w-0 flex-1 text-left"
                        >
                          {isOpen ? (
                            <ChevronDown size={11} className="text-content-tertiary shrink-0" />
                          ) : (
                            <ChevronRight size={11} className="text-content-tertiary shrink-0" />
                          )}
                          <span
                            className={`text-[11px] font-semibold truncate ${
                              active ? 'text-oe-blue' : 'text-content-primary'
                            }`}
                            title={category}
                          >
                            {prettifyCategoryName(category)}
                          </span>
                          <span className="text-[10px] text-content-quaternary tabular-nums shrink-0 ms-auto">
                            {total.toLocaleString()}
                          </span>
                        </button>
                        <button
                          type="button"
                          onClick={() => toggleSet('types', category)}
                          className={`text-[10px] px-1.5 py-0.5 rounded shrink-0 ${
                            active
                              ? 'bg-oe-blue text-white'
                              : 'text-content-tertiary hover:text-oe-blue hover:bg-surface-primary'
                          }`}
                          title={
                            active
                              ? t('bim.deselect_category', { defaultValue: 'Deselect category' })
                              : t('bim.select_category', { defaultValue: 'Filter by this category' })
                          }
                        >
                          {active ? '✓' : '+'}
                        </button>
                      </div>
                      {isOpen && (
                        <ul className="px-2 pb-1.5 pt-0.5 space-y-0.5">
                          {types.map(([typeName, count]) => (
                            <li
                              key={typeName}
                              className="flex items-center justify-between gap-1 px-1.5 py-0.5 rounded text-[10px] text-content-secondary hover:bg-surface-primary"
                            >
                              <span className="truncate" title={typeName}>
                                {typeName}
                              </span>
                              <span className="text-content-quaternary tabular-nums shrink-0">
                                {count.toLocaleString()}
                              </span>
                            </li>
                          ))}
                        </ul>
                      )}
                    </div>
                  );
                })
              )}
            </div>
          )}

          {/* ── Mode 3: Buckets — semantic groups ─────────────────────── */}
          {groupingMode === 'buckets' && (
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
                              ? t('bim.filter_bucket_clear', { defaultValue: 'Clear bucket' })
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
                                label={prettifyCategoryName(name)}
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
          )}
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

/**
 * Category flat-list view — splits every category into "Building elements"
 * (real things you'd estimate) and "Annotations & analytical" (drafting +
 * analytical-model junk).  Universal: works for any project because the
 * split is driven by `bucketOf()` which classifies every category by its
 * semantic bucket (building vs noise).
 *
 * The Other section is collapsible and starts collapsed so first-time
 * users see only real building categories without the panel exploding
 * with 100+ Revit annotation rows.
 */
function CategoryFlatList({
  types,
  activeSet,
  onToggle,
  t,
}: {
  types: Array<[string, number]>;
  activeSet: Set<string>;
  onToggle: (name: string) => void;
  t: ReturnType<typeof useTranslation>['t'];
}) {
  const [otherExpanded, setOtherExpanded] = useState(false);

  // Universal split via bucketOf — works for any project's category set
  const building: Array<[string, number]> = [];
  const other: Array<[string, number]> = [];
  for (const entry of types) {
    if (BUCKETS[bucketOf(entry[0])].noise) other.push(entry);
    else building.push(entry);
  }

  if (types.length === 0) {
    return (
      <div className="text-[10px] text-content-quaternary italic px-1">
        {t('bim.filter_no_types', { defaultValue: 'No element types detected' })}
      </div>
    );
  }

  return (
    <div className="space-y-1">
      {/* Building elements — real categories */}
      {building.length > 0 && (
        <div className="space-y-0.5">
          {building.map(([name, count]) => {
            const active = activeSet.has(name);
            return (
              <FilterChip
                key={name}
                label={prettifyCategoryName(name)}
                count={count}
                active={active}
                onClick={() => onToggle(name)}
              />
            );
          })}
        </div>
      )}

      {/* Annotations & analytical — collapsible, de-emphasised */}
      {other.length > 0 && (
        <div className="rounded border border-border-light/50 bg-surface-secondary/30">
          <button
            type="button"
            onClick={() => setOtherExpanded((v) => !v)}
            className="w-full flex items-center justify-between px-2 py-1 text-left"
          >
            <div className="flex items-center gap-1.5">
              {otherExpanded ? (
                <ChevronDown size={11} className="text-content-tertiary" />
              ) : (
                <ChevronRight size={11} className="text-content-tertiary" />
              )}
              <span className="text-[10px] font-medium text-content-tertiary uppercase tracking-wider">
                {t('bim.category_annotations_analytical', {
                  defaultValue: 'Annotations & analytical',
                })}
              </span>
            </div>
            <span className="text-[10px] text-content-quaternary tabular-nums">
              {other.reduce((s, [, c]) => s + c, 0).toLocaleString()}
            </span>
          </button>
          {otherExpanded && (
            <div className="px-1 pb-1 space-y-0.5">
              {other.map(([name, count]) => {
                const active = activeSet.has(name);
                return (
                  <FilterChip
                    key={name}
                    label={prettifyCategoryName(name)}
                    count={count}
                    active={active}
                    onClick={() => onToggle(name)}
                  />
                );
              })}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function FilterSection({
  title,
  icon,
  children,
  action,
}: {
  title: string;
  icon: React.ReactNode;
  children: React.ReactNode;
  action?: React.ReactNode;
}) {
  return (
    <div className="border-b border-border-light py-3 px-4">
      <div className="flex items-center justify-between gap-1.5 mb-2">
        <div className="flex items-center gap-1.5">
          <span className="text-content-tertiary">{icon}</span>
          <span className="text-[10px] font-semibold uppercase tracking-wider text-content-tertiary">
            {title}
          </span>
        </div>
        {action}
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
