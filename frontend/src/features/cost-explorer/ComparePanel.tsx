// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// "Compare bases" - one rate code priced across every loaded region. The same
// scope (a CWICR code is shared verbatim across bases) side by side, with a
// clear note when the currencies differ so the numbers are not misread as
// directly comparable.

import { useEffect, useState, type KeyboardEvent } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { AlertTriangle, Loader2, Search } from 'lucide-react';
import { Button, EmptyState, ErrorState, Input } from '@/shared/ui';
import { getErrorMessage } from '@/shared/lib/api';
import { compareBases } from './api';
import { fmtMoney } from './parts';
import { fmtList } from '@/shared/lib/formatters';

export function ComparePanel({ code, onCodeChange }: { code: string; onCodeChange: (code: string) => void }) {
  const { t } = useTranslation();
  const [draft, setDraft] = useState(code);

  useEffect(() => {
    setDraft(code);
  }, [code]);

  const query = useQuery({
    queryKey: ['cost-explorer', 'compare', code],
    queryFn: () => compareBases({ code: code.trim(), limit: 100 }),
    enabled: code.trim().length > 0,
  });

  function run() {
    onCodeChange(draft.trim());
  }
  function onKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'Enter') {
      e.preventDefault();
      run();
    }
  }

  const data = query.data;
  const rows = [...(data?.rows ?? [])].sort((a, b) => (a.region ?? '~').localeCompare(b.region ?? '~'));
  const mixedCurrency = (data?.currencies?.length ?? 0) > 1;

  return (
    <div className="space-y-4">
      <div>
        <label htmlFor="ce-compare-code" className="mb-1.5 block text-sm font-medium text-content-primary">
          {t('costExplorer.compare.label', { defaultValue: 'Rate code' })}
        </label>
        <div className="flex gap-2">
          <div className="flex-1">
            <Input
              id="ce-compare-code"
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={onKeyDown}
              icon={<Search className="h-4 w-4" aria-hidden />}
              placeholder={t('costExplorer.compare.placeholder', { defaultValue: 'A rate code shared across regions' })}
            />
          </div>
          <Button onClick={run} disabled={draft.trim().length === 0 || query.isFetching}>
            {query.isFetching
              ? t('costExplorer.compare.going', { defaultValue: 'Comparing...' })
              : t('costExplorer.compare.go', { defaultValue: 'Compare' })}
          </Button>
        </div>
        <p className="mt-1.5 text-xs text-content-tertiary">
          {t('costExplorer.compare.hint', { defaultValue: 'Tip: open this from a work in By resources or Find work to fill the code automatically.' })}
        </p>
      </div>

      {query.isError && <ErrorState title={getErrorMessage(query.error)} onRetry={() => query.refetch()} />}

      {query.isFetching && !data && (
        <div className="flex items-center gap-2 rounded-lg border border-border-light px-3 py-4 text-sm text-content-tertiary">
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
          {t('costExplorer.compare.loading', { defaultValue: 'Comparing across bases...' })}
        </div>
      )}

      {code.trim().length === 0 && !query.isFetching && (
        <EmptyState
          title={t('costExplorer.compare.startTitle', { defaultValue: 'Compare a rate across bases' })}
          description={t('costExplorer.compare.startBody', { defaultValue: 'Enter a rate code, or open one from another tab, to see how it is priced in each region.' })}
        />
      )}

      {data && rows.length > 0 && (
        <div className="space-y-3">
          <div>
            <div className="font-medium text-content-primary">{data.code}</div>
            {data.description && <p className="mt-0.5 text-sm text-content-secondary">{data.description}</p>}
            <p className="mt-0.5 text-xs text-content-tertiary">
              {t('costExplorer.compare.summary', {
                defaultValue: '{{count}} regions{{unit}}',
                count: data.region_count,
                unit: data.unit ? ` · ${data.unit}` : '',
              })}
            </p>
          </div>

          {mixedCurrency && (
            <div className="flex items-start gap-2 rounded-lg border border-semantic-warning/30 bg-semantic-warning/10 px-3 py-2 text-xs text-content-secondary">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-semantic-warning" aria-hidden />
              <span>
                {t('costExplorer.compare.mixedCurrency', {
                  defaultValue: 'These regions price in different currencies ({{list}}), so the amounts are not directly comparable.',
                  list: fmtList(data.currencies),
                })}
              </span>
            </div>
          )}

          <div className="overflow-x-auto rounded-lg border border-border-light bg-surface-primary">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border-light bg-surface-secondary text-left text-xs text-content-tertiary">
                  <th className="px-3 py-2 font-medium">{t('costExplorer.compare.region', { defaultValue: 'Region' })}</th>
                  <th className="px-3 py-2 font-medium">{t('costExplorer.compare.unit', { defaultValue: 'Unit' })}</th>
                  <th className="px-3 py-2 text-right font-medium">{t('costExplorer.compare.rate', { defaultValue: 'Rate' })}</th>
                  <th className="px-3 py-2 font-medium">{t('costExplorer.compare.source', { defaultValue: 'Source' })}</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.cost_item_id} className="border-b border-border-light last:border-0">
                    <td className="px-3 py-2 font-medium text-content-primary">{r.region ?? '-'}</td>
                    <td className="px-3 py-2 text-content-secondary">{r.unit || '-'}</td>
                    <td className="px-3 py-2 text-right tabular-nums text-content-primary">{fmtMoney(r.rate, r.currency)}</td>
                    <td className="px-3 py-2 text-content-tertiary">{r.source || '-'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {data && rows.length === 0 && (
        <EmptyState
          title={t('costExplorer.compare.noneTitle', { defaultValue: 'That code is not priced anywhere' })}
          description={t('costExplorer.compare.noneBody', { defaultValue: 'No loaded region carries this rate code. Check the code, or load the region that does.' })}
        />
      )}
    </div>
  );
}
