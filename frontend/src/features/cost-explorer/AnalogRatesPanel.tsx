// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// "Analog rates" - for one need, the top candidate rates laid side by side.
// An estimator rarely finds an exact rate for a partida; they pick the closest
// analog. Instead of opening each candidate one by one to read its price, work
// composition and application conditions, this panel ranks the candidates for a
// single query and puts price, unit, region, composition and conditions in one
// compact table so the best fit is obvious at a glance - then inserts the chosen
// rate to the clipboard in one click to paste into the estimate.
//
// It reuses the cost catalog's ranked semantic autocomplete (the same ranked
// candidate results the BOQ cost finder consumes), so no new backend is needed.
// Money arrives from that endpoint already computed; it is only formatted here,
// never summed or otherwise arithmetically combined.

import { useState, type KeyboardEvent } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { AlertTriangle, Copy, GitCompareArrows, Layers, ListChecks, Loader2, Search, Sparkles } from 'lucide-react';
import { Badge, Button, EmptyState, ErrorState, Input } from '@/shared/ui';
import { getErrorMessage } from '@/shared/lib/api';
import { copyToClipboard } from '@/shared/lib/browser';
import { useToastStore } from '@/stores/useToastStore';
import { boqApi, type CostAutocompleteItem } from '@/features/boq/api';
import { buildInsertRow, distinctCurrencies, lowestPriceIndex, scopeSteps, topItems } from './analogRates';
import { fmtMoney } from './parts';
import { BaseScopeNote, BaseSelect } from './BasePicker';
import type { CrossNav } from './types';
import { fmtList } from '@/shared/lib/formatters';

/** How many candidate rates to line up. Enough to choose from, few enough to scan. */
const ANALOG_LIMIT = 6;

// ── Component ────────────────────────────────────────────────────────────────

