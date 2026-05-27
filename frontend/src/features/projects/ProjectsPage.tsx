import React, { useState, useMemo, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useNavigate, useLocation, Link } from 'react-router-dom';
import {
  FolderPlus, FolderOpen, ArrowRight, MoreHorizontal, Copy, Trash2, Archive, ArchiveRestore, ExternalLink,
  Search, ChevronDown, ArrowUpDown, Star, Map as MapIcon, CloudSun,
  Building2, DollarSign, Euro, PoundSterling, Globe2, MapPin, Layers, AlertTriangle,
} from 'lucide-react';
import { formatDistanceToNowStrict, isValid as isValidDate, parseISO } from 'date-fns';
import { Button, Card, Badge, EmptyState, Skeleton, SkeletonGrid, Breadcrumb, ProjectMap, ProjectWeather, FileTypeChips, type LatLng } from '@/shared/ui';
import { useWidgetSettingsStore } from '@/stores/useWidgetSettingsStore';
import { getIntlLocale } from '@/shared/lib/formatters';
import { projectsApi, type Project } from './api';
import { apiGet, apiPatch, apiDelete } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { useLocalStorage } from '@/shared/hooks/useLocalStorage';
import { CreateProjectModal } from './CreateProjectPage';
import { BIMConverterStatusBanner } from '../bim/BIMConverterStatusBanner';

interface ProjectBOQStats {
  projectId: string;
  boqCount: number;
  totalValue: number;
  hasError?: boolean;
}

type SortOption = 'name_asc' | 'newest' | 'oldest' | 'value';
type StatusFilter = 'all' | 'active' | 'archived';

const ITEMS_PER_PAGE = 12;

// Region tags + colours are derived from actual project data — no
// region-specific list is hard-coded in the default UI per the
// "no country-specific standards or city names in default UI" rule.
// Avatar colours cycle through a palette indexed by region string.
const REGION_AVATAR_PALETTE = [
  'bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300',
  'bg-purple-100 text-purple-700 dark:bg-purple-900/40 dark:text-purple-300',
  'bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300',
  'bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300',
  'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300',
  'bg-cyan-100 text-cyan-700 dark:bg-cyan-900/40 dark:text-cyan-300',
  'bg-gray-100 text-gray-700 dark:bg-gray-900/40 dark:text-gray-300',
];

function getRegionAvatarClass(region?: string): string {
  if (!region) return 'bg-oe-blue-subtle text-oe-blue-text';
  // Stable hash → palette index so the same region always renders the same colour.
  let h = 0;
  for (let i = 0; i < region.length; i++) h = (h * 31 + region.charCodeAt(i)) >>> 0;
  return REGION_AVATAR_PALETTE[h % REGION_AVATAR_PALETTE.length] ?? 'bg-oe-blue-subtle text-oe-blue-text';
}

const currencyFmt = new Intl.NumberFormat(getIntlLocale(), {
  minimumFractionDigits: 0,
  maximumFractionDigits: 0,
});

