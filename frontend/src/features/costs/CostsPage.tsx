import { useState, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { Search, Copy, Check, Database, ChevronDown, Upload } from 'lucide-react';
import { Button, Card, Badge, EmptyState, Skeleton } from '@/shared/ui';
import { apiGet } from '@/shared/lib/api';

/* ── Types ─────────────────────────────────────────────────────────────── */

interface CostItem {
  id: string;
  code: string;
  description: string;
  unit: string;
  rate: number;
  din276_code: string;
  source: string;
}

interface CostSearchResponse {
  items: CostItem[];
  total: number;
  limit: number;
  offset: number;
}

/* ── Constants ─────────────────────────────────────────────────────────── */

const UNITS = ['', 'm', 'm2', 'm3', 'kg', 't', 'pcs', 'lsum', 'h', 'set', 'lm'] as const;
const SOURCES = ['', 'cwicr', 'custom'] as const;
const PAGE_SIZE = 20;

/* ── API ───────────────────────────────────────────────────────────────── */

function buildSearchUrl(query: string, unit: string, source: string, offset: number): string {
  const params = new URLSearchParams();
  if (query) params.set('q', query);
  if (unit) params.set('unit', unit);
  if (source) params.set('source', source);
  params.set('limit', String(PAGE_SIZE));
  params.set('offset', String(offset));
  return `/v1/costs/?${params.toString()}`;
}

/* ── Component ─────────────────────────────────────────────────────────── */

export function CostsPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();

  const [query, setQuery] = useState('');
  const [unit, setUnit] = useState('');
  const [source, setSource] = useState('');
  const [offset, setOffset] = useState(0);
  const [copiedId, setCopiedId] = useState<string | null>(null);

  const searchUrl = buildSearchUrl(query, unit, source, offset);

  const { data, isLoading, isFetching } = useQuery({
    queryKey: ['costs', query, unit, source, offset],
    queryFn: () => apiGet<CostSearchResponse>(searchUrl),
    placeholderData: (prev) => prev,
  });

  const items = data?.items ?? [];
  const total = data?.total ?? 0;
  const hasMore = offset + PAGE_SIZE < total;

  const handleSearch = useCallback(
    (value: string) => {
      setQuery(value);
      setOffset(0);
    },
    [],
  );

  const handleUnitChange = useCallback((value: string) => {
    setUnit(value);
    setOffset(0);
  }, []);

  const handleSourceChange = useCallback((value: string) => {
    setSource(value);
    setOffset(0);
  }, []);

  const handleCopyRate = useCallback(async (item: CostItem) => {
    try {
      await navigator.clipboard.writeText(String(item.rate));
      setCopiedId(item.id);
      setTimeout(() => setCopiedId(null), 2000);
    } catch {
      // Clipboard API unavailable — silently ignore.
    }
  }, []);

  const handleLoadMore = useCallback(() => {
    setOffset((prev) => prev + PAGE_SIZE);
  }, []);

  const fmt = (n: number) =>
    new Intl.NumberFormat('de-DE', {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }).format(n);

  return (
    <div className="max-w-content mx-auto animate-fade-in">
      {/* Header */}
      <div className="mb-6 flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold text-content-primary">{t('costs.title')}</h1>
          <p className="mt-1 text-sm text-content-secondary">
            {total > 0
              ? `${total.toLocaleString()} ${t('costs.results_found', 'results found')}`
              : t('costs.search_hint', 'Search cost items by description or code')}
          </p>
        </div>
        <Button
          variant="secondary"
          icon={<Upload size={16} />}
          onClick={() => navigate('/costs/import')}
        >
          {t('costs.import_database', { defaultValue: 'Import Database' })}
        </Button>
      </div>

      {/* Search & Filters */}
      <Card padding="none" className="mb-6">
        <div className="flex flex-col gap-3 p-4 sm:flex-row sm:items-end">
          {/* Search input */}
          <div className="relative flex-1">
            <div className="pointer-events-none absolute inset-y-0 left-0 flex items-center pl-3 text-content-tertiary">
              <Search size={16} />
            </div>
            <input
              type="text"
              value={query}
              onChange={(e) => handleSearch(e.target.value)}
              placeholder={t('costs.search_placeholder', 'Search by description or code...')}
              className="h-10 w-full rounded-lg border border-border bg-surface-primary pl-10 pr-3 text-sm text-content-primary placeholder:text-content-tertiary transition-all duration-fast ease-oe focus:outline-none focus:ring-2 focus:ring-oe-blue focus:border-transparent hover:border-content-tertiary"
            />
          </div>

          {/* Unit filter */}
          <div className="relative">
            <select
              value={unit}
              onChange={(e) => handleUnitChange(e.target.value)}
              className="h-10 w-full appearance-none rounded-lg border border-border bg-surface-primary pl-3 pr-9 text-sm text-content-primary transition-all duration-fast ease-oe focus:outline-none focus:ring-2 focus:ring-oe-blue focus:border-transparent hover:border-content-tertiary sm:w-32"
            >
              <option value="">{t('costs.all_units', 'All units')}</option>
              {UNITS.filter(Boolean).map((u) => (
                <option key={u} value={u}>
                  {u}
                </option>
              ))}
            </select>
            <div className="pointer-events-none absolute inset-y-0 right-0 flex items-center pr-2.5 text-content-tertiary">
              <ChevronDown size={14} />
            </div>
          </div>

          {/* Source filter */}
          <div className="relative">
            <select
              value={source}
              onChange={(e) => handleSourceChange(e.target.value)}
              className="h-10 w-full appearance-none rounded-lg border border-border bg-surface-primary pl-3 pr-9 text-sm text-content-primary transition-all duration-fast ease-oe focus:outline-none focus:ring-2 focus:ring-oe-blue focus:border-transparent hover:border-content-tertiary sm:w-36"
            >
              <option value="">{t('costs.all_sources', 'All sources')}</option>
              {SOURCES.filter(Boolean).map((s) => (
                <option key={s} value={s}>
                  {s === 'cwicr' ? 'CWICR' : s.charAt(0).toUpperCase() + s.slice(1)}
                </option>
              ))}
            </select>
            <div className="pointer-events-none absolute inset-y-0 right-0 flex items-center pr-2.5 text-content-tertiary">
              <ChevronDown size={14} />
            </div>
          </div>
        </div>
      </Card>

      {/* Results Table */}
      {isLoading ? (
        <Card padding="none" className="overflow-hidden">
          <div className="space-y-0 divide-y divide-border-light">
            {Array.from({ length: 6 }).map((_, i) => (
              <div key={i} className="flex items-center gap-4 px-4 py-3.5">
                <Skeleton width={72} height={14} />
                <Skeleton className="flex-1" height={14} />
                <Skeleton width={40} height={14} />
                <Skeleton width={80} height={14} />
                <Skeleton width={60} height={14} />
                <Skeleton width={28} height={28} rounded="md" />
              </div>
            ))}
          </div>
        </Card>
      ) : items.length === 0 ? (
        <EmptyState
          icon={<Database size={24} strokeWidth={1.5} />}
          title={t('costs.no_results', 'No cost items found')}
          description={
            query
              ? t('costs.no_results_hint', 'Try adjusting your search or filters')
              : t('costs.empty_hint', 'Start typing to search the cost database')
          }
        />
      ) : (
        <>
          <Card padding="none" className="overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border-light bg-surface-tertiary text-left">
                    <th className="px-4 py-3 font-medium text-content-secondary w-28">
                      {t('costs.code', 'Code')}
                    </th>
                    <th className="px-4 py-3 font-medium text-content-secondary min-w-[300px]">
                      {t('boq.description')}
                    </th>
                    <th className="px-4 py-3 font-medium text-content-secondary w-20 text-center">
                      {t('boq.unit')}
                    </th>
                    <th className="px-4 py-3 font-medium text-content-secondary w-32 text-right">
                      {t('costs.rate', 'Rate')}
                    </th>
                    <th className="px-4 py-3 font-medium text-content-secondary w-28 text-center">
                      {t('costs.din276', 'DIN 276')}
                    </th>
                    <th className="px-4 py-3 w-12" />
                  </tr>
                </thead>
                <tbody className="divide-y divide-border-light">
                  {items.map((item) => (
                    <tr
                      key={item.id}
                      className="group hover:bg-surface-secondary/50 transition-colors"
                    >
                      <td className="px-4 py-3 font-mono text-xs text-content-secondary">
                        {item.code}
                      </td>
                      <td className="px-4 py-3 text-content-primary">{item.description}</td>
                      <td className="px-4 py-3 text-center">
                        <Badge variant="neutral" size="sm">
                          {item.unit}
                        </Badge>
                      </td>
                      <td className="px-4 py-3 text-right font-semibold text-content-primary tabular-nums">
                        {fmt(item.rate)}
                      </td>
                      <td className="px-4 py-3 text-center">
                        {item.din276_code ? (
                          <Badge variant="blue" size="sm">
                            {item.din276_code}
                          </Badge>
                        ) : (
                          <span className="text-content-tertiary">-</span>
                        )}
                      </td>
                      <td className="px-2 py-3">
                        <button
                          onClick={() => handleCopyRate(item)}
                          title={t('costs.copy_rate', 'Copy rate to clipboard')}
                          className="flex h-8 w-8 items-center justify-center rounded-lg text-content-tertiary opacity-0 transition-all group-hover:opacity-100 hover:bg-surface-tertiary hover:text-content-primary"
                        >
                          {copiedId === item.id ? (
                            <Check size={14} className="text-semantic-success" />
                          ) : (
                            <Copy size={14} />
                          )}
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>

          {/* Load More / Pagination */}
          <div className="mt-6 flex flex-col items-center gap-3">
            <p className="text-xs text-content-tertiary">
              {t('costs.showing', 'Showing')} {Math.min(offset + PAGE_SIZE, total)}{' '}
              {t('costs.of', 'of')} {total.toLocaleString()}{' '}
              {t('costs.items', 'items')}
            </p>
            {hasMore && (
              <Button
                variant="secondary"
                size="sm"
                loading={isFetching}
                onClick={handleLoadMore}
              >
                {t('costs.load_more', 'Load more')}
              </Button>
            )}
          </div>
        </>
      )}
    </div>
  );
}
