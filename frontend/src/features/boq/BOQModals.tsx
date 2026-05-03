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
import {
  MultiVariantPicker,
  collectVariantSlots,
  type VariantSlot,
  type MultiVariantPickerResult,
  type SlotPick,
} from '@/features/costs/MultiVariantPicker';
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

/** Pending multi-variant pick — fires when a CostItem has 2+ independent
 *  variant slots (top-level + per-component, or 2+ per-component slots).
 *  The MultiVariantPicker modal renders all slots in one centered dialog so
 *  the user makes every variant decision before the position is created. */
interface PendingMultiVariantPick {
  item: CostSearchItem;
  slots: VariantSlot[];
  positionTitle: string;
  /** Optional progress chip for batch-add flows. Only set when the user
   *  selected 2+ items at once and this dialog will fire sequentially. */
  batchProgress?: { current: number; total: number };
  /** Number of OTHER multi-variant items still queued after this one in the
   *  current add batch. Surfaces the "Apply to remaining N" CTA in the modal
   *  footer; clicking it short-circuits every subsequent open and re-uses
   *  the user's slot picks (matched by slot name) across the remainder. */
  remainingCount: number;
  /** Pre-seeded picks when the user already chose "Apply to remaining N"
   *  on an earlier item in this batch. Carried across by slot-name match. */
  suggestedPicks?: Record<string, SlotPick>;
  resolve: (result: MultiVariantPickerResult | null) => void;
}

/** One section row pulled from the structured BOQ response. Used to populate
 *  the "Add to: …" footer dropdown so a batch can be filed under an existing
 *  section instead of always landing as root-level positions. */