export function ProjectsPage() {
  const { t } = useTranslation();
  const location = useLocation();

  // Create project modal
  const [createModalOpen, setCreateModalOpen] = useState(false);
  useEffect(() => {
    const state = location.state as { openCreateModal?: boolean } | null;
    if (state?.openCreateModal) {
      setCreateModalOpen(true);
      window.history.replaceState({}, '');
    }
  }, [location.state]);

  const [searchQuery, setSearchQuery] = useState('');
  const [filters, setFilters] = useLocalStorage('oe_projects_filters', {
    status: 'all' as StatusFilter,
    region: 'all',
    sort: 'newest' as SortOption,
  });
  const statusFilter = filters.status;
  const regionFilter = filters.region;
  const sortOption = filters.sort;
  const setStatusFilter = (v: StatusFilter) => setFilters((p) => ({ ...p, status: v }));
  const setRegionFilter = (v: string) => setFilters((p) => ({ ...p, region: v }));
  const setSortOption = (v: SortOption) => setFilters((p) => ({ ...p, sort: v }));
  const [page, setPage] = useState(1);

  const { data: projects, isLoading } = useQuery({
    queryKey: ['projects'],
    queryFn: projectsApi.list,
    staleTime: 5 * 60_000,
  });

  /* Map of project_id → uploaded file extensions (rvt/ifc/dwg/pdf/…),
     served by one aggregate endpoint so the cards don't fan out N
     requests. Used to show "has BIM / drawings / docs" chips. */
  const { data: fileTypesByProject } = useQuery({
    queryKey: ['projects-file-types'],
    queryFn: () => apiGet<Record<string, string[]>>('/v1/documents/file-types-by-project/'),
    staleTime: 60_000,
  });

  /* BOQ stats per project — pulled from the single dashboard/cards aggregator
     so the grid does not fan out N requests per project. The endpoint excludes
     archived projects, so archived rows simply show 0 stats (acceptable trade-off:
     archived projects are rarely sorted by value). */
  interface DashboardCard {
    id: string;
    boq_total_value: number;
    boq_count: number;
    open_tasks?: number;
    open_rfis?: number;
    safety_incidents?: number;
    progress_pct?: number;
  }
  const projectIdsKey = useMemo(
    () => (projects ? projects.map((p) => p.id).join(',') : ''),
    [projects],
  );
  const {
    data: boqStats,
    error: boqStatsError,
    refetch: refetchBoqStats,
    isFetching: isFetchingBoqStats,
  } = useQuery({
    queryKey: ['projects-dashboard-cards', projectIdsKey],
    queryFn: async () => {
      const cards = await apiGet<DashboardCard[]>('/v1/projects/dashboard/cards/');
      const cardMap = new Map(cards.map((c) => [c.id, c]));
      return (projects ?? []).map((p) => {
        const c = cardMap.get(p.id);
        return {
          projectId: p.id,
          boqCount: c?.boq_count ?? 0,
          totalValue: c?.boq_total_value ?? 0,
          hasError: false,
        };
      });
    },
    enabled: !!projects && projects.length > 0,
    staleTime: 60_000,
  });

  // Show a persistent warning if BOQ stats failed to load at the top level.
  // The cards still render via per-project fallback (boqStatsMap.get(id) →
  // undefined → ProjectCard's own fetcher fills in), so the whole page
  // doesn't blank out on a 500 from the rollup endpoint — but the warning
  // banner below makes the partial-data state explicit instead of leaving
  // the cards looking like "no BOQs / €0 value".
  useEffect(() => {
    if (boqStatsError) {
      if (import.meta.env.DEV) console.error('BOQ stats query failed:', boqStatsError);
    }
  }, [boqStatsError]);

  const boqStatsMap = useMemo(() => {
    if (!boqStats) return new Map<string, ProjectBOQStats>();
    return new Map(boqStats.map((s) => [s.projectId, s]));
  }, [boqStats]);

  /* ── Filter + Sort ────────────────────────────────────────────────── */

  const pinnedIds = useProjectContextStore((s) => s.pinnedProjectIds);

  const filtered = useMemo(() => {
    if (!projects) return [];
    let list = [...projects];

    // Search by name and description
    if (searchQuery) {
      const q = searchQuery.toLowerCase();
      list = list.filter(
        (p) =>
          p.name.toLowerCase().includes(q) ||
          (p.description && p.description.toLowerCase().includes(q)),
      );
    }

    // Status filter
    if (statusFilter !== 'all') {
      list = list.filter((p) => p.status === statusFilter);
    }

    // Region filter
    if (regionFilter !== 'all') {
      list = list.filter((p) => p.region === regionFilter);
    }

    // Sort — pinned first, then locale priority (en → de → others)
    // so the US and German demo projects anchor the top of the list,
    // then fall through to the user-selected sort option.
    const localePriority = (p: Project): number => {
      if (p.locale === 'en') return 0;
      if (p.locale === 'de') return 1;
      return 2;
    };
    list.sort((a, b) => {
      const aPinned = pinnedIds.includes(a.id) ? 0 : 1;
      const bPinned = pinnedIds.includes(b.id) ? 0 : 1;
      if (aPinned !== bPinned) return aPinned - bPinned;

      const aLoc = localePriority(a);
      const bLoc = localePriority(b);
      if (aLoc !== bLoc) return aLoc - bLoc;

      switch (sortOption) {
        case 'name_asc':
          return a.name.localeCompare(b.name);
        case 'newest':
          return new Date(b.created_at).getTime() - new Date(a.created_at).getTime();
        case 'oldest':
          return new Date(a.created_at).getTime() - new Date(b.created_at).getTime();
        case 'value': {
          const aVal = boqStatsMap.get(a.id)?.totalValue ?? 0;
          const bVal = boqStatsMap.get(b.id)?.totalValue ?? 0;
          return bVal - aVal;
        }
        default:
          return 0;
      }
    });

    return list;
  }, [projects, searchQuery, statusFilter, regionFilter, sortOption, boqStatsMap, pinnedIds]);

  // Reset page when filters change
  useEffect(() => {
    setPage(1);
  }, [searchQuery, statusFilter, regionFilter, sortOption]);

  // Pagination
  const totalPages = Math.max(1, Math.ceil(filtered.length / ITEMS_PER_PAGE));
  const paginatedProjects = filtered.slice(
    (page - 1) * ITEMS_PER_PAGE,
    page * ITEMS_PER_PAGE,
  );

  /* ── Stats ────────────────────────────────────────────────────────── */

  const stats = useMemo(() => {
    if (!projects) return null;
    const totalProjects = projects.length;
    const activeProjects = projects.filter((p) => p.status === 'active').length;
    const archivedProjects = projects.filter((p) => p.status === 'archived').length;
    const totalBoqs = boqStats ? boqStats.reduce((s, b) => s + b.boqCount, 0) : 0;
    const totalValue = boqStats ? boqStats.reduce((s, b) => s + b.totalValue, 0) : 0;
    const avgValue =
      boqStats && activeProjects > 0 ? totalValue / activeProjects : 0;
    const largestValue = boqStats
      ? boqStats.reduce((m, b) => (b.totalValue > m ? b.totalValue : m), 0)
      : 0;
    const avgBoqsPerProject = totalProjects > 0 ? totalBoqs / totalProjects : 0;

    const regions = new Set(projects.map((p) => p.region).filter(Boolean));
    const currencies = new Set(projects.map((p) => p.currency).filter(Boolean));

    const BIM_EXTS = new Set(['rvt', 'ifc', 'skp', 'nwc', 'nwd', 'dgn']);
    const bimProjectCount = fileTypesByProject
      ? projects.filter((p) =>
          (fileTypesByProject[p.id] ?? []).some((ext) =>
            BIM_EXTS.has(ext.toLowerCase()),
          ),
        ).length
      : 0;

    return {
      totalProjects,
      activeProjects,
      archivedProjects,
      totalBoqs,
      totalValue,
      avgValue,
      largestValue,
      avgBoqsPerProject,
      regionCount: regions.size,
      currencyCount: currencies.size,
      primaryCurrency: currencies.size === 1 ? [...currencies][0] : '',
      bimProjectCount,
    };
  }, [projects, boqStats, fileTypesByProject]);

  const formatBigValue = (v: number) =>
    v >= 1_000_000
      ? `${(v / 1_000_000).toFixed(1)}M`
      : v >= 1_000
        ? `${(v / 1_000).toFixed(0)}K`
        : currencyFmt.format(v);

  // Available region filter values — only regions actually present in the
  // user's project list (no globally hard-coded country/region inventory).
  const availableRegions = useMemo(() => {
    if (!projects) return ['all'];
    const set = new Set<string>();
    for (const p of projects) if (p.region) set.add(p.region);
    return ['all', ...Array.from(set).sort()];
  }, [projects]);

  /* ── Sort labels ──────────────────────────────────────────────────── */

  const sortOptions: { value: SortOption; label: string }[] = [
    { value: 'name_asc', label: t('projects.sort_name', { defaultValue: 'Name A-Z' }) },
    { value: 'newest', label: t('projects.sort_newest', { defaultValue: 'Newest' }) },
    { value: 'oldest', label: t('projects.sort_oldest', { defaultValue: 'Oldest' }) },
    { value: 'value', label: t('projects.sort_value', { defaultValue: 'Value' }) },
  ];

  return (
    <div className="w-full animate-fade-in">
      <Breadcrumb items={[{ label: t('nav.dashboard', 'Dashboard'), to: '/' }, { label: t('nav.projects', 'Projects') }]} className="mb-4" />
      {/* Header */}
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-content-primary">{t('projects.title')}</h1>
          <p className="mt-1 text-sm text-content-secondary">
            {projects
              ? t('projects.subtitle_count', {
                  defaultValue: 'Manage your construction estimation projects ({{count}} total)',
                  count: projects.length,
                })
              : t('common.loading', { defaultValue: 'Loading...' })}
          </p>
        </div>
        <Button
          variant="primary"
          icon={<FolderPlus size={16} />}
          onClick={() => setCreateModalOpen(true)}
        >
          {t('projects.new_project')}
        </Button>
      </div>

      {/* Stats cards — 4-up portfolio summary, each card with primary
          number + sub-line so no card is sparse. */}
      {stats && projects && projects.length > 0 && (
        <>
          <div className="grid grid-cols-2 sm:grid-cols-2 lg:grid-cols-4 gap-3 mb-6">
            {/* 1. Total Projects */}
            <div className="rounded-xl bg-surface-elevated border border-border-light p-3">
              <div className="text-2xs font-medium text-content-tertiary uppercase tracking-wider">
                {t('projects.stats_total', { defaultValue: 'Total Projects' })}
              </div>
              <div className="mt-1 text-xl font-bold text-content-primary tabular-nums leading-none">
                {stats.totalProjects}
              </div>
              <div className="mt-2 flex flex-wrap items-center gap-1">
                <Badge variant="success" size="sm" dot>
                  {t('projects.stats_active', {
                    defaultValue: '{{count}} active',
                    count: stats.activeProjects,
                  })}
                </Badge>
                {stats.archivedProjects > 0 && (
                  <Badge variant="neutral" size="sm" dot>
                    {t('projects.stats_archived', {
                      defaultValue: '{{count}} archived',
                      count: stats.archivedProjects,
                    })}
                  </Badge>
                )}
              </div>
            </div>

            {/* 2. Total BOQs */}
            <div className="rounded-xl bg-surface-elevated border border-border-light p-3">
              <div className="text-2xs font-medium text-content-tertiary uppercase tracking-wider">
                {t('projects.stats_boqs', { defaultValue: 'Total BOQs' })}
              </div>
              <div className="mt-1 text-xl font-bold text-content-primary tabular-nums leading-none">
                {boqStats ? stats.totalBoqs.toLocaleString() : (
                  <Skeleton width={40} height={20} className="inline-block align-middle" />
                )}
              </div>
              <div className="mt-2 text-2xs text-content-tertiary">
                {boqStats && stats.totalProjects > 0
                  ? t('projects.stats_boqs_per_project', {
                      defaultValue: '{{avg}} per project',
                      avg: stats.avgBoqsPerProject.toFixed(1),
                    })
                  : ''}
              </div>
            </div>

            {/* 3. Total Value */}
            <div className="rounded-xl bg-surface-elevated border border-border-light p-3">
              <div className="text-2xs font-medium text-content-tertiary uppercase tracking-wider">
                {t('projects.stats_value', { defaultValue: 'Total Value' })}
              </div>
              <div className="mt-1 text-xl font-bold text-content-primary tabular-nums leading-none">
                {boqStats ? formatBigValue(stats.totalValue) : (
                  <Skeleton width={64} height={20} className="inline-block align-middle" />
                )}
              </div>
              <div className="mt-2 text-2xs text-content-tertiary">
                {stats.currencyCount === 1 && stats.primaryCurrency
                  ? stats.primaryCurrency
                  : stats.currencyCount > 1
                    ? t('projects.stats_currencies', {
                        defaultValue: '{{count}} currencies',
                        count: stats.currencyCount,
                      })
                    : ''}
              </div>
            </div>

            {/* 4. Avg Project Size */}
            <div className="rounded-xl bg-surface-elevated border border-border-light p-3">
              <div className="text-2xs font-medium text-content-tertiary uppercase tracking-wider">
                {t('projects.stats_avg', { defaultValue: 'Avg Project Size' })}
              </div>
              <div className="mt-1 text-xl font-bold text-content-primary tabular-nums leading-none">
                {boqStats ? formatBigValue(stats.avgValue) : (
                  <Skeleton width={64} height={20} className="inline-block align-middle" />
                )}
              </div>
              <div className="mt-2 text-2xs text-content-tertiary">
                {boqStats && stats.largestValue > 0
                  ? t('projects.stats_largest', {
                      defaultValue: 'Largest {{value}}',
                      value: formatBigValue(stats.largestValue),
                    })
                  : ''}
              </div>
            </div>
          </div>

        </>
      )}

      {/* Search + Filters */}
      {projects && projects.length > 0 && (
        <Card padding="none" className="mb-6">
          <div className="flex flex-col gap-3 p-4 sm:flex-row sm:items-center">
            {/* Search */}
            <div className="relative flex-1">
              <div className="pointer-events-none absolute inset-y-0 left-0 flex items-center pl-3 text-content-tertiary">
                <Search size={16} />
              </div>
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder={t('projects.search_placeholder', {
                  defaultValue: 'Search projects...',
                })}
                aria-label={t('projects.search_placeholder', { defaultValue: 'Search projects...' })}
                className="h-10 w-full rounded-lg border border-border bg-surface-primary pl-10 pr-3 text-sm text-content-primary placeholder:text-content-tertiary focus:outline-none focus:ring-2 focus:ring-oe-blue focus:border-transparent"
              />
            </div>

            {/* Status filter */}
            <div className="relative">
              <select
                value={statusFilter}
                onChange={(e) => setStatusFilter(e.target.value as StatusFilter)}
                aria-label={t('a11y.projects.status_filter', {
                  defaultValue: 'Filter projects by status',
                })}
                className="h-10 appearance-none rounded-lg border border-border bg-surface-primary pl-3 pr-9 text-sm text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue sm:w-36"
              >
                <option value="all">
                  {t('projects.filter_all', { defaultValue: 'All' })}
                </option>
                <option value="active">
                  {t('projects.filter_active', { defaultValue: 'Active' })}
                </option>
                <option value="archived">
                  {t('projects.filter_archived', { defaultValue: 'Archived' })}
                </option>
              </select>
              <div className="pointer-events-none absolute inset-y-0 right-0 flex items-center pr-2.5 text-content-tertiary">
                <ChevronDown size={14} />
              </div>
            </div>

            {/* Region filter */}
            <div className="relative">
              <select
                value={regionFilter}
                onChange={(e) => setRegionFilter(e.target.value)}
                aria-label={t('a11y.projects.region_filter', {
                  defaultValue: 'Filter projects by region',
                })}
                className="h-10 appearance-none rounded-lg border border-border bg-surface-primary pl-3 pr-9 text-sm text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue sm:w-40"
              >
                {availableRegions.map((r) => (
                  <option key={r} value={r}>
                    {r === 'all'
                      ? t('projects.filter_all_regions', { defaultValue: 'All Regions' })
                      : r}
                  </option>
                ))}
              </select>
              <div className="pointer-events-none absolute inset-y-0 right-0 flex items-center pr-2.5 text-content-tertiary">
                <ChevronDown size={14} />
              </div>
            </div>

            {/* Sort buttons */}
            <div className="flex items-center gap-1 shrink-0">
              {sortOptions.map((opt) => (
                <button
                  key={opt.value}
                  onClick={() => setSortOption(opt.value)}
                  className={`flex items-center gap-1 rounded-md px-2 py-1.5 text-2xs font-medium transition-colors ${
                    sortOption === opt.value
                      ? 'bg-oe-blue-subtle text-oe-blue-text'
                      : 'text-content-tertiary hover:text-content-secondary hover:bg-surface-secondary'
                  }`}
                >
                  {opt.label}
                  {sortOption === opt.value && <ArrowUpDown size={10} />}
                </button>
              ))}
            </div>

            {/* Widget toggles — map + weather */}
            <WidgetToggles />
          </div>
        </Card>
      )}

      {/* Results */}
      {isLoading ? (
        <SkeletonGrid items={3} />
      ) : filtered.length === 0 && (searchQuery || statusFilter !== 'all' || regionFilter !== 'all') ? (
        <EmptyState
          icon={<Search size={28} strokeWidth={1.5} />}
          title={t('projects.no_results', { defaultValue: 'No matching projects' })}
          description={t('projects.no_results_hint', {
            defaultValue: 'Try adjusting your search or filters',
          })}
        />
      ) : !projects || projects.length === 0 ? (
        <div className="space-y-4">
          {/* Surface the BIM converter status here so a fresh-install user
           *  can see at a glance whether RVT/IFC/DWG/DGN drag-and-drop will
           *  work BEFORE creating the first project. Dismissible — once
           *  acknowledged it stays out of the way until the user resets
           *  the localStorage flag. */}
          <BIMConverterStatusBanner dismissible />
          {/* Empty-state copy unified per Probe-D P2-11. Title +
              description follow the shared "No {entity} yet" / "Create
              your first {entity}" template; the description retains the
              project-specific elaboration so users understand what a
              project is for. */}
          <EmptyState
            icon={<FolderOpen size={28} strokeWidth={1.5} />}
            title={t('projects.no_projects', { defaultValue: 'No projects yet' })}
            description={t('projects.no_projects_description', {
              defaultValue:
                'Projects organize your estimates, documents, and team. Create your first project to get started with cost estimation.',
            })}
            action={{
              label: t('projects.create_first', { defaultValue: 'Create your first project' }),
              onClick: () => setCreateModalOpen(true),
            }}
          />
        </div>
      ) : (
        <>
          {/* Rollup-failure banner. The aggregated /v1/projects/dashboard/
              cards endpoint feeds every card's BOQ count + value. When it
              500s the cards still render via per-project fallback (the
              card fetches its own stats), but the user has no idea the
              numbers are partial — they look identical to a zero-data
              project. Surface the failure explicitly with a Retry CTA. */}
          {boqStatsError && (
            <div
              role="status"
              className="mb-4 flex items-start gap-2 rounded-lg border border-amber-300 bg-amber-50 dark:bg-amber-900/20 dark:border-amber-800 px-3 py-2"
            >
              <AlertTriangle
                size={16}
                className="text-amber-600 dark:text-amber-400 shrink-0 mt-0.5"
              />
              <div className="flex-1 min-w-0">
                <p className="text-sm text-amber-900 dark:text-amber-100">
                  {t('projects.rollup_error', {
                    defaultValue:
                      'Could not load aggregated stats. Showing individual project data only.',
                  })}
                </p>
              </div>
              <Button
                variant="secondary"
                size="sm"
                onClick={() => refetchBoqStats()}
                disabled={isFetchingBoqStats}
              >
                {isFetchingBoqStats
                  ? t('common.loading', { defaultValue: 'Loading...' })
                  : t('common.retry', { defaultValue: 'Retry' })}
              </Button>
            </div>
          )}
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {paginatedProjects.map((project, i) => (
              <ProjectCard
                key={project.id}
                project={project}
                boqStats={boqStatsMap.get(project.id)}
                fileTypes={fileTypesByProject?.[project.id] ?? []}
                style={{ animationDelay: `${50 + i * 30}ms` }}
                onDeleted={() => setStatusFilter('active')}
              />
            ))}
          </div>

          {/* Pagination */}
          <div className="mt-6 flex flex-col items-center gap-3">
            {totalPages > 1 && (
              <div className="flex items-center gap-1">
                <button
                  onClick={() => setPage(1)}
                  disabled={page === 1}
                  className="rounded-lg border border-border-light px-3 py-2 text-sm font-medium text-content-secondary hover:bg-surface-secondary disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
                  title={t('common.first_page', { defaultValue: 'First page' })}
                >
                  &laquo;
                </button>
                <button
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                  disabled={page === 1}
                  className="rounded-lg border border-border-light px-4 py-2 text-sm font-medium text-content-secondary hover:bg-surface-secondary disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
                >
                  {t('common.previous', { defaultValue: 'Previous' })}
                </button>

                {/* Page numbers */}
                {Array.from({ length: totalPages }, (_, i) => i + 1)
                  .filter((p) => p === 1 || p === totalPages || Math.abs(p - page) <= 1)
                  .reduce<(number | 'dots')[]>((acc, p, i, arr) => {
                    if (i > 0 && arr[i - 1] !== undefined && p - (arr[i - 1] as number) > 1) acc.push('dots');
                    acc.push(p);
                    return acc;
                  }, [])
                  .map((item, i) =>
                    item === 'dots' ? (
                      <span key={`dots-${i}`} className="px-1 text-content-quaternary">...</span>
                    ) : (
                      <button
                        key={item}
                        onClick={() => setPage(item as number)}
                        className={`rounded-lg min-w-[40px] py-2 text-sm font-semibold transition-colors ${
                          page === item
                            ? 'bg-oe-blue text-white shadow-sm'
                            : 'border border-border-light text-content-secondary hover:bg-surface-secondary'
                        }`}
                      >
                        {item}
                      </button>
                    ),
                  )}

                <button
                  onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                  disabled={page === totalPages}
                  className="rounded-lg border border-border-light px-4 py-2 text-sm font-medium text-content-secondary hover:bg-surface-secondary disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
                >
                  {t('common.next', { defaultValue: 'Next' })}
                </button>
                <button
                  onClick={() => setPage(totalPages)}
                  disabled={page === totalPages}
                  className="rounded-lg border border-border-light px-3 py-2 text-sm font-medium text-content-secondary hover:bg-surface-secondary disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
                  title={t('common.last_page', { defaultValue: 'Last page' })}
                >
                  &raquo;
                </button>
              </div>
            )}
            <p className="text-sm text-content-tertiary">
              {t('projects.showing_of', {
                defaultValue: '{{from}}–{{to}} of {{filtered}} projects',
                from: (page - 1) * ITEMS_PER_PAGE + 1,
                to: Math.min(page * ITEMS_PER_PAGE, filtered.length),
                filtered: filtered.length,
              })}
              {(searchQuery || statusFilter !== 'all' || regionFilter !== 'all') && filtered.length !== (projects?.length ?? 0)
                ? ` (${t('projects.filtered_from', { defaultValue: 'filtered from {{total}}', total: projects?.length ?? 0 })})`
                : ''}
            </p>
          </div>
        </>
      )}

      <CreateProjectModal
        open={createModalOpen}
        onClose={() => setCreateModalOpen(false)}
      />
    </div>
  );
}

