import React, { useState, useMemo, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import {
  FolderPlus, FolderOpen, ArrowRight, MoreHorizontal, Copy, Trash2, Archive, ExternalLink,
  Search, ChevronDown, ArrowUpDown, Star,
} from 'lucide-react';
import { Button, Card, Badge, EmptyState, SkeletonGrid } from '@/shared/ui';
import { getIntlLocale } from '@/shared/lib/formatters';
import { projectsApi, type Project } from './api';
import { apiGet, apiPost, apiPatch, apiDelete } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { type BOQWithPositions } from '../boq/api';

interface BOQBasic {
  id: string;
  project_id: string;
  name: string;
  status: string;
  created_at: string;
}

interface ProjectBOQStats {
  projectId: string;
  boqCount: number;
  totalValue: number;
}

type SortOption = 'name_asc' | 'newest' | 'oldest' | 'value';
type StatusFilter = 'all' | 'active' | 'archived';

const currencyFmt = new Intl.NumberFormat(getIntlLocale(), {
  minimumFractionDigits: 0,
  maximumFractionDigits: 0,
});

export function ProjectsPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();

  const [searchQuery, setSearchQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all');
  const [sortOption, setSortOption] = useState<SortOption>('newest');

  const { data: projects, isLoading } = useQuery({
    queryKey: ['projects'],
    queryFn: projectsApi.list,
  });

  /* Fetch BOQ stats for all projects (count + total value) */
  const { data: boqStats } = useQuery({
    queryKey: ['projects-boq-stats', projects],
    queryFn: async () => {
      if (!projects || projects.length === 0) return [];
      const results: ProjectBOQStats[] = [];
      for (const p of projects) {
        try {
          const boqs = await apiGet<BOQBasic[]>(`/v1/boq/boqs/?project_id=${p.id}`);
          let totalValue = 0;
          for (const b of boqs) {
            try {
              const full = await apiGet<BOQWithPositions>(`/v1/boq/boqs/${b.id}`);
              totalValue += full.grand_total;
            } catch { /* ignore */ }
          }
          results.push({ projectId: p.id, boqCount: boqs.length, totalValue });
        } catch {
          results.push({ projectId: p.id, boqCount: 0, totalValue: 0 });
        }
      }
      return results;
    },
    enabled: !!projects && projects.length > 0,
  });

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

    // Sort — pinned first, then by selected sort option
    list.sort((a, b) => {
      const aPinned = pinnedIds.includes(a.id) ? 0 : 1;
      const bPinned = pinnedIds.includes(b.id) ? 0 : 1;
      if (aPinned !== bPinned) return aPinned - bPinned;

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
  }, [projects, searchQuery, statusFilter, sortOption, boqStatsMap, pinnedIds]);

  /* ── Stats ────────────────────────────────────────────────────────── */

  const stats = useMemo(() => {
    if (!projects) return null;
    const totalProjects = projects.length;
    const activeProjects = projects.filter((p) => p.status === 'active').length;
    const archivedProjects = projects.filter((p) => p.status === 'archived').length;
    const totalBoqs = boqStats ? boqStats.reduce((s, b) => s + b.boqCount, 0) : 0;
    const totalValue = boqStats ? boqStats.reduce((s, b) => s + b.totalValue, 0) : 0;
    return { totalProjects, activeProjects, archivedProjects, totalBoqs, totalValue };
  }, [projects, boqStats]);

  /* ── Sort labels ──────────────────────────────────────────────────── */

  const sortOptions: { value: SortOption; label: string }[] = [
    { value: 'name_asc', label: t('projects.sort_name', { defaultValue: 'Name A-Z' }) },
    { value: 'newest', label: t('projects.sort_newest', { defaultValue: 'Newest' }) },
    { value: 'oldest', label: t('projects.sort_oldest', { defaultValue: 'Oldest' }) },
    { value: 'value', label: t('projects.sort_value', { defaultValue: 'Value' }) },
  ];

  return (
    <div className="max-w-content mx-auto animate-fade-in">
      {/* Header */}
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-content-primary">{t('projects.title')}</h1>
          <p className="mt-1 text-sm text-content-secondary">
            {projects
              ? t('projects.subtitle_count', {
                  defaultValue: '{{count}} projects',
                  count: projects.length,
                })
              : t('common.loading', { defaultValue: 'Loading...' })}
          </p>
        </div>
        <Button
          variant="primary"
          icon={<FolderPlus size={16} />}
          onClick={() => navigate('/projects/new')}
        >
          {t('projects.new_project')}
        </Button>
      </div>

      {/* Stats cards */}
      {stats && projects && projects.length > 0 && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-6">
          <div className="rounded-xl bg-surface-elevated border border-border-light p-3">
            <div className="text-2xs font-medium text-content-tertiary uppercase tracking-wider">
              {t('projects.stats_total', { defaultValue: 'Total Projects' })}
            </div>
            <div className="mt-1 flex items-center gap-2">
              <span className="text-xl font-bold text-content-primary tabular-nums">
                {stats.totalProjects}
              </span>
              <div className="flex items-center gap-1.5">
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
          </div>
          <div className="rounded-xl bg-surface-elevated border border-border-light p-3">
            <div className="text-2xs font-medium text-content-tertiary uppercase tracking-wider">
              {t('projects.stats_boqs', { defaultValue: 'Total BOQs' })}
            </div>
            <div className="mt-1 text-xl font-bold text-content-primary tabular-nums">
              {boqStats ? stats.totalBoqs.toLocaleString() : (
                <span className="inline-block h-5 w-10 animate-pulse rounded bg-surface-tertiary" />
              )}
            </div>
          </div>
          <div className="rounded-xl bg-surface-elevated border border-border-light p-3 sm:col-span-2">
            <div className="text-2xs font-medium text-content-tertiary uppercase tracking-wider">
              {t('projects.stats_value', { defaultValue: 'Total Value' })}
            </div>
            <div className="mt-1 text-xl font-bold text-content-primary tabular-nums">
              {boqStats ? (
                stats.totalValue >= 1_000_000
                  ? `${(stats.totalValue / 1_000_000).toFixed(1)}M`
                  : stats.totalValue >= 1_000
                    ? `${(stats.totalValue / 1_000).toFixed(0)}K`
                    : currencyFmt.format(stats.totalValue)
              ) : (
                <span className="inline-block h-5 w-16 animate-pulse rounded bg-surface-tertiary" />
              )}
            </div>
          </div>
        </div>
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
                className="h-10 w-full rounded-lg border border-border bg-surface-primary pl-10 pr-3 text-sm text-content-primary placeholder:text-content-tertiary focus:outline-none focus:ring-2 focus:ring-oe-blue focus:border-transparent"
              />
            </div>

            {/* Status filter */}
            <div className="relative">
              <select
                value={statusFilter}
                onChange={(e) => setStatusFilter(e.target.value as StatusFilter)}
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

            {/* Sort buttons */}
            <div className="flex items-center gap-1 shrink-0">
              {sortOptions.map((opt) => (
                <button
                  key={opt.value}
                  onClick={() => setSortOption(opt.value)}
                  className={`flex items-center gap-1 rounded-md px-2 py-1.5 text-2xs font-medium transition-colors ${
                    sortOption === opt.value
                      ? 'bg-oe-blue-subtle text-oe-blue'
                      : 'text-content-tertiary hover:text-content-secondary hover:bg-surface-secondary'
                  }`}
                >
                  {opt.label}
                  {sortOption === opt.value && <ArrowUpDown size={10} />}
                </button>
              ))}
            </div>
          </div>
        </Card>
      )}

      {/* Results */}
      {isLoading ? (
        <SkeletonGrid items={3} />
      ) : filtered.length === 0 && (searchQuery || statusFilter !== 'all') ? (
        <EmptyState
          icon={<Search size={24} strokeWidth={1.5} />}
          title={t('projects.no_results', { defaultValue: 'No matching projects' })}
          description={t('projects.no_results_hint', {
            defaultValue: 'Try adjusting your search or filters',
          })}
        />
      ) : !projects || projects.length === 0 ? (
        <EmptyState
          icon={<FolderOpen size={24} strokeWidth={1.5} />}
          title={t('projects.no_projects', { defaultValue: 'No projects yet' })}
          description={t('projects.no_projects_description', {
            defaultValue: 'Create your first construction cost estimation project',
          })}
          action={{
            label: t('projects.new_project', { defaultValue: 'Create Project' }),
            onClick: () => navigate('/projects/new'),
          }}
        />
      ) : (
        <>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {filtered.map((project, i) => (
              <ProjectCard
                key={project.id}
                project={project}
                boqStats={boqStatsMap.get(project.id)}
                style={{ animationDelay: `${50 + i * 30}ms` }}
                onDeleted={() => setStatusFilter('active')}
              />
            ))}
          </div>

          {/* Summary footer */}
          <div className="pt-4 text-center text-xs text-content-tertiary">
            {filtered.length} {t('projects.of', { defaultValue: 'of' })}{' '}
            {projects.length} {t('projects.projects_label', { defaultValue: 'projects' })}
            {searchQuery || statusFilter !== 'all'
              ? ` (${t('projects.filtered', { defaultValue: 'filtered' })})`
              : ''}
          </div>
        </>
      )}
    </div>
  );
}

