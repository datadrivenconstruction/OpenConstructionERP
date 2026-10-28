// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// "By resources" - the reverse lookup. Give the resources you know (a material,
// a labour trade, a plant item) and see the priced works that consume them,
// ranked by how much of your set they cover and how much of the rate those
// resources drive.

import { useEffect, useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { ChevronDown, ChevronRight, GitCompareArrows, Repeat2, X } from 'lucide-react';
import { Badge, Button, EmptyState, ErrorState } from '@/shared/ui';
import { getErrorMessage } from '@/shared/lib/api';
import { findByResources, type ByResourcesMatch, type CatalogResource } from './api';
import { ResourceSearchInput } from './ResourceSearchInput';
import { fmtMoney, MetaLine, Meter, pct } from './parts';
import { BaseScopeNote, BaseSelect } from './BasePicker';
import { RowEstimateActions } from './RowEstimateActions';
import type { CrossNav } from './types';
import { fmtList } from '@/shared/lib/formatters';

interface Picked {
  code: string;
  name: string;
  /** Kept as a raw string so decimals like "1.5" can be typed without the
   * controlled input coercing mid-entry; parsed to a number only on search. */
  weight: string;
}

export function ByResourcesPanel({ nav }: { nav: CrossNav }) {
  const { t } = useTranslation();
  const [region, setRegion] = useState('');
  const [picked, setPicked] = useState<Picked[]>([]);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  const search = useMutation({
    mutationFn: () =>
      findByResources({
        region: region || null,
        resources: picked.map((p) => ({ code: p.code, weight: Math.max(0, Number(p.weight) || 0) })),
        limit: 50,
      }),
  });

  // Results describe the resource set AND region at the time of the search;
  // clear them the moment either changes (chip added/removed/reweighted, "Clear
  // all", or a different price-base region) so stale rows and the "no works"
  // message never linger over a query that no longer matches the controls.
  const { reset: resetSearch } = search;
  useEffect(() => {
    resetSearch();
    setExpanded(new Set());
  }, [picked, region, resetSearch]);

  function addResource(r: CatalogResource) {
    setPicked((prev) =>
      prev.some((p) => p.code === r.resource_code)
        ? prev
        : [...prev, { code: r.resource_code, name: r.name || r.resource_code, weight: '1' }],
    );
  }

  function toggleExpand(id: string) {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  const canSearch = picked.length > 0;
  const results = search.data?.results ?? [];

  return (
    <div className="space-y-4">
      <div className="grid gap-3 md:grid-cols-[1fr_220px]">
        <div>
          <label htmlFor="ce-byres-resource" className="mb-1.5 block text-sm font-medium text-content-primary">
            {t('costExplorer.byResources.addLabel', { defaultValue: 'Resources you know' })}
          </label>
          <ResourceSearchInput id="ce-byres-resource" onPick={addResource} region={region || null} excludeCodes={picked.map((p) => p.code)} />
        </div>
        <div>
          <label htmlFor="ce-byres-region" className="mb-1.5 block text-sm font-medium text-content-primary">
            {t('costExplorer.region.label', { defaultValue: 'Price base region' })}
          </label>
          <BaseSelect id="ce-byres-region" value={region} onChange={setRegion} />
        </div>
      </div>

      <BaseScopeNote value={region} />

      {picked.length > 0 && (
        <div className="space-y-2">
          {picked.map((p) => (
            <div key={p.code} className="flex items-center gap-3 rounded-lg border border-border-light bg-surface-secondary px-3 py-2">
              <div className="min-w-0 flex-1">
                <div className="truncate text-sm font-medium text-content-primary">{p.name}</div>
                <div className="truncate text-xs text-content-tertiary">{p.code}</div>
              </div>
              <div className="flex items-center gap-1.5">
                <label className="text-xs text-content-tertiary" htmlFor={`w-${p.code}`}>
                  {t('costExplorer.byResources.weight', { defaultValue: 'Weight' })}
                </label>
                <input
                  id={`w-${p.code}`}
                  type="number"
                  min={0}
                  step={0.5}
                  value={p.weight}
                  onChange={(e) =>
                    setPicked((prev) => prev.map((x) => (x.code === p.code ? { ...x, weight: e.target.value } : x)))
                  }
                  className="h-8 w-16 rounded-md border border-border bg-surface-primary px-2 text-sm tabular-nums text-content-primary focus:border-oe-blue focus:outline-none focus:ring-2 focus:ring-oe-blue/30"
                />
              </div>
              <button
                type="button"
                onClick={() => setPicked((prev) => prev.filter((x) => x.code !== p.code))}
                className="text-content-tertiary hover:text-semantic-error"
                aria-label={t('common.remove', { defaultValue: 'Remove' })}
              >
                <X className="h-4 w-4" />
              </button>
            </div>
          ))}
        </div>
      )}

      <div className="flex items-center gap-3">
        <Button onClick={() => search.mutate()} disabled={!canSearch || search.isPending}>
          {search.isPending
            ? t('common.searching', { defaultValue: 'Searching...' })
            : t('costExplorer.byResources.find', { defaultValue: 'Find works' })}
        </Button>
        {picked.length > 0 && (
          <button
            type="button"
            onClick={() => setPicked([])}
            className="text-sm text-content-tertiary hover:text-content-secondary"
          >
            {t('common.clearAll', { defaultValue: 'Clear all' })}
          </button>
        )}
      </div>

      {search.isError && <ErrorState title={getErrorMessage(search.error)} onRetry={() => search.mutate()} />}

      {search.isSuccess && results.length === 0 && (
        <EmptyState
          title={t('costExplorer.byResources.emptyTitle', { defaultValue: 'No works use these resources' })}
          description={t('costExplorer.byResources.emptyBody', {
            defaultValue: 'Try fewer resources, a different region, or rebuild the index if this base was just loaded.',
          })}
        />
      )}

      {results.length > 0 && (
        <div className="space-y-2">
          <div className="text-xs text-content-tertiary">
            {t('costExplorer.byResources.count', {
              defaultValue: '{{count}} works, best coverage first',
              count: results.length,
            })}
          </div>
          {results.map((row, i) => (
            <ResultRow
              key={row.cost_item_id}
              row={row}
              rank={i + 1}
              expanded={expanded.has(row.cost_item_id)}
              onToggle={() => toggleExpand(row.cost_item_id)}
              nav={nav}
            />
          ))}
        </div>
      )}

      {!search.data && !search.isPending && picked.length === 0 && (
        <EmptyState
          title={t('costExplorer.byResources.startTitle', { defaultValue: 'Start from what you know' })}
          description={t('costExplorer.byResources.startBody', {
            defaultValue: 'Add one or more resources above. Cost Explorer finds the priced works that consume them.',
          })}
        />
      )}
    </div>
  );
}

function ResultRow({
  row,
  rank,
  expanded,
  onToggle,
  nav,
}: {
  row: ByResourcesMatch;
  rank: number;
  expanded: boolean;
  onToggle: () => void;
  nav: CrossNav;
}) {
  const { t } = useTranslation();
  // Defensive: a drifted/partial API response should never crash the whole list.
  const matched = row.matched ?? [];
  const missing = row.missing_codes ?? [];
  return (
    <div className="rounded-lg border border-border-light bg-surface-primary">
      <div className="flex items-start gap-3 p-3">
        <div className="w-5 shrink-0 pt-0.5 text-xs tabular-nums text-content-tertiary">{rank}</div>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-medium text-content-primary">{row.code}</span>
            {row.region && <Badge>{row.region}</Badge>}
          </div>
          <p className="mt-0.5 line-clamp-2 text-sm text-content-secondary">{row.description || '-'}</p>
          <div className="mt-1">
            <MetaLine parts={[row.unit, row.source]} />
          </div>
          <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1.5">
            <Meter value={row.coverage} tone="green" label={`${t('costExplorer.byResources.coverage', { defaultValue: 'Coverage' })} ${pct(row.coverage)}`} />
            <Meter value={row.cost_weight} tone="blue" label={`${t('costExplorer.byResources.costShare', { defaultValue: 'Cost share' })} ${pct(row.cost_weight)}`} />
            <Meter value={row.score} tone="amber" label={`${t('costExplorer.byResources.match', { defaultValue: 'Match' })} ${pct(row.score)}`} />
          </div>
        </div>
        <div className="shrink-0 text-right">
          <div className="font-semibold tabular-nums text-content-primary">{fmtMoney(row.rate, row.currency)}</div>
          <div className="mt-2 flex flex-col items-end gap-1">
            <button type="button" onClick={() => nav.openCompare(row.code)} className="inline-flex items-center gap-1 text-xs text-oe-blue hover:underline">
              <GitCompareArrows className="h-3.5 w-3.5" /> {t('costExplorer.actions.compare', { defaultValue: 'Compare bases' })}
            </button>
            <button
              type="button"
              onClick={() =>
                nav.openSubstitute({
                  cost_item_id: row.cost_item_id,
                  code: row.code,
                  description: row.description,
                  unit: row.unit,
                  region: row.region,
                  currency: row.currency,
                  candidates: matched.map((m) => ({ code: m.code, name: m.name })),
                  resource_code: matched[0]?.code,
                  resource_name: matched[0]?.name,
                })
              }
              className="inline-flex items-center gap-1 text-xs text-oe-blue hover:underline"
            >
              <Repeat2 className="h-3.5 w-3.5" /> {t('costExplorer.actions.substitute', { defaultValue: 'Substitute' })}
            </button>
            <RowEstimateActions
              row={{
                cost_item_id: row.cost_item_id,
                code: row.code,
                description: row.description,
                unit: row.unit,
                rate: row.rate,
                currency: row.currency,
                region: row.region,
              }}
            />
          </div>
        </div>
      </div>
      <button
        type="button"
        onClick={onToggle}
        className="flex w-full items-center gap-1 border-t border-border-light px-3 py-1.5 text-xs text-content-tertiary hover:bg-surface-secondary"
        aria-expanded={expanded}
      >
        {expanded ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
        {t('costExplorer.byResources.matched', {
          defaultValue: '{{n}} matched, {{m}} missing',
          n: matched.length,
          m: missing.length,
        })}
      </button>
      {expanded && (
        <div className="space-y-2 border-t border-border-light bg-surface-secondary px-3 py-2.5">
          {matched.map((m) => (
            <div key={m.code} className="flex items-center justify-between gap-3 text-sm">
              <span className="min-w-0">
                <span className="truncate text-content-primary">{m.name || m.code}</span>{' '}
                <span className="text-xs text-content-tertiary">{m.code}</span>
              </span>
              <span className="shrink-0 tabular-nums text-content-secondary">
                × {fmtMoney(m.quantity)} · {fmtMoney(m.cost, row.currency)}
              </span>
            </div>
          ))}
          {missing.length > 0 && (
            <div className="pt-1 text-xs text-content-tertiary">
              {t('costExplorer.byResources.notUsed', { defaultValue: 'Not used by this work:' })}{' '}
              {fmtList(missing)}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
