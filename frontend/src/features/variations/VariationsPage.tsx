import { useState, useMemo, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import clsx from 'clsx';
import {
  Bell,
  FileText,
  FileCheck2,
  Hammer,
  Clock,
  Plus,
  Search,
  X,
  Send,
  CheckCircle2,
  XCircle,
  Loader2,
  ChevronRight,
  ArrowRight,
  Pencil,
  Trash2,
} from 'lucide-react';
import {
  Button,
  Card,
  Badge,
  EmptyState,
  Breadcrumb,
  RecoveryCard,
  SkeletonTable,
  ConfirmDialog,
  DismissibleInfo,
  IntroRichText,
} from '@/shared/ui';
import { useConfirm } from '@/shared/hooks/useConfirm';
import {
  WideModal,
  WideModalSection,
  WideModalField,
} from '@/shared/ui/WideModal';
import { useNavigate } from 'react-router-dom';
import { MoneyDisplay } from '@/shared/ui/MoneyDisplay';
import { DateDisplay } from '@/shared/ui/DateDisplay';
import { PageHeader } from '@/shared/ui/PageHeader';
import { apiGet, getErrorMessage } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { usePreferencesStore } from '@/stores/usePreferencesStore';
import { useTabKeyboardNav } from '@/shared/hooks/useTabKeyboardNav';
import {
  listNotices,
  listVariationRequests,
  listVariationOrders,
  listDaywork,
  listEoTClaims,
  projectDashboard,
  createNotice,
  createVR,
  createVO,
  createDaywork,
  createEoT,
  updateNotice,
  updateVR,
  updateVO,
  updateDaywork,
  updateEoT,
  deleteNotice,
  deleteVR,
  deleteVO,
  deleteDaywork,
  deleteEoT,
  submitVR,
  approveVR,
  rejectVR,
  convertVRToVO,
  acknowledgeNotice,
  respondNotice,
  closeNotice,
  startVO,
  completeVO,
  voidVO,
  signDaywork,
  billDaywork,
  submitEoT,
  grantEoT,
  rejectEoT,
  type Notice,
  type NoticeStatus,
  type VariationRequest,
  type VRStatus,
  type VariationOrder,
  type VOStatus,
  type DayworkSheet,
  type DayworkStatus,
  type ExtensionOfTimeClaim,
  type EotStatus,
} from './api';

const VARIATIONS_TAB_IDS = ['notices', 'requests', 'orders', 'daywork', 'eot'] as const;
type Tab = (typeof VARIATIONS_TAB_IDS)[number];

/** A row currently being edited — carries its tab so the modal can prefill
 *  and PATCH the right sub-entity. */
type EditTarget =
  | { kind: 'notices'; row: Notice }
  | { kind: 'requests'; row: VariationRequest }
  | { kind: 'orders'; row: VariationOrder }
  | { kind: 'daywork'; row: DayworkSheet }
  | { kind: 'eot'; row: ExtensionOfTimeClaim };

const NOTICE_VARIANT: Record<NoticeStatus, 'neutral' | 'blue' | 'success' | 'warning' | 'error'> = {
  issued: 'blue',
  acknowledged: 'warning',
  responded: 'success',
  closed: 'neutral',
};

const VR_VARIANT: Record<VRStatus, 'neutral' | 'blue' | 'success' | 'warning' | 'error'> = {
  draft: 'neutral',
  submitted: 'blue',
  under_review: 'warning',
  approved: 'success',
  rejected: 'error',
  converted_to_vo: 'success',
};

const VO_VARIANT: Record<VOStatus, 'neutral' | 'blue' | 'success' | 'warning' | 'error'> = {
  issued: 'blue',
  in_progress: 'warning',
  completed: 'success',
  voided: 'error',
};

const DAYWORK_VARIANT: Record<DayworkStatus, 'neutral' | 'blue' | 'success' | 'warning' | 'error'> = {
  draft: 'neutral',
  signed: 'success',
  disputed: 'error',
  billed: 'blue',
};

const EOT_VARIANT: Record<EotStatus, 'neutral' | 'blue' | 'success' | 'warning' | 'error'> = {
  draft: 'neutral',
  submitted: 'blue',
  under_review: 'warning',
  granted: 'success',
  rejected: 'error',
};

const inputCls =
  'h-9 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';

interface ProjectStub {
  id: string;
  name: string;
  currency?: string;
}

function listProjectsLite(): Promise<ProjectStub[]> {
  return apiGet<ProjectStub[]>('/v1/projects/?limit=200').catch(() => [] as ProjectStub[]);
}

/**
 * Statuses for which the backend `update_*` service rejects edits.
 * Only Variation Orders have a server-side guard (`update_order` blocks
 * `completed`/`voided`); every other sub-entity's update is unguarded, so
 * Edit stays enabled there. Delete is unguarded everywhere the endpoint
 * exists, so it is always offered.
 */
const EDIT_BLOCKED_STATUS: Partial<Record<Tab, readonly string[]>> = {
  orders: ['completed', 'voided'],
};

function isEditBlocked(kind: Tab, status: string): boolean {
  return (EDIT_BLOCKED_STATUS[kind] ?? []).includes(status);
}

/** Shared ghost Edit/Delete icon buttons rendered in the last table cell.
 *  Mirrors the gold-standard TasksPage row-action pattern. */
function RowActions({
  editBlocked,
  editBlockedReason,
  onEdit,
  onDelete,
}: {
  editBlocked?: boolean;
  editBlockedReason?: string;
  onEdit: () => void;
  onDelete: () => void;
}) {
  const { t } = useTranslation();
  return (
    <div
      className="flex items-center justify-end gap-1"
      onClick={(e) => e.stopPropagation()}
    >
      <Button
        variant="ghost"
        size="sm"
        onClick={onEdit}
        disabled={editBlocked}
        title={
          editBlocked
            ? editBlockedReason ||
              t('variations.edit_blocked', {
                defaultValue: 'This record can no longer be edited',
              })
            : t('common.edit', { defaultValue: 'Edit' })
        }
        className="!p-1 text-content-quaternary hover:text-oe-blue h-auto"
      >
        <Pencil size={13} />
      </Button>
      <Button
        variant="ghost"
        size="sm"
        onClick={onDelete}
        title={t('common.delete', { defaultValue: 'Delete' })}
        className="!p-1 text-content-quaternary hover:text-red-500 h-auto"
      >
        <Trash2 size={13} />
      </Button>
    </div>
  );
}

function DashKPI({
  label,
  value,
}: {
  label: React.ReactNode;
  value: React.ReactNode;
}) {
  return (
    <div className="rounded-lg border border-border-light bg-surface-secondary/50 px-3 py-2">
      <p className="text-[10px] uppercase tracking-wide text-content-tertiary">
        {label}
      </p>
      <p className="mt-0.5 text-sm font-semibold text-content-primary tabular-nums">
        {value}
      </p>
    </div>
  );
}

export function VariationsPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const activeProjectId = useProjectContextStore((s) => s.activeProjectId);

  const projectsQ = useQuery({
    queryKey: ['variations', 'projects'],
    queryFn: listProjectsLite,
    staleTime: 60_000,
  });
  const projects = projectsQ.data ?? [];
  const projectId = activeProjectId || projects[0]?.id || '';
  const currentProject = useMemo(
    () => projects.find((p) => p.id === projectId),
    [projects, projectId],
  );
  // Fall back to the user's configured currency — never a hardcoded
  // literal (the architecture guide: NEVER assume EUR).
  const prefsCurrency = usePreferencesStore((s) => s.currency);
  const currency = currentProject?.currency || prefsCurrency;

  const [tab, setTab] = useState<Tab>('notices');
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState<string>('');
  // Arrow-key navigation across the 5-tab variations strip (WCAG 2.1.1).
  const onTabKeyDown = useTabKeyboardNav<Tab>({
    ids: VARIATIONS_TAB_IDS,
    activeId: tab,
    onChange: (next) => {
      setTab(next);
      setStatusFilter('');
      setSearch('');
    },
    orientation: 'horizontal',
  });
  const [selected, setSelected] = useState<
    | { kind: 'notices'; id: string }
    | { kind: 'requests'; id: string }
    | { kind: 'orders'; id: string }
    | { kind: 'daywork'; id: string }
    | { kind: 'eot'; id: string }
    | null
  >(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [editTarget, setEditTarget] = useState<EditTarget | null>(null);

  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const { confirm, ...confirmProps } = useConfirm();

  const deleteMut = useMutation({
    mutationFn: (target: { kind: Tab; id: string }) => {
      switch (target.kind) {
        case 'notices':
          return deleteNotice(target.id);
        case 'requests':
          return deleteVR(target.id);
        case 'orders':
          return deleteVO(target.id);
        case 'daywork':
          return deleteDaywork(target.id);
        case 'eot':
          return deleteEoT(target.id);
        default:
          return Promise.reject(new Error('unknown kind'));
      }
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['variations'] });
      setSelected(null);
      addToast({
        type: 'success',
        title: t('variations.deleted', { defaultValue: 'Deleted' }),
      });
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  const handleDelete = async (kind: Tab, id: string) => {
    const ok = await confirm({
      title: t('variations.confirm_delete_title', {
        defaultValue: 'Delete this record?',
      }),
      message: t('variations.confirm_delete_msg', {
        defaultValue: 'This record will be permanently deleted. This cannot be undone.',
      }),
      confirmLabel: t('common.delete', { defaultValue: 'Delete' }),
      variant: 'danger',
    });
    if (ok) deleteMut.mutate({ kind, id });
  };

  const dashboardQ = useQuery({
    queryKey: ['variations', 'dashboard', projectId],
    queryFn: () => projectDashboard(projectId),
    enabled: !!projectId,
    retry: false,
    staleTime: 30_000,
  });

  const noticesQ = useQuery({
    queryKey: ['variations', 'notices', projectId, statusFilter],
    queryFn: () =>
      listNotices({ project_id: projectId, status: statusFilter || undefined, limit: 200 }),
    enabled: !!projectId && tab === 'notices',
  });
  const requestsQ = useQuery({
    queryKey: ['variations', 'requests', projectId, statusFilter],
    queryFn: () =>
      listVariationRequests({
        project_id: projectId,
        status: statusFilter || undefined,
        limit: 200,
      }),
    enabled: !!projectId && (tab === 'requests' || tab === 'notices'),
  });
  const ordersQ = useQuery({
    queryKey: ['variations', 'orders', projectId, statusFilter],
    queryFn: () =>
      listVariationOrders({
        project_id: projectId,
        status: statusFilter || undefined,
        limit: 200,
      }),
    enabled: !!projectId && (tab === 'orders' || tab === 'requests'),
  });
  const dayworkQ = useQuery({
    queryKey: ['variations', 'daywork', projectId, statusFilter],
    queryFn: () =>
      listDaywork({
        project_id: projectId,
        status: statusFilter || undefined,
        limit: 200,
      }),
    enabled: !!projectId && tab === 'daywork',
  });
  const eotQ = useQuery({
    queryKey: ['variations', 'eot', projectId, statusFilter],
    queryFn: () =>
      listEoTClaims({
        project_id: projectId,
        status: statusFilter || undefined,
        limit: 200,
      }),
    enabled: !!projectId && tab === 'eot',
  });

  const filteredNotices = useMemo(() => {
    const items = noticesQ.data ?? [];
    if (!search.trim()) return items;
    const s = search.toLowerCase();
    return items.filter(
      (n) =>
        n.code.toLowerCase().includes(s) ||
        (n.title || '').toLowerCase().includes(s) ||
        (n.description || '').toLowerCase().includes(s),
    );
  }, [noticesQ.data, search]);

  const filteredRequests = useMemo(() => {
    const items = requestsQ.data ?? [];
    if (!search.trim()) return items;
    const s = search.toLowerCase();
    return items.filter(
      (r) =>
        r.code.toLowerCase().includes(s) ||
        (r.title || '').toLowerCase().includes(s) ||
        (r.description || '').toLowerCase().includes(s),
    );
  }, [requestsQ.data, search]);

  const filteredOrders = useMemo(() => {
    const items = ordersQ.data ?? [];
    if (!search.trim()) return items;
    const s = search.toLowerCase();
    return items.filter(
      (o) =>
        o.code.toLowerCase().includes(s) || (o.title || '').toLowerCase().includes(s),
    );
  }, [ordersQ.data, search]);

  const filteredDaywork = useMemo(() => {
    const items = dayworkQ.data ?? [];
    if (!search.trim()) return items;
    const s = search.toLowerCase();
    return items.filter(
      (d) =>
        d.sheet_number.toLowerCase().includes(s) ||
        (d.description || '').toLowerCase().includes(s),
    );
  }, [dayworkQ.data, search]);

  const filteredEot = useMemo(() => {
    const items = eotQ.data ?? [];
    if (!search.trim()) return items;
    const s = search.toLowerCase();
    return items.filter((e) => (e.description || '').toLowerCase().includes(s));
  }, [eotQ.data, search]);

  if (!projectId) {
    return (
      <div className="space-y-5 animate-fade-in">
        <Breadcrumb items={[{ label: t('nav.variations', { defaultValue: 'Variations' }) }]} />
        <EmptyState
          icon={<FileText size={22} />}
          title={t('variations.no_project', {
            defaultValue: 'Select a project to manage variations',
          })}
          description={t('variations.no_project_desc', {
            defaultValue:
              'Variations are project-scoped, create or open a project, then return here.',
          })}
        />
      </div>
    );
  }

  const activeQuery =
    tab === 'notices'
      ? noticesQ
      : tab === 'requests'
        ? requestsQ
        : tab === 'orders'
          ? ordersQ
          : tab === 'daywork'
            ? dayworkQ
            : eotQ;
  const isLoading = activeQuery.isLoading;
  const isError = activeQuery.isError;

  const statusOptions: Record<Tab, string[]> = {
    notices: ['issued', 'acknowledged', 'responded', 'closed'],
    requests: ['draft', 'submitted', 'under_review', 'approved', 'rejected', 'converted_to_vo'],
    orders: ['issued', 'in_progress', 'completed', 'voided'],
    daywork: ['draft', 'signed', 'disputed', 'billed'],
    eot: ['draft', 'submitted', 'under_review', 'granted', 'rejected'],
  };

  return (
    <div className="space-y-5 animate-fade-in">
      <Breadcrumb
        items={[
          ...(currentProject
            ? [{ label: currentProject.name, to: `/projects/${currentProject.id}` }]
            : []),
          { label: t('nav.variations', { defaultValue: 'Variations' }) },
        ]}
      />

      {/* Header — project selection lives in the global top bar; no in-page
          project picker. The page reads the shared project context. */}
      <PageHeader
        subtitle={t('variations.subtitle', {
          defaultValue:
            'Track variation notices, requests, orders, daywork and EoT claims through to final account.',
        })}
        actions={
          <Button variant="primary" icon={<Plus size={14} />} onClick={() => setCreateOpen(true)}>
            {tab === 'notices'
              ? t('variations.new_notice', { defaultValue: 'New Notice' })
              : tab === 'requests'
                ? t('variations.new_request', { defaultValue: 'New Request' })
                : tab === 'orders'
                  ? t('variations.new_order', { defaultValue: 'New Order' })
                  : tab === 'daywork'
                    ? t('variations.new_daywork', { defaultValue: 'New Daywork' })
                    : t('variations.new_eot', { defaultValue: 'New EoT Claim' })}
          </Button>
        }
      />

      <DismissibleInfo
        storageKey="variations"
        title={t('variations.intro_title', {
          defaultValue: 'Settle changes before they become disputes',
        })}
        more={
          t('variations.intro_more', { defaultValue: '' })
            ? <IntroRichText text={t('variations.intro_more')} />
            : undefined
        }
        links={[
          {
            label: t('nav.contracts', { defaultValue: 'Contracts' }),
            onClick: () => navigate('/contracts'),
          },
          {
            label: t('nav.finance', { defaultValue: 'Finance' }),
            onClick: () => navigate('/finance'),
          },
          {
            // CONN-48: keep the three change pipelines connected. A variation
            // is the contractual sibling of a Management-of-Change item; one
            // click reaches the MoC register that may have triggered it.
            label: t('moc.title', { defaultValue: 'Management of Change' }),
            onClick: () => navigate('/moc'),
          },
        ]}
      >
        {t('variations.intro_body', {
          defaultValue:
            'Track a change event from a notice, through a priced variation request, to an agreed variation order, with daywork sheets and extension-of-time claims running alongside. On approval the order carries its cost and time impact into the contract final account and rolls up into Finance, so nothing agreed on site is lost at settlement.',
        })}
      </DismissibleInfo>

      {dashboardQ.data && (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-6">
          <DashKPI
            label={t('variations.kpi_notices_open', {
              defaultValue: 'Open notices',
            })}
            value={String(dashboardQ.data.notices_open)}
          />
          <DashKPI
            label={t('variations.kpi_requests_pending', {
              defaultValue: 'Pending requests',
            })}
            value={String(dashboardQ.data.requests_pending)}
          />
          <DashKPI
            label={t('variations.kpi_vo_active', {
              defaultValue: 'Active orders',
            })}
            value={String(dashboardQ.data.variation_orders_active)}
          />
          <DashKPI
            label={t('variations.kpi_cost_impact', {
              defaultValue: 'Cost impact',
            })}
            value={
              <MoneyDisplay
                amount={Number(dashboardQ.data.cost_impact_total) || 0}
                currency={dashboardQ.data.currency || currency}
              />
            }
          />
          <DashKPI
            label={t('variations.kpi_schedule_impact', {
              defaultValue: 'Schedule (days)',
            })}
            value={String(dashboardQ.data.schedule_impact_days)}
          />
          <DashKPI
            label={t('variations.kpi_eot_open', {
              defaultValue: 'Open EoT claims',
            })}
            value={String(dashboardQ.data.eot_claims_open)}
          />
        </div>
      )}

      <div className="border-b border-border-light">
        <nav
          className="flex gap-1 -mb-px"
          role="tablist"
          aria-label={t('variations.tabs_aria', {
            defaultValue: 'Variations sections',
          })}
          onKeyDown={onTabKeyDown}
        >
          {(
            [
              {
                id: 'notices',
                label: t('variations.tab_notices', { defaultValue: 'Notices' }),
                icon: Bell,
              },
              {
                id: 'requests',
                label: t('variations.tab_requests', { defaultValue: 'Requests' }),
                icon: FileText,
              },
              {
                id: 'orders',
                label: t('variations.tab_orders', { defaultValue: 'Orders' }),
                icon: FileCheck2,
              },
              {
                id: 'daywork',
                label: t('variations.tab_daywork', { defaultValue: 'Daywork' }),
                icon: Hammer,
              },
              {
                id: 'eot',
                label: t('variations.tab_eot', { defaultValue: 'EoT Claims' }),
                icon: Clock,
              },
            ] as { id: Tab; label: string; icon: React.ElementType }[]
          ).map((tabItem) => {
            const Icon = tabItem.icon;
            const isActive = tab === tabItem.id;
            return (
              <button
                key={tabItem.id}
                type="button"
                role="tab"
                id={`variations-tab-${tabItem.id}`}
                aria-selected={isActive}
                aria-controls={`variations-panel-${tabItem.id}`}
                tabIndex={isActive ? 0 : -1}
                onClick={() => {
                  setTab(tabItem.id);
                  setStatusFilter('');
                  setSearch('');
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

      <div className="flex flex-wrap items-center gap-2">
        <div className="relative flex-1 min-w-[200px] max-w-md">
          <Search
            size={14}
            className="absolute left-3 top-1/2 -translate-y-1/2 text-content-tertiary"
          />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder={t('common.search', { defaultValue: 'Search…' })}
            className={clsx(inputCls, 'pl-8')}
          />
        </div>
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          className={clsx(inputCls, 'max-w-[220px]')}
        >
          <option value="">{t('common.all_statuses', { defaultValue: 'All statuses' })}</option>
          {statusOptions[tab].map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
      </div>

      <Card padding="none">
        {isLoading ? (
          <div className="p-4">
            <SkeletonTable rows={8} columns={5} />
          </div>
        ) : isError ? (
          <div className="p-4">
            <RecoveryCard
              error={activeQuery.error}
              onRetry={() => {
                void activeQuery.refetch();
              }}
            />
          </div>
        ) : tab === 'notices' ? (
          <NoticeTable
            rows={filteredNotices}
            onSelect={(id) => setSelected({ kind: 'notices', id })}
            onEdit={(row) => setEditTarget({ kind: 'notices', row })}
            onDelete={(id) => void handleDelete('notices', id)}
            emptyAction={() => setCreateOpen(true)}
          />
        ) : tab === 'requests' ? (
          <RequestTable
            rows={filteredRequests}
            currency={currency}
            onSelect={(id) => setSelected({ kind: 'requests', id })}
            onEdit={(row) => setEditTarget({ kind: 'requests', row })}
            onDelete={(id) => void handleDelete('requests', id)}
            emptyAction={() => setCreateOpen(true)}
          />
        ) : tab === 'orders' ? (
          <OrderTable
            rows={filteredOrders}
            currency={currency}
            onSelect={(id) => setSelected({ kind: 'orders', id })}
            onEdit={(row) => setEditTarget({ kind: 'orders', row })}
            onDelete={(id) => void handleDelete('orders', id)}
            emptyAction={() => setCreateOpen(true)}
          />
        ) : tab === 'daywork' ? (
          <DayworkTable
            rows={filteredDaywork}
            currency={currency}
            onSelect={(id) => setSelected({ kind: 'daywork', id })}
            onEdit={(row) => setEditTarget({ kind: 'daywork', row })}
            onDelete={(id) => void handleDelete('daywork', id)}
            emptyAction={() => setCreateOpen(true)}
          />
        ) : (
          <EoTTable
            rows={filteredEot}
            onSelect={(id) => setSelected({ kind: 'eot', id })}
            onEdit={(row) => setEditTarget({ kind: 'eot', row })}
            onDelete={(id) => void handleDelete('eot', id)}
            emptyAction={() => setCreateOpen(true)}
          />
        )}
      </Card>

      {selected && (
        <DetailDrawer
          selected={selected}
          notices={noticesQ.data ?? []}
          requests={requestsQ.data ?? []}
          orders={ordersQ.data ?? []}
          daywork={dayworkQ.data ?? []}
          eot={eotQ.data ?? []}
          currency={currency}
          onClose={() => setSelected(null)}
        />
      )}

      {createOpen && (
        <CreateModal
          kind={tab}
          projectId={projectId}
          currency={currency}
          notices={noticesQ.data ?? []}
          requests={requestsQ.data ?? []}
          onClose={() => setCreateOpen(false)}
        />
      )}

      {editTarget && (
        <CreateModal
          kind={editTarget.kind}
          projectId={projectId}
          currency={currency}
          notices={noticesQ.data ?? []}
          requests={requestsQ.data ?? []}
          editTarget={editTarget}
          onClose={() => setEditTarget(null)}
        />
      )}

      <ConfirmDialog {...confirmProps} />
    </div>
  );
}

/* ─── Tables ─── */

function NoticeTable({
  rows,
  onSelect,
  onEdit,
  onDelete,
  emptyAction,
}: {
  rows: Notice[];
  onSelect: (id: string) => void;
  onEdit: (row: Notice) => void;
  onDelete: (id: string) => void;
  emptyAction: () => void;
}) {
  const { t } = useTranslation();
  if (rows.length === 0) {
    return (
      <EmptyState
        icon={<Bell size={22} />}
        title={t('variations.empty_notices', { defaultValue: 'No notices yet' })}
        description={t('variations.empty_notices_desc', {
          defaultValue: 'Issue a variation notice when a contractual event occurs.',
        })}
        action={{
          label: t('variations.new_notice', { defaultValue: 'New Notice' }),
          onClick: emptyAction,
        }}
      />
    );
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead className="bg-surface-secondary text-content-tertiary text-xs uppercase tracking-wide">
          <tr>
            <th className="px-4 py-2.5 text-left">{t('variations.code', { defaultValue: 'Code' })}</th>
            <th className="px-4 py-2.5 text-left">
              {t('variations.title_col', { defaultValue: 'Title' })}
            </th>
            <th className="px-4 py-2.5 text-left">
              {t('variations.recipient', { defaultValue: 'Recipient' })}
            </th>
            <th className="px-4 py-2.5 text-left">
              {t('variations.target_response', { defaultValue: 'Response by' })}
            </th>
            <th className="px-4 py-2.5 text-left">
              {t('variations.status', { defaultValue: 'Status' })}
            </th>
            <th className="px-4 py-2.5 text-right">
              {t('common.actions', { defaultValue: 'Actions' })}
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr
              key={r.id}
              onClick={() => onSelect(r.id)}
              className="border-t border-border-light hover:bg-surface-secondary cursor-pointer"
            >
              <td className="px-4 py-2 font-mono text-xs text-content-secondary">{r.code}</td>
              <td className="px-4 py-2 font-medium truncate max-w-[420px]">{r.title || '—'}</td>
              <td className="px-4 py-2 text-content-secondary text-xs">
                {r.recipient_name || r.recipient_type}
              </td>
              <td className="px-4 py-2 text-xs text-content-secondary">
                {r.target_response_date ? <DateDisplay value={r.target_response_date} /> : '—'}
              </td>
              <td className="px-4 py-2">
                <Badge variant={NOTICE_VARIANT[r.status]} dot>
                  {r.status}
                </Badge>
              </td>
              <td className="px-4 py-2">
                <RowActions
                  onEdit={() => onEdit(r)}
                  onDelete={() => onDelete(r.id)}
                />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function RequestTable({
  rows,
  currency,
  onSelect,
  onEdit,
  onDelete,
  emptyAction,
}: {
  rows: VariationRequest[];
  currency: string;
  onSelect: (id: string) => void;
  onEdit: (row: VariationRequest) => void;
  onDelete: (id: string) => void;
  emptyAction: () => void;
}) {
  const { t } = useTranslation();
  if (rows.length === 0) {
    return (
      <EmptyState
        icon={<FileText size={22} />}
        title={t('variations.empty_requests', { defaultValue: 'No variation requests yet' })}
        description={t('variations.empty_requests_desc', {
          defaultValue: 'Raise a variation request to estimate cost and schedule impacts.',
        })}
        action={{
          label: t('variations.new_request', { defaultValue: 'New Request' }),
          onClick: emptyAction,
        }}
      />
    );
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead className="bg-surface-secondary text-content-tertiary text-xs uppercase tracking-wide">
          <tr>
            <th className="px-4 py-2.5 text-left">{t('variations.code', { defaultValue: 'Code' })}</th>
            <th className="px-4 py-2.5 text-left">
              {t('variations.title_col', { defaultValue: 'Title' })}
            </th>
            <th className="px-4 py-2.5 text-left">
              {t('variations.classification', { defaultValue: 'Type' })}
            </th>
            <th className="px-4 py-2.5 text-right">
              {t('variations.cost_impact', { defaultValue: 'Cost' })}
            </th>
            <th className="px-4 py-2.5 text-right">
              {t('variations.days', { defaultValue: 'Days' })}
            </th>
            <th className="px-4 py-2.5 text-left">
              {t('variations.status', { defaultValue: 'Status' })}
            </th>
            <th className="px-4 py-2.5 text-right">
              {t('common.actions', { defaultValue: 'Actions' })}
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr
              key={r.id}
              onClick={() => onSelect(r.id)}
              className="border-t border-border-light hover:bg-surface-secondary cursor-pointer"
            >
              <td className="px-4 py-2 font-mono text-xs text-content-secondary">{r.code}</td>
              <td className="px-4 py-2 font-medium truncate max-w-[360px]">{r.title || '—'}</td>
              <td className="px-4 py-2 text-xs text-content-secondary">{r.classification}</td>
              <td className="px-4 py-2 text-right tabular-nums">
                <MoneyDisplay
                  amount={Number(r.estimated_cost_impact) || 0}
                  currency={r.currency || currency}
                />
              </td>
              <td className="px-4 py-2 text-right tabular-nums">{r.estimated_schedule_days}</td>
              <td className="px-4 py-2">
                <Badge variant={VR_VARIANT[r.status]} dot>
                  {r.status}
                </Badge>
              </td>
              <td className="px-4 py-2">
                <RowActions
                  onEdit={() => onEdit(r)}
                  onDelete={() => onDelete(r.id)}
                />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function OrderTable({
  rows,
  currency,
  onSelect,
  onEdit,
  onDelete,
  emptyAction,
}: {
  rows: VariationOrder[];
  currency: string;
  onSelect: (id: string) => void;
  onEdit: (row: VariationOrder) => void;
  onDelete: (id: string) => void;
  emptyAction: () => void;
}) {
  const { t } = useTranslation();
  if (rows.length === 0) {
    return (
      <EmptyState
        icon={<FileCheck2 size={22} />}
        title={t('variations.empty_orders', { defaultValue: 'No variation orders yet' })}
        description={t('variations.empty_orders_desc', {
          defaultValue: 'Variation orders are issued once a request is approved and agreed.',
        })}
        action={{
          label: t('variations.new_order', { defaultValue: 'New Order' }),
          onClick: emptyAction,
        }}
      />
    );
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead className="bg-surface-secondary text-content-tertiary text-xs uppercase tracking-wide">
          <tr>
            <th className="px-4 py-2.5 text-left">{t('variations.code', { defaultValue: 'Code' })}</th>
            <th className="px-4 py-2.5 text-left">
              {t('variations.title_col', { defaultValue: 'Title' })}
            </th>
            <th className="px-4 py-2.5 text-right">
              {t('variations.cost_impact', { defaultValue: 'Cost' })}
            </th>
            <th className="px-4 py-2.5 text-right">
              {t('variations.days', { defaultValue: 'Days' })}
            </th>
            <th className="px-4 py-2.5 text-left">
              {t('variations.agreed_at', { defaultValue: 'Agreed' })}
            </th>
            <th className="px-4 py-2.5 text-left">
              {t('variations.status', { defaultValue: 'Status' })}
            </th>
            <th className="px-4 py-2.5 text-right">
              {t('common.actions', { defaultValue: 'Actions' })}
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr
              key={r.id}
              onClick={() => onSelect(r.id)}
              className="border-t border-border-light hover:bg-surface-secondary cursor-pointer"
            >
              <td className="px-4 py-2 font-mono text-xs text-content-secondary">{r.code}</td>
              <td className="px-4 py-2 font-medium truncate max-w-[360px]">{r.title || '—'}</td>
              <td className="px-4 py-2 text-right tabular-nums">
                <MoneyDisplay
                  amount={Number(r.final_cost_impact) || 0}
                  currency={r.currency || currency}
                />
              </td>
              <td className="px-4 py-2 text-right tabular-nums">{r.final_schedule_days}</td>
              <td className="px-4 py-2 text-xs text-content-secondary">
                {r.agreed_at ? <DateDisplay value={r.agreed_at} /> : '—'}
              </td>
              <td className="px-4 py-2">
                <Badge variant={VO_VARIANT[r.status]} dot>
                  {r.status}
                </Badge>
              </td>
              <td className="px-4 py-2">
                <RowActions
                  editBlocked={isEditBlocked('orders', r.status)}
                  editBlockedReason={t('variations.order_edit_blocked', {
                    defaultValue:
                      'Completed or voided orders can no longer be edited',
                  })}
                  onEdit={() => onEdit(r)}
                  onDelete={() => onDelete(r.id)}
                />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function DayworkTable({
  rows,
  currency,
  onSelect,
  onEdit,
  onDelete,
  emptyAction,
}: {
  rows: DayworkSheet[];
  currency: string;
  onSelect: (id: string) => void;
  onEdit: (row: DayworkSheet) => void;
  onDelete: (id: string) => void;
  emptyAction: () => void;
}) {
  const { t } = useTranslation();
  if (rows.length === 0) {
    return (
      <EmptyState
        icon={<Hammer size={22} />}
        title={t('variations.empty_daywork', { defaultValue: 'No daywork sheets yet' })}
        description={t('variations.empty_daywork_desc', {
          defaultValue: 'Log daily labour, material and equipment for owner sign-off.',
        })}
        action={{
          label: t('variations.new_daywork', { defaultValue: 'New Daywork' }),
          onClick: emptyAction,
        }}
      />
    );
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead className="bg-surface-secondary text-content-tertiary text-xs uppercase tracking-wide">
          <tr>
            <th className="px-4 py-2.5 text-left">
              {t('variations.sheet_no', { defaultValue: 'Sheet #' })}
            </th>
            <th className="px-4 py-2.5 text-left">
              {t('variations.work_date', { defaultValue: 'Date' })}
            </th>
            <th className="px-4 py-2.5 text-left">
              {t('variations.description', { defaultValue: 'Description' })}
            </th>
            <th className="px-4 py-2.5 text-right">
              {t('variations.total', { defaultValue: 'Total' })}
            </th>
            <th className="px-4 py-2.5 text-left">
              {t('variations.status', { defaultValue: 'Status' })}
            </th>
            <th className="px-4 py-2.5 text-right">
              {t('common.actions', { defaultValue: 'Actions' })}
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr
              key={r.id}
              onClick={() => onSelect(r.id)}
              className="border-t border-border-light hover:bg-surface-secondary cursor-pointer"
            >
              <td className="px-4 py-2 font-mono text-xs text-content-secondary">
                {r.sheet_number}
              </td>
              <td className="px-4 py-2 text-xs text-content-secondary">
                {r.work_date ? <DateDisplay value={r.work_date} /> : '—'}
              </td>
              <td className="px-4 py-2 truncate max-w-[360px]">{r.description || '—'}</td>
              <td className="px-4 py-2 text-right tabular-nums">
                <MoneyDisplay
                  amount={Number(r.total_amount) || 0}
                  currency={r.currency || currency}
                />
              </td>
              <td className="px-4 py-2">
                <Badge variant={DAYWORK_VARIANT[r.status]} dot>
                  {r.status}
                </Badge>
              </td>
              <td className="px-4 py-2">
                <RowActions
                  onEdit={() => onEdit(r)}
                  onDelete={() => onDelete(r.id)}
                />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function EoTTable({
  rows,
  onSelect,
  onEdit,
  onDelete,
  emptyAction,
}: {
  rows: ExtensionOfTimeClaim[];
  onSelect: (id: string) => void;
  onEdit: (row: ExtensionOfTimeClaim) => void;
  onDelete: (id: string) => void;
  emptyAction: () => void;
}) {
  const { t } = useTranslation();
  if (rows.length === 0) {
    return (
      <EmptyState
        icon={<Clock size={22} />}
        title={t('variations.empty_eot', { defaultValue: 'No EoT claims yet' })}
        description={t('variations.empty_eot_desc', {
          defaultValue: 'Raise an Extension-of-Time claim when a delay event affects the critical path.',
        })}
        action={{
          label: t('variations.new_eot', { defaultValue: 'New EoT Claim' }),
          onClick: emptyAction,
        }}
      />
    );
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead className="bg-surface-secondary text-content-tertiary text-xs uppercase tracking-wide">
          <tr>
            <th className="px-4 py-2.5 text-left">
              {t('variations.description', { defaultValue: 'Description' })}
            </th>
            <th className="px-4 py-2.5 text-left">
              {t('variations.cause', { defaultValue: 'Cause' })}
            </th>
            <th className="px-4 py-2.5 text-right">
              {t('variations.requested_days', { defaultValue: 'Requested' })}
            </th>
            <th className="px-4 py-2.5 text-right">
              {t('variations.granted_days', { defaultValue: 'Granted' })}
            </th>
            <th className="px-4 py-2.5 text-left">
              {t('variations.critical_path', { defaultValue: 'CP' })}
            </th>
            <th className="px-4 py-2.5 text-left">
              {t('variations.status', { defaultValue: 'Status' })}
            </th>
            <th className="px-4 py-2.5 text-right">
              {t('common.actions', { defaultValue: 'Actions' })}
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr
              key={r.id}
              onClick={() => onSelect(r.id)}
              className="border-t border-border-light hover:bg-surface-secondary cursor-pointer"
            >
              <td className="px-4 py-2 truncate max-w-[360px]">{r.description || '—'}</td>
              <td className="px-4 py-2 text-xs text-content-secondary">{r.root_cause_category}</td>
              <td className="px-4 py-2 text-right tabular-nums">{r.requested_days}</td>
              <td className="px-4 py-2 text-right tabular-nums">
                {r.granted_days ?? '—'}
              </td>
              <td className="px-4 py-2 text-xs">
                {r.critical_path_impact ? (
                  <Badge variant="warning">CP</Badge>
                ) : (
                  <span className="text-content-tertiary">—</span>
                )}
              </td>
              <td className="px-4 py-2">
                <Badge variant={EOT_VARIANT[r.status]} dot>
                  {r.status}
                </Badge>
              </td>
              <td className="px-4 py-2">
                <RowActions
                  onEdit={() => onEdit(r)}
                  onDelete={() => onDelete(r.id)}
                />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/* ─── Detail drawer with workflow stepper ─── */

function WorkflowStepper({
  notice,
  request,
  order,
}: {
  notice: Notice | null;
  request: VariationRequest | null;
  order: VariationOrder | null;
}) {
  const { t } = useTranslation();
  const steps = [
    {
      label: t('variations.step_notice', { defaultValue: 'Notice' }),
      present: !!notice,
      status: notice?.status,
    },
    {
      label: t('variations.step_request', { defaultValue: 'Request' }),
      present: !!request,
      status: request?.status,
    },
    {
      label: t('variations.step_order', { defaultValue: 'Order' }),
      present: !!order,
      status: order?.status,
    },
  ];
  return (
    <div className="flex items-center gap-1.5 text-xs">
      {steps.map((s, idx) => (
        <div key={s.label} className="flex items-center gap-1.5">
          <span
            className={clsx(
              'rounded-full px-2 py-0.5 border',
              s.present
                ? 'bg-oe-blue/10 border-oe-blue text-oe-blue'
                : 'border-border-light text-content-tertiary',
            )}
          >
            {s.label}
            {s.status ? ` · ${s.status}` : ''}
          </span>
          {idx < steps.length - 1 && <ChevronRight size={12} className="text-content-tertiary" />}
        </div>
      ))}
    </div>
  );
}

function DetailDrawer({
  selected,
  notices,
  requests,
  orders,
  daywork,
  eot,
  currency,
  onClose,
}: {
  selected:
    | { kind: 'notices'; id: string }
    | { kind: 'requests'; id: string }
    | { kind: 'orders'; id: string }
    | { kind: 'daywork'; id: string }
    | { kind: 'eot'; id: string };
  notices: Notice[];
  requests: VariationRequest[];
  orders: VariationOrder[];
  daywork: DayworkSheet[];
  eot: ExtensionOfTimeClaim[];
  currency: string;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const addToast = useToastStore((s) => s.addToast);

  const notice = selected.kind === 'notices' ? notices.find((n) => n.id === selected.id) : null;
  const request = selected.kind === 'requests' ? requests.find((r) => r.id === selected.id) : null;
  const order = selected.kind === 'orders' ? orders.find((o) => o.id === selected.id) : null;
  const sheet = selected.kind === 'daywork' ? daywork.find((d) => d.id === selected.id) : null;
  const claim = selected.kind === 'eot' ? eot.find((e) => e.id === selected.id) : null;

  const chainNotice = request
    ? notices.find((n) => n.id === request.notice_id) ?? null
    : notice;
  const chainRequest = order
    ? requests.find((r) => r.id === order.variation_request_id) ?? null
    : request;
  const chainOrder = request
    ? orders.find((o) => o.variation_request_id === request.id) ?? null
    : order;

  /* Notice transitions */
  const ackMut = useMutation({
    mutationFn: () => acknowledgeNotice(selected.id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['variations'] });
      addToast({ type: 'success', title: t('variations.acknowledged', { defaultValue: 'Notice acknowledged' }) });
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });
  const [respText, setRespText] = useState('');
  const respMut = useMutation({
    mutationFn: () => respondNotice(selected.id, respText.trim() || undefined),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['variations'] });
      setRespText('');
      addToast({ type: 'success', title: t('variations.responded', { defaultValue: 'Response logged' }) });
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });
  const closeNoticeMut = useMutation({
    mutationFn: () => closeNotice(selected.id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['variations'] });
      addToast({ type: 'success', title: t('variations.notice_closed', { defaultValue: 'Notice closed' }) });
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  /* Request transitions */
  const submitVrMut = useMutation({
    mutationFn: () => submitVR(selected.id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['variations'] });
      addToast({ type: 'success', title: t('variations.vr_submitted', { defaultValue: 'Request submitted' }) });
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });
  const [decisionNotes, setDecisionNotes] = useState('');
  const approveMut = useMutation({
    mutationFn: () => approveVR(selected.id, decisionNotes.trim() || undefined),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['variations'] });
      setDecisionNotes('');
      addToast({ type: 'success', title: t('variations.vr_approved', { defaultValue: 'Request approved' }) });
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });
  const rejectMut = useMutation({
    mutationFn: () => rejectVR(selected.id, decisionNotes.trim() || undefined),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['variations'] });
      setDecisionNotes('');
      addToast({ type: 'success', title: t('variations.vr_rejected', { defaultValue: 'Request rejected' }) });
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });
  const convertMut = useMutation({
    mutationFn: () =>
      convertVRToVO(selected.id, request ? { currency: request.currency || currency } : {}),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['variations'] });
      addToast({ type: 'success', title: t('variations.converted', { defaultValue: 'Converted to order' }) });
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  /* Order transitions */
  const startMut = useMutation({
    mutationFn: () => startVO(selected.id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['variations'] });
      addToast({ type: 'success', title: t('variations.vo_started', { defaultValue: 'Order started' }) });
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });
  const completeMut = useMutation({
    mutationFn: () => completeVO(selected.id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['variations'] });
      addToast({ type: 'success', title: t('variations.vo_completed', { defaultValue: 'Order completed' }) });
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });
  const voidMut = useMutation({
    mutationFn: () => voidVO(selected.id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['variations'] });
      addToast({ type: 'success', title: t('variations.vo_voided', { defaultValue: 'Order voided' }) });
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  /* Daywork transitions */
  const signMut = useMutation({
    mutationFn: () => signDaywork(selected.id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['variations'] });
      addToast({ type: 'success', title: t('variations.daywork_signed', { defaultValue: 'Daywork signed' }) });
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });
  const billMut = useMutation({
    mutationFn: () => billDaywork(selected.id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['variations'] });
      addToast({ type: 'success', title: t('variations.daywork_billed', { defaultValue: 'Daywork billed' }) });
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  /* EoT transitions */
  const submitEoTMut = useMutation({
    mutationFn: () => submitEoT(selected.id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['variations'] });
      addToast({ type: 'success', title: t('variations.eot_submitted', { defaultValue: 'EoT submitted' }) });
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });
  const [grantedDays, setGrantedDays] = useState('0');
  const grantMut = useMutation({
    mutationFn: () => grantEoT(selected.id, Number(grantedDays) || 0, decisionNotes.trim() || undefined),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['variations'] });
      setDecisionNotes('');
      addToast({ type: 'success', title: t('variations.eot_granted', { defaultValue: 'EoT granted' }) });
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });
  const rejectEoTMut = useMutation({
    mutationFn: () => rejectEoT(selected.id, decisionNotes.trim() || undefined),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['variations'] });
      setDecisionNotes('');
      addToast({ type: 'success', title: t('variations.eot_rejected', { defaultValue: 'EoT rejected' }) });
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  const heading =
    notice?.code ||
    request?.code ||
    order?.code ||
    sheet?.sheet_number ||
    (claim ? `EoT ${claim.id.slice(0, 8)}` : '');

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-50 flex justify-end" onClick={onClose}>
      <div className="absolute inset-0 bg-black/30" />
      <div
        role="dialog"
        aria-modal="true"
        aria-label={
          heading || t('variations.detail', { defaultValue: 'Variation detail' })
        }
        className="relative h-full w-full max-w-xl overflow-y-auto bg-surface-elevated shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="sticky top-0 z-10 flex items-center justify-between border-b border-border-light bg-surface-elevated px-5 py-3">
          <h2 className="text-base font-semibold">{heading}</h2>
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
          {(selected.kind === 'notices' ||
            selected.kind === 'requests' ||
            selected.kind === 'orders') && (
            <WorkflowStepper
              notice={chainNotice ?? null}
              request={chainRequest ?? null}
              order={chainOrder ?? null}
            />
          )}

          {notice && (
            <>
              <div>
                <p className="text-lg font-semibold">{notice.title || '—'}</p>
                <p className="mt-1 text-sm text-content-secondary whitespace-pre-wrap">
                  {notice.description || '—'}
                </p>
              </div>
              <div className="grid grid-cols-2 gap-3 text-sm">
                <Field
                  label={t('variations.recipient', { defaultValue: 'Recipient' })}
                  value={notice.recipient_name || notice.recipient_type}
                />
                <Field
                  label={t('variations.status')}
                  value={
                    <Badge variant={NOTICE_VARIANT[notice.status]} dot>
                      {notice.status}
                    </Badge>
                  }
                />
                <Field
                  label={t('variations.target_response')}
                  value={notice.target_response_date ? <DateDisplay value={notice.target_response_date} /> : '—'}
                />
                <Field
                  label={t('variations.raised_at', { defaultValue: 'Raised' })}
                  value={notice.raised_at ? <DateDisplay value={notice.raised_at} /> : '—'}
                />
              </div>
              <div className="flex flex-wrap gap-2 pt-2 border-t border-border-light">
                {notice.status === 'issued' && (
                  <Button
                    variant="secondary"
                    icon={<CheckCircle2 size={14} />}
                    onClick={() => ackMut.mutate()}
                    loading={ackMut.isPending}
                  >
                    {t('variations.acknowledge', { defaultValue: 'Acknowledge' })}
                  </Button>
                )}
                {(notice.status === 'issued' || notice.status === 'acknowledged') && (
                  <Card padding="sm" className="w-full">
                    <p className="text-xs font-semibold uppercase tracking-wide text-content-secondary mb-2">
                      {t('variations.respond', { defaultValue: 'Respond' })}
                    </p>
                    <div className="space-y-2">
                      <textarea
                        rows={2}
                        value={respText}
                        onChange={(e) => setRespText(e.target.value)}
                        placeholder={t('variations.response_placeholder', {
                          defaultValue: 'Response summary…',
                        })}
                        className={clsx(inputCls, 'h-auto py-2')}
                      />
                      <Button
                        variant="primary"
                        icon={<Send size={14} />}
                        onClick={() => respMut.mutate()}
                        loading={respMut.isPending}
                      >
                        {t('variations.send_response', { defaultValue: 'Send response' })}
                      </Button>
                    </div>
                  </Card>
                )}
                {notice.status === 'responded' && (
                  <Button
                    variant="secondary"
                    icon={<XCircle size={14} />}
                    onClick={() => closeNoticeMut.mutate()}
                    loading={closeNoticeMut.isPending}
                  >
                    {t('variations.close', { defaultValue: 'Close' })}
                  </Button>
                )}
              </div>
            </>
          )}

          {request && (
            <>
              <div>
                <p className="text-lg font-semibold">{request.title || '—'}</p>
                <p className="mt-1 text-sm text-content-secondary whitespace-pre-wrap">
                  {request.description || '—'}
                </p>
              </div>
              <div className="grid grid-cols-2 gap-3 text-sm">
                <Field
                  label={t('variations.classification')}
                  value={request.classification}
                />
                <Field
                  label={t('variations.urgency', { defaultValue: 'Urgency' })}
                  value={request.urgency}
                />
                <Field
                  label={t('variations.cost_impact')}
                  value={
                    <MoneyDisplay
                      amount={Number(request.estimated_cost_impact) || 0}
                      currency={request.currency || currency}
                    />
                  }
                />
                <Field
                  label={t('variations.days')}
                  value={String(request.estimated_schedule_days)}
                />
                <Field
                  label={t('variations.status')}
                  value={
                    <Badge variant={VR_VARIANT[request.status]} dot>
                      {request.status}
                    </Badge>
                  }
                />
                <Field
                  label={t('variations.submitted_at', { defaultValue: 'Submitted' })}
                  value={request.submitted_at ? <DateDisplay value={request.submitted_at} /> : '—'}
                />
              </div>
              {request.decision_notes && (
                <Card padding="sm">
                  <p className="text-xs uppercase tracking-wide text-content-tertiary mb-1">
                    {t('variations.decision_notes', { defaultValue: 'Decision notes' })}
                  </p>
                  <p className="text-sm whitespace-pre-wrap">{request.decision_notes}</p>
                </Card>
              )}
              <div className="flex flex-wrap gap-2 pt-2 border-t border-border-light">
                {request.status === 'draft' && (
                  <Button
                    variant="primary"
                    icon={<Send size={14} />}
                    onClick={() => submitVrMut.mutate()}
                    loading={submitVrMut.isPending}
                  >
                    {t('variations.submit', { defaultValue: 'Submit' })}
                  </Button>
                )}
                {(request.status === 'submitted' || request.status === 'under_review') && (
                  <Card padding="sm" className="w-full">
                    <p className="text-xs font-semibold uppercase tracking-wide text-content-secondary mb-2">
                      {t('variations.decision', { defaultValue: 'Decision' })}
                    </p>
                    <div className="space-y-2">
                      <textarea
                        rows={2}
                        value={decisionNotes}
                        onChange={(e) => setDecisionNotes(e.target.value)}
                        placeholder={t('variations.decision_notes_placeholder', {
                          defaultValue: 'Decision notes…',
                        })}
                        className={clsx(inputCls, 'h-auto py-2')}
                      />
                      <div className="flex gap-2">
                        <Button
                          variant="primary"
                          icon={<CheckCircle2 size={14} />}
                          onClick={() => approveMut.mutate()}
                          loading={approveMut.isPending}
                        >
                          {t('variations.approve', { defaultValue: 'Approve' })}
                        </Button>
                        <Button
                          variant="danger"
                          icon={<XCircle size={14} />}
                          onClick={() => rejectMut.mutate()}
                          loading={rejectMut.isPending}
                        >
                          {t('variations.reject', { defaultValue: 'Reject' })}
                        </Button>
                      </div>
                    </div>
                  </Card>
                )}
                {request.status === 'approved' && (
                  <Button
                    variant="primary"
                    icon={<ArrowRight size={14} />}
                    onClick={() => convertMut.mutate()}
                    loading={convertMut.isPending}
                  >
                    {t('variations.convert_to_vo', { defaultValue: 'Convert to Order' })}
                  </Button>
                )}
              </div>
            </>
          )}

          {order && (
            <>
              <div>
                <p className="text-lg font-semibold">{order.title || '—'}</p>
              </div>
              <div className="grid grid-cols-2 gap-3 text-sm">
                <Field
                  label={t('variations.cost_impact')}
                  value={
                    <MoneyDisplay
                      amount={Number(order.final_cost_impact) || 0}
                      currency={order.currency || currency}
                    />
                  }
                />
                <Field
                  label={t('variations.days')}
                  value={String(order.final_schedule_days)}
                />
                <Field
                  label={t('variations.status')}
                  value={
                    <Badge variant={VO_VARIANT[order.status]} dot>
                      {order.status}
                    </Badge>
                  }
                />
                <Field
                  label={t('variations.agreed_at')}
                  value={order.agreed_at ? <DateDisplay value={order.agreed_at} /> : '—'}
                />
                <Field
                  label={t('variations.started_at', { defaultValue: 'Started' })}
                  value={
                    order.implementation_started_at ? (
                      <DateDisplay value={order.implementation_started_at} />
                    ) : (
                      '—'
                    )
                  }
                />
                <Field
                  label={t('variations.completed_at', { defaultValue: 'Completed' })}
                  value={
                    order.implementation_completed_at ? (
                      <DateDisplay value={order.implementation_completed_at} />
                    ) : (
                      '—'
                    )
                  }
                />
              </div>

              {/* Linked records — turn the already-fetched FKs into deep links
                  (mirrors MoCPage). The Change Order drives the budget; the
                  contract is the one this order amends. */}
              {(order.reference_change_order_id || order.affected_contract_id) && (
                <div className="flex flex-wrap items-center gap-2 pt-2 border-t border-border-light">
                  <span className="text-xs uppercase tracking-wide text-content-tertiary">
                    {t('variations.linked_records', { defaultValue: 'Linked records' })}
                  </span>
                  {order.reference_change_order_id && (
                    <button
                      type="button"
                      className="flex items-center gap-1.5 rounded-lg border border-blue-200 bg-blue-50 dark:bg-blue-950/20 dark:border-blue-800 px-2.5 py-1.5 text-xs text-blue-700 dark:text-blue-300 hover:bg-blue-100 transition-colors"
                      onClick={() => navigate('/changeorders')}
                    >
                      <ArrowRight size={12} />
                      {t('variations.linked_change_order', { defaultValue: 'Change order' })}
                    </button>
                  )}
                  {order.affected_contract_id && (
                    <button
                      type="button"
                      className="flex items-center gap-1.5 rounded-lg border border-blue-200 bg-blue-50 dark:bg-blue-950/20 dark:border-blue-800 px-2.5 py-1.5 text-xs text-blue-700 dark:text-blue-300 hover:bg-blue-100 transition-colors"
                      onClick={() => navigate('/contracts')}
                    >
                      <ArrowRight size={12} />
                      {t('variations.linked_contract', { defaultValue: 'Contract' })}
                    </button>
                  )}
                </div>
              )}

              <div className="flex flex-wrap gap-2 pt-2 border-t border-border-light">
                {order.status === 'issued' && (
                  <Button
                    variant="primary"
                    onClick={() => startMut.mutate()}
                    loading={startMut.isPending}
                  >
                    {t('variations.start', { defaultValue: 'Start' })}
                  </Button>
                )}
                {order.status === 'in_progress' && (
                  <Button
                    variant="primary"
                    icon={<CheckCircle2 size={14} />}
                    onClick={() => completeMut.mutate()}
                    loading={completeMut.isPending}
                  >
                    {t('variations.complete', { defaultValue: 'Complete' })}
                  </Button>
                )}
                {(order.status === 'issued' || order.status === 'in_progress') && (
                  <Button
                    variant="danger"
                    icon={<XCircle size={14} />}
                    onClick={() => voidMut.mutate()}
                    loading={voidMut.isPending}
                  >
                    {t('variations.void', { defaultValue: 'Void' })}
                  </Button>
                )}
              </div>
            </>
          )}

          {sheet && (
            <>
              <div className="grid grid-cols-2 gap-3 text-sm">
                <Field
                  label={t('variations.sheet_no')}
                  value={sheet.sheet_number}
                />
                <Field
                  label={t('variations.work_date')}
                  value={sheet.work_date ? <DateDisplay value={sheet.work_date} /> : '—'}
                />
                <Field
                  label={t('variations.total')}
                  value={
                    <MoneyDisplay
                      amount={Number(sheet.total_amount) || 0}
                      currency={sheet.currency || currency}
                    />
                  }
                />
                <Field
                  label={t('variations.status')}
                  value={
                    <Badge variant={DAYWORK_VARIANT[sheet.status]} dot>
                      {sheet.status}
                    </Badge>
                  }
                />
              </div>
              {sheet.description && (
                <Card padding="sm">
                  <p className="text-sm whitespace-pre-wrap">{sheet.description}</p>
                </Card>
              )}
              <div className="flex flex-wrap gap-2 pt-2 border-t border-border-light">
                {sheet.status === 'draft' && (
                  <Button
                    variant="primary"
                    icon={<CheckCircle2 size={14} />}
                    onClick={() => signMut.mutate()}
                    loading={signMut.isPending}
                  >
                    {t('variations.sign', { defaultValue: 'Sign' })}
                  </Button>
                )}
                {sheet.status === 'signed' && (
                  <Button
                    variant="secondary"
                    onClick={() => billMut.mutate()}
                    loading={billMut.isPending}
                  >
                    {t('variations.bill', { defaultValue: 'Bill' })}
                  </Button>
                )}
              </div>
            </>
          )}

          {claim && (
            <>
              <div>
                <p className="text-sm whitespace-pre-wrap">{claim.description || '—'}</p>
              </div>
              <div className="grid grid-cols-2 gap-3 text-sm">
                <Field
                  label={t('variations.cause')}
                  value={claim.root_cause_category}
                />
                <Field
                  label={t('variations.requested_days')}
                  value={String(claim.requested_days)}
                />
                <Field
                  label={t('variations.granted_days')}
                  value={claim.granted_days != null ? String(claim.granted_days) : '—'}
                />
                <Field
                  label={t('variations.critical_path')}
                  value={claim.critical_path_impact ? 'CP' : '—'}
                />
                <Field
                  label={t('variations.status')}
                  value={
                    <Badge variant={EOT_VARIANT[claim.status]} dot>
                      {claim.status}
                    </Badge>
                  }
                />
                <Field
                  label={t('variations.period', { defaultValue: 'Period' })}
                  value={
                    claim.claim_period_start && claim.claim_period_end
                      ? `${claim.claim_period_start} → ${claim.claim_period_end}`
                      : '—'
                  }
                />
              </div>
              {claim.decision_notes && (
                <Card padding="sm">
                  <p className="text-xs uppercase tracking-wide text-content-tertiary mb-1">
                    {t('variations.decision_notes')}
                  </p>
                  <p className="text-sm whitespace-pre-wrap">{claim.decision_notes}</p>
                </Card>
              )}
              <div className="flex flex-wrap gap-2 pt-2 border-t border-border-light">
                {claim.status === 'draft' && (
                  <Button
                    variant="primary"
                    icon={<Send size={14} />}
                    onClick={() => submitEoTMut.mutate()}
                    loading={submitEoTMut.isPending}
                  >
                    {t('variations.submit')}
                  </Button>
                )}
                {(claim.status === 'submitted' || claim.status === 'under_review') && (
                  <Card padding="sm" className="w-full">
                    <p className="text-xs font-semibold uppercase tracking-wide text-content-secondary mb-2">
                      {t('variations.decide', { defaultValue: 'Decide' })}
                    </p>
                    <div className="space-y-2">
                      <div className="grid grid-cols-2 gap-2">
                        <input
                          type="number"
                          value={grantedDays}
                          onChange={(e) => setGrantedDays(e.target.value)}
                          placeholder="0"
                          className={inputCls}
                          min={0}
                        />
                        <textarea
                          rows={1}
                          value={decisionNotes}
                          onChange={(e) => setDecisionNotes(e.target.value)}
                          placeholder={t('variations.decision_notes_placeholder', {
                            defaultValue: 'Decision notes…',
                          })}
                          className={clsx(inputCls, 'h-auto py-2')}
                        />
                      </div>
                      <div className="flex gap-2">
                        <Button
                          variant="primary"
                          icon={<CheckCircle2 size={14} />}
                          onClick={() => grantMut.mutate()}
                          loading={grantMut.isPending}
                        >
                          {t('variations.grant', { defaultValue: 'Grant' })}
                        </Button>
                        <Button
                          variant="danger"
                          icon={<XCircle size={14} />}
                          onClick={() => rejectEoTMut.mutate()}
                          loading={rejectEoTMut.isPending}
                        >
                          {t('variations.reject')}
                        </Button>
                      </div>
                    </div>
                  </Card>
                )}
              </div>
            </>
          )}
        </div>
      </div>
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

/* ─── Create / Edit modal ─── */

/** Trim an ISO datetime down to the YYYY-MM-DD a native `<input type="date">`
 *  expects. Falls back to '' so editing never crashes on a null/empty date. */
function toDateInput(v: string | null | undefined): string {
  return v ? v.slice(0, 10) : '';
}

/**
 * Dual-purpose modal: with no `editTarget` it creates a new sub-entity
 * (unchanged behaviour); with an `editTarget` it prefills the SAME form
 * from the list row and PATCHes via the matching `update*` API. The create
 * form is the single source of truth for both flows — Edit reuses it
 * verbatim per the gold-standard TasksPage pattern.
 */
function CreateModal({
  kind,
  projectId,
  currency,
  notices,
  requests,
  editTarget,
  onClose,
}: {
  kind: Tab;
  projectId: string;
  currency: string;
  notices: Notice[];
  requests: VariationRequest[];
  editTarget?: EditTarget | null;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [busy, setBusy] = useState(false);
  const isEdit = !!editTarget;

  const [noticeForm, setNoticeForm] = useState(() => {
    const n =
      editTarget?.kind === 'notices' ? editTarget.row : null;
    return {
      title: n?.title ?? '',
      description: n?.description ?? '',
      recipient_type: (n?.recipient_type ?? 'owner') as Notice['recipient_type'],
      recipient_name: n?.recipient_name ?? '',
      target_response_date: toDateInput(n?.target_response_date),
    };
  });

  const [vrForm, setVrForm] = useState(() => {
    const r =
      editTarget?.kind === 'requests' ? editTarget.row : null;
    return {
      title: r?.title ?? '',
      description: r?.description ?? '',
      notice_id: r?.notice_id ?? '',
      classification: (r?.classification ??
        'scope_change') as VariationRequest['classification'],
      urgency: (r?.urgency ?? 'med') as VariationRequest['urgency'],
      estimated_cost_impact:
        r != null ? String(r.estimated_cost_impact ?? '0') : '0',
      estimated_schedule_days:
        r != null ? String(r.estimated_schedule_days ?? '0') : '0',
      currency: r?.currency || currency,
    };
  });

  const [voForm, setVoForm] = useState(() => {
    const o = editTarget?.kind === 'orders' ? editTarget.row : null;
    return {
      title: o?.title ?? '',
      variation_request_id: o?.variation_request_id ?? '',
      final_cost_impact:
        o != null ? String(o.final_cost_impact ?? '0') : '0',
      final_schedule_days:
        o != null ? String(o.final_schedule_days ?? '0') : '0',
      currency: o?.currency || currency,
    };
  });

  const [dwForm, setDwForm] = useState(() => {
    const d = editTarget?.kind === 'daywork' ? editTarget.row : null;
    return {
      work_date: toDateInput(d?.work_date),
      description: d?.description ?? '',
      currency: d?.currency || currency,
    };
  });

  const [eotForm, setEotForm] = useState(() => {
    const e = editTarget?.kind === 'eot' ? editTarget.row : null;
    return {
      description: e?.description ?? '',
      root_cause_category: (e?.root_cause_category ??
        'neutral') as ExtensionOfTimeClaim['root_cause_category'],
      requested_days: e != null ? String(e.requested_days ?? '0') : '0',
      critical_path_impact: e?.critical_path_impact ?? false,
      claim_period_start: toDateInput(e?.claim_period_start),
      claim_period_end: toDateInput(e?.claim_period_end),
    };
  });

  const submit = async () => {
    setBusy(true);
    try {
      const editId = editTarget?.row.id ?? '';
      if (kind === 'notices') {
        if (isEdit && editTarget?.kind === 'notices') {
          await updateNotice(editId, {
            title: noticeForm.title.trim(),
            description: noticeForm.description.trim(),
            recipient_type: noticeForm.recipient_type,
            recipient_name: noticeForm.recipient_name.trim(),
            target_response_date: noticeForm.target_response_date || null,
          });
        } else {
          await createNotice({
            project_id: projectId,
            title: noticeForm.title.trim(),
            description: noticeForm.description.trim(),
            recipient_type: noticeForm.recipient_type,
            recipient_name: noticeForm.recipient_name.trim(),
            target_response_date: noticeForm.target_response_date || undefined,
          });
        }
        addToast({
          type: 'success',
          title: isEdit
            ? t('variations.notice_updated', { defaultValue: 'Notice updated' })
            : t('variations.notice_created', { defaultValue: 'Notice created' }),
        });
      } else if (kind === 'requests') {
        if (isEdit && editTarget?.kind === 'requests') {
          await updateVR(editId, {
            title: vrForm.title.trim(),
            description: vrForm.description.trim(),
            classification: vrForm.classification,
            urgency: vrForm.urgency,
            estimated_cost_impact: Number(vrForm.estimated_cost_impact) || 0,
            estimated_schedule_days: Number(vrForm.estimated_schedule_days) || 0,
            currency: vrForm.currency,
          });
        } else {
          await createVR({
            project_id: projectId,
            notice_id: vrForm.notice_id || null,
            title: vrForm.title.trim(),
            description: vrForm.description.trim(),
            classification: vrForm.classification,
            urgency: vrForm.urgency,
            estimated_cost_impact: Number(vrForm.estimated_cost_impact) || 0,
            estimated_schedule_days: Number(vrForm.estimated_schedule_days) || 0,
            currency: vrForm.currency,
          });
        }
        addToast({
          type: 'success',
          title: isEdit
            ? t('variations.vr_updated', { defaultValue: 'Request updated' })
            : t('variations.vr_created', { defaultValue: 'Request created' }),
        });
      } else if (kind === 'orders') {
        if (isEdit && editTarget?.kind === 'orders') {
          await updateVO(editId, {
            title: voForm.title.trim(),
            final_cost_impact: Number(voForm.final_cost_impact) || 0,
            final_schedule_days: Number(voForm.final_schedule_days) || 0,
            currency: voForm.currency,
          });
        } else {
          await createVO({
            project_id: projectId,
            variation_request_id: voForm.variation_request_id || null,
            title: voForm.title.trim(),
            final_cost_impact: Number(voForm.final_cost_impact) || 0,
            final_schedule_days: Number(voForm.final_schedule_days) || 0,
            currency: voForm.currency,
          });
        }
        addToast({
          type: 'success',
          title: isEdit
            ? t('variations.vo_updated', { defaultValue: 'Order updated' })
            : t('variations.vo_created', { defaultValue: 'Order created' }),
        });
      } else if (kind === 'daywork') {
        if (isEdit && editTarget?.kind === 'daywork') {
          await updateDaywork(editId, {
            work_date: dwForm.work_date || null,
            description: dwForm.description.trim(),
            currency: dwForm.currency,
          });
        } else {
          await createDaywork({
            project_id: projectId,
            work_date: dwForm.work_date || undefined,
            description: dwForm.description.trim(),
            currency: dwForm.currency,
          });
        }
        addToast({
          type: 'success',
          title: isEdit
            ? t('variations.daywork_updated', {
                defaultValue: 'Daywork sheet updated',
              })
            : t('variations.daywork_created', {
                defaultValue: 'Daywork sheet created',
              }),
        });
      } else if (kind === 'eot') {
        if (isEdit && editTarget?.kind === 'eot') {
          await updateEoT(editId, {
            description: eotForm.description.trim(),
            root_cause_category: eotForm.root_cause_category,
            requested_days: Number(eotForm.requested_days) || 0,
            critical_path_impact: eotForm.critical_path_impact,
          });
        } else {
          await createEoT({
            project_id: projectId,
            description: eotForm.description.trim(),
            root_cause_category: eotForm.root_cause_category,
            requested_days: Number(eotForm.requested_days) || 0,
            critical_path_impact: eotForm.critical_path_impact,
            claim_period_start: eotForm.claim_period_start || undefined,
            claim_period_end: eotForm.claim_period_end || undefined,
          });
        }
        addToast({
          type: 'success',
          title: isEdit
            ? t('variations.eot_updated', { defaultValue: 'EoT claim updated' })
            : t('variations.eot_created', {
                defaultValue: 'EoT claim created',
              }),
        });
      }
      qc.invalidateQueries({ queryKey: ['variations'] });
      onClose();
    } catch (err) {
      addToast({ type: 'error', title: getErrorMessage(err) });
    } finally {
      setBusy(false);
    }
  };

  const createTitle =
    kind === 'notices'
      ? t('variations.new_notice', { defaultValue: 'New Notice' })
      : kind === 'requests'
        ? t('variations.new_request', { defaultValue: 'New Request' })
        : kind === 'orders'
          ? t('variations.new_order', { defaultValue: 'New Order' })
          : kind === 'daywork'
            ? t('variations.new_daywork', { defaultValue: 'New Daywork' })
            : t('variations.new_eot', { defaultValue: 'New EoT Claim' });
  const editTitle =
    kind === 'notices'
      ? t('variations.edit_notice', { defaultValue: 'Edit Notice' })
      : kind === 'requests'
        ? t('variations.edit_request', { defaultValue: 'Edit Request' })
        : kind === 'orders'
          ? t('variations.edit_order', { defaultValue: 'Edit Order' })
          : kind === 'daywork'
            ? t('variations.edit_daywork', { defaultValue: 'Edit Daywork' })
            : t('variations.edit_eot', { defaultValue: 'Edit EoT Claim' });
  const title = isEdit ? editTitle : createTitle;

  // Requests is the densest (7 fields with a cost/days/currency triplet)
  // so it benefits from xl; the rest comfortably fit at lg.
  const size = kind === 'requests' || kind === 'eot' ? 'xl' : 'lg';

  return (
    <WideModal
      open
      onClose={onClose}
      title={title}
      size={size}
      busy={busy}
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={busy}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button
            variant="primary"
            onClick={submit}
            loading={busy}
            icon={
              busy ? (
                <Loader2 size={14} />
              ) : isEdit ? (
                <Pencil size={14} />
              ) : (
                <Plus size={14} />
              )
            }
          >
            {isEdit
              ? t('common.save', { defaultValue: 'Save' })
              : t('common.create', { defaultValue: 'Create' })}
          </Button>
        </>
      }
    >
      {kind === 'notices' && (
        <WideModalSection columns={2}>
          <WideModalField
            label={t('variations.title_col', { defaultValue: 'Title' })}
            span={2}
          >
            <input
              value={noticeForm.title}
              onChange={(e) => setNoticeForm({ ...noticeForm, title: e.target.value })}
              className={inputCls}
            />
          </WideModalField>
          <WideModalField
            label={t('variations.description', { defaultValue: 'Description' })}
            span={2}
          >
            <textarea
              value={noticeForm.description}
              onChange={(e) => setNoticeForm({ ...noticeForm, description: e.target.value })}
              rows={3}
              className={clsx(inputCls, 'h-auto py-2')}
            />
          </WideModalField>
          <WideModalField
            label={t('variations.recipient_type', { defaultValue: 'Recipient type' })}
          >
            <select
              value={noticeForm.recipient_type}
              onChange={(e) =>
                setNoticeForm({
                  ...noticeForm,
                  recipient_type: e.target.value as Notice['recipient_type'],
                })
              }
              className={inputCls}
            >
              {(['owner', 'contractor', 'architect', 'engineer', 'consultant'] as const).map(
                (rt) => (
                  <option key={rt} value={rt}>
                    {rt}
                  </option>
                ),
              )}
            </select>
          </WideModalField>
          <WideModalField
            label={t('variations.recipient_name', { defaultValue: 'Recipient name' })}
          >
            <input
              value={noticeForm.recipient_name}
              onChange={(e) =>
                setNoticeForm({ ...noticeForm, recipient_name: e.target.value })
              }
              className={inputCls}
            />
          </WideModalField>
          <WideModalField
            label={t('variations.target_response', { defaultValue: 'Response by' })}
            span={2}
          >
            <input
              type="date"
              value={noticeForm.target_response_date}
              onChange={(e) =>
                setNoticeForm({ ...noticeForm, target_response_date: e.target.value })
              }
              className={inputCls}
            />
          </WideModalField>
        </WideModalSection>
      )}

      {kind === 'requests' && (
        <>
          <WideModalSection
            title={t('variations.section_basic', { defaultValue: 'Basic info' })}
            columns={2}
          >
            <WideModalField
              label={t('variations.title_col', { defaultValue: 'Title' })}
              span={2}
            >
              <input
                value={vrForm.title}
                onChange={(e) => setVrForm({ ...vrForm, title: e.target.value })}
                className={inputCls}
              />
            </WideModalField>
            <WideModalField
              label={t('variations.description', { defaultValue: 'Description' })}
              span={2}
            >
              <textarea
                value={vrForm.description}
                onChange={(e) => setVrForm({ ...vrForm, description: e.target.value })}
                rows={3}
                className={clsx(inputCls, 'h-auto py-2')}
              />
            </WideModalField>
            {!isEdit && (
              <WideModalField
                label={t('variations.from_notice', {
                  defaultValue: 'From notice (optional)',
                })}
                span={2}
              >
                <select
                  value={vrForm.notice_id}
                  onChange={(e) =>
                    setVrForm({ ...vrForm, notice_id: e.target.value })
                  }
                  className={inputCls}
                >
                  <option value="">—</option>
                  {notices.map((n) => (
                    <option key={n.id} value={n.id}>
                      {n.code} — {n.title || '—'}
                    </option>
                  ))}
                </select>
              </WideModalField>
            )}
            <WideModalField label={t('variations.classification')}>
              <select
                value={vrForm.classification}
                onChange={(e) =>
                  setVrForm({
                    ...vrForm,
                    classification: e.target.value as VariationRequest['classification'],
                  })
                }
                className={inputCls}
              >
                {(
                  [
                    'scope_change',
                    'unforeseen',
                    'owner_change',
                    'design_dev',
                    'regulatory',
                    'other',
                  ] as const
                ).map((c) => (
                  <option key={c} value={c}>
                    {c}
                  </option>
                ))}
              </select>
            </WideModalField>
            <WideModalField label={t('variations.urgency')}>
              <select
                value={vrForm.urgency}
                onChange={(e) =>
                  setVrForm({ ...vrForm, urgency: e.target.value as VariationRequest['urgency'] })
                }
                className={inputCls}
              >
                {(['low', 'med', 'high'] as const).map((u) => (
                  <option key={u} value={u}>
                    {u}
                  </option>
                ))}
              </select>
            </WideModalField>
          </WideModalSection>

          <WideModalSection
            title={t('variations.section_impact', { defaultValue: 'Impact' })}
            columns={3}
          >
            <WideModalField label={t('variations.cost_impact')}>
              <input
                type="number"
                value={vrForm.estimated_cost_impact}
                onChange={(e) =>
                  setVrForm({ ...vrForm, estimated_cost_impact: e.target.value })
                }
                className={inputCls}
              />
            </WideModalField>
            <WideModalField label={t('variations.days')}>
              <input
                type="number"
                value={vrForm.estimated_schedule_days}
                onChange={(e) =>
                  setVrForm({ ...vrForm, estimated_schedule_days: e.target.value })
                }
                className={inputCls}
              />
            </WideModalField>
            <WideModalField
              label={t('common.currency', { defaultValue: 'Currency' })}
            >
              <input
                value={vrForm.currency}
                onChange={(e) => setVrForm({ ...vrForm, currency: e.target.value })}
                className={inputCls}
                maxLength={3}
              />
            </WideModalField>
          </WideModalSection>
        </>
      )}

      {kind === 'orders' && (
        <>
          <WideModalSection columns={2}>
            <WideModalField
              label={t('variations.title_col', { defaultValue: 'Title' })}
              span={2}
            >
              <input
                value={voForm.title}
                onChange={(e) => setVoForm({ ...voForm, title: e.target.value })}
                className={inputCls}
              />
            </WideModalField>
            {!isEdit && (
              <WideModalField
                label={t('variations.from_request', {
                  defaultValue: 'From request (optional)',
                })}
                span={2}
              >
                <select
                  value={voForm.variation_request_id}
                  onChange={(e) =>
                    setVoForm({
                      ...voForm,
                      variation_request_id: e.target.value,
                    })
                  }
                  className={inputCls}
                >
                  <option value="">—</option>
                  {requests.map((r) => (
                    <option key={r.id} value={r.id}>
                      {r.code} — {r.title || '—'}
                    </option>
                  ))}
                </select>
              </WideModalField>
            )}
          </WideModalSection>
          <WideModalSection
            title={t('variations.section_impact', { defaultValue: 'Impact' })}
            columns={3}
          >
            <WideModalField label={t('variations.cost_impact')}>
              <input
                type="number"
                value={voForm.final_cost_impact}
                onChange={(e) =>
                  setVoForm({ ...voForm, final_cost_impact: e.target.value })
                }
                className={inputCls}
              />
            </WideModalField>
            <WideModalField label={t('variations.days')}>
              <input
                type="number"
                value={voForm.final_schedule_days}
                onChange={(e) =>
                  setVoForm({ ...voForm, final_schedule_days: e.target.value })
                }
                className={inputCls}
              />
            </WideModalField>
            <WideModalField
              label={t('common.currency', { defaultValue: 'Currency' })}
            >
              <input
                value={voForm.currency}
                onChange={(e) => setVoForm({ ...voForm, currency: e.target.value })}
                className={inputCls}
                maxLength={3}
              />
            </WideModalField>
          </WideModalSection>
        </>
      )}

      {kind === 'daywork' && (
        <WideModalSection columns={2}>
          <WideModalField label={t('variations.work_date')}>
            <input
              type="date"
              value={dwForm.work_date}
              onChange={(e) => setDwForm({ ...dwForm, work_date: e.target.value })}
              className={inputCls}
            />
          </WideModalField>
          <WideModalField
            label={t('common.currency', { defaultValue: 'Currency' })}
          >
            <input
              value={dwForm.currency}
              onChange={(e) => setDwForm({ ...dwForm, currency: e.target.value })}
              className={inputCls}
              maxLength={3}
            />
          </WideModalField>
          <WideModalField
            label={t('variations.description', { defaultValue: 'Description' })}
            span={2}
          >
            <textarea
              value={dwForm.description}
              onChange={(e) => setDwForm({ ...dwForm, description: e.target.value })}
              rows={3}
              className={clsx(inputCls, 'h-auto py-2')}
            />
          </WideModalField>
        </WideModalSection>
      )}

      {kind === 'eot' && (
        <WideModalSection columns={2}>
          <WideModalField
            label={t('variations.description', { defaultValue: 'Description' })}
            span={2}
          >
            <textarea
              value={eotForm.description}
              onChange={(e) => setEotForm({ ...eotForm, description: e.target.value })}
              rows={3}
              className={clsx(inputCls, 'h-auto py-2')}
            />
          </WideModalField>
          <WideModalField label={t('variations.cause')}>
            <select
              value={eotForm.root_cause_category}
              onChange={(e) =>
                setEotForm({
                  ...eotForm,
                  root_cause_category: e.target
                    .value as ExtensionOfTimeClaim['root_cause_category'],
                })
              }
              className={inputCls}
            >
              {(['employer_caused', 'neutral', 'contractor_caused', 'concurrent'] as const).map(
                (c) => (
                  <option key={c} value={c}>
                    {c}
                  </option>
                ),
              )}
            </select>
          </WideModalField>
          <WideModalField label={t('variations.requested_days')}>
            <input
              type="number"
              value={eotForm.requested_days}
              onChange={(e) => setEotForm({ ...eotForm, requested_days: e.target.value })}
              className={inputCls}
              min={0}
            />
          </WideModalField>
          {!isEdit && (
            <>
              <WideModalField
                label={t('variations.period_start', {
                  defaultValue: 'Period start',
                })}
              >
                <input
                  type="date"
                  value={eotForm.claim_period_start}
                  onChange={(e) =>
                    setEotForm({
                      ...eotForm,
                      claim_period_start: e.target.value,
                    })
                  }
                  className={inputCls}
                />
              </WideModalField>
              <WideModalField
                label={t('variations.period_end', {
                  defaultValue: 'Period end',
                })}
              >
                <input
                  type="date"
                  value={eotForm.claim_period_end}
                  onChange={(e) =>
                    setEotForm({ ...eotForm, claim_period_end: e.target.value })
                  }
                  className={inputCls}
                />
              </WideModalField>
            </>
          )}
          <WideModalField label="" span={2}>
            <label className="inline-flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={eotForm.critical_path_impact}
                onChange={(e) =>
                  setEotForm({ ...eotForm, critical_path_impact: e.target.checked })
                }
              />
              {t('variations.affects_critical_path', {
                defaultValue: 'Affects critical path',
              })}
            </label>
          </WideModalField>
        </WideModalSection>
      )}
    </WideModal>
  );
}
