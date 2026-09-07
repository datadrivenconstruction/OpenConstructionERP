// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { useState, useCallback, useMemo, useEffect, useRef } from 'react';
import { triggerDownload } from '@/shared/lib/api';
import { useTranslation } from 'react-i18next';
import { useQuery, useQueryClient, useMutation } from '@tanstack/react-query';
import { useNavigate, useLocation } from 'react-router-dom';
import {
  Search, Plus, Layers, ChevronDown, ChevronLeft, ChevronRight, MoreHorizontal,
  Copy, Trash2, Download, ExternalLink, FileSpreadsheet, X, Sparkles, Loader2,
  Upload, Tag, Eye, Share2, LayoutGrid, Table2, ArrowUpDown, BarChart3, AlertCircle,
  CheckSquare, Square as SquareIcon, Library,
} from 'lucide-react';
import { Button, Card, Badge, DismissibleInfo, IntroRichText, EmptyState, SkeletonGrid, Breadcrumb, ModuleGuideButton } from '@/shared/ui';
import { PageHeader } from '@/shared/ui/PageHeader';
import { apiGet, apiPost, apiDelete } from '@/shared/lib/api';
import { fmtList, getIntlLocale } from '@/shared/lib/formatters';
import { useNameCollator } from '@/shared/lib/collator';
import { unitLabel } from '@/shared/lib/unitLabels';
import { copyToClipboard } from '@/shared/lib/browser';
import { useToastStore } from '@/stores/useToastStore';
import {
  assembliesApi,
  type Assembly,
  type AssemblySearchResponse,
  type AIGeneratedAssembly,
} from './api';
import { CreateAssemblyModal } from './CreateAssemblyPage';
import { assembliesGuide } from './assembliesGuide';
import { getNumberLocale } from '@/stores/usePreferencesStore';

/* -- Sort + view types --------------------------------------------------- */

type SortKey = 'updated_at' | 'name' | 'code' | 'total_rate' | 'usage_count' | 'component_count';
type SortDir = 'asc' | 'desc';
type ViewMode = 'grid' | 'table';

/* -- Constants ------------------------------------------------------------ */

// Labels are resolved via t() at render time; keep value-only entries here
const CATEGORY_VALUES = [
  { value: '', key: 'assemblies.category_all' },
  { value: 'concrete', key: 'assemblies.category_concrete' },
  { value: 'masonry', key: 'assemblies.category_masonry' },
  { value: 'steel', key: 'assemblies.category_steel' },
  { value: 'mep', key: 'assemblies.category_mep' },
  { value: 'earthwork', key: 'assemblies.category_earthwork' },
  { value: 'insulation', key: 'assemblies.category_insulation' },
  { value: 'finishing', key: 'assemblies.category_finishing' },
  { value: 'roofing', key: 'assemblies.category_roofing' },
  { value: 'general', key: 'assemblies.category_general' },
] as const;

const CATEGORY_COLORS: Record<string, 'blue' | 'success' | 'warning' | 'error' | 'neutral'> = {
  concrete: 'blue',
  masonry: 'warning',
  steel: 'neutral',
  mep: 'success',
  earthwork: 'warning',
  insulation: 'blue',
  finishing: 'success',
  roofing: 'warning',
  general: 'neutral',
};

const UNIT_OPTIONS = ['m', 'm2', 'm3', 'kg', 't', 'pcs', 'lsum', 'h', 'set', 'lm'];

/* Templates removed — assemblies are managed via New/AI Generate/Clone/Save from BOQ */

/* -- Helpers -------------------------------------------------------------- */

function csvEscape(val: string): string {
  if (val.includes(',') || val.includes('"') || val.includes('\n')) {
    return `"${val.replace(/"/g, '""')}"`;
  }
  return val;
}

function downloadFile(content: string, filename: string, mimeType: string) {
  const blob = new Blob([content], { type: mimeType });
  triggerDownload(blob, filename);
}

/* -- Component ------------------------------------------------------------ */

