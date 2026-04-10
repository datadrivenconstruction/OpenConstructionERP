/**
 * BIMFilterPanel — fast element filter + group sidebar for the BIM viewer.
 *
 * Supports:
 * - Free-text search across name / type / family
 * - Discipline toggles (architecture / structural / mep / other)
 * - Storey/level multi-select
 * - Element type tree (categories like Walls, Doors, PipeFitting)
 * - Group-by selector (discipline / storey / type)
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
  Building2,
  Package,
  ChevronRight,
  ChevronDown,
  Eye,
  EyeOff,
  X,
} from 'lucide-react';
import type { BIMElementData } from '@/shared/ui/BIMViewer';

// ── Types ────────────────────────────────────────────────────────────────

export type GroupBy = 'discipline' | 'storey' | 'type';

export interface BIMFilterState {
  search: string;
  disciplines: Set<string>; // empty = show all
  storeys: Set<string>; // empty = show all
  types: Set<string>; // empty = show all
  groupBy: GroupBy;
}

interface BIMFilterPanelProps {
  elements: BIMElementData[];
  onFilterChange: (
    predicate: (el: BIMElementData) => boolean,
    visibleCount: number,
  ) => void;
  onClose?: () => void;
  onElementClick?: (elementId: string) => void;
}

const DISCIPLINE_COLORS: Record<string, string> = {
  architecture: '#3b82f6',
  structural: '#f97316',
  mep: '#10b981',
  other: '#6b7280',
};

// ── Component ────────────────────────────────────────────────────────────

export default function BIMFilterPanel({
  elements,
  onFilterChange,
  onClose,
  onElementClick,
}: BIMFilterPanelProps) {
  const { t } = useTranslation();

  const [state, setState] = useState<BIMFilterState>({
    search: '',
    disciplines: new Set(),
    storeys: new Set(),
    types: new Set(),
    groupBy: 'discipline',
  });

  const [expandedGroups, setExpandedGroups] = useState<Set<string>>(new Set());

  // ── Derived: counts per dimension ──────────────────────────────────
  const counts = useMemo(() => {
    const byDiscipline = new Map<string, number>();
    const byStorey = new Map<string, number>();
    const byType = new Map<string, number>();

    for (const el of elements) {
      const d = el.discipline || 'other';
      byDiscipline.set(d, (byDiscipline.get(d) ?? 0) + 1);

      const s = el.storey || '—';
      byStorey.set(s, (byStorey.get(s) ?? 0) + 1);

      const tpe = el.element_type || 'Unknown';
      byType.set(tpe, (byType.get(tpe) ?? 0) + 1);
    }

    return {
      disciplines: Array.from(byDiscipline.entries()).sort((a, b) => b[1] - a[1]),
      storeys: Array.from(byStorey.entries()).sort((a, b) => a[0].localeCompare(b[0])),
      types: Array.from(byType.entries()).sort((a, b) => b[1] - a[1]),
    };
  }, [elements]);

  // ── Filter predicate ───────────────────────────────────────────────
  const applyFilters = useCallback(
    (s: BIMFilterState) => {
      const search = s.search.trim().toLowerCase();
      const predicate = (el: BIMElementData): boolean => {
        // Discipline filter (empty set = show all)
        if (s.disciplines.size > 0) {
          if (!s.disciplines.has(el.discipline || 'other')) return false;
        }
        // Storey filter
        if (s.storeys.size > 0) {
          if (!s.storeys.has(el.storey || '—')) return false;
        }
        // Type filter
        if (s.types.size > 0) {
          if (!s.types.has(el.element_type || 'Unknown')) return false;
        }
        // Search
        if (search) {
          const hay = (
            (el.name || '') +
            ' ' +
            (el.element_type || '') +
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
    [elements, onFilterChange],
  );

  // Re-apply whenever state changes
  useEffect(() => {
    applyFilters(state);
  }, [state, applyFilters]);

  // ── Handlers ───────────────────────────────────────────────────────
  const toggleSet = useCallback(
    (key: 'disciplines' | 'storeys' | 'types', value: string) => {
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
      disciplines: new Set(),
      storeys: new Set(),
      types: new Set(),
    }));
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
    state.search.length > 0 ||
    state.disciplines.size > 0 ||
    state.storeys.size > 0 ||
    state.types.size > 0;

  // ── Grouped element tree (for element explorer) ─────────────────────
  const visibleElements = useMemo(() => {
    const search = state.search.trim().toLowerCase();
    return elements.filter((el) => {
      if (state.disciplines.size > 0 && !state.disciplines.has(el.discipline || 'other')) return false;
      if (state.storeys.size > 0 && !state.storeys.has(el.storey || '—')) return false;
      if (state.types.size > 0 && !state.types.has(el.element_type || 'Unknown')) return false;
      if (search) {
        const hay = ((el.name || '') + ' ' + (el.element_type || '')).toLowerCase();
        if (!hay.includes(search)) return false;
      }
      return true;
    });
  }, [elements, state]);

  const groupedElements = useMemo(() => {
    const groups = new Map<string, BIMElementData[]>();
    for (const el of visibleElements) {
      let key: string;
      switch (state.groupBy) {
        case 'storey':
          key = el.storey || '—';
          break;
        case 'type':
          key = el.element_type || 'Unknown';
          break;
        default:
          key = el.discipline || 'other';
      }
      const arr = groups.get(key);
      if (arr) arr.push(el);
      else groups.set(key, [el]);
    }
    // Sort groups by size (biggest first)
    return Array.from(groups.entries()).sort((a, b) => b[1].length - a[1].length);
  }, [visibleElements, state.groupBy]);

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
            placeholder={t('bim.filter_search_placeholder', { defaultValue: 'Search name, type, storey…' })}
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
            <button
              onClick={clearAll}
              className="text-oe-blue hover:underline"
            >
              {t('bim.filter_clear', { defaultValue: 'Clear all' })}
            </button>
          )}
        </div>
      </div>

      {/* Scroll area: Disciplines + Storeys + Types */}
      <div className="flex-1 overflow-y-auto">
        {/* Disciplines */}
        <FilterSection
          title={t('bim.filter_disciplines', { defaultValue: 'Disciplines' })}
          icon={<Building2 size={12} />}
        >
          {counts.disciplines.map(([name, count]) => {
            const active = state.disciplines.has(name);
            const color = DISCIPLINE_COLORS[name] || DISCIPLINE_COLORS.other;
            return (
              <FilterChip
                key={name}
                label={name}
                count={count}
                active={active}
                color={color}
                onClick={() => toggleSet('disciplines', name)}
              />
            );
          })}
        </FilterSection>

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
        </FilterSection>

        {/* Types (scrollable if many) */}
        <FilterSection
          title={t('bim.filter_types', { defaultValue: 'Element Types' })}
          icon={<Package size={12} />}
        >
          <div className="max-h-64 overflow-y-auto pe-1 space-y-1">
            {counts.types.map(([name, count]) => {
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
              <option value="discipline">{t('bim.filter_group_discipline', { defaultValue: 'by Discipline' })}</option>
              <option value="storey">{t('bim.filter_group_storey', { defaultValue: 'by Storey' })}</option>
              <option value="type">{t('bim.filter_group_type', { defaultValue: 'by Type' })}</option>
            </select>
          </div>

          {/* Virtual-ish list: only render first 500 items per group when expanded */}
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
                        <ChevronDown size={12} className="text-content-tertiary shrink-0" />
                      ) : (
                        <ChevronRight size={12} className="text-content-tertiary shrink-0" />
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
                {t('bim.filter_no_results', { defaultValue: 'No elements match filters' })}
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
  color,
  onClick,
}: {
  label: string;
  count: number;
  active: boolean;
  color?: string;
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
        {color && (
          <span
            className="w-2 h-2 rounded-full shrink-0"
            style={{ background: color }}
          />
        )}
        {active ? (
          <Eye size={10} className="shrink-0" />
        ) : (
          <EyeOff size={10} className="shrink-0 opacity-40" />
        )}
        <span className="truncate capitalize">{label}</span>
      </div>
      <span className="text-[10px] text-content-quaternary tabular-nums shrink-0">
        {count.toLocaleString()}
      </span>
    </button>
  );
}
