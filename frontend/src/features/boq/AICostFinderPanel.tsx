/**
 * AICostFinderPanel — right-side sliding panel for semantic cost item search.
 *
 * Lets estimators search the 55K+ vector cost database by natural language,
 * view results with similarity scores and rates, and take action:
 * - "Add as Position" — creates a new BOQ position with prefilled data
 * - "Apply Rate" — updates the selected grid position's unit_rate
 *
 * Auto-searches when a grid position is selected (fills search with its description).
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import {
  ChevronDown,
  ChevronRight,
  Plus,
  Search,
  TrendingUp,
  X,
} from 'lucide-react';

import {
  boqApi,
  type CostItemSearchResult,
  type CreatePositionData,
  type Position,
} from './api';
import { fmtWithCurrency, getUnitsForLocale } from './boqHelpers';

/* ── Props ─────────────────────────────────────────────────────────── */

interface AICostFinderPanelProps {
  boqId: string;
  isOpen: boolean;
  onClose: () => void;
  /** Currently selected position in the grid (auto-search + Apply Rate target) */
  selectedPosition: Position | null;
  /** Creates a new BOQ position from a cost item */
  onAddPosition: (data: CreatePositionData) => void;
  /** Applies rate to the currently selected position */
  onApplyRate: (positionId: string, rate: number, source: string) => void;
  /** Project region for default filter */
  projectRegion?: string;
  /** ISO currency code (e.g. EUR, USD) */
  currencyCode?: string;
  /** Locale for number formatting (e.g. de-DE, en-US) */
  locale?: string;
}

/* ── Helpers ───────────────────────────────────────────────────────── */

const UNITS = ['', ...getUnitsForLocale()];

function scoreColor(score: number): string {
  if (score >= 0.8) return 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400';
  if (score >= 0.5) return 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400';
  return 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400';
}

function scoreBorder(score: number): string {
  if (score >= 0.8) return 'border-green-200 dark:border-green-800';
  if (score >= 0.5) return 'border-amber-200 dark:border-amber-800';
  return 'border-border-light';
}

/* ── Component ─────────────────────────────────────────────────────── */

