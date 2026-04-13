import { useState, useCallback, useRef, useEffect, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import {
  Search,
  Copy,
  Check,
  Database,
  ChevronDown,
  Upload,
  Download,
  Loader2,
  Plus,
  ChevronLeft,
  ChevronRight,
  ChevronUp,
  Hammer,
  HardHat,
  Package,
  Sparkles,
  Table2,
  FolderOpen,
  X,
  CheckSquare,
  Square,
  House,
  Star,
  Clock,
  Layers,
  TrendingUp,
  Trash2,
} from 'lucide-react';
import { Button, Card, Badge, EmptyState, InfoHint, SkeletonTable, CountryFlag, Breadcrumb, ConfirmDialog } from '@/shared/ui';
import { useConfirm } from '@/shared/hooks/useConfirm';
import { apiGet, apiPost, apiDelete, triggerDownload } from '@/shared/lib/api';
import { getIntlLocale } from '@/shared/lib/formatters';
import { useToastStore } from '@/stores/useToastStore';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { useCostDatabaseStore, REGION_MAP } from '@/stores/useCostDatabaseStore';
import { useAuthStore } from '@/stores/useAuthStore';
import { EscalationCalculator } from './EscalationCalculator';

/* ── Types ─────────────────────────────────────────────────────────────── */

interface CostComponent {
  name: string;
  code: string;
  unit: string;
  quantity: number;
  unit_rate: number;
  cost: number;
  type: 'material' | 'labor' | 'equipment' | 'operator' | 'electricity' | 'other';
}

interface CostItem {
  id: string;
  code: string;
  description: string;
  unit: string;
  rate: number;
  region: string | null;
  classification: Record<string, string>;
  components: CostComponent[];
  metadata_: Record<string, number>;
  source: string;
}

interface CostSearchResponse {
  items: CostItem[];
  total: number;
  limit: number;
  offset: number;
}

interface RegionStat {
  region: string;
  count: number;
}

interface Project {
  id: string;
  name: string;
  currency: string;
}

interface BOQ {
  id: string;
  project_id: string;
  name: string;
  status: string;
}

interface BOQSection {
  id: string;
  ordinal: string;
  description: string;
  unit: string;
}

/* ── Export helper ─────────────────────────────────────────────────────── */

async function downloadExcelExport(): Promise<void> {
  const token = useAuthStore.getState().accessToken;
  const headers: Record<string, string> = { Accept: 'application/octet-stream' };
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  const response = await fetch('/api/v1/costs/actions/export-excel/', { method: 'GET', headers });
  if (!response.ok) {
    let detail = 'Export failed';
    try {
      const body = await response.json();
      detail = body.detail || detail;
    } catch {
      // ignore parse error
    }
    throw new Error(detail);
  }

  const blob = await response.blob();
  const disposition = response.headers.get('Content-Disposition');
  const filename = disposition?.match(/filename="?(.+)"?/)?.[1] || 'cost_database_export.xlsx';
  triggerDownload(blob, filename);
}

/* ── Favourites & Recently Used (localStorage) ────────────────────────── */

const FAVOURITES_KEY = 'oe_cost_favourites';
const RECENT_KEY = 'oe_cost_recent';
const MAX_RECENT = 20;

interface RecentItem {
  id: string;
  name: string;
  usedAt: string;
}

function loadFavourites(): Set<string> {
  try {
    const raw = localStorage.getItem(FAVOURITES_KEY);
    if (raw) return new Set(JSON.parse(raw) as string[]);
  } catch {
    // ignore
  }
  return new Set();
}

function saveFavourites(ids: Set<string>): void {
  localStorage.setItem(FAVOURITES_KEY, JSON.stringify([...ids]));
}

function loadRecent(): RecentItem[] {
  try {
    const raw = localStorage.getItem(RECENT_KEY);
    if (raw) return JSON.parse(raw) as RecentItem[];
  } catch {
    // ignore
  }
  return [];
}

function addRecentItem(item: { id: string; description: string }): void {
  const list = loadRecent().filter((r) => r.id !== item.id);
  list.unshift({ id: item.id, name: item.description, usedAt: new Date().toISOString() });
  if (list.length > MAX_RECENT) list.length = MAX_RECENT;
  localStorage.setItem(RECENT_KEY, JSON.stringify(list));
}

/* ── Mini flag ─────────────────────────────────────────────────────────── */

function MiniFlag({ code, size = 14 }: { code: string; size?: number }) {
  if (!code || code === 'custom') {
    return <House size={size} className="shrink-0 text-oe-blue" />;
  }
  return <CountryFlag code={code} size={Math.round(size * 1.6)} className="shadow-xs border border-black/5" />;
}

/* ── Region Tab Bar ───────────────────────────────────────────────────── */

function RegionTabBar({
  regions,
  regionStats,
  activeRegion,
  onChangeRegion,
  totalItemCount,
}: {
  regions: string[];
  regionStats: RegionStat[];
  activeRegion: string;
  onChangeRegion: (region: string) => void;
  totalItemCount: number;
}) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const scrollRef = useRef<HTMLDivElement>(null);
  const [canScrollLeft, setCanScrollLeft] = useState(false);
  const [canScrollRight, setCanScrollRight] = useState(false);

  const totalItems = regionStats.reduce((s, r) => s + r.count, 0);
  const statsMap = new Map(regionStats.map((r) => [r.region, r.count]));

  // Check scroll overflow
  const checkScroll = useCallback(() => {
    const el = scrollRef.current;
    if (!el) return;
    setCanScrollLeft(el.scrollLeft > 4);
    setCanScrollRight(el.scrollLeft + el.clientWidth < el.scrollWidth - 4);
  }, []);

  useEffect(() => {
    checkScroll();
    const el = scrollRef.current;
    if (!el) return;
    el.addEventListener('scroll', checkScroll, { passive: true });
    const ro = new ResizeObserver(checkScroll);
    ro.observe(el);
    return () => {
      el.removeEventListener('scroll', checkScroll);
      ro.disconnect();
    };
  }, [checkScroll, regions]);

  const scroll = useCallback((dir: 'left' | 'right') => {
    const el = scrollRef.current;
    if (!el) return;
    el.scrollBy({ left: dir === 'left' ? -200 : 200, behavior: 'smooth' });
  }, []);

  if (regions.length === 0 && totalItemCount === 0) {
    return (
      <div className="mb-6 rounded-xl border-2 border-dashed border-border-light bg-surface-secondary/50 p-6 text-center">
        <Database size={28} className="mx-auto mb-2 text-content-tertiary" strokeWidth={1.5} />
        <p className="text-sm font-medium text-content-primary mb-1">
          {t('costs.no_database_loaded', { defaultValue: 'No database loaded' })}
        </p>
        <p className="text-xs text-content-tertiary mb-3">
          {t('costs.import_first_hint', {
            defaultValue: 'Import a regional cost database to start searching 55,000+ items.',
          })}
        </p>
        <Button
          variant="primary"
          size="sm"
          icon={<Upload size={14} />}
          onClick={() => navigate('/costs/import')}
        >
          {t('costs.import_database', { defaultValue: 'Import Database' })}
        </Button>
      </div>
    );
  }

  if (regions.length === 0) {
    return null;
  }

  return (
    <div className="mb-5 relative">
      {/* Scroll shadow + arrow (left) */}
      {canScrollLeft && (
        <button
          onClick={() => scroll('left')}
          className="absolute left-0 top-0 bottom-0 z-10 flex items-center pl-0.5 pr-3 bg-gradient-to-r from-surface-primary via-surface-primary/90 to-transparent"
        >
          <ChevronLeft size={16} className="text-content-tertiary" />
        </button>
      )}

      {/* Scroll shadow + arrow (right) */}
      {canScrollRight && (
        <button
          onClick={() => scroll('right')}
          className="absolute right-0 top-0 bottom-0 z-10 flex items-center pr-0.5 pl-3 bg-gradient-to-l from-surface-primary via-surface-primary/90 to-transparent"
        >
          <ChevronRight size={16} className="text-content-tertiary" />
        </button>
      )}

      <div
        ref={scrollRef}
        className="flex items-stretch gap-1 overflow-x-auto scrollbar-none scroll-smooth"
      >
        {/* All tab */}
        <button
          onClick={() => onChangeRegion('')}
          className={`
            group relative flex items-center gap-2 shrink-0 rounded-t-lg px-4 py-2.5
            border-b-2 transition-all duration-fast ease-oe
            ${
              activeRegion === ''
                ? 'border-oe-blue bg-oe-blue-subtle/20 text-content-primary'
                : 'border-transparent hover:bg-surface-secondary text-content-secondary hover:text-content-primary'
            }
          `}
        >
          <Database size={14} className={activeRegion === '' ? 'text-oe-blue' : 'text-content-tertiary'} />
          <span className="text-sm font-medium whitespace-nowrap">
            {t('costs.all_regions', { defaultValue: 'All' })}
          </span>
          <span className={`text-2xs tabular-nums ${activeRegion === '' ? 'text-oe-blue' : 'text-content-quaternary'}`}>
            {totalItems > 0 ? totalItems.toLocaleString() : ''}
          </span>
        </button>

        {/* Separator */}
        <div className="w-px shrink-0 bg-border-light my-2" />

        {/* Region tabs */}
        {regions.map((regionId) => {
          const info = REGION_MAP[regionId];
          if (!info) return null;
          const isActive = activeRegion === regionId;
          const count = statsMap.get(regionId) ?? 0;

          return (
            <button
              key={regionId}
              onClick={() => onChangeRegion(regionId)}
              className={`
                group relative flex items-center gap-2 shrink-0 rounded-t-lg px-3.5 py-2.5
                border-b-2 transition-all duration-fast ease-oe
                ${
                  isActive
                    ? 'border-oe-blue bg-oe-blue-subtle/20 text-content-primary'
                    : 'border-transparent hover:bg-surface-secondary text-content-secondary hover:text-content-primary'
                }
              `}
            >
              <MiniFlag code={info.flag} size={13} />
              <span className="text-sm font-medium whitespace-nowrap">{info.name}</span>
              <span className={`text-2xs tabular-nums ${isActive ? 'text-oe-blue' : 'text-content-quaternary'}`}>
                {count > 0 ? count.toLocaleString() : ''}
              </span>
            </button>
          );
        })}

        {/* Separator */}
        <div className="w-px shrink-0 bg-border-light my-2" />

        {/* Add database button */}
        <button
          onClick={() => navigate('/costs/import')}
          className="flex items-center gap-1.5 shrink-0 rounded-t-lg px-3 py-2.5 border-b-2 border-transparent text-content-tertiary hover:text-oe-blue hover:bg-oe-blue-subtle/10 transition-all duration-fast ease-oe"
          title={t('costs.import_database', { defaultValue: 'Import database' })}
        >
          <Plus size={14} />
          <span className="text-sm font-medium whitespace-nowrap">
            {t('costs.add_database', { defaultValue: 'Import' })}
          </span>
        </button>
      </div>

      {/* Bottom border line */}
      <div className="h-px bg-border-light -mt-px" />
    </div>
  );
}

