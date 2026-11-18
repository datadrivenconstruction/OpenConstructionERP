// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction

import { useEffect, useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import clsx from 'clsx';
import { Loader2, Search } from 'lucide-react';
import { fmtNumber } from '@/shared/lib/formatters';
import { fetchBoqResources, fetchProjectBoqs, type BoqResourceOption } from './api';

type Translate = (k: string, o?: Record<string, unknown>) => string;

/** Category label, reusing the BOQ editor's resource type names. */
export function categoryLabel(category: string, t: Translate): string {
  if (category === 'machinery') {
    return t('rfq_bidding.category_machinery', { defaultValue: 'Machinery' });
  }
  const fallback = category.charAt(0).toUpperCase() + category.slice(1);
  return t(`boq.resource_type_${category}`, { defaultValue: fallback });
}

/**
 * Pick the BOQ resources an RFQ asks suppliers to price: one BOQ, a category
 * filter, a search, and checkboxes. Quantities are the BOQ totals; the server
 * recomputes them from the keys, so what is shown here is what gets created.
 */
export function BoqResourcePicker({
  projectId,
  boqId,
  onBoqChange,
  selected,
  onSelectedChange,
  t,
}: {
  projectId: string;
  boqId: string;
  onBoqChange: (boqId: string) => void;
  selected: Set<string>;
  onSelectedChange: (next: Set<string>) => void;
  t: Translate;
}) {
  const [category, setCategory] = useState<string>('');
  const [search, setSearch] = useState('');

  const { data: boqs = [], isLoading: boqsLoading } = useQuery({
    queryKey: ['rfq-bidding', 'boqs', projectId],
    queryFn: () => fetchProjectBoqs(projectId),
    enabled: !!projectId,
    staleTime: 60_000,
  });

  // One BOQ is the usual case: take it without asking.
  useEffect(() => {
    if (!boqId && boqs.length > 0) onBoqChange(boqs[0]!.id);
  }, [boqId, boqs, onBoqChange]);

  const { data: resources = [], isLoading: resourcesLoading } = useQuery({
    queryKey: ['rfq-bidding', 'boq-resources', boqId],
    queryFn: () => fetchBoqResources(boqId),
    enabled: !!boqId,
    staleTime: 30_000,
  });

  const categoryCounts = useMemo(() => {
    const counts = new Map<string, number>();
    for (const r of resources) counts.set(r.category, (counts.get(r.category) ?? 0) + 1);
    return counts;
  }, [resources]);

  const shown = useMemo(() => {
    const q = search.trim().toLowerCase();
    return resources.filter(
      (r: BoqResourceOption) =>
        (!category || r.category === category) &&
        (!q || r.name.toLowerCase().includes(q) || (r.code ?? '').toLowerCase().includes(q)),
    );
  }, [resources, category, search]);

  const toggle = (key: string) => {
    const next = new Set(selected);
    if (next.has(key)) next.delete(key);
    else next.add(key);
    onSelectedChange(next);
  };

  const selectShown = () => {
    const next = new Set(selected);
    for (const r of shown) next.add(r.key);
    onSelectedChange(next);
  };

  if (boqsLoading) {
    return (
      <div className="flex items-center gap-2 text-sm text-content-tertiary">
        <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
        {t('rfq_bidding.boq_loading', { defaultValue: 'Loading resources...' })}
      </div>
    );
  }

  if (boqs.length === 0) {
    return (
      <p className="text-sm text-content-tertiary">
        {t('rfq_bidding.boq_none', { defaultValue: 'This project has no BOQ yet.' })}
      </p>
    );
  }

  return (
    <div className="space-y-2">
      {boqs.length > 1 && (
        <div>
          <label htmlFor="rfq-boq-select" className="oe-label">
            {t('rfq_bidding.boq_select_label', { defaultValue: 'BOQ' })}
          </label>
          <select
            id="rfq-boq-select"
            value={boqId}
            onChange={(e) => {
              onBoqChange(e.target.value);
              onSelectedChange(new Set());
              setCategory('');
            }}
            className="oe-input"
          >
            {boqs.map((b) => (
              <option key={b.id} value={b.id}>
                {b.name}
              </option>
            ))}
          </select>
        </div>
      )}

      {resourcesLoading ? (
        <div className="flex items-center gap-2 text-sm text-content-tertiary">
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
          {t('rfq_bidding.boq_loading', { defaultValue: 'Loading resources...' })}
        </div>
      ) : resources.length === 0 ? (
        <p className="text-sm text-content-tertiary">
          {t('rfq_bidding.boq_resources_empty', {
            defaultValue:
              'This BOQ has no resources yet. Add resources to its positions in the BOQ editor, or start with an empty scope.',
          })}
        </p>
      ) : (
        <>
          <div className="flex flex-wrap gap-1" role="group" aria-label={t('rfq_bidding.boq_filter_label', { defaultValue: 'Resource category' })}>
            {['', ...categoryCounts.keys()].map((c) => (
              <button
                key={c || 'all'}
                type="button"
                aria-pressed={category === c}
                onClick={() => setCategory(c)}
                className={clsx(
                  'rounded-full border px-2.5 py-0.5 text-xs',
                  category === c
                    ? 'border-oe-blue bg-oe-blue/10 text-oe-blue'
                    : 'border-border-light text-content-secondary hover:bg-surface-secondary',
                )}
              >
                {c ? categoryLabel(c, t) : t('rfq_bidding.boq_filter_all', { defaultValue: 'All' })} (
                {c ? categoryCounts.get(c) : resources.length})
              </button>
            ))}
          </div>

          <div className="relative">
            <Search className="pointer-events-none absolute left-2.5 top-2.5 h-4 w-4 text-content-tertiary" aria-hidden />
            <input
              type="search"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder={t('rfq_bidding.boq_resources_search', { defaultValue: 'Search by name or code' })}
              aria-label={t('rfq_bidding.boq_resources_search', { defaultValue: 'Search by name or code' })}
              className="oe-input pl-8"
            />
          </div>

          <div className="flex items-center justify-between text-xs">
            <span className="text-content-secondary" data-testid="rfq-boq-selected-count">
              {t('rfq_bidding.boq_selected_count', { defaultValue: 'Selected: {{count}}', count: selected.size })}
            </span>
            <span className="flex gap-2">
              <button type="button" onClick={selectShown} className="text-oe-blue hover:underline" disabled={shown.length === 0}>
                {t('rfq_bidding.boq_select_shown', { defaultValue: 'Select all shown' })}
              </button>
              <button
                type="button"
                onClick={() => onSelectedChange(new Set())}
                className="text-content-tertiary hover:underline"
                disabled={selected.size === 0}
              >
                {t('rfq_bidding.boq_clear_selection', { defaultValue: 'Clear' })}
              </button>
            </span>
          </div>

          <ul className="max-h-64 divide-y divide-border-light overflow-y-auto rounded-lg border border-border-light">
            {shown.length === 0 && (
              <li className="px-3 py-2 text-sm text-content-tertiary">
                {t('rfq_bidding.boq_no_match', { defaultValue: 'No resources match the filter.' })}
              </li>
            )}
            {shown.map((r) => (
              <li key={r.key}>
                <label className="flex cursor-pointer items-start gap-2 px-3 py-2 text-sm hover:bg-surface-secondary">
                  <input
                    type="checkbox"
                    className="mt-0.5"
                    checked={selected.has(r.key)}
                    onChange={() => toggle(r.key)}
                  />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-content-primary">{r.name}</span>
                    <span className="block text-xs text-content-tertiary">
                      {categoryLabel(r.category, t)}
                      {r.code ? ` · ${r.code}` : ''}
                      {' · '}
                      {t('rfq_bidding.boq_used_in', { defaultValue: 'Positions: {{count}}', count: r.position_count })}
                    </span>
                  </span>
                  <span className="shrink-0 tabular-nums text-content-secondary">
                    {fmtNumber(r.quantity, 2)} {r.unit}
                  </span>
                </label>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}
