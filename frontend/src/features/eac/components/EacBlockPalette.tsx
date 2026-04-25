/**
 * `<EacBlockPalette>` — categorized list of available blocks.
 *
 * Width: 220 px, collapsible. Categories per spec FR-3.1: Selectors, Logic,
 * Triplet, Attributes, Constraints, Variables, Templates.
 *
 * Filtering is local (no server roundtrip) — the palette catalog is small
 * enough that substring matching is fine. The search input is debounced via
 * React's controlled state; we don't need an external debounce because filter
 * cost is O(n) over a few dozen items.
 */
import clsx from 'clsx';
import { ChevronLeft, ChevronRight, Search } from 'lucide-react';
import { useMemo, useState } from 'react';

import { DraggablePaletteItem, type PaletteItem } from './DraggablePaletteItem';
import type { PaletteCategory } from '../types';

/** Title shown above each category section. */
const CATEGORY_TITLES: Record<PaletteCategory, string> = {
  selectors: 'Selectors',
  logic: 'Logic',
  triplet: 'Triplet',
  attributes: 'Attributes',
  constraints: 'Constraints',
  variables: 'Variables',
  templates: 'Templates',
};

/** Default catalog — used when the host doesn't pass an override. */
export const DEFAULT_PALETTE_CATALOG: Record<PaletteCategory, PaletteItem[]> = {
  selectors: [
    {
      id: 'selector.ifc_class',
      color: 'selector',
      label: 'IFC class',
      description: 'Match by IFC entity name',
      payload: { type: 'ifc_class' },
    },
    {
      id: 'selector.category',
      color: 'selector',
      label: 'Category',
      description: 'Match by Revit category',
      payload: { type: 'category' },
    },
    {
      id: 'selector.classification',
      color: 'selector',
      label: 'Classification',
      description: 'Match by Uniformat / DIN / NRM',
      payload: { type: 'classification' },
    },
    {
      id: 'selector.spatial',
      color: 'selector',
      label: 'Spatial',
      description: 'Level, zone, or room',
      payload: { type: 'spatial' },
    },
  ],
  logic: [
    { id: 'logic.and', color: 'logic', label: 'AND', payload: { type: 'and' } },
    { id: 'logic.or', color: 'logic', label: 'OR', payload: { type: 'or' } },
    { id: 'logic.not', color: 'logic', label: 'NOT', payload: { type: 'not' } },
  ],
  triplet: [
    {
      id: 'triplet.attr_constraint',
      color: 'attribute',
      label: 'Attribute + constraint',
      description: 'Pair a property with a comparison',
      payload: { type: 'triplet' },
    },
  ],
  attributes: [
    {
      id: 'attr.exact',
      color: 'attribute',
      label: 'Property',
      description: 'pset.name reference',
      payload: { kind: 'exact' },
    },
    {
      id: 'attr.alias',
      color: 'attribute',
      label: 'Alias',
      description: 'Resolved through synonyms',
      payload: { kind: 'alias' },
    },
    {
      id: 'attr.regex',
      color: 'attribute',
      label: 'Regex',
      description: 'Match property name pattern',
      payload: { kind: 'regex' },
    },
  ],
  constraints: [
    { id: 'constraint.eq', color: 'constraint', label: 'Equals (=)', payload: { operator: 'eq' } },
    {
      id: 'constraint.gte',
      color: 'constraint',
      label: 'Greater or equal (≥)',
      payload: { operator: 'gte' },
    },
    {
      id: 'constraint.between',
      color: 'constraint',
      label: 'Between',
      payload: { operator: 'between' },
    },
    {
      id: 'constraint.in',
      color: 'constraint',
      label: 'In set',
      payload: { operator: 'in' },
    },
    {
      id: 'constraint.matches',
      color: 'constraint',
      label: 'Regex match',
      payload: { operator: 'matches' },
    },
  ],
  variables: [
    {
      id: 'variable.local',
      color: 'variable',
      label: 'Local variable',
      description: 'Sum, avg, count, min, max, …',
      payload: { scope: 'local' },
    },
  ],
  templates: [
    {
      id: 'template.external_walls',
      color: 'selector',
      label: 'External walls thickness',
      description: 'Selector + triplet + constraint',
      payload: { template: 'external_walls' },
    },
  ],
};

const CATEGORY_ORDER: PaletteCategory[] = [
  'selectors',
  'logic',
  'triplet',
  'attributes',
  'constraints',
  'variables',
  'templates',
];

