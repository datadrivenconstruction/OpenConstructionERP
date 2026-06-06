import { useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate, useSearchParams } from 'react-router-dom';
import {
  useQuery,
  useMutation,
  useQueryClient,
} from '@tanstack/react-query';
import clsx from 'clsx';
import {
  Users,
  ClipboardList,
  CalendarRange,
  Search,
  X,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  HardHat,
  Wrench,
  Award,
  Plus,
  Loader2,
  MoreHorizontal,
  Pencil,
  Trash2,
  Ban,
  UserPlus,
  RefreshCw,
  Flame,
  AlertOctagon,
  ArrowUpDown,
  ArrowUp,
  ArrowDown,
  Download,
  Filter,
} from 'lucide-react';
import {
  Button,
  Card,
  Badge,
  DismissibleInfo,
  IntroRichText,
  EmptyState,
  Breadcrumb,
  SkeletonTable,
  WideModal,
  WideModalSection,
  WideModalField,
  ConfirmDialog,
} from '@/shared/ui';
import { DateDisplay } from '@/shared/ui/DateDisplay';
import { MoneyDisplay } from '@/shared/ui/MoneyDisplay';
import { PageHeader } from '@/shared/ui/PageHeader';
import { useToastStore } from '@/stores/useToastStore';
import { getErrorMessage, ApiError } from '@/shared/lib/api';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { useAuthStore } from '@/stores/useAuthStore';
import { usePreferencesStore } from '@/stores/usePreferencesStore';
import {
  listResources,
  getResourceDashboard,
  getBoard,
  listBoardConflicts,
  confirmAssignment,
  cancelAssignment,
  proposeAssignment,
  updateAssignment,
  deleteAssignment,
  listSkills,
  listWindows,
  listRequests,
  createResource,
  updateResource,
  deleteResource,
  createRequest,
  updateRequest,
  deleteRequest,
  fulfillRequest,
  type Resource,
  type ResourceType,
  type ResourceStatus,
  type ResourceRequest,
  type RequestStatus,
  type RequestPriority,
  type Assignment,
  type AssignmentStatus,
  type WindowType,
  type BoardConflict,
  type Skill,
} from './api';
import { projectsApi } from '@/features/projects/api';

type Tab = 'resources' | 'requests' | 'assignments';

const TYPE_VARIANT: Record<ResourceType, 'neutral' | 'blue' | 'success' | 'warning'> = {
  person: 'blue',
  crew: 'success',
  equipment: 'warning',
  subcontractor: 'neutral',
};

const ASSIGN_VARIANT: Record<AssignmentStatus, 'neutral' | 'blue' | 'success' | 'warning' | 'error'> = {
  proposed: 'warning',
  confirmed: 'blue',
  in_progress: 'success',
  completed: 'neutral',
  cancelled: 'error',
};

/* ─── Enum → i18n label helpers ───────────────────────────────────────────
 *
 * Badges across this page were rendering raw snake_case enum tokens
 * (e.g. 'in_progress', 'subcontractor', 'on_leave') verbatim, so non-English
 * locales and screen readers saw machine identifiers instead of human text.
 * These helpers route each enum value through the SAME i18n keys the adjacent
 * <select> options already use, falling back to the raw value for any
 * unmapped token so nothing ever renders blank.
 */
type TFn = (key: string, opts?: Record<string, unknown>) => string;

function resourceTypeLabel(t: TFn, v: ResourceType | string): string {
  const map: Record<string, string> = {
    person: t('resources.type_person', { defaultValue: 'Person' }),
    crew: t('resources.type_crew', { defaultValue: 'Crew' }),
    equipment: t('resources.type_equipment', { defaultValue: 'Equipment' }),
    subcontractor: t('resources.type_subcontractor', { defaultValue: 'Subcontractor' }),
  };
  return map[v] ?? v;
}

function resourceStatusLabel(t: TFn, v: ResourceStatus | string): string {
  const map: Record<string, string> = {
    active: t('resources.status_active', { defaultValue: 'Active' }),
    on_leave: t('resources.status_on_leave', { defaultValue: 'On leave' }),
    inactive: t('resources.status_inactive', { defaultValue: 'Inactive' }),
  };
  return map[v] ?? v;
}

function assignmentStatusLabel(t: TFn, v: AssignmentStatus | string): string {
  const map: Record<string, string> = {
    proposed: t('resources.status_proposed', { defaultValue: 'Proposed' }),
    confirmed: t('resources.status_confirmed', { defaultValue: 'Confirmed' }),
    in_progress: t('resources.status_in_progress', { defaultValue: 'In progress' }),
    completed: t('resources.status_completed', { defaultValue: 'Completed' }),
    cancelled: t('resources.status_cancelled', { defaultValue: 'Cancelled' }),
  };
  return map[v] ?? v;
}

function requestStatusLabel(t: TFn, v: RequestStatus | string): string {
  const map: Record<string, string> = {
    open: t('resources.req_status_open', { defaultValue: 'Open' }),
    fulfilled: t('resources.req_status_fulfilled', { defaultValue: 'Fulfilled' }),
    cancelled: t('resources.req_status_cancelled', { defaultValue: 'Cancelled' }),
  };
  return map[v] ?? v;
}

function requestPriorityLabel(t: TFn, v: RequestPriority | string): string {
  const map: Record<string, string> = {
    low: t('resources.priority_low', { defaultValue: 'Low' }),
    med: t('resources.priority_med', { defaultValue: 'Medium' }),
    high: t('resources.priority_high', { defaultValue: 'High' }),
    critical: t('resources.priority_critical', { defaultValue: 'Critical' }),
  };
  return map[v] ?? v;
}

function windowTypeLabel(t: TFn, v: WindowType | string): string {
  const map: Record<string, string> = {
    available: t('resources.window_available', { defaultValue: 'Available' }),
    unavailable: t('resources.window_unavailable', { defaultValue: 'Unavailable' }),
    holiday: t('resources.window_holiday', { defaultValue: 'Holiday' }),
    sick: t('resources.window_sick', { defaultValue: 'Sick leave' }),
  };
  return map[v] ?? v;
}

function certStatusLabel(t: TFn, v: string): string {
  const map: Record<string, string> = {
    valid: t('resources.cert_status_valid', { defaultValue: 'Valid' }),
    expired: t('resources.cert_status_expired', { defaultValue: 'Expired' }),
    revoked: t('resources.cert_status_revoked', { defaultValue: 'Revoked' }),
  };
  return map[v] ?? v;
}

/**
 * Resolve a display message from a propose/fulfill error.
 *
 * The propose_assignment / fulfill_request endpoints return their conflict
 * (409) and skill-mismatch (422) details as an OBJECT detail
 * (`{ message, conflicts }` / `{ message, missing }`). The shared error
 * extractor only understands string/array `detail`, so it discards the rich
 * message and the toast falls back to a generic "this conflicts with existing
 * data". Read the object detail's `message` here so the user sees the real,
 * actionable reason; fall back to the shared resolver for everything else.
 */
function resourceErrorMessage(err: unknown): string {
  if (err instanceof ApiError && err.body && typeof err.body === 'object') {
    const detail = (err.body as { detail?: unknown }).detail;
    if (
      detail &&
      typeof detail === 'object' &&
      !Array.isArray(detail) &&
      typeof (detail as { message?: unknown }).message === 'string'
    ) {
      const msg = (detail as { message: string }).message;
      if (msg.trim().length > 0) return msg;
    }
  }
  return getErrorMessage(err);
}

const inputCls =
  'h-9 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';

function startOfWeek(): string {
  const d = new Date();
  const day = d.getDay();
  const diff = d.getDate() - day + (day === 0 ? -6 : 1);
  d.setDate(diff);
  d.setHours(0, 0, 0, 0);
  return d.toISOString();
}

function endOfWeek(): string {
  const d = new Date(startOfWeek());
  d.setDate(d.getDate() + 7);
  return d.toISOString();
}

/* ─── Page ─── */

/* ─── Persisted sort/filter state ─────────────────────────────────────
 *
 * Each user gets their preferred sort key/direction and status filter
 * sticky across navigations. We use sessionStorage (not localStorage)
 * so a fresh tab starts clean, mirroring how the requests-tab sort
 * works elsewhere on this page.
 */
type ResourceSortKey = 'code' | 'name' | 'resource_type' | 'status' | 'default_cost_rate';
type SortDir = 'asc' | 'desc';

const RES_SORT_STORAGE_KEY = 'oe.res.sort';
const RES_STATUS_STORAGE_KEY = 'oe.res.statusFilter';
const RES_CURRENCY_STORAGE_KEY = 'oe.res.currencyFilter';

function loadStoredSort(): { key: ResourceSortKey; dir: SortDir } {
  try {
    const raw = sessionStorage.getItem(RES_SORT_STORAGE_KEY);
    if (raw) {
      const parsed = JSON.parse(raw) as { key: ResourceSortKey; dir: SortDir };
      if (parsed && parsed.key && parsed.dir) return parsed;
    }
  } catch {
    /* ignore — corrupt JSON falls through to default */
  }
  return { key: 'code', dir: 'asc' };
}

function buildResourcesCsv(rows: Resource[]): string {
  // Minimal, locale-safe CSV — escape quotes and wrap every cell, RFC-4180.
  const esc = (v: unknown) => `"${String(v ?? '').replace(/"/g, '""')}"`;
  const header = ['code', 'name', 'type', 'status', 'rate', 'currency', 'notes'];
  const lines = [header.map(esc).join(',')];
  for (const r of rows) {
    lines.push(
      [
        r.code,
        r.name,
        r.resource_type,
        r.status,
        r.default_cost_rate,
        r.currency,
        r.notes,
      ]
        .map(esc)
        .join(','),
    );
  }
  return lines.join('\r\n');
}