export function AnalogRatesPanel({ nav }: { nav: CrossNav }) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const [draft, setDraft] = useState('');
  const [query, setQuery] = useState('');
  const [region, setRegion] = useState('');

  const enabled = query.trim().length >= 2;
  const search = useQuery({
    queryKey: ['cost-explorer', 'analogs', query, region],
    queryFn: () => boqApi.autocomplete(query.trim(), ANALOG_LIMIT, region || undefined),
    enabled,
    staleTime: 60_000,
  });

  const items = search.data ?? [];
  const currencies = distinctCurrencies(items);
  const mixedCurrency = currencies.length > 1;
  // Only mark a cheapest rate when the amounts are actually comparable.
  const lowestIdx = mixedCurrency ? -1 : lowestPriceIndex(items);

  function run() {
    setQuery(draft.trim());
  }
  function onKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'Enter') {
      e.preventDefault();
      run();
    }
  }

  async function insert(item: CostAutocompleteItem) {
    const ok = await copyToClipboard(buildInsertRow(item));
    if (ok) {
      addToast({
        type: 'success',
        title: t('costExplorer.analogs.copied', { defaultValue: 'Rate copied' }),
        message: t('costExplorer.analogs.copiedDetail', {
          defaultValue: '{{code}} is on the clipboard. Paste it into your estimate.',
          code: item.code,
        }),
      });
    } else {
      addToast({
        type: 'error',
        title: t('costExplorer.analogs.copyFailed', { defaultValue: 'Could not copy the rate' }),
      });
    }
  }

  return (
    <div className="space-y-4">
      <div className="grid gap-3 md:grid-cols-[1fr_220px]">
        <div>
          <label htmlFor="ce-analogs-q" className="mb-1.5 block text-sm font-medium text-content-primary">
            {t('costExplorer.analogs.label', { defaultValue: 'Describe the need' })}
          </label>
          <Input
            id="ce-analogs-q"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={onKeyDown}
            icon={<Search className="h-4 w-4" aria-hidden />}
            placeholder={t('costExplorer.analogs.placeholder', {
              defaultValue: 'e.g. reinforced concrete wall C30/37, 200 mm',
            })}
          />
        </div>
        <div>
          <label htmlFor="ce-analogs-region" className="mb-1.5 block text-sm font-medium text-content-primary">
            {t('costExplorer.region.label', { defaultValue: 'Price base region' })}
          </label>
          <BaseSelect id="ce-analogs-region" value={region} onChange={setRegion} />
        </div>
      </div>

      <BaseScopeNote value={region} />

      <Button onClick={run} disabled={draft.trim().length < 2 || search.isFetching}>
        {search.isFetching
          ? t('common.searching', { defaultValue: 'Searching...' })
          : t('costExplorer.analogs.search', { defaultValue: 'Compare analogs' })}
      </Button>

      <p className="flex items-start gap-2 text-xs text-content-tertiary">
        <Sparkles className="mt-0.5 h-3.5 w-3.5 shrink-0 text-oe-blue" aria-hidden />
        <span>
          {t('costExplorer.analogs.hint', {
            defaultValue:
              'These are analog rates ranked by similarity, not exact matches. Compare the composition and conditions before you use one.',
          })}
        </span>
      </p>

      {search.isError && <ErrorState title={getErrorMessage(search.error)} onRetry={() => search.refetch()} />}

      {search.isFetching && items.length === 0 && (
        <div className="flex items-center gap-2 rounded-lg border border-border-light px-3 py-4 text-sm text-content-tertiary">
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
          {t('costExplorer.analogs.loading', { defaultValue: 'Lining up the candidate rates...' })}
        </div>
      )}

      {!enabled && !search.isFetching && (
        <EmptyState
          title={t('costExplorer.analogs.startTitle', { defaultValue: 'Compare the candidate rates for one need' })}
          description={t('costExplorer.analogs.startBody', {
            defaultValue:
              'Describe the work. The closest priced rates line up side by side with their composition and conditions, so you can pick the best analog and insert it in one click.',
          })}
        />
      )}

      {enabled && search.isSuccess && items.length === 0 && (
        <EmptyState
          title={t('costExplorer.analogs.emptyTitle', { defaultValue: 'No candidate rates matched' })}
          description={t('costExplorer.analogs.emptyBody', {
            defaultValue: 'Try fewer or more general words, or a different price base region.',
          })}
        />
      )}

      {items.length > 0 && (
        <div className="space-y-3">
          <div className="text-xs text-content-tertiary">
            {t('costExplorer.analogs.count', { defaultValue: '{{count}} candidate rates, closest first', count: items.length })}
          </div>

          {mixedCurrency && (
            <div className="flex items-start gap-2 rounded-lg border border-semantic-warning/30 bg-semantic-warning/10 px-3 py-2 text-xs text-content-secondary">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-semantic-warning" aria-hidden />
              <span>
                {t('costExplorer.analogs.mixedCurrency', {
                  defaultValue:
                    'These candidates price in different currencies ({{list}}), so the amounts are not directly comparable. Pick a region to compare like for like.',
                  list: fmtList(currencies),
                })}
              </span>
            </div>
          )}

          <div className="overflow-x-auto rounded-lg border border-border-light bg-surface-primary">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border-light bg-surface-secondary text-left text-xs text-content-tertiary">
                  <th className="px-3 py-2 font-medium">{t('costExplorer.analogs.colRate', { defaultValue: 'Rate' })}</th>
                  <th className="px-3 py-2 font-medium">{t('costExplorer.analogs.colRegion', { defaultValue: 'Region' })}</th>
                  <th className="px-3 py-2 font-medium">{t('costExplorer.analogs.colUnit', { defaultValue: 'Unit' })}</th>
                  <th className="px-3 py-2 text-right font-medium">{t('costExplorer.analogs.colPrice', { defaultValue: 'Price' })}</th>
                  <th className="min-w-[11rem] px-3 py-2 font-medium">
                    <span className="inline-flex items-center gap-1">
                      <Layers className="h-3.5 w-3.5" aria-hidden />
                      {t('costExplorer.analogs.colComposition', { defaultValue: 'Work composition' })}
                    </span>
                  </th>
                  <th className="min-w-[11rem] px-3 py-2 font-medium">
                    <span className="inline-flex items-center gap-1">
                      <ListChecks className="h-3.5 w-3.5" aria-hidden />
                      {t('costExplorer.analogs.colConditions', { defaultValue: 'Application conditions' })}
                    </span>
                  </th>
                  <th className="px-3 py-2 font-medium">
                    <span className="sr-only">{t('costExplorer.analogs.colActions', { defaultValue: 'Actions' })}</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {items.map((item, i) => {
                  const comp = topItems(item.components, 4);
                  const steps = scopeSteps(item, 3);
                  const isLowest = i === lowestIdx;
                  return (
                    <tr key={`${item.code || 'row'}-${item.region ?? ''}-${i}`} className="border-b border-border-light align-top last:border-0">
                      <td className="px-3 py-2.5">
                        <div className="font-medium text-content-primary">{item.code || '-'}</div>
                        {item.description && (
                          <p className="mt-0.5 line-clamp-2 max-w-[18rem] text-xs text-content-secondary">{item.description}</p>
                        )}
                      </td>
                      <td className="px-3 py-2.5">{item.region ? <Badge>{item.region}</Badge> : <span className="text-content-tertiary">-</span>}</td>
                      <td className="px-3 py-2.5 text-content-secondary">{item.unit || '-'}</td>
                      <td className="px-3 py-2.5 text-right">
                        <div className="font-semibold tabular-nums text-content-primary">{fmtMoney(item.rate, item.currency)}</div>
                        {isLowest && (
                          <span className="mt-1 inline-block rounded bg-semantic-success/15 px-1.5 py-0.5 text-xs font-medium text-semantic-success">
                            {t('costExplorer.analogs.lowest', { defaultValue: 'Lowest' })}
                          </span>
                        )}
                      </td>
                      <td className="px-3 py-2.5">
                        {comp.shown.length === 0 ? (
                          <span className="text-content-tertiary">-</span>
                        ) : (
                          <ul className="space-y-0.5">
                            {comp.shown.map((c, ci) => {
                              const qtyLabel = c.unit
                                ? `${Number.isFinite(c.quantity) && c.quantity > 0 ? `${fmtMoney(c.quantity)} ` : ''}${c.unit}`
                                : '';
                              return (
                                <li key={`${c.code ?? c.name ?? 'c'}-${ci}`} className="text-xs text-content-secondary">
                                  <span className="text-content-primary">{c.name || c.code || '-'}</span>
                                  {qtyLabel && <span className="text-content-tertiary"> · {qtyLabel}</span>}
                                </li>
                              );
                            })}
                            {comp.more > 0 && (
                              <li className="text-xs text-content-tertiary">
                                {t('costExplorer.analogs.more', { defaultValue: '+{{count}} more', count: comp.more })}
                              </li>
                            )}
                          </ul>
                        )}
                      </td>
                      <td className="px-3 py-2.5">
                        {steps.shown.length === 0 ? (
                          <span className="text-content-tertiary">-</span>
                        ) : (
                          <ul className="list-disc space-y-0.5 pl-4">
                            {steps.shown.map((s, si) => (
                              <li key={`${si}-${s}`} className="text-xs text-content-secondary">
                                {s}
                              </li>
                            ))}
                            {steps.more > 0 && (
                              <li className="list-none text-xs text-content-tertiary">
                                {t('costExplorer.analogs.more', { defaultValue: '+{{count}} more', count: steps.more })}
                              </li>
                            )}
                          </ul>
                        )}
                      </td>
                      <td className="px-3 py-2.5">
                        <div className="flex flex-col items-start gap-1.5">
                          <Button
                            size="sm"
                            variant="secondary"
                            onClick={() => {
                              void insert(item);
                            }}
                            aria-label={t('costExplorer.analogs.insertAria', {
                              defaultValue: 'Copy rate {{code}} to paste into the estimate',
                              code: item.code,
                            })}
                          >
                            <Copy className="mr-1 h-3.5 w-3.5" aria-hidden />
                            {t('costExplorer.analogs.insert', { defaultValue: 'Insert' })}
                          </Button>
                          <button
                            type="button"
                            onClick={() => nav.openCompare(item.code)}
                            className="inline-flex items-center gap-1 text-xs text-oe-blue hover:underline"
                          >
                            <GitCompareArrows className="h-3.5 w-3.5" aria-hidden />
                            {t('costExplorer.actions.compare', { defaultValue: 'Compare bases' })}
                          </button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
