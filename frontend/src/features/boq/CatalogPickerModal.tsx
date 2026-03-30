/**
 * CatalogPickerModal — Pick a resource from the Resource Catalog
 * to add to a BOQ position.
 *
 * Opens as a full-screen overlay with search, type filters, and a results list.
 * Follows the same visual pattern as CostDatabaseSearchModal in BOQModals.tsx.
 */

import { useState, useEffect, useRef, useCallback } from 'react';
import { createPortal } from 'react-dom';
import { useTranslation } from 'react-i18next';
import { Search, X, Package, Hammer, Cpu, Users, Loader2, Boxes } from 'lucide-react';
import { Button } from '@/shared/ui';
import { apiGet } from '@/shared/lib/api';
import { getIntlLocale } from '@/shared/lib/formatters';

/* ── Types ───────────────────────────────────────────────────────────── */

export interface CatalogResource {
  id: string;
  resource_code: string;
  name: string;
  resource_type: string;
  category: string;
  unit: string;
  base_price: number;
  currency: string;
  region: string | null;
}

export interface CatalogPickerModalProps {
  open: boolean;
  onClose: () => void;
  onSelect: (resource: CatalogResource) => void;
}

/* ── Resource type filter tabs ───────────────────────────────────────── */

const TYPE_FILTERS = [
  { key: '', labelKey: 'catalog.all_types', defaultLabel: 'All', icon: null },
  { key: 'material', labelKey: 'catalog.material', defaultLabel: 'Material', icon: Package },
  { key: 'labor', labelKey: 'catalog.labor', defaultLabel: 'Labor', icon: Hammer },
  { key: 'equipment', labelKey: 'catalog.equipment', defaultLabel: 'Equipment', icon: Cpu },
  { key: 'operator', labelKey: 'catalog.operator', defaultLabel: 'Operator', icon: Users },
] as const;

/* ── Type badge colors (mirrors RESOURCE_TYPE_BADGE from boqHelpers) ── */

const TYPE_BADGE_STYLE: Record<string, string> = {
  material: 'bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300',
  labor: 'bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300',
  equipment: 'bg-violet-100 text-violet-700 dark:bg-violet-900/40 dark:text-violet-300',
  operator: 'bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-300',
  subcontractor: 'bg-pink-100 text-pink-700 dark:bg-pink-900/40 dark:text-pink-300',
  other: 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400',
};

/* ── Component ───────────────────────────────────────────────────────── */