function downloadCsv(filename: string, csv: string) {
  // BOM ensures Excel opens UTF-8 correctly (German / Russian / Greek
  // umlauts in code/name would otherwise mojibake). Use the U+FEFF escape
  // rather than a literal BOM char so the zero-width-guard CI scan passes.
  const blob = new Blob(['\uFEFF', csv], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

export function ResourcesPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const [tab, setTab] = useState<Tab>('resources');
  const [search, setSearch] = useState('');
  const [typeFilter, setTypeFilter] = useState<ResourceType | ''>('');
  const [statusFilter, setStatusFilter] = useState<ResourceStatus | ''>(() => {
    try {
      return (
        (sessionStorage.getItem(RES_STATUS_STORAGE_KEY) as ResourceStatus | '') ?? ''
      );
    } catch {
      return '';
    }
  });
  const [currencyFilter, setCurrencyFilter] = useState<string>(() => {
    try {
      return sessionStorage.getItem(RES_CURRENCY_STORAGE_KEY) ?? '';
    } catch {
      return '';
    }
  });
  const [sortState, setSortState] = useState<{ key: ResourceSortKey; dir: SortDir }>(
    () => loadStoredSort(),
  );
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [bulkDeleteOpen, setBulkDeleteOpen] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  // Deep link: /resources?resourceId=<id> opens the matching resource drawer
  // (used by Capacity Planning's clickable resource labels). Consume the param
  // once so a back/forward or manual close does not re-open the drawer, and
  // the URL stays clean.
  useEffect(() => {
    const rid = searchParams.get('resourceId');
    if (!rid) return;
    setSelectedId(rid);
    const next = new URLSearchParams(searchParams);
    next.delete('resourceId');
    setSearchParams(next, { replace: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams]);
  const [createOpen, setCreateOpen] = useState(false);
  const [proposeOpen, setProposeOpen] = useState(false);
  // Per-row edit / delete state. Lifted up here so the modal / confirm
  // dialog sit at page-root and survive table re-renders.
  const [editTarget, setEditTarget] = useState<Resource | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<Resource | null>(null);

  // Persist sort + filters across remounts.
  useEffect(() => {
    try {
      sessionStorage.setItem(RES_SORT_STORAGE_KEY, JSON.stringify(sortState));
    } catch {
      /* storage quota / disabled — non-fatal */
    }
  }, [sortState]);
  useEffect(() => {
    try {
      sessionStorage.setItem(RES_STATUS_STORAGE_KEY, statusFilter);
    } catch {
      /* non-fatal */
    }
  }, [statusFilter]);
  useEffect(() => {
    try {
      sessionStorage.setItem(RES_CURRENCY_STORAGE_KEY, currencyFilter);
    } catch {
      /* non-fatal */
    }
  }, [currencyFilter]);
  // Requests tab — lifted up so the page-header "New Request" button can open
  // the modal owned by the tab. Persisted across tab switches.
  const [newRequestOpen, setNewRequestOpen] = useState(false);
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const activeProjectId = useProjectContextStore((s) => s.activeProjectId);
  const activeProjectName = useProjectContextStore((s) => s.activeProjectName);
  const setActiveProject = useProjectContextStore((s) => s.setActiveProject);

  const deleteResourceMut = useMutation({
    mutationFn: (id: string) => deleteResource(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['resources', 'list'] });
      addToast({
        type: 'success',
        title: t('resources.deleted_ok', { defaultValue: 'Resource deleted' }),
      });
      setDeleteTarget(null);
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  /* Inline rate edit — optimistically PATCH a single field. Errors roll
     back via invalidate (we don't need a manual snapshot because the
     query has staleTime 0). */
  const inlineRateMut = useMutation({
    mutationFn: ({ id, rate }: { id: string; rate: number }) =>
      updateResource(id, { default_cost_rate: rate }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['resources', 'list'] });
    },
    onError: (err) => {
      addToast({ type: 'error', title: getErrorMessage(err) });
      qc.invalidateQueries({ queryKey: ['resources', 'list'] });
    },
  });

  /* Bulk delete — mirrors AssignmentsTab pattern. Promise.allSettled
     so a single 409 doesn't kill the others. */
  const bulkDeleteMut = useMutation({
    mutationFn: async (ids: string[]) => {
      const results = await Promise.allSettled(ids.map((id) => deleteResource(id)));
      return {
        total: ids.length,
        failed: results.filter((r) => r.status === 'rejected').length,
      };
    },
    onSuccess: ({ total, failed }) => {
      qc.invalidateQueries({ queryKey: ['resources', 'list'] });
      setSelectedIds(new Set());
      setBulkDeleteOpen(false);
      if (failed === 0) {
        addToast({
          type: 'success',
          title: t('resources.bulk_delete_resources_ok', {
            defaultValue: '{{count}} resources deleted',
            count: total,
          }),
        });
      } else {
        addToast({
          type: 'warning',
          title: t('resources.bulk_delete_partial', {
            defaultValue: '{{ok}} of {{total}} deleted, {{failed}} failed',
            ok: total - failed,
            total,
            failed,
          }),
        });
      }
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });
  const [requestsProjectId, setRequestsProjectId] = useState<string>(
    activeProjectId ?? '',
  );
  // Keep the requests-tab project in lockstep with the global project
  // context when the user switches projects elsewhere (header, /projects,
  // etc.).
  useEffect(() => {
    if (activeProjectId && activeProjectId !== requestsProjectId) {
      setRequestsProjectId(activeProjectId);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeProjectId]);

  const resourcesQ = useQuery({
    queryKey: ['resources', 'list'],
    queryFn: () => listResources({ limit: 200 }),
  });

  const conflictsQ = useQuery({
    queryKey: ['resources', 'conflicts'],
    queryFn: () =>
      listBoardConflicts({ start: startOfWeek(), end: endOfWeek() }).catch(
        () => [] as BoardConflict[],
      ),
    enabled: tab === 'assignments',
  });

  const allResources: Resource[] = resourcesQ.data ?? [];

  // Distinct currencies in the loaded set — drives the currency-filter
  // dropdown. Sorted for stable order across renders.
  const availableCurrencies = useMemo(() => {
    const seen = new Set<string>();
    for (const r of allResources) {
      if (r.currency) seen.add(r.currency);
    }
    return Array.from(seen).sort();
  }, [allResources]);

  const filteredResources = useMemo(() => {
    const s = search.trim().toLowerCase();
    const filtered = allResources.filter((r) => {
      if (typeFilter && r.resource_type !== typeFilter) return false;
      if (statusFilter && r.status !== statusFilter) return false;
      if (currencyFilter && r.currency !== currencyFilter) return false;
      if (!s) return true;
      return (
        r.name.toLowerCase().includes(s) ||
        r.code.toLowerCase().includes(s) ||
        r.notes.toLowerCase().includes(s)
      );
    });
    const dir = sortState.dir === 'asc' ? 1 : -1;
    const { key } = sortState;
    return filtered.slice().sort((a, b) => {
      let cmp = 0;
      if (key === 'default_cost_rate') {
        cmp = (Number(a.default_cost_rate) || 0) - (Number(b.default_cost_rate) || 0);
      } else {
        // Locale-aware string sort — handles diacritics & non-Latin codes
        // (CWICR has Cyrillic/CJK in some seeds).
        cmp = String(a[key] ?? '').localeCompare(String(b[key] ?? ''), undefined, {
          numeric: true,
          sensitivity: 'base',
        });
      }
      return cmp * dir;
    });
  }, [allResources, search, typeFilter, statusFilter, currencyFilter, sortState]);

  // Drop selections that fall outside the visible filtered set so the
  // "Selected: N" counter never lies and the bulk-delete confirmation
  // always matches the rendered checkboxes.
  useEffect(() => {
    const visible = new Set(filteredResources.map((r) => r.id));
    setSelectedIds((prev) => {
      let changed = false;
      const next = new Set<string>();
      for (const id of prev) {
        if (visible.has(id)) next.add(id);
        else changed = true;
      }
      return changed ? next : prev;
    });
  }, [filteredResources]);

  const hasActiveFilters =
    !!search || !!typeFilter || !!statusFilter || !!currencyFilter;
  const clearAllFilters = () => {
    setSearch('');
    setTypeFilter('');
    setStatusFilter('');
    setCurrencyFilter('');
  };

  const isLoading = tab === 'resources' && resourcesQ.isLoading;

  return (
    <div className="space-y-5 animate-fade-in">
      <Breadcrumb
        items={[
          ...(activeProjectName
            ? [{ label: activeProjectName, to: `/projects/${activeProjectId}` }]
            : []),
          { label: t('nav.resources', { defaultValue: 'Resources & Crews' }) },
        ]}
      />

      <PageHeader
        srTitle={t('resources.title', { defaultValue: 'Resources & Crews' })}
        subtitle={t('resources.subtitle', {
          defaultValue:
            'People, equipment and crew assignments - propose, confirm, resolve conflicts.',
        })}
        actions={
          <>
            {tab === 'assignments' && (
              <>
                <Button
                  variant="secondary"
                  size="sm"
                  icon={<CalendarRange size={14} />}
                  onClick={() => navigate('/portfolio/capacity')}
                >
                  {t('resources.assignments_capacity', {
                    defaultValue: 'Portfolio capacity',
                  })}
                </Button>
                <Button
                  variant="primary"
                  size="sm"
                  icon={<Plus size={14} />}
                  onClick={() => setProposeOpen(true)}
                >
                  {t('resources.propose', { defaultValue: 'Propose Assignment' })}
                </Button>
              </>
            )}
            {tab === 'resources' && (
              <Button
                variant="primary"
                size="sm"
                icon={<Plus size={14} />}
                onClick={() => setCreateOpen(true)}
              >
                {t('resources.new_resource', { defaultValue: 'New Resource' })}
              </Button>
            )}
            {tab === 'requests' && (
              <Button
                variant="primary"
                size="sm"
                icon={<Plus size={14} />}
                onClick={() => setNewRequestOpen(true)}
                disabled={!requestsProjectId}
                title={
                  requestsProjectId
                    ? undefined
                    : t('resources.requests_pick_project_first', {
                        defaultValue: 'Select a project below first',
                      })
                }
              >
                {t('resources.new_request', { defaultValue: 'New Request' })}
              </Button>
            )}
          </>
        }
      />

      <DismissibleInfo
        storageKey="resources"
        title={t('resources.intro_title', {
          defaultValue: 'Stop double-booking crews and kit',
        })}
        more={
          t('resources.intro_more', { defaultValue: '' })
            ? <IntroRichText text={t('resources.intro_more')} />
            : undefined
        }
        links={[
          {
            label: t('resources.intro_link_capacity', { defaultValue: 'Capacity Planning' }),
            onClick: () => navigate('/portfolio/capacity'),
          },
          {
            label: t('resources.intro_link_leveling', { defaultValue: 'Resource Leveling' }),
            onClick: () => navigate('/portfolio/leveling'),
          },
          {
            label: t('resources.intro_link_schedule', { defaultValue: '4D Schedule' }),
            onClick: () => navigate('/schedule'),
          },
          {
            label: t('resources.intro_link_tasks', { defaultValue: 'Tasks' }),
            onClick: () => navigate('/tasks'),
          },
          {
            label: t('resources.intro_link_equipment', { defaultValue: 'Equipment' }),
            onClick: () => navigate('/equipment'),
          },
        ]}
      >
        {t('resources.intro_body', {
          defaultValue:
            'Register people, crews and equipment, then put them to work: a foreman raises a Request, a dispatcher fulfils it by matching an available resource, and the resulting Assignment reserves that resource for a date range with double-booking conflicts flagged automatically. Confirmed assignments are the source of truth for who is on site each day and align with the schedule and tasks.',
        })}
      </DismissibleInfo>

      {/* Tabs */}
      <div className="border-b border-border-light">
        <nav className="flex gap-1 -mb-px">
          {(
            [
              {
                id: 'resources',
                label: t('resources.tab_resources', { defaultValue: 'Resources' }),
                icon: Users,
              },
              {
                id: 'requests',
                label: t('resources.tab_requests', { defaultValue: 'Requests' }),
                icon: ClipboardList,
              },
              {
                id: 'assignments',
                label: t('resources.tab_assignments', { defaultValue: 'Assignments' }),
                icon: CalendarRange,
              },
            ] as { id: Tab; label: string; icon: React.ElementType }[]
          ).map((tabItem) => {
            const Icon = tabItem.icon;
            return (
              <button
                key={tabItem.id}
                type="button"
                onClick={() => {
                  setTab(tabItem.id);
                  // Search resets per-tab (each tab has its own logical
                  // search scope). Type/status/currency stay because the
                  // user explicitly persisted them via sessionStorage.
                  setSearch('');
                  if (tabItem.id !== 'resources') {
                    setTypeFilter('');
                  }
                }}
                className={clsx(
                  'flex items-center gap-2 px-4 py-2.5 text-sm font-medium border-b-2 transition-colors',
                  tab === tabItem.id
                    ? 'border-oe-blue text-oe-blue'
                    : 'border-transparent text-content-secondary hover:text-content-primary',
                )}
              >
                <Icon size={14} />
                {tabItem.label}
              </button>
            );
          })}
        </nav>
      </div>

      {tab === 'resources' && (
        <>
          {/* Filter toolbar — search + type + status + currency + clear */}
          <div
            className="flex flex-wrap items-center gap-2"
            role="search"
            aria-label={t('resources.filter_toolbar_aria', {
              defaultValue: 'Filter resources',
            })}
          >
            <div className="relative flex-1 min-w-[200px] max-w-md">
              <Search
                size={14}
                className="absolute left-3 top-1/2 -translate-y-1/2 text-content-tertiary"
                aria-hidden="true"
              />
              <input
                type="text"
                placeholder={t('resources.search_placeholder', {
                  defaultValue: 'Search code, name or notes…',
                })}
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                className={clsx(inputCls, 'pl-8 pr-8')}
                aria-label={t('common.search', { defaultValue: 'Search' })}
                data-testid="resources-search"
              />
              {search && (
                <button
                  type="button"
                  onClick={() => setSearch('')}
                  aria-label={t('common.clear', { defaultValue: 'Clear' })}
                  className="absolute right-2 top-1/2 -translate-y-1/2 rounded p-1 text-content-tertiary hover:bg-surface-secondary hover:text-content-primary"
                  data-testid="resources-search-clear"
                >
                  <X size={12} />
                </button>
              )}
            </div>
            <select
              value={typeFilter}
              onChange={(e) => setTypeFilter(e.target.value as ResourceType | '')}
              className={clsx(inputCls, 'max-w-[180px]')}
              aria-label={t('resources.filter_type', { defaultValue: 'Filter by type' })}
              data-testid="resources-type-filter"
            >
              <option value="">
                {t('resources.all_types', { defaultValue: 'All types' })}
              </option>
              <option value="person">
                {t('resources.type_person', { defaultValue: 'Person' })}
              </option>
              <option value="crew">
                {t('resources.type_crew', { defaultValue: 'Crew' })}
              </option>
              <option value="equipment">
                {t('resources.type_equipment', { defaultValue: 'Equipment' })}
              </option>
              <option value="subcontractor">
                {t('resources.type_subcontractor', { defaultValue: 'Subcontractor' })}
              </option>
            </select>
            <select
              value={statusFilter}
              onChange={(e) =>
                setStatusFilter(e.target.value as ResourceStatus | '')
              }
              className={clsx(inputCls, 'max-w-[180px]')}
              aria-label={t('resources.filter_status', {
                defaultValue: 'Filter by status',
              })}
              data-testid="resources-status-filter"
            >
              <option value="">
                {t('resources.all_statuses', { defaultValue: 'All statuses' })}
              </option>
              <option value="active">
                {t('resources.status_active', { defaultValue: 'Active' })}
              </option>
              <option value="on_leave">
                {t('resources.status_on_leave', { defaultValue: 'On leave' })}
              </option>
              <option value="inactive">
                {t('resources.status_inactive', { defaultValue: 'Inactive' })}
              </option>
            </select>
            {availableCurrencies.length > 1 && (
              <select
                value={currencyFilter}
                onChange={(e) => setCurrencyFilter(e.target.value)}
                className={clsx(inputCls, 'max-w-[140px]')}
                aria-label={t('resources.filter_currency', {
                  defaultValue: 'Filter by currency',
                })}
                data-testid="resources-currency-filter"
              >
                <option value="">
                  {t('resources.all_currencies', {
                    defaultValue: 'All currencies',
                  })}
                </option>
                {availableCurrencies.map((c) => (
                  <option key={c} value={c}>
                    {c}
                  </option>
                ))}
              </select>
            )}
            {hasActiveFilters && (
              <Button
                size="sm"
                variant="ghost"
                icon={<Filter size={12} />}
                onClick={clearAllFilters}
                data-testid="resources-clear-filters"
                aria-label={t('resources.clear_filters_aria', {
                  defaultValue: 'Clear all filters',
                })}
              >
                {t('resources.clear_filters', { defaultValue: 'Clear filters' })}
              </Button>
            )}
            <div
              className="ms-auto text-xs tabular-nums text-content-tertiary"
              aria-live="polite"
              role="status"
              data-testid="resources-result-count"
            >
              {hasActiveFilters
                ? t('resources.result_count_filtered', {
                    defaultValue: '{{shown}} of {{total}}',
                    shown: filteredResources.length,
                    total: allResources.length,
                  })
                : t('resources.result_count', {
                    defaultValue: '{{count}} resources',
                    count: allResources.length,
                  })}
            </div>
          </div>

          <Card padding="none">
            {isLoading ? (
              <div className="p-4">
                <SkeletonTable rows={8} columns={5} />
              </div>
            ) : resourcesQ.isError ? (
              <EmptyState
                icon={<AlertTriangle size={22} />}
                title={t('resources.load_failed_title', {
                  defaultValue: 'Could not load resources',
                })}
                description={getErrorMessage(resourcesQ.error)}
                action={{
                  label: t('common.retry', { defaultValue: 'Retry' }),
                  onClick: () => resourcesQ.refetch(),
                }}
              />
            ) : (
              <>
                {/* Bulk action bar — visible when at least one row is selected */}
                {selectedIds.size > 0 && (
                  <div
                    className="flex items-center gap-2 border-b border-border-light bg-oe-blue-subtle/40 px-4 py-2 text-xs"
                    data-testid="resources-bulk-bar"
                  >
                    <span className="font-medium">
                      {t('resources.selected_count', {
                        defaultValue: '{{count}} selected',
                        count: selectedIds.size,
                      })}
                    </span>
                    <button
                      type="button"
                      onClick={() => setSelectedIds(new Set())}
                      className="text-content-tertiary hover:text-content-primary"
                    >
                      {t('common.clear', { defaultValue: 'Clear' })}
                    </button>
                    <Button
                      size="sm"
                      variant="ghost"
                      className="ms-auto"
                      icon={<Download size={12} />}
                      onClick={() => {
                        const selectedRows = filteredResources.filter((r) =>
                          selectedIds.has(r.id),
                        );
                        const stamp = new Date().toISOString().slice(0, 10);
                        downloadCsv(
                          `resources-${stamp}.csv`,
                          buildResourcesCsv(selectedRows),
                        );
                      }}
                      data-testid="resources-bulk-export"
                    >
                      {t('resources.bulk_export_csv', {
                        defaultValue: 'Export CSV',
                      })}
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      className="!text-rose-600 hover:!bg-rose-50"
                      icon={<Trash2 size={12} />}
                      onClick={() => setBulkDeleteOpen(true)}
                      data-testid="resources-bulk-delete"
                      disabled={bulkDeleteMut.isPending}
                    >
                      {t('resources.bulk_delete', { defaultValue: 'Delete selected' })}
                    </Button>
                  </div>
                )}
                <ResourceTable
                  rows={filteredResources}
                  total={allResources.length}
                  hasActiveFilters={hasActiveFilters}
                  search={search}
                  selectedIds={selectedIds}
                  onToggleOne={(id) =>
                    setSelectedIds((prev) => {
                      const next = new Set(prev);
                      if (next.has(id)) next.delete(id);
                      else next.add(id);
                      return next;
                    })
                  }
                  onToggleAll={() =>
                    setSelectedIds((prev) =>
                      prev.size === filteredResources.length
                        ? new Set()
                        : new Set(filteredResources.map((r) => r.id)),
                    )
                  }
                  sortKey={sortState.key}
                  sortDir={sortState.dir}
                  onSort={(key) =>
                    setSortState((prev) =>
                      prev.key === key
                        ? { key, dir: prev.dir === 'asc' ? 'desc' : 'asc' }
                        : { key, dir: 'asc' },
                    )
                  }
                  onSelect={(id) => setSelectedId(id)}
                  onEdit={(r) => setEditTarget(r)}
                  onDelete={(r) => setDeleteTarget(r)}
                  emptyAction={() => setCreateOpen(true)}
                  onClearFilters={clearAllFilters}
                  onInlineRateSave={(id, rate) =>
                    inlineRateMut.mutate({ id, rate })
                  }
                  pendingRateId={inlineRateMut.variables?.id ?? null}
                />
              </>
            )}
          </Card>
        </>
      )}

      {tab === 'requests' && (
        <RequestsTab
          projectId={requestsProjectId}
          onProjectChange={(id, name) => {
            setRequestsProjectId(id);
            if (id && name) setActiveProject(id, name);
          }}
          activeProjectName={activeProjectName}
          allResources={allResources}
          newRequestOpen={newRequestOpen}
          onNewRequestOpenChange={setNewRequestOpen}
        />
      )}

      {tab === 'assignments' && (
        <AssignmentsTab
          resources={allResources}
          conflicts={conflictsQ.data ?? []}
          onSelectResource={(id) => setSelectedId(id)}
        />
      )}

      {selectedId && (
        <ResourceDrawer resourceId={selectedId} onClose={() => setSelectedId(null)} />
      )}

      {createOpen && <CreateResourceModal onClose={() => setCreateOpen(false)} />}

      {editTarget && (
        <EditResourceModal
          resource={editTarget}
          onClose={() => setEditTarget(null)}
        />
      )}

      <ConfirmDialog
        open={!!deleteTarget}
        title={t('resources.delete_resource_title', {
          defaultValue: 'Delete this resource?',
        })}
        message={t('resources.delete_resource_msg', {
          defaultValue:
            'This permanently removes the resource. Active assignments referencing it will be blocked - cancel or reassign them first.',
        })}
        confirmLabel={t('common.delete', { defaultValue: 'Delete' })}
        cancelLabel={t('common.cancel', { defaultValue: 'Cancel' })}
        variant="danger"
        loading={deleteResourceMut.isPending}
        onConfirm={() => {
          if (deleteTarget) deleteResourceMut.mutate(deleteTarget.id);
        }}
        onCancel={() => setDeleteTarget(null)}
      />

      <ConfirmDialog
        open={bulkDeleteOpen}
        title={t('resources.bulk_delete_resources_title', {
          defaultValue: 'Delete {{count}} resources?',
          count: selectedIds.size,
        })}
        message={t('resources.bulk_delete_resources_msg', {
          defaultValue:
            'This permanently removes {{count}} resources. Any active assignments referencing them will block their delete - those rows stay and a warning will be shown.',
          count: selectedIds.size,
        })}
        confirmLabel={t('common.delete', { defaultValue: 'Delete' })}
        cancelLabel={t('common.cancel', { defaultValue: 'Cancel' })}
        variant="danger"
        loading={bulkDeleteMut.isPending}
        onConfirm={() => bulkDeleteMut.mutate(Array.from(selectedIds))}
        onCancel={() => setBulkDeleteOpen(false)}
      />

      {proposeOpen && (
        <ProposeAssignmentModal
          resources={allResources}
          onClose={() => setProposeOpen(false)}
        />
      )}
    </div>
  );
}

/* ─── Resource table ───────────────────────────────────────────────────
 *
 * Renders the filtered + sorted resources with:
 *   - bulk-select checkbox column (header = indeterminate when partial)
 *   - sortable headers (code, name, type, status, rate) with aria-sort
 *   - inline rate edit (double-click cell → input → Enter/Esc/blur)
 *   - per-row edit / delete buttons (data-row-action guards row click)
 *
 * Empty state is three-way:
 *   1. No resources at all → CTA to create.
 *   2. Filters active but nothing matches → CTA to clear filters.
 *   3. Search term but nothing matches → quotes the search term.
 */

interface SortableHeaderProps {
  label: string;
  columnKey: ResourceSortKey;
  activeKey: ResourceSortKey;
  dir: SortDir;
  align?: 'left' | 'right';
  onSort: (key: ResourceSortKey) => void;
}

function SortableHeader({
  label,
  columnKey,
  activeKey,
  dir,
  align = 'left',
  onSort,
}: SortableHeaderProps) {
  const isActive = activeKey === columnKey;
  const Arrow = !isActive ? ArrowUpDown : dir === 'asc' ? ArrowUp : ArrowDown;
  return (
    <th
      className={clsx(
        'px-4 py-2.5',
        align === 'right' ? 'text-right' : 'text-left',
      )}
      aria-sort={isActive ? (dir === 'asc' ? 'ascending' : 'descending') : 'none'}
      scope="col"
    >
      <button
        type="button"
        onClick={() => onSort(columnKey)}
        className={clsx(
          'inline-flex items-center gap-1 font-medium uppercase tracking-wide transition-colors',
          isActive ? 'text-content-primary' : 'hover:text-content-primary',
          align === 'right' && 'flex-row-reverse',
        )}
        data-testid={`resources-sort-${columnKey}`}
      >
        {label}
        <Arrow size={11} className={clsx(!isActive && 'opacity-40')} aria-hidden="true" />
      </button>
    </th>
  );
}

interface InlineRateCellProps {
  resource: Resource;
  pending: boolean;
  onSave: (id: string, rate: number) => void;
}

function InlineRateCell({ resource, pending, onSave }: InlineRateCellProps) {
  const { t } = useTranslation();
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(String(resource.default_cost_rate ?? '0'));
  const inputRef = useRef<HTMLInputElement>(null);

  // Re-seed local state whenever the underlying row changes (e.g. server
  // round-trip finished, or another user edited it via WebSocket).
  useEffect(() => {
    if (!editing) setValue(String(resource.default_cost_rate ?? '0'));
  }, [resource.default_cost_rate, editing]);

  useEffect(() => {
    if (editing) {
      inputRef.current?.focus();
      inputRef.current?.select();
    }
  }, [editing]);

  const commit = () => {
    const num = Number(value);
    if (Number.isNaN(num) || num < 0) {
      // Reject silently and restore — the toast would be too noisy for an
      // inline edit. The original value is back, the user sees that.
      setValue(String(resource.default_cost_rate ?? '0'));
      setEditing(false);
      return;
    }
    if (num !== Number(resource.default_cost_rate)) {
      onSave(resource.id, num);
    }
    setEditing(false);
  };

  if (editing) {
    return (
      <input
        ref={inputRef}
        type="number"
        min={0}
        step="0.01"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === 'Enter') commit();
          else if (e.key === 'Escape') {
            setValue(String(resource.default_cost_rate ?? '0'));
            setEditing(false);
          }
        }}
        // Stop the row-click handler firing while the user types.
        onClick={(e) => e.stopPropagation()}
        className="w-24 rounded border border-oe-blue bg-surface-primary px-2 py-0.5 text-right text-sm tabular-nums focus:outline-none focus:ring-2 focus:ring-oe-blue/30"
        aria-label={t('resources.edit_rate_aria', {
          defaultValue: 'Edit rate for {{name}}',
          name: resource.name,
        })}
        data-testid={`resource-rate-input-${resource.id}`}
      />
    );
  }
  return (
    <button
      type="button"
      data-row-action
      onClick={(e) => {
        e.stopPropagation();
        setEditing(true);
      }}
      onDoubleClick={(e) => {
        e.stopPropagation();
        setEditing(true);
      }}
      className={clsx(
        'inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-right tabular-nums transition-colors',
        'hover:bg-oe-blue-subtle hover:text-oe-blue-text',
        pending && 'opacity-50',
      )}
      title={t('resources.edit_rate_hint', {
        defaultValue: 'Click to edit rate',
      })}
      data-testid={`resource-rate-${resource.id}`}
      disabled={pending}
    >
      <MoneyDisplay
        amount={Number(resource.default_cost_rate) || 0}
        currency={resource.currency || undefined}
      />
      {pending && <Loader2 size={10} className="animate-spin" />}
    </button>
  );
}

interface ResourceTableProps {
  rows: Resource[];
  total: number;
  hasActiveFilters: boolean;
  search: string;
  selectedIds: Set<string>;
  onToggleOne: (id: string) => void;
  onToggleAll: () => void;
  sortKey: ResourceSortKey;
  sortDir: SortDir;
  onSort: (key: ResourceSortKey) => void;
  onSelect: (id: string) => void;
  onEdit: (r: Resource) => void;
  onDelete: (r: Resource) => void;
  emptyAction: () => void;
  onClearFilters: () => void;
  onInlineRateSave: (id: string, rate: number) => void;
  pendingRateId: string | null;
}

function ResourceTable({
  rows,
  total,
  hasActiveFilters: _hasActiveFilters,
  search,
  selectedIds,
  onToggleOne,
  onToggleAll,
  sortKey,
  sortDir,
  onSort,
  onSelect,
  onEdit,
  onDelete,
  emptyAction,
  onClearFilters,
  onInlineRateSave,
  pendingRateId,
}: ResourceTableProps) {
  const { t } = useTranslation();

  // Three-way empty state — see header comment above.
  if (rows.length === 0) {
    if (total === 0) {
      return (
        <EmptyState
          icon={<Users size={22} />}
          title={t('resources.empty_title', { defaultValue: 'No resources yet' })}
          description={t('resources.empty_desc', {
            defaultValue:
              'Add people, crews and equipment to start planning their assignments. Click + New Resource to create your first one, or import an Excel file from the catalog page.',
          })}
          action={{
            label: t('resources.new_resource', { defaultValue: 'New Resource' }),
            onClick: emptyAction,
          }}
        />
      );
    }
    if (search.trim()) {
      return (
        <EmptyState
          icon={<Search size={22} />}
          title={t('resources.empty_search_title', {
            defaultValue: 'No resources match "{{q}}"',
            q: search.trim(),
          })}
          description={t('resources.empty_search_desc', {
            defaultValue:
              'Try a shorter search, fewer filters, or check spelling. Search looks at code, name and notes.',
          })}
          action={{
            label: t('resources.clear_filters', { defaultValue: 'Clear filters' }),
            onClick: onClearFilters,
          }}
        />
      );
    }
    return (
      <EmptyState
        icon={<Filter size={22} />}
        title={t('resources.empty_filter_title', {
          defaultValue: 'No resources match the current filters',
        })}
        description={t('resources.empty_filter_desc', {
          defaultValue:
            'Adjust the type, status or currency filter - or clear all filters to see everything.',
        })}
        action={{
          label: t('resources.clear_filters', { defaultValue: 'Clear filters' }),
          onClick: onClearFilters,
        }}
      />
    );
  }

  const allSelected = rows.length > 0 && selectedIds.size === rows.length;
  const someSelected = selectedIds.size > 0 && selectedIds.size < rows.length;

  return (
    <>
      {/* Inline how-to hint above the grid — makes the edit / delete /
          inline-rate-edit affordance discoverable without a dedicated tour. */}
      <div className="flex items-center gap-2 px-4 py-2 text-xs text-content-tertiary border-b border-border-light bg-surface-secondary/40">
        <Pencil size={11} aria-hidden="true" />
        <span>
          {t('resources.row_hint_v2', {
            defaultValue:
              'Click a row for details. Click the rate to edit inline. Use the pencil or trash icons for full edit / delete. Click headers to sort.',
          })}
        </span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm" data-testid="resources-table">
          <thead className="bg-surface-secondary text-content-tertiary text-xs">
            <tr>
              <th className="px-3 py-2.5 text-left w-8" scope="col">
                <input
                  type="checkbox"
                  aria-label={t('common.select_all', { defaultValue: 'Select all' })}
                  checked={allSelected}
                  ref={(el) => {
                    if (el) el.indeterminate = someSelected;
                  }}
                  onChange={onToggleAll}
                  data-testid="resources-select-all"
                />
              </th>
              <SortableHeader
                label={t('resources.col_code', { defaultValue: 'Code' })}
                columnKey="code"
                activeKey={sortKey}
                dir={sortDir}
                onSort={onSort}
              />
              <SortableHeader
                label={t('resources.col_name', { defaultValue: 'Name' })}
                columnKey="name"
                activeKey={sortKey}
                dir={sortDir}
                onSort={onSort}
              />
              <SortableHeader
                label={t('resources.col_type', { defaultValue: 'Type' })}
                columnKey="resource_type"
                activeKey={sortKey}
                dir={sortDir}
                onSort={onSort}
              />
              <SortableHeader
                label={t('resources.col_status', { defaultValue: 'Status' })}
                columnKey="status"
                activeKey={sortKey}
                dir={sortDir}
                onSort={onSort}
              />
              <SortableHeader
                label={t('resources.col_rate', { defaultValue: 'Rate' })}
                columnKey="default_cost_rate"
                activeKey={sortKey}
                dir={sortDir}
                align="right"
                onSort={onSort}
              />
              <th
                className="px-4 py-2.5 text-right w-24 uppercase tracking-wide font-medium"
                scope="col"
              >
                {t('resources.actions', { defaultValue: 'Actions' })}
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              const isSelected = selectedIds.has(r.id);
              return (
                <tr
                  key={r.id}
                  onClick={(e) => {
                    const target = e.target as HTMLElement;
                    // Don't open the drawer when the click came from one of
                    // the per-row action buttons or the checkbox.
                    if (target.closest('[data-row-action]')) return;
                    if (target.closest('input[type="checkbox"]')) return;
                    onSelect(r.id);
                  }}
                  className={clsx(
                    'border-t border-border-light hover:bg-surface-secondary cursor-pointer group',
                    isSelected && 'bg-oe-blue-subtle/20',
                  )}
                  data-testid={`resource-row-${r.id}`}
                  aria-selected={isSelected}
                >
                  <td className="px-3 py-2">
                    <input
                      type="checkbox"
                      checked={isSelected}
                      onChange={() => onToggleOne(r.id)}
                      onClick={(e) => e.stopPropagation()}
                      aria-label={t('common.select_row', {
                        defaultValue: 'Select row',
                      })}
                      data-testid={`resource-select-${r.id}`}
                    />
                  </td>
                  <td className="px-4 py-2 font-mono text-xs tabular-nums text-content-secondary">
                    {r.code}
                  </td>
                  <td className="px-4 py-2 font-medium text-content-primary">
                    {r.name}
                  </td>
                  <td className="px-4 py-2">
                    <Badge variant={TYPE_VARIANT[r.resource_type]} size="sm">
                      {resourceTypeLabel(t, r.resource_type)}
                    </Badge>
                  </td>
                  <td className="px-4 py-2">
                    <Badge
                      variant={
                        r.status === 'active'
                          ? 'success'
                          : r.status === 'on_leave'
                            ? 'warning'
                            : 'neutral'
                      }
                      dot
                      size="sm"
                    >
                      {resourceStatusLabel(t, r.status)}
                    </Badge>
                  </td>
                  <td className="px-4 py-2 text-right">
                    <InlineRateCell
                      resource={r}
                      pending={pendingRateId === r.id}
                      onSave={onInlineRateSave}
                    />
                  </td>
                  <td className="px-4 py-2 text-right">
                    <div className="inline-flex gap-1 opacity-60 group-hover:opacity-100 transition-opacity">
                      <button
                        type="button"
                        data-row-action
                        onClick={(e) => {
                          e.stopPropagation();
                          onEdit(r);
                        }}
                        className="rounded p-1 text-content-secondary hover:text-oe-blue-text hover:bg-oe-blue-subtle"
                        aria-label={t('resources.edit_aria', {
                          defaultValue: 'Edit {{name}}',
                          name: r.name,
                        })}
                        title={t('resources.edit_title', {
                          defaultValue: 'Edit resource',
                        })}
                        data-testid={`resource-edit-${r.id}`}
                      >
                        <Pencil size={13} />
                      </button>
                      <button
                        type="button"
                        data-row-action
                        onClick={(e) => {
                          e.stopPropagation();
                          onDelete(r);
                        }}
                        className="rounded p-1 text-content-secondary hover:text-rose-600 hover:bg-rose-50"
                        aria-label={t('resources.delete_aria', {
                          defaultValue: 'Delete {{name}}',
                          name: r.name,
                        })}
                        title={t('resources.delete_title', {
                          defaultValue: 'Delete resource',
                        })}
                        data-testid={`resource-delete-${r.id}`}
                      >
                        <Trash2 size={13} />
                      </button>
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </>
  );
}

/* ─── Requests tab ─── */
//
// "Resource requests" are demand-side records — a foreman or project
// manager raises a request like "I need 2 carpenters with formwork
// experience next Tuesday-Friday". Dispatchers fulfil them by matching
// an available resource (supply side) → assignment. They are scoped per
// project, so this tab needs a project picker to render real data.
//
// The tab supports the full lifecycle:
//   - Project picker (synced with the global ProjectContext store).
//   - Filters: status, priority, search.
//   - Counters per-status (open / fulfilled / cancelled).
//   - Sortable table with priority + Window + skills + status badges.
//   - Per-row actions: Fulfill, Edit, Cancel, Delete (with confirm).
//   - Create / Edit / Fulfill modals using React Query mutations.

const REQUEST_STATUS_VARIANT: Record<
  RequestStatus,
  'neutral' | 'blue' | 'success' | 'warning' | 'error'
> = {
  open: 'warning',
  fulfilled: 'success',
  cancelled: 'neutral',
};

const PRIORITY_VARIANT: Record<
  RequestPriority,
  'neutral' | 'blue' | 'success' | 'warning' | 'error'
> = {
  low: 'neutral',
  med: 'blue',
  high: 'warning',
  critical: 'error',
};

const PRIORITY_ORDER: Record<RequestPriority, number> = {
  critical: 0,
  high: 1,
  med: 2,
  low: 3,
};

type SortKey = 'priority' | 'start_at' | 'created_at' | 'quantity';

function isoLocalNow(offsetDays = 0): string {
  // datetime-local needs a value WITHOUT trailing Z. Build it from local clock.
  const d = new Date();
  d.setDate(d.getDate() + offsetDays);
  d.setMinutes(d.getMinutes() - d.getTimezoneOffset());
  return d.toISOString().slice(0, 16);
}

function localDatetimeToIso(local: string): string {
  // datetime-local emits "2026-05-14T10:30" in the user's local tz.
  return new Date(local).toISOString();
}

function isoToLocalDatetime(iso: string): string {
  const d = new Date(iso);
  d.setMinutes(d.getMinutes() - d.getTimezoneOffset());
  return d.toISOString().slice(0, 16);
}

interface RequestsTabProps {
  projectId: string;
  onProjectChange: (id: string, name: string) => void;
  activeProjectName: string;
  allResources: Resource[];
  newRequestOpen: boolean;
  onNewRequestOpenChange: (open: boolean) => void;
}

function RequestsTab({
  projectId,
  onProjectChange,
  activeProjectName,
  allResources,
  newRequestOpen,
  onNewRequestOpenChange,
}: RequestsTabProps) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);

  const [statusFilter, setStatusFilter] = useState<RequestStatus | ''>('open');
  const [priorityFilter, setPriorityFilter] = useState<RequestPriority | ''>('');
  const [search, setSearch] = useState('');
  const [sortKey, setSortKey] = useState<SortKey>('priority');
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('asc');

  const [editTarget, setEditTarget] = useState<ResourceRequest | null>(null);
  const [fulfillTarget, setFulfillTarget] = useState<ResourceRequest | null>(null);
  const [confirmDelete, setConfirmDelete] = useState<ResourceRequest | null>(null);
  const [confirmCancel, setConfirmCancel] = useState<ResourceRequest | null>(null);

  const projectsQ = useQuery({
    queryKey: ['resources', 'requests-projects'],
    queryFn: () => projectsApi.list(),
    staleTime: 60_000,
  });

  // Fetch all-status requests so we can show accurate counters even when
  // a status filter is set. The dataset is normally small per project
  // (a few hundred rows at most) so client-side filtering is fine.
  const requestsQ = useQuery({
    queryKey: ['resources', 'requests', projectId],
    queryFn: () =>
      listRequests({
        project_id: projectId,
        limit: 500,
      }),
    enabled: !!projectId,
  });

  // Skill labels for the chips in the table — fetched once per session.
  const skillsQ = useQuery({
    queryKey: ['resources', 'skills', 'all'],
    queryFn: () => listSkills({ limit: 500 }).catch(() => [] as Skill[]),
    staleTime: 300_000,
  });
  const skillIdToName = useMemo(() => {
    const m: Record<string, string> = {};
    for (const s of skillsQ.data ?? []) m[s.id] = s.name;
    return m;
  }, [skillsQ.data]);

  const all = requestsQ.data ?? [];
  const counts = useMemo(() => {
    const c = { open: 0, fulfilled: 0, cancelled: 0, total: all.length };
    for (const r of all) c[r.status]++;
    return c;
  }, [all]);

  const filtered = useMemo(() => {
    const s = search.trim().toLowerCase();
    const rows = all.filter((r) => {
      if (statusFilter && r.status !== statusFilter) return false;
      if (priorityFilter && r.priority !== priorityFilter) return false;
      if (!s) return true;
      return (
        r.title.toLowerCase().includes(s) ||
        r.description.toLowerCase().includes(s)
      );
    });
    const dir = sortDir === 'asc' ? 1 : -1;
    rows.sort((a, b) => {
      let cmp = 0;
      if (sortKey === 'priority') {
        cmp = PRIORITY_ORDER[a.priority] - PRIORITY_ORDER[b.priority];
      } else if (sortKey === 'start_at') {
        cmp = new Date(a.start_at).getTime() - new Date(b.start_at).getTime();
      } else if (sortKey === 'created_at') {
        cmp = new Date(a.created_at).getTime() - new Date(b.created_at).getTime();
      } else if (sortKey === 'quantity') {
        cmp = a.quantity - b.quantity;
      }
      return cmp * dir;
    });
    return rows;
  }, [all, statusFilter, priorityFilter, search, sortKey, sortDir]);

  const invalidateRequests = () => {
    qc.invalidateQueries({ queryKey: ['resources', 'requests', projectId] });
  };

  const updateMut = useMutation({
    mutationFn: ({ id, data }: { id: string; data: Parameters<typeof updateRequest>[1] }) =>
      updateRequest(id, data),
    onSuccess: () => {
      invalidateRequests();
      addToast({
        type: 'success',
        title: t('resources.request_updated_ok', { defaultValue: 'Request updated' }),
      });
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  const deleteMut = useMutation({
    mutationFn: (id: string) => deleteRequest(id),
    onSuccess: () => {
      invalidateRequests();
      addToast({
        type: 'success',
        title: t('resources.request_deleted_ok', { defaultValue: 'Request deleted' }),
      });
      setConfirmDelete(null);
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  const handleSort = (key: SortKey) => {
    if (sortKey === key) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'));
    } else {
      setSortKey(key);
      setSortDir(key === 'priority' ? 'asc' : 'desc');
    }
  };

  const projects = projectsQ.data ?? [];

  return (
    <div className="space-y-4">
      {/* Toolbar — project picker, filters, search, counters */}
      <Card padding="md">
        <div className="flex flex-wrap items-end gap-3">
          <div className="flex-1 min-w-[240px]">
            <label className="block text-xs font-medium text-content-secondary mb-1">
              {t('resources.requests_project_label', {
                defaultValue: 'Project',
              })}
            </label>
            <select
              value={projectId}
              onChange={(e) => {
                const id = e.target.value;
                const name = projects.find((p) => p.id === id)?.name || '';
                onProjectChange(id, name);
              }}
              className={inputCls}
              disabled={projectsQ.isLoading}
              data-testid="requests-project-select"
            >
              <option value="">
                — {t('resources.requests_project_picker_placeholder', {
                  defaultValue: 'Select a project to see its requests…',
                })} —
              </option>
              {projects.map((p) => (
                <option key={p.id} value={p.id}>{p.name}</option>
              ))}
            </select>
          </div>
          <div className="min-w-[140px]">
            <label className="block text-xs font-medium text-content-secondary mb-1">
              {t('resources.requests_status_label', { defaultValue: 'Status' })}
            </label>
            <select
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value as RequestStatus | '')}
              className={inputCls}
              data-testid="requests-status-filter"
            >
              <option value="">{t('resources.status_all', { defaultValue: 'All' })}</option>
              <option value="open">
                {t('resources.req_status_open', { defaultValue: 'Open' })} ({counts.open})
              </option>
              <option value="fulfilled">
                {t('resources.req_status_fulfilled', { defaultValue: 'Fulfilled' })} ({counts.fulfilled})
              </option>
              <option value="cancelled">
                {t('resources.req_status_cancelled', { defaultValue: 'Cancelled' })} ({counts.cancelled})
              </option>
            </select>
          </div>
          <div className="min-w-[140px]">
            <label className="block text-xs font-medium text-content-secondary mb-1">
              {t('resources.requests_priority_label', { defaultValue: 'Priority' })}
            </label>
            <select
              value={priorityFilter}
              onChange={(e) => setPriorityFilter(e.target.value as RequestPriority | '')}
              className={inputCls}
              data-testid="requests-priority-filter"
            >
              <option value="">{t('resources.priority_all', { defaultValue: 'All priorities' })}</option>
              <option value="critical">{t('resources.priority_critical', { defaultValue: 'Critical' })}</option>
              <option value="high">{t('resources.priority_high', { defaultValue: 'High' })}</option>
              <option value="med">{t('resources.priority_med', { defaultValue: 'Medium' })}</option>
              <option value="low">{t('resources.priority_low', { defaultValue: 'Low' })}</option>
            </select>
          </div>
          <div className="min-w-[200px] flex-1">
            <label className="block text-xs font-medium text-content-secondary mb-1">
              {t('common.search', { defaultValue: 'Search' })}
            </label>
            <div className="relative">
              <Search
                size={14}
                className="absolute left-3 top-1/2 -translate-y-1/2 text-content-tertiary"
              />
              <input
                type="text"
                placeholder={t('resources.requests_search_placeholder', {
                  defaultValue: 'Search title or description…',
                })}
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                className={clsx(inputCls, 'pl-8')}
                data-testid="requests-search"
              />
            </div>
          </div>
          <Button
            variant="ghost"
            size="sm"
            icon={<RefreshCw size={12} />}
            onClick={() => invalidateRequests()}
            disabled={!projectId || requestsQ.isFetching}
            loading={requestsQ.isFetching}
            aria-label={t('common.refresh', { defaultValue: 'Refresh' })}
          >
            {t('common.refresh', { defaultValue: 'Refresh' })}
          </Button>
        </div>

        {/* Counter pills */}
        {projectId && all.length > 0 && (
          <div className="mt-3 flex flex-wrap items-center gap-2 text-xs">
            <span className="text-content-secondary">
              {t('resources.requests_summary', { defaultValue: 'In this project' })}:
            </span>
            <button
              type="button"
              onClick={() => setStatusFilter('')}
              className={clsx(
                'px-2 py-0.5 rounded-full border transition-colors',
                statusFilter === ''
                  ? 'border-oe-blue bg-oe-blue/10 text-oe-blue'
                  : 'border-border-light text-content-secondary hover:bg-surface-secondary',
              )}
            >
              {t('resources.status_all', { defaultValue: 'All' })} · {counts.total}
            </button>
            <button
              type="button"
              onClick={() => setStatusFilter('open')}
              className={clsx(
                'px-2 py-0.5 rounded-full border transition-colors',
                statusFilter === 'open'
                  ? 'border-amber-500 bg-amber-50 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300'
                  : 'border-border-light text-content-secondary hover:bg-surface-secondary',
              )}
            >
              {t('resources.req_status_open', { defaultValue: 'Open' })} · {counts.open}
            </button>
            <button
              type="button"
              onClick={() => setStatusFilter('fulfilled')}
              className={clsx(
                'px-2 py-0.5 rounded-full border transition-colors',
                statusFilter === 'fulfilled'
                  ? 'border-emerald-500 bg-emerald-50 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-300'
                  : 'border-border-light text-content-secondary hover:bg-surface-secondary',
              )}
            >
              {t('resources.req_status_fulfilled', { defaultValue: 'Fulfilled' })} · {counts.fulfilled}
            </button>
            <button
              type="button"
              onClick={() => setStatusFilter('cancelled')}
              className={clsx(
                'px-2 py-0.5 rounded-full border transition-colors',
                statusFilter === 'cancelled'
                  ? 'border-border bg-surface-tertiary text-content-primary'
                  : 'border-border-light text-content-secondary hover:bg-surface-secondary',
              )}
            >
              {t('resources.req_status_cancelled', { defaultValue: 'Cancelled' })} · {counts.cancelled}
            </button>
          </div>
        )}

        <p className="mt-3 text-xs text-content-secondary leading-relaxed">
          {t('resources.requests_explainer', {
            defaultValue:
              'Resource requests are "demand-side" records - foremen and PMs raise them when they need people or equipment on a specific date range. Dispatchers fulfil each request by matching one of your resources to it; that creates an assignment row in the Assignments tab.',
          })}
        </p>
      </Card>

      {/* Body */}
      {!projectId ? (
        <Card padding="md">
          <EmptyState
            icon={<ClipboardList size={22} />}
            title={t('resources.requests_pick_project_title', {
              defaultValue: 'Pick a project above to load its requests',
            })}
            description={
              activeProjectName
                ? t('resources.requests_pick_project_active', {
                    defaultValue:
                      'You currently have "{{name}}" active elsewhere - pick it from the dropdown to start.',
                    name: activeProjectName,
                  })
                : t('resources.requests_pick_project_desc', {
                    defaultValue:
                      'Requests are project-scoped - choose a project to see the open queue and start fulfilling.',
                  })
            }
          />
        </Card>
      ) : requestsQ.isLoading ? (
        <Card padding="md">
          <SkeletonTable rows={6} columns={6} />
        </Card>
      ) : requestsQ.isError ? (
        <Card padding="md">
          <EmptyState
            icon={<AlertTriangle size={22} />}
            title={t('resources.requests_load_failed_title', {
              defaultValue: 'Could not load requests',
            })}
            description={getErrorMessage(requestsQ.error)}
            action={{
              label: t('common.retry', { defaultValue: 'Retry' }),
              onClick: () => requestsQ.refetch(),
            }}
          />
        </Card>
      ) : filtered.length === 0 ? (
        <Card padding="md">
          {all.length === 0 ? (
            <EmptyState
              icon={<ClipboardList size={22} />}
              title={t('resources.requests_none_title_for_project', {
                defaultValue: 'No requests on this project yet',
              })}
              description={t('resources.requests_none_desc_for_project', {
                defaultValue:
                  'Open the first request to ask dispatchers for the people, crew or equipment you need.',
              })}
              action={{
                label: t('resources.new_request', { defaultValue: 'New Request' }),
                onClick: () => onNewRequestOpenChange(true),
              }}
            />
          ) : (
            <EmptyState
              icon={<ClipboardList size={22} />}
              title={t('resources.requests_none_title', {
                defaultValue: 'No requests match the current filter',
              })}
              description={t('resources.requests_filter_hint', {
                defaultValue:
                  'Clear filters or try a different status / priority combination.',
              })}
              action={{
                label: t('resources.requests_clear_filters', {
                  defaultValue: 'Clear filters',
                }),
                onClick: () => {
                  setStatusFilter('');
                  setPriorityFilter('');
                  setSearch('');
                },
              }}
            />
          )}
        </Card>
      ) : (
        <Card padding="none">
          <RequestsTable
            rows={filtered}
            skillIdToName={skillIdToName}
            sortKey={sortKey}
            sortDir={sortDir}
            onSort={handleSort}
            onEdit={(r) => setEditTarget(r)}
            onFulfill={(r) => setFulfillTarget(r)}
            onCancel={(r) => setConfirmCancel(r)}
            onDelete={(r) => setConfirmDelete(r)}
            busyIds={
              new Set([
                ...(updateMut.variables ? [updateMut.variables.id] : []),
                ...(deleteMut.variables ? [deleteMut.variables] : []),
              ])
            }
          />
        </Card>
      )}

      {newRequestOpen && projectId && (
        <NewRequestModal
          projectId={projectId}
          skills={skillsQ.data ?? []}
          onClose={() => onNewRequestOpenChange(false)}
          onCreated={() => {
            invalidateRequests();
            onNewRequestOpenChange(false);
          }}
        />
      )}

      {editTarget && (
        <EditRequestModal
          request={editTarget}
          skills={skillsQ.data ?? []}
          onClose={() => setEditTarget(null)}
          onSaved={() => {
            invalidateRequests();
            setEditTarget(null);
          }}
        />
      )}

      {fulfillTarget && (
        <FulfillRequestModal
          request={fulfillTarget}
          resources={allResources}
          onClose={() => setFulfillTarget(null)}
          onFulfilled={() => {
            invalidateRequests();
            qc.invalidateQueries({ queryKey: ['resources', 'assignments'] });
            setFulfillTarget(null);
          }}
        />
      )}

      <ConfirmDialog
        open={!!confirmDelete}
        title={t('resources.delete_request_title', { defaultValue: 'Delete this request?' })}
        message={t('resources.delete_request_msg', {
          defaultValue:
            'This permanently removes the request. Fulfilment history is kept on the assignment but the request itself disappears.',
        })}
        confirmLabel={t('common.delete', { defaultValue: 'Delete' })}
        cancelLabel={t('common.cancel', { defaultValue: 'Cancel' })}
        variant="danger"
        loading={deleteMut.isPending}
        onConfirm={() => {
          if (confirmDelete) deleteMut.mutate(confirmDelete.id);
        }}
        onCancel={() => setConfirmDelete(null)}
      />

      <ConfirmDialog
        open={!!confirmCancel}
        title={t('resources.cancel_request_title', { defaultValue: 'Cancel this request?' })}
        message={t('resources.cancel_request_msg', {
          defaultValue:
            'The request will be marked as cancelled and removed from the open queue. You can still reopen it from the cancelled filter.',
        })}
        confirmLabel={t('resources.cancel_request_confirm', {
          defaultValue: 'Cancel request',
        })}
        cancelLabel={t('common.keep', { defaultValue: 'Keep' })}
        variant="warning"
        loading={updateMut.isPending}
        onConfirm={() => {
          if (confirmCancel) {
            updateMut.mutate(
              { id: confirmCancel.id, data: { status: 'cancelled' } },
              { onSuccess: () => setConfirmCancel(null) },
            );
          }
        }}
        onCancel={() => setConfirmCancel(null)}
      />
    </div>
  );
}

interface RequestsTableProps {
  rows: ResourceRequest[];
  skillIdToName: Record<string, string>;
  sortKey: SortKey;
  sortDir: 'asc' | 'desc';
  onSort: (key: SortKey) => void;
  onEdit: (r: ResourceRequest) => void;
  onFulfill: (r: ResourceRequest) => void;
  onCancel: (r: ResourceRequest) => void;
  onDelete: (r: ResourceRequest) => void;
  busyIds: Set<string>;
}

function RequestsTable({
  rows,
  skillIdToName,
  sortKey,
  sortDir,
  onSort,
  onEdit,
  onFulfill,
  onCancel,
  onDelete,
  busyIds,
}: RequestsTableProps) {
  const { t } = useTranslation();
  const SortArrow = ({ active }: { active: boolean }) => (
    <span
      className={clsx(
        'inline-block ml-1 transition-transform',
        active ? 'opacity-100' : 'opacity-30',
        sortDir === 'desc' && active ? 'rotate-180' : '',
      )}
      aria-hidden="true"
    >
      ▲
    </span>
  );

  return (
    <div className="overflow-x-auto" data-testid="requests-table">
      <table className="min-w-full text-sm">
        <thead className="bg-surface-secondary/50 border-b border-border-light">
          <tr className="text-xs uppercase text-content-secondary">
            <th className="text-left px-4 py-2 font-medium">
              <button
                type="button"
                onClick={() => onSort('priority')}
                className="inline-flex items-center hover:text-content-primary"
              >
                {t('resources.req_col_priority', { defaultValue: 'Priority' })}
                <SortArrow active={sortKey === 'priority'} />
              </button>
            </th>
            <th className="text-left px-4 py-2 font-medium">
              {t('resources.req_col_title', { defaultValue: 'Title' })}
            </th>
            <th className="text-left px-4 py-2 font-medium">
              <button
                type="button"
                onClick={() => onSort('start_at')}
                className="inline-flex items-center hover:text-content-primary"
              >
                {t('resources.req_col_window', { defaultValue: 'Window' })}
                <SortArrow active={sortKey === 'start_at'} />
              </button>
            </th>
            <th className="text-left px-4 py-2 font-medium">
              <button
                type="button"
                onClick={() => onSort('quantity')}
                className="inline-flex items-center hover:text-content-primary"
              >
                {t('resources.req_col_qty', { defaultValue: 'Qty' })}
                <SortArrow active={sortKey === 'quantity'} />
              </button>
            </th>
            <th className="text-left px-4 py-2 font-medium">
              {t('resources.req_col_skills', { defaultValue: 'Skills' })}
            </th>
            <th className="text-left px-4 py-2 font-medium">
              {t('common.status', { defaultValue: 'Status' })}
            </th>
            <th className="text-right px-4 py-2 font-medium">
              {t('resources.actions', { defaultValue: 'Actions' })}
            </th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border-light">
          {rows.map((r) => (
            <RequestRow
              key={r.id}
              r={r}
              skillIdToName={skillIdToName}
              onEdit={() => onEdit(r)}
              onFulfill={() => onFulfill(r)}
              onCancel={() => onCancel(r)}
              onDelete={() => onDelete(r)}
              busy={busyIds.has(r.id)}
            />
          ))}
        </tbody>
      </table>
    </div>
  );
}

interface RequestRowProps {
  r: ResourceRequest;
  skillIdToName: Record<string, string>;
  onEdit: () => void;
  onFulfill: () => void;
  onCancel: () => void;
  onDelete: () => void;
  busy: boolean;
}

function RequestRow({
  r,
  skillIdToName,
  onEdit,
  onFulfill,
  onCancel,
  onDelete,
  busy,
}: RequestRowProps) {
  const { t } = useTranslation();
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

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

  const PriorityIcon =
    r.priority === 'critical' ? Flame : r.priority === 'high' ? AlertOctagon : null;

  const isOpen = r.status === 'open';

  return (
    <tr className="hover:bg-surface-secondary/30">
      <td className="px-4 py-2.5">
        <Badge variant={PRIORITY_VARIANT[r.priority]} size="sm">
          {PriorityIcon && <PriorityIcon size={10} className="inline mr-1" />}
          {requestPriorityLabel(t, r.priority)}
        </Badge>
      </td>
      <td className="px-4 py-2.5">
        <div className="font-medium text-content-primary truncate max-w-xs" title={r.title}>
          {r.title}
        </div>
        {r.description && (
          <div className="text-xs text-content-tertiary truncate max-w-xs" title={r.description}>
            {r.description}
          </div>
        )}
      </td>
      <td className="px-4 py-2.5 text-xs text-content-secondary tabular-nums whitespace-nowrap">
        <DateDisplay value={r.start_at} />
        {' → '}
        <DateDisplay value={r.end_at} />
      </td>
      <td className="px-4 py-2.5 tabular-nums">{r.quantity}</td>
      <td className="px-4 py-2.5">
        <div className="flex flex-wrap gap-1 max-w-xs">
          {r.required_skills.slice(0, 4).map((s) => (
            <Badge key={s} variant="neutral" size="sm">
              {skillIdToName[s] || s.slice(0, 8)}
            </Badge>
          ))}
          {r.required_skills.length > 4 && (
            <span className="text-xs text-content-tertiary">
              +{r.required_skills.length - 4}
            </span>
          )}
          {r.required_skills.length === 0 && (
            <span className="text-xs text-content-tertiary">—</span>
          )}
        </div>
      </td>
      <td className="px-4 py-2.5">
        <Badge variant={REQUEST_STATUS_VARIANT[r.status]} dot size="sm">
          {requestStatusLabel(t, r.status)}
        </Badge>
      </td>
      <td className="px-4 py-2.5 text-right">
        <div className="inline-flex items-center gap-1">
          {isOpen && (
            <Button
              size="sm"
              variant="ghost"
              icon={<UserPlus size={12} />}
              onClick={onFulfill}
              disabled={busy}
              data-testid={`request-fulfill-${r.id}`}
            >
              {t('resources.fulfill', { defaultValue: 'Fulfill' })}
            </Button>
          )}
          <div className="relative" ref={menuRef}>
            <button
              type="button"
              onClick={() => setMenuOpen((o) => !o)}
              className="p-1.5 rounded hover:bg-surface-secondary text-content-secondary"
              aria-label={t('resources.row_actions', { defaultValue: 'Row actions' })}
              aria-haspopup="menu"
              aria-expanded={menuOpen}
              data-testid={`request-menu-${r.id}`}
              disabled={busy}
            >
              {busy ? <Loader2 size={14} className="animate-spin" /> : <MoreHorizontal size={14} />}
            </button>
            {menuOpen && (
              <div
                role="menu"
                className="absolute right-0 z-20 mt-1 w-48 rounded-lg border border-border-light bg-surface-elevated shadow-xl py-1 text-sm"
                data-testid={`request-menu-open-${r.id}`}
              >
                <button
                  type="button"
                  role="menuitem"
                  className="w-full px-3 py-1.5 text-left hover:bg-surface-secondary flex items-center gap-2"
                  onClick={() => {
                    setMenuOpen(false);
                    onEdit();
                  }}
                >
                  <Pencil size={12} />
                  {t('common.edit', { defaultValue: 'Edit' })}
                </button>
                {isOpen && (
                  <button
                    type="button"
                    role="menuitem"
                    className="w-full px-3 py-1.5 text-left hover:bg-surface-secondary flex items-center gap-2"
                    onClick={() => {
                      setMenuOpen(false);
                      onFulfill();
                    }}
                  >
                    <UserPlus size={12} />
                    {t('resources.fulfill', { defaultValue: 'Fulfill' })}
                  </button>
                )}
                {isOpen && (
                  <button
                    type="button"
                    role="menuitem"
                    className="w-full px-3 py-1.5 text-left hover:bg-surface-secondary flex items-center gap-2 text-content-secondary"
                    onClick={() => {
                      setMenuOpen(false);
                      onCancel();
                    }}
                  >
                    <Ban size={12} />
                    {t('resources.cancel_request', { defaultValue: 'Cancel request' })}
                  </button>
                )}
                <div className="my-1 border-t border-border-light" />
                <button
                  type="button"
                  role="menuitem"
                  className="w-full px-3 py-1.5 text-left hover:bg-semantic-error/10 text-semantic-error flex items-center gap-2"
                  onClick={() => {
                    setMenuOpen(false);
                    onDelete();
                  }}
                >
                  <Trash2 size={12} />
                  {t('common.delete', { defaultValue: 'Delete' })}
                </button>
              </div>
            )}
          </div>
        </div>
      </td>
    </tr>
  );
}

/* ─── Request modals ─── */

interface NewRequestModalProps {
  projectId: string;
  skills: Skill[];
  onClose: () => void;
  onCreated: () => void;
}

function NewRequestModal({ projectId, skills, onClose, onCreated }: NewRequestModalProps) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const [busy, setBusy] = useState(false);

  const [form, setForm] = useState({
    title: '',
    description: '',
    start_at: isoLocalNow(1),
    end_at: isoLocalNow(3),
    quantity: 1,
    priority: 'med' as RequestPriority,
    required_skills: [] as string[],
  });

  async function submit() {
    if (!form.title.trim()) {
      addToast({
        type: 'error',
        title: t('resources.title_required', { defaultValue: 'Title is required' }),
      });
      return;
    }
    if (new Date(form.end_at) <= new Date(form.start_at)) {
      addToast({
        type: 'error',
        title: t('resources.window_invalid', {
          defaultValue: 'End must be after start',
        }),
      });
      return;
    }
    setBusy(true);
    try {
      await createRequest({
        project_id: projectId,
        title: form.title.trim(),
        description: form.description.trim(),
        start_at: localDatetimeToIso(form.start_at),
        end_at: localDatetimeToIso(form.end_at),
        quantity: form.quantity,
        priority: form.priority,
        required_skills: form.required_skills,
      });
      addToast({
        type: 'success',
        title: t('resources.request_created_ok', { defaultValue: 'Request created' }),
      });
      onCreated();
    } catch (err) {
      addToast({ type: 'error', title: getErrorMessage(err) });
    } finally {
      setBusy(false);
    }
  }

  return (
    <WideModal
      open
      onClose={onClose}
      busy={busy}
      size="lg"
      title={t('resources.new_request', { defaultValue: 'New Request' })}
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={busy}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button
            variant="primary"
            onClick={submit}
            loading={busy}
            icon={busy ? <Loader2 size={14} /> : <Plus size={14} />}
            data-testid="new-request-submit"
          >
            {t('resources.create_request', { defaultValue: 'Create request' })}
          </Button>
        </>
      }
    >
      <RequestFormFields form={form} setForm={setForm} skills={skills} />
    </WideModal>
  );
}

interface EditRequestModalProps {
  request: ResourceRequest;
  skills: Skill[];
  onClose: () => void;
  onSaved: () => void;
}

function EditRequestModal({ request, skills, onClose, onSaved }: EditRequestModalProps) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const [busy, setBusy] = useState(false);

  const [form, setForm] = useState({
    title: request.title,
    description: request.description,
    start_at: isoToLocalDatetime(request.start_at),
    end_at: isoToLocalDatetime(request.end_at),
    quantity: request.quantity,
    priority: request.priority,
    required_skills: request.required_skills,
  });

  async function submit() {
    if (!form.title.trim()) {
      addToast({
        type: 'error',
        title: t('resources.title_required', { defaultValue: 'Title is required' }),
      });
      return;
    }
    if (new Date(form.end_at) <= new Date(form.start_at)) {
      addToast({
        type: 'error',
        title: t('resources.window_invalid', {
          defaultValue: 'End must be after start',
        }),
      });
      return;
    }
    setBusy(true);
    try {
      await updateRequest(request.id, {
        title: form.title.trim(),
        description: form.description.trim(),
        start_at: localDatetimeToIso(form.start_at),
        end_at: localDatetimeToIso(form.end_at),
        quantity: form.quantity,
        priority: form.priority,
        required_skills: form.required_skills,
      });
      addToast({
        type: 'success',
        title: t('resources.request_updated_ok', { defaultValue: 'Request updated' }),
      });
      onSaved();
    } catch (err) {
      addToast({ type: 'error', title: getErrorMessage(err) });
    } finally {
      setBusy(false);
    }
  }

  return (
    <WideModal
      open
      onClose={onClose}
      busy={busy}
      size="lg"
      title={t('resources.edit_request', { defaultValue: 'Edit Request' })}
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={busy}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button
            variant="primary"
            onClick={submit}
            loading={busy}
            icon={busy ? <Loader2 size={14} /> : <CheckCircle2 size={14} />}
          >
            {t('common.save', { defaultValue: 'Save' })}
          </Button>
        </>
      }
    >
      <RequestFormFields form={form} setForm={setForm} skills={skills} />
    </WideModal>
  );
}