interface BOQSectionOption {
  id: string;
  ordinal: string;
  description: string;
  /** Highest numeric suffix amongst this section's existing children — used
   *  to compute the next sibling ordinal without a re-fetch. */
  childMaxNum: number;
  /** Number of existing children, surfaced in the dropdown for context. */
  childCount: number;
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
  //
  // The lazy initializer reads from the React Query cache synchronously —
  // when ``BOQEditorPage``'s idle prefetch has already populated
  // ``cost-regions-modal``, we start with the right region and skip the
  // throwaway region='' tree + search fetches that fire before the
  // auto-default useEffect runs. Cold cache (no prefetch yet) falls
  // through to the empty initial value and the auto-default still works.
  const [region, setRegion] = useState<string>(() => {
    const cached = queryClient.getQueryData<string[]>(['cost-regions-modal']);
    return cached?.[0] ?? '';
  });
  // Seed the "already defaulted" flag from the same cache lookup we used
  // to seed `region` itself — otherwise the auto-default effect would
  // overwrite a region the user has clicked between mount and the first
  // useEffect tick.
  const regionDefaultedRef = useRef<boolean>(
    Boolean(queryClient.getQueryData<string[]>(['cost-regions-modal'])?.[0]),
  );
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
  const [activeMultiVariantPick, setActiveMultiVariantPick] =
    useState<PendingMultiVariantPick | null>(null);
  /** Per-row quantity overrides, keyed by item id. Items absent from the
   *  map ship as quantity=1 (the legacy default). Editing the input here
   *  saves the user from 20 cell edits after a 20-item batch add. */
  const [rowQuantity, setRowQuantity] = useState<Record<string, number>>({});
  /** Keyboard-navigation cursor over the current results list. -1 means
   *  the user hasn't engaged the keyboard yet — clicks won't render a
   *  highlight ring then.  ↓/↑ moves; Space toggles; Enter adds. */
  const [cursorIndex, setCursorIndex] = useState<number>(-1);
  /** Mobile-only popover for the category tree.  Hidden on >=md viewports. */
  const [mobileTreeOpen, setMobileTreeOpen] = useState(false);
  /** Section parent for new positions. ``null`` means root-level (the legacy
   *  default). Picked from the footer dropdown; the structured BOQ fetch
   *  populates the option list. */
  const [selectedParentId, setSelectedParentId] = useState<string | null>(null);
  /** Cached sections list — fetched lazily when the dropdown is first opened
   *  or when handleAdd needs the parent context. ``null`` = not yet fetched. */
  const [boqSections, setBoqSections] = useState<BOQSectionOption[] | null>(null);
  /** Open/closed flag for the section dropdown popover. */
  const [sectionMenuOpen, setSectionMenuOpen] = useState(false);
  const addButtonRef = useRef<HTMLButtonElement>(null);
  const sectionMenuRef = useRef<HTMLDivElement>(null);
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
  // The backend ``/v1/costs/category-tree/`` endpoint accepts a ``depth``
  // (1..4) param; we keep the modal at the default depth=4 so users can
  // drill the full classification hierarchy from the sidebar without a
  // second request. Cold catalogs still feel snappy because the tree
  // query is independent of the search-results query — the right pane
  // renders the first 15 items as soon as the search returns, even
  // before the tree finishes loading.
  const {
    data: categoryTree,
    isLoading: treeLoading,
    isError: treeError,
    refetch: refetchTree,
  } = useQuery({
    queryKey: ['cost-tree', region, 2],
    // Open with depth=2 — far cheaper GROUP BY than depth=4 on cold SQLite
    // (2 json_extract columns vs 4). Deeper levels are reachable via the
    // search endpoint's `classification_path` filter when the user clicks
    // a level-2 leaf, so dropping the upfront depth doesn't cost coverage.
    // Cold-cache wall-clock: ~85 s @ depth=4 → ~10 s @ depth=2 on a 100 k+
    // catalog, which is the difference between "modal opens" and "modal
    // hangs" from the user's perspective.
    queryFn: () => fetchCategoryTree(region || undefined, 2),
    staleTime: 5 * 60 * 1000,
    enabled: regionsData !== undefined,
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
        // Small initial page so the modal shows results within ~150 ms even
        // on a cold catalog. The IntersectionObserver below auto-loads the
        // next page when the user scrolls near the sentinel — perceived
        // "infinite scroll" without holding up the first paint on a 50-item
        // batch fetch + serialization.
        limit: 15,
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

  /** Fetch the BOQ in structured form so we get the section list pre-grouped
   *  with each section's child positions. Used to populate the footer
   *  "Add to: …" dropdown and to compute parent-relative ordinals at apply
   *  time. Returned promise resolves to the cached value on subsequent calls
   *  to avoid hammering the endpoint mid-batch. */
  const loadSections = useCallback(async (): Promise<BOQSectionOption[]> => {
    if (boqSections) return boqSections;
    interface StructuredPosition {
      id: string;
      ordinal: string;
      description: string;
    }
    interface StructuredSection {
      id: string;
      ordinal: string;
      description: string;
      positions: StructuredPosition[];
    }
    interface StructuredBOQ {
      sections: StructuredSection[];
      positions: StructuredPosition[];
    }
    try {
      const data = await apiGet<StructuredBOQ>(`/v1/boq/boqs/${boqId}/structured/`);
      const opts: BOQSectionOption[] = (data.sections ?? []).map((s) => {
        // Numeric suffix of the highest existing child ordinal under this
        // section, so the next sibling slot is `${maxNum + 1}`. Sections
        // typically use a `<parent>.<NNN>` ordinal scheme (e.g. 02.001),
        // so we read the trailing dot-segment of each child ordinal.
        let maxNum = 0;
        for (const p of s.positions ?? []) {
          const tail = p.ordinal.split('.').pop() ?? '';
          const n = parseInt(tail, 10);
          if (!Number.isNaN(n) && n > maxNum) maxNum = n;
        }
        return {
          id: s.id,
          ordinal: s.ordinal,
          description: s.description,
          childMaxNum: maxNum,
          childCount: (s.positions ?? []).length,
        };
      });
      setBoqSections(opts);
      return opts;
    } catch {
      // Endpoint failure shouldn't block adding — fall back to a flat root
      // add (legacy behaviour). The dropdown stays empty so the user can't
      // pick a phantom section.
      setBoqSections([]);
      return [];
    }
  }, [boqId, boqSections]);

  // Eager-load sections once the modal mounts so the dropdown opens with
  // an immediate list. Lightweight call (~one row per section).
  useEffect(() => {
    loadSections();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Close the section dropdown on outside click + Esc.
  useEffect(() => {
    if (!sectionMenuOpen) return;
    function onDoc(e: MouseEvent) {
      if (!sectionMenuRef.current?.contains(e.target as Node)) {
        setSectionMenuOpen(false);
      }
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') setSectionMenuOpen(false);
    }
    document.addEventListener('mousedown', onDoc);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onDoc);
      document.removeEventListener('keydown', onKey);
    };
  }, [sectionMenuOpen]);

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
      // Resolve the parent context. When the user chose a section in the
      // footer dropdown, new positions land under that section with
      // section-relative ordinals (`<section>.<NNN+1>`). Otherwise we fall
      // back to the legacy flat numbering where each new position lives at
      // the BOQ root with a `<NN>.<NNN>` ordinal one slot past the highest
      // existing numeric component.
      const sections = await loadSections();
      const targetSection = selectedParentId
        ? sections.find((s) => s.id === selectedParentId) ?? null
        : null;

      let nextOrdNum = 1; // root-mode counter (legacy)
      let nextChildNum = 1; // section-mode counter (relative to parent)

      if (targetSection) {
        nextChildNum = targetSection.childMaxNum + 1;
      } else {
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
      }

      const selectedItems = items.filter((i) => selected.has(i.id));

      // Promise wrapper around the single-slot variant picker — used when
      // a cost item has exactly one top-level variant slot. Cancelling
      // resolves with `null`; "Use average" resolves with `{ kind: 'default' }`.
      const pickVariant = (item: CostSearchItem): Promise<VariantResolution | null> =>
        new Promise((resolve) => {
          setActiveVariantPick({ item, resolve });
        });

      // Promise wrapper around the multi-slot picker — fires when a cost
      // item carries 2+ independent variant slots (e.g. top-level catalog
      // variant + per-component abstract resources, or just multiple
      // per-component slots). The modal renders every slot at once so the
      // user makes all decisions up-front instead of discovering buried
      // medians via per-resource pills later. The optional `batchProgress`
      // surfaces an "Item N of M" badge in the modal header so users know
      // how many remain when the cost-DB selection has more than one item.
      const pickMultiVariants = (
        item: CostSearchItem,
        slots: VariantSlot[],
        batchProgress: { current: number; total: number } | undefined,
        remainingCount: number,
        suggestedPicks: Record<string, SlotPick> | undefined,
      ): Promise<MultiVariantPickerResult | null> =>
        new Promise((resolve) => {
          setActiveMultiVariantPick({
            item,
            slots,
            positionTitle: item.description || 'Position',
            batchProgress,
            remainingCount,
            suggestedPicks,
            resolve,
          });
        });

      // Toast suppression flags are scoped per-batch — the user gets one
      // success toast per *kind* of pick (variant / default / multi) for
      // the entire add batch, not per-item. This keeps the screen calm
      // when adding 5+ items but still confirms that something landed.
      let variantToastShown = false;
      let defaultToastShown = false;
      let multiToastShown = false;

      // Track position within the batch so the multi-picker header can
      // render "Item N of M". Only items that actually open the modal
      // count toward the progress; single-popover and zero-slot items
      // are skipped. Pre-scan slots so the total is correct upfront.
      const multiQueue: number[] = [];
      const fallbackCurrencyFor = (it: CostSearchItem) =>
        (it.currency && it.currency.trim()) ||
        (it.region && REGION_MAP[it.region]?.currency) ||
        'EUR';
      selectedItems.forEach((it, idx) => {
        const itSlots = collectVariantSlots(it, fallbackCurrencyFor(it));
        const willOpenMulti =
          itSlots.length >= 2 || itSlots.some((s) => s.slotId !== 'top');
        if (willOpenMulti) multiQueue.push(idx);
      });
      const multiTotal = multiQueue.length;
      let multiCurrent = 0;

      // Cached picks from "Apply to remaining N items" — once the user
      // commits via that footer button on any item in the batch, every
      // subsequent multi-variant item skips the modal entirely. Slot
      // matching is name-based: each new item's slots are looked up by
      // `name` against the cached map. Slots without a match fall back to
      // the silent median default (same as not engaging the modal). The
      // cache key is `slot.name` rather than `slotId`, because slotIds
      // ("comp:0", "comp:1", …) are positional and the order of variant
      // resources can differ between catalog rows even for the same trade.
      let cachedSlotsByName: Record<string, SlotPick> | null = null;
      let appliedToCount = 0;

      // Track per-item POST outcomes so a partial failure in a 20-item batch
      // doesn't silently drop everything (the previous behaviour bubbled the
      // first error to the outer catch and aborted the rest of the loop).
      let succeeded = 0;
      const failed: Array<{ description: string; code: string; error: string }> = [];

      for (const item of selectedItems) {
        const variants = item.metadata_?.variants;
        const stats = item.metadata_?.variant_stats;

        const slotFallbackCurrency = fallbackCurrencyFor(item);
        const slots = collectVariantSlots(item, slotFallbackCurrency);

        let resolution: VariantResolution | null = null;
        let multiResult: MultiVariantPickerResult | null = null;

        // Routing:
        //   2+ slots OR ≥1 per-component slot → MultiVariantPicker (modal)
        //   exactly 1 top-level slot          → existing anchored popover
        //   0 slots                            → no variant flow
        const useMultiPicker =
          slots.length >= 2 || slots.some((s) => s.slotId !== 'top');

        if (useMultiPicker) {
          multiCurrent++;

          // Fast-forward path: if the user already chose "Apply to
          // remaining N" on an earlier item, build a picks map for THIS
          // item by slot-name lookup and skip the modal entirely.
          if (cachedSlotsByName) {
            const projected: Record<string, SlotPick> = {};
            for (const s of slots) {
              const cached = cachedSlotsByName[s.name];
              if (cached?.kind === 'variant') {
                // Match by variant.index when the same index exists; else
                // fall back to median. Different CWICR rows can carry the
                // same slot name with disjoint variant catalogs, so a
                // stale index would phantom-stamp a wrong rate.
                const stillThere = s.variants.some(
                  (v) => v.index === cached.variant.index,
                );
                projected[s.slotId] = stillThere
                  ? cached
                  : { kind: 'default', strategy: 'median' };
              } else if (cached?.kind === 'default') {
                projected[s.slotId] = cached;
              } else {
                projected[s.slotId] = { kind: 'default', strategy: 'median' };
              }
            }
            multiResult = { picks: projected };
            appliedToCount++;
            const topPick = projected['top'];
            if (topPick?.kind === 'variant') {
              resolution = { kind: 'variant', variant: topPick.variant };
            } else if (topPick?.kind === 'default') {
              resolution = { kind: 'default', strategy: topPick.strategy };
            }
          } else {
            const progress =
              multiTotal > 1
                ? { current: multiCurrent, total: multiTotal }
                : undefined;
            // Suggested picks carried over from a prior soft-pre-seed (none
            // today; reserved for a future "remember last batch" feature).
            const suggested: Record<string, SlotPick> | undefined = undefined;
            const remaining = Math.max(0, multiTotal - multiCurrent);
            const r = await pickMultiVariants(
              item,
              slots,
              progress,
              remaining,
              suggested,
            );
            // Cancelled — skip THIS item but keep going with the rest.
            if (!r) continue;
            multiResult = r;
            // Capture cache once the user opts in to apply-to-all. Subsequent
            // iterations consume the cache; this one still proceeds normally.
            if (r.applyToAll) {
              const byName: Record<string, SlotPick> = {};
              for (const s of slots) {
                const p = r.picks[s.slotId];
                if (p) byName[s.name] = p;
              }
              cachedSlotsByName = byName;
            }
            // Project the top-level pick (if present) back into the legacy
            // resolution shape so the existing top-level resource-append
            // block below stays untouched.
            const topPick = r.picks['top'];
            if (topPick?.kind === 'variant') {
              resolution = { kind: 'variant', variant: topPick.variant };
            } else if (topPick?.kind === 'default') {
              resolution = { kind: 'default', strategy: topPick.strategy };
            }
          }
        } else if (
          slots.length === 1 &&
          slots[0]?.slotId === 'top' &&
          variants &&
          variants.length >= 2 &&
          stats
        ) {
          resolution = await pickVariant(item);
          if (!resolution) continue;
        }

        let ordinal: string;
        if (targetSection) {
          // Section-relative ordinal: <parent>.<NNN+next>. Padded 3-digit
          // suffix so dictionary sort matches numeric order up to 999
          // children (which is far past any realistic per-section row count).
          const tail = String(nextChildNum).padStart(3, '0');
          ordinal = `${targetSection.ordinal}.${tail}`;
        } else {
          const section = String(Math.floor((nextOrdNum - 1) / 999) + 1).padStart(2, '0');
          const pos = String(((nextOrdNum - 1) % 999) + 1).padStart(3, '0');
          ordinal = `${section}.${pos}`;
        }
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
        // Track the FIRST component index per dedupe key (resource_code or
        // first-variant-label fallback). When CWICR ships two component rows
        // both pointing at the same abstract-resource catalog (real shape —
        // e.g. KADX_KATO_KAKASA_KATO has two rows under code KALI-RI-KATO-KANE
        // with identical 3-variant catalogs), the picker pill is rendered on
        // ONLY the first row, and the rest are treated as plain rate rows.
        // Without this dedupe the user sees two ▾3 pills that look like a
        // bug ("different variant resources can't have the same count").
        const variantPrimaryIdx = new Map<string, number>();
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
        }> = (item.components || []).map((c, i) => {
          const compVariants = c.available_variants;
          const compStats = c.available_variant_stats;
          const hasCompVariants =
            Array.isArray(compVariants) &&
            compVariants.length >= 2 &&
            compStats != null;

          if (!hasCompVariants) {
            return {
              name: c.name,
              code: c.code || '',
              type: c.type || 'other',
              unit: c.unit || 'pcs',
              quantity: c.quantity ?? 1,
              unit_rate: c.unit_rate ?? 0,
              total: c.cost || (c.quantity ?? 1) * (c.unit_rate ?? 0),
            };
          }

          // Compute the dedupe key. Prefer resource_code; fall back to the
          // first variant's label so two unrelated catalogs that happen to
          // ship without codes don't accidentally collapse.
          const code = (c.code || '').trim();
          const dedupeKey = code || (compVariants![0]?.label ?? `__c${i}`);
          const primaryIdx = variantPrimaryIdx.get(dedupeKey) ?? i;
          if (!variantPrimaryIdx.has(dedupeKey)) {
            variantPrimaryIdx.set(dedupeKey, i);
          }
          const isPrimary = primaryIdx === i;

          // Linked components share the primary slot's pick — collectVariantSlots
          // only emits one slot per dedupe key, so picks[`comp:${i}`] for a
          // duplicate index would always be undefined.
          const compPick = multiResult?.picks[`comp:${primaryIdx}`];
          const qty = c.quantity ?? 1;

          if (compPick?.kind === 'variant') {
            const v = compPick.variant;
            const cs = (compStats!.common_start || '').trim();
            const composedName =
              (v.full_label || '').trim() ||
              (cs ? `${cs} ${v.label}`.trim() : v.label) ||
              c.name;
            return {
              name: composedName,
              code: c.code || '',
              type: c.type || 'other',
              unit: c.unit || 'pcs',
              quantity: qty,
              unit_rate: v.price,
              total: qty * v.price,
              variant: { label: v.label, price: v.price, index: v.index },
              ...(isPrimary && {
                available_variants: compVariants,
                available_variant_stats: compStats,
              }),
            };
          }

          // Default strategy — explicit from the modal (mean | median),
          // otherwise silent median for backwards compatibility.
          const strategy: 'mean' | 'median' =
            compPick?.kind === 'default' ? compPick.strategy : 'median';
          const rate =
            strategy === 'mean' ? compStats!.mean : compStats!.median;
          return {
            name: c.name,
            code: c.code || '',
            type: c.type || 'other',
            unit: c.unit || 'pcs',
            quantity: qty,
            unit_rate: rate,
            total: qty * rate,
            variant_default: strategy,
            ...(isPrimary && {
              available_variants: compVariants,
              available_variant_stats: compStats,
            }),
          };
        });

        // Resolve description + variant metadata from the resolution.
        const baseDescription = item.description || 'Unnamed item';
        const description = baseDescription;
        let variantMeta: Record<string, unknown> = {};

        // Detect when the item's top-level catalog is mirrored on a component
        // we already pushed (real CWICR shape — many rates list the abstract
        // resource as both ``metadata.variants`` AND ``components[0]`` with
        // identical 8-variant catalogs). When that happens we MUST NOT push
        // the synthetic top-level resource below: the components already
        // carry the rate, and adding a third line would inflate the position
        // by double-counting the same variant. ``collectVariantSlots()``
        // already drops the top slot from the picker UI in this case.
        const topVariantsForCheck = item.metadata_?.variants;
        let topMirroredOnComponent = false;
        if (topVariantsForCheck && topVariantsForCheck.length >= 2) {
          const topHash = topVariantsForCheck
            .map((v) => (v.label || '').trim())
            .join('|');
          for (const c of item.components || []) {
            if (
              Array.isArray(c.available_variants) &&
              c.available_variants.length >= 2
            ) {
              const compHash = c.available_variants
                .map((v) => (v.label || '').trim())
                .join('|');
              if (compHash === topHash) {
                topMirroredOnComponent = true;
                break;
              }
            }
          }
        }

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

        if (resolution?.kind === 'variant' && !topMirroredOnComponent) {
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
        } else if (resolution?.kind === 'default' && !topMirroredOnComponent) {
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

        // Position quantity: the inline qty input in the cost-DB modal lets
        // the user pick a non-default qty per row before the batch POST.
        // Empty / cleared input falls back to 1 (the legacy default) — that
        // mirror's the previous hardcoded value so existing tests / UX stay
        // intact when the user doesn't engage the input.
        const positionQty = rowQuantity[item.id] ?? 1;

        try {
          await apiPost(`/v1/boq/boqs/${boqId}/positions/`, {
          boq_id: boqId,
          ...(targetSection ? { parent_id: targetSection.id } : {}),
          ordinal,
          description,
          unit: item.unit || 'pcs',
          quantity: positionQty,
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
            // Provenance — which UI surface produced this position so
            // adoption of the multi-variant modal is measurable from the
            // server side without diffing payloads.
            ui_source: multiResult
              ? 'multi_picker'
              : resolution
                ? 'single_popover'
                : slots.length > 0
                  ? 'silent_default'
                  : 'no_variants',
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
          succeeded++;
        } catch (postErr) {
          // Per-item failure recovery: log to the failed[] array and keep
          // iterating so a single 4xx/5xx doesn't drop the rest of the
          // batch. The trailing summary toast lists the casualties.
          const msg = postErr instanceof Error ? postErr.message : String(postErr);
          failed.push({
            description: description || item.code || 'Unnamed item',
            code: item.code || '',
            error: msg,
          });
          if (import.meta.env.DEV) console.error('Failed to POST position:', item.code, msg);
          // Don't increment ordinal — leave the slot open for the next item.
          continue;
        }

        // Advance the ordinal counter only on success — root or section.
        if (targetSection) {
          nextChildNum++;
        } else {
          nextOrdNum++;
        }

        if (multiResult && !multiToastShown) {
          // Count slots where the user picked an explicit variant (not a
          // fallback strategy). One toast per add batch — multiple
          // positions adding sequentially share the announcement.
          const explicitCount = Object.values(multiResult.picks).filter(
            (p) => p.kind === 'variant',
          ).length;
          if (explicitCount > 0) {
            addToast({
              type: 'success',
              title: t('boq.mvp.toast_applied', {
                defaultValue: '{{count}} variant chosen',
                defaultValue_other: '{{count}} variants chosen',
                count: explicitCount,
              }),
            });
            multiToastShown = true;
          }
        }

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
      }

      // Apply-to-all summary toast — only when the user actually exercised
      // the affordance (cachedSlotsByName non-null AND ≥1 item benefited
      // from it). Quiet when applyToAll never engaged so single-item adds
      // stay toast-free.
      if (cachedSlotsByName && appliedToCount > 0) {
        addToast({
          type: 'success',
          title: t('boq.mvp.toast_apply_to_remaining', {
            defaultValue: 'Applied picks to {{count}} more item',
            defaultValue_other: 'Applied picks to {{count}} more items',
            count: appliedToCount,
          }),
        });
      }

      // Trailing summary — partial success is the new normal, not a fatal
      // error.  Three branches:
      //   all succeeded → existing onAdded() + close, no extra toast.
      //   partial      → warning toast listing the first 3 failures.
      //   all failed   → error toast (matches legacy behaviour).
      if (failed.length === 0) {
        onAdded();
      } else if (succeeded > 0) {
        const sample = failed.slice(0, 3).map((f) => f.code || f.description).join(', ');
        const more = failed.length > 3 ? ` (+${failed.length - 3})` : '';
        addToast({
          type: 'warning',
          title: t('boq.add_partial_success', {
            defaultValue: 'Added {{ok}} of {{total}} positions',
            ok: succeeded,
            total: succeeded + failed.length,
          }),
          message: t('boq.add_partial_failed_items', {
            defaultValue: 'Failed: {{items}}{{more}}',
            items: sample,
            more,
          }),
        });
        onAdded();
      } else {
        addToast({
          type: 'error',
          title: t('boq.add_all_failed', {
            defaultValue: 'Could not add any of the {{count}} positions',
            count: failed.length,
          }),
          message: failed[0]?.error || '',
        });
      }
    } catch (err) {
      // Outer catch only fires for unexpected exceptions OUTSIDE the per-item
      // try (e.g. JSON.parse on the BOQ-detail fetch). Per-item POST errors
      // are now collected in the failed[] array and surfaced via the partial-
      // success toast above.
      if (import.meta.env.DEV) console.error('Add-from-cost-DB outer error:', err);
      addToast({
        type: 'error',
        title: t('boq.add_failed', { defaultValue: 'Failed to add positions' }),
        message: err instanceof Error ? err.message : String(err),
      });
    } finally {
      setIsAdding(false);
    }
  }, [
    boqId,
    selected,
    items,
    rowQuantity,
    selectedParentId,
    loadSections,
    onAdded,
    onSelectForResources,
    addToast,
    t,
  ]);

  // Modal-scoped keyboard navigation:
  //   Esc           — close
  //   ↓ / ↑         — move cursor over the result rows
  //   Space         — toggle the highlighted row's selection
  //   Enter         — toggle selection of the highlighted row (or fire Add
  //                   when no row is highlighted but selection is non-empty)
  //   PageDown / PageUp — jump 10 rows at a time
  //   Home / End    — jump to first/last row
  //
  // The handler skips arrow / space / enter when focus is in an input,
  // textarea, or contenteditable so typing in the search bar keeps working.
  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === 'Escape') {
        e.preventDefault();
        onClose();
        return;
      }
      const target = e.target as HTMLElement | null;
      const inEditable =
        target instanceof HTMLElement &&
        (target.tagName === 'INPUT' ||
          target.tagName === 'TEXTAREA' ||
          target.isContentEditable);
      if (inEditable) return;
      if (items.length === 0) return;

