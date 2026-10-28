// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// "Find work" - plain text search over the priced works, across every loaded
// price base. Every match can jump straight to comparing it across bases or
// testing a resource substitution.

import { useEffect, useState, type KeyboardEvent } from 'react';
import { useMutation } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { GitCompareArrows, Repeat2, Search, X } from 'lucide-react';
import { Badge, Button, EmptyState, ErrorState, Input } from '@/shared/ui';
import { getErrorMessage } from '@/shared/lib/api';
import { findWork } from './api';
import { selectFindWorkHint } from './findWorkHint';
import { fmtMoney, MetaLine, Meter, pct } from './parts';
import { BaseScopeNote, BaseSelect } from './BasePicker';
import { RowEstimateActions } from './RowEstimateActions';
import type { CrossNav } from './types';

export function FindWorkPanel({ nav }: { nav: CrossNav }) {
  const { t } = useTranslation();
  const [q, setQ] = useState('');
  const [region, setRegion] = useState('');
  const [dismissedSuggestion, setDismissedSuggestion] = useState<string | null>(null);

  const search = useMutation({
    mutationFn: (term: string) => findWork({ q: term.trim(), region: region || null, limit: 40 }),
  });
  const results = search.data?.results ?? [];
  const hintView = selectFindWorkHint(search.data, dismissedSuggestion);

  // Results are tagged to the region they were searched in; changing the price
  // base region clears them (and any pending did-you-mean) so old rows with a
  // mismatched region badge never linger over the new filter until the next
  // search.
  const { reset: resetSearch } = search;
  useEffect(() => {
    resetSearch();
    setDismissedSuggestion(null);
  }, [region, resetSearch]);

  function run() {
    if (q.trim().length > 0) search.mutate(q);
  }
  function onKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'Enter') {
      e.preventDefault();
      run();
    }
  }
  // Accept a did-you-mean suggestion: adopt the corrected query and re-run it.
  function applySuggestion(suggestion: string) {
    setQ(suggestion);
    setDismissedSuggestion(null);
    search.mutate(suggestion);
  }

  return (
    <div className="space-y-4">
      <div className="grid gap-3 md:grid-cols-[1fr_220px]">
        <div>
          <label htmlFor="ce-findwork-q" className="mb-1.5 block text-sm font-medium text-content-primary">
            {t('costExplorer.findWork.label', { defaultValue: 'Describe the work' })}
          </label>
          <Input
            id="ce-findwork-q"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={onKeyDown}
            icon={<Search className="h-4 w-4" aria-hidden />}
            placeholder={t('costExplorer.findWork.placeholder', { defaultValue: 'e.g. reinforced concrete wall, formwork, excavation' })}
          />
        </div>
        <div>
          <label htmlFor="ce-findwork-region" className="mb-1.5 block text-sm font-medium text-content-primary">
            {t('costExplorer.region.label', { defaultValue: 'Price base region' })}
          </label>
          <BaseSelect id="ce-findwork-region" value={region} onChange={setRegion} />
        </div>
      </div>

      <BaseScopeNote value={region} />

      <Button onClick={run} disabled={q.trim().length === 0 || search.isPending}>
        {search.isPending ? t('common.searching', { defaultValue: 'Searching...' }) : t('costExplorer.findWork.search', { defaultValue: 'Search works' })}
      </Button>

      {search.isError && <ErrorState title={getErrorMessage(search.error)} onRetry={run} />}

      {hintView?.kind === 'suggestion' && (
        <div className="flex items-center gap-2 rounded-lg border border-oe-blue/30 bg-oe-blue/5 px-3 py-2 text-sm">
          <Search className="h-4 w-4 shrink-0 text-oe-blue" aria-hidden />
          <span className="text-content-secondary">
            {t('costExplorer.findWork.didYouMean', { defaultValue: 'Did you mean' })}
          </span>
          <button
            type="button"
            onClick={() => applySuggestion(hintView.suggestion)}
            className="font-medium text-oe-blue hover:underline"
          >
            {hintView.suggestion}
          </button>
          <button
            type="button"
            onClick={() => setDismissedSuggestion(hintView.suggestion)}
            aria-label={t('common.dismiss', { defaultValue: 'Dismiss' })}
            className="ml-auto shrink-0 text-content-tertiary hover:text-content-secondary"
          >
            <X className="h-4 w-4" aria-hidden />
          </button>
        </div>
      )}

      {hintView?.kind === 'note' && (
        <p className="text-xs text-content-tertiary">{t(hintView.code, { defaultValue: hintView.message })}</p>
      )}

      {search.isSuccess && results.length === 0 && (
        <EmptyState
          title={t('costExplorer.findWork.emptyTitle', { defaultValue: 'No works matched' })}
          description={t('costExplorer.findWork.emptyBody', { defaultValue: 'Try fewer or more general words, or a different region.' })}
        />
      )}

      {results.length > 0 && (
        <div className="space-y-2">
          <div className="text-xs text-content-tertiary">
            {t('costExplorer.findWork.count', { defaultValue: '{{count}} works', count: results.length })}
          </div>
          {results.map((row) => (
            <div key={row.cost_item_id} className="flex items-start gap-3 rounded-lg border border-border-light bg-surface-primary p-3">
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-medium text-content-primary">{row.code}</span>
                  {row.region && <Badge>{row.region}</Badge>}
                </div>
                <p className="mt-0.5 line-clamp-2 text-sm text-content-secondary">{row.description || '-'}</p>
                <div className="mt-1 flex flex-wrap items-center gap-x-4 gap-y-1">
                  <MetaLine parts={[row.unit, row.source]} />
                  {row.score > 0 && <Meter value={row.score} tone="amber" label={`${t('costExplorer.byResources.match', { defaultValue: 'Match' })} ${pct(row.score)}`} />}
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
          ))}
        </div>
      )}

      {!search.data && !search.isPending && (
        <EmptyState
          title={t('costExplorer.findWork.startTitle', { defaultValue: 'Search the priced works' })}
          description={t('costExplorer.findWork.startBody', { defaultValue: 'Type what the work is. Results span every loaded price base unless you pick a region.' })}
        />
      )}
    </div>
  );
}