interface RequestFormState {
  title: string;
  description: string;
  start_at: string;
  end_at: string;
  quantity: number;
  priority: RequestPriority;
  required_skills: string[];
}

interface RequestFormFieldsProps {
  form: RequestFormState;
  setForm: React.Dispatch<React.SetStateAction<RequestFormState>>;
  skills: Skill[];
}

function RequestFormFields({ form, setForm, skills }: RequestFormFieldsProps) {
  const { t } = useTranslation();
  return (
    <>
      <WideModalSection columns={2}>
        <WideModalField
          label={t('resources.req_col_title', { defaultValue: 'Title' })}
          required
          span={2}
        >
          <input
            value={form.title}
            onChange={(e) => setForm({ ...form, title: e.target.value })}
            className={inputCls}
            placeholder={t('resources.title_placeholder', {
              defaultValue: 'e.g. 2 carpenters with formwork experience',
            })}
            data-testid="request-form-title"
          />
        </WideModalField>
        <WideModalField
          label={t('common.description', { defaultValue: 'Description' })}
          span={2}
        >
          <textarea
            value={form.description}
            onChange={(e) => setForm({ ...form, description: e.target.value })}
            className={clsx(inputCls, 'h-20 py-2 resize-y')}
            placeholder={t('resources.description_placeholder', {
              defaultValue: 'Optional notes for the dispatcher…',
            })}
          />
        </WideModalField>
        <WideModalField label={t('resources.start', { defaultValue: 'Start' })} required>
          <input
            type="datetime-local"
            value={form.start_at}
            onChange={(e) => setForm({ ...form, start_at: e.target.value })}
            className={inputCls}
          />
        </WideModalField>
        <WideModalField label={t('resources.end', { defaultValue: 'End' })} required>
          <input
            type="datetime-local"
            value={form.end_at}
            onChange={(e) => setForm({ ...form, end_at: e.target.value })}
            className={inputCls}
          />
        </WideModalField>
        <WideModalField label={t('resources.req_col_qty', { defaultValue: 'Quantity' })}>
          <input
            type="number"
            min={1}
            max={999}
            value={form.quantity}
            onChange={(e) =>
              setForm({ ...form, quantity: Math.max(1, Number(e.target.value) || 1) })
            }
            className={inputCls}
          />
        </WideModalField>
        <WideModalField
          label={t('resources.requests_priority_label', { defaultValue: 'Priority' })}
        >
          <select
            value={form.priority}
            onChange={(e) => setForm({ ...form, priority: e.target.value as RequestPriority })}
            className={inputCls}
          >
            <option value="low">{t('resources.priority_low', { defaultValue: 'Low' })}</option>
            <option value="med">{t('resources.priority_med', { defaultValue: 'Medium' })}</option>
            <option value="high">{t('resources.priority_high', { defaultValue: 'High' })}</option>
            <option value="critical">
              {t('resources.priority_critical', { defaultValue: 'Critical' })}
            </option>
          </select>
        </WideModalField>
      </WideModalSection>

      {skills.length > 0 && (
        <WideModalSection
          title={t('resources.required_skills', { defaultValue: 'Required skills' })}
          columns={1}
        >
          <WideModalField
            label={t('resources.required_skills_pick', {
              defaultValue: 'Pick relevant skills',
            })}
          >
            <div className="flex flex-wrap gap-1.5 max-h-48 overflow-y-auto">
              {skills.slice(0, 60).map((s) => {
                const checked = form.required_skills.includes(s.id);
                return (
                  <button
                    type="button"
                    key={s.id}
                    onClick={() =>
                      setForm({
                        ...form,
                        required_skills: checked
                          ? form.required_skills.filter((x) => x !== s.id)
                          : [...form.required_skills, s.id],
                      })
                    }
                    className={clsx(
                      'rounded-full px-2 py-0.5 text-xs border transition-colors',
                      checked
                        ? 'border-oe-blue bg-oe-blue/10 text-oe-blue'
                        : 'border-border-light text-content-secondary hover:bg-surface-secondary',
                    )}
                  >
                    <Wrench size={10} className="inline mr-1" />
                    {s.name}
                  </button>
                );
              })}
            </div>
          </WideModalField>
        </WideModalSection>
      )}
    </>
  );
}