      switch (e.key) {
        case 'ArrowDown':
          e.preventDefault();
          setCursorIndex((i) => Math.min(items.length - 1, (i < 0 ? -1 : i) + 1));
          break;
        case 'ArrowUp':
          e.preventDefault();
          setCursorIndex((i) => Math.max(0, (i < 0 ? items.length : i) - 1));
          break;
        case 'PageDown':
          e.preventDefault();
          setCursorIndex((i) => Math.min(items.length - 1, (i < 0 ? 0 : i) + 10));
          break;
        case 'PageUp':
          e.preventDefault();
          setCursorIndex((i) => Math.max(0, (i < 0 ? 0 : i) - 10));
          break;
        case 'Home':
          e.preventDefault();
          setCursorIndex(0);
          break;
        case 'End':
          e.preventDefault();
          setCursorIndex(items.length - 1);
          break;
        case ' ':
        case 'Spacebar': {
          e.preventDefault();
          const idx = cursorIndex < 0 ? 0 : cursorIndex;
          if (cursorIndex < 0) setCursorIndex(0);
          const it = items[idx];
          if (it) toggleSelect(it.id);
          break;
        }
        case 'Enter':
          if (cursorIndex >= 0 && cursorIndex < items.length) {
            e.preventDefault();
            const it = items[cursorIndex];
            if (it) toggleSelect(it.id);
          } else if (selected.size > 0 && !isAdding) {
            e.preventDefault();
            handleAdd();
          }
          break;
      }
    }
    document.addEventListener('keydown', handleKeyDown, { capture: true });
    return () => document.removeEventListener('keydown', handleKeyDown, { capture: true });
  }, [onClose, items, cursorIndex, toggleSelect, selected.size, isAdding, handleAdd]);

  // Reset the keyboard cursor when the result list flips (e.g. region change).
  useEffect(() => {
    setCursorIndex((i) => (i >= items.length ? -1 : i));
  }, [items.length]);

  // Scroll the highlighted row into view as the cursor moves. Uses the
  // existing listScrollRef so the smooth scroll respects the modal's own
  // scroll container instead of the page viewport.
  useEffect(() => {
    if (cursorIndex < 0) return;
    const el = listScrollRef.current?.querySelector<HTMLTableRowElement>(
      `[data-cursor-index="${cursorIndex}"]`,
    );
    el?.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
  }, [cursorIndex]);

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

  /** Live projected sum for the current selection — Σ(rate × qty) across
   *  the items the user has selected (qty falls back to 1). Surfaces the
   *  cumulative cost impact in the modal footer so a 5-item batch isn't
   *  committed blind. Variant rates aren't projected here yet — the picker
   *  will negotiate them at apply-time; this is the catalog-rate baseline. */
  const selectionPreview = useMemo(() => {
    if (selected.size === 0) return null;
    let sum = 0;
    let currency: string | null = null;
    for (const item of items) {
      if (!selected.has(item.id)) continue;
      const qty = rowQuantity[item.id] ?? 1;
      const rate = typeof item.rate === 'number' ? item.rate : 0;
      sum += rate * qty;
      if (!currency) {
        currency =
          (item.currency && item.currency.trim()) ||
          (item.region && REGION_MAP[item.region]?.currency) ||
          null;
      }
    }
    return { total: sum, currency: currency || 'EUR' };
  }, [selected, items, rowQuantity]);

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
                // Show a skeleton table that mirrors the actual result
                // columns so the modal feels populated even while the
                // search round-trip is in flight. Cold-cache catalogs
                // can take 1-2 s warm and 18 s cold for the first page;
                // a generic centered spinner reads as "stuck", a
                // skeleton reads as "loading specific data".
                <div
                  className="px-3 py-2"
                  data-testid="cost-results-skeleton"
                  aria-busy="true"
                >
                  <div className="space-y-1.5">
                    {Array.from({ length: 8 }).map((_, i) => (
                      <div
                        key={i}
                        className="flex items-center gap-3 px-2 py-2.5 rounded-md"
                      >
                        <div className="h-4 w-4 rounded-sm bg-surface-secondary/70 animate-pulse" />
                        <div className="flex-1 min-w-0 space-y-1.5">
                          <div className="h-3 rounded bg-surface-secondary/70 animate-pulse" style={{ width: `${50 + ((i * 7) % 40)}%` }} />
                          <div className="h-2.5 rounded bg-surface-secondary/50 animate-pulse" style={{ width: `${30 + ((i * 11) % 30)}%` }} />
                        </div>
                        <div className="h-4 w-12 rounded bg-surface-secondary/70 animate-pulse" />
                        <div className="h-4 w-16 rounded bg-surface-secondary/70 animate-pulse" />
                        <div className="h-4 w-20 rounded bg-surface-secondary/70 animate-pulse" />
                      </div>
                    ))}
                  </div>
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
                      <th className="px-3 py-2 text-start text-xs font-medium text-content-secondary">{t('boq.description')}</th>
                      <th className="px-3 py-2 text-center text-xs font-medium text-content-secondary w-16">{t('boq.unit')}</th>
                      <th className="px-3 py-2 text-end text-xs font-medium text-content-secondary w-20">
                        {t('boq.quantity_short', { defaultValue: 'Qty' })}
                      </th>
                      <th className="px-3 py-2 text-end text-xs font-medium text-content-secondary w-24">{t('costs.rate', 'Rate')}</th>
                      <th className="px-3 py-2 text-center text-xs font-medium text-content-secondary w-20">
                        {t('boq.region', { defaultValue: 'Database' })}
                      </th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border-light">
                    {items.map((item, idx) => {
                      const isSel = selected.has(item.id);
                      const isCursor = cursorIndex === idx;
                      return (
                        <tr
                          key={item.id}
                          data-cursor-index={idx}
                          onClick={() => {
                            setCursorIndex(idx);
                            toggleSelect(item.id);
                          }}
                          className={
                            'cursor-pointer transition-colors ' +
                            (isSel ? 'bg-oe-blue-subtle/20 ' : 'hover:bg-surface-secondary/50 ') +
                            (isCursor
                              ? 'outline outline-1 outline-oe-blue/60 -outline-offset-1'
                              : '')
                          }
                        >
                          <td className="px-3 py-2.5">
                            <div className={`h-4 w-4 rounded border-2 flex items-center justify-center ${isSel ? 'border-oe-blue bg-oe-blue' : 'border-content-quaternary'}`}>
                              {isSel && <Check size={10} className="text-white" />}
                            </div>
                          </td>
                          <td className="px-3 py-2.5 max-w-[420px]">
                            {(() => {
                              // Variant resources (CWICR ``price_abstract_resource_*``)
                              // carry an abstract base name in
                              // ``metadata_.variant_stats.common_start`` which is the
                              // user-facing identifier for the resource family
                              // (e.g. "Beton, Sortenliste C"). The bare
                              // ``item.description`` is the rate-code description —
                              // useful as context, but secondary. Render
                              // ``common_start`` as the primary line and the rate-code
                              // description as a smaller subtitle when present so the
                              // estimator can scan variant rows by their material name.
                              const cs = item.metadata_?.variant_stats?.common_start?.trim() ?? '';
                              const hasCs = cs.length > 0;
                              const desc = item.description || 'Unnamed item';
                              const primary = hasCs ? cs : desc;
                              const secondary = hasCs && desc && desc !== cs ? desc : '';
                              return (
                                <>
                                  <span
                                    className="text-content-primary truncate block"
                                    title={hasCs ? `${cs}\n${desc}` : desc}
                                  >
                                    {primary}
                                  </span>
                                  {secondary && (
                                    <span
                                      className="text-2xs text-content-tertiary truncate block"
                                      title={secondary}
                                    >
                                      {secondary}
                                    </span>
                                  )}
                                  <span className="text-2xs text-content-quaternary font-mono">{item.code}</span>
                                </>
                              );
                            })()}
                          </td>
                          <td className="px-3 py-2.5 text-center">
                            <Badge variant="neutral" size="sm">{item.unit}</Badge>
                          </td>
                          <td
                            className="px-3 py-2.5 text-end"
                            onClick={(e) => e.stopPropagation()}
                          >
                            <input
                              type="number"
                              min="0"
                              step="0.01"
                              value={rowQuantity[item.id] ?? ''}
                              placeholder="1"
                              onChange={(e) => {
                                const raw = e.target.value;
                                if (raw === '') {
                                  // Empty input → clear override so the POST falls back to 1.
                                  setRowQuantity((cur) => {
                                    const next = { ...cur };
                                    delete next[item.id];
                                    return next;
                                  });
                                  return;
                                }
                                const parsed = parseFloat(raw);
                                if (!isNaN(parsed) && parsed >= 0) {
                                  setRowQuantity((cur) => ({ ...cur, [item.id]: parsed }));
                                }
                              }}
                              onFocus={(e) => {
                                // Auto-select selects this row so the user sees their qty
                                // edit reflected in the bottom "N selected" counter and
                                // the rate × qty preview without an extra checkbox click.
                                if (!isSel) toggleSelect(item.id);
                                e.currentTarget.select();
                              }}
                              onKeyDown={(e) => {
                                if (e.key === 'Enter') {
                                  e.preventDefault();
                                  e.currentTarget.blur();
                                }
                              }}
                              aria-label={t('boq.quantity_for_item', {
                                defaultValue: 'Quantity for {{item}}',
                                item: item.description || item.code,
                              })}
                              className="w-16 h-7 px-1.5 text-xs tabular-nums text-end rounded border border-border-light bg-surface-elevated text-content-primary focus:outline-none focus:ring-1 focus:ring-oe-blue"
                              data-testid={`cost-row-qty-${item.id}`}
                            />
                          </td>
                          <td className="px-3 py-2.5 text-end font-semibold tabular-nums text-content-primary">
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
                              {(() => {
                                // Validation hint surfaced pre-add — saves the user
                                // from finding the warning later via the BOQ row's
                                // quality dashboard. ``rate <= 0`` flags the catalog
                                // entry whose price never landed (CWICR rows with
                                // empty rate column); ``lump_sum`` is high-risk
                                // because qty × rate becomes ambiguous.
                                const lowRate = !(typeof item.rate === 'number' && item.rate > 0);
                                const lumpSum = (item.unit || '').toLowerCase() === 'lump_sum';
                                if (!lowRate && !lumpSum) return null;
                                return (
                                  <span
                                    title={
                                      lowRate
                                        ? t('boq.warn_zero_rate', {
                                            defaultValue: 'No rate — review before commit',
                                          })
                                        : t('boq.warn_lump_sum', {
                                            defaultValue:
                                              'Lump sum — quantity × rate may not match expected total',
                                          })
                                    }
                                  >
                                    <AlertCircle
                                      size={12}
                                      className="text-amber-500 dark:text-amber-400"
                                    />
                                  </span>
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
          <div className="flex items-center gap-2 text-xs">
            <span className="text-content-tertiary">
              {selected.size > 0
                ? `${selected.size} ${t('boq.items_selected', { defaultValue: 'items selected' })}`
                : t('boq.click_to_select', { defaultValue: 'Click rows to select' })}
            </span>
            {selectionPreview && (
              <>
                <span className="text-content-quaternary">·</span>
                <span
                  className="font-mono font-semibold tabular-nums text-content-secondary"
                  data-testid="cost-modal-selection-preview"
                  title={t('boq.preview_total_hint', {
                    defaultValue:
                      'Catalog-rate × quantity for the selection. Variant picks may adjust this.',
                  })}
                >
                  ≈ {new Intl.NumberFormat(getIntlLocale(), {
                    style: 'currency',
                    currency: selectionPreview.currency,
                    minimumFractionDigits: 0,
                    maximumFractionDigits: 0,
                  }).format(selectionPreview.total)}
                </span>
              </>
            )}
          </div>
          <div className="flex items-center gap-2">
            {/* Section picker — hidden in resource-pick mode (the modal is
                opened to fill `metadata.resources[]`, not to create a new
                position) and when the BOQ has no sections at all. */}
            {!onSelectForResources && boqSections && boqSections.length > 0 && (
              <div ref={sectionMenuRef} className="relative">
                <button
                  type="button"
                  onClick={() => setSectionMenuOpen((v) => !v)}
                  className="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-medium border border-border-light bg-surface-primary hover:bg-surface-hover text-content-secondary"
                  data-testid="cost-modal-section-picker"
                  aria-haspopup="listbox"
                  aria-expanded={sectionMenuOpen}
                  title={t('boq.add_to_section_hint', {
                    defaultValue: 'Choose where new items land in the BOQ',
                  })}
                >
                  <Layers size={12} className="text-content-tertiary" />
                  <span className="text-content-tertiary">
                    {t('boq.add_to_label', { defaultValue: 'Add to:' })}
                  </span>
                  <span className="font-semibold text-content-primary truncate max-w-[160px]">
                    {selectedParentId
                      ? (() => {
                          const s = boqSections.find((x) => x.id === selectedParentId);
                          return s
                            ? `${s.ordinal} ${s.description || ''}`.trim()
                            : t('boq.add_to_root', { defaultValue: '[Root]' });
                        })()
                      : t('boq.add_to_root', { defaultValue: '[Root]' })}
                  </span>
                  <ChevronDown size={12} className="text-content-tertiary" />
                </button>
                {sectionMenuOpen && (
                  <div
                    role="listbox"
                    className="absolute end-0 bottom-full mb-1 z-20 min-w-[260px] max-h-72 overflow-y-auto rounded-lg border border-border bg-surface-elevated shadow-lg py-1"
                    data-testid="cost-modal-section-menu"
                  >
                    <button
                      type="button"
                      role="option"
                      aria-selected={selectedParentId === null}
                      onClick={() => {
                        setSelectedParentId(null);
                        setSectionMenuOpen(false);
                      }}
                      className={
                        'w-full px-3 py-2 flex items-center justify-between gap-3 text-start hover:bg-surface-hover ' +
                        (selectedParentId === null
                          ? 'bg-blue-50/40 dark:bg-blue-950/20'
                          : '')
                      }
                    >
                      <span className="text-xs font-medium text-content-primary">
                        {t('boq.add_to_root', { defaultValue: '[Root]' })}
                      </span>
                      <span className="text-2xs text-content-tertiary">
                        {t('boq.add_to_root_hint', {
                          defaultValue: 'top-level',
                        })}
                      </span>
                    </button>
                    <div className="my-1 border-t border-border-light/60" />
                    {boqSections.map((s) => (
                      <button
                        key={s.id}
                        type="button"
                        role="option"
                        aria-selected={selectedParentId === s.id}
                        onClick={() => {
                          setSelectedParentId(s.id);
                          setSectionMenuOpen(false);
                        }}
                        className={
                          'w-full px-3 py-2 flex items-center justify-between gap-3 text-start hover:bg-surface-hover ' +
                          (selectedParentId === s.id
                            ? 'bg-blue-50/40 dark:bg-blue-950/20'
                            : '')
                        }
                        data-testid={`cost-modal-section-option-${s.id}`}
                      >
                        <div className="min-w-0 flex-1">
                          <span className="text-xs font-mono text-content-tertiary me-2">
                            {s.ordinal}
                          </span>
                          <span className="text-xs text-content-primary truncate">
                            {s.description || (
                              <span className="italic text-content-tertiary">
                                {t('boq.untitled_section', {
                                  defaultValue: '(untitled)',
                                })}
                              </span>
                            )}
                          </span>
                        </div>
                        <span className="text-2xs text-content-tertiary tabular-nums shrink-0">
                          {t('boq.section_child_count', {
                            defaultValue: '{{count}} item',
                            defaultValue_other: '{{count}} items',
                            count: s.childCount,
                          })}
                        </span>
                      </button>
                    ))}
                  </div>
                )}
              </div>
            )}
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

      {/* Multi-variant picker — centered modal that handles a CostItem with
          2+ independent variant slots in one go. Single-slot top-level picks
          continue to use the anchored VariantPicker above. */}
      {activeMultiVariantPick && (
        <MultiVariantPicker
          positionTitle={activeMultiVariantPick.positionTitle}
          slots={activeMultiVariantPick.slots}
          batchProgress={activeMultiVariantPick.batchProgress}
          remainingCount={activeMultiVariantPick.remainingCount}
          suggestedPicks={activeMultiVariantPick.suggestedPicks}
          onApply={(result) => {
            const pending = activeMultiVariantPick;
            setActiveMultiVariantPick(null);
            pending.resolve(result);
          }}
          onCancel={() => {
            const pending = activeMultiVariantPick;
            setActiveMultiVariantPick(null);
            pending.resolve(null);
          }}
        />
      )}
    </div>
  );
}