export function AICostFinderPanel({
  boqId,
  isOpen,
  onClose,
  selectedPosition,
  onAddPosition,
  onApplyRate,
  projectRegion,
  currencyCode = 'EUR',
  locale = 'de-DE',
}: AICostFinderPanelProps) {
  const { t } = useTranslation();

  /* ── State ─────────────────────────────────────────────────────── */
  const [query, setQuery] = useState('');
  const [debouncedQuery, setDebouncedQuery] = useState('');
  const [unitFilter, setUnitFilter] = useState('');
  const [regionFilter, setRegionFilter] = useState('');
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout>>();
  const lastAutoFilledRef = useRef<string | null>(null);

  /* ── Debounce search ───────────────────────────────────────────── */
  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      setDebouncedQuery(query.trim());
    }, 400);
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [query]);

  /* ── Auto-fill search from selected position ───────────────────── */
  useEffect(() => {
    if (!isOpen || !selectedPosition) return;
    if (lastAutoFilledRef.current === selectedPosition.id) return;
    if (selectedPosition.description) {
      setQuery(selectedPosition.description.slice(0, 200));
      lastAutoFilledRef.current = selectedPosition.id;
    }
  }, [selectedPosition?.id, isOpen]);

  /* ── Focus input on open ───────────────────────────────────────── */
  useEffect(() => {
    if (isOpen) {
      setTimeout(() => inputRef.current?.focus(), 350);
    }
  }, [isOpen]);

  /* ── React Query search ────────────────────────────────────────── */
  const { data, isLoading, isError } = useQuery({
    queryKey: ['cost-item-search', debouncedQuery, unitFilter, regionFilter],
    queryFn: () =>
      boqApi.searchCostItems({
        query: debouncedQuery,
        unit: unitFilter || undefined,
        region: regionFilter || undefined,
        limit: 15,
        min_score: 0.3,
      }),
    enabled: debouncedQuery.length >= 2,
    staleTime: 30_000,
  });

  const results = data?.results ?? [];

  /* ── Handlers ──────────────────────────────────────────────────── */
  const handleAddPosition = useCallback(
    (item: CostItemSearchResult) => {
      onAddPosition({
        boq_id: boqId,
        ordinal: '',
        description: item.description,
        unit: item.unit,
        quantity: 1,
        unit_rate: item.rate,
        classification: item.classification,
      });
    },
    [boqId, onAddPosition],
  );

  const handleApplyRate = useCallback(
    (item: CostItemSearchResult) => {
      if (!selectedPosition) return;
      onApplyRate(selectedPosition.id, item.rate, item.code);
    },
    [selectedPosition, onApplyRate],
  );

  /* ── Render ────────────────────────────────────────────────────── */
  return (
    <div
      className={`fixed right-0 top-0 z-50 h-full w-[380px] bg-surface-elevated border-l border-border-light shadow-xl flex flex-col transition-transform duration-300 ease-in-out ${
        isOpen ? 'translate-x-0' : 'translate-x-full'
      }`}
    >
      {/* ── Header ───────────────────────────────────────────────── */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-border-light shrink-0">
        <div className="flex items-center gap-2">
          <Search size={16} className="text-primary" />
          <span className="font-semibold text-sm">
            {t('boq.cost_finder_title', { defaultValue: 'AI Cost Finder' })}
          </span>
        </div>
        <button
          onClick={onClose}
          className="p-1.5 rounded-md hover:bg-red-100 dark:hover:bg-red-900/30 text-text-muted hover:text-red-600 dark:hover:text-red-400 transition-colors"
          aria-label="Close"
        >
          <X size={18} />
        </button>
      </div>

      {/* ── Search Input ─────────────────────────────────────────── */}
      <div className="px-4 pt-3 pb-2 shrink-0 space-y-2">
        <div className="relative">
          <Search
            size={14}
            className="absolute left-2.5 top-1/2 -translate-y-1/2 text-text-muted"
          />
          <input
            ref={inputRef}
            type="text"
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              lastAutoFilledRef.current = null;
            }}
            placeholder={t('boq.cost_finder_search_placeholder', {
              defaultValue: 'Search cost items by description...',
            })}
            className="w-full pl-8 pr-3 py-2 text-sm border border-border-light rounded-md bg-surface focus:outline-none focus:ring-1 focus:ring-primary"
          />
        </div>

        {/* ── Filters ────────────────────────────────────────────── */}
        <div className="flex gap-2">
          <select
            value={unitFilter}
            onChange={(e) => setUnitFilter(e.target.value)}
            className="flex-1 text-xs border border-border-light rounded px-2 py-1.5 bg-surface"
          >
            <option value="">
              {t('boq.cost_finder_all_units', { defaultValue: 'All units' })}
            </option>
            {UNITS.filter(Boolean).map((u) => (
              <option key={u} value={u}>
                {u}
              </option>
            ))}
          </select>
          <select
            value={regionFilter}
            onChange={(e) => setRegionFilter(e.target.value)}
            className="flex-1 text-xs border border-border-light rounded px-2 py-1.5 bg-surface"
          >
            <option value="">
              {t('boq.cost_finder_all_regions', { defaultValue: 'All regions' })}
            </option>
            {projectRegion && (
              <option value={projectRegion}>{projectRegion}</option>
            )}
          </select>
        </div>
      </div>

      {/* ── Results ──────────────────────────────────────────────── */}
      <div className="flex-1 overflow-y-auto px-4 py-2 space-y-2">
        {/* Loading */}
        {isLoading && debouncedQuery.length >= 2 && (
          <div className="flex items-center justify-center py-8 text-text-muted text-sm">
            <div className="animate-spin h-4 w-4 border-2 border-primary border-t-transparent rounded-full mr-2" />
            {t('common.loading', { defaultValue: 'Searching...' })}
          </div>
        )}

        {/* Error */}
        {isError && (
          <div className="text-center py-8 text-red-500 text-sm">
            {t('boq.cost_finder_error', { defaultValue: 'Search failed. Check vector database.' })}
          </div>
        )}

        {/* Empty query */}
        {!isLoading && !isError && debouncedQuery.length < 2 && (
          <div className="text-center py-8 text-text-muted text-sm">
            {t('boq.cost_finder_no_query', {
              defaultValue: 'Enter a description to search the cost database',
            })}
          </div>
        )}

        {/* No results */}
        {!isLoading && !isError && debouncedQuery.length >= 2 && results.length === 0 && data && (
          <div className="text-center py-8 text-text-muted text-sm">
            {t('boq.cost_finder_no_results', { defaultValue: 'No matching items found' })}
          </div>
        )}

        {/* Result cards */}
        {results.map((item) => (
          <ResultCard
            key={item.id}
            item={item}
            currencyCode={currencyCode}
            locale={locale}
            expanded={expandedId === item.id}
            onToggleExpand={() =>
              setExpandedId((prev) => (prev === item.id ? null : item.id))
            }
            canApplyRate={!!selectedPosition}
            onAddPosition={() => handleAddPosition(item)}
            onApplyRate={() => handleApplyRate(item)}
            t={t}
          />
        ))}
      </div>

      {/* ── Footer ───────────────────────────────────────────────── */}
      <div className="shrink-0 px-4 py-2 border-t border-border-light text-xs text-text-muted">
        {data && debouncedQuery.length >= 2 && (
          <span>
            {t('boq.cost_finder_results_count', {
              defaultValue: '{{count}} results ({{ms}}ms)',
              count: data.total_found,
              ms: Math.round(data.search_ms),
            })}
          </span>
        )}
        {selectedPosition && (
          <div className="truncate mt-0.5 text-text-secondary">
            {t('boq.cost_finder_for_position', {
              defaultValue: 'For: {{description}}',
              description: selectedPosition.description?.slice(0, 50) ?? '',
            })}
          </div>
        )}
      </div>
    </div>
  );
}