/* ── Constants ─────────────────────────────────────────────────────────── */

const UNITS = ['', 'm', 'm2', 'm3', 'kg', 't', 'pcs', 'lsum', 'h', 'set', 'lm'] as const;
const SOURCES = ['', 'cwicr', 'custom'] as const;
const PAGE_SIZE = 20;

/* ── API ───────────────────────────────────────────────────────────────── */

function buildSearchUrl(
  query: string,
  unit: string,
  source: string,
  region: string,
  offset: number,
  category?: string,
): string {
  const params = new URLSearchParams();
  if (query) params.set('q', query);
  if (unit) params.set('unit', unit);
  if (source) params.set('source', source);
  if (region) params.set('region', region);
  if (category) params.set('category', category);
  params.set('limit', String(PAGE_SIZE));
  params.set('offset', String(offset));
  return `/v1/costs/?${params.toString()}`;
}

/* ── Component ─────────────────────────────────────────────────────────── */

export function CostsPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const addToast = useToastStore((s) => s.addToast);
  const queryClient = useQueryClient();

  // Global active region from Zustand store
  const activeRegion = useCostDatabaseStore((s) => s.activeRegion);
  const setActiveRegion = useCostDatabaseStore((s) => s.setActiveRegion);

  const [query, setQuery] = useState('');
  const [debouncedQuery, setDebouncedQuery] = useState('');
  const [unit, setUnit] = useState('');
  const [source, setSource] = useState('');
  const [category, setCategory] = useState('');
  const [region, setRegion] = useState<string>(activeRegion);
  const [offset, setOffset] = useState(0);
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [showAddToBOQ, setShowAddToBOQ] = useState(false);
  const [showCreateAssembly, setShowCreateAssembly] = useState(false);
  const [showCreateItem, setShowCreateItem] = useState(false);
  const [showEscalation, setShowEscalation] = useState(false);
  const [semanticSearch, setSemanticSearch] = useState(false);

  // Column sorting
  type SortField = 'code' | 'rate' | 'description' | '';
  type SortDir = 'asc' | 'desc';
  const [sortField, setSortField] = useState<SortField>('');
  const [sortDir, setSortDir] = useState<SortDir>('asc');

  // Favourites & Recently Used
  const [favourites, setFavourites] = useState<Set<string>>(() => loadFavourites());
  const [recentItems, setRecentItems] = useState<RecentItem[]>(() => loadRecent());
  const [specialTab, setSpecialTab] = useState<'' | 'favourites' | 'recent'>('');

  // Fetch loaded regions list
  const { data: loadedRegions } = useQuery({
    queryKey: ['costs', 'regions'],
    queryFn: () => apiGet<string[]>('/v1/costs/regions/'),
    retry: false,
  });

  // Fetch per-region stats (for item counts in tabs)
  const { data: regionStats } = useQuery({
    queryKey: ['costs', 'regions', 'stats'],
    queryFn: () => apiGet<RegionStat[]>('/v1/costs/regions/stats/'),
    retry: false,
  });

  // Fetch distinct categories (classification.collection values)
  const { data: categories } = useQuery({
    queryKey: ['costs', 'categories', region],
    queryFn: () => {
      const params = new URLSearchParams();
      if (region) params.set('region', region);
      return apiGet<string[]>(`/v1/costs/categories/?${params.toString()}`);
    },
    retry: false,
  });

  // Debounce search query (300ms)
  useEffect(() => {
    const timer = setTimeout(() => setDebouncedQuery(query), 300);
    return () => clearTimeout(timer);
  }, [query]);

  const searchUrl = buildSearchUrl(debouncedQuery, unit, source, region, offset, category);

  const { data, isLoading, isFetching } = useQuery({
    queryKey: ['costs', debouncedQuery, unit, source, category, region, offset, semanticSearch],
    queryFn: async () => {
      // Use vector semantic search when toggled and query is present
      if (semanticSearch && debouncedQuery.length >= 2) {
        try {
          const params = new URLSearchParams({ q: debouncedQuery, limit: String(PAGE_SIZE) });
          if (region) params.set('region', region);
          const results = await apiGet<Array<Record<string, unknown>>>(`/v1/costs/vector/search/?${params}`);
          // Wrap in CostSearchResponse format
          return {
            items: results.map((r) => ({
              id: String(r.id ?? ''),
              code: String(r.code ?? ''),
              description: String(r.description ?? ''),
              unit: String(r.unit ?? ''),
              rate: Number(r.rate ?? 0),
              region: String(r.region ?? ''),
              classification: (r.classification ?? {}) as Record<string, string>,
              components: [],
              metadata_: {},
              source: 'cwicr',
            })),
            total: results.length,
            limit: PAGE_SIZE,
            offset: 0,
          } as CostSearchResponse;
        } catch (err) {
          console.error('Semantic search failed, falling back to regular search:', err);
          // Fall back to regular search
        }
      }
      return apiGet<CostSearchResponse>(searchUrl);
    },
    placeholderData: (prev) => prev,
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => apiDelete(`/v1/costs/${id}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['costs'] });
      addToast({ type: 'success', title: t('costs.item_deleted', { defaultValue: 'Item deleted' }) });
    },
    onError: (err: Error) => {
      addToast({ type: 'error', title: t('costs.delete_failed', { defaultValue: 'Delete failed' }), message: err.message });
    },
  });

  const exportMutation = useMutation({
    mutationFn: downloadExcelExport,
    onSuccess: () => {
      addToast({
        type: 'success',
        title: t('costs.export_success', { defaultValue: 'Export complete' }),
        message: t('costs.export_success_msg', { defaultValue: 'Excel file downloaded.' }),
      });
    },
    onError: (err: Error) => {
      addToast({
        type: 'error',
        title: t('costs.export_failed', { defaultValue: 'Export failed' }),
        message: err.message,
      });
    },
  });

  const rawItems = data?.items ?? [];
  const rawTotal = data?.total ?? 0;

  // Apply favourites / recent filter on top of API results
  const items = specialTab === 'favourites'
    ? rawItems.filter((i) => favourites.has(i.id))
    : specialTab === 'recent'
      ? rawItems.filter((i) => recentItems.some((r) => r.id === i.id))
      : rawItems;
  const total = specialTab ? items.length : rawTotal;
  // hasMore: specialTab ? false : offset + PAGE_SIZE < rawTotal — for future load-more UI

  // Client-side column sorting
  const sortedItems = useMemo(() => {
    if (!sortField) return items;
    return [...items].sort((a, b) => {
      let cmp = 0;
      if (sortField === 'code') cmp = a.code.localeCompare(b.code);
      else if (sortField === 'rate') cmp = a.rate - b.rate;
      else if (sortField === 'description') cmp = a.description.localeCompare(b.description);
      return sortDir === 'desc' ? -cmp : cmp;
    });
  }, [items, sortField, sortDir]);

  const toggleSort = useCallback((field: SortField) => {
    if (sortField === field) {
      setSortDir(d => d === 'asc' ? 'desc' : 'asc');
    } else {
      setSortField(field);
      setSortDir('asc');
    }
  }, [sortField]);

  // Active filter count & clear all
  const activeFilterCount = [query, unit, source, category].filter(Boolean).length + (region ? 1 : 0) + (specialTab ? 1 : 0);

  const clearAllFilters = useCallback(() => {
    setQuery('');
    setDebouncedQuery('');
    setUnit('');
    setSource('');
    setCategory('');
    setOffset(0);
    setSpecialTab('');
  }, []);

  const handleSearch = useCallback((value: string) => {
    setQuery(value);
    setOffset(0);
  }, []);

  const handleUnitChange = useCallback((value: string) => {
    setUnit(value);
    setOffset(0);
  }, []);

  const handleSourceChange = useCallback((value: string) => {
    setSource(value);
    setOffset(0);
  }, []);

  const handleCategoryChange = useCallback((value: string) => {
    setCategory(value);
    setOffset(0);
  }, []);

  const handleRegionChange = useCallback(
    (value: string) => {
      setRegion(value);
      setOffset(0);
      setActiveRegion(value);
    },
    [setActiveRegion],
  );

  const handleCopyRate = useCallback(async (item: CostItem) => {
    try {
      await navigator.clipboard.writeText(String(item.rate));
      setCopiedId(item.id);
      setTimeout(() => setCopiedId(null), 2000);
    } catch {
      // Clipboard API unavailable -- silently ignore.
    }
  }, []);

  // handleLoadMore for future pagination: () => setOffset(prev => prev + PAGE_SIZE)

  const toggleSelect = useCallback((id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  const toggleSelectAll = useCallback(() => {
    if (selectedIds.size === items.length) {
      setSelectedIds(new Set());
    } else {
      setSelectedIds(new Set(items.map((i) => i.id)));
    }
  }, [items, selectedIds.size]);

  const toggleFavourite = useCallback((id: string) => {
    setFavourites((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      saveFavourites(next);
      return next;
    });
  }, []);

  const trackRecentUsage = useCallback((item: CostItem) => {
    addRecentItem({ id: item.id, description: item.description });
    setRecentItems(loadRecent());
  }, []);

  const selectedItems = items.filter((i) => selectedIds.has(i.id));

  const fmt = (n: number) =>
    new Intl.NumberFormat(getIntlLocale(), {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }).format(n);

  // Current region info for subtitle
  const regionInfo = region ? REGION_MAP[region] : null;

  return (
    <div className="max-w-content mx-auto animate-fade-in">
      <Breadcrumb items={[
        { label: t('nav.dashboard', 'Dashboard'), to: '/' },
        { label: t('costs.title', 'Cost Database') },
      ]} className="mb-4" />

      {/* Header */}
      <div className="mb-5 flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold text-content-primary">{t('costs.title')}</h1>
          <p className="mt-1 text-sm text-content-secondary">
            {regionInfo
              ? `${regionInfo.name} — ${total.toLocaleString()} ${t('costs.items', 'items')}`
              : total > 0
                ? `${total.toLocaleString()} ${t('costs.results_found', 'results found')}`
                : t('costs.search_hint', 'Search cost items by description or code')}
          </p>
          <InfoHint inline className="ml-1" text={t('costs.what_is_cost_db', { defaultValue: 'Unit rates and composite prices for materials, labor, and equipment. Import regional databases (CWICR, BKI, RSMeans) from Modules or add custom rates. Toggle AI Semantic Search for natural-language queries.' })} />
        </div>
        <div className="flex items-center gap-2">
          {total > 0 && (
            <Button
              variant="secondary"
              size="sm"
              icon={
                exportMutation.isPending ? (
                  <Loader2 size={14} className="animate-spin" />
                ) : (
                  <Download size={14} />
                )
              }
              onClick={() => exportMutation.mutate()}
              disabled={exportMutation.isPending}
            >
              {t('costs.export', { defaultValue: 'Export' })}
            </Button>
          )}
          <Button
            variant="secondary"
            size="sm"
            icon={<TrendingUp size={14} />}
            onClick={() => setShowEscalation((p) => !p)}
            className={showEscalation ? 'border-amber-300 text-amber-600 bg-amber-50 dark:bg-amber-900/20' : ''}
          >
            {t('costs.escalation', { defaultValue: 'Escalation' })}
          </Button>
          <Button
            variant="secondary"
            size="sm"
            icon={<Plus size={14} />}
            onClick={() => setShowCreateItem(true)}
          >
            {t('costs.add_item', { defaultValue: 'Add Item' })}
          </Button>
          <Button
            variant="primary"
            size="sm"
            icon={<Upload size={14} />}
            onClick={() => navigate('/costs/import')}
          >
            {t('costs.import_database', { defaultValue: 'Import' })}
          </Button>
        </div>
      </div>

      {/* Escalation Calculator (collapsible) */}
      {showEscalation && (
        <EscalationCalculator className="mb-5 animate-fade-in" />
      )}

      {/* Region Tabs */}
      <RegionTabBar
        regions={loadedRegions ?? []}
        regionStats={regionStats ?? []}
        activeRegion={region}
        onChangeRegion={handleRegionChange}
        totalItemCount={total}
      />

      {/* Favourites & Recent Quick Filters */}
      <div className="mb-4 flex items-center gap-2">
        <button
          onClick={() => setSpecialTab(specialTab === 'favourites' ? '' : 'favourites')}
          className={`flex items-center gap-1.5 px-3 py-1.5 text-sm rounded-lg transition-colors ${
            specialTab === 'favourites'
              ? 'bg-yellow-50 text-yellow-700 border border-yellow-200'
              : 'text-content-secondary hover:bg-surface-secondary border border-transparent'
          }`}
        >
          <Star size={14} className={specialTab === 'favourites' ? 'fill-yellow-400' : ''} />
          {t('costs.favourites', { defaultValue: 'Favourites' })}
          {favourites.size > 0 && (
            <span className="text-xs tabular-nums">{favourites.size}</span>
          )}
        </button>
        <button
          onClick={() => setSpecialTab(specialTab === 'recent' ? '' : 'recent')}
          className={`flex items-center gap-1.5 px-3 py-1.5 text-sm rounded-lg transition-colors ${
            specialTab === 'recent'
              ? 'bg-blue-50 text-blue-700 border border-blue-200'
              : 'text-content-secondary hover:bg-surface-secondary border border-transparent'
          }`}
        >
          <Clock size={14} />
          {t('costs.recently_used', { defaultValue: 'Recently Used' })}
          {recentItems.length > 0 && (
            <span className="text-xs tabular-nums">{recentItems.length}</span>
          )}
        </button>
      </div>

      {/* Search & Filters */}
      <Card padding="none" className="mb-6">
        <div className="flex flex-col gap-3 p-4 sm:flex-row sm:items-end">
          {/* Search input + AI toggle */}
          <div className="relative flex-1 flex gap-2">
            <div className="relative flex-1">
              <div className="pointer-events-none absolute inset-y-0 left-0 flex items-center pl-3 text-content-tertiary">
                <Search size={16} />
              </div>
              <input
                type="text"
                value={query}
                onChange={(e) => handleSearch(e.target.value)}
                placeholder={
                  semanticSearch
                    ? t('costs.semantic_placeholder', 'Describe what you need (AI finds similar)...')
                    : regionInfo
                      ? t('costs.search_in_region', { defaultValue: 'Search in {{name}}...', name: regionInfo.name })
                      : t('costs.search_placeholder', 'Search by description or code...')
                }
                aria-label={t('costs.search_placeholder', { defaultValue: 'Search cost items' })}
                className={`h-10 w-full rounded-lg border bg-surface-primary pl-10 ${query ? 'pr-8' : 'pr-3'} text-sm text-content-primary placeholder:text-content-tertiary transition-all duration-fast ease-oe focus:outline-none focus:ring-2 focus:border-transparent hover:border-content-tertiary ${
                  semanticSearch ? 'border-purple-400 focus:ring-purple-400/30' : 'border-border focus:ring-oe-blue'
                }`}
              />
              {query && (
                <button
                  onClick={() => { setQuery(''); setDebouncedQuery(''); setOffset(0); }}
                  className="absolute inset-y-0 right-0 flex items-center pr-3 text-content-tertiary hover:text-content-primary"
                >
                  <X size={14} />
                </button>
              )}
            </div>
            <button
              onClick={() => setSemanticSearch(!semanticSearch)}
              title={semanticSearch ? t('costs.switch_to_text_search', { defaultValue: 'Switch to text search' }) : t('costs.switch_to_ai_search', { defaultValue: 'Switch to AI semantic search' })}
              className={`flex h-10 shrink-0 items-center gap-1.5 rounded-lg border px-2.5 transition-all text-xs font-medium ${
                semanticSearch
                  ? 'border-purple-400 bg-purple-500/10 text-purple-500'
                  : 'border-border bg-surface-primary text-content-tertiary hover:text-purple-500 hover:border-purple-300'
              }`}
            >
              <Sparkles size={14} />
              <span className="hidden sm:inline">{semanticSearch ? 'AI' : 'AI'}</span>
            </button>
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
                  {t(`costs.source_${s}`, { defaultValue: s === 'cwicr' ? 'CWICR' : s.charAt(0).toUpperCase() + s.slice(1) })}
                </option>
              ))}
            </select>
            <div className="pointer-events-none absolute inset-y-0 right-0 flex items-center pr-2.5 text-content-tertiary">
              <ChevronDown size={14} />
            </div>
          </div>

          {/* Category filter */}
          {categories && categories.length > 0 && (
            <div className="relative">
              <select
                value={category}
                onChange={(e) => handleCategoryChange(e.target.value)}
                className="h-10 w-full appearance-none rounded-lg border border-border bg-surface-primary pl-3 pr-9 text-sm text-content-primary transition-all duration-fast ease-oe focus:outline-none focus:ring-2 focus:ring-oe-blue focus:border-transparent hover:border-content-tertiary sm:w-48"
              >
                <option value="">
                  {t('costs.all_categories', 'All categories')}
                </option>
                {categories.map((cat) => (
                  <option key={cat} value={cat}>
                    {cat}
                  </option>
                ))}
              </select>
              <div className="pointer-events-none absolute inset-y-0 right-0 flex items-center pr-2.5 text-content-tertiary">
                <ChevronDown size={14} />
              </div>
            </div>
          )}
        </div>
      </Card>

      {/* Active filters indicator */}
      {activeFilterCount > 0 && (
        <div className="flex items-center gap-2 mb-4 -mt-3">
          <Badge variant="blue" size="sm">{activeFilterCount} {t('costs.filters_active', { defaultValue: 'filters active' })}</Badge>
          <button
            onClick={clearAllFilters}
            className="text-xs text-oe-blue hover:underline"
          >
            {t('costs.clear_filters', { defaultValue: 'Clear all' })}
          </button>
        </div>
      )}

      {/* Results Table */}
      {isLoading ? (
        <SkeletonTable rows={6} columns={6} />
      ) : items.length === 0 ? (
        <EmptyState
          icon={specialTab === 'favourites' ? <Star size={24} strokeWidth={1.5} /> : specialTab === 'recent' ? <Clock size={24} strokeWidth={1.5} /> : <Database size={24} strokeWidth={1.5} />}
          title={
            specialTab === 'favourites'
              ? t('costs.no_favourites', { defaultValue: 'No favourites yet' })
              : specialTab === 'recent'
                ? t('costs.no_recent', { defaultValue: 'No recently used items' })
                : t('costs.no_results', 'No cost items found')
          }
          description={
            specialTab === 'favourites'
              ? t('costs.no_favourites_hint', { defaultValue: 'Click the star icon on any cost item to add it to your favourites' })
              : specialTab === 'recent'
                ? t('costs.no_recent_hint', { defaultValue: 'Items you add to BOQ will appear here for quick access' })
                : query
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
                    <th className="px-2 py-3 w-16">
                      <div className="flex items-center gap-0.5">
                        <Star size={14} className="text-content-quaternary ml-1" />
                        <button
                          onClick={toggleSelectAll}
                          className="flex h-5 w-5 items-center justify-center rounded text-content-tertiary hover:text-oe-blue transition-colors"
                        >
                          {selectedIds.size > 0 && selectedIds.size === items.length ? (
                            <CheckSquare size={16} className="text-oe-blue" />
                          ) : (
                            <Square size={16} />
                          )}
                        </button>
                      </div>
                    </th>
                    <th className="px-4 py-3 font-medium text-content-secondary w-28 cursor-pointer select-none" onClick={() => toggleSort('code')}>
                      <div className="flex items-center gap-1">
                        {t('costs.code', 'Code')}
                        {sortField === 'code' && (sortDir === 'asc' ? <ChevronUp size={12} /> : <ChevronDown size={12} />)}
                      </div>
                    </th>
                    <th className="px-4 py-3 font-medium text-content-secondary cursor-pointer select-none" onClick={() => toggleSort('description')}>
                      <div className="flex items-center gap-1">
                        {t('boq.description')}
                        {sortField === 'description' && (sortDir === 'asc' ? <ChevronUp size={12} /> : <ChevronDown size={12} />)}
                      </div>
                    </th>
                    <th className="px-4 py-3 font-medium text-content-secondary w-20 text-center">
                      {t('boq.unit')}
                    </th>
                    <th className="px-4 py-3 font-medium text-content-secondary w-32 text-right cursor-pointer select-none" onClick={() => toggleSort('rate')}>
                      <div className="flex items-center justify-end gap-1">
                        {t('costs.rate', 'Rate')}
                        {sortField === 'rate' && (sortDir === 'asc' ? <ChevronUp size={12} /> : <ChevronDown size={12} />)}
                      </div>
                    </th>
                    <th className="px-4 py-3 font-medium text-content-secondary w-28 text-center">
                      {t('costs.classification', 'Class.')}
                    </th>
                    <th className="px-2 py-3 w-20" />
                  </tr>
                </thead>
                <tbody className="divide-y divide-border-light">
                  {sortedItems.map((item) => {
                    const isExpanded = expandedId === item.id;
                    const hasComponents = item.components && item.components.length > 0;
                    return (
                      <CostItemRow
                        key={item.id}
                        item={item}
                        isExpanded={isExpanded}
                        hasComponents={hasComponents}
                        copiedId={copiedId}
                        isSelected={selectedIds.has(item.id)}
                        isFavourite={favourites.has(item.id)}
                        onSelect={() => toggleSelect(item.id)}
                        onToggle={() => setExpandedId(isExpanded ? null : item.id)}
                        onCopy={() => handleCopyRate(item)}
                        onToggleFavourite={() => toggleFavourite(item.id)}
                        onDelete={(id) => deleteMutation.mutate(id)}
                        fmt={fmt}
                        t={t}
                      />
                    );
                  })}
                </tbody>
              </table>
            </div>
          </Card>

          {/* Pagination */}
          {(() => {
            const currentPage = Math.floor(offset / PAGE_SIZE) + 1;
            const totalPages = Math.ceil(total / PAGE_SIZE);
            const goToPage = (p: number) => setOffset((p - 1) * PAGE_SIZE);
            // Show up to 5 page buttons around current
            const start = Math.max(1, currentPage - 2);
            const end = Math.min(totalPages, start + 4);
            const pages = Array.from({ length: end - start + 1 }, (_, i) => start + i);

            return (
              <div className="mt-6 flex flex-col items-center gap-3">
                <p className="text-xs text-content-tertiary">
                  {t('costs.showing_range', {
                    defaultValue: '{{from}}-{{to}} of {{total}}',
                    from: offset + 1,
                    to: Math.min(offset + PAGE_SIZE, total),
                    total: total.toLocaleString(),
                  })}
                </p>
                {totalPages > 1 && (
                  <div className="flex items-center gap-1">
                    <button
                      onClick={() => goToPage(currentPage - 1)}
                      disabled={currentPage === 1 || isFetching}
                      className="flex h-8 w-8 items-center justify-center rounded-lg text-content-tertiary hover:bg-surface-secondary disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
                    >
                      <ChevronLeft size={16} />
                    </button>
                    {start > 1 && (
                      <>
                        <button onClick={() => goToPage(1)} className="flex h-8 min-w-[32px] items-center justify-center rounded-lg text-xs text-content-secondary hover:bg-surface-secondary transition-colors">1</button>
                        {start > 2 && <span className="text-content-quaternary text-xs px-1">...</span>}
                      </>
                    )}
                    {pages.map((p) => (
                      <button
                        key={p}
                        onClick={() => goToPage(p)}
                        disabled={isFetching}
                        className={`flex h-8 min-w-[32px] items-center justify-center rounded-lg text-xs font-medium transition-colors ${
                          p === currentPage
                            ? 'bg-oe-blue text-white'
                            : 'text-content-secondary hover:bg-surface-secondary'
                        }`}
                      >
                        {p}
                      </button>
                    ))}
                    {end < totalPages && (
                      <>
                        {end < totalPages - 1 && <span className="text-content-quaternary text-xs px-1">...</span>}
                        <button onClick={() => goToPage(totalPages)} className="flex h-8 min-w-[32px] items-center justify-center rounded-lg text-xs text-content-secondary hover:bg-surface-secondary transition-colors">{totalPages}</button>
                      </>
                    )}
                    <button
                      onClick={() => goToPage(currentPage + 1)}
                      disabled={currentPage === totalPages || isFetching}
                      className="flex h-8 w-8 items-center justify-center rounded-lg text-content-tertiary hover:bg-surface-secondary disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
                    >
                      <ChevronRight size={16} />
                    </button>
                  </div>
                )}
              </div>
            );
          })()}
        </>
      )}

      {/* ── Floating Selection Bar ───────────────────────────────────────── */}
      {selectedIds.size > 0 && (
        <div className="fixed bottom-6 left-1/2 -translate-x-1/2 z-30 animate-fade-in">
          <div className="flex items-center gap-3 rounded-2xl border border-border bg-surface-elevated px-5 py-3 shadow-xl">
            <span className="text-sm font-semibold text-content-primary tabular-nums">
              {t('costs.n_selected', { defaultValue: '{{count}} selected', count: selectedIds.size })}
            </span>
            <div className="w-px h-6 bg-border-light" />
            <Button
              variant="primary"
              size="sm"
              icon={<Table2 size={14} />}
              onClick={() => setShowAddToBOQ(true)}
            >
              {t('costs.add_to_boq', { defaultValue: 'Add to BOQ' })}
            </Button>
            <Button
              variant="secondary"
              size="sm"
              icon={<Layers size={14} />}
              onClick={() => setShowCreateAssembly(true)}
            >
              {t('assemblies.create_assembly', { defaultValue: 'Create Assembly' })}
            </Button>
            <Button
              variant="secondary"
              size="sm"
              icon={<Copy size={14} />}
              onClick={() => {
                const text = selectedItems.map((i) => `${i.code}\t${i.description}\t${i.unit}\t${i.rate}`).join('\n');
                navigator.clipboard.writeText(text).then(() => {
                  addToast({ type: 'success', title: t('common.copied', { defaultValue: 'Copied' }), message: t('costs.items_copied', { defaultValue: '{{count}} items copied to clipboard', count: selectedIds.size }) });
                }).catch((err) => {
                  addToast({ type: 'error', title: t('common.copy_failed', { defaultValue: 'Copy failed' }), message: err?.message || 'Clipboard access denied' });
                });
              }}
            >
              {t('common.copy', { defaultValue: 'Copy' })}
            </Button>
            <button
              onClick={() => setSelectedIds(new Set())}
              className="flex h-7 w-7 items-center justify-center rounded-lg text-content-tertiary hover:text-content-primary hover:bg-surface-secondary transition-colors"
            >
              <X size={14} />
            </button>
          </div>
        </div>
      )}

      {/* ── Add to BOQ Modal ──────────────────────────────────────────── */}
      {showAddToBOQ && (
        <AddToBOQModal
          items={selectedItems}
          onClose={() => setShowAddToBOQ(false)}
          onSuccess={() => {
            // Track all added items as recently used
            selectedItems.forEach((si) => trackRecentUsage(si));
            setShowAddToBOQ(false);
            setSelectedIds(new Set());
          }}
        />
      )}

      {/* ── Create Assembly from selected items ────────────────────── */}
      {showCreateAssembly && (
        <CreateAssemblyFromCostsModal
          items={selectedItems}
          onClose={() => setShowCreateAssembly(false)}
          onSuccess={() => {
            setShowCreateAssembly(false);
            setSelectedIds(new Set());
          }}
        />
      )}

      {/* Create Custom Item Modal */}
      {showCreateItem && (
        <CreateCostItemModal
          onClose={() => setShowCreateItem(false)}
          onCreated={() => {
            setShowCreateItem(false);
            queryClient.invalidateQueries({ queryKey: ['costs'] });
          }}
        />
      )}
    </div>
  );
}

/* ── Add to BOQ Modal ──────────────────────────────────────────────────── */

function AddToBOQModal({
  items,
  onClose,
  onSuccess,
}: {
  items: CostItem[];
  onClose: () => void;
  onSuccess: () => void;
}) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const addToast = useToastStore((s) => s.addToast);
  const activeProjectId = useProjectContextStore((s) => s.activeProjectId);

  const [projectId, setProjectId] = useState(activeProjectId ?? '');
  const [boqId, setBoqId] = useState('');
  const [isAdding, setIsAdding] = useState(false);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [onClose]);

  // Fetch projects
  const { data: projects } = useQuery({
    queryKey: ['projects'],
    queryFn: () => apiGet<Project[]>('/v1/projects/'),
    retry: false,
    staleTime: 5 * 60_000,
  });

  // Fetch BOQs for selected project
  const { data: boqs } = useQuery({
    queryKey: ['boqs', projectId],
    queryFn: () => apiGet<BOQ[]>(`/v1/boq/boqs/?project_id=${projectId}`),
    enabled: !!projectId,
    retry: false,
  });

  // Auto-select first BOQ when list loads
  useEffect(() => {
    if (boqs && boqs.length > 0 && !boqId) {
      setBoqId(boqs[0]!.id);
    }
  }, [boqs, boqId]);

  // Fetch sections for selected BOQ (extract positions from BOQ detail)
  const { data: sections } = useQuery({
    queryKey: ['boq-sections', boqId],
    queryFn: async () => {
      const boqData = await apiGet<{ positions?: BOQSection[] }>(`/v1/boq/boqs/${boqId}`);
      const positions = boqData.positions ?? [];
      // Sections are positions with empty unit
      return positions.filter((p) => !p.unit || p.unit.trim() === '');
    },
    enabled: !!boqId,
    retry: false,
  });

  const [sectionId, setSectionId] = useState('');

  const handleAdd = useCallback(async () => {
    if (!boqId) return;
    setIsAdding(true);

    try {
      let nextOrdinal = 1;
      // Fetch BOQ detail to find the max existing ordinal for correct numbering
      try {
        const boqData = await apiGet<{ positions?: Array<{ ordinal: string }> }>(
          `/v1/boq/boqs/${boqId}`,
        );
        const existing = boqData.positions ?? [];
        if (existing.length > 0) {
          let maxNum = 0;
          for (const p of existing) {
            const parts = p.ordinal.split('.');
            for (const part of parts) {
              const n = parseInt(part, 10);
              if (!isNaN(n) && n > maxNum) maxNum = n;
            }
          }
          nextOrdinal = maxNum + 1;
        }
      } catch {
        // Fallback: start at 1
      }

      for (const item of items) {
        const section = String(Math.floor((nextOrdinal - 1) / 999) + 1).padStart(2, '0');
        const pos = String(((nextOrdinal - 1) % 999) + 1).padStart(3, '0');
        const ordinal = `${section}.${pos}`;

        // Build rich metadata with cost breakdown + components
        const meta: Record<string, unknown> = {
          cost_item_id: item.id,
          cost_item_code: item.code,
          cost_item_region: item.region,
          ...item.metadata_,
        };

        // Include resource breakdown for BOQ Grid display
        // BOQ Grid reads from metadata.resources: Array<{name, code, type, unit, quantity, unit_rate, total}>
        if (item.components && item.components.length > 0) {
          // Full component data available — use it directly
          meta.resources = item.components.map((c) => ({
            name: c.name,
            code: c.code,
            type: c.type,
            unit: c.unit,
            quantity: c.quantity,
            unit_rate: c.unit_rate,
            total: c.cost,
          }));
          meta.resource_count = item.components.length;
        } else if (item.metadata_) {
          // No components stored — synthesize from metadata cost summary
          const synth: Array<{ name: string; code: string; type: string; unit: string; quantity: number; unit_rate: number; total: number }> = [];
          const m = item.metadata_;
          if (m.labor_cost && m.labor_cost > 0) {
            synth.push({ name: t('costs.component_labor', { defaultValue: 'Labor' }), code: '', type: 'labor', unit: item.unit, quantity: 1, unit_rate: m.labor_cost, total: m.labor_cost });
          }
          if (m.material_cost && m.material_cost > 0) {
            synth.push({ name: t('costs.component_material', { defaultValue: 'Material' }), code: '', type: 'material', unit: item.unit, quantity: 1, unit_rate: m.material_cost, total: m.material_cost });
          }
          if (m.equipment_cost && m.equipment_cost > 0) {
            synth.push({ name: t('costs.component_equipment', { defaultValue: 'Equipment' }), code: '', type: 'equipment', unit: item.unit, quantity: 1, unit_rate: m.equipment_cost, total: m.equipment_cost });
          }
          if (synth.length > 0) {
            meta.resources = synth;
            meta.resource_count = synth.length;
          }
        }

        // Cost breakdown summary
        if (meta.resources) {
          const byType: Record<string, number> = {};
          for (const r of meta.resources as Array<{ type: string; total: number }>) {
            byType[r.type] = (byType[r.type] ?? 0) + r.total;
          }
          meta.cost_breakdown = byType;
        }

        await apiPost(`/v1/boq/boqs/${boqId}/positions/`, {
          boq_id: boqId,
          ordinal,
          description: item.description,
          unit: item.unit,
          quantity: 1,
          unit_rate: item.rate,
          classification: item.classification || {},
          parent_id: sectionId || undefined,
          source: 'cost_database',
          metadata: meta,
        });
        nextOrdinal++;
      }

      addToast({
        type: 'success',
        title: t('costs.items_added_to_boq', { defaultValue: '{{count}} items added to BOQ', count: items.length }),
        message: t('costs.positions_created_hint', { defaultValue: 'Positions created with unit rates from cost database' }),
      });
      onSuccess();
    } catch (err) {
      addToast({
        type: 'error',
        title: t('costs.add_items_failed', { defaultValue: 'Failed to add items' }),
        message: err instanceof Error ? err.message : t('common.unknown_error', { defaultValue: 'Unknown error' }),
      });
    } finally {
      setIsAdding(false);
    }
  }, [boqId, sectionId, items, addToast, onSuccess]);

  const fmt = (n: number) =>
    new Intl.NumberFormat(getIntlLocale(), { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(n);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 animate-fade-in" onClick={onClose}>
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="add-to-boq-modal-title"
        className="bg-surface-elevated rounded-2xl border border-border shadow-2xl w-full max-w-lg mx-4 overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-border-light">
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-oe-blue-subtle text-oe-blue">
              <Table2 size={18} />
            </div>
            <div>
              <h2 id="add-to-boq-modal-title" className="text-base font-semibold text-content-primary">{t('costs.add_to_boq', { defaultValue: 'Add to BOQ' })}</h2>
              <p className="text-xs text-content-tertiary">
                {t('costs.n_items_selected', { defaultValue: '{{count}} items selected', count: items.length })}
              </p>
            </div>
          </div>
          <button onClick={onClose} className="flex h-8 w-8 items-center justify-center rounded-lg text-content-tertiary hover:bg-surface-secondary hover:text-content-primary transition-colors">
            <X size={16} />
          </button>
        </div>

        {/* Body */}
        <div className="px-6 py-4 space-y-4">
          {/* Project selector */}
          <div>
            <label className="text-xs font-medium text-content-secondary mb-1.5 flex items-center gap-1.5">
              <FolderOpen size={12} />
              {t('projects.project', { defaultValue: 'Project' })}
            </label>
            {projects && projects.length > 0 ? (
              <select
                value={projectId}
                onChange={(e) => { setProjectId(e.target.value); setBoqId(''); setSectionId(''); }}
                className="h-10 w-full appearance-none rounded-lg border border-border bg-surface-primary px-3 text-sm text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue focus:border-transparent"
              >
                <option value="">{t('projects.select_project', { defaultValue: 'Select project...' })}</option>
                {projects.map((p) => (
                  <option key={p.id} value={p.id}>{p.name}</option>
                ))}
              </select>
            ) : (
              <div className="flex items-center gap-2">
                <span className="text-xs text-content-tertiary">{t('projects.no_projects', 'No projects yet')}</span>
                <Button variant="primary" size="sm" onClick={() => { onClose(); navigate('/projects/new'); }}>
                  {t('projects.create_project', { defaultValue: 'Create Project' })}
                </Button>
              </div>
            )}
          </div>

          {/* BOQ selector */}
          {projectId && (
            <div>
              <label className="text-xs font-medium text-content-secondary mb-1.5 flex items-center gap-1.5">
                <Table2 size={12} />
                {t('boq.title', { defaultValue: 'Bill of Quantities' })}
              </label>
              {boqs && boqs.length > 0 ? (
                <select
                  value={boqId}
                  onChange={(e) => { setBoqId(e.target.value); setSectionId(''); }}
                  className="h-10 w-full appearance-none rounded-lg border border-border bg-surface-primary px-3 text-sm text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue focus:border-transparent"
                >
                  <option value="">{t('boq.select_boq', { defaultValue: 'Select BOQ...' })}</option>
                  {boqs.map((b) => (
                    <option key={b.id} value={b.id}>{b.name} ({b.status})</option>
                  ))}
                </select>
              ) : (
                <div className="flex items-center gap-2">
                  <span className="text-xs text-content-tertiary">{t('boq.no_boqs_in_project', { defaultValue: 'No BOQs in this project.' })}</span>
                  <Button variant="primary" size="sm" onClick={() => { onClose(); navigate('/boq'); }}>
                    {t('boq.create_boq', { defaultValue: 'Create BOQ' })}
                  </Button>
                </div>
              )}
            </div>
          )}

          {/* Section selector (optional) */}
          {boqId && sections && sections.length > 0 && (
            <div>
              <label className="text-xs font-medium text-content-secondary mb-1.5 block">
                {t('boq.section_optional', { defaultValue: 'Section (optional)' })}
              </label>
              <select
                value={sectionId}
                onChange={(e) => setSectionId(e.target.value)}
                className="h-10 w-full appearance-none rounded-lg border border-border bg-surface-primary px-3 text-sm text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue focus:border-transparent"
              >
                <option value="">{t('boq.no_section', 'No section (top level)')}</option>
                {sections.map((s) => (
                  <option key={s.id} value={s.id}>{s.ordinal} — {s.description || t('boq.untitled_section', { defaultValue: 'Untitled section' })}</option>
                ))}
              </select>
            </div>
          )}

          {/* Preview */}
          {items.length > 0 && (
            <div className="rounded-lg border border-border-light bg-surface-secondary/50 overflow-hidden max-h-40 overflow-y-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="bg-surface-tertiary text-content-secondary">
                    <th className="px-3 py-1.5 text-left font-medium">{t('boq.description')}</th>
                    <th className="px-3 py-1.5 text-center font-medium w-14">{t('boq.unit')}</th>
                    <th className="px-3 py-1.5 text-right font-medium w-20">{t('costs.rate', 'Rate')}</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border-light">
                  {items.slice(0, 10).map((item) => (
                    <tr key={item.id}>
                      <td className="px-3 py-1.5 text-content-primary truncate max-w-[250px]">{item.description}</td>
                      <td className="px-3 py-1.5 text-center text-content-tertiary">{item.unit}</td>
                      <td className="px-3 py-1.5 text-right tabular-nums font-medium text-content-primary">{fmt(item.rate)}</td>
                    </tr>
                  ))}
                  {items.length > 10 && (
                    <tr>
                      <td colSpan={3} className="px-3 py-1.5 text-center text-content-quaternary">
                        {t('costs.and_n_more', { defaultValue: '...and {{count}} more', count: items.length - 10 })}
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between px-6 py-4 border-t border-border-light bg-surface-secondary/30">
          <span className="text-xs text-content-tertiary">
            {t('costs.n_positions_will_be_created', { defaultValue: '{{count}} positions will be created', count: items.length })}
          </span>
          <div className="flex items-center gap-2">
            <Button variant="secondary" size="sm" onClick={onClose}>
              {t('common.cancel', 'Cancel')}
            </Button>
            <Button
              variant="primary"
              size="sm"
              icon={isAdding ? <Loader2 size={14} className="animate-spin" /> : <Plus size={14} />}
              onClick={handleAdd}
              disabled={!boqId || isAdding}
            >
              {isAdding
                ? t('costs.adding', { defaultValue: 'Adding...' })
                : t('costs.add_n_to_boq', { defaultValue: 'Add {{count}} to BOQ', count: items.length })}
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}

/* ── Create Cost Item Modal ────────────────────────────────────────────── */

/* ── Create Assembly from Cost Items ──────────────────────────────────── */

function CreateAssemblyFromCostsModal({
  items,
  onClose,
  onSuccess,
}: {
  items: CostItem[];
  onClose: () => void;
  onSuccess: () => void;
}) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const addToast = useToastStore((s) => s.addToast);
  const [name, setName] = useState('');
  const [unit, setUnit] = useState('m2');
  const [isCreating, setIsCreating] = useState(false);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [onClose]);

  const fmt = (n: number) =>
    new Intl.NumberFormat(getIntlLocale(), { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(n);

  const totalRate = items.reduce((s, i) => s + (i.rate || 0), 0);

  const handleCreate = useCallback(async () => {
    if (!name.trim()) return;
    setIsCreating(true);
    try {
      const code = `ASM-${Date.now().toString(36).toUpperCase()}`;
      const assembly = await apiPost<{ id: string }>('/v1/assemblies/', {
        code,
        name: name.trim(),
        unit,
        category: 'General',
        currency: 'EUR',
      });

      // Add each cost item as a component
      for (const item of items) {
        await apiPost(`/v1/assemblies/${assembly.id}/components/`, {
          cost_item_id: item.id,
          description: item.description,
          unit: item.unit,
          unit_cost: item.rate,
          quantity: 1,
          factor: 1.0,
        });
      }

      addToast({
        type: 'success',
        title: t('assemblies.assembly_created', { defaultValue: 'Assembly created' }),
        message: `"${name.trim()}" ${t('assemblies.with_n_components', { defaultValue: 'with {{count}} components', count: items.length })}`,
      });
      onSuccess();
      navigate(`/assemblies/${assembly.id}`);
    } catch (err) {
      addToast({
        type: 'error',
        title: t('assemblies.create_failed', { defaultValue: 'Failed to create assembly' }),
        message: err instanceof Error ? err.message : t('common.unknown_error', { defaultValue: 'Unknown error' }),
      });
    } finally {
      setIsCreating(false);
    }
  }, [name, unit, items, addToast, t, onSuccess, navigate]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 animate-fade-in" onClick={onClose}>
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="create-assembly-modal-title"
        className="bg-surface-elevated rounded-2xl border border-border shadow-2xl w-full max-w-lg mx-4 overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-6 py-4 border-b border-border-light">
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-purple-100 text-purple-600 dark:bg-purple-900/30">
              <Layers size={18} />
            </div>
            <div>
              <h2 id="create-assembly-modal-title" className="text-base font-semibold text-content-primary">{t('assemblies.create_assembly', { defaultValue: 'Create Assembly' })}</h2>
              <p className="text-xs text-content-tertiary">
                {t('costs.n_cost_items_to_recipe', { defaultValue: '{{count}} cost items → reusable recipe', count: items.length })}
              </p>
            </div>
          </div>
          <button onClick={onClose} className="flex h-8 w-8 items-center justify-center rounded-lg text-content-tertiary hover:bg-surface-secondary hover:text-content-primary transition-colors">
            <X size={16} />
          </button>
        </div>

        <div className="px-6 py-4 space-y-4">
          <div>
            <label className="text-xs font-medium text-content-secondary mb-1.5 block">{t('assemblies.assembly_name', { defaultValue: 'Assembly Name' })}</label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder={t('assemblies.assembly_name_placeholder', { defaultValue: 'e.g. Reinforced Concrete Wall C30/37 24cm' })}
              className="h-10 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm text-content-primary placeholder:text-content-quaternary focus:outline-none focus:ring-2 focus:ring-purple-500/30 focus:border-purple-400"
              autoFocus
            />
          </div>
          <div>
            <label className="text-xs font-medium text-content-secondary mb-1.5 block">{t('boq.unit')}</label>
            <select
              value={unit}
              onChange={(e) => setUnit(e.target.value)}
              className="h-10 w-full appearance-none rounded-lg border border-border bg-surface-primary px-3 text-sm text-content-primary focus:outline-none focus:ring-2 focus:ring-purple-500/30"
            >
              {['m', 'm2', 'm3', 'kg', 't', 'pcs', 'lsum', 'h', 'set', 'lm'].map((u) => (
                <option key={u} value={u}>{u}</option>
              ))}
            </select>
          </div>

          {/* Preview components */}
          <div>
            <label className="text-xs font-medium text-content-secondary mb-1.5 block">{t('assemblies.components_count', { defaultValue: 'Components ({{count}})', count: items.length })}</label>
            <div className="rounded-lg border border-border-light overflow-hidden max-h-40 overflow-y-auto">
              {items.map((item) => (
                <div key={item.id} className="flex items-center justify-between px-3 py-2 text-xs border-b border-border-light/50 last:border-0">
                  <span className="text-content-primary truncate flex-1 mr-2">{item.description || item.code}</span>
                  <span className="text-content-secondary shrink-0 tabular-nums">{fmt(item.rate)} / {item.unit}</span>
                </div>
              ))}
            </div>
            <div className="flex items-center justify-between mt-2 text-xs">
              <span className="text-content-tertiary">{t('assemblies.total_rate_sum', { defaultValue: 'Total rate (sum of components)' })}</span>
              <span className="font-semibold text-content-primary tabular-nums">{fmt(totalRate)} EUR</span>
            </div>
          </div>
        </div>

        <div className="flex items-center justify-end gap-2 px-6 py-4 border-t border-border-light bg-surface-secondary/30">
          <Button variant="secondary" size="sm" onClick={onClose}>{t('common.cancel', { defaultValue: 'Cancel' })}</Button>
          <Button
            variant="primary"
            size="sm"
            onClick={handleCreate}
            loading={isCreating}
            disabled={!name.trim() || isCreating}
          >
            {t('assemblies.create_assembly', { defaultValue: 'Create Assembly' })}
          </Button>
        </div>
      </div>
    </div>
  );
}


const INITIAL_COST_ITEM_FORM = {
  code: '',
  description: '',
  unit: 'm2',
  rate: '',
  currency: 'EUR',
};

function CreateCostItemModal({
  onClose,
  onCreated,
}: {
  onClose: () => void;
  onCreated: () => void;
}) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [form, setForm] = useState(INITIAL_COST_ITEM_FORM);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [onClose]);

  const UNITS = ['m', 'm2', 'm3', 'kg', 't', 'pcs', 'lsum', 'h', 'set', 'lm'];

  const handleSubmit = useCallback(async () => {
    if (!form.description.trim()) return;
    setIsSubmitting(true);
    try {
      const code = form.code.trim() || `CUSTOM-${Date.now().toString(36).toUpperCase()}`;
      await apiPost('/v1/costs/', {
        code,
        description: form.description.trim(),
        unit: form.unit,
        rate: parseFloat(form.rate) || 0,
        currency: form.currency,
        source: 'custom',
        region: 'CUSTOM',
        classification: {},
      });
      addToast({ type: 'success', title: t('costs.item_created', { defaultValue: 'Cost item created' }) });
      onCreated();
    } catch (err) {
      addToast({ type: 'error', title: t('common.error'), message: err instanceof Error ? err.message : 'Failed' });
    } finally {
      setIsSubmitting(false);
    }
  }, [form, addToast, t, onCreated]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40" onClick={onClose}>
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="create-cost-item-modal-title"
        className="bg-surface-elevated rounded-2xl border border-border shadow-2xl w-full max-w-md mx-4 overflow-hidden animate-fade-in"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-6 py-4 border-b border-border-light">
          <div>
            <h2 id="create-cost-item-modal-title" className="text-base font-semibold text-content-primary">
              {t('costs.create_item', { defaultValue: 'Add Custom Cost Item' })}
            </h2>
            <p className="text-xs text-content-tertiary">
              {t('costs.create_item_desc', { defaultValue: 'Create your own cost item for this project' })}
            </p>
          </div>
          <button onClick={onClose} className="flex h-8 w-8 items-center justify-center rounded-lg text-content-tertiary hover:bg-surface-secondary">
            <X size={16} />
          </button>
        </div>

        <div className="px-6 py-4 space-y-3">
          <div>
            <label className="text-xs font-medium text-content-secondary mb-1 block">
              {t('costs.code', 'Code')}
              <span className="text-content-quaternary ml-1">({t('costs.optional', 'optional')})</span>
            </label>
            <input
              type="text"
              value={form.code}
              onChange={(e) => setForm({ ...form, code: e.target.value })}
              placeholder={t('costs.code_placeholder', { defaultValue: 'e.g. WALL-001' })}
              className="h-9 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue"
            />
          </div>

          <div>
            <label className="text-xs font-medium text-content-secondary mb-1 block">
              {t('boq.description')} *
            </label>
            <input
              autoFocus
              type="text"
              value={form.description}
              onChange={(e) => setForm({ ...form, description: e.target.value })}
              placeholder={t('costs.description_placeholder', { defaultValue: 'e.g. Reinforced concrete wall C30/37, 25cm' })}
              className="h-9 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue"
            />
          </div>

          <div className="grid grid-cols-3 gap-3">
            <div>
              <label className="text-xs font-medium text-content-secondary mb-1 block">{t('boq.unit')}</label>
              <select
                value={form.unit}
                onChange={(e) => setForm({ ...form, unit: e.target.value })}
                className="h-9 w-full rounded-lg border border-border bg-surface-primary px-2 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue"
              >
                {UNITS.map((u) => <option key={u} value={u}>{u}</option>)}
              </select>
            </div>
            <div>
              <label className="text-xs font-medium text-content-secondary mb-1 block">{t('costs.rate', 'Rate')}</label>
              <input
                type="number"
                step="0.01"
                value={form.rate}
                onChange={(e) => setForm({ ...form, rate: e.target.value })}
                placeholder="0.00"
                className="h-9 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm text-right focus:outline-none focus:ring-2 focus:ring-oe-blue"
              />
            </div>
            <div>
              <label className="text-xs font-medium text-content-secondary mb-1 block">{t('costs.currency', 'Currency')}</label>
              <select
                value={form.currency}
                onChange={(e) => setForm({ ...form, currency: e.target.value })}
                className="h-9 w-full rounded-lg border border-border bg-surface-primary px-2 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue"
              >
                {['EUR', 'USD', 'GBP', 'CHF', 'CAD', 'AUD', 'AED', 'RUB', 'CNY', 'INR', 'BRL'].map((c) => (
                  <option key={c} value={c}>{c}</option>
                ))}
              </select>
            </div>
          </div>
        </div>

        <div className="flex items-center justify-end gap-2 px-6 py-3 border-t border-border-light bg-surface-secondary/30">
          <Button variant="secondary" size="sm" onClick={onClose}>
            {t('common.cancel', 'Cancel')}
          </Button>
          <Button
            variant="primary"
            size="sm"
            disabled={!form.description.trim() || isSubmitting}
            icon={isSubmitting ? <Loader2 size={14} className="animate-spin" /> : <Plus size={14} />}
            onClick={handleSubmit}
          >
            {isSubmitting ? t('costs.creating', { defaultValue: 'Creating...' }) : t('costs.create', { defaultValue: 'Create Item' })}
          </Button>
        </div>
      </div>
    </div>
  );
}

/* ── Cost Item Row with expand ─────────────────────────────────────────── */

function CostItemRow({
  item,
  isExpanded,
  hasComponents,
  copiedId,
  isSelected,
  isFavourite,
  onSelect,
  onToggle,
  onCopy,
  onToggleFavourite,
  onDelete,
  fmt,
  t,
}: {
  item: CostItem;
  isExpanded: boolean;
  hasComponents: boolean;
  copiedId: string | null;
  isSelected: boolean;
  isFavourite: boolean;
  onSelect: () => void;
  onToggle: () => void;
  onCopy: () => void;
  onToggleFavourite: () => void;
  onDelete?: (id: string) => void;
  fmt: (n: number) => string;
  t: ReturnType<typeof import('react-i18next').useTranslation>['t'];
}) {
  const { confirm, ...confirmProps } = useConfirm();
  const meta = item.metadata_ ?? {};
  const laborCost = meta.labor_cost ?? 0;
  const equipmentCost = meta.equipment_cost ?? 0;
  const materialCost = meta.material_cost ?? 0;
  const laborHours = meta.labor_hours ?? 0;
  const workers = meta.workers_per_unit ?? 0;

  // Classify components by type
  const materials = (item.components ?? []).filter((c) => c.type === 'material');
  const machines = (item.components ?? []).filter((c) => c.type === 'equipment' || c.type === 'operator' || c.type === 'electricity');

  // Classification breadcrumb
  const cls = item.classification ?? {};
  const breadcrumb = [cls.category, cls.collection, cls.department, cls.section, cls.subsection]
    .filter(Boolean)
    .join(' > ');

  return (
    <>
      <tr
        onClick={hasComponents ? onToggle : undefined}
        className={`group transition-colors ${
          hasComponents ? 'cursor-pointer' : ''
        } ${isExpanded ? 'bg-oe-blue-subtle/10' : isSelected ? 'bg-oe-blue-subtle/5' : 'hover:bg-surface-secondary/50'}`}
      >
        <td className="px-2 py-3 w-10">
          <div className="flex items-center gap-0.5">
            <button
              onClick={(e) => { e.stopPropagation(); onToggleFavourite(); }}
              className="p-1 hover:bg-surface-secondary rounded transition-colors"
              title={isFavourite ? t('costs.remove_from_favourites', { defaultValue: 'Remove from favourites' }) : t('costs.add_to_favourites', { defaultValue: 'Add to favourites' })}
            >
              <Star
                size={14}
                className={isFavourite ? 'fill-yellow-400 text-yellow-400' : 'text-content-tertiary'}
              />
            </button>
            <button
              onClick={(e) => { e.stopPropagation(); onSelect(); }}
              className="flex h-5 w-5 items-center justify-center rounded text-content-tertiary hover:text-oe-blue transition-colors"
            >
              {isSelected ? (
                <CheckSquare size={16} className="text-oe-blue" />
              ) : (
                <Square size={16} />
              )}
            </button>
          </div>
        </td>
        <td className="px-4 py-3 font-mono text-xs text-content-secondary">
          {item.code}
        </td>
        <td className="px-4 py-3 text-content-primary max-w-[400px]">
          <div className="flex items-center gap-2">
            {hasComponents && (
              isExpanded
                ? <ChevronUp size={14} className="text-oe-blue shrink-0" />
                : <ChevronDown size={14} className="text-content-quaternary shrink-0" />
            )}
            <span className="truncate" title={item.description}>{item.description}</span>
            {item.source === 'custom' && (
              <Badge variant="neutral" size="sm" className="ml-1.5 text-2xs">
                {t('costs.custom_label', { defaultValue: 'Custom' })}
              </Badge>
            )}
            {hasComponents && (
              <span className="text-2xs text-content-quaternary shrink-0">
                {item.components.length} res.
              </span>
            )}
          </div>
        </td>
        <td className="px-4 py-3 text-center">
          <Badge variant="neutral" size="sm">{item.unit}</Badge>
        </td>
        <td className="px-4 py-3 text-right font-semibold text-content-primary tabular-nums">
          {fmt(item.rate)}
        </td>
        <td className="px-4 py-3 text-center">
          {cls.collection || cls.code || cls.din276 ? (
            <Badge variant="blue" size="sm">
              {cls.collection || cls.code || cls.din276}
            </Badge>
          ) : (
            <span className="text-content-tertiary">-</span>
          )}
        </td>
        <td className="px-2 py-3">
          <div className="flex items-center gap-0.5">
            <button
              onClick={(e) => { e.stopPropagation(); onSelect(); }}
              title={t('costs.add_to_boq', 'Select for BOQ')}
              className={`flex h-7 w-7 items-center justify-center rounded-md transition-all ${
                isSelected
                  ? 'bg-oe-blue text-white'
                  : 'text-content-tertiary opacity-0 group-hover:opacity-100 hover:bg-oe-blue-subtle hover:text-oe-blue'
              }`}
            >
              <Plus size={14} />
            </button>
            <button
              onClick={(e) => { e.stopPropagation(); onCopy(); }}
              title={t('costs.copy_rate', 'Copy rate')}
              className="flex h-7 w-7 items-center justify-center rounded-md text-content-tertiary opacity-0 transition-all group-hover:opacity-100 hover:bg-surface-tertiary hover:text-content-primary"
            >
              {copiedId === item.id ? (
                <Check size={13} className="text-semantic-success" />
              ) : (
                <Copy size={13} />
              )}
            </button>
            {item.source === 'custom' && (
              <button
                onClick={async (e) => {
                  e.stopPropagation();
                  const ok = await confirm({
                    title: t('costs.confirm_delete_title', { defaultValue: 'Delete cost item?' }),
                    message: t('costs.confirm_delete', { defaultValue: 'Delete this custom cost item?' }),
                  });
                  if (ok) onDelete?.(item.id);
                }}
                title={t('common.delete', { defaultValue: 'Delete' })}
                className="flex h-7 w-7 items-center justify-center rounded text-content-tertiary hover:text-semantic-error hover:bg-semantic-error-bg transition-colors"
              >
                <Trash2 size={13} />
              </button>
            )}
          </div>
        </td>
      </tr>

      {/* Expanded detail */}
      {isExpanded && hasComponents && (
        <tr>
          <td colSpan={7} className="p-0">
            <div className="bg-surface-secondary/30 border-t border-b border-border-light px-6 py-4 animate-fade-in">
              {/* Breadcrumb — wraps instead of overflowing */}
              {breadcrumb && (
                <div className="mb-3 flex flex-wrap items-center gap-x-1 gap-y-0.5">
                  {[cls.category, cls.collection, cls.department, cls.section, cls.subsection]
                    .filter(Boolean)
                    .map((part, i, arr) => (
                      <span key={`${String(part)}-${i}`} className="flex items-center gap-1">
                        <span className="text-2xs text-content-quaternary">{String(part)}</span>
                        {i < arr.length - 1 && <span className="text-2xs text-content-quaternary/50">&rsaquo;</span>}
                      </span>
                    ))}
                </div>
              )}

              {/* Cost breakdown summary cards */}
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-4">
                <div className="rounded-lg bg-surface-primary border border-border-light p-3">
                  <div className="flex items-center gap-1.5 mb-1">
                    <HardHat size={12} className="text-amber-500" />
                    <span className="text-2xs font-medium text-content-secondary uppercase tracking-wider">Labor</span>
                  </div>
                  <div className="text-sm font-bold tabular-nums text-content-primary">
                    {laborCost > 0 ? fmt(laborCost) : '—'}
                  </div>
                  {laborHours > 0 && (
                    <div className="text-2xs text-content-tertiary mt-0.5">{laborHours.toFixed(1)} hrs</div>
                  )}
                  {workers > 0 && (
                    <div className="text-2xs text-content-tertiary">{workers} workers/unit</div>
                  )}
                </div>
                <div className="rounded-lg bg-surface-primary border border-border-light p-3">
                  <div className="flex items-center gap-1.5 mb-1">
                    <Hammer size={12} className="text-blue-500" />
                    <span className="text-2xs font-medium text-content-secondary uppercase tracking-wider">Equipment</span>
                  </div>
                  <div className="text-sm font-bold tabular-nums text-content-primary">
                    {equipmentCost > 0 ? fmt(equipmentCost) : '—'}
                  </div>
                  {machines.length > 0 && (
                    <div className="text-2xs text-content-tertiary mt-0.5">{machines.length} items</div>
                  )}
                </div>
                <div className="rounded-lg bg-surface-primary border border-border-light p-3">
                  <div className="flex items-center gap-1.5 mb-1">
                    <Package size={12} className="text-green-600" />
                    <span className="text-2xs font-medium text-content-secondary uppercase tracking-wider">Materials</span>
                  </div>
                  <div className="text-sm font-bold tabular-nums text-content-primary">
                    {materialCost > 0 ? fmt(materialCost) : '—'}
                  </div>
                  {materials.length > 0 && (
                    <div className="text-2xs text-content-tertiary mt-0.5">{materials.length} items</div>
                  )}
                </div>
                <div className="rounded-lg bg-surface-primary border border-border-light p-3">
                  <div className="flex items-center gap-1.5 mb-1">
                    <span className="text-2xs font-medium text-content-secondary uppercase tracking-wider">Total</span>
                  </div>
                  <div className="text-sm font-bold tabular-nums text-content-primary">{fmt(item.rate)}</div>
                  <div className="text-2xs text-content-tertiary mt-0.5">per {item.unit}</div>
                </div>
              </div>

              {/* Cost breakdown bar */}
              {(laborCost > 0 || equipmentCost > 0 || materialCost > 0) && (
                <div className="mb-4">
                  <div className="h-2 w-full rounded-full overflow-hidden flex bg-surface-tertiary">
                    {laborCost > 0 && (
                      <div
                        className="h-full bg-amber-400"
                        style={{ width: `${(laborCost / item.rate) * 100}%` }}
                        title={`Labor: ${fmt(laborCost)}`}
                      />
                    )}
                    {equipmentCost > 0 && (
                      <div
                        className="h-full bg-blue-400"
                        style={{ width: `${(equipmentCost / item.rate) * 100}%` }}
                        title={`Equipment: ${fmt(equipmentCost)}`}
                      />
                    )}
                    {materialCost > 0 && (
                      <div
                        className="h-full bg-green-400"
                        style={{ width: `${(materialCost / item.rate) * 100}%` }}
                        title={`Materials: ${fmt(materialCost)}`}
                      />
                    )}
                  </div>
                  <div className="flex gap-4 mt-1.5 text-2xs text-content-tertiary">
                    {laborCost > 0 && (
                      <span className="flex items-center gap-1">
                        <span className="h-2 w-2 rounded-full bg-amber-400" />
                        Labor {((laborCost / item.rate) * 100).toFixed(0)}%
                      </span>
                    )}
                    {equipmentCost > 0 && (
                      <span className="flex items-center gap-1">
                        <span className="h-2 w-2 rounded-full bg-blue-400" />
                        Equipment {((equipmentCost / item.rate) * 100).toFixed(0)}%
                      </span>
                    )}
                    {materialCost > 0 && (
                      <span className="flex items-center gap-1">
                        <span className="h-2 w-2 rounded-full bg-green-400" />
                        Materials {((materialCost / item.rate) * 100).toFixed(0)}%
                      </span>
                    )}
                  </div>
                </div>
              )}

              {/* Resource table */}
              <div className="rounded-lg border border-border-light overflow-hidden">
                <table className="w-full text-xs table-fixed">
                  <thead>
                    <tr className="bg-surface-tertiary">
                      <th className="px-3 py-2 text-left font-medium text-content-secondary truncate">Resource</th>
                      <th className="px-3 py-2 text-left font-medium text-content-secondary w-16">Type</th>
                      <th className="px-3 py-2 text-left font-medium text-content-secondary w-16">Unit</th>
                      <th className="px-3 py-2 text-right font-medium text-content-secondary w-20">Qty</th>
                      <th className="px-3 py-2 text-right font-medium text-content-secondary w-24">Unit Rate</th>
                      <th className="px-3 py-2 text-right font-medium text-content-secondary w-24">Cost</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border-light">
                    {item.components.map((comp, i) => {
                      const TYPE_COLOR_MAP: Record<string, string> = {
                        labor: 'text-amber-700 bg-amber-50',
                        material: 'text-green-700 bg-green-50',
                        equipment: 'text-blue-600 bg-blue-50',
                        operator: 'text-violet-600 bg-violet-50',
                        electricity: 'text-cyan-600 bg-cyan-50',
                        other: 'text-gray-600 bg-gray-50',
                      };
                      const typeColor = TYPE_COLOR_MAP[comp.type] || 'text-gray-600 bg-gray-50';
                      const typeLabel = t(`costs.component_${comp.type}`, { defaultValue: comp.type.charAt(0).toUpperCase() + comp.type.slice(1) });
                      return (
                        <tr key={`${comp.name}-${comp.type}-${i}`} className="hover:bg-surface-secondary/30">
                          <td className="px-3 py-2 text-content-primary truncate" title={comp.name}>{comp.name}</td>
                          <td className="px-3 py-2">
                            <span className={`inline-block text-2xs font-medium px-1.5 py-0.5 rounded ${typeColor}`}>
                              {typeLabel}
                            </span>
                          </td>
                          <td className="px-3 py-2 text-content-tertiary">{comp.unit}</td>
                          <td className="px-3 py-2 text-right tabular-nums text-content-secondary">
                            {comp.quantity > 0 ? comp.quantity.toFixed(2) : '—'}
                          </td>
                          <td className="px-3 py-2 text-right tabular-nums text-content-secondary">
                            {comp.unit_rate > 0 ? fmt(comp.unit_rate) : '—'}
                          </td>
                          <td className="px-3 py-2 text-right tabular-nums font-medium text-content-primary">
                            {comp.cost > 0 ? fmt(comp.cost) : '—'}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>

              {/* All Properties */}
              <details className="mt-4">
                <summary className="text-2xs font-medium text-content-tertiary cursor-pointer hover:text-content-secondary transition-colors select-none">
                  All properties ({Object.keys(cls).length + Object.keys(meta).length + 5} fields)
                </summary>
                <div className="mt-2 grid grid-cols-2 gap-x-6 gap-y-1.5 text-2xs">
                  {/* Basic fields */}
                  <div className="flex justify-between"><span className="text-content-quaternary">Code</span><span className="text-content-secondary font-mono">{item.code}</span></div>
                  <div className="flex justify-between"><span className="text-content-quaternary">Unit</span><span className="text-content-secondary">{item.unit}</span></div>
                  <div className="flex justify-between"><span className="text-content-quaternary">Rate</span><span className="text-content-secondary font-semibold">{fmt(item.rate)}</span></div>
                  <div className="flex justify-between"><span className="text-content-quaternary">Region</span><span className="text-content-secondary">{item.region || '—'}</span></div>
                  <div className="flex justify-between"><span className="text-content-quaternary">Source</span><span className="text-content-secondary">{item.source}</span></div>

                  {/* Classification */}
                  {Object.entries(cls).map(([k, v]) => (
                    <div key={k} className="flex justify-between">
                      <span className="text-content-quaternary capitalize">{k}</span>
                      <span className="text-content-secondary truncate ml-2 max-w-[200px]" title={String(v)}>{String(v)}</span>
                    </div>
                  ))}

                  {/* Metadata (cost breakdown) */}
                  {Object.entries(meta).map(([k, v]) => (
                    <div key={k} className="flex justify-between">
                      <span className="text-content-quaternary">{k.replace(/_/g, ' ')}</span>
                      <span className="text-content-secondary tabular-nums">
                        {typeof v === 'number' ? fmt(v) : String(v)}
                      </span>
                    </div>
                  ))}

                  <div className="flex justify-between"><span className="text-content-quaternary">Components</span><span className="text-content-secondary">{item.components?.length || 0} resources</span></div>
                </div>
              </details>
            </div>
          </td>
        </tr>
      )}
      <ConfirmDialog {...confirmProps} />
    </>
  );
}
