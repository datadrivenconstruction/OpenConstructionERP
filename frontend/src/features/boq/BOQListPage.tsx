import { useState, useCallback, useMemo, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import {
  Table, Table2, ArrowRight, FolderOpen, Copy, Trash2, Plus,
  Search, ArrowUpDown, ChevronDown, GitCompareArrows, X, Loader2,
} from 'lucide-react';
import { Card, Badge, EmptyState, Skeleton, Button } from '@/shared/ui';
import { apiGet } from '@/shared/lib/api';
import { getIntlLocale } from '@/shared/lib/formatters';
import { boqApi, type BOQWithPositions, groupPositionsIntoSections, type SectionGroup } from './api';
import { useToastStore } from '@/stores/useToastStore';
import { useModuleStore } from '@/stores/useModuleStore';
import { PresenceAvatars } from '@/modules/collaboration/components/PresenceAvatars';
import { usePresenceStore } from '@/modules/collaboration/hooks/usePresence';

interface Project {
  id: string;
  name: string;
  currency: string;
  classification_standard: string;
}

interface BOQ {
  id: string;
  project_id: string;
  name: string;
  description: string;
  status: string;
  created_at: string;
}

interface BOQWithProject extends BOQ {
  projectName: string;
  currency: string;
  positionCount: number;
  grandTotal: number;
  classificationStandard: string;
}

const ITEMS_PER_PAGE = 12;

const currencyFmt = new Intl.NumberFormat(getIntlLocale(), {
  minimumFractionDigits: 0,
  maximumFractionDigits: 0,
});

/* ── Compare Modal ───────────────────────────────────────────────────── */

interface CompareModalProps {
  boqIdA: string;
  boqIdB: string;
  currencyA: string;
  currencyB: string;
  onClose: () => void;
}

function fmtDiff(diff: number, currency: string): string {
  const sign = diff >= 0 ? '+' : '';
  return `${sign}${currencyFmt.format(diff)} ${currency}`;
}

function fmtPct(a: number, b: number): string {
  if (a === 0) return b === 0 ? '0%' : '+100%';
  const pct = ((b - a) / Math.abs(a)) * 100;
  const sign = pct >= 0 ? '+' : '';
  return `${sign}${pct.toFixed(1)}%`;
}

function diffColor(diff: number): string {
  if (diff < 0) return 'text-semantic-success';
  if (diff > 0) return 'text-semantic-error';
  return 'text-content-tertiary';
}

function CompareModal({ boqIdA, boqIdB, currencyA, currencyB, onClose }: CompareModalProps) {
  const { t } = useTranslation();
  const [boqA, setBoqA] = useState<BOQWithPositions | null>(null);
  const [boqB, setBoqB] = useState<BOQWithPositions | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    Promise.all([boqApi.get(boqIdA), boqApi.get(boqIdB)])
      .then(([a, b]) => {
        if (!cancelled) {
          setBoqA(a);
          setBoqB(b);
        }
      })
      .catch(() => {
        if (!cancelled) setError(t('boq.compare_load_error', { defaultValue: 'Failed to load BOQ data for comparison' }));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => { cancelled = true; };
  }, [boqIdA, boqIdB, t]);

  // Build section comparison: match sections by ordinal or description
  const comparison = useMemo(() => {
    if (!boqA || !boqB) return null;

    const groupA = groupPositionsIntoSections(boqA.positions);
    const groupB = groupPositionsIntoSections(boqB.positions);

    // Build a map of section key -> section data for both sides
    const sectionKey = (sg: SectionGroup) =>
      sg.section.ordinal.trim() || sg.section.description.trim().toLowerCase();

    const mapA = new Map<string, SectionGroup>();
    const mapB = new Map<string, SectionGroup>();
    for (const s of groupA.sections) mapA.set(sectionKey(s), s);
    for (const s of groupB.sections) mapB.set(sectionKey(s), s);

    const allKeys = new Set([...mapA.keys(), ...mapB.keys()]);
    const paired: { key: string; nameA: string; nameB: string; totalA: number; totalB: number; countA: number; countB: number }[] = [];

    for (const key of allKeys) {
      const a = mapA.get(key);
      const b = mapB.get(key);
      paired.push({
        key,
        nameA: a?.section.description ?? '--',
        nameB: b?.section.description ?? '--',
        totalA: a?.subtotal ?? 0,
        totalB: b?.subtotal ?? 0,
        countA: a?.children.length ?? 0,
        countB: b?.children.length ?? 0,
      });
    }

    // Add ungrouped totals if any
    const ungroupedTotalA = groupA.ungrouped.reduce((s, p) => s + p.total, 0);
    const ungroupedTotalB = groupB.ungrouped.reduce((s, p) => s + p.total, 0);
    if (ungroupedTotalA > 0 || ungroupedTotalB > 0) {
      paired.push({
        key: '__ungrouped__',
        nameA: t('boq.ungrouped', { defaultValue: 'Ungrouped' }),
        nameB: t('boq.ungrouped', { defaultValue: 'Ungrouped' }),
        totalA: ungroupedTotalA,
        totalB: ungroupedTotalB,
        countA: groupA.ungrouped.length,
        countB: groupB.ungrouped.length,
      });
    }

    return { paired };
  }, [boqA, boqB, t]);

  // Close on Escape
  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [onClose]);

  const currency = currencyA || currencyB || 'EUR';

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm animate-fade-in" onClick={onClose}>
      <div
        className="relative mx-4 max-h-[85vh] w-full max-w-4xl overflow-hidden rounded-2xl bg-surface-primary border border-border-light shadow-2xl flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between border-b border-border-light px-6 py-4">
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-oe-blue-subtle text-oe-blue">
              <GitCompareArrows size={18} />
            </div>
            <h2 className="text-lg font-bold text-content-primary">{t('boq.compare_title', { defaultValue: 'BOQ Comparison' })}</h2>
          </div>
          <button onClick={onClose} className="flex h-8 w-8 items-center justify-center rounded-lg text-content-tertiary hover:text-content-primary hover:bg-surface-secondary transition-colors">
            <X size={18} />
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto p-6">
          {loading ? (
            <div className="flex items-center justify-center gap-3 py-16 text-content-tertiary">
              <Loader2 size={20} className="animate-spin" />
              <span className="text-sm">{t('common.loading')}</span>
            </div>
          ) : error ? (
            <div className="py-16 text-center text-sm text-semantic-error">{error}</div>
          ) : boqA && boqB && comparison ? (
            <div className="space-y-6">
              {/* Summary row */}
              <div className="grid grid-cols-2 gap-4">
                {/* BOQ A summary */}
                <div className="rounded-xl border border-border-light bg-surface-elevated p-4">
                  <div className="text-xs font-medium text-content-tertiary uppercase tracking-wider mb-1">A</div>
                  <div className="text-sm font-bold text-content-primary truncate">{boqA.name}</div>
                  <div className="mt-2 flex items-baseline gap-2">
                    <span className="text-xl font-bold text-content-primary tabular-nums">{currencyFmt.format(boqA.grand_total)}</span>
                    <span className="text-xs text-content-tertiary">{currency}</span>
                  </div>
                  <div className="mt-1 text-xs text-content-tertiary">{boqA.positions.length} {t('boq.positions_label', { defaultValue: 'positions' })}</div>
                </div>

                {/* BOQ B summary */}
                <div className="rounded-xl border border-border-light bg-surface-elevated p-4">
                  <div className="text-xs font-medium text-content-tertiary uppercase tracking-wider mb-1">B</div>
                  <div className="text-sm font-bold text-content-primary truncate">{boqB.name}</div>
                  <div className="mt-2 flex items-baseline gap-2">
                    <span className="text-xl font-bold text-content-primary tabular-nums">{currencyFmt.format(boqB.grand_total)}</span>
                    <span className="text-xs text-content-tertiary">{currency}</span>
                  </div>
                  <div className="mt-1 text-xs text-content-tertiary">{boqB.positions.length} {t('boq.positions_label', { defaultValue: 'positions' })}</div>
                </div>
              </div>

              {/* Difference banner */}
              {(() => {
                const diff = boqB.grand_total - boqA.grand_total;
                return (
                  <div className={`rounded-xl border p-4 text-center ${diff > 0 ? 'border-semantic-error/30 bg-semantic-error-bg' : diff < 0 ? 'border-semantic-success/30 bg-semantic-success-bg' : 'border-border-light bg-surface-secondary'}`}>
                    <div className="text-xs font-medium text-content-tertiary uppercase tracking-wider mb-1">
                      {t('boq.compare_difference', { defaultValue: 'Difference (B vs A)' })}
                    </div>
                    <div className={`text-lg font-bold tabular-nums ${diffColor(diff)}`}>
                      {fmtDiff(diff, currency)} ({fmtPct(boqA.grand_total, boqB.grand_total)})
                    </div>
                  </div>
                );
              })()}

              {/* Section-by-section breakdown */}
              {comparison.paired.length > 0 && (
                <div>
                  <h3 className="text-sm font-semibold text-content-primary mb-3">
                    {t('boq.compare_by_section', { defaultValue: 'By Section' })}
                  </h3>
                  <div className="rounded-xl border border-border-light overflow-hidden">
                    {/* Table header */}
                    <div className="grid grid-cols-[1fr_auto_auto_auto] gap-2 bg-surface-secondary px-4 py-2.5 text-2xs font-medium text-content-tertiary uppercase tracking-wider">
                      <div>{t('boq.section', { defaultValue: 'Section' })}</div>
                      <div className="w-28 text-right">A</div>
                      <div className="w-28 text-right">B</div>
                      <div className="w-24 text-right">{t('boq.compare_diff', { defaultValue: 'Diff' })}</div>
                    </div>
                    {/* Rows */}
                    {comparison.paired.map((row, i) => {
                      const diff = row.totalB - row.totalA;
                      return (
                        <div
                          key={row.key}
                          className={`grid grid-cols-[1fr_auto_auto_auto] gap-2 px-4 py-2.5 text-sm ${i % 2 === 0 ? 'bg-surface-primary' : 'bg-surface-elevated/50'}`}
                        >
                          <div className="text-content-primary truncate font-medium">
                            {row.nameA !== '--' ? row.nameA : row.nameB}
                          </div>
                          <div className="w-28 text-right tabular-nums text-content-secondary">
                            {row.totalA > 0 ? currencyFmt.format(row.totalA) : '--'}
                          </div>
                          <div className="w-28 text-right tabular-nums text-content-secondary">
                            {row.totalB > 0 ? currencyFmt.format(row.totalB) : '--'}
                          </div>
                          <div className={`w-24 text-right tabular-nums font-medium ${diffColor(diff)}`}>
                            {row.totalA === 0 && row.totalB === 0
                              ? '--'
                              : `${diff >= 0 ? '+' : ''}${currencyFmt.format(diff)}`}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
}

/* ── BOQ List Page ───────────────────────────────────────────────────── */

type SortField = 'name' | 'total' | 'positions' | 'date';

export function BOQListPage() {
  const { t, i18n } = useTranslation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);

  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState(() => {
    try {
      const saved = JSON.parse(localStorage.getItem('oe_boq_filters') ?? '{}');
      return saved.status ?? '';
    } catch { return ''; }
  });
  const [projectFilter, setProjectFilter] = useState(() => {
    try {
      const saved = JSON.parse(localStorage.getItem('oe_boq_filters') ?? '{}');
      return saved.project ?? '';
    } catch { return ''; }
  });
  const [sortField, setSortField] = useState<SortField>(() => {
    try {
      const saved = JSON.parse(localStorage.getItem('oe_boq_filters') ?? '{}');
      return saved.sortField ?? 'date';
    } catch { return 'date'; }
  });
  const [sortAsc, setSortAsc] = useState(() => {
    try {
      const saved = JSON.parse(localStorage.getItem('oe_boq_filters') ?? '{}');
      return saved.sortAsc ?? false;
    } catch { return false; }
  });
  const [page, setPage] = useState(1);

  // Persist filters to localStorage
  useEffect(() => {
    try {
      localStorage.setItem('oe_boq_filters', JSON.stringify({
        status: statusFilter,
        project: projectFilter,
        sortField,
        sortAsc,
      }));
    } catch {}
  }, [statusFilter, projectFilter, sortField, sortAsc]);

  // Compare mode state
  const [compareMode, setCompareMode] = useState(false);
  const [selectedForCompare, setSelectedForCompare] = useState<{ id: string; currency: string } | null>(null);
  const [compareTarget, setCompareTarget] = useState<{ idA: string; idB: string; currencyA: string; currencyB: string } | null>(null);

  const exitCompareMode = useCallback(() => {
    setCompareMode(false);
    setSelectedForCompare(null);
    setCompareTarget(null);
  }, []);

  const handleCompareClick = useCallback((boqId: string, currency: string) => {
    if (!compareMode) {
      // Enter compare mode and select first BOQ
      setCompareMode(true);
      setSelectedForCompare({ id: boqId, currency });
    } else if (selectedForCompare && selectedForCompare.id !== boqId) {
      // Second selection — open modal
      setCompareTarget({
        idA: selectedForCompare.id,
        idB: boqId,
        currencyA: selectedForCompare.currency,
        currencyB: currency,
      });
    }
  }, [compareMode, selectedForCompare]);

  const { data: projects, isLoading: projLoading } = useQuery({
    queryKey: ['projects'],
    queryFn: () => apiGet<Project[]>('/v1/projects/'),
  });

  const { data: allBoqs, isLoading: boqLoading } = useQuery({
    queryKey: ['all-boqs', projects?.map((p) => p.id).join(',')],
    queryFn: async () => {
      if (!projects || projects.length === 0) return [];

      // Fetch all BOQs in parallel (one request per project, no N+1 for grand_total)
      const projectMap = new Map(projects.map((p) => [p.id, p]));
      const fetches = projects.map(async (p) => {
        try {
          const boqs = await apiGet<BOQ[]>(`/v1/boq/boqs/?project_id=${p.id}`);
          return boqs.map((b) => ({
            ...b,
            projectName: p.name,
            currency: p.currency,
            positionCount: (b as any).position_count ?? 0,
            grandTotal: (b as any).grand_total ?? 0,
            classificationStandard: p.classification_standard,
          } as BOQWithProject));
        } catch (err) {
          console.error(`Failed to fetch BOQs for project ${p.id}:`, err);
          return [] as BOQWithProject[];
        }
      });

      const results = await Promise.all(fetches);
      return results.flat();
    },
    enabled: !!projects && projects.length > 0,
  });

  // Seed demo presence when collaboration module is enabled and BOQs load
  const isCollabEnabled = useModuleStore((s) => s.isModuleEnabled('collaboration'));
  const seedDemoPresence = usePresenceStore((s) => s.seedDemoPresence);
  useEffect(() => {
    if (isCollabEnabled && allBoqs && allBoqs.length > 0) {
      seedDemoPresence(allBoqs.map((b) => b.id));
    }
  }, [isCollabEnabled, allBoqs, seedDemoPresence]);

  /* ── Filter + Sort ────────────────────────────────────────────────── */

  const filtered = useMemo(() => {
    if (!allBoqs) return [];
    let list = [...allBoqs];

    if (searchQuery) {
      const q = searchQuery.toLowerCase();
      list = list.filter(
        (b) =>
          b.name.toLowerCase().includes(q) ||
          b.projectName.toLowerCase().includes(q) ||
          (b.description && b.description.toLowerCase().includes(q)),
      );
    }
    if (statusFilter) {
      list = list.filter((b) => b.status === statusFilter);
    }
    if (projectFilter) {
      list = list.filter((b) => b.project_id === projectFilter);
    }

    list.sort((a, b) => {
      let cmp = 0;
      switch (sortField) {
        case 'name': cmp = a.name.localeCompare(b.name); break;
        case 'total': cmp = a.grandTotal - b.grandTotal; break;
        case 'positions': cmp = a.positionCount - b.positionCount; break;
        case 'date': cmp = new Date(a.created_at).getTime() - new Date(b.created_at).getTime(); break;
      }
      return sortAsc ? cmp : -cmp;
    });

    return list;
  }, [allBoqs, searchQuery, statusFilter, projectFilter, sortField, sortAsc]);

  // Reset page when filters/search/sort change
  useEffect(() => {
    setPage(1);
  }, [searchQuery, statusFilter, projectFilter, sortField, sortAsc]);

  // Pagination
  const totalPages = Math.max(1, Math.ceil(filtered.length / ITEMS_PER_PAGE));
  const paginatedBoqs = filtered.slice(
    (page - 1) * ITEMS_PER_PAGE,
    page * ITEMS_PER_PAGE,
  );

  /* ── Stats ────────────────────────────────────────────────────────── */

  const stats = useMemo(() => {
    if (!allBoqs) return null;
    const totalValue = allBoqs.reduce((s, b) => s + b.grandTotal, 0);
    const totalPositions = allBoqs.reduce((s, b) => s + b.positionCount, 0);
    const drafts = allBoqs.filter((b) => b.status === 'draft').length;
    const finals = allBoqs.filter((b) => b.status === 'final').length;
    return { totalValue, totalPositions, drafts, finals };
  }, [allBoqs]);

  /* ── Mutations ────────────────────────────────────────────────────── */

  const duplicateMutation = useMutation({
    mutationFn: (boqId: string) => boqApi.duplicateBoq(boqId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['all-boqs'] });
      addToast({ type: 'success', title: t('boq.duplicated', { defaultValue: 'BOQ duplicated' }) });
    },
    onError: () => {
      addToast({ type: 'error', title: t('boq.duplicate_failed', { defaultValue: 'Failed to duplicate' }) });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (boqId: string) => boqApi.deleteBoq(boqId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['all-boqs'] });
      setConfirmDeleteId(null);
      addToast({ type: 'success', title: t('boq.deleted', { defaultValue: 'BOQ deleted' }) });
    },
    onError: () => {
      setConfirmDeleteId(null);
      addToast({ type: 'error', title: t('boq.delete_failed', { defaultValue: 'Failed to delete' }) });
    },
  });

  const handleSort = useCallback((field: SortField) => {
    if (sortField === field) {
      setSortAsc(!sortAsc);
    } else {
      setSortField(field);
      setSortAsc(false);
    }
  }, [sortField, sortAsc]);

  function statusVariant(status: string): 'success' | 'blue' | 'warning' | 'neutral' {
    switch (status) {
      case 'final': return 'success';
      case 'draft': return 'blue';
      case 'in_review': return 'warning';
      default: return 'neutral';
    }
  }

  const isLoading = projLoading || boqLoading;
  const uniqueProjects = Array.from(
    new Map((projects ?? []).map((p) => [p.name, p])).values(),
  );
  const uniqueStatuses = [...new Set((allBoqs ?? []).map((b) => b.status))];

  function valueBorderColor(value: number): string {
    if (value > 10_000_000) return 'border-l-amber-500';
    if (value > 1_000_000) return 'border-l-emerald-500';
    if (value > 100_000) return 'border-l-blue-500';
    return 'border-l-gray-300 dark:border-l-gray-600';
  }

  return (
    <div className="max-w-content mx-auto animate-fade-in">
      {/* Header */}
      <div className="mb-6 flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold text-content-primary">{t('boq.title')}</h1>
          <p className="mt-1 text-sm text-content-secondary">
            {allBoqs
              ? `${allBoqs.length} ${t('boq.estimates', { defaultValue: 'estimates' })} · ${projects?.length ?? 0} ${t('boq.projects_label', { defaultValue: 'projects' })}`
              : t('common.loading')}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {compareMode ? (
            <Button
              variant="ghost"
              icon={<X size={16} />}
              onClick={exitCompareMode}
            >
              {t('boq.cancel_compare', { defaultValue: 'Cancel Compare' })}
            </Button>
          ) : null}
          <Button
            variant="primary"
            icon={<Plus size={16} />}
            onClick={() => navigate('/projects')}
          >
            {t('boq.new_estimate', { defaultValue: 'New Estimate' })}
          </Button>
        </div>
      </div>

      {/* Stats cards */}
      {stats && allBoqs && allBoqs.length > 0 && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-6">
          <div className="rounded-xl bg-surface-elevated border border-border-light p-3">
            <div className="text-2xs font-medium text-content-tertiary uppercase tracking-wider">{t('boq.total_estimates', { defaultValue: 'Total Estimates' })}</div>
            <div className="mt-1 text-xl font-bold text-content-primary tabular-nums">{allBoqs.length}</div>
          </div>
          <div className="rounded-xl bg-surface-elevated border border-border-light p-3">
            <div className="text-2xs font-medium text-content-tertiary uppercase tracking-wider">{t('boq.total_positions', { defaultValue: 'Total Positions' })}</div>
            <div className="mt-1 text-xl font-bold text-content-primary tabular-nums">{stats.totalPositions.toLocaleString()}</div>
          </div>
          <div className="rounded-xl bg-surface-elevated border border-border-light p-3">
            <div className="text-2xs font-medium text-content-tertiary uppercase tracking-wider">{t('boq.total_value', { defaultValue: 'Total Value' })}</div>
            <div className="mt-1 text-xl font-bold text-content-primary tabular-nums">
              {stats.totalValue >= 1_000_000
                ? `${(stats.totalValue / 1_000_000).toFixed(1)}M`
                : stats.totalValue >= 1_000
                  ? `${(stats.totalValue / 1_000).toFixed(0)}K`
                  : currencyFmt.format(stats.totalValue)}
            </div>
          </div>
          <div className="rounded-xl bg-surface-elevated border border-border-light p-3">
            <div className="text-2xs font-medium text-content-tertiary uppercase tracking-wider">{t('boq.status', { defaultValue: 'Status' })}</div>
            <div className="mt-1 flex items-center gap-2">
              <Badge variant="blue" size="sm" dot>{stats.drafts} {t('boq.draft', { defaultValue: 'draft' })}</Badge>
              <Badge variant="success" size="sm" dot>{stats.finals} {t('boq.final', { defaultValue: 'final' })}</Badge>
            </div>
          </div>
        </div>
      )}

      {/* Search + Filters */}
      {allBoqs && allBoqs.length > 0 && (
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
                placeholder={t('boq.search_placeholder', { defaultValue: 'Search estimates...' })}
                className="h-10 w-full rounded-lg border border-border bg-surface-primary pl-10 pr-3 text-sm text-content-primary placeholder:text-content-tertiary focus:outline-none focus:ring-2 focus:ring-oe-blue focus:border-transparent"
              />
            </div>

            {/* Project filter */}
            {uniqueProjects.length > 1 && (
              <div className="relative">
                <select
                  value={projectFilter}
                  onChange={(e) => setProjectFilter(e.target.value)}
                  className="h-10 appearance-none rounded-lg border border-border bg-surface-primary pl-3 pr-9 text-sm text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue sm:w-44"
                >
                  <option value="">{t('boq.all_projects', { defaultValue: 'All projects' })}</option>
                  {uniqueProjects.map((p) => (
                    <option key={p.id} value={p.id}>{p.name}</option>
                  ))}
                </select>
                <div className="pointer-events-none absolute inset-y-0 right-0 flex items-center pr-2.5 text-content-tertiary">
                  <ChevronDown size={14} />
                </div>
              </div>
            )}

            {/* Status filter */}
            {uniqueStatuses.length > 1 && (
              <div className="relative">
                <select
                  value={statusFilter}
                  onChange={(e) => setStatusFilter(e.target.value)}
                  className="h-10 appearance-none rounded-lg border border-border bg-surface-primary pl-3 pr-9 text-sm text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue sm:w-32"
                >
                  <option value="">{t('boq.all_statuses', { defaultValue: 'All statuses' })}</option>
                  {uniqueStatuses.map((s) => (
                    <option key={s} value={s}>{s.charAt(0).toUpperCase() + s.slice(1)}</option>
                  ))}
                </select>
                <div className="pointer-events-none absolute inset-y-0 right-0 flex items-center pr-2.5 text-content-tertiary">
                  <ChevronDown size={14} />
                </div>
              </div>
            )}

            {/* Sort buttons */}
            <div className="flex items-center gap-1 shrink-0">
              {([
                ['name', t('boq.name', { defaultValue: 'Name' })],
                ['total', t('boq.value', { defaultValue: 'Value' })],
                ['date', t('boq.date', { defaultValue: 'Date' })],
              ] as [SortField, string][]).map(([field, label]) => (
                <button
                  key={field}
                  onClick={() => handleSort(field)}
                  className={`flex items-center gap-1 rounded-md px-2 py-1.5 text-2xs font-medium transition-colors ${
                    sortField === field
                      ? 'bg-oe-blue-subtle text-oe-blue'
                      : 'text-content-tertiary hover:text-content-secondary hover:bg-surface-secondary'
                  }`}
                >
                  {label}
                  {sortField === field && (
                    <ArrowUpDown size={10} className={sortAsc ? '' : 'rotate-180'} />
                  )}
                </button>
              ))}
            </div>
          </div>
        </Card>
      )}

      {/* Compare mode banner */}
      {compareMode && selectedForCompare && !compareTarget && (
        <div className="mb-4 flex items-center gap-3 rounded-xl border border-oe-blue/30 bg-oe-blue-subtle px-4 py-3">
          <GitCompareArrows size={16} className="text-oe-blue shrink-0" />
          <span className="text-sm text-oe-blue font-medium">
            {t('boq.compare_select_second', { defaultValue: 'Select a second BOQ to compare' })}
          </span>
        </div>
      )}

      {/* Results */}
      {isLoading ? (
        <div className="space-y-3">
          {[1, 2, 3].map((i) => (
            <Skeleton key={i} height={80} className="w-full" rounded="lg" />
          ))}
        </div>
      ) : filtered.length === 0 && (searchQuery || statusFilter || projectFilter) ? (
        <EmptyState
          icon={<Search size={24} strokeWidth={1.5} />}
          title={t('boq.no_results', { defaultValue: 'No matching estimates' })}
          description={t('boq.no_results_hint', { defaultValue: 'Try adjusting your search or filters' })}
        />
      ) : !allBoqs || allBoqs.length === 0 ? (
        <EmptyState
          icon={<Table size={24} strokeWidth={1.5} />}
          title={t('boq.no_boqs', { defaultValue: 'No BOQs yet' })}
          description={t('boq.no_boqs_hint', { defaultValue: 'Create a project first, then add a Bill of Quantities' })}
          action={{
            label: t('boq.create_boq', { defaultValue: 'Create BOQ' }),
            onClick: () => navigate('/projects/new'),
          }}
        />
      ) : (
        <div className="space-y-2">
          {paginatedBoqs.map((boq, i) => (
            <Card
              key={boq.id}
              hoverable
              padding="none"
              className={`cursor-pointer animate-card-in border-l-4 ${valueBorderColor(boq.grandTotal)} ${selectedForCompare?.id === boq.id ? 'ring-2 ring-oe-blue' : ''}`}
              style={{ animationDelay: `${50 + i * 30}ms` }}
              onClick={() => {
                if (compareMode && selectedForCompare && selectedForCompare.id !== boq.id) {
                  handleCompareClick(boq.id, boq.currency);
                } else if (!compareMode) {
                  navigate(`/boq/${boq.id}`);
                }
              }}
            >
              <div className="flex items-center gap-4 px-5 py-3.5">
                <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-oe-blue-subtle text-oe-blue">
                  <Table2 size={18} strokeWidth={1.75} />
                </div>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-semibold text-content-primary truncate">{boq.name}</span>
                    <Badge variant={statusVariant(boq.status)} size="sm" dot>{boq.status}</Badge>
                    {isCollabEnabled && <PresenceAvatars boqId={boq.id} />}
                  </div>
                  <div className="mt-0.5 flex items-center gap-2 text-xs text-content-tertiary">
                    <span className="truncate">{boq.projectName}</span>
                    <span>·</span>
                    <span className="tabular-nums">{boq.positionCount} {t('boq.positions_short', { defaultValue: 'pos.' })}</span>
                  </div>
                  <div className="mt-1 text-base font-bold text-content-primary tabular-nums">
                    {currencyFmt.format(boq.grandTotal)} {boq.currency}
                  </div>
                </div>

                <div className="flex items-center gap-1.5 shrink-0">
                  <span className="text-2xs text-content-quaternary hidden sm:inline">
                    {new Date(boq.created_at).toLocaleDateString(i18n.language)}
                  </span>

                  <button
                    onClick={(e) => { e.stopPropagation(); handleCompareClick(boq.id, boq.currency); }}
                    className={`flex h-7 w-7 items-center justify-center rounded-md transition-all ${
                      selectedForCompare?.id === boq.id
                        ? 'text-oe-blue bg-oe-blue-subtle'
                        : 'text-content-tertiary hover:text-oe-blue hover:bg-oe-blue-subtle'
                    }`}
                    title={
                      compareMode && selectedForCompare?.id === boq.id
                        ? t('boq.compare_selected', { defaultValue: 'Selected for comparison' })
                        : t('boq.compare', { defaultValue: 'Compare' })
                    }
                  >
                    <GitCompareArrows size={13} />
                  </button>

                  <button
                    onClick={(e) => { e.stopPropagation(); duplicateMutation.mutate(boq.id); }}
                    disabled={duplicateMutation.isPending}
                    className="flex h-7 w-7 items-center justify-center rounded-md text-content-tertiary hover:text-oe-blue hover:bg-oe-blue-subtle transition-all disabled:opacity-40"
                    title={t('boq.duplicate', { defaultValue: 'Duplicate' })}
                  >
                    <Copy size={13} />
                  </button>

                  {confirmDeleteId === boq.id ? (
                    <div className="flex items-center gap-1" onClick={(e) => e.stopPropagation()}>
                      <Button variant="danger" size="sm" onClick={() => deleteMutation.mutate(boq.id)} loading={deleteMutation.isPending}>
                        {t('common.delete')}
                      </Button>
                      <Button variant="ghost" size="sm" onClick={() => setConfirmDeleteId(null)}>
                        {t('common.cancel')}
                      </Button>
                    </div>
                  ) : (
                    <button
                      onClick={(e) => { e.stopPropagation(); setConfirmDeleteId(boq.id); }}
                      className="flex h-7 w-7 items-center justify-center rounded-md text-content-tertiary hover:text-semantic-error hover:bg-semantic-error-bg transition-all"
                      title={t('common.delete')}
                    >
                      <Trash2 size={13} />
                    </button>
                  )}

                  <ArrowRight size={14} className="text-content-quaternary ml-1" />
                </div>
              </div>
            </Card>
          ))}

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

            {/* Summary footer */}
            <p className="text-sm text-content-tertiary">
              {t('boq.pagination_range', { defaultValue: '{{from}}–{{to}} of {{total}} estimates', from: (page - 1) * ITEMS_PER_PAGE + 1, to: Math.min(page * ITEMS_PER_PAGE, filtered.length), total: filtered.length })}
              {(searchQuery || statusFilter || projectFilter) && filtered.length !== (allBoqs?.length ?? 0)
                ? ` (${t('boq.filtered_from', { defaultValue: 'filtered from {{total}}', total: allBoqs?.length ?? 0 })})`
                : ''}
            </p>
          </div>
        </div>
      )}

      {/* Compare modal */}
      {compareTarget && (
        <CompareModal
          boqIdA={compareTarget.idA}
          boqIdB={compareTarget.idB}
          currencyA={compareTarget.currencyA}
          currencyB={compareTarget.currencyB}
          onClose={exitCompareMode}
        />
      )}
    </div>
  );
}
