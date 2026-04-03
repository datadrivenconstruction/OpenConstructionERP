/**
 * BOQModals — Cost Database Search Modal and Assembly Picker Modal
 * for the BOQ Editor.
 *
 * Extracted from BOQEditorPage.tsx for modularity.
 */

import { useState, useCallback, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import {
  Plus,
  X,
  Search,
  Loader2,
  Check,
  Layers,
  Database,
} from 'lucide-react';
import { Button, Badge, CountryFlag } from '@/shared/ui';
import { apiGet, apiPost } from '@/shared/lib/api';
import { getIntlLocale } from '@/shared/lib/formatters';
import { useToastStore } from '@/stores/useToastStore';
import { REGION_MAP } from '@/stores/useCostDatabaseStore';

/* ── Types ───────────────────────────────────────────────────────────── */

interface CostSearchItem {
  id: string;
  code: string;
  description: string;
  unit: string;
  rate: number;
  region: string | null;
  classification: Record<string, string>;
  components: Array<{
    name: string;
    code?: string;
    unit: string;
    quantity: number;
    unit_rate: number;
    cost: number;
    type: string;
  }>;
  metadata_: Record<string, unknown>;
}

/* ── AssemblyPickerModal ─────────────────────────────────────────────── */

export function AssemblyPickerModal({
  boqId,
  onClose,
  onApplied,
}: {
  boqId: string;
  onClose: () => void;
  onApplied: () => void;
}) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [search, setSearch] = useState('');
  const [applying, setApplying] = useState<string | null>(null);
  const [quantity, setQuantity] = useState<Record<string, number>>({});
  const addToast = useToastStore((s) => s.addToast);

  const { data: assemblies, isLoading } = useQuery({
    queryKey: ['assemblies', search],
    queryFn: () => apiGet<{ items: Array<{
      id: string;
      code: string;
      name: string;
      unit: string;
      category: string;
      total_rate: number;
      currency: string;
      components: Array<{ description: string; unit: string; unit_cost: number; quantity: number }>;
    }>; total: number }>(`/v1/assemblies/?q=${encodeURIComponent(search)}&limit=20`).then((r) => r.items),
    retry: false,
  });

  const handleApply = useCallback(async (assemblyId: string) => {
    const qty = quantity[assemblyId] || 1;
    setApplying(assemblyId);
    try {
      await apiPost(`/v1/assemblies/${assemblyId}/apply-to-boq`, {
        boq_id: boqId,
        quantity: qty,
      });
      onApplied();
    } catch (err) {
      addToast({
        type: 'error',
        title: t('assemblies.apply_failed', { defaultValue: 'Failed to apply assembly' }),
        message: err instanceof Error ? err.message : t('common.unknown_error', { defaultValue: 'Unknown error' }),
      });
    } finally {
      setApplying(null);
    }
  }, [boqId, quantity, onApplied, addToast]);

  // Close on Escape
  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === 'Escape') { e.preventDefault(); onClose(); }
    }
    document.addEventListener('keydown', handleKeyDown, { capture: true });
    return () => document.removeEventListener('keydown', handleKeyDown, { capture: true });
  }, [onClose]);

  const fmt = (n: number) =>
    new Intl.NumberFormat(getIntlLocale(), { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(n);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 animate-fade-in" onClick={onClose} aria-hidden="true">
      <div
        role="dialog"
        aria-modal="true"
        aria-label={t('assemblies.apply_assembly_to_boq', { defaultValue: 'Apply Assembly to BOQ' })}
        className="bg-surface-elevated rounded-2xl border border-border shadow-2xl w-full max-w-2xl mx-4 max-h-[80vh] flex flex-col overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-border-light shrink-0">
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-purple-100 text-purple-600 dark:bg-purple-900/30">
              <Layers size={18} />
            </div>
            <div>
              <h2 className="text-base font-semibold text-content-primary">{t('assemblies.apply_assembly_to_boq', { defaultValue: 'Apply Assembly to BOQ' })}</h2>
              <p className="text-xs text-content-tertiary">{t('assemblies.select_recipe_desc', { defaultValue: 'Select a pre-built recipe to add as a position' })}</p>
            </div>
          </div>
          <button onClick={onClose} aria-label={t('common.close', { defaultValue: 'Close' })} className="flex h-8 w-8 items-center justify-center rounded-lg text-content-tertiary hover:bg-surface-secondary hover:text-content-primary transition-colors">
            <X size={16} />
          </button>
        </div>

        {/* Search */}
        <div className="px-6 py-3 border-b border-border-light shrink-0">
          <div className="relative">
            <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-content-quaternary" />
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder={t('assemblies.search_placeholder', { defaultValue: 'Search assemblies...' })}
              aria-label={t('assemblies.search_placeholder', { defaultValue: 'Search assemblies...' })}
              className="w-full h-9 pl-9 pr-3 rounded-lg border border-border-light bg-surface-primary text-sm text-content-primary placeholder:text-content-quaternary focus:outline-none focus:ring-2 focus:ring-purple-500/30 focus:border-purple-400"
              autoFocus
            />
          </div>
        </div>

        {/* List */}
        <div className="flex-1 overflow-y-auto px-6 py-3">
          {isLoading ? (
            <div className="flex items-center justify-center py-12 text-xs text-content-tertiary">
              <Loader2 size={16} className="animate-spin mr-2" /> {t('assemblies.loading', { defaultValue: 'Loading assemblies...' })}
            </div>
          ) : !assemblies || assemblies.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12 text-center">
              <Layers size={32} className="text-content-quaternary mb-3" />
              <p className="text-sm font-medium text-content-secondary mb-1">
                {search ? t('assemblies.no_search_match', { defaultValue: 'No assemblies match your search' }) : t('assemblies.no_assemblies', { defaultValue: 'No assemblies yet' })}
              </p>
              <p className="text-xs text-content-tertiary mb-3">
                {search ? t('assemblies.try_different_term', { defaultValue: 'Try a different search term' }) : t('assemblies.create_from_catalog', { defaultValue: 'Create assemblies from the Resource Catalog' })}
              </p>
              {!search && (
                <Button variant="secondary" size="sm" onClick={() => { onClose(); navigate('/catalog'); }}>
                  {t('catalog.go_to_catalog', { defaultValue: 'Go to Catalog' })}
                </Button>
              )}
            </div>
          ) : (
            <div className="space-y-2">
              {assemblies.map((asm) => {
                const isApplying = applying === asm.id;
                return (
                  <div
                    key={asm.id}
                    className="rounded-xl border border-border-light bg-surface-primary hover:bg-surface-secondary/50 transition-colors p-3"
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2 mb-0.5">
                          <span className="text-sm font-semibold text-content-primary truncate">{asm.name}</span>
                          <span className="text-2xs font-mono text-content-quaternary">{asm.code}</span>
                        </div>
                        <div className="flex items-center gap-2 text-xs text-content-tertiary">
                          <span className="inline-flex items-center gap-1 rounded bg-purple-100 dark:bg-purple-900/30 text-purple-700 dark:text-purple-400 px-1.5 py-0.5 text-2xs font-medium">
                            {asm.category || t('assemblies.category_general', { defaultValue: 'General' })}
                          </span>
                          <span>{asm.unit}</span>
                          <span className="font-semibold text-content-primary tabular-nums">{fmt(asm.total_rate)} {asm.currency}</span>
                          {asm.components && (
                            <span className="text-content-quaternary">{t('assemblies.n_components', { defaultValue: '{{count}} components', count: asm.components.length })}</span>
                          )}
                        </div>
                      </div>
                      <div className="flex items-center gap-2 shrink-0">
                        <div className="flex items-center gap-1">
                          <label className="text-2xs text-content-quaternary">{t('boq.quantity_abbr', { defaultValue: 'Qty:' })}</label>
                          <input
                            type="number"
                            min="0.01"
                            step="0.01"
                            value={quantity[asm.id] ?? 1}
                            onChange={(e) => setQuantity((prev) => ({ ...prev, [asm.id]: parseFloat(e.target.value) || 1 }))}
                            className="w-16 h-7 rounded border border-border-light bg-surface-elevated px-1.5 text-xs text-content-primary text-right tabular-nums focus:outline-none focus:ring-1 focus:ring-purple-400"
                          />
                        </div>
                        <Button
                          variant="primary"
                          size="sm"
                          onClick={() => handleApply(asm.id)}
                          loading={isApplying}
                          disabled={applying !== null}
                        >
                          {t('common.apply', { defaultValue: 'Apply' })}
                        </Button>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="px-6 py-3 border-t border-border-light bg-surface-secondary/30 shrink-0">
          <div className="flex items-center justify-between text-2xs text-content-quaternary">
            <span>{t('assemblies.footer_hint', { defaultValue: 'Assemblies are reusable recipes built from cost items and resources' })}</span>
            <button
              onClick={() => { onClose(); navigate('/assemblies'); }}
              className="text-purple-600 hover:text-purple-700 font-medium"
            >
              {t('assemblies.manage_assemblies', { defaultValue: 'Manage Assemblies' })} &rarr;
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

/* ── CostDatabaseSearchModal ─────────────────────────────────────────── */

export function CostDatabaseSearchModal({
  boqId,
  onClose,
  onAdded,
  onSelectForResources,
}: {
  boqId: string;
  onClose: () => void;
  onAdded: () => void;
  /** When provided, the modal operates in "add resource" mode — selected items are passed back instead of added as positions. */
  onSelectForResources?: (item: CostSearchItem) => void;
}) {
  const { t } = useTranslation();
  const [query, setQuery] = useState('');
  const [region, setRegion] = useState('');
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [isAdding, setIsAdding] = useState(false);

  // Load available regions
  const { data: regionsData } = useQuery({
    queryKey: ['cost-regions-modal'],
    queryFn: () => apiGet<string[]>('/v1/costs/regions'),
  });
  const regions = regionsData ?? [];

  // Search cost items with region filter — show first 20 immediately
  const regionParam = region ? `&region=${encodeURIComponent(region)}` : '';
  const searchParam = query.length >= 2 ? `&q=${encodeURIComponent(query)}&semantic=true` : '';
  const { data, isLoading } = useQuery({
    queryKey: ['cost-search-modal', query.length >= 2 ? query : '', region],
    queryFn: () =>
      apiGet<{ items: CostSearchItem[]; total: number }>(
        `/v1/costs/?limit=30${regionParam}${searchParam}`,
      ),
  });

  const items = data?.items ?? [];

  const toggleSelect = useCallback((id: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  const addToast = useToastStore((s) => s.addToast);

  const handleAdd = useCallback(async () => {
    if (selected.size === 0) return;

    // Resource mode: pass the first selected item back
    if (onSelectForResources) {
      const selectedItems = items.filter((i) => selected.has(i.id));
      for (const item of selectedItems) {
        onSelectForResources(item);
      }
      return;
    }

    setIsAdding(true);

    try {
      // Get existing position count for ordinal
      let nextOrd = 1;
      try {
        const existing = await apiGet<unknown[]>(`/v1/boq/boqs/${boqId}/positions`);
        nextOrd = existing.length + 1;
      } catch { /* ignore */ }

      const selectedItems = items.filter((i) => selected.has(i.id));
      for (const item of selectedItems) {
        const ordinal = String(nextOrd).padStart(3, '0');
        // Convert cost item components to position resources
        const resources = (item.components || []).map((c) => ({
          name: c.name,
          code: c.code || '',
          type: c.type || 'other',
          unit: c.unit || 'pcs',
          quantity: c.quantity ?? 1,
          unit_rate: c.unit_rate ?? 0,
          total: c.cost || (c.quantity ?? 1) * (c.unit_rate ?? 0),
        }));
        await apiPost(`/v1/boq/boqs/${boqId}/positions`, {
          boq_id: boqId,
          ordinal,
          description: item.description || 'Unnamed item',
          unit: item.unit || 'pcs',
          quantity: 1,
          unit_rate: item.rate ?? 0,
          classification: item.classification || {},
          source: 'cost_database',
          metadata: {
            cost_item_code: item.code,
            cost_item_region: item.region,
            ...(resources.length > 0 ? { resources } : {}),
          },
        });
        nextOrd++;
      }
      onAdded();
    } catch (err) {
      console.error('Failed to add positions from cost DB:', err);
      addToast({
        type: 'error',
        title: t('boq.add_failed', { defaultValue: 'Failed to add positions' }),
        message: err instanceof Error ? err.message : String(err),
      });
    } finally {
      setIsAdding(false);
    }
  }, [boqId, selected, items, onAdded, onSelectForResources, addToast, t]);

  // Close on Escape
  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === 'Escape') { e.preventDefault(); onClose(); }
    }
    document.addEventListener('keydown', handleKeyDown, { capture: true });
    return () => document.removeEventListener('keydown', handleKeyDown, { capture: true });
  }, [onClose]);

  const fmtRate = (n: number) =>
    new Intl.NumberFormat(getIntlLocale(), { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(n);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40" onClick={onClose} aria-hidden="true">
      <div
        role="dialog"
        aria-modal="true"
        aria-label={onSelectForResources
          ? t('boq.add_resource_from_database', { defaultValue: 'Add Resources from Database' })
          : t('boq.add_from_database', { defaultValue: 'Add from Cost Database' })}
        className="bg-surface-elevated rounded-2xl border border-border shadow-2xl w-full max-w-2xl mx-4 overflow-hidden animate-fade-in"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center gap-3 px-6 py-4 border-b border-border-light">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-oe-blue-subtle text-oe-blue">
            <Database size={18} />
          </div>
          <div className="flex-1">
            <h2 className="text-base font-semibold text-content-primary">
              {onSelectForResources
                ? t('boq.add_resource_from_database', { defaultValue: 'Add Resources from Database' })
                : t('boq.add_from_database', { defaultValue: 'Add from Cost Database' })}
            </h2>
            <p className="text-xs text-content-tertiary">
              {onSelectForResources
                ? t('boq.search_and_add_resources', { defaultValue: 'Search cost items to add as resources to position' })
                : t('boq.search_and_add', { defaultValue: 'Search items and add them to your estimate' })}
            </p>
          </div>
          <button onClick={onClose} aria-label={t('common.close', { defaultValue: 'Close' })} className="flex h-8 w-8 items-center justify-center rounded-lg text-content-tertiary hover:bg-surface-secondary">
            <X size={16} />
          </button>
        </div>

        {/* Region tabs */}
        <div className="px-6 py-2 border-b border-border-light flex items-center gap-1.5 overflow-x-auto scrollbar-none">
          <button
            onClick={() => setRegion('')}
            className={`shrink-0 rounded-md px-2.5 py-1 text-xs font-medium transition-colors ${
              region === ''
                ? 'bg-oe-blue text-white'
                : 'bg-surface-secondary text-content-secondary hover:bg-surface-tertiary'
            }`}
          >
            {t('catalog.all_regions', { defaultValue: 'All databases' })}
          </button>
          {regions.map((r) => {
            const info = REGION_MAP[r];
            const label = info?.name || r;
            const flag = info?.flag;
            const isActive = region === r;
            return (
              <button
                key={r}
                onClick={() => setRegion(r)}
                className={`shrink-0 flex items-center gap-1.5 rounded-md px-2.5 py-1 text-xs font-medium transition-colors ${
                  isActive
                    ? 'bg-oe-blue text-white'
                    : 'bg-surface-secondary text-content-secondary hover:bg-surface-tertiary'
                }`}
              >
                {flag && flag !== 'custom' ? (
                  <CountryFlag code={flag} size={13} />
                ) : flag === 'custom' ? (
                  <span className="text-[10px]">&#9733;</span>
                ) : null}
                <span>{label}</span>
              </button>
            );
          })}
        </div>

        {/* Search */}
        <div className="px-6 py-3 border-b border-border-light">
          <div className="relative">
            <div className="pointer-events-none absolute inset-y-0 left-0 flex items-center pl-3 text-content-tertiary">
              <Search size={16} />
            </div>
            <input
              autoFocus
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder={t('boq.search_cost_items', { defaultValue: 'Search cost items by description...' })}
              aria-label={t('boq.search_cost_items', { defaultValue: 'Search cost items by description...' })}
              className="h-10 w-full rounded-lg border border-border bg-surface-primary pl-10 pr-3 text-sm text-content-primary placeholder:text-content-tertiary focus:outline-none focus:ring-2 focus:ring-oe-blue"
            />
          </div>
        </div>

        {/* Results */}
        <div className="max-h-[400px] overflow-y-auto">
          {isLoading ? (
            <div className="px-6 py-8 text-center">
              <Loader2 size={20} className="mx-auto mb-2 animate-spin text-oe-blue" />
              <p className="text-xs text-content-tertiary">{t('common.loading')}</p>
            </div>
          ) : items.length === 0 ? (
            <div className="px-6 py-8 text-center">
              <p className="text-sm text-content-tertiary">
                {t('boq.no_items_found', { defaultValue: 'No matching items found' })}
              </p>
            </div>
          ) : (
            <table className="w-full text-sm">
              <thead className="bg-surface-tertiary sticky top-0">
                <tr>
                  <th className="px-3 py-2 w-8" />
                  <th className="px-3 py-2 text-left text-xs font-medium text-content-secondary">{t('boq.description')}</th>
                  <th className="px-3 py-2 text-center text-xs font-medium text-content-secondary w-16">{t('boq.unit')}</th>
                  <th className="px-3 py-2 text-right text-xs font-medium text-content-secondary w-24">{t('costs.rate', 'Rate')}</th>
                  <th className="px-3 py-2 text-center text-xs font-medium text-content-secondary w-20">
                    {t('boq.region', { defaultValue: 'Database' })}
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border-light">
                {items.map((item) => {
                  const isSel = selected.has(item.id);
                  return (
                    <tr
                      key={item.id}
                      onClick={() => toggleSelect(item.id)}
                      className={`cursor-pointer transition-colors ${isSel ? 'bg-oe-blue-subtle/20' : 'hover:bg-surface-secondary/50'}`}
                    >
                      <td className="px-3 py-2.5">
                        <div className={`h-4 w-4 rounded border-2 flex items-center justify-center ${isSel ? 'border-oe-blue bg-oe-blue' : 'border-content-quaternary'}`}>
                          {isSel && <Check size={10} className="text-white" />}
                        </div>
                      </td>
                      <td className="px-3 py-2.5 max-w-[300px]">
                        <span className="text-content-primary truncate block" title={item.description}>{item.description}</span>
                        <span className="text-2xs text-content-quaternary font-mono">{item.code}</span>
                      </td>
                      <td className="px-3 py-2.5 text-center">
                        <Badge variant="neutral" size="sm">{item.unit}</Badge>
                      </td>
                      <td className="px-3 py-2.5 text-right font-semibold tabular-nums text-content-primary">
                        {fmtRate(item.rate)}
                      </td>
                      <td className="px-3 py-2.5 text-center">
                        {(() => {
                          const info = item.region ? REGION_MAP[item.region] : null;
                          if (!info) return <span className="text-2xs text-content-quaternary">&mdash;</span>;
                          return (
                            <span className="inline-flex items-center gap-1 text-2xs text-content-tertiary">
                              {info.flag && info.flag !== 'custom' && (
                                <CountryFlag code={info.flag} size={11} />
                              )}
                              <span className="truncate max-w-[60px]">{info.label?.split(' ')[0] || item.region}</span>
                            </span>
                          );
                        })()}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between px-6 py-3 border-t border-border-light bg-surface-secondary/30">
          <span className="text-xs text-content-tertiary">
            {selected.size > 0
              ? `${selected.size} ${t('boq.items_selected', { defaultValue: 'items selected' })}`
              : t('boq.click_to_select', { defaultValue: 'Click rows to select' })}
          </span>
          <div className="flex items-center gap-2">
            <Button variant="secondary" size="sm" onClick={onClose}>
              {t('common.cancel', 'Cancel')}
            </Button>
            <Button
              variant="primary"
              size="sm"
              disabled={selected.size === 0 || isAdding}
              icon={isAdding ? <Loader2 size={14} className="animate-spin" /> : <Plus size={14} />}
              onClick={handleAdd}
            >
              {isAdding
                ? t('boq.adding', { defaultValue: 'Adding...' })
                : onSelectForResources
                  ? t('boq.add_as_resources', { defaultValue: 'Add {{count}} as resources', count: selected.size })
                  : t('boq.add_n_positions', { defaultValue: 'Add {{count}} to BOQ', count: selected.size })}
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
