import { useState, useMemo, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import clsx from 'clsx';
import {
  PenTool,
  Search,
  Download,
  ChevronDown,
  ChevronRight,
  Trash2,
  Cloud,
  ArrowRight,
  Type,
  Stamp,
  Ruler,
  Highlighter,
  PenLine,
  Filter,
  Plus,
  FileText,
} from 'lucide-react';
import { Button, Card, Badge, EmptyState, Breadcrumb } from '@/shared/ui';
import { apiGet } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import {
  fetchMarkups,
  fetchMarkupsSummary,
  fetchStampTemplates,
  updateMarkup,
  deleteMarkup,
  exportMarkupsCSV,
} from './api';
import type {
  Markup,
  MarkupType,
  MarkupStatus,
  MarkupsSummary,
  StampTemplate,
} from './api';

/* ── Constants ─────────────────────────────────────────────────────────── */

interface Project {
  id: string;
  name: string;
  currency: string;
}

interface DocItem {
  id: string;
  name: string;
}

const MARKUP_TYPES: MarkupType[] = [
  'cloud',
  'arrow',
  'text',
  'stamp',
  'measurement',
  'highlight',
  'freehand',
];

const MARKUP_STATUSES: MarkupStatus[] = ['active', 'resolved', 'archived'];

const TYPE_ICONS: Record<MarkupType, React.ElementType> = {
  cloud: Cloud,
  arrow: ArrowRight,
  text: Type,
  stamp: Stamp,
  measurement: Ruler,
  highlight: Highlighter,
  freehand: PenLine,
};

const TYPE_LABELS: Record<MarkupType, string> = {
  cloud: 'Cloud',
  arrow: 'Arrow',
  text: 'Text',
  stamp: 'Stamp',
  measurement: 'Measurement',
  highlight: 'Highlight',
  freehand: 'Freehand',
};

const STATUS_BADGE_VARIANT: Record<MarkupStatus, 'blue' | 'success' | 'neutral'> = {
  active: 'blue',
  resolved: 'success',
  archived: 'neutral',
};

const DEFAULT_STAMPS = [
  { name: 'approved', label: 'Approved', color: 'green' },
  { name: 'rejected', label: 'Rejected', color: 'red' },
  { name: 'for_review', label: 'For Review', color: 'blue' },
  { name: 'revised', label: 'Revised', color: 'purple' },
  { name: 'final', label: 'Final', color: 'amber' },
];

const STAMP_COLORS: Record<string, string> = {
  approved:
    'bg-green-100 text-green-800 border-green-300 dark:bg-green-900/30 dark:text-green-400 dark:border-green-700',
  rejected:
    'bg-red-100 text-red-800 border-red-300 dark:bg-red-900/30 dark:text-red-400 dark:border-red-700',
  for_review:
    'bg-blue-100 text-blue-800 border-blue-300 dark:bg-blue-900/30 dark:text-blue-400 dark:border-blue-700',
  reviewed:
    'bg-blue-100 text-blue-800 border-blue-300 dark:bg-blue-900/30 dark:text-blue-400 dark:border-blue-700',
  for_information:
    'bg-amber-100 text-amber-800 border-amber-300 dark:bg-amber-900/30 dark:text-amber-400 dark:border-amber-700',
  revised:
    'bg-purple-100 text-purple-800 border-purple-300 dark:bg-purple-900/30 dark:text-purple-400 dark:border-purple-700',
  final:
    'bg-amber-100 text-amber-800 border-amber-300 dark:bg-amber-900/30 dark:text-amber-400 dark:border-amber-700',
};

/* ── Styling helpers ──────────────────────────────────────────────────── */

const inputCls =
  'h-10 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';

/* ── Stats Cards ──────────────────────────────────────────────────────── */

function StatsCards({ summary }: { summary: MarkupsSummary | undefined }) {
  const { t } = useTranslation();

  const total = summary?.total ?? 0;
  const byType = summary?.by_type ?? {};
  const byStatus = summary?.by_status ?? {};

  const typeBreakdown =
    MARKUP_TYPES.filter((tp) => (byType[tp] ?? 0) > 0)
      .map((tp) => `${byType[tp]} ${tp}`)
      .join(', ') || '-';

  const activeCount = byStatus['active'] ?? 0;
  const resolvedCount = byStatus['resolved'] ?? 0;
  const archivedCount = byStatus['archived'] ?? 0;

  const items = [
    {
      label: t('markups.stat_total', { defaultValue: 'Total Markups' }),
      value: total,
      cls: 'text-content-primary',
    },
    {
      label: t('markups.stat_by_type', { defaultValue: 'By Type' }),
      value: typeBreakdown,
      cls: 'text-content-primary',
    },
    {
      label: t('markups.stat_by_status', { defaultValue: 'By Status' }),
      value: `${activeCount} / ${resolvedCount} / ${archivedCount}`,
      sub: t('markups.stat_status_labels', { defaultValue: 'Active / Resolved / Archived' }),
      cls: 'text-content-primary',
    },
    {
      label: t('markups.stat_authors', { defaultValue: 'Authors' }),
      value: Object.keys(summary?.by_author ?? {}).length,
      cls: 'text-content-primary',
    },
  ];

  return (
    <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
      {items.map((item) => (
        <Card key={item.label} className="p-4 animate-card-in">
          <p className="text-2xs text-content-tertiary uppercase tracking-wide">{item.label}</p>
          <p className={clsx('text-lg font-semibold mt-1 tabular-nums', item.cls)}>
            {item.value}
          </p>
          {'sub' in item && item.sub && (
            <p className="text-2xs text-content-quaternary mt-0.5">{item.sub}</p>
          )}
        </Card>
      ))}
    </div>
  );
}

/* ── Expanded Row Detail ──────────────────────────────────────────────── */

function MarkupDetail({ markup }: { markup: Markup }) {
  const { t } = useTranslation();
  return (
    <div className="px-6 py-4 bg-surface-secondary/50 border-t border-border-light">
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div>
          <p className="text-2xs font-medium text-content-tertiary uppercase tracking-wide mb-1">
            {t('markups.full_text', { defaultValue: 'Full Text' })}
          </p>
          <p className="text-sm text-content-secondary">
            {markup.full_text || t('markups.no_text', { defaultValue: '(none)' })}
          </p>
        </div>
        <div>
          <p className="text-2xs font-medium text-content-tertiary uppercase tracking-wide mb-1">
            {t('markups.geometry_preview', { defaultValue: 'Geometry' })}
          </p>
          <p className="text-sm text-content-secondary">
            {markup.geometry
              ? t('markups.has_geometry', { defaultValue: 'Geometry data available' })
              : t('markups.no_geometry', { defaultValue: 'No geometry data' })}
          </p>
        </div>
        <div>
          <p className="text-2xs font-medium text-content-tertiary uppercase tracking-wide mb-1">
            {t('markups.linked_boq', { defaultValue: 'Linked BOQ Position' })}
          </p>
          <p className="text-sm text-content-secondary">
            {markup.linked_position_id || t('markups.not_linked', { defaultValue: 'Not linked' })}
          </p>
        </div>
      </div>
      {markup.metadata && Object.keys(markup.metadata).length > 0 && (
        <div className="mt-3">
          <p className="text-2xs font-medium text-content-tertiary uppercase tracking-wide mb-1">
            {t('markups.metadata', { defaultValue: 'Metadata' })}
          </p>
          <pre className="text-xs text-content-tertiary bg-surface-primary rounded-lg p-2 overflow-x-auto">
            {JSON.stringify(markup.metadata, null, 2)}
          </pre>
        </div>
      )}
    </div>
  );
}

/* ── Stamp Templates Section ──────────────────────────────────────────── */

function StampTemplatesSection({
  stamps,
  projectId,
}: {
  stamps: StampTemplate[];
  projectId: string;
}) {
  const { t } = useTranslation();

  // Merge API stamps with defaults — always show predefined stamps
  const apiStampMap = new Map(stamps.map((s) => [s.name, s]));
  const displayStamps: Array<{ name: string; label: string; color: string }> = DEFAULT_STAMPS.map(
    (def) => {
      const apiStamp = apiStampMap.get(def.name);
      return apiStamp
        ? { name: apiStamp.name, label: apiStamp.label, color: apiStamp.color }
        : def;
    },
  );

  // Add any extra API stamps not in defaults
  for (const s of stamps) {
    if (!DEFAULT_STAMPS.some((d) => d.name === s.name)) {
      displayStamps.push({ name: s.name, label: s.label, color: s.color });
    }
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-sm font-semibold text-content-primary">
          {t('markups.stamp_templates', { defaultValue: 'Stamp Templates' })}
        </h2>
        <Button variant="ghost" size="sm" disabled={!projectId}>
          <Plus size={14} className="mr-1" />
          {t('markups.create_custom_stamp', { defaultValue: 'Create Custom Stamp' })}
        </Button>
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-5 gap-3">
        {displayStamps.map((stamp) => {
          const colorCls =
            STAMP_COLORS[stamp.name] ??
            'bg-gray-100 text-gray-800 border-gray-300 dark:bg-gray-900/30 dark:text-gray-400 dark:border-gray-700';
          return (
            <div
              key={stamp.name}
              className={clsx(
                'flex flex-col items-center justify-center rounded-lg border-2 p-4 text-center transition-all hover:scale-105 cursor-pointer',
                colorCls,
              )}
            >
              <Stamp size={24} className="mb-2" />
              <span className="text-sm font-semibold">{stamp.label}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

/* ── Main Page ─────────────────────────────────────────────────────────── */

export function MarkupsPage() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const activeProjectId = useProjectContextStore((s) => s.activeProjectId);

  // Filter state
  const [searchQuery, setSearchQuery] = useState('');
  const [filterType, setFilterType] = useState<MarkupType | ''>('');
  const [filterStatus, setFilterStatus] = useState<MarkupStatus | ''>('');
  const [filterAuthor, setFilterAuthor] = useState('');
  const [filterDocumentId, setFilterDocumentId] = useState('');
  const [showFilters, setShowFilters] = useState(false);
  const [expandedRowId, setExpandedRowId] = useState<string | null>(null);

  // Data queries
  const { data: projects = [] } = useQuery({
    queryKey: ['projects'],
    queryFn: () => apiGet<Project[]>('/v1/projects/'),
  });

  const projectId = activeProjectId || projects[0]?.id || '';
  const project = useMemo(
    () => projects.find((p) => p.id === projectId),
    [projects, projectId],
  );

  // Fetch documents for the selected project (used in document filter dropdown)
  const { data: documents = [] } = useQuery({
    queryKey: ['documents-list', projectId],
    queryFn: () => apiGet<DocItem[]>(`/v1/documents/?project_id=${projectId}`),
    enabled: !!projectId,
  });

  const { data: markups = [], isLoading } = useQuery({
    queryKey: ['markups', projectId, filterType, filterStatus, filterAuthor, filterDocumentId],
    queryFn: () =>
      fetchMarkups(projectId, {
        type: filterType || undefined,
        status: filterStatus || undefined,
        author_id: filterAuthor || undefined,
        document_id: filterDocumentId || undefined,
      }),
    enabled: !!projectId,
  });

  const { data: summary } = useQuery({
    queryKey: ['markups-summary', projectId],
    queryFn: () => fetchMarkupsSummary(projectId),
    enabled: !!projectId,
  });

  const { data: stamps = [] } = useQuery({
    queryKey: ['stamp-templates', projectId],
    queryFn: () => fetchStampTemplates(projectId),
    enabled: !!projectId,
  });

  // Unique authors from markups for filter dropdown
  const authors = useMemo(() => {
    const map = new Map<string, string>();
    for (const m of markups) {
      if (m.author_id && m.author) map.set(m.author_id, m.author);
    }
    return Array.from(map.entries()).map(([id, name]) => ({ id, name }));
  }, [markups]);

  // Client-side search filter
  const filteredMarkups = useMemo(() => {
    if (!searchQuery.trim()) return markups;
    const q = searchQuery.toLowerCase();
    return markups.filter(
      (m) =>
        m.label.toLowerCase().includes(q) ||
        m.full_text.toLowerCase().includes(q) ||
        m.document_name.toLowerCase().includes(q) ||
        m.author.toLowerCase().includes(q),
    );
  }, [markups, searchQuery]);

  // Invalidation
  const invalidateAll = useCallback(() => {
    qc.invalidateQueries({ queryKey: ['markups'] });
    qc.invalidateQueries({ queryKey: ['markups-summary'] });
  }, [qc]);

  // Mutations
  const statusMut = useMutation({
    mutationFn: ({ id, status }: { id: string; status: MarkupStatus }) =>
      updateMarkup(id, { status }),
    onSuccess: () => {
      invalidateAll();
      addToast({
        type: 'success',
        title: t('markups.status_updated', { defaultValue: 'Markup status updated' }),
      });
    },
    onError: (e: Error) =>
      addToast({
        type: 'error',
        title: t('common.error', { defaultValue: 'Error' }),
        message: e.message,
      }),
  });

  const delMut = useMutation({
    mutationFn: (id: string) => deleteMarkup(id),
    onSuccess: () => {
      invalidateAll();
      addToast({
        type: 'success',
        title: t('markups.deleted', { defaultValue: 'Markup deleted' }),
      });
    },
    onError: (e: Error) =>
      addToast({
        type: 'error',
        title: t('common.error', { defaultValue: 'Error' }),
        message: e.message,
      }),
  });

  // CSV export handler
  const handleExportCSV = useCallback(async () => {
    if (!projectId) return;
    try {
      const blob = await exportMarkupsCSV(projectId);
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `markups-${projectId}.csv`;
      a.click();
      URL.revokeObjectURL(url);
      addToast({
        type: 'success',
        title: t('markups.exported', { defaultValue: 'Markups exported to CSV' }),
      });
    } catch (e) {
      addToast({
        type: 'error',
        title: t('common.error', { defaultValue: 'Error' }),
        message: e instanceof Error ? e.message : String(e),
      });
    }
  }, [projectId, addToast, t]);

  return (
    <div className="mx-auto max-w-6xl px-6 py-6">
      {/* Breadcrumb */}
      <Breadcrumb
        items={[
          { label: t('nav.dashboard', { defaultValue: 'Dashboard' }), to: '/' },
          {
            label: t('markups.title', { defaultValue: 'Markups & Annotations' }),
          },
        ]}
      />

      {/* Header */}
      <div className="mt-4 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-content-primary flex items-center gap-2">
            <PenTool size={24} className="text-oe-blue" />
            {t('markups.title', { defaultValue: 'Markups & Annotations' })}
          </h1>
          {project && (
            <p className="mt-1 text-sm text-content-secondary">{project.name}</p>
          )}
        </div>
        <div className="flex items-center gap-3">
          {/* Project selector — always shown when projects exist */}
          {projects.length > 0 && (
            <select
              value={projectId}
              onChange={(e) => {
                const p = projects.find((pr) => pr.id === e.target.value);
                if (p) {
                  useProjectContextStore.getState().setActiveProject(p.id, p.name);
                }
              }}
              className={inputCls + ' max-w-[220px]'}
            >
              <option value="" disabled>
                {t('markups.select_project', { defaultValue: 'Select project...' })}
              </option>
              {projects.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          )}

          {/* Document selector */}
          {projectId && documents.length > 0 && (
            <select
              value={filterDocumentId}
              onChange={(e) => setFilterDocumentId(e.target.value)}
              className={inputCls + ' max-w-[200px]'}
            >
              <option value="">
                {t('markups.all_documents', { defaultValue: 'All Documents' })}
              </option>
              {documents.map((doc) => (
                <option key={doc.id} value={doc.id}>
                  {doc.name}
                </option>
              ))}
            </select>
          )}

          <Button variant="secondary" size="sm" onClick={handleExportCSV} disabled={!projectId}>
            <Download size={16} className="mr-1.5" />
            {t('markups.export_csv', { defaultValue: 'Export CSV' })}
          </Button>
        </div>
      </div>

      {/* Empty state: no project selected */}
      {!projectId ? (
        <div className="mt-12">
          <EmptyState
            icon={<PenTool size={40} className="text-content-quaternary" />}
            title={t('markups.no_project_title', { defaultValue: 'No project selected' })}
            description={t('markups.no_project_desc', {
              defaultValue:
                'Select a project from the dropdown above to view and manage markups and annotations on your documents.',
            })}
          />
        </div>
      ) : (
        <>
          {/* Stats */}
          <div className="mt-6">
            <StatsCards summary={summary} />
          </div>

          {/* Filter bar */}
          <div className="mt-6 flex flex-col sm:flex-row sm:items-center gap-3">
            {/* Search */}
            <div className="relative flex-1 max-w-sm">
              <Search
                size={16}
                className="absolute left-3 top-1/2 -translate-y-1/2 text-content-tertiary"
              />
              <input
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder={t('markups.search', {
                  defaultValue: 'Search label, text, document...',
                })}
                className={inputCls + ' pl-9'}
              />
            </div>

            <Button
              variant="ghost"
              size="sm"
              onClick={() => setShowFilters(!showFilters)}
              className={showFilters ? 'text-oe-blue' : ''}
            >
              <Filter size={16} className="mr-1" />
              {t('common.filters', { defaultValue: 'Filters' })}
            </Button>
          </div>

          {/* Collapsible filters */}
          {showFilters && (
            <div className="mt-3 flex flex-wrap gap-3 animate-fade-in">
              <select
                value={filterType}
                onChange={(e) => setFilterType(e.target.value as MarkupType | '')}
                className={inputCls + ' max-w-[160px]'}
              >
                <option value="">
                  {t('markups.all_types', { defaultValue: 'All Types' })}
                </option>
                {MARKUP_TYPES.map((tp) => (
                  <option key={tp} value={tp}>
                    {t(`markups.type_${tp}`, {
                      defaultValue: TYPE_LABELS[tp],
                    })}
                  </option>
                ))}
              </select>

              <select
                value={filterStatus}
                onChange={(e) => setFilterStatus(e.target.value as MarkupStatus | '')}
                className={inputCls + ' max-w-[160px]'}
              >
                <option value="">
                  {t('markups.all_statuses', { defaultValue: 'All Statuses' })}
                </option>
                {MARKUP_STATUSES.map((st) => (
                  <option key={st} value={st}>
                    {t(`markups.status_${st}`, {
                      defaultValue: st.charAt(0).toUpperCase() + st.slice(1),
                    })}
                  </option>
                ))}
              </select>

              <select
                value={filterAuthor}
                onChange={(e) => setFilterAuthor(e.target.value)}
                className={inputCls + ' max-w-[180px]'}
              >
                <option value="">
                  {t('markups.all_authors', { defaultValue: 'All Authors' })}
                </option>
                {authors.map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.name}
                  </option>
                ))}
              </select>
            </div>
          )}

          {/* Table */}
          <div className="mt-6">
            {isLoading ? (
              <div className="flex items-center justify-center py-16">
                <div className="h-6 w-6 animate-spin rounded-full border-2 border-oe-blue border-t-transparent" />
              </div>
            ) : filteredMarkups.length === 0 ? (
              <EmptyState
                icon={<PenTool size={40} className="text-content-quaternary" />}
                title={t('markups.empty_title', { defaultValue: 'No markups found' })}
                description={t('markups.empty_desc', {
                  defaultValue:
                    'Select a project and start annotating documents. Markups and annotations will appear here.',
                })}
              />
            ) : (
              <Card className="overflow-hidden">
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-border-light bg-surface-secondary/50">
                        <th className="px-4 py-3 text-left text-2xs font-semibold uppercase tracking-wider text-content-tertiary">
                          {t('markups.col_type', { defaultValue: 'Type' })}
                        </th>
                        <th className="px-4 py-3 text-left text-2xs font-semibold uppercase tracking-wider text-content-tertiary">
                          {t('markups.col_label', { defaultValue: 'Label / Text' })}
                        </th>
                        <th className="px-4 py-3 text-left text-2xs font-semibold uppercase tracking-wider text-content-tertiary">
                          {t('markups.col_document', { defaultValue: 'Document' })}
                        </th>
                        <th className="px-4 py-3 text-left text-2xs font-semibold uppercase tracking-wider text-content-tertiary">
                          {t('markups.col_page', { defaultValue: 'Page' })}
                        </th>
                        <th className="px-4 py-3 text-left text-2xs font-semibold uppercase tracking-wider text-content-tertiary">
                          {t('markups.col_author', { defaultValue: 'Author' })}
                        </th>
                        <th className="px-4 py-3 text-left text-2xs font-semibold uppercase tracking-wider text-content-tertiary">
                          {t('markups.col_status', { defaultValue: 'Status' })}
                        </th>
                        <th className="px-4 py-3 text-left text-2xs font-semibold uppercase tracking-wider text-content-tertiary">
                          {t('markups.col_measurement', { defaultValue: 'Measurement' })}
                        </th>
                        <th className="px-4 py-3 text-left text-2xs font-semibold uppercase tracking-wider text-content-tertiary">
                          {t('markups.col_date', { defaultValue: 'Date' })}
                        </th>
                        <th className="px-4 py-3 text-right text-2xs font-semibold uppercase tracking-wider text-content-tertiary">
                          {t('common.actions', { defaultValue: 'Actions' })}
                        </th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-border-light">
                      {filteredMarkups.map((markup) => {
                        const TypeIcon = TYPE_ICONS[markup.type] ?? PenTool;
                        const isExpanded = expandedRowId === markup.id;

                        return (
                          <MarkupTableRow
                            key={markup.id}
                            markup={markup}
                            TypeIcon={TypeIcon}
                            isExpanded={isExpanded}
                            onToggleExpand={() =>
                              setExpandedRowId(isExpanded ? null : markup.id)
                            }
                            onChangeStatus={(status) =>
                              statusMut.mutate({ id: markup.id, status })
                            }
                            onDelete={() => delMut.mutate(markup.id)}
                            t={t}
                          />
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </Card>
            )}
          </div>

          {/* Stamp Templates */}
          <div className="mt-8">
            <StampTemplatesSection stamps={stamps} projectId={projectId} />
          </div>
        </>
      )}
    </div>
  );
}

/* ── Table Row ─────────────────────────────────────────────────────────── */

function MarkupTableRow({
  markup,
  TypeIcon,
  isExpanded,
  onToggleExpand,
  onChangeStatus,
  onDelete,
  t,
}: {
  markup: Markup;
  TypeIcon: React.ElementType;
  isExpanded: boolean;
  onToggleExpand: () => void;
  onChangeStatus: (status: MarkupStatus) => void;
  onDelete: () => void;
  t: ReturnType<typeof useTranslation>['t'];
}) {
  const formattedDate = useMemo(() => {
    try {
      return new Date(markup.created_at).toLocaleDateString(undefined, {
        year: 'numeric',
        month: 'short',
        day: 'numeric',
      });
    } catch {
      return markup.created_at;
    }
  }, [markup.created_at]);

  const measurementDisplay =
    markup.measurement_value && markup.measurement_unit
      ? `${markup.measurement_value} ${markup.measurement_unit}`
      : '-';

  // Resolve a more descriptive icon color per type
  const typeColorCls: Record<MarkupType, string> = {
    cloud: 'text-blue-500',
    arrow: 'text-orange-500',
    text: 'text-content-secondary',
    stamp: 'text-purple-500',
    measurement: 'text-emerald-600',
    highlight: 'text-yellow-500',
    freehand: 'text-pink-500',
  };

  const iconColor = typeColorCls[markup.type] ?? 'text-content-secondary';

  return (
    <>
      <tr
        onClick={onToggleExpand}
        className="cursor-pointer hover:bg-surface-secondary/50 transition-colors"
      >
        <td className="px-4 py-3">
          <div className="flex items-center gap-2">
            {isExpanded ? (
              <ChevronDown size={14} className="text-content-tertiary shrink-0" />
            ) : (
              <ChevronRight size={14} className="text-content-tertiary shrink-0" />
            )}
            <TypeIcon size={16} className={clsx('shrink-0', iconColor)} />
            <span className="text-xs text-content-secondary capitalize">
              {t(`markups.type_${markup.type}`, {
                defaultValue: TYPE_LABELS[markup.type] ?? markup.type,
              })}
            </span>
          </div>
        </td>
        <td className="px-4 py-3">
          <span className="text-sm text-content-primary font-medium truncate max-w-[200px] block">
            {markup.label || markup.full_text.slice(0, 40) || '-'}
          </span>
        </td>
        <td className="px-4 py-3">
          <div className="flex items-center gap-1.5">
            <FileText size={14} className="text-content-tertiary shrink-0" />
            <span className="text-sm text-content-secondary truncate max-w-[150px] block">
              {markup.document_name}
            </span>
          </div>
        </td>
        <td className="px-4 py-3 text-sm text-content-secondary tabular-nums">
          {markup.page}
        </td>
        <td className="px-4 py-3 text-sm text-content-secondary">{markup.author}</td>
        <td className="px-4 py-3">
          <Badge variant={STATUS_BADGE_VARIANT[markup.status] ?? 'neutral'} size="sm">
            {t(`markups.status_${markup.status}`, {
              defaultValue: markup.status.charAt(0).toUpperCase() + markup.status.slice(1),
            })}
          </Badge>
        </td>
        <td className="px-4 py-3 text-sm text-content-secondary tabular-nums">
          {measurementDisplay}
        </td>
        <td className="px-4 py-3 text-sm text-content-tertiary">{formattedDate}</td>
        <td className="px-4 py-3 text-right">
          <div
            className="flex items-center justify-end gap-1"
            onClick={(e) => e.stopPropagation()}
          >
            {/* Status actions */}
            {markup.status === 'active' && (
              <Button
                variant="ghost"
                size="sm"
                onClick={() => onChangeStatus('resolved')}
                title={t('markups.action_resolve', { defaultValue: 'Resolve' })}
              >
                {t('markups.action_resolve', { defaultValue: 'Resolve' })}
              </Button>
            )}
            {markup.status === 'resolved' && (
              <Button
                variant="ghost"
                size="sm"
                onClick={() => onChangeStatus('archived')}
                title={t('markups.action_archive', { defaultValue: 'Archive' })}
              >
                {t('markups.action_archive', { defaultValue: 'Archive' })}
              </Button>
            )}
            <Button
              variant="ghost"
              size="sm"
              onClick={onDelete}
              className="text-semantic-error hover:text-semantic-error"
              title={t('common.delete', { defaultValue: 'Delete' })}
            >
              <Trash2 size={14} />
            </Button>
          </div>
        </td>
      </tr>
      {isExpanded && (
        <tr>
          <td colSpan={9}>
            <MarkupDetail markup={markup} />
          </td>
        </tr>
      )}
    </>
  );
}