function ProjectCard({
  project,
  boqStats,
  style,
  onDeleted,
}: {
  project: Project;
  boqStats?: ProjectBOQStats;
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

  const deleteMutation = useMutation({
    mutationFn: () => apiDelete(`/v1/projects/${project.id}`),
    onSuccess: () => {
      setConfirmDelete(false);
      queryClient.invalidateQueries({ queryKey: ['projects'] });
      addToast({ type: 'success', title: t('projects.deleted', 'Project archived') });
      onDeleted?.();
    },
    onError: () => {
      addToast({
        type: 'error',
        title: t('projects.delete_failed', 'Failed to delete project'),
      });
    },
  });

  const duplicateMutation = useMutation({
    mutationFn: async () => {
      // Create a copy of the project with a new name
      return apiPost<Project>('/v1/projects/', {
        name: `${project.name} (Copy)`,
        description: project.description,
        region: project.region,
        classification_standard: project.classification_standard,
        currency: project.currency,
      });
    },
    onSuccess: (newProject) => {
      queryClient.invalidateQueries({ queryKey: ['projects'] });
      addToast({ type: 'success', title: t('projects.duplicated', 'Project duplicated') });
      navigate(`/projects/${newProject.id}`);
    },
    onError: () => {
      addToast({
        type: 'error',
        title: t('projects.duplicate_failed', 'Failed to duplicate'),
      });
    },
  });

  const archiveMutation = useMutation({
    mutationFn: () => apiPatch(`/v1/projects/${project.id}`, { status: 'archived' }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['projects'] });
      addToast({ type: 'success', title: t('toasts.project_archived', { defaultValue: 'Project archived' }) });
    },
    onError: (error: Error) => {
      addToast({ type: 'error', title: t('toasts.error', { defaultValue: 'Error' }), message: error.message });
    },
  });

  const standardLabels: Record<string, string> = {
    din276: 'DIN 276',
    nrm: 'NRM',
    masterformat: 'MasterFormat',
  };

  return (
    <Card
      hoverable
      padding="none"
      className="cursor-pointer relative animate-card-in"
      style={style}
      onClick={() => navigate(`/projects/${project.id}`)}
    >
      <div className="p-5">
        <div className="flex items-start justify-between">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-oe-blue-subtle text-oe-blue font-bold">
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
              className="flex h-7 w-7 items-center justify-center rounded-md text-content-tertiary hover:bg-surface-secondary transition-colors"
              onClick={(e) => {
                e.stopPropagation();
                setMenuOpen(!menuOpen);
              }}
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
            <button
              onClick={() => {
                archiveMutation.mutate();
                setMenuOpen(false);
              }}
              className="flex w-full items-center gap-2 px-3 py-2 text-sm text-content-secondary hover:bg-surface-secondary transition-colors"
            >
              <Archive size={14} /> {t('common.archive', 'Archive')}
            </button>
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

        <h3 className="mt-3 text-sm font-semibold text-content-primary truncate">
          {project.name}
        </h3>
        {project.description && (
          <p className="mt-1 text-xs text-content-secondary line-clamp-2">
            {project.description}
          </p>
        )}
        <div className="mt-3 flex flex-wrap items-center gap-1.5 overflow-hidden">
          <Badge variant="blue" size="sm">
            {standardLabels[project.classification_standard] ?? project.classification_standard}
          </Badge>
          <Badge variant="neutral" size="sm">
            {project.currency}
          </Badge>
          <Badge variant="neutral" size="sm">
            {project.region}
          </Badge>
        </div>
      </div>
      <div className="flex items-center justify-between border-t border-border-light px-5 py-2.5">
        <div className="flex items-center gap-3 text-2xs text-content-tertiary">
          <span>{new Date(project.created_at).toLocaleDateString(getIntlLocale())}</span>
          {boqStats && boqStats.boqCount > 0 && (
            <>
              <span>
                {t('projects.boq_count', {
                  defaultValue: '{{count}} BOQs',
                  count: boqStats.boqCount,
                })}
              </span>
              {boqStats.totalValue > 0 && (
                <span className="font-medium text-content-secondary tabular-nums">
                  {currencyFmt.format(boqStats.totalValue)} {project.currency}
                </span>
              )}
            </>
          )}
        </div>
        <ArrowRight size={12} className="text-content-tertiary" />
      </div>
    </Card>
  );
}

function PinButton({ projectId }: { projectId: string }) {
  const { t } = useTranslation();
  const togglePinned = useProjectContextStore((s) => s.togglePinned);
  const isPinned = useProjectContextStore((s) => s.pinnedProjectIds.includes(projectId));

  return (
    <button
      className={`flex h-7 w-7 items-center justify-center rounded-md transition-colors ${
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