/* ── Result Card ───────────────────────────────────────────────────── */

interface ResultCardProps {
  item: CostItemSearchResult;
  currencyCode: string;
  locale: string;
  expanded: boolean;
  onToggleExpand: () => void;
  canApplyRate: boolean;
  onAddPosition: () => void;
  onApplyRate: () => void;
  t: (key: string, options?: Record<string, string | number>) => string;
}

function ResultCard({
  item,
  currencyCode,
  locale,
  expanded,
  onToggleExpand,
  canApplyRate,
  onAddPosition,
  onApplyRate,
  t,
}: ResultCardProps) {
  const hasComponents = item.components && item.components.length > 0;

  return (
    <div className={`border rounded-lg p-3 ${scoreBorder(item.score)} bg-surface`}>
      {/* Top row: score badge + description */}
      <div className="flex items-start gap-2">
        <span
          className={`shrink-0 text-[10px] font-bold px-1.5 py-0.5 rounded ${scoreColor(item.score)}`}
        >
          {Math.round(item.score * 100)}%
        </span>
        <div className="flex-1 min-w-0">
          <p className="text-sm font-medium leading-tight line-clamp-2">
            {item.description}
          </p>
          <div className="flex items-center gap-2 mt-1 text-xs text-text-muted">
            <span className="font-mono">{item.code}</span>
            <span className="text-text-muted">|</span>
            <span>{item.unit}</span>
            <span className="text-text-muted">|</span>
            <span className="font-semibold text-text-primary">
              {fmtWithCurrency(item.rate, locale, currencyCode)}
            </span>
          </div>
          <div className="text-[10px] text-text-muted mt-0.5">
            {item.region}
          </div>
        </div>
      </div>

      {/* Components expand */}
      {hasComponents && (
        <button
          onClick={onToggleExpand}
          className="flex items-center gap-1 mt-2 text-xs text-text-muted hover:text-text-primary transition-colors"
        >
          {expanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
          {t('boq.cost_finder_components', {
            defaultValue: '{{count}} components',
            count: item.components.length,
          })}
        </button>
      )}
      {expanded && hasComponents && (
        <div className="mt-1 ml-4 space-y-0.5">
          {item.components.map((c, i) => (
            <div key={`${c.description}-${c.unit}-${i}`} className="text-xs text-text-muted flex justify-between">
              <span className="truncate mr-2">{c.description}</span>
              <span className="shrink-0">
                {c.unit} {fmtWithCurrency(c.rate, locale, currencyCode)}
              </span>
            </div>
          ))}
        </div>
      )}

      {/* Action buttons */}
      <div className="flex gap-2 mt-2">
        <button
          onClick={onAddPosition}
          className="flex items-center gap-1 px-2 py-1 text-xs font-medium rounded bg-primary/10 text-primary hover:bg-primary/20 transition-colors"
        >
          <Plus size={12} />
          {t('boq.cost_finder_add_position', { defaultValue: 'Add Position' })}
        </button>
        {canApplyRate && (
          <button
            onClick={onApplyRate}
            className="flex items-center gap-1 px-2 py-1 text-xs font-medium rounded bg-green-500/10 text-green-600 hover:bg-green-500/20 dark:text-green-400 transition-colors"
          >
            <TrendingUp size={12} />
            {t('boq.cost_finder_apply_rate', { defaultValue: 'Apply Rate' })}
          </button>
        )}
      </div>
    </div>
  );
}