interface FulfillRequestModalProps {
  request: ResourceRequest;
  resources: Resource[];
  onClose: () => void;
  onFulfilled: () => void;
}

function FulfillRequestModal({
  request,
  resources,
  onClose,
  onFulfilled,
}: FulfillRequestModalProps) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const prefCurrency = usePreferencesStore((s) => s.currency);
  const [busy, setBusy] = useState(false);

  // Suggest the first active resource as a default; user can change it.
  const defaultResource = useMemo(
    () => resources.find((r) => r.status === 'active') ?? resources[0],
    [resources],
  );

  const [form, setForm] = useState({
    resource_id: defaultResource?.id ?? '',
    cost_rate: defaultResource ? String(defaultResource.default_cost_rate ?? '0') : '0',
    // Fall back to the user's currency preference (never a hardcoded
    // 'EUR') when the picked resource has no currency of its own.
    currency: defaultResource?.currency || prefCurrency,
    allocation_percent: 100,
    notes: '',
  });

  // When the resource changes, copy its default rate + currency so the
  // dispatcher does not retype them.
  useEffect(() => {
    const r = resources.find((x) => x.id === form.resource_id);
    if (r) {
      setForm((f) => ({
        ...f,
        cost_rate: String(r.default_cost_rate ?? '0'),
        currency: r.currency || f.currency,
      }));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [form.resource_id]);

  async function submit() {
    if (!form.resource_id) {
      addToast({
        type: 'error',
        title: t('resources.pick_resource', { defaultValue: 'Pick a resource.' }),
      });
      return;
    }
    setBusy(true);
    try {
      await fulfillRequest(request.id, {
        resource_id: form.resource_id,
        cost_rate: form.cost_rate,
        currency: form.currency,
        allocation_percent: form.allocation_percent,
        notes: form.notes,
      });
      addToast({
        type: 'success',
        title: t('resources.fulfilled_ok', { defaultValue: 'Request fulfilled' }),
      });
      onFulfilled();
    } catch (err) {
      addToast({ type: 'error', title: resourceErrorMessage(err) });
    } finally {
      setBusy(false);
    }
  }

  return (
    <WideModal
      open
      onClose={onClose}
      busy={busy}
      size="lg"
      title={t('resources.fulfill_request', { defaultValue: 'Fulfill Request' })}
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={busy}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button
            variant="primary"
            onClick={submit}
            loading={busy}
            icon={busy ? <Loader2 size={14} /> : <CheckCircle2 size={14} />}
            data-testid="fulfill-request-submit"
          >
            {t('resources.fulfill', { defaultValue: 'Fulfill' })}
          </Button>
        </>
      }
    >
      <WideModalSection columns={1}>
        <WideModalField label={t('resources.req_col_title', { defaultValue: 'Title' })}>
          <div className="text-sm text-content-primary">{request.title}</div>
          <p className="text-xs text-content-secondary mt-1">
            <DateDisplay value={request.start_at} /> →{' '}
            <DateDisplay value={request.end_at} /> ·{' '}
            {request.quantity} ×{' '}
            <Badge variant={PRIORITY_VARIANT[request.priority]} size="sm">
              {requestPriorityLabel(t, request.priority)}
            </Badge>
          </p>
        </WideModalField>
      </WideModalSection>

      <WideModalSection columns={2}>
        <WideModalField
          label={t('resources.resource', { defaultValue: 'Resource' })}
          required
          span={2}
        >
          <select
            value={form.resource_id}
            onChange={(e) => setForm({ ...form, resource_id: e.target.value })}
            className={inputCls}
            data-testid="fulfill-resource-select"
          >
            <option value="">
              — {t('common.select', { defaultValue: 'Select' })} —
            </option>
            {resources.map((r) => (
              <option key={r.id} value={r.id}>
                {r.code} — {r.name} ({resourceTypeLabel(t, r.resource_type)})
              </option>
            ))}
          </select>
        </WideModalField>
        <WideModalField
          label={t('resources.allocation', { defaultValue: 'Allocation %' })}
        >
          <input
            type="number"
            min={0}
            max={100}
            value={form.allocation_percent}
            onChange={(e) =>
              setForm({
                ...form,
                allocation_percent: Math.min(100, Math.max(0, Number(e.target.value) || 0)),
              })
            }
            className={inputCls}
          />
        </WideModalField>
        <WideModalField label={t('resources.col_rate', { defaultValue: 'Rate' })}>
          <input
            type="number"
            min={0}
            step="0.01"
            value={form.cost_rate}
            onChange={(e) => setForm({ ...form, cost_rate: e.target.value })}
            className={inputCls}
          />
        </WideModalField>
        <WideModalField label={t('common.currency', { defaultValue: 'Currency' })}>
          <input
            value={form.currency}
            onChange={(e) => setForm({ ...form, currency: e.target.value })}
            maxLength={3}
            className={inputCls}
          />
        </WideModalField>
        <WideModalField label={t('common.notes', { defaultValue: 'Notes' })} span={2}>
          <textarea
            value={form.notes}
            onChange={(e) => setForm({ ...form, notes: e.target.value })}
            className={clsx(inputCls, 'h-16 py-2 resize-y')}
            placeholder={t('resources.fulfil_notes_placeholder', {
              defaultValue: 'Optional handoff notes for the assignee…',
            })}
          />
        </WideModalField>
      </WideModalSection>
    </WideModal>
  );
}