export interface EacBlockPaletteProps {
  /** Override the default catalog if the host wants to inject custom blocks. */
  catalog?: Record<PaletteCategory, PaletteItem[]>;
  /** Initial collapsed state. */
  collapsed?: boolean;
  /**
   * Activate handler — fired when the user clicks (not drags) a palette item.
   * The canvas can listen here to insert a block at the default position
   * for non-drag interactions.
   */
  onActivate?: (item: PaletteItem) => void;
  /** Test id override. */
  testId?: string;
}

export function EacBlockPalette({
  catalog = DEFAULT_PALETTE_CATALOG,
  collapsed: collapsedProp = false,
  onActivate,
  testId,
}: EacBlockPaletteProps) {
  const [query, setQuery] = useState('');
  const [collapsed, setCollapsed] = useState(collapsedProp);

  const filteredCategories = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    if (!normalized) return catalog;

    const result: Record<PaletteCategory, PaletteItem[]> = {
      selectors: [],
      logic: [],
      triplet: [],
      attributes: [],
      constraints: [],
      variables: [],
      templates: [],
    };
    for (const category of CATEGORY_ORDER) {
      result[category] = (catalog[category] ?? []).filter(
        (item) =>
          item.label.toLowerCase().includes(normalized) ||
          (item.description?.toLowerCase().includes(normalized) ?? false),
      );
    }
    return result;
  }, [catalog, query]);

  if (collapsed) {
    return (
      <aside
        data-testid={testId ?? 'eac-block-palette'}
        data-collapsed="true"
        className={clsx(
          'flex h-full w-10 shrink-0 flex-col items-center border-r border-border bg-surface-secondary py-2',
        )}
      >
        <button
          type="button"
          aria-label="Expand palette"
          onClick={() => setCollapsed(false)}
          className="flex h-8 w-8 items-center justify-center rounded-md hover:bg-surface-tertiary"
        >
          <ChevronRight size={16} aria-hidden="true" />
        </button>
      </aside>
    );
  }

  const totalItems = Object.values(filteredCategories).reduce(
    (sum, items) => sum + items.length,
    0,
  );

  return (
    <aside
      data-testid={testId ?? 'eac-block-palette'}
      data-collapsed="false"
      className={clsx(
        'flex h-full w-[220px] shrink-0 flex-col border-r border-border bg-surface-secondary',
      )}
      aria-label="Block palette"
    >
      <header className="flex items-center justify-between gap-2 border-b border-border px-3 py-2">
        <span className="text-xs font-semibold uppercase tracking-wide text-content-secondary">
          Blocks
        </span>
        <button
          type="button"
          aria-label="Collapse palette"
          onClick={() => setCollapsed(true)}
          className="flex h-6 w-6 items-center justify-center rounded hover:bg-surface-tertiary"
        >
          <ChevronLeft size={14} aria-hidden="true" />
        </button>
      </header>
      <div className="px-3 py-2">
        <label className="relative block">
          <span className="sr-only">Search blocks</span>
          <Search
            size={14}
            aria-hidden="true"
            className="pointer-events-none absolute left-2 top-1/2 -translate-y-1/2 text-content-tertiary"
          />
          <input
            type="search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search…"
            data-testid="eac-palette-search"
            className={clsx(
              'h-8 w-full rounded-md border border-border bg-surface-primary pl-7 pr-2 text-sm',
              'placeholder:text-content-tertiary',
              'focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue',
            )}
          />
        </label>
      </div>
      <div className="flex-1 overflow-y-auto px-2 pb-3">
        {totalItems === 0 ? (
          <p
            data-testid="eac-palette-empty"
            className="px-2 py-4 text-center text-xs text-content-tertiary"
          >
            No blocks match "{query}"
          </p>
        ) : (
          CATEGORY_ORDER.map((category) => {
            const items = filteredCategories[category];
            if (!items.length) return null;
            return (
              <section
                key={category}
                data-testid={`eac-palette-category-${category}`}
                className="mt-2 first:mt-0"
              >
                <h3 className="mb-1 px-1 text-2xs font-semibold uppercase tracking-wide text-content-tertiary">
                  {CATEGORY_TITLES[category]}
                </h3>
                <div className="flex flex-col gap-1">
                  {items.map((item) => (
                    <DraggablePaletteItem
                      key={item.id}
                      item={item}
                      onActivate={onActivate}
                    />
                  ))}
                </div>
              </section>
            );
          })
        )}
      </div>
    </aside>
  );
}
