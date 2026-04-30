/**
 * BOQModals — Cost Database Search Modal and Assembly Picker Modal
 * for the BOQ Editor.
 *
 * Extracted from BOQEditorPage.tsx for modularity.
 */

import { useState, useCallback, useEffect, useMemo, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import {
  useInfiniteQuery,
  useQuery,
  useQueryClient,
} from '@tanstack/react-query';
import {
  Plus,
  X,
  Search,
  Loader2,
  Check,
  Layers,
  Database,
  ChevronDown,
  AlertCircle,
} from 'lucide-react';
import { Button, Badge, CountryFlag } from '@/shared/ui';
import { apiGet, apiPost } from '@/shared/lib/api';
import { getIntlLocale } from '@/shared/lib/formatters';
import { useToastStore } from '@/stores/useToastStore';
import { REGION_MAP } from '@/stores/useCostDatabaseStore';
import { VariantPicker } from '@/features/costs/VariantPicker';
import type { CostVariant } from '@/features/costs/api';
import {
  fetchCategoryTree,
  fetchCostSearch,
  type CostSearchItem as ApiCostSearchItem,
  type CostSearchPage,
} from './api';
import { CostCategoryTree } from './CostCategoryTree';

/* ── Types ───────────────────────────────────────────────────────────── */

/**
 * Local alias — narrows the canonical ``ApiCostSearchItem`` so the existing
 * variant-picker integration code (which reads ``metadata_.variants`` and
 * ``metadata_.variant_stats`` as concrete CWICR shapes) keeps its types.
 *
 * The canonical type stores ``metadata_`` as ``Record<string, unknown>`` so
 * the API surface stays generic.  We re-narrow here without using ``any`` or
 * ``as unknown as`` — TS happily accepts the broader source.
 */
type CostSearchItem = Omit<ApiCostSearchItem, 'metadata_'> & {
  metadata_?: {
    variants?: CostVariant[];
    variant_stats?: import('@/features/costs/api').VariantStats;
    [key: string]: unknown;
  };
};

/** Pending variant pick — stored in state so the picker can render once
 *  outside the multi-item add loop and the loop can resolve sequentially.
 *
 *  Resolution shape:
 *    `{ kind: 'variant', variant }` — explicit user pick.
 *    `{ kind: 'default', strategy }` — user clicked "Use average".
 *    `null` — cancelled.
 */
type VariantResolution =
  | { kind: 'variant'; variant: CostVariant }
  | { kind: 'default'; strategy: 'mean' | 'median' };

interface PendingVariantPick {
  item: CostSearchItem;
  resolve: (chosen: VariantResolution | null) => void;
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
      await apiPost(`/v1/assemblies/${assemblyId}/apply-to-boq/`, {
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
  /** When provided, the modal operates in "add resource" mode — selected items
   *  are passed back instead of added as positions. The optional second arg
   *  carries the user's variant choice when the item had 2+ variants; resource
   *  rate / variant marker are persisted by the caller on the resource entry. */
  onSelectForResources?: (item: CostSearchItem, picked?: VariantResolution) => void;
}) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [query, setQuery] = useState('');
  // Region: empty means no filter (legacy "All databases" behaviour).
  // On mount we auto-pick the first country DB once regions load, so the
  // initial result set is fast (single-region scan, ~1 s) instead of the
  // 10+ s "all databases" scan. The "All databases" tab is still rendered
  // at the end of the row so the user can opt in to the multi-region view.
  const [region, setRegion] = useState('');
  const regionDefaultedRef = useRef(false);
  // Distinguishes user-initiated region changes (tab click) from the
  // auto-default. Path-reset only fires on user clicks — the auto-default
  // mustn't wipe a path the user clicked on before regions resolved.
  const userPickedRegionRef = useRef(false);
  const setRegionByUser = useCallback((r: string) => {
    userPickedRegionRef.current = true;
    setRegion(r);
  }, []);
  /** Slash-joined classification breadcrumb selected in the left tree.
   *  Empty string = "All categories". */
  const [selectedPath, setSelectedPath] = useState('');
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [isAdding, setIsAdding] = useState(false);
  const [activeVariantPick, setActiveVariantPick] = useState<PendingVariantPick | null>(null);
  /** Mobile-only popover for the category tree.  Hidden on >=md viewports. */
  const [mobileTreeOpen, setMobileTreeOpen] = useState(false);
  const addButtonRef = useRef<HTMLButtonElement>(null);
  const listScrollRef = useRef<HTMLDivElement>(null);
  const sentinelRef = useRef<HTMLDivElement>(null);
  const cursorErrorToastShown = useRef(false);
  const addToast = useToastStore((s) => s.addToast);

  // Load available regions
  const { data: regionsData } = useQuery({
    queryKey: ['cost-regions-modal'],
    queryFn: () => apiGet<string[]>('/v1/costs/regions/'),
  });
  const regions = useMemo(() => regionsData ?? [], [regionsData]);

  // Category tree — separate query, scoped to active region.  5-min staleTime
  // matches the backend's cache TTL so we don't refetch on every interaction.
  const {
    data: categoryTree,
    isLoading: treeLoading,
    isError: treeError,
    refetch: refetchTree,
  } = useQuery({
    queryKey: ['cost-tree', region],
    queryFn: () => fetchCategoryTree(region || undefined),
    staleTime: 5 * 60 * 1000,
  });

  // Paginated infinite search.  Cursor-based — when ``next_cursor`` is null,
  // ``hasNextPage`` flips to false and ``fetchNextPage`` is a no-op.
  const {
    data: searchData,
    isLoading,
    isError: searchError,
    error: searchErrorObj,
    hasNextPage,
    isFetchingNextPage,
    fetchNextPage,
    refetch: refetchSearch,
  } = useInfiniteQuery<CostSearchPage, Error>({
    queryKey: [
      'cost-search',
      region,
      query.length >= 2 ? query : '',
      selectedPath,
    ],
    queryFn: ({ pageParam }) =>
      fetchCostSearch({
        region: region || undefined,
        q: query.length >= 2 ? query : undefined,
        classification_path: selectedPath || undefined,
        cursor: (pageParam as string | null) ?? null,
        limit: 50,
      }),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next_cursor,
    // Wait for the regions list before firing the search. Without this we
    // burn a 10+ s "all regions" scan on mount, then re-fire 1 s later
    // with the auto-defaulted country DB (see effect below). Skipping the
    // first fetch is also what keeps tests deterministic — only one fetch
    // per (region × path × query) tuple, never an intermediate Loading...
    // race during the queryKey flip.
    enabled: regionsData !== undefined,
  });

  // Recover from a stale cursor (server returns 400 when the cursor format
  // changes after a deploy).  One-shot toast + cache reset so subsequent
  // refetches start fresh from the first page.
  useEffect(() => {
    if (!searchError) {
      cursorErrorToastShown.current = false;
      return;
    }
    const msg = searchErrorObj instanceof Error ? searchErrorObj.message : '';
    if (/cursor|400/i.test(msg) && !cursorErrorToastShown.current) {
      cursorErrorToastShown.current = true;
      addToast({
        type: 'info',
        title: t('boq.cursor_error_title', {
          defaultValue: 'Loading older results failed — refreshing',
        }),
      });
      // Drop pages so the next fetch starts at cursor=null.
      queryClient.removeQueries({
        queryKey: ['cost-search', region, query.length >= 2 ? query : '', selectedPath],
      });
      refetchSearch();
    }
  }, [
    searchError,
    searchErrorObj,
    addToast,
    t,
    queryClient,
    region,
    query,
    selectedPath,
    refetchSearch,
  ]);

  // Flatten pages for rendering.  Empty pages array → empty items.
  const items: CostSearchItem[] = useMemo(() => {
    if (!searchData) return [];
    const flat: CostSearchItem[] = [];
    for (const page of searchData.pages) {
      for (const item of page.items) {
        flat.push(item as CostSearchItem);
      }
    }
    return flat;
  }, [searchData]);

  // Total count is only known on the first page.  Subsequent pages get null.
  const totalCount = searchData?.pages[0]?.total ?? null;

  // IntersectionObserver-driven auto-load.  Only attaches when there's a
  // sentinel in the DOM AND another page exists.  Re-runs whenever the active
  // query key flips (e.g. region change → fresh observer for the new list).
  // Older runtimes (IE11, JSDOM-based test envs) lack the API; the visible
  // "Load more" fallback button keeps pagination usable in those cases.
  useEffect(() => {
    const node = sentinelRef.current;
    if (!node || !hasNextPage) return;
    if (typeof IntersectionObserver === 'undefined') return;

    const root = listScrollRef.current ?? null;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting) && !isFetchingNextPage) {
          fetchNextPage();
        }
      },
      { root, rootMargin: '200px 0px', threshold: 0 },
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, [hasNextPage, isFetchingNextPage, fetchNextPage, items.length]);

  // Region change resets selected path + scroll, and invalidates the tree
  // cache for the previous region (fresh fetch on next visit). Gated on
  // `userPickedRegionRef` so the on-mount auto-default does NOT wipe a
  // path the user clicked on before the regions response landed.
  const previousRegionRef = useRef(region);
  useEffect(() => {
    if (previousRegionRef.current === region) return;
    previousRegionRef.current = region;
    if (!userPickedRegionRef.current) return;
    setSelectedPath('');
    setSelected(new Set());
    if (listScrollRef.current) {
      listScrollRef.current.scrollTop = 0;
    }
    queryClient.invalidateQueries({ queryKey: ['cost-tree'] });
  }, [region, queryClient]);

  // Auto-default the region to the first country DB once regions arrive.
  useEffect(() => {
    if (regionDefaultedRef.current) return;
    const first = regions[0];
    if (!first) return;
    regionDefaultedRef.current = true;
    setRegion(first);
  }, [regions]);



  const handleSelectPath = useCallback((path: string) => {
    setSelectedPath(path);
    setMobileTreeOpen(false);
    if (listScrollRef.current) {
      listScrollRef.current.scrollTop = 0;
    }
  }, []);

  const toggleSelect = useCallback((id: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  const handleAdd = useCallback(async () => {
    if (selected.size === 0) return;

    // Resource mode: pass each selected item back. When an item carries 2+
    // CWICR abstract-resource variants, open the picker FIRST so the chosen
    // variant rate is what lands on the resource entry — and the caller can
    // stamp `metadata.resources[i].variant`/`variant_default` for backend
    // snapshotting via `_stamp_resource_variant_snapshots`.
    if (onSelectForResources) {
      const selectedItems = items.filter((i) => selected.has(i.id));

      const pickVariantForResource = (
        item: CostSearchItem,
      ): Promise<VariantResolution | null> =>
        new Promise((resolve) => {
          setActiveVariantPick({ item, resolve });
        });

      for (const item of selectedItems) {
        const variants = item.metadata_?.variants;
        const stats = item.metadata_?.variant_stats;
        let picked: VariantResolution | undefined;
        if (variants && variants.length >= 2 && stats) {
          const resolution = await pickVariantForResource(item);
          // Cancelled — skip this item, keep iterating.
          if (!resolution) continue;
          picked = resolution;
        }
        onSelectForResources(item, picked);
      }
      return;
    }

    setIsAdding(true);

    try {
      // Fetch BOQ detail to find the max existing ordinal for unique numbering
      let nextOrdNum = 1;
      try {
        const boqData = await apiGet<{ positions?: Array<{ ordinal: string }> }>(
          `/v1/boq/boqs/${boqId}`,
        );
        const positions = boqData.positions ?? [];
        if (positions.length > 0) {
          // Parse all ordinal numeric parts and find the max
          let maxNum = 0;
          for (const p of positions) {
            const parts = p.ordinal.split('.');
            for (const part of parts) {
              const n = parseInt(part, 10);
              if (!isNaN(n) && n > maxNum) maxNum = n;
            }
          }
          nextOrdNum = maxNum + 1;
        }
      } catch {
        /* ignore — start at 1 */
      }

      const selectedItems = items.filter((i) => selected.has(i.id));

      // Promise wrapper around the variant picker — used only when a cost
      // item carries 2+ CWICR abstract-resource variants.  Cancelling the
      // picker (Esc / Cancel / outside-click) resolves with `null` and the
      // outer loop skips that item but continues with the rest.  Resolving
      // with `{ kind: 'default' }` honours the "Use average" CTA and writes
      // `variant_default` instead of a per-row pick on the position.
      const pickVariant = (item: CostSearchItem): Promise<VariantResolution | null> =>
        new Promise((resolve) => {
          setActiveVariantPick({ item, resolve });
        });

      let variantToastShown = false;
      let defaultToastShown = false;

      for (const item of selectedItems) {
        const variants = item.metadata_?.variants;
        const stats = item.metadata_?.variant_stats;
        let resolution: VariantResolution | null = null;

        if (variants && variants.length >= 2 && stats) {
          resolution = await pickVariant(item);
          // Cancelled — skip THIS item but keep going with the rest.
          if (!resolution) continue;
        }

        const section = String(Math.floor((nextOrdNum - 1) / 999) + 1).padStart(2, '0');
        const pos = String(((nextOrdNum - 1) % 999) + 1).padStart(3, '0');
        const ordinal = `${section}.${pos}`;
        // Convert cost item components to position resources.
        //
        // Per-component variants (v2.6.30+): the backend stamps
        // ``available_variants`` + ``available_variant_stats`` on each
        // abstract-resource component slot. Forward those onto the
        // resource entry so the BOQ row exposes a dedicated re-pick pill
        // per variant resource — supporting positions with MANY
        // independent variant components (concrete grade + rebar type +
        // formwork type, ...). Auto-default to the median rate so the
        // resource has a working price out of the box; the amber
        // provenance bar + per-resource pill make it discoverable for
        // refinement.
        const resources: Array<{
          name: string;
          code: string;
          type: string;
          unit: string;
          quantity: number;
          unit_rate: number;
          total: number;
          variant?: { label: string; price: number; index: number };
          variant_default?: 'mean' | 'median';
          available_variants?: CostVariant[];
          available_variant_stats?: import('@/features/costs/api').VariantStats;
        }> = (item.components || []).map((c) => {
          const compVariants = c.available_variants;
          const compStats = c.available_variant_stats;
          const hasCompVariants =
            Array.isArray(compVariants) &&
            compVariants.length >= 2 &&
            compStats != null;
          return {
            name: c.name,
            code: c.code || '',
            type: c.type || 'other',
            unit: c.unit || 'pcs',
            quantity: c.quantity ?? 1,
            unit_rate: c.unit_rate ?? 0,
            total: c.cost || (c.quantity ?? 1) * (c.unit_rate ?? 0),
            ...(hasCompVariants
              ? {
                  variant_default: 'median' as const,
                  available_variants: compVariants,
                  available_variant_stats: compStats,
                }
              : {}),
          };
        });

        // Resolve description + variant metadata from the resolution.
        const baseDescription = item.description || 'Unnamed item';
        const description = baseDescription;
        let variantMeta: Record<string, unknown> = {};

        // Currency for the variant resource entry — falls back to the
        // catalog's native currency, then EUR.
        const itemCurrency = item.currency && item.currency.trim() ? item.currency : 'EUR';
        // common_start is the abstract resource's base name
        // (price_abstract_resource_common_start). When non-empty it is the
        // shared prefix every variant variable_part hangs off of (e.g.
        // "Beton, Sortenliste C"). When empty (CWICR rows whose abstract
        // resource doesn't carry a separate base) we DO NOT fall back to
        // the cost item description — that just duplicates the rate-code
        // text in front of an already-full variant label and produced the
        // "Realizzazione di piattaforme... Bandstahl warmgewalzt..." mess
        // user reported. In the empty-CS case the variant's full_label
        // already carries the complete display name on its own.
        const commonStart =
          (stats?.common_start && stats.common_start.trim()) || '';

        if (resolution?.kind === 'variant') {
          variantMeta = {
            variant: {
              label: resolution.variant.label,
              price: resolution.variant.price,
              index: resolution.variant.index,
            },
          };
          // Persist the variant catalog ON the resource entry as well so
          // the per-resource re-pick pill (EditableResourceRow / ResourceSummary)
          // can fire without an extra fetch. This is what enables a position
          // to carry MULTIPLE independent variant resources — every resource
          // with its own ``available_variants`` gets its own picker pill in
          // the expanded resource panel.
          // Append the variant as an additional resource line so the
          // position's total = sum of all resource totals (the contract
          // the user expects: "если есть ресурсы — стоимость собирается
          // из общей стоимости ресурсов"). Without this, position.unit_rate
          // would lose the variant's contribution and the resource panel
          // total would diverge from the cell display.
          //
          // Resource name resolution priority:
          //   1. The variant's own ``full_label`` (backend already composes
          //      ``common_start + variable_part``, truncated to 400 chars).
          //   2. ``${common_start} ${variant.label}`` when full_label is
          //      missing (pre-v2.6.30 imports) but common_start is captured.
          //   3. ``variant.label`` alone — for CWICR rows whose abstract
          //      resource has no separate common_start (the label already
          //      carries the full display text). Falls back to baseDescription
          //      only when the label is also empty (defensive).
          const variantFullLabel = (resolution.variant.full_label || '').trim();
          const variantLabel = (resolution.variant.label || '').trim();
          const composedName = variantFullLabel
            || (commonStart && variantLabel
                ? `${commonStart} ${variantLabel}`.trim()
                : variantLabel)
            || baseDescription;
          resources.push({
            name: composedName,
            code: item.code,
            type: 'material',
            unit: item.unit || 'pcs',
            quantity: 1,
            unit_rate: resolution.variant.price,
            total: resolution.variant.price,
            variant: {
              label: resolution.variant.label,
              price: resolution.variant.price,
              index: resolution.variant.index,
            },
            // available_variants + stats carried on the resource so the
            // per-resource picker (EditableResourceRow's ▾ pill) opens
            // immediately on click — independent of any other variant
            // resource on the same position.
            available_variants: variants,
            available_variant_stats: stats,
          });
        } else if (resolution?.kind === 'default') {
          // Mean is the production default; median is exposed only by
          // legacy callers.  Fall back to median if mean is zero (defensive).
          const stats2 = item.metadata_!.variant_stats!;
          const meanRate = stats2.mean;
          const medianRate = stats2.median;
          const defaultRate =
            resolution.strategy === 'mean' && meanRate > 0
              ? meanRate
              : medianRate > 0
                ? medianRate
                : (item.rate ?? 0);
          variantMeta = {
            variant_default: resolution.strategy,
          };
          // Default-pick name = the abstract base (common_start) when the
          // CWICR row carries one, otherwise the cost item description.
          // No variable_part is chosen yet, so we cannot compose
          // common_start + variable_part — the row will show only the base
          // until the user explicitly picks a variant via the re-pick pill.
          resources.push({
            name: commonStart || baseDescription,
            code: item.code,
            type: 'material',
            unit: item.unit || 'pcs',
            quantity: 1,
            unit_rate: defaultRate,
            total: defaultRate,
            variant_default: resolution.strategy,
            // Carry the variant catalog on the resource so the user can
            // refine the auto-default into an explicit pick later via the
            // per-resource re-pick pill.
            available_variants: variants,
            available_variant_stats: stats,
          });
        }

        // unit_rate = sum of all resource totals when resources exist,
        // otherwise fall back to the catalog rate (positions without a
        // component breakdown still need a price).
        const resourcesTotal = resources.reduce((s, r) => s + (r.total ?? 0), 0);
        const unitRate = resources.length > 0 ? resourcesTotal : (item.rate ?? 0);
        // Stamp catalog-native currency on every resource line so the
        // BOQ row's per-resource currency cell shows it correctly.
        for (const r of resources) {
          (r as Record<string, unknown>).currency = itemCurrency;
        }

        // Cache the variant set on the position metadata so the inline
        // picker on the BOQ row can re-open without an extra fetch.  The
        // backend `_stamp_variant_snapshot` will also use these for the
        // immutability snapshot.
        const variantCacheMeta: Record<string, unknown> = {};
        if (variants && variants.length >= 2 && stats) {
          variantCacheMeta.cost_item_variants = variants;
          variantCacheMeta.cost_item_variant_stats = stats;
          variantCacheMeta.cost_item_variant_count = stats.count;
          variantCacheMeta.cost_item_variant_mean = stats.mean;
          variantCacheMeta.cost_item_variant_min = stats.min;
          variantCacheMeta.cost_item_variant_max = stats.max;
        }

        await apiPost(`/v1/boq/boqs/${boqId}/positions/`, {
          boq_id: boqId,
          ordinal,
          description,
          unit: item.unit || 'pcs',
          quantity: 1,
          unit_rate: unitRate,
          classification: item.classification || {},
          source: 'cost_database',
          metadata: {
            cost_item_code: item.code,
            cost_item_region: item.region,
            cost_item_id: item.id,
            // Resolve currency: catalog field (now populated server-side
            // via _resolve_currency) → region map fallback → EUR. Avoid
            // the legacy "USD" default, which mislabelled every RU/RO/UK
            // rate when the catalog row had an empty currency string.
            currency:
              (item.currency && item.currency.trim()) ||
              (item.region && REGION_MAP[item.region]?.currency) ||
              'EUR',
            ...variantCacheMeta,
            ...variantMeta,
            ...(resources.length > 0 ? { resources } : {}),
            // Carry the catalog's scope-of-work bullets onto the new
            // position so the BOQ grid can render the (i) hint next
            // to the description. The CWICR loader populates this for
            // every region with non-empty ``work_composition_text``.
            ...(Array.isArray((item.metadata_ as Record<string, unknown> | undefined)?.scope_of_work) &&
            ((item.metadata_ as Record<string, unknown>).scope_of_work as unknown[]).length > 0
              ? { scope_of_work: (item.metadata_ as Record<string, unknown>).scope_of_work }
              : {}),
          },
        });

        if (resolution?.kind === 'variant' && !variantToastShown) {
          addToast({
            type: 'success',
            title: t('boq.variant_applied', {
              defaultValue: 'Variant applied: {{label}}',
              label: resolution.variant.label,
            }),
          });
          variantToastShown = true;
        } else if (resolution?.kind === 'default' && !defaultToastShown) {
          addToast({
            type: 'info',
            title: t('boq.variant_default_applied_title', {
              defaultValue: 'Applied with average price',
            }),
            message: t('boq.variant_default_applied_msg', {
              defaultValue:
                'Click the row in the BOQ to choose a specific variant.',
            }),
          });
          defaultToastShown = true;
        }

        nextOrdNum++;
      }
      onAdded();
    } catch (err) {
      if (import.meta.env.DEV) console.error('Failed to add positions from cost DB:', err);
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

  // Compose the count label.  When ``totalCount`` is known we render the
  // canonical "{{loaded}} of {{total}}" form; while still loading more pages
  // without a known total we show "{{loaded}}+ items".
  const countLabel = (() => {
    if (isLoading && items.length === 0) {
      return t('boq.tree_loading', { defaultValue: 'Loading...' });
    }
    if (totalCount != null) {
      return t('boq.loaded_n_of_m', {
        defaultValue: '{{loaded}} of {{total}} items',
        loaded: items.length.toLocaleString(),
        total: totalCount.toLocaleString(),
      });
    }
    return t('boq.cost_results_count', {
      defaultValue: '{{loaded}}+ items',
      loaded: items.length.toLocaleString(),
    });
  })();

  // Active filter chips — selected category breadcrumb + free-text query.
  const hasActiveFilters = selectedPath !== '' || query.length >= 2;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40" onClick={onClose} aria-hidden="true">
      <div
        role="dialog"
        aria-modal="true"
        aria-label={onSelectForResources
          ? t('boq.add_resource_from_database', { defaultValue: 'Add Resources from Database' })
          : t('boq.add_from_database', { defaultValue: 'Add from Cost Database' })}
        className="bg-surface-elevated rounded-2xl border border-border shadow-2xl w-full max-w-6xl mx-4 max-h-[88vh] overflow-hidden animate-fade-in flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center gap-3 px-6 py-4 border-b border-border-light shrink-0">
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

        {/* Region tabs — country DBs first, "All databases" pushed to the
            end of the row. The first country DB is auto-selected on mount
            (see defaulting effect above) so the initial paint is fast,
            and "All databases" remains accessible for the user who wants
            the multi-region view. */}
        <div className="px-6 py-2 border-b border-border-light flex items-center gap-1.5 overflow-x-auto scrollbar-none shrink-0">
          {regions.map((r) => {
            const info = REGION_MAP[r];
            const label = info?.name || r;
            const flag = info?.flag;
            const isActive = region === r;
            return (
              <button
                key={r}
                onClick={() => setRegionByUser(r)}
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
          <button
            onClick={() => setRegionByUser('')}
            className={`shrink-0 rounded-md px-2.5 py-1 text-xs font-medium transition-colors ${
              region === ''
                ? 'bg-oe-blue text-white'
                : 'bg-surface-secondary text-content-secondary hover:bg-surface-tertiary'
            }`}
          >
            {t('catalog.all_regions', { defaultValue: 'All databases' })}
          </button>
        </div>

        {/* Two-pane body: tree (left) + search/list (right) */}
        <div className="flex flex-1 min-h-0 overflow-hidden">
          {/* Left: category tree.  Hidden on mobile; popover variant rendered
              inside the right pane via mobileTreeOpen.  Desktop sidebar is
              fixed-width (w-72) with its own scroll. */}
          <aside
            className="hidden md:flex w-72 shrink-0 flex-col border-r border-border-light bg-surface-secondary/30"
            data-testid="cost-modal-sidebar"
          >
            <div className="px-3 pt-3 pb-1 text-2xs font-semibold uppercase tracking-wide text-content-tertiary">
              {t('boq.cost_tree_title', { defaultValue: 'Categories' })}
            </div>
            {treeLoading ? (
              <div className="flex flex-1 items-center justify-center text-xs text-content-tertiary">
                <Loader2 size={14} className="mr-1.5 animate-spin" />
                {t('boq.tree_loading', { defaultValue: 'Loading...' })}
              </div>
            ) : treeError ? (
              <div className="px-3 py-4 text-center">
                <AlertCircle size={16} className="mx-auto mb-1.5 text-semantic-error" />
                <p className="mb-2 text-2xs text-content-tertiary">
                  {t('boq.cost_tree_error', {
                    defaultValue: 'Could not load categories',
                  })}
                </p>
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => refetchTree()}
                >
                  {t('common.retry', { defaultValue: 'Retry' })}
                </Button>
              </div>
            ) : (
              <CostCategoryTree
                tree={categoryTree ?? []}
                selectedPath={selectedPath}
                onSelect={handleSelectPath}
                t={t}
              />
            )}
          </aside>

          {/* Right pane */}
          <div className="flex flex-1 min-w-0 flex-col">
            {/* Search */}
            <div className="px-6 py-3 border-b border-border-light shrink-0 flex items-center gap-2">
              {/* Mobile-only "Categories" toggle */}
              <button
                type="button"
                onClick={() => setMobileTreeOpen((v) => !v)}
                className="md:hidden flex items-center gap-1 rounded-md border border-border-light bg-surface-primary px-2 py-1.5 text-xs text-content-secondary"
                aria-expanded={mobileTreeOpen}
              >
                <span>{t('boq.cost_tree_title', { defaultValue: 'Categories' })}</span>
                <ChevronDown size={12} />
              </button>
              <div className="relative flex-1">
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

            {/* Mobile category-tree popover */}
            {mobileTreeOpen && (
              <div className="md:hidden border-b border-border-light bg-surface-secondary/30 max-h-72 overflow-hidden flex flex-col">
                {treeLoading ? (
                  <div className="px-3 py-4 text-center text-xs text-content-tertiary">
                    <Loader2 size={14} className="mx-auto animate-spin" />
                  </div>
                ) : treeError ? (
                  <div className="px-3 py-4 text-center">
                    <p className="mb-2 text-2xs text-content-tertiary">
                      {t('boq.cost_tree_error', {
                        defaultValue: 'Could not load categories',
                      })}
                    </p>
                    <Button variant="secondary" size="sm" onClick={() => refetchTree()}>
                      {t('common.retry', { defaultValue: 'Retry' })}
                    </Button>
                  </div>
                ) : (
                  <CostCategoryTree
                    tree={categoryTree ?? []}
                    selectedPath={selectedPath}
                    onSelect={handleSelectPath}
                    t={t}
                  />
                )}
              </div>
            )}

            {/* Active filter chips + result count */}
            <div className="flex items-center gap-2 px-6 py-2 border-b border-border-light shrink-0 text-2xs text-content-tertiary flex-wrap">
              <span data-testid="cost-results-count">{countLabel}</span>
              {hasActiveFilters && <span className="text-content-quaternary">·</span>}
              {selectedPath && (
                <span
                  data-testid="filter-chip-category"
                  className="inline-flex items-center gap-1 rounded-full bg-oe-blue-subtle/60 text-oe-blue px-2 py-0.5 text-2xs font-medium"
                >
                  <span title={selectedPath} className="max-w-[200px] truncate">
                    {selectedPath
                      .split('/')
                      .map((seg) =>
                        seg === '__unspecified__'
                          ? t('boq.uncategorized', { defaultValue: '(Uncategorized)' })
                          : seg,
                      )
                      .join(' / ')}
                  </span>
                  <button
                    type="button"
                    onClick={() => handleSelectPath('')}
                    aria-label={t('boq.clear_filter', { defaultValue: 'Clear filter' })}
                    className="hover:text-oe-blue-active"
                  >
                    <X size={10} />
                  </button>
                </span>
              )}
              {query.length >= 2 && (
                <span
                  data-testid="filter-chip-query"
                  className="inline-flex items-center gap-1 rounded-full bg-surface-tertiary text-content-secondary px-2 py-0.5 text-2xs font-medium"
                >
                  <Search size={10} />
                  <span className="max-w-[140px] truncate">{query}</span>
                  <button
                    type="button"
                    onClick={() => setQuery('')}
                    aria-label={t('boq.clear_filter', { defaultValue: 'Clear filter' })}
                    className="hover:text-content-primary"
                  >
                    <X size={10} />
                  </button>
                </span>
              )}
            </div>

            {/* Results */}
            <div
              ref={listScrollRef}
              className="flex-1 overflow-y-auto"
              data-testid="cost-results-scroll"
            >
              {isLoading ? (
                <div className="px-6 py-8 text-center">
                  <Loader2 size={20} className="mx-auto mb-2 animate-spin text-oe-blue" />
                  <p className="text-xs text-content-tertiary">{t('common.loading')}</p>
                </div>
              ) : items.length === 0 ? (
                regions.length === 0 && query.length < 2 && !region && !selectedPath ? (
                  <div className="px-6 py-10 text-center">
                    <div className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-full bg-oe-blue-subtle/40">
                      <Database size={22} className="text-oe-blue" />
                    </div>
                    <h3 className="mb-1 text-sm font-semibold text-content-primary">
                      {t('boq.no_databases_title', {
                        defaultValue: 'No cost database installed yet',
                      })}
                    </h3>
                    <p className="mx-auto mb-4 max-w-sm text-xs text-content-tertiary">
                      {t('boq.no_databases_help', {
                        defaultValue:
                          "There's no cost-rate database on this server, so search has nothing to show. Import a free CWICR pack — 30 regional databases are one click away.",
                      })}
                    </p>
                    <Button
                      size="sm"
                      onClick={() => {
                        onClose();
                        navigate('/costs/import');
                      }}
                      icon={<Plus size={14} />}
                    >
                      {t('boq.import_database_cta', {
                        defaultValue: 'Import a database',
                      })}
                    </Button>
                  </div>
                ) : (
                  <div className="px-6 py-8 text-center">
                    <p className="text-sm text-content-tertiary">
                      {t('boq.no_items_found', { defaultValue: 'No matching items found' })}
                    </p>
                  </div>
                )
              ) : (
                <table className="w-full text-sm">
                  <thead className="bg-surface-tertiary sticky top-0 z-10">
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
                          <td className="px-3 py-2.5 max-w-[420px]">
                            <span className="text-content-primary truncate block" title={item.description}>{item.description}</span>
                            <span className="text-2xs text-content-quaternary font-mono">{item.code}</span>
                          </td>
                          <td className="px-3 py-2.5 text-center">
                            <Badge variant="neutral" size="sm">{item.unit}</Badge>
                          </td>
                          <td className="px-3 py-2.5 text-right font-semibold tabular-nums text-content-primary">
                            <div className="inline-flex items-center gap-1.5">
                              <span>{fmtRate(item.rate)}</span>
                              {(() => {
                                const vc = item.metadata_?.variant_stats?.count ?? 0;
                                const vs = item.metadata_?.variant_stats;
                                if (vc < 2 || !vs) return null;
                                return (
                                  <Badge variant="blue" size="sm" className="text-2xs">
                                    <span title={`${fmtRate(vs.min)} – ${fmtRate(vs.max)}`}>
                                      {t('costs.variants_count', { count: vc, defaultValue: '{{count}} variants' })}
                                    </span>
                                  </Badge>
                                );
                              })()}
                            </div>
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

              {/* Infinite-scroll sentinel + Load-more fallback button.
                  The button is purely a fallback for environments where
                  IntersectionObserver fails (older browsers, JSDOM). */}
              {items.length > 0 && hasNextPage && (
                <div
                  ref={sentinelRef}
                  data-testid="cost-results-sentinel"
                  className="flex items-center justify-center py-3"
                >
                  {isFetchingNextPage ? (
                    <span className="inline-flex items-center gap-1.5 text-2xs text-content-tertiary">
                      <Loader2 size={12} className="animate-spin" />
                      {t('boq.tree_loading', { defaultValue: 'Loading...' })}
                    </span>
                  ) : (
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => fetchNextPage()}
                    >
                      {t('boq.load_more', { defaultValue: 'Load more' })}
                    </Button>
                  )}
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between px-6 py-3 border-t border-border-light bg-surface-secondary/30 shrink-0">
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
              ref={addButtonRef}
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

      {/* Variant picker — anchored to the Add button so positioning is
          stable across the multi-item add loop.  Rendered outside the
          modal's overflow:hidden body via createPortal in VariantPicker.
          Default strategy is "mean" (matches CostX/iTWO defaults); the
          legacy "median" tag in the Cost-DB browser remains available
          via the `defaultStrategy` prop on direct callers. */}
      {activeVariantPick && activeVariantPick.item.metadata_?.variants
        && activeVariantPick.item.metadata_?.variant_stats && (
        <VariantPicker
          variants={activeVariantPick.item.metadata_.variants}
          stats={activeVariantPick.item.metadata_.variant_stats}
          defaultStrategy="mean"
          anchorEl={addButtonRef.current}
          unitLabel={activeVariantPick.item.unit || ''}
          currency={
            activeVariantPick.item.currency
            || (activeVariantPick.item.region
              ? REGION_MAP[activeVariantPick.item.region]?.currency
              : null)
            || 'USD'
          }
          onApply={(chosen) => {
            const pending = activeVariantPick;
            setActiveVariantPick(null);
            pending.resolve({ kind: 'variant', variant: chosen });
          }}
          onUseDefault={(strategy) => {
            const pending = activeVariantPick;
            setActiveVariantPick(null);
            pending.resolve({ kind: 'default', strategy });
          }}
          onClose={() => {
            const pending = activeVariantPick;
            setActiveVariantPick(null);
            pending.resolve(null);
          }}
        />
      )}
    </div>
  );
}