/* ─── Assignments tab ─── */

function AssignmentsTab({
  resources,
  conflicts,
  onSelectResource,
}: {
  resources: Resource[];
  conflicts: BoardConflict[];
  onSelectResource: (id: string) => void;
}) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const userRole = useAuthStore((s) => s.userRole);
  // Editor / manager / admin can mutate. Lower roles see a read-only view
  // with the action buttons hidden (the backend RBAC will reject anyway,
  // but we hide the affordance to keep the UI honest).
  const canEdit =
    userRole === 'admin' || userRole === 'manager' || userRole === 'editor';

  const idToName = useMemo(() => {
    const m: Record<string, string> = {};
    for (const r of resources) m[r.id] = r.name;
    return m;
  }, [resources]);

  // Load assignments for ALL resources in one org-wide dispatcher query
  // instead of fanning out per-resource (which previously capped at the
  // first 50 resources and silently dropped assignments for resource #51+).
  // The board returns resources + their assignments for the window in a
  // single round-trip, keeping the list, header count and the side
  // Conflicts panel over the same population. The window starts at the
  // beginning of the current week and extends ~6 months out to cover the
  // "upcoming" assignments the header advertises.
  const boardWindow = useMemo(() => {
    const start = startOfWeek();
    const end = new Date(start);
    end.setMonth(end.getMonth() + 6);
    return { start, end: end.toISOString() };
  }, []);

  const boardQ = useQuery({
    queryKey: ['resources', 'assignments', 'board', boardWindow.start, boardWindow.end],
    queryFn: () => getBoard({ start: boardWindow.start, end: boardWindow.end }),
    staleTime: 30_000,
  });

  const isLoading = boardQ.isLoading;

  // Flatten + sort by start date ascending so "next up" is at the top.
  type FlatAssignment = Assignment & { resource_name: string };
  const flat: FlatAssignment[] = useMemo(() => {
    const out: FlatAssignment[] = [];
    for (const entry of boardQ.data?.entries ?? []) {
      const name = entry.resource.name ?? idToName[entry.resource.id] ?? '';
      for (const a of entry.assignments) {
        out.push({ ...a, resource_name: name });
      }
    }
    out.sort((a, b) => (a.start_at < b.start_at ? -1 : a.start_at > b.start_at ? 1 : 0));
    return out;
  }, [boardQ.data, idToName]);

  const [statusFilter, setStatusFilter] = useState<AssignmentStatus | ''>('');
  const filtered = useMemo(
    () => (statusFilter ? flat.filter((a) => a.status === statusFilter) : flat),
    [flat, statusFilter],
  );

  /* selection + bulk delete */
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const toggleOne = (id: string) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  const toggleAll = () =>
    setSelected((prev) =>
      prev.size === filtered.length ? new Set() : new Set(filtered.map((a) => a.id)),
    );
  // Prune selection if the row disappears (e.g. after delete).
  useEffect(() => {
    const visible = new Set(filtered.map((a) => a.id));
    setSelected((prev) => {
      let changed = false;
      const next = new Set<string>();
      for (const id of prev) {
        if (visible.has(id)) next.add(id);
        else changed = true;
      }
      return changed ? next : prev;
    });
  }, [filtered]);

  /* modals + dialogs */
  const [editing, setEditing] = useState<Assignment | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<Assignment | null>(null);
  const [bulkDeleteOpen, setBulkDeleteOpen] = useState(false);

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ['resources', 'assignments'] });
    qc.invalidateQueries({ queryKey: ['resources', 'dashboard'] });
    qc.invalidateQueries({ queryKey: ['resources', 'conflicts'] });
  };

  const deleteMut = useMutation({
    mutationFn: (id: string) => deleteAssignment(id),
    onSuccess: () => {
      invalidate();
      addToast({
        type: 'success',
        title: t('resources.assign_deleted_ok', {
          defaultValue: 'Assignment deleted',
        }),
      });
      setDeleteTarget(null);
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  const bulkDeleteMut = useMutation({
    mutationFn: async (ids: string[]) => {
      const results = await Promise.allSettled(ids.map((id) => deleteAssignment(id)));
      const failed = results.filter((r) => r.status === 'rejected').length;
      return { total: ids.length, failed };
    },
    onSuccess: ({ total, failed }) => {
      invalidate();
      setSelected(new Set());
      setBulkDeleteOpen(false);
      if (failed === 0) {
        addToast({
          type: 'success',
          title: t('resources.bulk_delete_ok', {
            defaultValue: '{{count}} assignments deleted',
            count: total,
          }),
        });
      } else {
        addToast({
          type: 'warning',
          title: t('resources.bulk_delete_partial', {
            defaultValue: '{{ok}} of {{total}} deleted, {{failed}} failed',
            ok: total - failed,
            total,
            failed,
          }),
        });
      }
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  /* keyboard shortcuts — only when no modal/dialog is open */
  const [focusedId, setFocusedId] = useState<string | null>(null);
  useEffect(() => {
    if (editing || deleteTarget || bulkDeleteOpen) return;
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement)?.tagName;
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;
      if (!focusedId || !canEdit) return;
      const row = filtered.find((a) => a.id === focusedId);
      if (!row) return;
      if (e.key === 'e' || e.key === 'E') {
        e.preventDefault();
        setEditing(row);
      } else if (e.key === 'Delete' || e.key === 'Backspace') {
        e.preventDefault();
        setDeleteTarget(row);
      }
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [editing, deleteTarget, bulkDeleteOpen, focusedId, filtered, canEdit]);

  return (
    <>
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">
        <div className="lg:col-span-2 space-y-3">
          <Card padding="none">
            <div className="flex flex-wrap items-center gap-2 p-3 border-b border-border-light">
              <h3 className="text-sm font-semibold">
                {t('resources.this_week', { defaultValue: 'This week & upcoming' })}
              </h3>
              <span className="text-xs text-content-tertiary tabular-nums">
                {filtered.length}
              </span>
              <div className="ms-auto flex items-center gap-2">
                <select
                  value={statusFilter}
                  onChange={(e) =>
                    setStatusFilter(e.target.value as AssignmentStatus | '')
                  }
                  className={clsx(inputCls, 'max-w-[160px]')}
                  aria-label={t('resources.filter_status', {
                    defaultValue: 'Filter by status',
                  })}
                >
                  <option value="">
                    {t('resources.status_all', { defaultValue: 'All statuses' })}
                  </option>
                  <option value="proposed">
                    {t('resources.status_proposed', { defaultValue: 'Proposed' })}
                  </option>
                  <option value="confirmed">
                    {t('resources.status_confirmed', { defaultValue: 'Confirmed' })}
                  </option>
                  <option value="in_progress">
                    {t('resources.status_in_progress', { defaultValue: 'In progress' })}
                  </option>
                  <option value="completed">
                    {t('resources.status_completed', { defaultValue: 'Completed' })}
                  </option>
                  <option value="cancelled">
                    {t('resources.status_cancelled', { defaultValue: 'Cancelled' })}
                  </option>
                </select>
              </div>
            </div>

            {/* Bulk action bar — shown when at least one row is selected */}
            {canEdit && selected.size > 0 && (
              <div
                className="flex items-center gap-2 border-b border-border-light bg-oe-blue-subtle/40 px-3 py-2 text-xs"
                data-testid="assign-bulk-bar"
              >
                <span className="font-medium">
                  {t('resources.selected_count', {
                    defaultValue: '{{count}} selected',
                    count: selected.size,
                  })}
                </span>
                <button
                  type="button"
                  onClick={() => setSelected(new Set())}
                  className="text-content-tertiary hover:text-content-primary"
                >
                  {t('common.clear', { defaultValue: 'Clear' })}
                </button>
                <Button
                  size="sm"
                  variant="ghost"
                  className="ms-auto !text-rose-600 hover:!bg-rose-50"
                  icon={<Trash2 size={12} />}
                  onClick={() => setBulkDeleteOpen(true)}
                  data-testid="assign-bulk-delete"
                  disabled={bulkDeleteMut.isPending}
                >
                  {t('resources.bulk_delete', { defaultValue: 'Delete selected' })}
                </Button>
              </div>
            )}

            {isLoading ? (
              <div className="p-4">
                <SkeletonTable rows={6} columns={7} />
              </div>
            ) : filtered.length === 0 ? (
              <EmptyState
                icon={<CalendarRange size={22} />}
                title={t('resources.assign_empty_title', {
                  defaultValue: 'No assignments yet',
                })}
                description={t('resources.assign_empty_desc', {
                  defaultValue:
                    'Propose an assignment to put a resource on a project for a specific date range.',
                })}
              />
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="bg-surface-secondary text-content-tertiary text-xs uppercase tracking-wide">
                    <tr>
                      {canEdit && (
                        <th className="px-3 py-2 text-left w-8">
                          <input
                            type="checkbox"
                            aria-label={t('common.select_all', {
                              defaultValue: 'Select all',
                            })}
                            checked={
                              filtered.length > 0 && selected.size === filtered.length
                            }
                            ref={(el) => {
                              if (el)
                                el.indeterminate =
                                  selected.size > 0 && selected.size < filtered.length;
                            }}
                            onChange={toggleAll}
                            data-testid="assign-row-select-all"
                          />
                        </th>
                      )}
                      <th className="px-3 py-2 text-left">
                        {t('resources.col_resource', { defaultValue: 'Resource' })}
                      </th>
                      <th className="px-3 py-2 text-left">
                        {t('resources.col_project_task', {
                          defaultValue: 'Project / Task',
                        })}
                      </th>
                      <th className="px-3 py-2 text-left">
                        {t('resources.start', { defaultValue: 'Start' })}
                      </th>
                      <th className="px-3 py-2 text-left">
                        {t('resources.end', { defaultValue: 'End' })}
                      </th>
                      <th className="px-3 py-2 text-right">
                        {t('resources.alloc', { defaultValue: 'Alloc' })}
                      </th>
                      <th className="px-3 py-2 text-left">
                        {t('resources.col_status', { defaultValue: 'Status' })}
                      </th>
                      <th className="px-3 py-2 text-right">
                        {t('resources.actions', { defaultValue: 'Actions' })}
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {filtered.map((a) => {
                      const isSelected = selected.has(a.id);
                      const isPast = new Date(a.end_at).getTime() < Date.now();
                      return (
                        <tr
                          key={a.id}
                          tabIndex={0}
                          onFocus={() => setFocusedId(a.id)}
                          onClick={(e) => {
                            const target = e.target as HTMLElement;
                            if (
                              target.closest('input,button,[data-testid^="assign-"]')
                            )
                              return;
                            onSelectResource(a.resource_id);
                          }}
                          className={clsx(
                            'border-t border-border-light hover:bg-surface-secondary focus:bg-surface-secondary outline-none',
                            isSelected && 'bg-oe-blue-subtle/20',
                          )}
                          data-testid={`assign-row-${a.id}`}
                        >
                          {canEdit && (
                            <td className="px-3 py-1.5">
                              <input
                                type="checkbox"
                                checked={isSelected}
                                onChange={() => toggleOne(a.id)}
                                aria-label={t('common.select_row', {
                                  defaultValue: 'Select row',
                                })}
                                data-testid={`assign-row-select-${a.id}`}
                              />
                            </td>
                          )}
                          <td className="px-3 py-1.5">
                            <button
                              type="button"
                              className="text-left font-medium text-content-primary hover:text-oe-blue"
                              onClick={() => onSelectResource(a.resource_id)}
                            >
                              {a.resource_name}
                            </button>
                          </td>
                          <td className="px-3 py-1.5 text-xs">
                            <div className="flex flex-col gap-0.5">
                              {a.project_id ? (
                                <button
                                  type="button"
                                  className="inline-flex w-fit items-center gap-1 text-left text-content-primary hover:text-oe-blue hover:underline"
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    navigate(`/projects/${a.project_id}`);
                                  }}
                                  title={t('resources.open_project', {
                                    defaultValue: 'Open project',
                                  })}
                                >
                                  {a.project_name ||
                                    t('resources.untitled_project', {
                                      defaultValue: 'Project',
                                    })}
                                </button>
                              ) : (
                                <span className="text-content-tertiary">
                                  {t('resources.no_project', {
                                    defaultValue: 'Unassigned',
                                  })}
                                </span>
                              )}
                              {a.task_id && (
                                <button
                                  type="button"
                                  className="inline-flex w-fit items-center gap-1 text-left text-2xs text-content-tertiary hover:text-oe-blue hover:underline"
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    // Emits ?taskId for the Tasks page; the deep-link
                                    // consumer is owned by the tasks batch and lands
                                    // separately - until then this opens the Tasks list.
                                    navigate(
                                      `/tasks?taskId=${encodeURIComponent(a.task_id as string)}`,
                                    );
                                  }}
                                  title={t('resources.open_task', {
                                    defaultValue: 'Open task',
                                  })}
                                >
                                  {a.task_name ||
                                    t('resources.linked_task', {
                                      defaultValue: 'Linked task',
                                    })}
                                </button>
                              )}
                            </div>
                          </td>
                          <td className="px-3 py-1.5 text-xs tabular-nums">
                            <DateDisplay value={a.start_at} />
                          </td>
                          <td className="px-3 py-1.5 text-xs tabular-nums">
                            <DateDisplay value={a.end_at} />
                            {isPast && (
                              <span className="ms-1 text-[10px] uppercase text-content-tertiary">
                                ({t('resources.past', { defaultValue: 'past' })})
                              </span>
                            )}
                          </td>
                          <td className="px-3 py-1.5 text-xs tabular-nums text-right">
                            {a.allocation_percent}%
                          </td>
                          <td className="px-3 py-1.5">
                            <Badge variant={ASSIGN_VARIANT[a.status]} dot size="sm">
                              {assignmentStatusLabel(t, a.status)}
                            </Badge>
                          </td>
                          <td className="px-3 py-1.5 text-right">
                            {canEdit ? (
                              <div className="inline-flex gap-1">
                                <button
                                  type="button"
                                  onClick={() => setEditing(a)}
                                  className="rounded p-1 text-content-secondary hover:text-oe-blue-text hover:bg-oe-blue-subtle"
                                  aria-label={t('common.edit', { defaultValue: 'Edit' })}
                                  title={t('common.edit', { defaultValue: 'Edit' })}
                                  data-testid={`assign-edit-${a.id}`}
                                >
                                  <Pencil size={13} />
                                </button>
                                <button
                                  type="button"
                                  onClick={() => setDeleteTarget(a)}
                                  className="rounded p-1 text-content-secondary hover:text-rose-600 hover:bg-rose-50"
                                  aria-label={t('common.delete', {
                                    defaultValue: 'Delete',
                                  })}
                                  title={t('common.delete', { defaultValue: 'Delete' })}
                                  data-testid={`assign-delete-${a.id}`}
                                >
                                  <Trash2 size={13} />
                                </button>
                              </div>
                            ) : (
                              <span
                                className="text-xs text-content-tertiary"
                                title={t('resources.readonly_hint', {
                                  defaultValue:
                                    'Read-only - ask a manager to edit assignments',
                                })}
                              >
                                —
                              </span>
                            )}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </Card>
        </div>

        <div>
          <Card>
            <div className="p-4 border-b border-border-light flex items-center gap-2">
              <AlertTriangle size={14} className="text-semantic-warning" />
              <h3 className="text-sm font-semibold">
                {t('resources.conflicts', { defaultValue: 'Conflicts' })}
              </h3>
              <span className="ms-auto text-xs text-content-tertiary tabular-nums">
                {conflicts.length}
              </span>
            </div>
            {conflicts.length === 0 ? (
              <div className="p-6 text-center text-sm text-content-tertiary">
                {t('resources.conflicts_none', {
                  defaultValue: 'No conflicts this week.',
                })}
              </div>
            ) : (
              <ul className="divide-y divide-border-light">
                {conflicts.map((c) => (
                  <li
                    key={c.resource_id}
                    className="p-4 hover:bg-surface-secondary cursor-pointer"
                    onClick={() => onSelectResource(c.resource_id)}
                  >
                    <p className="text-sm font-medium text-content-primary">
                      {idToName[c.resource_id] || c.resource_name}
                    </p>
                    <p className="mt-0.5 text-xs text-content-secondary">
                      {c.conflicts.length}{' '}
                      {t('resources.overlap_count', { defaultValue: 'overlap(s)' })}
                    </p>
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </div>
      </div>

      {/* Edit assignment modal */}
      {editing && (
        <EditAssignmentModal
          assignment={editing}
          onClose={() => setEditing(null)}
          onSaved={invalidate}
        />
      )}

      {/* Single-row delete confirm */}
      <ConfirmDialog
        open={!!deleteTarget}
        title={t('resources.delete_confirm_title', {
          defaultValue: 'Delete this assignment?',
        })}
        message={t('resources.delete_confirm_msg', {
          defaultValue: 'This action cannot be undone.',
        })}
        confirmLabel={t('common.delete', { defaultValue: 'Delete' })}
        onCancel={() => setDeleteTarget(null)}
        onConfirm={() => deleteTarget && deleteMut.mutate(deleteTarget.id)}
        loading={deleteMut.isPending}
        variant="danger"
      />

      {/* Bulk delete confirm */}
      <ConfirmDialog
        open={bulkDeleteOpen}
        title={t('resources.bulk_delete_title', {
          defaultValue: 'Delete {{count}} assignments?',
          count: selected.size,
        })}
        message={t('resources.bulk_delete_msg', {
          defaultValue:
            'You are about to delete {{count}} assignments. This action cannot be undone.',
          count: selected.size,
        })}
        confirmLabel={t('common.delete', { defaultValue: 'Delete' })}
        onCancel={() => setBulkDeleteOpen(false)}
        onConfirm={() => bulkDeleteMut.mutate(Array.from(selected))}
        loading={bulkDeleteMut.isPending}
        variant="danger"
      />
    </>
  );
}

/* ─── Edit assignment modal ─── */
//
// Pre-filled inline editor for one Assignment. Mirrors ProposeAssignment-
// Modal's field layout for muscle-memory. The resource_id is read-only
// because changing the assignee would effectively delete + re-create
// the row — Propose Assignment is the right entry point for that.

function toDatetimeLocal(iso: string): string {
  // Convert an ISO timestamp to the value format expected by
  // <input type="datetime-local"> (YYYY-MM-DDTHH:mm in local time).
  const d = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(
    d.getHours(),
  )}:${pad(d.getMinutes())}`;
}

function EditAssignmentModal({
  assignment,
  onClose,
  onSaved,
}: {
  assignment: Assignment;
  onClose: () => void;
  onSaved: () => void;
}) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const [form, setForm] = useState({
    start_at: toDatetimeLocal(assignment.start_at),
    end_at: toDatetimeLocal(assignment.end_at),
    allocation_percent: assignment.allocation_percent,
    status: assignment.status,
    notes: assignment.notes ?? '',
  });

  const isPast = new Date(assignment.end_at).getTime() < Date.now();

  const mut = useMutation({
    mutationFn: () =>
      updateAssignment(assignment.id, {
        start_at: new Date(form.start_at).toISOString(),
        end_at: new Date(form.end_at).toISOString(),
        allocation_percent: form.allocation_percent,
        status: form.status as AssignmentStatus,
        notes: form.notes,
      }),
    onSuccess: () => {
      addToast({
        type: 'success',
        title: t('resources.assign_saved_ok', {
          defaultValue: 'Assignment saved',
        }),
      });
      onSaved();
      onClose();
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  const submit = () => {
    if (!form.start_at || !form.end_at) {
      addToast({
        type: 'error',
        title: t('resources.dates_required', {
          defaultValue: 'Start and end are required.',
        }),
      });
      return;
    }
    if (new Date(form.end_at) <= new Date(form.start_at)) {
      addToast({
        type: 'error',
        title: t('resources.end_after_start', {
          defaultValue: 'End must be after start.',
        }),
      });
      return;
    }
    mut.mutate();
  };

  return (
    <WideModal
      open
      onClose={onClose}
      busy={mut.isPending}
      size="lg"
      title={t('resources.edit_assignment', {
        defaultValue: 'Edit assignment',
      })}
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={mut.isPending}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button
            variant="primary"
            onClick={submit}
            loading={mut.isPending}
            data-testid="assign-edit-save"
            icon={mut.isPending ? <Loader2 size={14} /> : <CheckCircle2 size={14} />}
          >
            {t('common.save', { defaultValue: 'Save' })}
          </Button>
        </>
      }
    >
      {isPast && (
        <div
          className="mb-3 flex items-start gap-2 rounded-lg border border-semantic-warning/30 bg-semantic-warning/10 px-3 py-2 text-xs text-semantic-warning"
          data-testid="assign-edit-past-warning"
        >
          <AlertTriangle size={12} className="mt-0.5 shrink-0" />
          <span>
            {t('resources.edit_past_warning', {
              defaultValue:
                'This assignment is in the past - changes are typically only for record corrections.',
            })}
          </span>
        </div>
      )}
      <WideModalSection columns={2}>
        <WideModalField label={t('resources.start', { defaultValue: 'Start' })} required>
          <input
            type="datetime-local"
            name="start_at"
            value={form.start_at}
            onChange={(e) => setForm({ ...form, start_at: e.target.value })}
            className={inputCls}
          />
        </WideModalField>
        <WideModalField label={t('resources.end', { defaultValue: 'End' })} required>
          <input
            type="datetime-local"
            name="end_at"
            value={form.end_at}
            onChange={(e) => setForm({ ...form, end_at: e.target.value })}
            className={inputCls}
          />
        </WideModalField>
        <WideModalField
          label={t('resources.allocation', { defaultValue: 'Allocation %' })}
        >
          <input
            type="number"
            name="allocation_percent"
            min={0}
            max={100}
            value={form.allocation_percent}
            onChange={(e) =>
              setForm({
                ...form,
                allocation_percent: Math.max(0, Math.min(100, Number(e.target.value) || 0)),
              })
            }
            className={inputCls}
          />
        </WideModalField>
        <WideModalField label={t('resources.col_status', { defaultValue: 'Status' })}>
          <select
            name="status"
            value={form.status}
            onChange={(e) =>
              setForm({ ...form, status: e.target.value as AssignmentStatus })
            }
            className={inputCls}
          >
            <option value="proposed">
              {t('resources.status_proposed', { defaultValue: 'Proposed' })}
            </option>
            <option value="confirmed">
              {t('resources.status_confirmed', { defaultValue: 'Confirmed' })}
            </option>
            <option value="in_progress">
              {t('resources.status_in_progress', { defaultValue: 'In progress' })}
            </option>
            <option value="completed">
              {t('resources.status_completed', { defaultValue: 'Completed' })}
            </option>
            <option value="cancelled">
              {t('resources.status_cancelled', { defaultValue: 'Cancelled' })}
            </option>
          </select>
        </WideModalField>
        <WideModalField
          label={t('resources.notes', { defaultValue: 'Notes' })}
          span={2}
        >
          <textarea
            name="notes"
            value={form.notes}
            onChange={(e) => setForm({ ...form, notes: e.target.value })}
            rows={3}
            className={clsx(inputCls, 'h-auto py-2')}
          />
        </WideModalField>
      </WideModalSection>
    </WideModal>
  );
}

/* ─── Resource drawer ─── */

function ResourceDrawer({
  resourceId,
  onClose,
}: {
  resourceId: string;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);

  const dashQ = useQuery({
    queryKey: ['resources', 'dashboard', resourceId],
    queryFn: () => getResourceDashboard(resourceId),
  });

  const timeOffQ = useQuery({
    queryKey: ['resources', 'time-off', resourceId],
    queryFn: () => listWindows(resourceId),
  });

  const confirmMut = useMutation({
    mutationFn: (id: string) => confirmAssignment(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['resources', 'dashboard', resourceId] });
      addToast({
        type: 'success',
        title: t('resources.confirmed_ok', { defaultValue: 'Assignment confirmed' }),
      });
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  const cancelMut = useMutation({
    mutationFn: (id: string) => cancelAssignment(id, 'declined'),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['resources', 'dashboard', resourceId] });
      addToast({
        type: 'success',
        title: t('resources.declined_ok', { defaultValue: 'Assignment declined' }),
      });
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  // Close on Escape — consistent with every other dialog/drawer in the app
  // (WideModal, ConfirmDialog). Without this the slide-over could only be
  // dismissed by mouse, which is an a11y/keyboard-trap regression.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onClose]);

  const data = dashQ.data;
  const timeOff = (timeOffQ.data ?? []).filter(
    (w) => w.window_type !== 'available',
  );
  const loadError = dashQ.isError ? dashQ.error : null;

  return (
    <div className="fixed inset-0 z-50 flex justify-end" onClick={onClose}>
      <div className="absolute inset-0 bg-black/30" />
      <div
        role="dialog"
        aria-modal="true"
        aria-label={t('resources.resource_detail', {
          defaultValue: 'Resource detail',
        })}
        className="relative h-full w-full max-w-xl overflow-y-auto bg-surface-elevated shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="sticky top-0 z-10 flex items-center justify-between border-b border-border-light bg-surface-elevated px-5 py-3">
          <div>
            <h2 className="text-base font-semibold">
              {data?.resource.name ?? t('common.loading', { defaultValue: 'Loading…' })}
            </h2>
            {data && (
              <p className="text-xs text-content-tertiary font-mono">
                {data.resource.code}
              </p>
            )}
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded p-1 hover:bg-surface-secondary"
            aria-label={t('common.close', { defaultValue: 'Close' })}
          >
            <X size={16} />
          </button>
        </div>

        <div className="space-y-4 p-5">
          {dashQ.isLoading && <SkeletonTable rows={5} columns={2} />}
          {loadError && !dashQ.isLoading && (
            <div
              role="alert"
              className="flex items-start gap-2 rounded-lg border border-semantic-error/30 bg-semantic-error/10 px-3 py-2.5 text-sm text-semantic-error"
              data-testid="resource-drawer-error"
            >
              <AlertTriangle size={14} className="mt-0.5 shrink-0" />
              <div className="space-y-1.5">
                <p>{getErrorMessage(loadError)}</p>
                <button
                  type="button"
                  onClick={() => dashQ.refetch()}
                  className="font-medium underline hover:no-underline"
                >
                  {t('common.retry', { defaultValue: 'Retry' })}
                </button>
              </div>
            </div>
          )}
          {data && (
            <>
              <div className="grid grid-cols-2 gap-3 text-sm">
                <Field
                  label={t('resources.col_type')}
                  value={
                    <Badge variant={TYPE_VARIANT[data.resource.resource_type]} size="sm">
                      {resourceTypeLabel(t, data.resource.resource_type)}
                    </Badge>
                  }
                />
                <Field
                  label={t('resources.col_status')}
                  value={
                    <Badge
                      variant={data.resource.status === 'active' ? 'success' : 'neutral'}
                      dot
                      size="sm"
                    >
                      {resourceStatusLabel(t, data.resource.status)}
                    </Badge>
                  }
                />
                <Field
                  label={t('resources.col_rate')}
                  value={
                    <MoneyDisplay
                      amount={Number(data.resource.default_cost_rate) || 0}
                      currency={data.resource.currency || undefined}
                    />
                  }
                />
                <Field
                  label={t('resources.utilization', { defaultValue: 'Utilization (30d)' })}
                  value={
                    data.utilization_30d
                      ? `${data.utilization_30d.utilization_percent.toFixed(0)}%`
                      : '—'
                  }
                />
              </div>

              <Section
                title={t('resources.current_assignments', {
                  defaultValue: 'Current assignments',
                })}
                icon={<HardHat size={14} />}
              >
                {data.active_assignments.length === 0 ? (
                  <EmptyHint
                    text={t('resources.no_active', { defaultValue: 'None active.' })}
                  />
                ) : (
                  <AssignmentTable
                    rows={data.active_assignments}
                    onConfirm={(id) => confirmMut.mutate(id)}
                    onDecline={(id) => cancelMut.mutate(id)}
                    busy={confirmMut.isPending || cancelMut.isPending}
                  />
                )}
              </Section>

              <Section
                title={t('resources.future_commitments', {
                  defaultValue: 'Future commitments',
                })}
                icon={<CalendarRange size={14} />}
              >
                {data.upcoming_assignments.length === 0 ? (
                  <EmptyHint
                    text={t('resources.no_upcoming', { defaultValue: 'No upcoming work.' })}
                  />
                ) : (
                  <AssignmentTable
                    rows={data.upcoming_assignments}
                    onConfirm={(id) => confirmMut.mutate(id)}
                    onDecline={(id) => cancelMut.mutate(id)}
                    busy={confirmMut.isPending || cancelMut.isPending}
                  />
                )}
              </Section>

              <Section
                title={t('resources.time_off', { defaultValue: 'Time off' })}
                icon={<CalendarRange size={14} />}
              >
                {timeOff.length === 0 ? (
                  <EmptyHint
                    text={t('resources.no_time_off', { defaultValue: 'No time off logged.' })}
                  />
                ) : (
                  <ul className="divide-y divide-border-light text-sm">
                    {timeOff.map((w) => (
                      <li
                        key={w.id}
                        className="flex items-center justify-between py-1.5"
                      >
                        <span className="text-content-secondary">
                          {windowTypeLabel(t, w.window_type)}
                          {w.note ? ` · ${w.note}` : ''}
                        </span>
                        <span className="text-content-tertiary text-xs">
                          <DateDisplay value={w.start_at} /> →{' '}
                          <DateDisplay value={w.end_at} />
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
              </Section>

              <Section
                title={t('resources.certifications', { defaultValue: 'Certifications' })}
                icon={<Award size={14} />}
              >
                {data.certifications.length === 0 ? (
                  <EmptyHint
                    text={t('resources.no_certs', { defaultValue: 'No certifications.' })}
                  />
                ) : (
                  <ul className="divide-y divide-border-light text-sm">
                    {data.certifications.map((c) => (
                      <li key={c.id} className="py-1.5">
                        <div className="flex items-center justify-between">
                          <span className="font-medium">{c.cert_type}</span>
                          <Badge
                            variant={c.status === 'valid' ? 'success' : 'warning'}
                            size="sm"
                          >
                            {certStatusLabel(t, c.status)}
                          </Badge>
                        </div>
                        {c.valid_until && (
                          <p className="text-xs text-content-tertiary mt-0.5">
                            {t('resources.valid_until', { defaultValue: 'Valid until' })}:{' '}
                            {c.valid_until}
                          </p>
                        )}
                      </li>
                    ))}
                  </ul>
                )}
              </Section>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

function Section({
  title,
  icon,
  children,
}: {
  title: string;
  icon?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <div>
      <h3 className="mb-2 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-content-tertiary">
        {icon}
        {title}
      </h3>
      {children}
    </div>
  );
}

function EmptyHint({ text }: { text: string }) {
  return <p className="rounded-md bg-surface-secondary/60 p-3 text-xs text-content-tertiary">{text}</p>;
}

function AssignmentTable({
  rows,
  onConfirm,
  onDecline,
  busy,
}: {
  rows: Assignment[];
  onConfirm: (id: string) => void;
  onDecline: (id: string) => void;
  busy: boolean;
}) {
  const { t } = useTranslation();
  const userRole = useAuthStore((s) => s.userRole);
  // Confirm maps to resources.confirm_assignment (MANAGER); Decline maps to
  // cancel which is resources.assign (EDITOR). Hide affordances the user
  // cannot exercise so they don't click a button that always 403s.
  const canConfirm = userRole === 'admin' || userRole === 'manager';
  const canDecline =
    userRole === 'admin' || userRole === 'manager' || userRole === 'editor';
  return (
    <div className="overflow-x-auto rounded border border-border-light">
      <table className="w-full text-sm">
        <thead className="bg-surface-secondary text-content-tertiary text-xs uppercase tracking-wide">
          <tr>
            <th className="px-3 py-2 text-left">
              {t('resources.start', { defaultValue: 'Start' })}
            </th>
            <th className="px-3 py-2 text-left">
              {t('resources.end', { defaultValue: 'End' })}
            </th>
            <th className="px-3 py-2 text-left">
              {t('resources.alloc', { defaultValue: 'Alloc' })}
            </th>
            <th className="px-3 py-2 text-left">
              {t('resources.col_status', { defaultValue: 'Status' })}
            </th>
            <th className="px-3 py-2 text-right">
              {t('resources.actions', { defaultValue: 'Actions' })}
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((a) => (
            <tr key={a.id} className="border-t border-border-light">
              <td className="px-3 py-1.5 text-xs">
                <DateDisplay value={a.start_at} />
              </td>
              <td className="px-3 py-1.5 text-xs">
                <DateDisplay value={a.end_at} />
              </td>
              <td className="px-3 py-1.5 text-xs tabular-nums">
                {a.allocation_percent}%
              </td>
              <td className="px-3 py-1.5">
                <Badge variant={ASSIGN_VARIANT[a.status]} dot size="sm">
                  {assignmentStatusLabel(t, a.status)}
                </Badge>
              </td>
              <td className="px-3 py-1.5 text-right">
                {a.status === 'proposed' && (canConfirm || canDecline) ? (
                  <div className="inline-flex gap-1">
                    {canConfirm && (
                      <Button
                        size="sm"
                        variant="ghost"
                        icon={<CheckCircle2 size={12} />}
                        onClick={() => onConfirm(a.id)}
                        disabled={busy}
                      >
                        {t('resources.confirm', { defaultValue: 'Confirm' })}
                      </Button>
                    )}
                    {canDecline && (
                      <Button
                        size="sm"
                        variant="ghost"
                        icon={<XCircle size={12} />}
                        onClick={() => onDecline(a.id)}
                        disabled={busy}
                      >
                        {t('resources.decline', { defaultValue: 'Decline' })}
                      </Button>
                    )}
                  </div>
                ) : null}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Field({ label, value }: { label: React.ReactNode; value: React.ReactNode }) {
  return (
    <div>
      <p className="text-xs uppercase tracking-wide text-content-tertiary">{label}</p>
      <p className="mt-0.5 text-sm text-content-primary">{value}</p>
    </div>
  );
}

/* ─── Modals ─── */

function CreateResourceModal({ onClose }: { onClose: () => void }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const prefCurrency = usePreferencesStore((s) => s.currency);
  const [busy, setBusy] = useState(false);
  const [form, setForm] = useState({
    code: '',
    name: '',
    resource_type: 'person' as ResourceType,
    default_cost_rate: '0',
    // Seed with the user's currency preference, not a hardcoded 'EUR'.
    currency: prefCurrency,
  });

  async function submit() {
    if (!form.code || !form.name) {
      addToast({
        type: 'error',
        title: t('resources.required_missing', {
          defaultValue: 'Code and name are required.',
        }),
      });
      return;
    }
    setBusy(true);
    try {
      await createResource({
        code: form.code,
        name: form.name,
        resource_type: form.resource_type,
        default_cost_rate: Number(form.default_cost_rate) || 0,
        currency: form.currency,
      });
      addToast({
        type: 'success',
        title: t('resources.created_ok', { defaultValue: 'Resource created' }),
      });
      qc.invalidateQueries({ queryKey: ['resources', 'list'] });
      onClose();
    } catch (err) {
      addToast({ type: 'error', title: getErrorMessage(err) });
    } finally {
      setBusy(false);
    }
  }

  return (
    <WideModal
      open
      onClose={onClose}
      busy={busy}
      size="lg"
      title={t('resources.new_resource', { defaultValue: 'New Resource' })}
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={busy}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button
            variant="primary"
            onClick={submit}
            loading={busy}
            icon={busy ? <Loader2 size={14} /> : <Plus size={14} />}
          >
            {t('common.create', { defaultValue: 'Create' })}
          </Button>
        </>
      }
    >
      <WideModalSection columns={2}>
        <WideModalField label={t('resources.code', { defaultValue: 'Code' })} required>
          <input
            value={form.code}
            onChange={(e) => setForm({ ...form, code: e.target.value })}
            className={inputCls}
            placeholder="e.g. CR-001"
          />
        </WideModalField>
        <WideModalField label={t('resources.name', { defaultValue: 'Name' })} required>
          <input
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
            className={inputCls}
          />
        </WideModalField>
        <WideModalField label={t('resources.col_type', { defaultValue: 'Type' })} span={2}>
          <select
            value={form.resource_type}
            onChange={(e) =>
              setForm({ ...form, resource_type: e.target.value as ResourceType })
            }
            className={inputCls}
          >
            <option value="person">{t('resources.type_person', { defaultValue: 'Person' })}</option>
            <option value="crew">{t('resources.type_crew', { defaultValue: 'Crew' })}</option>
            <option value="equipment">
              {t('resources.type_equipment', { defaultValue: 'Equipment' })}
            </option>
            <option value="subcontractor">
              {t('resources.type_subcontractor', { defaultValue: 'Subcontractor' })}
            </option>
          </select>
        </WideModalField>
        <WideModalField label={t('resources.rate', { defaultValue: 'Rate' })}>
          <input
            type="number"
            value={form.default_cost_rate}
            onChange={(e) =>
              setForm({ ...form, default_cost_rate: e.target.value })
            }
            className={inputCls}
          />
        </WideModalField>
        <WideModalField label={t('common.currency', { defaultValue: 'Currency' })}>
          <input
            value={form.currency}
            onChange={(e) => setForm({ ...form, currency: e.target.value })}
            maxLength={3}
            className={inputCls}
          />
        </WideModalField>
      </WideModalSection>
    </WideModal>
  );
}

/* ─── Edit resource modal ─── */
//
// Mirrors CreateResourceModal's field layout for muscle-memory, but is
// pre-filled from the row the user clicked and adds the two fields
// missing from create (status, notes) which the backend accepts via
// PATCH /resources/{id}.

function EditResourceModal({
  resource,
  onClose,
}: {
  resource: Resource;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [busy, setBusy] = useState(false);
  const [form, setForm] = useState({
    code: resource.code,
    name: resource.name,
    resource_type: resource.resource_type,
    default_cost_rate: String(resource.default_cost_rate ?? '0'),
    currency: resource.currency || '',
    status: resource.status,
    notes: resource.notes ?? '',
  });

  async function submit() {
    if (!form.code.trim() || !form.name.trim()) {
      addToast({
        type: 'error',
        title: t('resources.required_missing', {
          defaultValue: 'Code and name are required.',
        }),
      });
      return;
    }
    const rateNum = Number(form.default_cost_rate);
    if (Number.isNaN(rateNum) || rateNum < 0) {
      addToast({
        type: 'error',
        title: t('resources.rate_invalid', {
          defaultValue: 'Rate must be a non-negative number.',
        }),
      });
      return;
    }
    setBusy(true);
    try {
      await updateResource(resource.id, {
        code: form.code.trim(),
        name: form.name.trim(),
        resource_type: form.resource_type,
        default_cost_rate: rateNum,
        currency: form.currency.trim() || undefined,
        status: form.status,
        notes: form.notes,
      });
      addToast({
        type: 'success',
        title: t('resources.updated_ok', { defaultValue: 'Resource updated' }),
      });
      qc.invalidateQueries({ queryKey: ['resources', 'list'] });
      qc.invalidateQueries({ queryKey: ['resources', 'dashboard', resource.id] });
      onClose();
    } catch (err) {
      addToast({ type: 'error', title: getErrorMessage(err) });
    } finally {
      setBusy(false);
    }
  }

  return (
    <WideModal
      open
      onClose={onClose}
      busy={busy}
      size="lg"
      title={t('resources.edit_resource', { defaultValue: 'Edit Resource' })}
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={busy}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button
            variant="primary"
            onClick={submit}
            loading={busy}
            data-testid="edit-resource-save"
            icon={busy ? <Loader2 size={14} /> : <CheckCircle2 size={14} />}
          >
            {t('common.save', { defaultValue: 'Save' })}
          </Button>
        </>
      }
    >
      <WideModalSection columns={2}>
        <WideModalField label={t('resources.code', { defaultValue: 'Code' })} required>
          <input
            value={form.code}
            onChange={(e) => setForm({ ...form, code: e.target.value })}
            className={inputCls}
            placeholder="e.g. CR-001"
            data-testid="edit-resource-code"
          />
        </WideModalField>
        <WideModalField label={t('resources.name', { defaultValue: 'Name' })} required>
          <input
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
            className={inputCls}
            data-testid="edit-resource-name"
          />
        </WideModalField>
        <WideModalField label={t('resources.col_type', { defaultValue: 'Type' })}>
          <select
            value={form.resource_type}
            onChange={(e) =>
              setForm({ ...form, resource_type: e.target.value as ResourceType })
            }
            className={inputCls}
          >
            <option value="person">
              {t('resources.type_person', { defaultValue: 'Person' })}
            </option>
            <option value="crew">
              {t('resources.type_crew', { defaultValue: 'Crew' })}
            </option>
            <option value="equipment">
              {t('resources.type_equipment', { defaultValue: 'Equipment' })}
            </option>
            <option value="subcontractor">
              {t('resources.type_subcontractor', { defaultValue: 'Subcontractor' })}
            </option>
          </select>
        </WideModalField>
        <WideModalField label={t('resources.col_status', { defaultValue: 'Status' })}>
          <select
            value={form.status}
            onChange={(e) =>
              setForm({ ...form, status: e.target.value as ResourceStatus })
            }
            className={inputCls}
          >
            <option value="active">
              {t('resources.status_active', { defaultValue: 'Active' })}
            </option>
            <option value="on_leave">
              {t('resources.status_on_leave', { defaultValue: 'On leave' })}
            </option>
            <option value="inactive">
              {t('resources.status_inactive', { defaultValue: 'Inactive' })}
            </option>
          </select>
        </WideModalField>
        <WideModalField label={t('resources.rate', { defaultValue: 'Rate' })}>
          <input
            type="number"
            min={0}
            step="0.01"
            value={form.default_cost_rate}
            onChange={(e) =>
              setForm({ ...form, default_cost_rate: e.target.value })
            }
            className={inputCls}
          />
        </WideModalField>
        <WideModalField label={t('common.currency', { defaultValue: 'Currency' })}>
          <input
            value={form.currency}
            onChange={(e) => setForm({ ...form, currency: e.target.value })}
            maxLength={3}
            className={inputCls}
          />
        </WideModalField>
        <WideModalField
          label={t('common.notes', { defaultValue: 'Notes' })}
          span={2}
        >
          <textarea
            value={form.notes}
            onChange={(e) => setForm({ ...form, notes: e.target.value })}
            rows={3}
            className={clsx(inputCls, 'h-auto py-2 resize-y')}
            placeholder={t('resources.notes_placeholder', {
              defaultValue: 'Optional notes about this resource…',
            })}
          />
        </WideModalField>
      </WideModalSection>
    </WideModal>
  );
}

function ProposeAssignmentModal({
  resources,
  onClose,
}: {
  resources: Resource[];
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [busy, setBusy] = useState(false);

  const skillsQ = useQuery({
    queryKey: ['resources', 'skills'],
    queryFn: () => listSkills({ limit: 200 }).catch(() => []),
  });

  // datetime-local inputs are wall-clock and tz-naive. Seeding them from
  // a UTC ISO string and then re-parsing with `new Date` double-applies
  // the timezone offset, so a proposed assignment landed hours away from
  // the time the dispatcher actually picked. Use the same local-clock
  // helpers the other modals use.
  const [form, setForm] = useState({
    resource_id: resources[0]?.id || '',
    start_at: isoLocalNow(0),
    end_at: isoLocalNow(1),
    allocation_percent: 100,
    notes: '',
    required_skills: [] as string[],
  });

  async function submit() {
    if (!form.resource_id) {
      addToast({
        type: 'error',
        title: t('resources.pick_resource', { defaultValue: 'Pick a resource.' }),
      });
      return;
    }
    setBusy(true);
    try {
      if (new Date(form.end_at) <= new Date(form.start_at)) {
        addToast({
          type: 'error',
          title: t('resources.end_after_start', {
            defaultValue: 'End must be after start.',
          }),
        });
        setBusy(false);
        return;
      }
      await proposeAssignment({
        resource_id: form.resource_id,
        start_at: localDatetimeToIso(form.start_at),
        end_at: localDatetimeToIso(form.end_at),
        allocation_percent: form.allocation_percent,
        required_skills: form.required_skills,
        notes: form.notes,
      });
      addToast({
        type: 'success',
        title: t('resources.proposed_ok', { defaultValue: 'Assignment proposed' }),
      });
      qc.invalidateQueries({ queryKey: ['resources'] });
      onClose();
    } catch (err) {
      addToast({ type: 'error', title: resourceErrorMessage(err) });
    } finally {
      setBusy(false);
    }
  }

  return (
    <WideModal
      open
      onClose={onClose}
      busy={busy}
      size="lg"
      title={t('resources.propose', { defaultValue: 'Propose Assignment' })}
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={busy}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button
            variant="primary"
            onClick={submit}
            loading={busy}
            icon={busy ? <Loader2 size={14} /> : <CheckCircle2 size={14} />}
          >
            {t('resources.propose', { defaultValue: 'Propose' })}
          </Button>
        </>
      }
    >
      <WideModalSection columns={2}>
        <WideModalField
          label={t('resources.resource', { defaultValue: 'Resource' })}
          required
          span={2}
        >
          <select
            value={form.resource_id}
            onChange={(e) => setForm({ ...form, resource_id: e.target.value })}
            className={inputCls}
          >
            <option value="">
              — {t('common.select', { defaultValue: 'Select' })} —
            </option>
            {resources.map((r) => (
              <option key={r.id} value={r.id}>
                {r.code} — {r.name}
              </option>
            ))}
          </select>
        </WideModalField>
        <WideModalField label={t('resources.start', { defaultValue: 'Start' })}>
          <input
            type="datetime-local"
            value={form.start_at}
            onChange={(e) => setForm({ ...form, start_at: e.target.value })}
            className={inputCls}
          />
        </WideModalField>
        <WideModalField label={t('resources.end', { defaultValue: 'End' })}>
          <input
            type="datetime-local"
            value={form.end_at}
            onChange={(e) => setForm({ ...form, end_at: e.target.value })}
            className={inputCls}
          />
        </WideModalField>
        <WideModalField
          label={t('resources.allocation', { defaultValue: 'Allocation %' })}
          span={2}
        >
          <input
            type="number"
            min={0}
            max={100}
            value={form.allocation_percent}
            onChange={(e) =>
              setForm({ ...form, allocation_percent: Number(e.target.value) || 0 })
            }
            className={inputCls}
          />
        </WideModalField>
      </WideModalSection>

      {(skillsQ.data?.length ?? 0) > 0 && (
        <WideModalSection
          title={t('resources.required_skills', { defaultValue: 'Required skills' })}
          columns={1}
        >
          <WideModalField label={t('resources.required_skills_pick', { defaultValue: 'Pick relevant skills' })}>
            <div className="flex flex-wrap gap-1.5">
              {(skillsQ.data ?? []).slice(0, 20).map((s) => {
                const checked = form.required_skills.includes(s.id);
                return (
                  <button
                    type="button"
                    key={s.id}
                    onClick={() =>
                      setForm({
                        ...form,
                        required_skills: checked
                          ? form.required_skills.filter((x) => x !== s.id)
                          : [...form.required_skills, s.id],
                      })
                    }
                    className={clsx(
                      'rounded-full px-2 py-0.5 text-xs border transition-colors',
                      checked
                        ? 'border-oe-blue bg-oe-blue/10 text-oe-blue'
                        : 'border-border-light text-content-secondary hover:bg-surface-secondary',
                    )}
                  >
                    <Wrench size={10} className="inline mr-1" />
                    {s.name}
                  </button>
                );
              })}
            </div>
          </WideModalField>
        </WideModalSection>
      )}
    </WideModal>
  );
}