export function CatalogPickerModal({ open, onClose, onSelect }: CatalogPickerModalProps) {
  const { t } = useTranslation();
  const [query, setQuery] = useState('');
  const [debouncedQuery, setDebouncedQuery] = useState('');
  const [typeFilter, setTypeFilter] = useState('');
  const [results, setResults] = useState<CatalogResource[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [initialLoad, setInitialLoad] = useState(true);
  const inputRef = useRef<HTMLInputElement>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout>>();

  const fmt = useCallback(
    (n: number) =>
      new Intl.NumberFormat(getIntlLocale(), {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
      }).format(n),
    [],
  );

  /* ── Debounce search input ─────────────────────────────────────────── */

  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      setDebouncedQuery(query);
    }, 300);
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [query]);

  /* ── Fetch catalog results ─────────────────────────────────────────── */

  useEffect(() => {
    if (!open) return;

    let cancelled = false;
    setLoading(true);

    const params = new URLSearchParams();
    if (debouncedQuery) params.set('q', debouncedQuery);
    if (typeFilter) params.set('resource_type', typeFilter);
    params.set('limit', '30');

    apiGet<{ items: CatalogResource[]; total: number }>(`/v1/catalog/?${params.toString()}`)
      .then((data) => {
        if (cancelled) return;
        setResults(data.items ?? []);
        setTotal(data.total ?? 0);
        setInitialLoad(false);
      })
      .catch(() => {
        if (cancelled) return;
        setResults([]);
        setTotal(0);
        setInitialLoad(false);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [open, debouncedQuery, typeFilter]);

  /* ── Close on Escape ───────────────────────────────────────────────── */

  useEffect(() => {
    if (!open) return;
    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === 'Escape') {
        e.preventDefault();
        onClose();
      }
    }
    document.addEventListener('keydown', handleKeyDown, { capture: true });
    return () => document.removeEventListener('keydown', handleKeyDown, { capture: true });
  }, [open, onClose]);

  /* ── Focus input on open ───────────────────────────────────────────── */

  useEffect(() => {
    if (open) {
      setTimeout(() => inputRef.current?.focus(), 50);
    } else {
      // Reset state on close
      setQuery('');
      setDebouncedQuery('');
      setTypeFilter('');
      setResults([]);
      setTotal(0);
      setInitialLoad(true);
    }
  }, [open]);

  /* ── Render ────────────────────────────────────────────────────────── */

  if (!open) return null;

  return createPortal(
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 animate-fade-in"
      onClick={onClose}
      aria-hidden="true"
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label={t('boq.pick_from_catalog', { defaultValue: 'Pick from Catalog' })}
        className="bg-surface-elevated rounded-2xl border border-border shadow-2xl w-full max-w-2xl mx-4 max-h-[80vh] flex flex-col overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-border-light shrink-0">
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-emerald-100 text-emerald-600 dark:bg-emerald-900/30">
              <Boxes size={18} />
            </div>
            <div>
              <h2 className="text-base font-semibold text-content-primary">
                {t('boq.pick_from_catalog', { defaultValue: 'Pick from Catalog' })}
              </h2>
              <p className="text-xs text-content-tertiary">
                {t('boq.pick_from_catalog_desc', {
                  defaultValue: 'Search and add a resource from the catalog to this position',
                })}
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            aria-label={t('common.close', { defaultValue: 'Close' })}
            className="flex h-8 w-8 items-center justify-center rounded-lg text-content-tertiary hover:bg-surface-secondary hover:text-content-primary transition-colors"
          >
            <X size={16} />
          </button>
        </div>

        {/* Type filter tabs */}
        <div className="px-6 py-2 border-b border-border-light flex items-center gap-1.5 overflow-x-auto scrollbar-none shrink-0">
          {TYPE_FILTERS.map((tf) => {
            const isActive = typeFilter === tf.key;
            const Icon = tf.icon;
            return (
              <button
                key={tf.key}
                onClick={() => setTypeFilter(tf.key)}
                className={`shrink-0 flex items-center gap-1.5 rounded-md px-2.5 py-1 text-xs font-medium transition-colors ${
                  isActive
                    ? 'bg-emerald-600 text-white'
                    : 'bg-surface-secondary text-content-secondary hover:bg-surface-tertiary'
                }`}
              >
                {Icon && <Icon size={12} />}
                <span>{t(tf.labelKey, { defaultValue: tf.defaultLabel })}</span>
              </button>
            );
          })}
        </div>

        {/* Search input */}
        <div className="px-6 py-3 border-b border-border-light shrink-0">
          <div className="relative">
            <div className="pointer-events-none absolute inset-y-0 left-0 flex items-center pl-3 text-content-tertiary">
              <Search size={16} />
            </div>
            <input
              ref={inputRef}
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder={t('boq.search_catalog_resources', {
                defaultValue: 'Search resources by name, code, or category...',
              })}
              aria-label={t('boq.search_catalog_resources', {
                defaultValue: 'Search resources by name, code, or category...',
              })}
              className="h-10 w-full rounded-lg border border-border bg-surface-primary pl-10 pr-3 text-sm text-content-primary placeholder:text-content-tertiary focus:outline-none focus:ring-2 focus:ring-emerald-500/30 focus:border-emerald-400"
            />
            {loading && (
              <div className="absolute inset-y-0 right-0 flex items-center pr-3">
                <Loader2 size={14} className="animate-spin text-content-quaternary" />
              </div>
            )}
          </div>
        </div>

        {/* Results list */}
        <div className="flex-1 overflow-y-auto">
          {initialLoad && loading ? (
            <div className="flex items-center justify-center py-12 text-xs text-content-tertiary">
              <Loader2 size={16} className="animate-spin mr-2" />
              {t('common.loading', { defaultValue: 'Loading...' })}
            </div>
          ) : results.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12 text-center px-6">
              <Boxes size={32} className="text-content-quaternary mb-3" />
              <p className="text-sm font-medium text-content-secondary mb-1">
                {debouncedQuery || typeFilter
                  ? t('boq.no_catalog_results', { defaultValue: 'No resources match your search' })
                  : t('boq.catalog_empty', { defaultValue: 'No resources in catalog' })}
              </p>
              <p className="text-xs text-content-tertiary">
                {debouncedQuery || typeFilter
                  ? t('boq.try_different_search', { defaultValue: 'Try a different search term or filter' })
                  : t('boq.import_catalog_hint', {
                      defaultValue: 'Import a resource catalog from Settings or the Catalog page',
                    })}
              </p>
            </div>
          ) : (
            <div className="divide-y divide-border-light">
              {results.map((res) => {
                const badgeStyle = TYPE_BADGE_STYLE[res.resource_type] ?? TYPE_BADGE_STYLE.other;
                return (
                  <button
                    key={res.id}
                    type="button"
                    className="w-full text-left px-6 py-3 hover:bg-surface-secondary/50 transition-colors cursor-pointer focus:outline-none focus:bg-surface-secondary/50"
                    onClick={() => onSelect(res)}
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2 mb-0.5">
                          <span className="text-sm font-medium text-content-primary truncate">
                            {res.name}
                          </span>
                          <span className="text-2xs font-mono text-content-quaternary shrink-0">
                            {res.resource_code}
                          </span>
                        </div>
                        <div className="flex items-center gap-2 text-xs text-content-tertiary">
                          <span
                            className={`inline-flex items-center rounded px-1.5 py-0.5 text-2xs font-medium ${badgeStyle}`}
                          >
                            {res.resource_type}
                          </span>
                          {res.category && (
                            <span className="text-content-quaternary">{res.category}</span>
                          )}
                        </div>
                      </div>
                      <div className="text-right shrink-0">
                        <div className="text-sm font-semibold text-content-primary tabular-nums">
                          {fmt(res.base_price)} {res.currency || ''}
                        </div>
                        <div className="text-2xs text-content-quaternary">
                          {t('boq.per_unit', { defaultValue: 'per {{unit}}', unit: res.unit })}
                        </div>
                      </div>
                    </div>
                  </button>
                );
              })}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="px-6 py-3 border-t border-border-light bg-surface-secondary/30 shrink-0">
          <div className="flex items-center justify-between text-2xs text-content-quaternary">
            <span>
              {total > 0
                ? t('boq.catalog_showing_count', {
                    defaultValue: 'Showing {{count}} of {{total}} resources',
                    count: results.length,
                    total,
                  })
                : t('boq.catalog_click_to_add', {
                    defaultValue: 'Click a resource to add it to the position',
                  })}
            </span>
            <Button variant="ghost" size="sm" onClick={onClose}>
              {t('common.cancel', { defaultValue: 'Cancel' })}
            </Button>
          </div>
        </div>
      </div>
    </div>,
    document.body,
  );
}