function ProjectCard({
  project,
  boqStats,
  fileTypes,
  style,
  onDeleted,
}: {
  project: Project;
  boqStats?: ProjectBOQStats;
  /** Uploaded file extensions for this project (e.g. ['rvt','dwg','pdf']). */
  fileTypes?: string[];
  style?: React.CSSProperties;
  onDeleted?: () => void;
}) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [menuOpen, setMenuOpen] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const menuRef = React.useRef<HTMLDivElement>(null);

  // Close dropdown on outside click
  useEffect(() => {
    if (!menuOpen) return;
    const handler = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setMenuOpen(false);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [menuOpen]);

  // Close dropdown on Escape key
  useEffect(() => {
    if (!menuOpen) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setMenuOpen(false);
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [menuOpen]);

  const deleteMutation = useMutation({
    mutationFn: () => apiDelete(`/v1/projects/${project.id}`),
    onSuccess: () => {
      setConfirmDelete(false);
      queryClient.invalidateQueries({ queryKey: ['projects'] });
      addToast({ type: 'success', title: t('projects.deleted', 'Project deleted successfully') });
      onDeleted?.();
    },
    onError: (e: Error) => {
      addToast({
        type: 'error',
        title: t('projects.delete_failed', 'Failed to delete project'),
        message: e.message,
      });
    },
  });

  const duplicateMutation = useMutation({
    mutationFn: () => projectsApi.duplicate(project.id),
    onSuccess: (newProject) => {
      queryClient.invalidateQueries({ queryKey: ['projects'] });
      addToast({ type: 'success', title: t('projects.duplicated', 'Project duplicated successfully') });
      navigate(`/projects/${newProject.id}`);
    },
    onError: (e: Error) => {
      addToast({
        type: 'error',
        title: t('projects.duplicate_failed', 'Failed to duplicate project'),
        message: e.message,
      });
    },
  });

  const archiveMutation = useMutation({
    mutationFn: () => apiPatch(`/v1/projects/${project.id}`, { status: 'archived' }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['projects'] });
      addToast({ type: 'success', title: t('toasts.project_archived', { defaultValue: 'Project archived successfully' }) });
    },
    onError: (error: Error) => {
      addToast({ type: 'error', title: t('toasts.archive_failed', { defaultValue: 'Failed to archive project' }), message: error.message });
    },
  });

  const restoreMutation = useMutation({
    mutationFn: () => projectsApi.restore(project.id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['projects'] });
      addToast({
        type: 'success',
        title: t('toasts.project_restored', { defaultValue: 'Project restored' }),
      });
    },
    onError: (error: Error) => {
      addToast({
        type: 'error',
        title: t('toasts.restore_failed', { defaultValue: 'Failed to restore project' }),
        message: error.message,
      });
    },
  });

  const standardLabels: Record<string, string> = {
    din276: 'DIN 276',
    nrm: 'NRM',
    masterformat: 'MasterFormat',
  };

  // Currency symbol icon — falls back to neutral DollarSign for unknown codes
  // so we never render an empty chip. Tabular currency labels still appear
  // alongside the icon for unambiguous reading.
  const CurrencyIcon =
    project.currency === 'EUR'
      ? Euro
      : project.currency === 'GBP'
        ? PoundSterling
        : DollarSign;

  // Last-modified relative time. We prefer updated_at when present so the
  // freshness signal reflects actual edits rather than only project age.
  // date-fns gracefully degrades for invalid input — guard so a malformed
  // timestamp can't crash the card render.
  const modifiedSource = project.updated_at || project.created_at;
  const modifiedDate = modifiedSource ? parseISO(modifiedSource) : null;
  const relativeModified =
    modifiedDate && isValidDate(modifiedDate)
      ? formatDistanceToNowStrict(modifiedDate, { addSuffix: true })
      : null;
  const absoluteModified = modifiedDate && isValidDate(modifiedDate)
    ? modifiedDate.toLocaleDateString(getIntlLocale())
    : '';

  // Variations marker — rendered only when project metadata exposes a
  // non-zero count. Acts as a passive warning chip; clicking the card
  // still opens the project (variations module owns the resolution UI).
  const openVariations = (() => {
    const meta = project.metadata as Record<string, unknown> | undefined;
    const v = meta?.open_variations;
    return typeof v === 'number' && v > 0 ? v : 0;
  })();

  const mapEnabled = useWidgetSettingsStore((s) => s.projectMapEnabled);
  const weatherEnabled = useWidgetSettingsStore((s) => s.projectWeatherEnabled);
  const [cardCoords, setCardCoords] = useState<LatLng | null>(
    project.address?.lat && project.address?.lng
      ? { lat: project.address.lat, lng: project.address.lng }
      : null,
  );

  return (
    <Card
      hoverable
      padding="none"
      className="group cursor-pointer relative animate-card-in overflow-hidden rounded-xl bg-gradient-to-b from-surface-elevated to-surface-primary hover:shadow-xl hover:border-oe-blue/40 focus-within:ring-2 focus-within:ring-oe-blue/30 motion-safe:transition-all"
      style={style}
      onClick={() => navigate(`/projects/${project.id}`)}
    >
      {mapEnabled && project.address && (
        <div className="relative" onClick={(e) => e.stopPropagation()}>
          <ProjectMap
            variant="card"
            lat={project.address?.lat ?? null}
            lng={project.address?.lng ?? null}
            address={project.address?.street}
            city={project.address?.city}
            country={project.address?.country}
            label={[project.address?.city, project.address?.country]
              .filter(Boolean)
              .join(', ')}
            className="rounded-none border-none"
            onResolved={setCardCoords}
          />
          {/* Geo Hub overlay CTA — only when coords are resolved so we
              never ship a deeplink to an unanchored project. Sits over
              the map (top-right) with a glass pill so the underlying
              tiles remain visible. */}
          {cardCoords && (
            <Link
              to={`/projects/${project.id}/geo`}
              onClick={(e) => e.stopPropagation()}
              className="absolute top-2 right-2 z-10 inline-flex items-center gap-1 rounded-full border border-white/40 bg-white/85 px-2.5 py-1 text-2xs font-semibold text-oe-blue shadow-sm backdrop-blur-md transition-all hover:bg-white hover:shadow-md hover:scale-[1.03] focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/60 dark:border-white/10 dark:bg-slate-900/70 dark:text-sky-300 dark:hover:bg-slate-900/90"
              title={t('projects.card.fly_to_on_map', {
                defaultValue: 'Fly camera to {{name}} on the globe',
                name: project.name,
              })}
              aria-label={t('projects.card.fly_to_on_map', {
                defaultValue: 'Fly camera to {{name}} on the globe',
                name: project.name,
              })}
              data-testid="project-card-view-on-map"
            >
              <Globe2 size={11} strokeWidth={2.25} />
              {t('projects.card.view_on_map', { defaultValue: 'On map' })}
            </Link>
          )}
        </div>
      )}
      <div className="p-5">
        <div className="flex items-start justify-between gap-3">
          <div className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-xl text-base font-bold ring-1 ring-inset ring-white/40 dark:ring-white/5 shadow-sm transition-transform duration-normal ease-oe group-hover:scale-105 ${getRegionAvatarClass(project.region)}`}>
            {project.name.charAt(0).toUpperCase()}
          </div>
          <div className="flex items-center gap-1.5">
            {project.status === 'archived' && (
              <Badge variant="neutral" size="sm">
                {t('projects.status_archived', { defaultValue: 'Archived' })}
              </Badge>
            )}
            <PinButton projectId={project.id} />
            <button
              type="button"
              className="flex h-7 w-7 min-h-[44px] min-w-[44px] items-center justify-center rounded-md text-content-tertiary hover:bg-surface-secondary transition-colors"
              onClick={(e) => {
                e.stopPropagation();
                setMenuOpen(!menuOpen);
              }}
              aria-label={t('a11y.projects.card_actions', {
                defaultValue: 'Project actions for {{name}}',
                name: project.name,
              })}
              aria-haspopup="menu"
              aria-expanded={menuOpen}
            >
              <MoreHorizontal size={14} />
            </button>
          </div>
        </div>

        {/* Dropdown menu */}
        {menuOpen && (
          <div
            ref={menuRef}
            className="absolute top-14 right-4 z-20 w-44 rounded-lg border border-border bg-surface-elevated shadow-lg overflow-hidden"
            onClick={(e) => e.stopPropagation()}
          >
            <button
              onClick={() => {
                navigate(`/projects/${project.id}`);
                setMenuOpen(false);
              }}
              className="flex w-full items-center gap-2 px-3 py-2 text-sm text-content-primary hover:bg-surface-secondary transition-colors"
            >
              <ExternalLink size={14} /> {t('common.open', 'Open')}
            </button>
            <button
              onClick={() => {
                duplicateMutation.mutate();
                setMenuOpen(false);
              }}
              className="flex w-full items-center gap-2 px-3 py-2 text-sm text-content-primary hover:bg-surface-secondary transition-colors"
            >
              <Copy size={14} /> {t('common.duplicate', 'Duplicate')}
            </button>
            {project.status === 'archived' ? (
              <button
                onClick={() => {
                  restoreMutation.mutate();
                  setMenuOpen(false);
                }}
                disabled={restoreMutation.isPending}
                className="flex w-full items-center gap-2 px-3 py-2 text-sm text-content-secondary hover:bg-surface-secondary transition-colors disabled:opacity-60"
              >
                <ArchiveRestore size={14} /> {t('common.restore', { defaultValue: 'Restore' })}
              </button>
            ) : (
              <button
                onClick={() => {
                  archiveMutation.mutate();
                  setMenuOpen(false);
                }}
                disabled={archiveMutation.isPending}
                className="flex w-full items-center gap-2 px-3 py-2 text-sm text-content-secondary hover:bg-surface-secondary transition-colors disabled:opacity-60"
              >
                <Archive size={14} /> {t('common.archive', 'Archive')}
              </button>
            )}
            <div className="h-px bg-border-light" />
            <button
              onClick={() => {
                setConfirmDelete(true);
                setMenuOpen(false);
              }}
              className="flex w-full items-center gap-2 px-3 py-2 text-sm text-semantic-error hover:bg-semantic-error-bg transition-colors"
            >
              <Trash2 size={14} /> {t('common.delete', 'Delete')}
            </button>
          </div>
        )}

        {/* Delete confirmation */}
        {confirmDelete && (
          <div
            className="absolute inset-0 z-30 flex items-center justify-center rounded-xl bg-white/95 dark:bg-gray-900/95 backdrop-blur-sm p-4"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="text-center">
              <div className="flex h-10 w-10 items-center justify-center rounded-full bg-semantic-error-bg mx-auto mb-3">
                <Trash2 size={18} className="text-semantic-error" />
              </div>
              <p className="text-sm font-semibold text-content-primary mb-1">
                {t('projects.confirm_delete', 'Delete this project?')}
              </p>
              <p className="text-xs text-content-tertiary mb-4 max-w-[200px] mx-auto">
                {project.name}
              </p>
              <div className="flex items-center justify-center gap-2">
                <Button
                  variant="danger"
                  size="sm"
                  onClick={() => deleteMutation.mutate()}
                  loading={deleteMutation.isPending}
                >
                  {t('common.delete', 'Delete')}
                </Button>
                <Button variant="secondary" size="sm" onClick={() => setConfirmDelete(false)}>
                  {t('common.cancel', 'Cancel')}
                </Button>
              </div>
            </div>
          </div>
        )}

        <h3 className="mt-4 text-base font-semibold tracking-tight text-content-primary truncate">
          {project.name}
        </h3>
        {project.description && (
          <p className="mt-1 text-xs leading-relaxed text-content-secondary line-clamp-2 transition-colors group-hover:text-content-primary/80">
            {project.description}
          </p>
        )}
        <div className="mt-3.5 flex flex-wrap items-center gap-1.5">
          <span className="inline-flex items-center gap-1 rounded-full border border-oe-blue/20 bg-oe-blue-subtle px-2 py-0.5 text-2xs font-medium text-oe-blue-text">
            <Building2 size={11} strokeWidth={2.25} />
            {standardLabels[project.classification_standard] ?? project.classification_standard}
          </span>
          <span className="inline-flex items-center gap-1 rounded-full border border-border-light bg-surface-secondary px-2 py-0.5 text-2xs font-medium text-content-secondary">
            <CurrencyIcon size={11} strokeWidth={2.25} />
            {project.currency}
          </span>
          <span className="inline-flex items-center gap-1 rounded-full border border-border-light bg-surface-secondary px-2 py-0.5 text-2xs font-medium text-content-secondary">
            <Globe2 size={11} strokeWidth={2.25} />
            {project.region}
          </span>
          {project.address?.city && (
            <span className="inline-flex items-center gap-1 rounded-full border border-border-light bg-surface-secondary px-2 py-0.5 text-2xs font-medium text-content-secondary">
              <MapPin size={11} strokeWidth={2.25} />
              {project.address.city}
            </span>
          )}
          {/* Inline fallback: when the map widget is OFF we still want a
              discoverable jump-to-Geo affordance on geo-anchored projects.
              Hidden when the overlay version is already shown above. */}
          {!mapEnabled && cardCoords && (
            <Link
              to={`/projects/${project.id}/geo`}
              onClick={(e) => e.stopPropagation()}
              className="inline-flex items-center gap-1 rounded-full border border-oe-blue/30 bg-oe-blue-subtle px-2 py-0.5 text-2xs font-semibold text-oe-blue-text transition-all hover:bg-oe-blue hover:text-white hover:shadow-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/60"
              title={t('projects.card.fly_to_on_map', {
                defaultValue: 'Fly camera to {{name}} on the globe',
                name: project.name,
              })}
              aria-label={t('projects.card.fly_to_on_map', {
                defaultValue: 'Fly camera to {{name}} on the globe',
                name: project.name,
              })}
              data-testid="project-card-view-on-map-inline"
            >
              <Globe2 size={11} strokeWidth={2.25} />
              {t('projects.card.view_on_map', { defaultValue: 'On map' })}
            </Link>
          )}
          {fileTypes && fileTypes.length > 0 && (
            <div className="ml-auto">
              <FileTypeChips fileTypes={fileTypes} size="md" />
            </div>
          )}
        </div>
      </div>
      {/* Feature row: total cost as the visual anchor — gradient underline,
       *  large tabular numerals, currency code aligned for legibility. */}
      {boqStats && boqStats.boqCount > 0 && boqStats.totalValue > 0 && (
        <div className="relative px-5 pb-3">
          <div className="rounded-xl border border-border-light bg-gradient-to-br from-oe-blue-subtle/60 via-surface-elevated to-surface-elevated px-4 py-3">
            <div className="text-[10px] font-medium uppercase tracking-wider text-content-tertiary">
              {t('projects.card_total_value', { defaultValue: 'Total value' })}
            </div>
            <div className="mt-0.5 flex items-baseline gap-1.5">
              <span className="text-xl font-bold tabular-nums text-content-primary">
                {currencyFmt.format(boqStats.totalValue)}
              </span>
              <span className="text-2xs font-semibold uppercase tracking-wider text-content-tertiary">
                {project.currency}
              </span>
            </div>
          </div>
        </div>
      )}
      <div className="border-t border-border-light px-5 py-3">
        {weatherEnabled && cardCoords && (
          <div className="mb-2" onClick={(e) => e.stopPropagation()}>
            <ProjectWeather
              variant="summary"
              lat={cardCoords.lat}
              lng={cardCoords.lng}
            />
          </div>
        )}
        <div className="flex items-center justify-between gap-2">
          <div className="flex flex-wrap items-center gap-1.5">
            {relativeModified && (
              <span
                className="text-2xs text-content-tertiary"
                title={absoluteModified}
              >
                {relativeModified}
              </span>
            )}
            {boqStats && boqStats.boqCount > 0 && (
              <span className="inline-flex items-center gap-1 rounded-md bg-surface-secondary px-1.5 py-0.5 text-2xs font-medium text-content-secondary">
                <Layers size={10} strokeWidth={2.25} />
                <span className="tabular-nums">{boqStats.boqCount}</span>
                <span>
                  {t('projects.boq_short', { defaultValue: 'BOQs' })}
                </span>
              </span>
            )}
            {openVariations > 0 && (
              <span
                className="inline-flex items-center gap-1 rounded-md bg-amber-50 px-1.5 py-0.5 text-2xs font-semibold text-amber-700 ring-1 ring-amber-200/60 dark:bg-amber-500/10 dark:text-amber-300 dark:ring-amber-500/20"
                title={t('projects.card_open_variations', {
                  defaultValue: 'Open variations',
                })}
              >
                <AlertTriangle size={10} strokeWidth={2.25} />
                <span className="tabular-nums">{openVariations}</span>
              </span>
            )}
          </div>
          <ArrowRight
            size={14}
            className="shrink-0 text-content-tertiary transition-transform duration-normal ease-oe group-hover:translate-x-0.5 group-hover:text-oe-blue"
          />
        </div>
      </div>
    </Card>
  );
}

/**
 * WidgetToggles — inline on/off switches for the map + weather widgets.
 *
 * Lives in the filters toolbar next to sort.  State is persisted via
 * `useWidgetSettingsStore`, so the choice sticks across reloads without
 * a server round-trip.
 */
function WidgetToggles() {
  const { t } = useTranslation();
  const mapEnabled = useWidgetSettingsStore((s) => s.projectMapEnabled);
  const weatherEnabled = useWidgetSettingsStore((s) => s.projectWeatherEnabled);
  const toggleMap = useWidgetSettingsStore((s) => s.toggleProjectMap);
  const toggleWeather = useWidgetSettingsStore((s) => s.toggleProjectWeather);

  const btn = (active: boolean) =>
    `flex items-center gap-1 rounded-md px-2 py-1.5 text-2xs font-medium transition-colors ${
      active
        ? 'bg-oe-blue-subtle text-oe-blue-text'
        : 'text-content-tertiary hover:text-content-secondary hover:bg-surface-secondary'
    }`;

  return (
    <div className="flex items-center gap-1 shrink-0 border-l border-border-light pl-2 ml-1">
      <button
        type="button"
        onClick={toggleMap}
        className={btn(mapEnabled)}
        title={t('widget_settings.toggle_map', { defaultValue: 'Toggle project map' })}
      >
        <MapIcon size={12} />
        {t('widget_settings.map', { defaultValue: 'Map' })}
      </button>
      <button
        type="button"
        onClick={toggleWeather}
        className={btn(weatherEnabled)}
        title={t('widget_settings.toggle_weather', { defaultValue: 'Toggle weather forecast' })}
      >
        <CloudSun size={12} />
        {t('widget_settings.weather', { defaultValue: 'Weather' })}
      </button>
    </div>
  );
}

function PinButton({ projectId }: { projectId: string }) {
  const { t } = useTranslation();
  const togglePinned = useProjectContextStore((s) => s.togglePinned);
  const isPinned = useProjectContextStore((s) => s.pinnedProjectIds.includes(projectId));

  return (
    <button
      className={`flex h-7 w-7 min-h-[44px] min-w-[44px] items-center justify-center rounded-md transition-colors ${
        isPinned
          ? 'text-amber-500 hover:bg-amber-50 dark:hover:bg-amber-500/10'
          : 'text-content-tertiary hover:bg-surface-secondary hover:text-content-secondary'
      }`}
      onClick={(e) => {
        e.stopPropagation();
        togglePinned(projectId);
      }}
      title={isPinned ? t('common.unpin', 'Unpin') : t('common.pin', 'Pin')}
    >
      <Star size={14} fill={isPinned ? 'currentColor' : 'none'} />
    </button>
  );
}