export function AssembliesPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const location = useLocation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);

  // Create assembly modal
  const [createModalOpen, setCreateModalOpen] = useState(false);
  useEffect(() => {
    const state = location.state as { openCreateModal?: boolean } | null;
    if (state?.openCreateModal) {
      setCreateModalOpen(true);
      window.history.replaceState({}, '');
    }
  }, [location.state]);

  const PAGE_SIZE = 50;

  const [query, setQuery] = useState('');
  const [debouncedQuery, setDebouncedQuery] = useState('');
  const [category, setCategory] = useState('');
  const [offset, setOffset] = useState(0);
  const [showExportMenu, setShowExportMenu] = useState(false);
  const [showAiGenerate, setShowAiGenerate] = useState(false);
  const [showImportModal, setShowImportModal] = useState(false);
  const [tagFilter, setTagFilter] = useState('');

  // Sort, view, multi-select state
  const [sortKey, setSortKey] = useState<SortKey>('updated_at');
  const [sortDir, setSortDir] = useState<SortDir>('desc');
  const [viewMode, setViewMode] = useState<ViewMode>(() => {
    try { return (localStorage.getItem('oe_assemblies_view') as ViewMode) || 'grid'; }
    catch { return 'grid'; }
  });
  useEffect(() => {
    try { localStorage.setItem('oe_assemblies_view', viewMode); } catch { /* ignore */ }
  }, [viewMode]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [onlyUnused, setOnlyUnused] = useState(false);
  const [showBulkTag, setShowBulkTag] = useState(false);
  const [showBulkConfirmDelete, setShowBulkConfirmDelete] = useState(false);

  // Debounce search query (300ms)
  useEffect(() => {
    const timer = setTimeout(() => {
      setDebouncedQuery(query);
      setOffset(0);
    }, 300);
    return () => clearTimeout(timer);
  }, [query]);

  useEffect(() => {
    if (!showExportMenu) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setShowExportMenu(false);
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [showExportMenu]);

  const params: Record<string, string> = {};
  if (debouncedQuery) params.q = debouncedQuery;
  if (category) params.category = category;
  if (tagFilter) params.tag = tagFilter;
  params.limit = String(PAGE_SIZE);
  params.offset = String(offset);

  const { data, isLoading, isFetching } = useQuery({
    queryKey: ['assemblies', debouncedQuery, category, tagFilter, offset],
    queryFn: () => assembliesApi.list(params),
    placeholderData: (prev) => prev,
  });

  const total = data?.total ?? 0;

  // Stats banner — backend /stats/ returns total, by_category, most_used.
  // For avg-rate / total-components / unused-count we need the full set,
  // which is small enough (<500) to fetch in one shot.
  const { data: statsData } = useQuery({
    queryKey: ['assemblies-stats'],
    queryFn: () => assembliesApi.getStats(),
    staleTime: 60_000,
  });
  const { data: allForBanner } = useQuery({
    queryKey: ['assemblies-all-for-banner'],
    queryFn: () => assembliesApi.list({ limit: '500', offset: '0' }),
    staleTime: 60_000,
  });

  const banner = useMemo(() => {
    const all = allForBanner?.items ?? [];
    const totalCount = statsData?.total ?? all.length ?? 0;
    const totalComponents = all.reduce((sum, a) => sum + (a.component_count ?? 0), 0);
    // Avg rate must NEVER blend currencies — averaging an EUR + USD + GBP
    // mix yields a meaningless number. Group rated assemblies by their
    // own ISO currency, then surface the dominant currency's average
    // (with its code). When more than one currency is present we flag it
    // so the single number isn't mistaken for a portfolio-wide rate.
    const ratedItems = all.filter((a) => a.total_rate > 0);
    const byCurrency = new Map<string, { sum: number; count: number }>();
    for (const a of ratedItems) {
      // No silent EUR in the grouping key either: an assembly with no stored
      // currency is its own group, not a Euro one. Folding it into EUR made
      // the tile label a set of unknown-currency rates "EUR", which is the
      // same guess as showing the symbol on a bare number.
      const code = (a.currency || '').toUpperCase();
      const acc = byCurrency.get(code) ?? { sum: 0, count: 0 };
      acc.sum += Number(a.total_rate) || 0;
      acc.count += 1;
      byCurrency.set(code, acc);
    }
    let avgRate = 0;
    let avgRateCurrency = '';
    let avgRateMixed = false;
    const dominant = [...byCurrency.entries()].sort((x, y) => y[1].count - x[1].count)[0];
    if (dominant) {
      avgRateCurrency = dominant[0];
      avgRate = dominant[1].count ? dominant[1].sum / dominant[1].count : 0;
      avgRateMixed = byCurrency.size > 1;
    }
    const unusedCount = all.filter((a) => (a.usage_count ?? 0) === 0).length;
    const byCategory = statsData?.by_category ?? {};
    const topCategories = Object.entries(byCategory)
      .sort((a, b) => b[1] - a[1])
      .slice(0, 3);
    // Tag chips: all distinct tags across the full set with counts.
    const tagCounts = new Map<string, number>();
    for (const a of all) {
      for (const t of a.tags ?? []) tagCounts.set(t, (tagCounts.get(t) ?? 0) + 1);
    }
    const topTags = [...tagCounts.entries()]
      .sort((a, b) => b[1] - a[1])
      .slice(0, 8);
    // Most-used recipes — already computed server-side in /stats/. Surface
    // it as a hover hint on the total tile so the fetched data isn't dead.
    const mostUsed = (statsData?.most_used ?? []).filter((m) => (m.usage_count ?? 0) > 0);
    return {
      totalCount,
      totalComponents,
      avgRate,
      avgRateCurrency,
      avgRateMixed,
      unusedCount,
      topCategories,
      topTags,
      mostUsed,
    };
  }, [statsData, allForBanner]);

  // Assembly names are user data; the name column orders them in this
  // reader's language. `code` stays on a plain compare because it is an
  // identifier, not something a reader alphabetises.
  const compareNames = useNameCollator();

  // Sort + unused filter (FE-side over the current page slice).
  const items = useMemo(() => {
    let raw = data?.items ?? [];
    if (onlyUnused) raw = raw.filter((a) => (a.usage_count ?? 0) === 0);
    const dir = sortDir === 'asc' ? 1 : -1;
    const cmp = (a: Assembly, b: Assembly) => {
      switch (sortKey) {
        case 'name': return compareNames(a.name, b.name) * dir;
        case 'code': return a.code.localeCompare(b.code) * dir;
        case 'total_rate': return ((a.total_rate ?? 0) - (b.total_rate ?? 0)) * dir;
        case 'usage_count': return ((a.usage_count ?? 0) - (b.usage_count ?? 0)) * dir;
        case 'component_count': return ((a.component_count ?? 0) - (b.component_count ?? 0)) * dir;
        case 'updated_at':
        default:
          return (new Date(a.updated_at).getTime() - new Date(b.updated_at).getTime()) * dir;
      }
    };
    return [...raw].sort(cmp);
  }, [data, sortKey, sortDir, onlyUnused, compareNames]);

  // Multi-select helpers — selection survives filtering/paging (set of ids).
  const allOnPageSelected = items.length > 0 && items.every((a) => selected.has(a.id));
  const someOnPageSelected = items.some((a) => selected.has(a.id));
  const toggleSelectAll = useCallback(() => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (allOnPageSelected) {
        for (const a of items) next.delete(a.id);
      } else {
        for (const a of items) next.add(a.id);
      }
      return next;
    });
  }, [items, allOnPageSelected]);
  const toggleSelect = useCallback((id: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  }, []);
  const clearSelection = useCallback(() => setSelected(new Set()), []);

  // Bulk actions
  const handleBulkDelete = useCallback(async () => {
    const ids = Array.from(selected);
    const results = await Promise.allSettled(
      ids.map((id) => apiDelete(`/v1/assemblies/${id}`)),
    );
    const ok = results.filter((r) => r.status === 'fulfilled').length;
    const fail = results.length - ok;
    setShowBulkConfirmDelete(false);
    clearSelection();
    queryClient.invalidateQueries({ queryKey: ['assemblies'] });
    queryClient.invalidateQueries({ queryKey: ['assemblies-stats'] });
    queryClient.invalidateQueries({ queryKey: ['assemblies-all-for-banner'] });
    addToast({
      type: fail === 0 ? 'success' : 'error',
      // Two keys rather than one with a conditional tail. A glued-on ", n failed"
      // cannot be moved, and languages that inflect the count or put the failure
      // first would have to break the opening half to place it.
      title: fail
        ? t('assemblies.bulk_deleted_partial', {
            ok,
            failed: fail,
            defaultValue: '{{ok}} deleted, {{failed}} failed',
          })
        : t('assemblies.bulk_deleted', { count: ok, defaultValue: '{{count}} deleted' }),
    });
  }, [selected, addToast, queryClient, clearSelection, t]);

  // Single-assembly delete, shared by the card menu and the table row action
  // so both views expose the same affordance (the table previously had no
  // per-row delete at all - the only path was bulk-select).
  const deleteAssembly = useCallback(async (id: string) => {
    try {
      await apiDelete(`/v1/assemblies/${id}`);
      queryClient.invalidateQueries({ queryKey: ['assemblies'] });
      queryClient.invalidateQueries({ queryKey: ['assemblies-stats'] });
      queryClient.invalidateQueries({ queryKey: ['assemblies-all-for-banner'] });
      addToast({ type: 'success', title: t('toasts.assembly_deleted', { defaultValue: 'Assembly deleted' }) });
    } catch {
      addToast({ type: 'error', title: t('toasts.delete_failed', { defaultValue: 'Delete failed' }) });
    }
  }, [addToast, queryClient, t]);

  const handleBulkExport = useCallback(async () => {
    const ids = Array.from(selected);
    if (ids.length === 0) return;
    try {
      const exports = await Promise.all(ids.map((id) => assembliesApi.exportAssembly(id)));
      const payload = { exported_at: new Date().toISOString(), count: exports.length, assemblies: exports };
      downloadFile(
        JSON.stringify(payload, null, 2),
        `assemblies_bulk_${new Date().toISOString().slice(0, 10)}.json`,
        'application/json',
      );
      addToast({ type: 'success', title: t('assemblies.bulk_exported', { count: exports.length, defaultValue: '{{count}} exported' }) });
    } catch {
      addToast({ type: 'error', title: t('common.export_failed', { defaultValue: 'Export failed' }) });
    }
  }, [selected, addToast, t]);

  const handleBulkTag = useCallback(async (tagsToAdd: string[]) => {
    const ids = Array.from(selected);
    const results = await Promise.allSettled(
      ids.map((id) => {
        const asm = (data?.items ?? []).find((a) => a.id === id)
          ?? (allForBanner?.items ?? []).find((a) => a.id === id);
        const existing = new Set(asm?.tags ?? []);
        for (const t2 of tagsToAdd) existing.add(t2);
        return assembliesApi.updateTags(id, [...existing]);
      }),
    );
    const ok = results.filter((r) => r.status === 'fulfilled').length;
    const fail = results.length - ok;
    setShowBulkTag(false);
    queryClient.invalidateQueries({ queryKey: ['assemblies'] });
    queryClient.invalidateQueries({ queryKey: ['assemblies-all-for-banner'] });
    addToast({
      type: fail === 0 ? 'success' : 'error',
      title: fail
        ? t('assemblies.bulk_tagged_partial', {
            ok,
            failed: fail,
            defaultValue: '{{ok}} tagged, {{failed}} failed',
          })
        : t('assemblies.bulk_tagged', { count: ok, defaultValue: '{{count}} tagged' }),
    });
  }, [selected, addToast, queryClient, data, allForBanner, t]);

  const handleSearch = useCallback((value: string) => {
    setQuery(value);
  }, []);

  const handleCategoryChange = useCallback((value: string) => {
    setCategory(value);
    setOffset(0);
  }, []);

  const cycleSortDir = useCallback((nextKey: SortKey) => {
    setSortKey((prevKey) => {
      if (prevKey === nextKey) {
        setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'));
      } else {
        setSortDir(nextKey === 'name' || nextKey === 'code' ? 'asc' : 'desc');
      }
      return nextKey;
    });
  }, []);

  // Templates removed — use New / AI Generate / Clone instead

  const fmt = (n: number) =>
    new Intl.NumberFormat(getNumberLocale(), {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }).format(n);

  return (
    <div className="space-y-5 animate-fade-in">
      <Breadcrumb items={[{ label: t('nav.assemblies', 'Assemblies') }]} />
      {/* Canonical top block — module name + icon are shown in the global top
          app bar. The page renders only its (contextual) subtitle and the
          action stack. */}
      <PageHeader
        srTitle={t('assemblies.title', 'Assemblies')}
        subtitle={
          total > 0
            ? `${total} ${t('assemblies.assemblies_found', 'assemblies')}`
            : t('assemblies.description', 'Reusable cost recipes')
        }
        actions={
          <>
          <div className="relative">
            <Button
              variant="secondary"
              size="sm"
              icon={<Download size={14} />}
              onClick={() => setShowExportMenu((p) => !p)}
            >
              {t('common.export')}
            </Button>
            {showExportMenu && (
              <div className="absolute right-0 top-full mt-1 z-50 w-44 rounded-lg border border-border-light bg-surface-elevated shadow-md animate-fade-in">
                <button
                  onClick={async () => {
                    setShowExportMenu(false);
                    try {
                      const resp = await apiGet<AssemblySearchResponse>('/v1/assemblies/?limit=500');
                      const allItems = resp.items;
                      // One row per assembly. The list endpoint returns no
                      // component rows, so we export only the per-assembly
                      // fields rather than printing empty Component/Factor
                      // columns. Use the JSON export (or per-assembly
                      // export) for the full component breakdown.
                      const rows: string[] = ['Assembly,Code,Category,Unit,Total Rate,Currency'];
                      for (const a of allItems) {
                        rows.push([
                          csvEscape(a.name),
                          csvEscape(a.code),
                          a.category,
                          a.unit || '',
                          String(a.total_rate ?? ''),
                          a.currency || '',
                        ].join(','));
                      }
                      downloadFile(rows.join('\n'), `assemblies_${new Date().toISOString().slice(0, 10)}.csv`, 'text/csv');
                      addToast({ type: 'success', title: t('assemblies.exported_csv', { defaultValue: 'CSV exported' }) });
                    } catch {
                      addToast({ type: 'error', title: t('common.export_failed', { defaultValue: 'Export failed' }) });
                    }
                  }}
                  className="flex w-full items-center gap-2.5 px-3 py-2.5 text-sm text-content-primary hover:bg-surface-secondary transition-colors rounded-t-lg"
                >
                  <FileSpreadsheet size={15} className="text-content-tertiary" />
                  CSV (.csv)
                </button>
                <button
                  onClick={async () => {
                    setShowExportMenu(false);
                    try {
                      const resp = await apiGet<AssemblySearchResponse>('/v1/assemblies/?limit=500');
                      downloadFile(JSON.stringify(resp.items, null, 2), `assemblies_${new Date().toISOString().slice(0, 10)}.json`, 'application/json');
                      addToast({ type: 'success', title: t('assemblies.exported_json', { defaultValue: 'JSON exported' }) });
                    } catch {
                      addToast({ type: 'error', title: t('common.export_failed', { defaultValue: 'Export failed' }) });
                    }
                  }}
                  className="flex w-full items-center gap-2.5 px-3 py-2.5 text-sm text-content-primary hover:bg-surface-secondary transition-colors rounded-b-lg"
                >
                  <Download size={15} className="text-content-tertiary" />
                  JSON (.json)
                </button>
              </div>
            )}
          </div>
          <Button
            variant="secondary"
            size="sm"
            icon={<Library size={14} />}
            onClick={() => navigate('/assemblies/library')}
            title={t('assemblies.browse_library_hint', {
              defaultValue: 'Browse the built-in canonical recipe templates and apply one as a starting point',
            })}
          >
            {t('assemblies.browse_library', { defaultValue: 'Browse Library' })}
          </Button>
          <Button
            variant="secondary"
            size="sm"
            icon={<Upload size={14} />}
            onClick={() => setShowImportModal(true)}
          >
            {t('assemblies.import', { defaultValue: 'Import' })}
          </Button>
          <Button
            data-guide="assemblies-ai-generate"
            variant="secondary"
            size="sm"
            icon={<Sparkles size={14} />}
            onClick={() => setShowAiGenerate(true)}
          >
            {t('assemblies.ai_generate', { defaultValue: 'AI Generate' })}
          </Button>
          <Button
            data-guide="assemblies-new"
            variant="primary"
            size="sm"
            icon={<Plus size={14} />}
            onClick={() => setCreateModalOpen(true)}
          >
            {t('assemblies.new_assembly', 'New Assembly')}
          </Button>
          {/* "How it works" guide — explains the assembly recipe concept,
              the component/factor model and the data-entry flow. Its closing
              CTA opens the New Assembly modal. This module has no separate
              guided Tour, so the Guide button stands on its own here. */}
          <ModuleGuideButton
            content={assembliesGuide}
            onCta={() => setCreateModalOpen(true)}
          />
          </>
        }
      />

      {/* Intro / help banner — collapsible, remembers its state per page.
          Explains the assembly recipe metaphor and how it ties into the
          BOQ on first visit, then folds to a one-line header for returners. */}
      <DismissibleInfo
        storageKey="assemblies"
        title={t('assemblies.intro_title', { defaultValue: 'Price recurring work once, reuse it everywhere' })}
        more={t('assemblies.intro_more', { defaultValue: '' }) ? <IntroRichText text={t('assemblies.intro_more')} /> : undefined}
        links={[
          {
            label: t('assemblies.browse_library', { defaultValue: 'Browse Library' }),
            onClick: () => navigate('/assemblies/library'),
          },
          {
            label: t('assemblies.new_assembly', { defaultValue: 'New Assembly' }),
            onClick: () => navigate('/assemblies/new'),
          },
          {
            label: t('nav.boq', { defaultValue: 'Bill of Quantities' }),
            onClick: () => navigate('/boq'),
          },
        ]}
      >
        {t('assemblies.intro_body', {
          defaultValue:
            'Assemblies are reusable cost recipes that bundle materials, labour and equipment into one composite rate, for example a reinforced concrete wall combining concrete, rebar, formwork and labour. Apply an assembly to a BOQ position to auto-populate its component costs and keep rates consistent across the project.',
        })}
      </DismissibleInfo>

      {/* Stats banner — surfaces aggregated insight from /stats/ + the
          full-set fetch so the list feels like an estimating tool, not a
          plain table. Five tiles: total, total components, avg rate, top
          categories (clickable as filter), unused (clickable as filter).
          Hidden when there are zero assemblies; renders skeleton rows
          while banner data is loading. */}
      {(banner.totalCount > 0 || allForBanner) && (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-5">
          <StatTile
            icon={<Layers size={14} />}
            label={t('assemblies.stat_total', { defaultValue: 'Assemblies' })}
            value={String(banner.totalCount)}
            title={
              banner.mostUsed.length > 0
                ? `${t('assemblies.stat_most_used', { defaultValue: 'Most used' })}: ${fmtList(banner.mostUsed
                    .map((m) => `${m.name} (${m.usage_count})`))}`
                : undefined
            }
          />
          <StatTile
            icon={<BarChart3 size={14} />}
            label={t('assemblies.stat_components', { defaultValue: 'Total components' })}
            value={String(banner.totalComponents)}
          />
          <StatTile
            icon={<BarChart3 size={14} />}
            label={
              banner.avgRateMixed && banner.avgRateCurrency
                ? t('assemblies.stat_avg_rate_dominant', {
                    defaultValue: 'Avg. rate ({{currency}})',
                    currency: banner.avgRateCurrency,
                  })
                : t('assemblies.stat_avg_rate', { defaultValue: 'Avg. rate' })
            }
            value={
              banner.avgRate > 0 && banner.avgRateCurrency
                ? `${fmt(banner.avgRate)} ${banner.avgRateCurrency}`
                : '—'
            }
            title={
              banner.avgRate > 0 && !banner.avgRateCurrency
                ? t('assemblies.stat_avg_rate_no_currency_hint', {
                    defaultValue:
                      'Most assemblies here have no currency set, so their average cannot be stated in any money.',
                  })
                : banner.avgRateMixed
                  ? t('assemblies.stat_avg_rate_mixed_hint', {
                      defaultValue:
                        'Assemblies span multiple currencies; showing the average for the most common one ({{currency}}).',
                      currency: banner.avgRateCurrency,
                    })
                  : undefined
            }
          />
          <StatTile
            icon={<Tag size={14} />}
            label={t('assemblies.stat_top_categories', { defaultValue: 'Top categories' })}
            value={
              banner.topCategories.length > 0
                ? fmtList(banner.topCategories.map(([c, n]) => `${c} (${n})`))
                : '—'
            }
            valueClassName="text-xs leading-snug"
          />
          <StatTile
            icon={<AlertCircle size={14} />}
            label={t('assemblies.stat_unused', { defaultValue: 'Unused (cleanup)' })}
            value={String(banner.unusedCount)}
            interactive
            active={onlyUnused}
            onClick={() => { setOnlyUnused((v) => !v); setOffset(0); }}
            highlightTone={banner.unusedCount > 0 ? 'amber' : 'neutral'}
          />
        </div>
      )}

      {/* Category quick-chips — clickable badges with counts pulled from
          /stats/. Acts as a faster category picker than the dropdown and
          telegraphs distribution at a glance. */}
      {Object.keys(statsData?.by_category ?? {}).length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5">
          <button
            type="button"
            onClick={() => handleCategoryChange('')}
            className={`h-7 px-2.5 rounded-full text-xs font-medium border transition-colors ${
              category === ''
                ? 'border-oe-blue bg-oe-blue text-white'
                : 'border-border-light text-content-secondary hover:bg-surface-secondary'
            }`}
          >
            {t('assemblies.category_all', { defaultValue: 'All' })} ({banner.totalCount})
          </button>
          {Object.entries(statsData?.by_category ?? {})
            .sort((a, b) => b[1] - a[1])
            .map(([cat, count]) => {
              const active = category === cat;
              return (
                <button
                  key={cat}
                  type="button"
                  onClick={() => handleCategoryChange(active ? '' : cat)}
                  className={`h-7 px-2.5 rounded-full text-xs font-medium border transition-colors inline-flex items-center gap-1 ${
                    active
                      ? 'border-oe-blue bg-oe-blue text-white'
                      : 'border-border-light text-content-secondary hover:bg-surface-secondary'
                  }`}
                  title={t('assemblies.filter_by_category', { defaultValue: 'Filter by category' })}
                >
                  <span className="capitalize">{cat}</span>
                  <span className={active ? 'text-white/80' : 'text-content-tertiary'}>({count})</span>
                </button>
              );
            })}
          {banner.topTags.length > 0 && (
            <>
              <span className="mx-1 h-4 w-px bg-border-light" aria-hidden />
              {banner.topTags.map(([tag, count]) => {
                const active = tagFilter === tag;
                return (
                  <button
                    key={tag}
                    type="button"
                    onClick={() => { setTagFilter(active ? '' : tag); setOffset(0); }}
                    className={`h-7 px-2.5 rounded-full text-xs font-medium border transition-colors inline-flex items-center gap-1 ${
                      active
                        ? 'border-violet-500 bg-violet-500 text-white'
                        : 'border-violet-200/60 text-violet-600 bg-violet-50/60 hover:bg-violet-100 dark:bg-violet-900/20 dark:text-violet-300 dark:border-violet-700/40'
                    }`}
                    title={t('assemblies.filter_by_tag', { defaultValue: 'Filter by tag' })}
                  >
                    <Tag size={11} />
                    {tag}
                    <span className={active ? 'text-white/80' : 'text-violet-400'}>({count})</span>
                  </button>
                );
              })}
            </>
          )}
        </div>
      )}

      {/* Search & Filters — flat toolbar (was a Card with internal p-4
          giving a card-in-card look). 32px less vertical chrome. */}
      <div className="mb-3 flex flex-col gap-2 sm:flex-row sm:items-end">
          {/* Search input */}
          <div className="relative flex-1">
            <label htmlFor="assemblies-search" className="sr-only">
              {t('common.search', { defaultValue: 'Search' })}
            </label>
            <div className="pointer-events-none absolute inset-y-0 start-0 flex items-center ps-3 text-content-tertiary">
              <Search size={16} />
            </div>
            <input
              id="assemblies-search"
              type="text"
              value={query}
              onChange={(e) => handleSearch(e.target.value)}
              placeholder={t(
                'assemblies.search_placeholder',
                'Search by name or code...',
              )}
              aria-label={t('assemblies.search_placeholder', { defaultValue: 'Search by name or code...' })}
              className="h-10 w-full rounded-lg border border-border bg-surface-primary ps-10 pe-9 text-sm text-content-primary placeholder:text-content-tertiary transition-all duration-fast ease-oe focus:outline-none focus:ring-2 focus:ring-oe-blue focus:border-transparent hover:border-content-tertiary"
            />
            {query && (
              <button
                onClick={() => { setQuery(''); setDebouncedQuery(''); setOffset(0); }}
                className="absolute inset-y-0 end-0 flex items-center pe-3 text-content-tertiary hover:text-content-primary transition-colors"
                aria-label={t('common.clear', { defaultValue: 'Clear' })}
              >
                <X size={14} />
              </button>
            )}
          </div>

          {/* Category filter */}
          <div className="relative">
            <select
              value={category}
              onChange={(e) => handleCategoryChange(e.target.value)}
              aria-label={t('a11y.assemblies.category_filter', {
                defaultValue: 'Filter assemblies by category',
              })}
              className="h-10 w-full appearance-none rounded-lg border border-border bg-surface-primary ps-3 pe-9 text-sm text-content-primary transition-all duration-fast ease-oe focus:outline-none focus:ring-2 focus:ring-oe-blue focus:border-transparent hover:border-content-tertiary sm:w-44"
            >
              {CATEGORY_VALUES.map((c) => (
                <option key={c.value} value={c.value}>
                  {t(c.key, { defaultValue: c.value || 'All categories' })}
                </option>
              ))}
            </select>
            <div className="pointer-events-none absolute inset-y-0 end-0 flex items-center pe-2.5 text-content-tertiary">
              <ChevronDown size={14} />
            </div>
          </div>

          {/* Tag filter */}
          <div className="relative">
            <div className="pointer-events-none absolute inset-y-0 start-0 flex items-center ps-3 text-content-tertiary">
              <Tag size={14} />
            </div>
            <input
              type="text"
              value={tagFilter}
              onChange={(e) => { setTagFilter(e.target.value); setOffset(0); }}
              placeholder={t('assemblies.filter_by_tag', { defaultValue: 'Filter by tag...' })}
              className="h-10 w-full rounded-lg border border-border bg-surface-primary ps-9 pe-3 text-sm text-content-primary placeholder:text-content-tertiary transition-all duration-fast ease-oe focus:outline-none focus:ring-2 focus:ring-oe-blue focus:border-transparent hover:border-content-tertiary sm:w-40"
            />
          </div>

          {/* Sort control */}
          <div className="relative">
            <label htmlFor="assemblies-sort" className="sr-only">
              {t('assemblies.sort_label', { defaultValue: 'Sort' })}
            </label>
            <div className="pointer-events-none absolute inset-y-0 start-0 flex items-center ps-2.5 text-content-tertiary">
              <ArrowUpDown size={13} />
            </div>
            <select
              id="assemblies-sort"
              value={`${sortKey}:${sortDir}`}
              onChange={(e) => {
                const [k, d] = e.target.value.split(':') as [SortKey, SortDir];
                setSortKey(k);
                setSortDir(d);
              }}
              aria-label={t('assemblies.sort_label', { defaultValue: 'Sort' })}
              className="h-10 appearance-none rounded-lg border border-border bg-surface-primary ps-8 pe-7 text-sm text-content-primary transition-all duration-fast ease-oe focus:outline-none focus:ring-2 focus:ring-oe-blue focus:border-transparent hover:border-content-tertiary"
            >
              <option value="updated_at:desc">{t('assemblies.sort_recent', { defaultValue: 'Recently updated' })}</option>
              <option value="updated_at:asc">{t('assemblies.sort_oldest', { defaultValue: 'Oldest updated' })}</option>
              <option value="name:asc">{t('assemblies.sort_name_az', { defaultValue: 'Name A→Z' })}</option>
              <option value="name:desc">{t('assemblies.sort_name_za', { defaultValue: 'Name Z→A' })}</option>
              <option value="code:asc">{t('assemblies.sort_code_az', { defaultValue: 'Code A→Z' })}</option>
              <option value="code:desc">{t('assemblies.sort_code_za', { defaultValue: 'Code Z→A' })}</option>
              <option value="total_rate:desc">{t('assemblies.sort_rate_hi', { defaultValue: 'Rate high→low' })}</option>
              <option value="total_rate:asc">{t('assemblies.sort_rate_lo', { defaultValue: 'Rate low→high' })}</option>
              <option value="usage_count:desc">{t('assemblies.sort_usage_hi', { defaultValue: 'Most used' })}</option>
              <option value="component_count:desc">{t('assemblies.sort_comp_hi', { defaultValue: 'Most components' })}</option>
            </select>
            <div className="pointer-events-none absolute inset-y-0 end-0 flex items-center pe-2 text-content-tertiary">
              <ChevronDown size={13} />
            </div>
          </div>

          {/* Grid / table view toggle — segmented control. Persisted to
              localStorage so power users get their preference back. */}
          <div className="inline-flex h-10 rounded-lg border border-border bg-surface-primary p-0.5 shrink-0">
            <button
              type="button"
              onClick={() => setViewMode('grid')}
              aria-pressed={viewMode === 'grid'}
              title={t('assemblies.view_grid', { defaultValue: 'Card grid' })}
              className={`flex items-center justify-center px-2.5 rounded-md transition-colors ${
                viewMode === 'grid'
                  ? 'bg-oe-blue text-white shadow-sm'
                  : 'text-content-tertiary hover:text-content-primary'
              }`}
            >
              <LayoutGrid size={14} />
            </button>
            <button
              type="button"
              onClick={() => setViewMode('table')}
              aria-pressed={viewMode === 'table'}
              title={t('assemblies.view_table', { defaultValue: 'Compact table' })}
              className={`flex items-center justify-center px-2.5 rounded-md transition-colors ${
                viewMode === 'table'
                  ? 'bg-oe-blue text-white shadow-sm'
                  : 'text-content-tertiary hover:text-content-primary'
              }`}
            >
              <Table2 size={14} />
            </button>
          </div>

      </div>

      {/* Bulk-action bar — slides in when 1+ items selected. Sticky-ish
          banner that reuses the same multi-select Set across both grid
          and table views. */}
      {selected.size > 0 && (
        <div className="mb-3 flex flex-wrap items-center gap-2 rounded-lg border border-oe-blue/30 bg-oe-blue-subtle px-3 py-2">
          <span className="text-sm font-medium text-oe-blue">
            {t('assemblies.selected_count', { count: selected.size, defaultValue: '{{count}} selected' })}
          </span>
          <button
            type="button"
            onClick={clearSelection}
            className="text-xs text-content-tertiary hover:text-content-primary underline-offset-2 hover:underline"
          >
            {t('common.clear', { defaultValue: 'Clear' })}
          </button>
          <span className="ml-auto flex flex-wrap items-center gap-1.5">
            <Button variant="secondary" size="sm" icon={<Download size={13} />} onClick={handleBulkExport}>
              {t('assemblies.bulk_export', { defaultValue: 'Export selected' })}
            </Button>
            <Button variant="secondary" size="sm" icon={<Tag size={13} />} onClick={() => setShowBulkTag(true)}>
              {t('assemblies.bulk_tag', { defaultValue: 'Add tag' })}
            </Button>
            <Button
              variant="secondary"
              size="sm"
              icon={<Trash2 size={13} />}
              onClick={() => setShowBulkConfirmDelete(true)}
              className="text-red-600 border-red-200 hover:bg-red-50 dark:text-red-400 dark:border-red-800/40 dark:hover:bg-red-900/20"
            >
              {t('assemblies.bulk_delete', { defaultValue: 'Delete' })}
            </Button>
          </span>
        </div>
      )}

      {/* Results */}
      {isLoading ? (
        <SkeletonGrid items={6} />
      ) : items.length === 0 ? (
        <EmptyState
          icon={<Layers size={28} strokeWidth={1.5} />}
          title={
            query || category
              ? t('assemblies.no_results', { defaultValue: 'No assemblies found' })
              : t('assemblies.no_assemblies', { defaultValue: 'No assemblies yet' })
          }
          description={
            query || category
              ? t('assemblies.no_results_hint', { defaultValue: 'Try adjusting your search or filters' })
              : t('assemblies.empty_hint', {
                  defaultValue: 'Create your first assembly to build reusable cost recipes, or browse the built-in template library for a starting point',
                })
          }
          action={
            !query && !category
              ? {
                  label: t('assemblies.new_assembly', { defaultValue: 'Create Assembly' }),
                  onClick: () => setCreateModalOpen(true),
                }
              : undefined
          }
        />
      ) : (
        <>
          {viewMode === 'grid' ? (
            <div data-testid="assemblies-grid" className="grid gap-2.5 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 2xl:grid-cols-5">
              {items.map((assembly) => (
                <AssemblyCard
                  key={assembly.id}
                  assembly={assembly}
                  fmt={fmt}
                  selected={selected.has(assembly.id)}
                  onToggleSelect={() => toggleSelect(assembly.id)}
                  onClick={() => navigate(`/assemblies/${assembly.id}`)}
                  onDuplicate={async () => {
                    try {
                      const cloned = await apiPost<Assembly>(`/v1/assemblies/${assembly.id}/clone/`, {});
                      queryClient.invalidateQueries({ queryKey: ['assemblies'] });
                      addToast({ type: 'success', title: t('toasts.assembly_duplicated', { defaultValue: 'Assembly duplicated' }), message: cloned.name });
                    } catch {
                      addToast({ type: 'error', title: t('toasts.duplicate_failed', { defaultValue: 'Duplicate failed' }) });
                    }
                  }}
                  onDelete={() => deleteAssembly(assembly.id)}
                  onExport={async () => {
                    try {
                      const exported = await assembliesApi.exportAssembly(assembly.id);
                      const json = JSON.stringify(exported, null, 2);
                      const blob = new Blob([json], { type: 'application/json' });
                      triggerDownload(blob, `${assembly.code}.json`);
                      addToast({ type: 'success', title: t('assemblies.exported_json', { defaultValue: 'JSON exported' }) });
                    } catch {
                      addToast({ type: 'error', title: t('common.export_failed', { defaultValue: 'Export failed' }) });
                    }
                  }}
                />
              ))}
            </div>
          ) : (
            <AssemblyTable
              items={items}
              fmt={fmt}
              selected={selected}
              onToggleSelect={toggleSelect}
              onToggleAll={toggleSelectAll}
              allSelected={allOnPageSelected}
              someSelected={someOnPageSelected && !allOnPageSelected}
              sortKey={sortKey}
              sortDir={sortDir}
              onSort={cycleSortDir}
              onOpen={(id) => navigate(`/assemblies/${id}`)}
              onDelete={deleteAssembly}
            />
          )}

          {/* Pagination */}
          {(() => {
            const currentPage = Math.floor(offset / PAGE_SIZE) + 1;
            const totalPages = Math.ceil(total / PAGE_SIZE);
            const goToPage = (p: number) => setOffset((p - 1) * PAGE_SIZE);
            const start = Math.max(1, currentPage - 2);
            const end = Math.min(totalPages, start + 4);
            const pages = Array.from({ length: end - start + 1 }, (_, i) => start + i);

            return (
              <div className="mt-6 flex flex-col items-center gap-3">
                <p className="text-xs text-content-tertiary">
                  {t('assemblies.showing_range', {
                    defaultValue: '{{from}}-{{to}} of {{total}}',
                    from: offset + 1,
                    to: Math.min(offset + PAGE_SIZE, total),
                    total: total.toLocaleString(getNumberLocale()),
                  })}
                </p>
                {totalPages > 1 && (
                  <div className="flex items-center gap-1">
                    <button aria-label={t('common.previous_page', { defaultValue: 'Previous page' })}
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
                    <button aria-label={t('common.next_page', { defaultValue: 'Next page' })}
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

      {/* AI Generate Modal */}
      {showAiGenerate && (
        <AIGenerateModal
          onClose={() => setShowAiGenerate(false)}
          onCreated={(id) => {
            setShowAiGenerate(false);
            queryClient.invalidateQueries({ queryKey: ['assemblies'] });
            navigate(`/assemblies/${id}`);
          }}
        />
      )}

      <CreateAssemblyModal
        open={createModalOpen}
        onClose={() => setCreateModalOpen(false)}
      />

      {/* Import Modal */}
      {showImportModal && (
        <ImportAssemblyModal
          onClose={() => setShowImportModal(false)}
          onImported={() => {
            setShowImportModal(false);
            queryClient.invalidateQueries({ queryKey: ['assemblies'] });
          }}
        />
      )}

      {/* Bulk tag modal */}
      {showBulkTag && (
        <BulkTagModal
          count={selected.size}
          onClose={() => setShowBulkTag(false)}
          onApply={handleBulkTag}
        />
      )}

      {/* Bulk delete confirm */}
      {showBulkConfirmDelete && (
        <BulkDeleteConfirm
          count={selected.size}
          onCancel={() => setShowBulkConfirmDelete(false)}
          onConfirm={handleBulkDelete}
        />
      )}
    </div>
  );
}

/* -- StatTile ------------------------------------------------------------- */

function StatTile({
  icon,
  label,
  value,
  valueClassName,
  interactive,
  active,
  onClick,
  highlightTone = 'neutral',
  title,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  valueClassName?: string;
  interactive?: boolean;
  active?: boolean;
  onClick?: () => void;
  highlightTone?: 'neutral' | 'amber';
  title?: string;
}) {
  const base =
    'flex flex-col gap-1 rounded-lg border px-3 py-2.5 text-left transition-colors';
  const tone =
    active
      ? 'border-oe-blue bg-oe-blue-subtle'
      : highlightTone === 'amber'
        ? 'border-amber-200/60 bg-amber-50/60 dark:border-amber-700/30 dark:bg-amber-900/15'
        : 'border-border-light bg-surface-secondary';
  const cursor = interactive ? 'cursor-pointer hover:border-content-tertiary' : '';
  const Tag = interactive ? 'button' : 'div';
  return (
    <Tag
      type={interactive ? 'button' : undefined}
      onClick={interactive ? onClick : undefined}
      className={`${base} ${tone} ${cursor}`}
    >
      <span className="inline-flex items-center gap-1.5 text-xs text-content-tertiary">
        <span
          className={
            highlightTone === 'amber'
              ? 'text-amber-600 dark:text-amber-400'
              : 'text-content-tertiary'
          }
        >
          {icon}
        </span>
        {label}
      </span>
      <span
        className={`font-semibold text-content-primary tabular-nums truncate ${
          valueClassName ?? 'text-lg'
        }`}
        title={title ?? value}
      >
        {value}
      </span>
    </Tag>
  );
}

/* -- AssemblyTable -------------------------------------------------------- */

function AssemblyTable({
  items,
  fmt,
  selected,
  onToggleSelect,
  onToggleAll,
  allSelected,
  someSelected,
  sortKey,
  sortDir,
  onSort,
  onOpen,
  onDelete,
}: {
  items: Assembly[];
  fmt: (n: number) => string;
  selected: Set<string>;
  onToggleSelect: (id: string) => void;
  onToggleAll: () => void;
  allSelected: boolean;
  someSelected: boolean;
  sortKey: SortKey;
  sortDir: SortDir;
  onSort: (k: SortKey) => void;
  onOpen: (id: string) => void;
  onDelete: (id: string) => void;
}) {
  const { t } = useTranslation();
  // Two-step inline confirm for per-row delete (id armed for deletion). Keeps
  // the table compact while still guarding against an accidental click.
  const [confirmId, setConfirmId] = useState<string | null>(null);
  const headerCellBase =
    'px-3 py-2 text-left text-xs font-medium text-content-secondary select-none';
  const sortBtn = (key: SortKey, label: string, align: 'left' | 'right' | 'center' = 'left') => (
    <button
      type="button"
      onClick={() => onSort(key)}
      className={`inline-flex items-center gap-1 hover:text-content-primary transition-colors ${
        align === 'right' ? 'justify-end' : align === 'center' ? 'justify-center' : ''
      }`}
    >
      {label}
      {sortKey === key && (
        <span className="text-oe-blue">{sortDir === 'asc' ? '↑' : '↓'}</span>
      )}
    </button>
  );
  return (
    <div data-testid="assemblies-table" className="overflow-hidden rounded-xl border border-border-light bg-surface-primary">
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-surface-secondary border-b border-border-light">
            <tr>
              <th className={`${headerCellBase} w-10`}>
                <BulkCheckbox checked={allSelected} indeterminate={someSelected} onChange={onToggleAll} />
              </th>
              <th className={headerCellBase}>{sortBtn('name', t('assemblies.col_name', { defaultValue: 'Name' }))}</th>
              <th className={headerCellBase}>{sortBtn('code', t('common.code'))}</th>
              <th className={headerCellBase}>{t('assemblies.col_category', { defaultValue: 'Category' })}</th>
              <th className={headerCellBase}>{t('assemblies.col_unit', { defaultValue: 'Unit' })}</th>
              <th className={`${headerCellBase} text-right`}>{sortBtn('total_rate', t('assemblies.col_rate', { defaultValue: 'Rate' }), 'right')}</th>
              <th className={headerCellBase}>{t('assemblies.col_currency', { defaultValue: 'Currency' })}</th>
              <th className={`${headerCellBase} text-right`}>{sortBtn('component_count', t('assemblies.col_components', { defaultValue: 'Components' }), 'right')}</th>
              <th className={`${headerCellBase} text-right`}>{sortBtn('usage_count', t('assemblies.col_usage', { defaultValue: 'Used in BOQ' }), 'right')}</th>
              <th className={headerCellBase}>{sortBtn('updated_at', t('assemblies.col_updated', { defaultValue: 'Updated' }))}</th>
              <th className={`${headerCellBase} w-24 text-right`}>
                <span className="sr-only">{t('common.actions', { defaultValue: 'Actions' })}</span>
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border-light">
            {items.map((a) => {
              const isSel = selected.has(a.id);
              return (
                <tr
                  key={a.id}
                  data-selected={isSel ? 'true' : 'false'}
                  className={`group cursor-pointer transition-colors ${
                    isSel ? 'bg-oe-blue-subtle/50' : 'hover:bg-surface-secondary'
                  }`}
                  onClick={() => onOpen(a.id)}
                >
                  <td className="px-3 py-2 align-middle" onClick={(e) => e.stopPropagation()}>
                    <BulkCheckbox
                      checked={isSel}
                      indeterminate={false}
                      onChange={() => onToggleSelect(a.id)}
                    />
                  </td>
                  <td className="px-3 py-2 align-middle">
                    <span className="font-medium text-content-primary group-hover:text-oe-blue transition-colors">
                      {a.name}
                    </span>
                  </td>
                  <td className="px-3 py-2 align-middle font-mono text-xs text-content-tertiary">{a.code}</td>
                  <td className="px-3 py-2 align-middle">
                    {a.category ? (
                      <Badge variant={CATEGORY_COLORS[a.category] ?? 'neutral'} size="sm">{a.category}</Badge>
                    ) : (
                      <span className="text-content-quaternary">—</span>
                    )}
                  </td>
                  <td className="px-3 py-2 align-middle text-content-secondary uppercase text-xs">{a.unit}</td>
                  <td className="px-3 py-2 align-middle text-right tabular-nums font-semibold text-content-primary">
                    {a.total_rate > 0 ? fmt(a.total_rate) : <span className="text-content-quaternary font-normal">—</span>}
                  </td>
                  <td className="px-3 py-2 align-middle text-xs text-content-tertiary">
                    {a.currency || (
                      <span title={t('projects.currency_not_set', { defaultValue: 'Currency not set' })}>—</span>
                    )}
                  </td>
                  <td className="px-3 py-2 align-middle text-right tabular-nums text-content-secondary">{a.component_count ?? 0}</td>
                  <td className="px-3 py-2 align-middle text-right tabular-nums">
                    {(a.usage_count ?? 0) > 0 ? (
                      <span className="text-oe-blue font-medium">{a.usage_count}</span>
                    ) : (
                      <span className="text-content-quaternary">0</span>
                    )}
                  </td>
                  <td className="px-3 py-2 align-middle text-xs text-content-tertiary whitespace-nowrap">
                    {new Date(a.updated_at).toLocaleDateString(getIntlLocale())}
                  </td>
                  <td className="px-3 py-2 align-middle text-right" onClick={(e) => e.stopPropagation()}>
                    {confirmId === a.id ? (
                      <span className="inline-flex items-center gap-1">
                        <button
                          type="button"
                          onClick={() => { setConfirmId(null); onDelete(a.id); }}
                          className="rounded-md px-2 py-1 text-xs font-medium text-white bg-red-500 hover:bg-red-600 transition-colors"
                        >
                          {t('common.delete', { defaultValue: 'Delete' })}
                        </button>
                        <button
                          type="button"
                          onClick={() => setConfirmId(null)}
                          className="rounded-md px-2 py-1 text-xs font-medium text-content-secondary hover:bg-surface-secondary transition-colors"
                        >
                          {t('common.cancel', { defaultValue: 'Cancel' })}
                        </button>
                      </span>
                    ) : (
                      <button
                        type="button"
                        onClick={() => setConfirmId(a.id)}
                        className="opacity-0 group-hover:opacity-100 focus:opacity-100 inline-flex h-7 w-7 items-center justify-center rounded-md text-content-tertiary hover:bg-red-50 hover:text-red-500 dark:hover:bg-red-900/20 transition-all"
                        title={t('assemblies.delete_confirm', { defaultValue: 'Delete assembly?' })}
                        aria-label={t('a11y.assemblies.delete_row', {
                          defaultValue: 'Delete assembly {{name}}',
                          name: a.name,
                        })}
                      >
                        <Trash2 size={14} />
                      </button>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function BulkCheckbox({
  checked,
  indeterminate,
  onChange,
}: {
  checked: boolean;
  indeterminate: boolean;
  onChange: () => void;
}) {
  const ref = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (ref.current) ref.current.indeterminate = indeterminate;
  }, [indeterminate]);
  return (
    <label className="inline-flex items-center justify-center cursor-pointer">
      <input
        ref={ref}
        type="checkbox"
        checked={checked}
        onChange={onChange}
        className="h-4 w-4 rounded border-border text-oe-blue focus:ring-oe-blue cursor-pointer"
      />
    </label>
  );
}

/* -- Bulk Tag Modal ------------------------------------------------------- */

function BulkTagModal({
  count,
  onClose,
  onApply,
}: {
  count: number;
  onClose: () => void;
  onApply: (tags: string[]) => void;
}) {
  const { t } = useTranslation();
  const [input, setInput] = useState('');
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 animate-fade-in" onClick={onClose}>
      <div
        className="bg-surface-elevated rounded-2xl border border-border shadow-2xl w-full max-w-md mx-4"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-5 py-3 border-b border-border-light">
          <div className="flex items-center gap-2">
            <Tag size={16} className="text-violet-500" />
            <h2 className="text-sm font-semibold text-content-primary">
              {t('assemblies.bulk_tag_title', { defaultValue: `Add tag to ${count} assemblies`, count })}
            </h2>
          </div>
          <button
            onClick={onClose}
            aria-label={t('common.close', { defaultValue: 'Close' })}
            className="text-content-tertiary hover:text-content-primary"
          >
            <X size={16} />
          </button>
        </div>
        <div className="px-5 py-4 space-y-3">
          <p className="text-xs text-content-tertiary">
            {t('assemblies.bulk_tag_desc', {
              defaultValue: 'Enter one or more tags, separated by commas. Existing tags are preserved.',
            })}
          </p>
          <input
            type="text"
            autoFocus
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder={t('assemblies.bulk_tag_placeholder', { defaultValue: 'e.g. reviewed, q2-2026' })}
            className="w-full h-10 px-3 rounded-lg border border-border-light bg-surface-primary text-sm text-content-primary placeholder:text-content-quaternary focus:outline-none focus:ring-2 focus:ring-oe-blue focus:border-transparent"
          />
        </div>
        <div className="flex items-center justify-end gap-2 px-5 py-3 border-t border-border-light">
          <Button variant="secondary" size="sm" onClick={onClose}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button
            variant="primary"
            size="sm"
            disabled={!input.trim()}
            onClick={() => {
              const tags = input.split(',').map((s) => s.trim()).filter(Boolean);
              if (tags.length > 0) onApply(tags);
            }}
          >
            {t('assemblies.bulk_tag_apply', { defaultValue: 'Apply' })}
          </Button>
        </div>
      </div>
    </div>
  );
}

/* -- Bulk Delete Confirm -------------------------------------------------- */

function BulkDeleteConfirm({
  count,
  onCancel,
  onConfirm,
}: {
  count: number;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  const { t } = useTranslation();
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 animate-fade-in" onClick={onCancel}>
      <div
        className="bg-surface-elevated rounded-2xl border border-border shadow-2xl w-full max-w-md mx-4"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="px-5 py-4">
          <div className="flex h-10 w-10 items-center justify-center rounded-full bg-red-50 dark:bg-red-900/20 mb-3">
            <Trash2 size={18} className="text-red-500" />
          </div>
          <h2 className="text-sm font-semibold text-content-primary mb-1">
            {t('assemblies.bulk_delete_title', { defaultValue: `Delete ${count} assemblies?`, count })}
          </h2>
          <p className="text-xs text-content-tertiary">
            {t('assemblies.bulk_delete_desc', {
              defaultValue:
                'This permanently removes the selected assemblies and all their components. Assemblies referenced by BOQ positions are not auto-unlinked.',
            })}
          </p>
        </div>
        <div className="flex items-center justify-end gap-2 px-5 py-3 border-t border-border-light">
          <Button variant="secondary" size="sm" onClick={onCancel}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button variant="danger" size="sm" onClick={onConfirm}>
            {t('common.delete')}
          </Button>
        </div>
      </div>
    </div>
  );
}

/* -- AI Generate Modal ---------------------------------------------------- */

function AIGenerateModal({
  onClose,
  onCreated,
}: {
  onClose: () => void;
  onCreated: (assemblyId: string) => void;
}) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);

  const [description, setDescription] = useState('');
  const [region, setRegion] = useState('');
  const [unit, setUnit] = useState('m2');
  const [result, setResult] = useState<AIGeneratedAssembly | null>(null);
  const [saving, setSaving] = useState(false);

  const generateMutation = useMutation({
    mutationFn: () => assembliesApi.aiGenerate({ description, region, unit }),
    onSuccess: (data) => setResult(data),
    onError: (err: Error) => {
      addToast({ type: 'error', title: t('assemblies.ai_generate_failed', { defaultValue: 'Generation failed' }), message: err.message });
    },
  });

  const handleSave = async () => {
    if (!result) return;
    setSaving(true);
    try {
      // Create the assembly
      const assembly = await assembliesApi.create({
        code: result.code,
        name: result.name,
        unit: result.unit,
        category: result.category || 'general',
        bid_factor: 1.0,
      });

      // Add all components
      for (const comp of result.components) {
        await assembliesApi.addComponent(assembly.id, {
          cost_item_id: comp.cost_item_id || undefined,
          description: comp.name,
          factor: 1.0,
          quantity: comp.quantity,
          unit: comp.unit,
          unit_cost: comp.unit_rate,
        });
      }

      addToast({
        type: 'success',
        title: t('assemblies.ai_assembly_saved', { defaultValue: 'Assembly saved' }),
        message: result.name,
      });
      onCreated(assembly.id);
    } catch {
      addToast({
        type: 'error',
        title: t('assemblies.ai_save_failed', { defaultValue: 'Failed to save assembly' }),
      });
    } finally {
      setSaving(false);
    }
  };

  const fmt = (n: number) =>
    new Intl.NumberFormat(getNumberLocale(), {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }).format(n);

  // The backend "confidence" is purely a function of how many catalogue rows
  // matched the keyword search (it is a lexical ILIKE search, not a model).
  // Surface it honestly as "match coverage" so a non-expert does not read it
  // as AI certainty.
  const coverageColor = result
    ? result.confidence >= 0.7
      ? 'text-emerald-600'
      : result.confidence >= 0.4
        ? 'text-amber-600'
        : 'text-red-500'
    : '';

  const coverageLabel = result
    ? result.confidence >= 0.7
      ? t('assemblies.coverage_high', { defaultValue: 'Strong' })
      : result.confidence >= 0.4
        ? t('assemblies.coverage_medium', { defaultValue: 'Partial' })
        : t('assemblies.coverage_low', { defaultValue: 'Sparse' })
    : '';

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 animate-fade-in" onClick={onClose}>
      <div
        className="bg-surface-elevated rounded-2xl border border-border shadow-2xl w-full max-w-2xl mx-4 max-h-[85vh] flex flex-col overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-border-light shrink-0">
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-gradient-to-br from-violet-100 to-blue-100 text-violet-600 dark:from-violet-900/30 dark:to-blue-900/30">
              <Sparkles size={18} />
            </div>
            <div>
              <h2 className="text-base font-semibold text-content-primary">
                {t('assemblies.ai_generate_title', { defaultValue: 'AI Assembly Generator' })}
              </h2>
              <p className="text-xs text-content-tertiary">
                {t('assemblies.ai_generate_desc', { defaultValue: 'Describe what you need and we search the cost catalogue for matching priced components' })}
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

        {/* Input form */}
        <div className="px-6 py-4 border-b border-border-light shrink-0 space-y-3">
          <div>
            <label className="block text-sm font-medium text-content-primary mb-1.5">
              {t('assemblies.ai_description_label', { defaultValue: 'Description' })}
            </label>
            <input
              type="text"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder={t('assemblies.ai_description_placeholder', { defaultValue: 'e.g. Reinforced concrete wall C30/37, 25cm thickness' })}
              className="w-full h-10 px-3 rounded-lg border border-border-light bg-surface-primary text-sm text-content-primary placeholder:text-content-quaternary focus:outline-none focus:ring-2 focus:ring-violet-500/30 focus:border-violet-400"
              autoFocus
              onKeyDown={(e) => {
                if (e.key === 'Enter' && description.trim().length >= 3 && !generateMutation.isPending) {
                  generateMutation.mutate();
                }
              }}
            />
          </div>
          <div className="flex gap-3">
            <div className="flex-1">
              <label className="block text-xs font-medium text-content-tertiary mb-1">
                {t('assemblies.unit', { defaultValue: 'Unit' })}
              </label>
              <select
                value={unit}
                onChange={(e) => setUnit(e.target.value)}
                className="w-full h-9 px-2.5 rounded-lg border border-border-light bg-surface-primary text-sm text-content-primary focus:outline-none focus:ring-2 focus:ring-violet-500/30 appearance-none cursor-pointer"
              >
                {UNIT_OPTIONS.map((u) => (
                  <option key={u} value={u}>{unitLabel(u, t)}</option>
                ))}
              </select>
            </div>
            <div className="flex-1">
              <label className="block text-xs font-medium text-content-tertiary mb-1">
                {t('assemblies.region', { defaultValue: 'Region (optional)' })}
              </label>
              <input
                type="text"
                value={region}
                onChange={(e) => setRegion(e.target.value)}
                placeholder={t('assemblies.region_placeholder', { defaultValue: 'e.g. Berlin' })}
                className="w-full h-9 px-2.5 rounded-lg border border-border-light bg-surface-primary text-sm text-content-primary placeholder:text-content-quaternary focus:outline-none focus:ring-2 focus:ring-violet-500/30"
              />
            </div>
            <div className="flex items-end">
              <Button
                variant="primary"
                size="sm"
                icon={generateMutation.isPending ? <Loader2 size={14} className="animate-spin" /> : <Sparkles size={14} />}
                onClick={() => generateMutation.mutate()}
                disabled={description.trim().length < 3 || generateMutation.isPending}
                className="bg-violet-600 hover:bg-violet-700 h-9"
              >
                {generateMutation.isPending
                  ? t('assemblies.generating', { defaultValue: 'Generating...' })
                  : t('assemblies.generate', { defaultValue: 'Generate' })
                }
              </Button>
            </div>
          </div>
        </div>

        {/* Results */}
        <div className="flex-1 overflow-y-auto px-6 py-4">
          {!result && !generateMutation.isPending && (
            <div className="flex flex-col items-center justify-center py-12 text-center">
              <Sparkles size={32} className="text-content-quaternary mb-3" />
              <p className="text-sm text-content-tertiary">
                {t('assemblies.ai_generate_hint', { defaultValue: 'Enter a description and click Generate to search for matching cost components' })}
              </p>
            </div>
          )}

          {generateMutation.isPending && (
            <div className="flex flex-col items-center justify-center py-12">
              <Loader2 size={24} className="animate-spin text-violet-500 mb-3" />
              <p className="text-sm text-content-tertiary">
                {t('assemblies.ai_searching', { defaultValue: 'Searching cost database for matching components...' })}
              </p>
            </div>
          )}

          {result && (
            <div className="space-y-4">
              {/* Summary */}
              <div className="flex items-center justify-between">
                <div>
                  <h3 className="text-sm font-semibold text-content-primary">{result.name}</h3>
                  <p className="text-xs text-content-tertiary mt-0.5">
                    {result.source_items_count} {t('assemblies.items_found', { defaultValue: 'items found' })}
                    {' / '}
                    <span
                      title={t('assemblies.coverage_hint', {
                        defaultValue:
                          'How many of the components were matched to a priced catalogue item by the keyword search. This reflects catalogue coverage, not AI certainty - always review the matched rates.',
                      })}
                      className="cursor-help underline decoration-dotted decoration-content-quaternary underline-offset-2"
                    >
                      {t('assemblies.match_coverage', { defaultValue: 'Match coverage' })}
                    </span>
                    : <span className={`font-semibold ${coverageColor}`}>{coverageLabel}</span>
                  </p>
                </div>
                <div className="text-right">
                  <p className="text-lg font-bold text-content-primary tabular-nums">
                    {fmt(result.total_rate)}
                    <span className="text-xs font-normal text-content-tertiary ml-1">/ {result.unit}</span>
                  </p>
                </div>
              </div>

              {/* Components table */}
              {result.components.length > 0 ? (
                <div className="rounded-lg border border-border-light overflow-hidden">
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="border-b border-border-light bg-surface-tertiary">
                        <th className="px-3 py-2 text-left font-medium text-content-secondary">{t('boq.description', { defaultValue: 'Description' })}</th>
                        <th className="px-3 py-2 text-center font-medium text-content-secondary w-16">{t('assemblies.type', { defaultValue: 'Type' })}</th>
                        <th className="px-3 py-2 text-center font-medium text-content-secondary w-14">{t('boq.unit', { defaultValue: 'Unit' })}</th>
                        <th className="px-3 py-2 text-right font-medium text-content-secondary w-14">{t('boq.quantity', { defaultValue: 'Qty' })}</th>
                        <th className="px-3 py-2 text-right font-medium text-content-secondary w-20">{t('assemblies.rate', { defaultValue: 'Rate' })}</th>
                        <th className="px-3 py-2 text-right font-medium text-content-secondary w-20">{t('boq.total', { defaultValue: 'Total' })}</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-border-light">
                      {result.components.map((comp, idx) => {
                        const typeBadge = comp.type === 'labor'
                          ? 'bg-blue-50 text-blue-700 dark:bg-blue-900/20 dark:text-blue-400'
                          : comp.type === 'equipment'
                            ? 'bg-amber-50 text-amber-700 dark:bg-amber-900/20 dark:text-amber-400'
                            : 'bg-emerald-50 text-emerald-700 dark:bg-emerald-900/20 dark:text-emerald-400';
                        return (
                          <tr key={`${comp.name}-${comp.type}-${idx}`} className="hover:bg-surface-secondary/50">
                            <td className="px-3 py-2 text-content-primary truncate max-w-[250px]">{comp.name}</td>
                            <td className="px-3 py-2 text-center">
                              <span className={`inline-block px-1.5 py-0.5 rounded text-[10px] font-medium ${typeBadge}`}>
                                {comp.type}
                              </span>
                            </td>
                            <td className="px-3 py-2 text-center text-content-secondary font-mono uppercase">{comp.unit}</td>
                            <td className="px-3 py-2 text-right text-content-primary tabular-nums">{comp.quantity}</td>
                            <td className="px-3 py-2 text-right text-content-primary tabular-nums">{fmt(comp.unit_rate)}</td>
                            <td className="px-3 py-2 text-right font-semibold text-content-primary tabular-nums">{fmt(comp.total)}</td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              ) : (
                <div className="rounded-lg bg-surface-tertiary p-6 text-center">
                  <p className="text-sm text-content-tertiary">
                    {t('assemblies.no_components_found', { defaultValue: 'No matching cost items found. Try a different description.' })}
                  </p>
                </div>
              )}
            </div>
          )}
        </div>

        {/* Footer actions */}
        {result && result.components.length > 0 && (
          <div className="flex items-center justify-between px-6 py-4 border-t border-border-light shrink-0">
            <Button variant="secondary" size="sm" onClick={() => setResult(null)}>
              {t('assemblies.discard', { defaultValue: 'Discard' })}
            </Button>
            <Button
              variant="primary"
              size="sm"
              onClick={handleSave}
              loading={saving}
              icon={<Layers size={14} />}
              className="bg-violet-600 hover:bg-violet-700"
            >
              {t('assemblies.save_as_assembly', { defaultValue: 'Save as Assembly' })}
            </Button>
          </div>
        )}
      </div>
    </div>
  );
}

/* -- Assembly Card -------------------------------------------------------- */

function AssemblyCard({
  assembly,
  fmt,
  onClick,
  onDuplicate,
  onDelete,
  onExport,
  selected,
  onToggleSelect,
}: {
  assembly: Assembly;
  fmt: (n: number) => string;
  onClick: () => void;
  onDuplicate: () => void;
  onDelete: () => void;
  onExport: () => void;
  selected: boolean;
  onToggleSelect: () => void;
}) {
  const { t } = useTranslation();
  const [menuOpen, setMenuOpen] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [previewOpen, setPreviewOpen] = useState(false);
  // Hover preview — fires after a 400 ms hover-intent so it never
  // flickers during fast cursor sweeps across the grid.
  const [hoverPreview, setHoverPreview] = useState(false);
  const hoverTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const cancelHover = useCallback(() => {
    if (hoverTimer.current) { clearTimeout(hoverTimer.current); hoverTimer.current = null; }
    setHoverPreview(false);
  }, []);
  const scheduleHover = useCallback(() => {
    if (hoverTimer.current) clearTimeout(hoverTimer.current);
    hoverTimer.current = setTimeout(() => setHoverPreview(true), 400);
  }, []);
  useEffect(() => () => { if (hoverTimer.current) clearTimeout(hoverTimer.current); }, []);
  const badgeVariant = CATEGORY_COLORS[assembly.category] ?? 'neutral';

  return (
    <Card
      padding="none"
      hoverable
      className={`cursor-pointer group relative ${
        selected ? 'ring-2 ring-oe-blue ring-offset-1 ring-offset-surface-primary' : ''
      }`}
      onClick={onClick}
      onMouseEnter={scheduleHover}
      onMouseLeave={cancelHover}
    >
      {/* Delete confirmation overlay */}
      {confirmDelete && (
        <div
          className="absolute inset-0 z-30 flex items-center justify-center rounded-xl bg-white/95 dark:bg-gray-900/95 backdrop-blur-sm p-4"
          onClick={(e) => e.stopPropagation()}
        >
          <div className="text-center">
            <div className="flex h-10 w-10 items-center justify-center rounded-full bg-red-50 dark:bg-red-900/20 mx-auto mb-3">
              <Trash2 size={18} className="text-red-500" />
            </div>
            <p className="text-sm font-semibold text-content-primary mb-1">{t('assemblies.delete_confirm', { defaultValue: 'Delete assembly?' })}</p>
            <p className="text-xs text-content-tertiary mb-4 max-w-[180px] mx-auto line-clamp-1">{assembly.name}</p>
            <div className="flex items-center justify-center gap-2">
              <Button variant="danger" size="sm" onClick={() => { onDelete(); setConfirmDelete(false); }}>
                {t('common.delete')}
              </Button>
              <Button variant="secondary" size="sm" onClick={() => setConfirmDelete(false)}>
                {t('common.cancel', { defaultValue: 'Cancel' })}
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* Quick preview overlay */}
      {previewOpen && (
        <QuickPreview
          assemblyId={assembly.id}
          assemblyName={assembly.name}
          onClose={() => setPreviewOpen(false)}
        />
      )}

      <div className="p-3">
        {/* Top row: select checkbox + code + menu */}
        <div className="flex items-start justify-between mb-1">
          <div className="flex items-center gap-2 min-w-0">
            <button
              type="button"
              onClick={(e) => { e.stopPropagation(); onToggleSelect(); }}
              className={`shrink-0 flex h-5 w-5 items-center justify-center rounded-md transition-all ${
                selected
                  ? 'bg-oe-blue text-white'
                  : 'border border-border bg-surface-primary text-transparent opacity-0 group-hover:opacity-100 hover:border-content-tertiary'
              }`}
              aria-label={t('assemblies.toggle_select', { defaultValue: 'Toggle selection' })}
              aria-pressed={selected}
            >
              {selected ? <CheckSquare size={12} /> : <SquareIcon size={12} />}
            </button>
            <p className="text-xs font-mono text-content-tertiary truncate">{assembly.code}</p>
          </div>
          <div className="flex items-center gap-1">
            <button
              type="button"
              onClick={(e) => { e.stopPropagation(); setPreviewOpen(true); }}
              className="opacity-0 group-hover:opacity-100 flex h-6 w-6 items-center justify-center rounded-md text-content-tertiary hover:bg-surface-secondary hover:text-content-primary transition-all"
              title={t('assemblies.quick_preview', { defaultValue: 'Quick preview' })}
              aria-label={t('a11y.assemblies.quick_preview', {
                defaultValue: 'Quick preview of {{name}}',
                name: assembly.name,
              })}
            >
              <Eye size={14} />
            </button>
            <button
              type="button"
              onClick={(e) => { e.stopPropagation(); setMenuOpen(!menuOpen); }}
              /* Always visible (not hover-only) so the delete/duplicate/export
                 actions are discoverable on touch and for users who do not
                 hover - the menu is the only place card-view delete lives. */
              className="opacity-60 group-hover:opacity-100 flex h-6 w-6 items-center justify-center rounded-md text-content-tertiary hover:bg-surface-secondary hover:text-content-primary transition-all"
              aria-label={t('a11y.assemblies.card_actions', {
                defaultValue: 'Actions for assembly {{name}}',
                name: assembly.name,
              })}
              aria-haspopup="menu"
              aria-expanded={menuOpen}
            >
              <MoreHorizontal size={14} />
            </button>
          </div>
        </div>

        {/* Hover popover — first 3 components with their rates. Only
            fetched after the 400ms hover-intent fires, so we don't
            slam the backend on a hover sweep. */}
        {hoverPreview && !previewOpen && !confirmDelete && !menuOpen && (
          <HoverComponentsPopover assemblyId={assembly.id} fmt={fmt} />
        )}

        {/* Context menu */}
        {menuOpen && (
          <div
            className="absolute top-10 right-4 z-20 w-44 rounded-lg border border-border bg-surface-elevated shadow-lg overflow-hidden"
            onClick={(e) => e.stopPropagation()}
          >
            <button
              onClick={() => { setMenuOpen(false); onClick(); }}
              className="flex w-full items-center gap-2 px-3 py-2 text-sm text-content-primary hover:bg-surface-secondary transition-colors"
            >
              <ExternalLink size={14} /> {t('assemblies.open_editor', { defaultValue: 'Open Editor' })}
            </button>
            <button
              onClick={() => { setMenuOpen(false); onDuplicate(); }}
              className="flex w-full items-center gap-2 px-3 py-2 text-sm text-content-primary hover:bg-surface-secondary transition-colors"
            >
              <Copy size={14} /> {t('assemblies.duplicate', { defaultValue: 'Duplicate & Edit' })}
            </button>
            <button
              onClick={() => { setMenuOpen(false); onExport(); }}
              className="flex w-full items-center gap-2 px-3 py-2 text-sm text-content-primary hover:bg-surface-secondary transition-colors"
            >
              <Share2 size={14} /> {t('assemblies.export_json', { defaultValue: 'Export as JSON' })}
            </button>
            <button
              onClick={() => {
                setMenuOpen(false);
                const text = `${assembly.code}\t${assembly.name}\t${assembly.unit}\t${assembly.total_rate}\t${assembly.category}`;
                copyToClipboard(text).catch(() => {});
              }}
              className="flex w-full items-center gap-2 px-3 py-2 text-sm text-content-primary hover:bg-surface-secondary transition-colors"
            >
              <Download size={14} /> {t('assemblies.copy_data', { defaultValue: 'Copy to Clipboard' })}
            </button>
            <div className="h-px bg-border-light" />
            <button
              onClick={() => { setMenuOpen(false); setConfirmDelete(true); }}
              className="flex w-full items-center gap-2 px-3 py-2 text-sm text-red-500 hover:bg-red-50 dark:hover:bg-red-900/20 transition-colors"
            >
              <Trash2 size={14} /> {t('common.delete', { defaultValue: 'Delete' })}
            </button>
          </div>
        )}

        {/* Name */}
        <h3 className="text-sm font-semibold text-content-primary leading-snug line-clamp-2 group-hover:text-oe-blue transition-colors">
          {assembly.name}
        </h3>

        {/* Component count + usage count */}
        <div className="mt-1 flex items-center gap-2 text-2xs text-content-tertiary">
          <span>
            {assembly.component_count ?? 0} {t('assemblies.components', { defaultValue: 'components' })}
          </span>
          {(assembly.usage_count ?? 0) > 0 && (
            <>
              <span className="text-content-quaternary">|</span>
              <span className="text-oe-blue">
                {assembly.usage_count} {t('assemblies.times_used', { defaultValue: 'used in BOQ' })}
              </span>
            </>
          )}
        </div>

        {/* Rate */}
        <p className="mt-1.5 text-base font-bold tabular-nums" style={{ color: assembly.total_rate > 0 ? undefined : 'var(--color-content-tertiary)' }}>
          {assembly.total_rate > 0 ? fmt(assembly.total_rate) : '0,00'}
          <span className="ml-1 text-xs font-normal text-content-tertiary">
            / {assembly.unit}
          </span>
          {assembly.total_rate === 0 && (
            <span className="ml-2 text-2xs font-medium text-amber-500">
              ({t('assemblies.draft', { defaultValue: 'draft' })})
            </span>
          )}
        </p>

        {/* Category + currency badges */}
        <div className="mt-1.5 flex flex-wrap items-center gap-1">
          {assembly.category && (
            <Badge variant={badgeVariant} size="sm">
              {assembly.category}
            </Badge>
          )}
          <span
            title={
              assembly.currency
                ? undefined
                : t('projects.currency_not_set', { defaultValue: 'Currency not set' })
            }
          >
            <Badge variant="neutral" size="sm">
              {assembly.currency || '—'}
            </Badge>
          </span>
          {assembly.bid_factor !== 1.0 && (
            <Badge variant="blue" size="sm">
              BF {assembly.bid_factor}
            </Badge>
          )}
          {/* Tags */}
          {(assembly.tags ?? []).map((tag) => (
            <Badge key={tag} variant="neutral" size="sm" className="bg-violet-50 text-violet-700 dark:bg-violet-900/20 dark:text-violet-400 border-violet-200/50">
              {tag}
            </Badge>
          ))}
        </div>
      </div>
    </Card>
  );
}

/* -- Quick Preview -------------------------------------------------------- */

function QuickPreview({
  assemblyId,
  assemblyName,
  onClose,
}: {
  assemblyId: string;
  assemblyName: string;
  onClose: () => void;
}) {
  const { t } = useTranslation();

  const { data, isLoading } = useQuery({
    queryKey: ['assembly-preview', assemblyId],
    queryFn: () => assembliesApi.get(assemblyId),
    staleTime: 60_000,
  });

  const fmt = (n: number) =>
    new Intl.NumberFormat(getNumberLocale(), {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }).format(n);

  const components = data?.components ?? [];
  const preview = components.slice(0, 5);
  const remaining = components.length - preview.length;

  return (
    <div
      className="absolute inset-0 z-30 flex flex-col rounded-xl bg-white/95 dark:bg-gray-900/95 backdrop-blur-sm p-4 animate-fade-in overflow-hidden"
      onClick={(e) => e.stopPropagation()}
    >
      <div className="flex items-center justify-between mb-3">
        <p className="text-xs font-semibold text-content-primary truncate flex-1 mr-2">
          {assemblyName}
        </p>
        <button
          onClick={onClose}
          aria-label={t('common.close', { defaultValue: 'Close' })}
          className="flex h-5 w-5 items-center justify-center rounded text-content-tertiary hover:text-content-primary transition-colors shrink-0"
        >
          <X size={12} />
        </button>
      </div>

      {isLoading ? (
        <div className="flex-1 flex items-center justify-center">
          <Loader2 size={16} className="animate-spin text-content-tertiary" />
        </div>
      ) : preview.length === 0 ? (
        <p className="text-2xs text-content-tertiary text-center flex-1 flex items-center justify-center">
          {t('assemblies.no_components_hint', { defaultValue: 'No components yet' })}
        </p>
      ) : (
        <div className="flex-1 overflow-hidden">
          <div className="space-y-1">
            {preview.map((comp) => (
              <div key={comp.id} className="flex items-center justify-between gap-2 text-2xs">
                <span className="text-content-primary truncate flex-1">{comp.description}</span>
                <span className="text-content-secondary tabular-nums shrink-0">{fmt(comp.total)}</span>
              </div>
            ))}
          </div>
          {remaining > 0 && (
            <p className="mt-1.5 text-2xs text-content-quaternary">
              +{remaining} {t('assemblies.more_components', { defaultValue: 'more' })}...
            </p>
          )}
          {data && (
            <div className="mt-2 pt-2 border-t border-border-light flex items-center justify-between text-xs">
              <span className="font-medium text-content-secondary">
                {t('assemblies.total_rate', { defaultValue: 'Total Rate' })}
              </span>
              <span className="font-bold text-content-primary tabular-nums">
                {fmt(data.total_rate)} / {data.unit}
              </span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/* -- Hover Components Popover -------------------------------------------- */

function HoverComponentsPopover({
  assemblyId,
  fmt,
}: {
  assemblyId: string;
  fmt: (n: number) => string;
}) {
  const { t } = useTranslation();
  // Fetch only when this mounts — cached for 60s so re-hovering the
  // same card doesn't re-fire the request.
  const { data, isLoading } = useQuery({
    queryKey: ['assembly-preview', assemblyId],
    queryFn: () => assembliesApi.get(assemblyId),
    staleTime: 60_000,
  });
  const top = (data?.components ?? []).slice(0, 3);
  const remaining = Math.max(0, (data?.components?.length ?? 0) - top.length);
  return (
    <div className="absolute left-2 right-2 top-12 z-20 rounded-lg border border-border bg-surface-elevated shadow-xl px-3 py-2 animate-fade-in pointer-events-none">
      <p className="text-2xs uppercase tracking-wide text-content-tertiary mb-1.5">
        {t('assemblies.preview_components', { defaultValue: 'Top components' })}
      </p>
      {isLoading ? (
        <div className="flex items-center gap-2 py-1 text-xs text-content-tertiary">
          <Loader2 size={11} className="animate-spin" />
          {t('common.loading')}
        </div>
      ) : top.length === 0 ? (
        <p className="text-xs text-content-tertiary">
          {t('assemblies.no_components_hint', { defaultValue: 'No components yet' })}
        </p>
      ) : (
        <div className="space-y-1">
          {top.map((c) => (
            <div key={c.id} className="flex items-center justify-between gap-2 text-xs">
              <span className="text-content-primary truncate flex-1">{c.description}</span>
              <span className="text-content-secondary tabular-nums shrink-0">{fmt(c.total)}</span>
            </div>
          ))}
          {remaining > 0 && (
            <p className="text-2xs text-content-quaternary pt-0.5">
              +{remaining} {t('assemblies.more_components', { defaultValue: 'more' })}…
            </p>
          )}
        </div>
      )}
    </div>
  );
}

/* -- Import Assembly Modal ------------------------------------------------ */

function ImportAssemblyModal({
  onClose,
  onImported,
}: {
  onClose: () => void;
  onImported: () => void;
}) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const [jsonText, setJsonText] = useState('');
  const [importing, setImporting] = useState(false);
  const [error, setError] = useState('');

  const handleFileSelect = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (ev) => {
      setJsonText(ev.target?.result as string || '');
      setError('');
    };
    reader.readAsText(file);
  }, []);

  const handleImport = async () => {
    setError('');
    setImporting(true);
    try {
      const parsed = JSON.parse(jsonText);
      if (!parsed.code || !parsed.name || !parsed.unit) {
        setError(t('assemblies.import_invalid', { defaultValue: 'Invalid JSON: must contain code, name, and unit fields' }));
        setImporting(false);
        return;
      }
      await assembliesApi.importAssembly(parsed);
      addToast({ type: 'success', title: t('assemblies.import_success', { defaultValue: 'Assembly imported' }) });
      onImported();
    } catch (err) {
      if (err instanceof SyntaxError) {
        setError(t('assemblies.import_json_error', { defaultValue: 'Invalid JSON format' }));
      } else {
        setError((err as Error).message || t('assemblies.import_failed', { defaultValue: 'Import failed' }));
      }
    } finally {
      setImporting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 animate-fade-in" onClick={onClose}>
      <div
        className="bg-surface-elevated rounded-2xl border border-border shadow-2xl w-full max-w-lg mx-4 flex flex-col overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-border-light">
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-oe-blue-subtle text-oe-blue-text">
              <Upload size={18} />
            </div>
            <div>
              <h2 className="text-base font-semibold text-content-primary">
                {t('assemblies.import_title', { defaultValue: 'Import Assembly' })}
              </h2>
              <p className="text-xs text-content-tertiary">
                {t('assemblies.import_desc', { defaultValue: 'Paste JSON or upload an exported assembly file' })}
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

        {/* Body */}
        <div className="px-6 py-4 space-y-3">
          <div>
            <label className="flex items-center gap-2 text-sm font-medium text-content-primary mb-1.5">
              <Upload size={14} />
              {t('assemblies.upload_file', { defaultValue: 'Upload JSON file' })}
            </label>
            <input
              type="file"
              accept=".json"
              onChange={handleFileSelect}
              className="w-full text-sm text-content-secondary file:mr-3 file:py-1.5 file:px-3 file:rounded-lg file:border file:border-border-light file:bg-surface-secondary file:text-sm file:font-medium file:text-content-primary file:cursor-pointer hover:file:bg-surface-tertiary"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-content-primary mb-1.5">
              {t('assemblies.or_paste_json', { defaultValue: 'Or paste JSON' })}
            </label>
            <textarea
              value={jsonText}
              onChange={(e) => { setJsonText(e.target.value); setError(''); }}
              rows={8}
              placeholder='{"code": "ASM-001", "name": "...", "unit": "m2", "components": [...]}'
              className="w-full rounded-lg border border-border-light bg-surface-primary px-3 py-2 text-xs font-mono text-content-primary placeholder:text-content-quaternary focus:outline-none focus:ring-2 focus:ring-oe-blue-light/50 focus:border-oe-blue-light resize-none"
            />
          </div>
          {error && (
            <div className="rounded-lg bg-semantic-error-bg px-3 py-2 text-sm text-semantic-error">
              {error}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-3 px-6 py-4 border-t border-border-light">
          <Button variant="secondary" onClick={onClose}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button
            variant="primary"
            onClick={handleImport}
            disabled={!jsonText.trim()}
            loading={importing}
            icon={<Upload size={15} />}
          >
            {t('assemblies.import_btn', { defaultValue: 'Import' })}
          </Button>
        </div>
      </div>
    </div>
  );
}
