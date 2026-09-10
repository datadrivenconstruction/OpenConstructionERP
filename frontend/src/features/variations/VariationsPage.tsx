// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { Fragment, useState, useMemo, useEffect, type ReactNode } from 'react';
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
  Network,
  Pencil,
  Trash2,
  Calculator,
  AlertTriangle,
} from 'lucide-react';
import {
  Button,
  Card,
  Badge,
  CollapsibleSection,
  EmptyState,
  Breadcrumb,
  RecoveryCard,
  SkeletonTable,
  ConfirmDialog,
  DismissibleInfo,
  IntroRichText,
  ModuleGuideButton,
} from '@/shared/ui';
import {
  ProvabilityGauge,
  EvidenceThreadPanel,
  reconstructTypeForKind,
  type SubjectKind,
} from '@/features/claims-evidence';
import { useConfirm } from '@/shared/hooks/useConfirm';
import {
  WideModal,
  WideModalSection,
  WideModalField,
} from '@/shared/ui/WideModal';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { listContracts } from '../contracts/api';
import {
  changeOrderDeepLink,
  contractDeepLink,
  variationBoqDeepLink,
} from '@/shared/lib/changeChainLinks';
import { MoneyDisplay } from '@/shared/ui/MoneyDisplay';
import { DateDisplay } from '@/shared/ui/DateDisplay';
import { PageHeader } from '@/shared/ui/PageHeader';
import { TruncationNotice } from '@/shared/ui/TruncationNotice';
import { apiGet, getErrorMessage } from '@/shared/lib/api';
import { onlyChangedFields } from '@/shared/lib/apiHelpers';
import { useToastStore } from '@/stores/useToastStore';
import { useActiveProjectId } from '@/shared/hooks/useActiveProjectId';
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
  getVariationRequestBOQ,
  createVariationRequestBOQ,
  adoptVariationRequestBOQ,
  type ApproveVRPayload,
  type CreateVariationBOQPayload,
  type VariationBOQ,
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
import {
  approvalBaseline,
  approvalBlockReason,
  buildApprovalPayload,
  type ApprovalMode,
} from './approvalDecision';
import { VariationSourcePicker } from './VariationSourcePicker';
import { variationsGuide } from './variationsGuide';
import { InsightsPanel, InsightsToggleButton, useModuleInsights } from '@/features/insights';
import { buildVariationsInsights, classLabel, statusLabel, urgencyLabel } from './variationsInsights';

const VARIATIONS_TAB_IDS = ['notices', 'requests', 'orders', 'daywork', 'eot'] as const;
type Tab = (typeof VARIATIONS_TAB_IDS)[number];

const isTab = (value: string | null): value is Tab =>
  (VARIATIONS_TAB_IDS as readonly string[]).includes(value ?? '');

/** The record whose drawer is open, keyed by the tab it lives on. */
type Selection =
  | { kind: 'notices'; id: string }
  | { kind: 'requests'; id: string }
  | { kind: 'orders'; id: string }
  | { kind: 'daywork'; id: string }
  | { kind: 'eot'; id: string }
  | null;

/** The selection a deep link asks for, or none.
 *
 * A change order's "From variation" pill, a management-of-change entry's
 * "Linked variation" pill and their kin land here as
 * `/variations?tab=<kind>&highlight=<id>` (Issue #435). Both halves are
 * needed: a request id and an order id look the same, so a highlight with no
 * tab would be an id this page has to guess the kind of, and a tab this page
 * does not have is a link nothing here can honour.
 */
function selectionFromUrl(tab: string | null, id: string | null): Selection {
  if (!id || !isTab(tab)) return null;
  switch (tab) {
    case 'notices':
      return { kind: 'notices', id };
    case 'requests':
      return { kind: 'requests', id };
    case 'orders':
      return { kind: 'orders', id };
    case 'daywork':
      return { kind: 'daywork', id };
    case 'eot':
      return { kind: 'eot', id };
  }
}

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

/**
 * The failure is deliberately left to propagate.
 *
 * Swallowing it into an empty array made a project list that failed to load
 * indistinguishable from an account with no projects, and the page then told
 * the user to go and create one. That is worse than an error: it is confident,
 * wrong, and it sends them off to fix a problem they do not have.
 */
function listProjectsLite(): Promise<ProjectStub[]> {
  return apiGet<ProjectStub[]>('/v1/projects/?limit=200');
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

/* ── How it works + connects ─────────────────────────────────────────────
 * Compact at-a-glance flow so a commercial manager sees what Variations does
 * and which sibling modules a change event flows between. Mirrors the approved
 * norm-expansion pattern. */
function ModLink({ to, children }: { to: string; children: ReactNode }) {
  return (
    <Link to={to} className="font-medium text-oe-blue-text hover:underline">
      {children}
    </Link>
  );
}

function HowVariationsWork() {
  const { t } = useTranslation();
  const steps: { icon: ReactNode; title: string; desc: string }[] = [
    {
      icon: <Bell size={14} className="text-oe-blue" />,
      title: t('variations.flow_1_title', { defaultValue: 'Raise a notice' }),
      desc: t('variations.flow_1_desc', {
        defaultValue: 'Flag a change event the moment it happens on site.',
      }),
    },
    {
      icon: <FileText size={14} className="text-oe-blue" />,
      title: t('variations.flow_2_title', { defaultValue: 'Price the request' }),
      desc: t('variations.flow_2_desc', {
        defaultValue: 'Estimate the cost and time impact for the client to review.',
      }),
    },
    {
      icon: <FileCheck2 size={14} className="text-oe-blue" />,
      title: t('variations.flow_3_title', { defaultValue: 'Agree the order' }),
      desc: t('variations.flow_3_desc', {
        defaultValue: 'Approve and issue the variation order once it is agreed.',
      }),
    },
    {
      icon: <Hammer size={14} className="text-oe-blue" />,
      title: t('variations.flow_4_title', { defaultValue: 'Track daywork & EoT' }),
      desc: t('variations.flow_4_desc', {
        defaultValue: 'Log daily work and time claims through to the final account.',
      }),
    },
  ];

  return (
    <CollapsibleSection
      storageKey="variations.how"
      icon={<Network size={15} className="text-oe-blue" />}
      title={t('variations.flow_title', { defaultValue: 'How variations work, and what they connect to' })}
    >
      <p className="text-xs text-content-tertiary">
        {t('variations.flow_intro', {
          defaultValue:
            'Turn every site change into an agreed, priced variation order so nothing is lost at settlement. Start by raising a notice for the current project.',
        })}
      </p>

      <ol className="mt-3 flex flex-col gap-2 lg:flex-row lg:items-stretch">
        {steps.map((s, i) => (
          <Fragment key={s.title}>
            <li className="flex-1 rounded-lg border border-border-light bg-surface-primary p-3">
              <div className="flex items-center gap-2">
                <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-lg bg-oe-blue-subtle">
                  {s.icon}
                </span>
                <span className="text-xs font-semibold text-content-primary">{s.title}</span>
              </div>
              <p className="mt-1.5 text-2xs leading-relaxed text-content-tertiary">{s.desc}</p>
            </li>
            {i < steps.length - 1 && (
              <li
                aria-hidden="true"
                className="hidden shrink-0 items-center self-center text-content-quaternary lg:flex"
              >
                <ArrowRight size={16} />
              </li>
            )}
          </Fragment>
        ))}
      </ol>

      <div className="mt-3 border-t border-border-light pt-3 text-2xs text-content-tertiary">
        <span className="font-medium text-content-secondary">
          {t('variations.flow_connects', { defaultValue: 'Connects with:' })}
        </span>{' '}
        <ModLink to="/contracts">
          {t('variations.mod_contracts', { defaultValue: 'Contracts' })}
        </ModLink>
        {' · '}
        <ModLink to="/boq">{t('variations.mod_boq', { defaultValue: 'BOQ' })}</ModLink>
        {' · '}
        <ModLink to="/reconciliation">
          {t('variations.mod_reconciliation', { defaultValue: 'Reconciliation' })}
        </ModLink>
        {' · '}
        <ModLink to="/reports">{t('variations.mod_reports', { defaultValue: 'Reports' })}</ModLink>
      </div>
    </CollapsibleSection>
  );
}

export function VariationsPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const activeProjectId = useActiveProjectId();

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

  // Deep-link consumer (Issue #435). Both params are read once, on mount:
  // they are a starting point, not a lock, so the tab strip and the drawer's
  // close button work as they always did. Closing the drawer drops the
  // highlight so a later remount does not re-open the record the user just
  // closed.
  const [searchParams, setSearchParams] = useSearchParams();
  const highlightedTab = searchParams.get('tab');
  const highlightedId = searchParams.get('highlight');
  const [tab, setTab] = useState<Tab>(isTab(highlightedTab) ? highlightedTab : 'notices');
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState<string>('');
  /* Both of these narrow every tab, and the status one is sent to the
     endpoint, which applies it before counting. So while either is set the
     `total` on the envelope describes the query rather than the register and
     cannot be read as a denial that the register holds anything. */
  const filtersActive = Boolean(search.trim() || statusFilter);
  const clearFilters = () => {
    setSearch('');
    setStatusFilter('');
  };
  // Arrow-key navigation across the 5-tab variations strip (WCAG 2.1.1).
  const onTabKeyDown = useTabKeyboardNav<Tab>({
    ids: VARIATIONS_TAB_IDS,
    activeId: tab,
    onChange: (next) => {
      setTab(next);
      clearFilters();
    },
    orientation: 'horizontal',
  });
  const [selected, setSelected] = useState<Selection>(() =>
    selectionFromUrl(highlightedTab, highlightedId),
  );
  const closeDetail = () => {
    setSelected(null);
    if (highlightedId) {
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          next.delete('highlight');
          return next;
        },
        { replace: true },
      );
    }
  };
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
    const items = noticesQ.data?.items ?? [];
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
    const items = requestsQ.data?.items ?? [];
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
    const items = ordersQ.data?.items ?? [];
    if (!search.trim()) return items;
    const s = search.toLowerCase();
    return items.filter(
      (o) =>
        o.code.toLowerCase().includes(s) || (o.title || '').toLowerCase().includes(s),
    );
  }, [ordersQ.data, search]);

  const filteredDaywork = useMemo(() => {
    const items = dayworkQ.data?.items ?? [];
    if (!search.trim()) return items;
    const s = search.toLowerCase();
    return items.filter(
      (d) =>
        d.sheet_number.toLowerCase().includes(s) ||
        (d.description || '').toLowerCase().includes(s),
    );
  }, [dayworkQ.data, search]);

  const filteredEot = useMemo(() => {
    const items = eotQ.data?.items ?? [];
    if (!search.trim()) return items;
    const s = search.toLowerCase();
    return items.filter((e) => (e.description || '').toLowerCase().includes(s));
  }, [eotQ.data, search]);

  // Module Insights - the toggleable visualization panel for this module. It
  // charts the variation requests already loaded (the entity that carries each
  // change's estimated cost and schedule impact); when the project has none the
  // panel draws nothing rather than inventing rows to fill it. Declared before
  // the no-project early return below so the hook order stays stable.
  const insights = useModuleInsights('variations', { defaultOpen: true });
  const { datasets: insightDatasets, builtins: insightBuiltins } = useMemo(
    () => buildVariationsInsights(requestsQ.data?.items ?? [], currency, t),
    [requestsQ.data, currency, t],
  );

  // A project list that failed to load is not an account without projects, and
  // the two must not lead to the same screen. Only say there is nothing here
  // once the list has actually come back.
  if (!projectId && (projectsQ.isError || projectsQ.isPending)) {
    return (
      <div className="space-y-5 animate-fade-in">
        <Breadcrumb items={[{ label: t('nav.variations', { defaultValue: 'Variations' }) }]} />
        {projectsQ.isError ? (
          <RecoveryCard
            error={projectsQ.error}
            onRetry={() => {
              void projectsQ.refetch();
            }}
          />
        ) : (
          <SkeletonTable rows={4} />
        )}
      </div>
    );
  }

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
        srTitle={t('nav.variations', { defaultValue: 'Variations' })}
        subtitle={t('variations.subtitle', {
          defaultValue:
            'Track variation notices, requests, orders, daywork and EoT claims through to final account.',
        })}
        actions={
          <>
            <InsightsToggleButton open={insights.open} onClick={insights.toggle} />
            <ModuleGuideButton content={variationsGuide} />
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
          </>
        }
      />

      {/* Module Insights panel - toggled by the header button. Placed high so
          its charts are visible as the page opens. */}
      <InsightsPanel
        open={insights.open}
        title={t('variations.insights.title', { defaultValue: 'Variations insights' })}
        datasets={insightDatasets}
        builtins={insightBuiltins}
        custom={insights.custom}
        onAdd={insights.addCustom}
        onUpdate={insights.updateCustom}
        onRemove={insights.removeCustom}
        onCollapse={() => insights.setOpen(false)}
      />

      <HowVariationsWork />

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
                  clearFilters();
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
              {statusLabel(s, t)}
            </option>
          ))}
        </select>
      </div>

      <Card padding="none">
        {/* Driven by the SERVER page for the active tab, not by the filtered
            rows below it. The search box narrows what is on screen and cannot
            reach the rows the server withheld, so a search that finds nothing
            still has to say the register was only partly read. */}
        {activeQuery.data && <TruncationNotice page={activeQuery.data} className="px-4 pt-3" />}
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
          /* `activeQuery` is this tab's own query, so its envelope total is
             the size of the register the table is showing. The tables need it
             to tell an empty register apart from a search that matched none of
             the loaded page, the same distinction the notice above draws. */
          <NoticeTable
            rows={filteredNotices}
            registerTotal={activeQuery.data?.total ?? 0}
            onClearFilters={filtersActive ? clearFilters : undefined}
            onSelect={(id) => setSelected({ kind: 'notices', id })}
            onEdit={(row) => setEditTarget({ kind: 'notices', row })}
            onDelete={(id) => void handleDelete('notices', id)}
            emptyAction={() => setCreateOpen(true)}
          />
        ) : tab === 'requests' ? (
          <RequestTable
            rows={filteredRequests}
            registerTotal={activeQuery.data?.total ?? 0}
            onClearFilters={filtersActive ? clearFilters : undefined}
            currency={currency}
            onSelect={(id) => setSelected({ kind: 'requests', id })}
            onEdit={(row) => setEditTarget({ kind: 'requests', row })}
            onDelete={(id) => void handleDelete('requests', id)}
            emptyAction={() => setCreateOpen(true)}
          />
        ) : tab === 'orders' ? (
          <OrderTable
            rows={filteredOrders}
            registerTotal={activeQuery.data?.total ?? 0}
            onClearFilters={filtersActive ? clearFilters : undefined}
            currency={currency}
            onSelect={(id) => setSelected({ kind: 'orders', id })}
            onEdit={(row) => setEditTarget({ kind: 'orders', row })}
            onDelete={(id) => void handleDelete('orders', id)}
            emptyAction={() => setCreateOpen(true)}
          />
        ) : tab === 'daywork' ? (
          <DayworkTable
            rows={filteredDaywork}
            registerTotal={activeQuery.data?.total ?? 0}
            onClearFilters={filtersActive ? clearFilters : undefined}
            currency={currency}
            onSelect={(id) => setSelected({ kind: 'daywork', id })}
            onEdit={(row) => setEditTarget({ kind: 'daywork', row })}
            onDelete={(id) => void handleDelete('daywork', id)}
            emptyAction={() => setCreateOpen(true)}
          />
        ) : (
          <EoTTable
            rows={filteredEot}
            registerTotal={activeQuery.data?.total ?? 0}
            onClearFilters={filtersActive ? clearFilters : undefined}
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
          projectId={projectId}
          notices={noticesQ.data?.items ?? []}
          requests={requestsQ.data?.items ?? []}
          orders={ordersQ.data?.items ?? []}
          daywork={dayworkQ.data?.items ?? []}
          eot={eotQ.data?.items ?? []}
          currency={currency}
          onClose={closeDetail}
        />
      )}

      {createOpen && (
        <CreateModal
          kind={tab}
          projectId={projectId}
          currency={currency}
          notices={noticesQ.data?.items ?? []}
          requests={requestsQ.data?.items ?? []}
          onClose={() => setCreateOpen(false)}
        />
      )}

      {editTarget && (
        <CreateModal
          kind={editTarget.kind}
          projectId={projectId}
          currency={currency}
          notices={noticesQ.data?.items ?? []}
          requests={requestsQ.data?.items ?? []}
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
  registerTotal,
  onClearFilters,
  onSelect,
  onEdit,
  onDelete,
  emptyAction,
}: {
  rows: Notice[];
  /** What the register holds, from the page envelope, not what survived the search box. */
  registerTotal: number;
  /** Set only while a filter narrows the list, and clears every one of them.
      Its presence is also the signal that `registerTotal` counts a filtered
      query rather than the register, so it cannot be read as a denial. */
  onClearFilters?: () => void;
  onSelect: (id: string) => void;
  onEdit: (row: Notice) => void;
  onDelete: (id: string) => void;
  emptyAction: () => void;
}) {
  const { t } = useTranslation();
  if (rows.length === 0) {
    // Whether the register is empty is answered by the register, not by what
    // survived the search box narrowing the loaded page. Reading it off `rows`
    // prints "No notices yet" under a notice reporting how many the register
    // holds, and invites the reader to raise the first one.
    if (registerTotal > 0 || onClearFilters) {
      return (
        <EmptyState
          icon={<Bell size={22} />}
          title={t('common.no_results', { defaultValue: 'No results found' })}
          action={
            onClearFilters
              ? {
                  label: t('common.clear_filters', { defaultValue: 'Clear filters' }),
                  onClick: onClearFilters,
                }
              : undefined
          }
        />
      );
    }
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
                  {statusLabel(r.status, t)}
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
  registerTotal,
  onClearFilters,
  currency,
  onSelect,
  onEdit,
  onDelete,
  emptyAction,
}: {
  rows: VariationRequest[];
  /** What the register holds, from the page envelope, not what survived the search box. */
  registerTotal: number;
  /** Set only while a filter narrows the list, and clears every one of them.
      Its presence is also the signal that `registerTotal` counts a filtered
      query rather than the register, so it cannot be read as a denial. */
  onClearFilters?: () => void;
  currency: string;
  onSelect: (id: string) => void;
  onEdit: (row: VariationRequest) => void;
  onDelete: (id: string) => void;
  emptyAction: () => void;
}) {
  const { t } = useTranslation();
  if (rows.length === 0) {
    if (registerTotal > 0 || onClearFilters) {
      return (
        <EmptyState
          icon={<FileText size={22} />}
          title={t('common.no_results', { defaultValue: 'No results found' })}
          action={
            onClearFilters
              ? {
                  label: t('common.clear_filters', { defaultValue: 'Clear filters' }),
                  onClick: onClearFilters,
                }
              : undefined
          }
        />
      );
    }
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
              <td className="px-4 py-2 text-xs text-content-secondary">{classLabel(r.classification, t)}</td>
              <td className="px-4 py-2 text-right tabular-nums">
                <MoneyDisplay
                  amount={Number(r.estimated_cost_impact) || 0}
                  currency={r.currency || currency}
                />
              </td>
              <td className="px-4 py-2 text-right tabular-nums">{r.estimated_schedule_days}</td>
              <td className="px-4 py-2">
                <Badge variant={VR_VARIANT[r.status]} dot>
                  {statusLabel(r.status, t)}
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
  registerTotal,
  onClearFilters,
  currency,
  onSelect,
  onEdit,
  onDelete,
  emptyAction,
}: {
  rows: VariationOrder[];
  /** What the register holds, from the page envelope, not what survived the search box. */
  registerTotal: number;
  /** Set only while a filter narrows the list, and clears every one of them.
      Its presence is also the signal that `registerTotal` counts a filtered
      query rather than the register, so it cannot be read as a denial. */
  onClearFilters?: () => void;
  currency: string;
  onSelect: (id: string) => void;
  onEdit: (row: VariationOrder) => void;
  onDelete: (id: string) => void;
  emptyAction: () => void;
}) {
  const { t } = useTranslation();
  if (rows.length === 0) {
    if (registerTotal > 0 || onClearFilters) {
      return (
        <EmptyState
          icon={<FileCheck2 size={22} />}
          title={t('common.no_results', { defaultValue: 'No results found' })}
          action={
            onClearFilters
              ? {
                  label: t('common.clear_filters', { defaultValue: 'Clear filters' }),
                  onClick: onClearFilters,
                }
              : undefined
          }
        />
      );
    }
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
                  {statusLabel(r.status, t)}
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
  registerTotal,
  onClearFilters,
  currency,
  onSelect,
  onEdit,
  onDelete,
  emptyAction,
}: {
  rows: DayworkSheet[];
  /** What the register holds, from the page envelope, not what survived the search box. */
  registerTotal: number;
  /** Set only while a filter narrows the list, and clears every one of them.
      Its presence is also the signal that `registerTotal` counts a filtered
      query rather than the register, so it cannot be read as a denial. */
  onClearFilters?: () => void;
  currency: string;
  onSelect: (id: string) => void;
  onEdit: (row: DayworkSheet) => void;
  onDelete: (id: string) => void;
  emptyAction: () => void;
}) {
  const { t } = useTranslation();
  if (rows.length === 0) {
    if (registerTotal > 0 || onClearFilters) {
      return (
        <EmptyState
          icon={<Hammer size={22} />}
          title={t('common.no_results', { defaultValue: 'No results found' })}
          action={
            onClearFilters
              ? {
                  label: t('common.clear_filters', { defaultValue: 'Clear filters' }),
                  onClick: onClearFilters,
                }
              : undefined
          }
        />
      );
    }
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
                  {statusLabel(r.status, t)}
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
  registerTotal,
  onClearFilters,
  onSelect,
  onEdit,
  onDelete,
  emptyAction,
}: {
  rows: ExtensionOfTimeClaim[];
  /** What the register holds, from the page envelope, not what survived the search box. */
  registerTotal: number;
  /** Set only while a filter narrows the list, and clears every one of them.
      Its presence is also the signal that `registerTotal` counts a filtered
      query rather than the register, so it cannot be read as a denial. */
  onClearFilters?: () => void;
  onSelect: (id: string) => void;
  onEdit: (row: ExtensionOfTimeClaim) => void;
  onDelete: (id: string) => void;
  emptyAction: () => void;
}) {
  const { t } = useTranslation();
  if (rows.length === 0) {
    if (registerTotal > 0 || onClearFilters) {
      return (
        <EmptyState
          icon={<Clock size={22} />}
          title={t('common.no_results', { defaultValue: 'No results found' })}
          action={
            onClearFilters
              ? {
                  label: t('common.clear_filters', { defaultValue: 'Clear filters' }),
                  onClick: onClearFilters,
                }
              : undefined
          }
        />
      );
    }
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
                  {statusLabel(r.status, t)}
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
  changeOrderId,
  contractId,
}: {
  notice: Notice | null;
  request: VariationRequest | null;
  order: VariationOrder | null;
  changeOrderId?: string | null;
  contractId?: string | null;
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
    ...(changeOrderId
      ? [{
          label: t('variations.step_change_order', { defaultValue: 'CO' }),
          present: true,
          status: undefined as string | undefined,
        }]
      : []),
    ...(contractId
      ? [{
          label: t('variations.step_contract', { defaultValue: 'Contract' }),
          present: true,
          status: undefined as string | undefined,
        }]
      : []),
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
            {s.status ? ` · ${statusLabel(s.status, t)}` : ''}
          </span>
          {idx < steps.length - 1 && <ChevronRight size={12} className="text-content-tertiary" />}
        </div>
      ))}
    </div>
  );
}

/** Where the other records of the change chain live.
 *
 * The destinations are defined once in `@/shared/lib/changeChainLinks`, so
 * the change-order and management-of-change pages reach them without pulling
 * this page into their bundle chunks. Re-exported here for the callers that
 * learned the two names on this module.
 */
export { changeOrderDeepLink, variationBoqDeepLink };

/** The priced scope of one variation request, inside the request drawer.
 *
 * Placement is deliberate. This is per-request state, not a register, so it
 * belongs beside the request it describes rather than behind a sixth tab that
 * would ask the user to leave the record to see its own price.
 *
 * A request that has no bill is the normal case and says so plainly, with the
 * one button that changes it. Nothing here writes to the headline estimate on
 * its own: the bill and the estimate are shown side by side, and it takes a
 * click to make the priced figure the one the request carries.
 */
function PricedScope({
  request,
  currency,
}: {
  request: VariationRequest;
  currency: string;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const addToast = useToastStore((s) => s.addToast);
  const [pickerOpen, setPickerOpen] = useState(false);

  const boqQ = useQuery<VariationBOQ>({
    queryKey: ['variations', 'request-boq', request.id],
    queryFn: () => getVariationRequestBOQ(request.id),
  });

  // The payload is the whole point of this mutation. It used to be called with
  // no argument, so the endpoint that seeds a bill from named contract lines
  // and estimating positions was reachable only over the API and every bill
  // opened from the product had no provenance at all.
  const openMut = useMutation({
    mutationFn: (payload: CreateVariationBOQPayload) =>
      createVariationRequestBOQ(request.id, payload),
    onSuccess: (boq) => {
      qc.invalidateQueries({ queryKey: ['variations'] });
      addToast({
        type: 'success',
        title: t('variations.boq_opened', { defaultValue: 'Bill opened' }),
      });
      navigate(variationBoqDeepLink(boq.id));
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  const adoptMut = useMutation({
    mutationFn: () => adoptVariationRequestBOQ(request.id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['variations'] });
      addToast({
        type: 'success',
        title: t('variations.boq_adopted', {
          defaultValue: 'Estimate taken from the bill',
        }),
      });
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  const boq = boqQ.data;
  const decided =
    request.status === 'approved' ||
    request.status === 'rejected' ||
    request.status === 'converted_to_vo';

  return (
    <Card padding="sm">
      <p className="text-xs font-semibold uppercase tracking-wide text-content-secondary mb-2">
        {t('variations.priced_scope', { defaultValue: 'Priced scope' })}
      </p>

      {boqQ.isLoading && (
        <p className="text-sm text-content-tertiary">
          {t('common.loading', { defaultValue: 'Loading…' })}
        </p>
      )}

      {boqQ.isError && (
        <p className="text-sm text-content-tertiary">{getErrorMessage(boqQ.error)}</p>
      )}

      {boq && !boq.has_boq && (
        <div className="space-y-2">
          <p className="text-sm text-content-secondary">
            {t('variations.priced_scope_hint', {
              defaultValue:
                'Price this variation on a bill of its own, holding only the scope it changes and separate from the project estimate.',
            })}
          </p>
          {pickerOpen ? (
            <VariationSourcePicker
              projectId={request.project_id}
              busy={openMut.isPending}
              onOpen={(payload) => openMut.mutate(payload)}
              onCancel={() => setPickerOpen(false)}
            />
          ) : (
            <Button
              variant="secondary"
              icon={<Calculator size={14} />}
              onClick={() => setPickerOpen(true)}
            >
              {t('variations.open_variation_boq', { defaultValue: 'Open a bill' })}
            </Button>
          )}
        </div>
      )}

      {boq && boq.has_boq && (
        <div className="space-y-3">
          <div className="grid grid-cols-2 gap-3 text-sm">
            <Field
              label={t('variations.priced_total', { defaultValue: 'Priced total' })}
              value={
                <MoneyDisplay
                  amount={Number(boq.grand_total ?? 0)}
                  currency={boq.base_currency || request.currency || currency}
                />
              }
            />
            <Field
              label={t('variations.priced_lines', { defaultValue: 'Priced lines' })}
              value={String(boq.position_count)}
            />
            <Field
              label={t('variations.traced_lines', { defaultValue: 'Traced lines' })}
              value={String(boq.traces.length)}
            />
            <Field
              label={t('variations.boq_name', { defaultValue: 'Bill' })}
              value={boq.name || '—'}
            />
          </div>

          {/* What the variation does to the contract, before markups: the
              direct cost split by added / removed / modified, with the net as
              their sum so an omission visibly comes off. A line nobody has
              traced counts as added, the same reading the bill's rule gives it. */}
          {boq.change_summary && (() => {
            const summary = boq.change_summary;
            const money = boq.base_currency || request.currency || currency;
            const cell = (label: string, subtotal: { line_count: number; total: string }) => (
              <Field
                label={`${label} · ${subtotal.line_count}`}
                value={<MoneyDisplay amount={Number(subtotal.total)} currency={money} />}
              />
            );
            return (
              <div data-testid="variation-change-summary">
                <p className="text-xs uppercase tracking-wide text-content-tertiary mb-1">
                  {t('variations.change_summary', { defaultValue: 'Change to the contract' })}
                </p>
                <div className="grid grid-cols-2 gap-3 text-sm">
                  {cell(t('variations.change_added', { defaultValue: 'Added' }), summary.added)}
                  {cell(t('variations.change_removed', { defaultValue: 'Removed' }), summary.removed)}
                  {cell(t('variations.change_modified', { defaultValue: 'Modified' }), summary.modified)}
                  <Field
                    label={t('variations.net_change', { defaultValue: 'Net change' })}
                    value={<MoneyDisplay amount={Number(summary.net_total)} currency={money} />}
                  />
                </div>
              </div>
            );
          })()}

          {boq.is_mixed_currency && (
            <p className="flex items-start gap-1.5 text-xs text-content-secondary">
              <AlertTriangle size={13} className="mt-0.5 shrink-0" />
              {t('variations.boq_mixed_currency', {
                defaultValue:
                  'This bill blends currencies, so its total is not a figure to settle on yet.',
              })}
            </p>
          )}

          {!boq.estimate_matches_boq && !boq.is_mixed_currency && (
            <p className="text-xs text-content-secondary">
              {t('variations.boq_differs_from_estimate', {
                defaultValue:
                  'The estimate on this request has not been taken from the bill yet, so the two figures above are saying different things.',
              })}
            </p>
          )}

          {boq.checks.map((check, index) => (
            <p
              key={`${check.rule_id}:${index}`}
              className="flex items-start gap-1.5 text-xs text-content-secondary"
            >
              <AlertTriangle size={13} className="mt-0.5 shrink-0" />
              {check.message}
            </p>
          ))}

          <div className="flex flex-wrap gap-2">
            {boq.boq_id && (
              <Button
                variant="secondary"
                icon={<Calculator size={14} />}
                onClick={() => navigate(variationBoqDeepLink(boq.boq_id as string))}
              >
                {t('variations.open_boq_editor', { defaultValue: 'Open bill' })}
              </Button>
            )}
            {!decided && !boq.estimate_matches_boq && !boq.is_mixed_currency && (
              <Button
                variant="primary"
                icon={<CheckCircle2 size={14} />}
                onClick={() => adoptMut.mutate()}
                loading={adoptMut.isPending}
              >
                {t('variations.adopt_boq_total', { defaultValue: 'Use as estimate' })}
              </Button>
            )}
          </div>
        </div>
      )}
    </Card>
  );
}

type Translate = ReturnType<typeof useTranslation>['t'];

/** The label a recorded `agreed_basis` reads as on screen. */
function agreedBasisLabel(basis: string, t: Translate): string {
  if (basis === 'negotiated') {
    return t('variations.agreed_basis_negotiated', { defaultValue: 'Negotiated' });
  }
  if (basis === 'priced_boq') {
    return t('variations.agreed_basis_priced_boq', { defaultValue: 'Priced bill' });
  }
  if (basis === 'headline_estimate') {
    return t('variations.agreed_basis_headline', { defaultValue: 'Headline estimate' });
  }
  return basis;
}

/** What a decided request was agreed at, and on what footing (Issue #435).
 *
 * Shown after the decision because the agreed amount is a different fact from
 * the estimate the request was raised with, and until now the screen showed
 * only the estimate. A reader looking at an approved variation could not tell
 * whether the figure carried forward was priced, negotiated or simply the
 * headline nobody revisited.
 */
export function AgreedValueCard({
  request,
  currency,
}: {
  request: VariationRequest;
  currency: string;
}) {
  const { t } = useTranslation();
  if (!request.agreed_basis) return null;

  return (
    <Card padding="sm">
      <p className="text-xs font-semibold uppercase tracking-wide text-content-secondary mb-2">
        {t('variations.agreed_value', { defaultValue: 'Agreed value' })}
      </p>
      <div className="grid grid-cols-2 gap-3 text-sm">
        <Field
          label={t('variations.agreed_amount', { defaultValue: 'Agreed amount' })}
          value={
            request.agreed_cost_impact === null ? (
              '—'
            ) : (
              <MoneyDisplay
                amount={Number(request.agreed_cost_impact)}
                currency={request.currency || currency}
              />
            )
          }
        />
        <Field
          label={t('variations.agreed_basis', { defaultValue: 'Basis' })}
          value={agreedBasisLabel(request.agreed_basis, t)}
        />
        <Field
          label={t('variations.submitted_boq_total', {
            defaultValue: 'Submitted bill total',
          })}
          value={
            request.submitted_boq_total === null ? (
              t('variations.no_submitted_bill', { defaultValue: 'No bill submitted' })
            ) : (
              <MoneyDisplay
                amount={Number(request.submitted_boq_total)}
                currency={request.currency || currency}
              />
            )
          }
        />
      </div>
      {request.agreed_variance_note && (
        <div className="mt-2">
          <p className="text-xs uppercase tracking-wide text-content-tertiary">
            {t('variations.agreed_variance_note', { defaultValue: 'What was negotiated' })}
          </p>
          <p className="mt-0.5 text-sm whitespace-pre-wrap">{request.agreed_variance_note}</p>
        </div>
      )}
    </Card>
  );
}

/** The approval itself, as two acts rather than one button (Issue #435).
 *
 * A quantity surveyor either accepts the pricing state that was submitted or
 * agrees a different figure with the other side. The second is the case the
 * reporter's example turns on - a variation claimed at 12,000, priced at 7,500
 * and settled at 7,200 - and it was unreachable from the product: the screen
 * posted the decision notes and nothing else, so every approval was recorded
 * as the submitted total on a priced-bill basis.
 *
 * The reason is required exactly where the figure departs from what was
 * submitted, and not when the two agree. An unexplained departure is the one
 * part of the decision nobody can reconstruct from the record afterwards.
 */
export function ApprovalDecisionPanel({
  request,
  currency,
  approving,
  rejecting,
  onApprove,
  onReject,
}: {
  request: VariationRequest;
  currency: string;
  approving: boolean;
  rejecting: boolean;
  onApprove: (payload: ApproveVRPayload) => void;
  onReject: (decisionNotes?: string) => void;
}) {
  const { t } = useTranslation();
  const [mode, setMode] = useState<ApprovalMode>('as_submitted');
  const [agreedAmount, setAgreedAmount] = useState('');
  const [varianceNote, setVarianceNote] = useState('');
  const [decisionNotes, setDecisionNotes] = useState('');

  const baseline = approvalBaseline(request);
  const draft = { mode, agreedAmount, varianceNote, decisionNotes };
  const blockReason = approvalBlockReason(draft, baseline);

  return (
    <Card padding="sm" className="w-full">
      <p className="text-xs font-semibold uppercase tracking-wide text-content-secondary mb-2">
        {t('variations.decision', { defaultValue: 'Decision' })}
      </p>
      <div className="space-y-2">
        <Field
          label={
            baseline.source === 'submitted_boq'
              ? t('variations.submitted_boq_total', { defaultValue: 'Submitted bill total' })
              : t('variations.headline_estimate', { defaultValue: 'Headline estimate' })
          }
          value={
            baseline.amount === null ? (
              '—'
            ) : (
              <MoneyDisplay
                amount={baseline.amount}
                currency={request.currency || currency}
              />
            )
          }
        />

        <div className="space-y-1">
          <label className="flex items-start gap-2 text-sm">
            <input
              type="radio"
              className="mt-1"
              name={`approval-mode-${request.id}`}
              checked={mode === 'as_submitted'}
              onChange={() => setMode('as_submitted')}
            />
            <span>
              {t('variations.approve_as_submitted', {
                defaultValue: 'Approve the amount that was submitted',
              })}
            </span>
          </label>
          <label className="flex items-start gap-2 text-sm">
            <input
              type="radio"
              className="mt-1"
              name={`approval-mode-${request.id}`}
              checked={mode === 'negotiated'}
              onChange={() => setMode('negotiated')}
            />
            <span>
              {t('variations.approve_negotiated', {
                defaultValue: 'Approve a negotiated amount',
              })}
            </span>
          </label>
        </div>

        {mode === 'negotiated' && (
          <div className="space-y-2 rounded-lg border border-border-light p-2">
            <div>
              <label
                htmlFor={`agreed-amount-${request.id}`}
                className="text-xs uppercase tracking-wide text-content-tertiary"
              >
                {t('variations.agreed_amount', { defaultValue: 'Agreed amount' })}
              </label>
              <input
                id={`agreed-amount-${request.id}`}
                type="number"
                step="0.01"
                value={agreedAmount}
                onChange={(e) => setAgreedAmount(e.target.value)}
                className={clsx(inputCls, 'mt-0.5')}
              />
            </div>
            <div>
              <label
                htmlFor={`variance-note-${request.id}`}
                className="text-xs uppercase tracking-wide text-content-tertiary"
              >
                {t('variations.agreed_variance_note', { defaultValue: 'What was negotiated' })}
              </label>
              <textarea
                id={`variance-note-${request.id}`}
                rows={2}
                value={varianceNote}
                onChange={(e) => setVarianceNote(e.target.value)}
                placeholder={t('variations.agreed_variance_note_placeholder', {
                  defaultValue: 'Why the agreed amount differs from what was submitted…',
                })}
                className={clsx(inputCls, 'mt-0.5 h-auto py-2')}
              />
            </div>
            {blockReason && (
              <p className="flex items-start gap-1.5 text-xs text-content-secondary">
                <AlertTriangle size={13} className="mt-0.5 shrink-0" />
                {blockReason === 'amount_missing'
                  ? t('variations.agreed_amount_required', {
                      defaultValue:
                        'Type the amount that was agreed, or approve the submitted amount instead.',
                    })
                  : t('variations.agreed_variance_required', {
                      defaultValue:
                        'This differs from the amount that was submitted, so the approval needs a reason. The gap between the two figures is the part nobody can reconstruct later.',
                    })}
              </p>
            )}
          </div>
        )}

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
            disabled={blockReason !== null}
            onClick={() => onApprove(buildApprovalPayload(draft))}
            loading={approving}
          >
            {t('variations.approve', { defaultValue: 'Approve' })}
          </Button>
          <Button
            variant="danger"
            icon={<XCircle size={14} />}
            onClick={() => onReject(decisionNotes.trim() || undefined)}
            loading={rejecting}
          >
            {t('variations.reject', { defaultValue: 'Reject' })}
          </Button>
        </div>
      </div>
    </Card>
  );
}

/** Promotion, with the contract the resulting order amends (Issue #435).
 *
 * `affected_contract_id` has been accepted on the promotion since August and
 * nothing named it, so every order promoted from this screen was created
 * unattached and could never post to a contract. Completing an order that
 * names one is what moves the contract sum, so leaving it out quietly
 * disconnects the variation from the money it is supposed to move.
 *
 * The default comes from the bill rather than from a guess: where every
 * schedule-of-values line the variation is priced against belongs to one
 * contract, that is the contract it amends, and the surveyor confirms rather
 * than looks it up.
 */
export function PromoteToOrderCard({
  request,
  projectId,
  contractId,
  onContractIdChange,
  onPromote,
  promoting,
}: {
  request: VariationRequest;
  projectId: string;
  contractId: string;
  onContractIdChange: (value: string) => void;
  onPromote: () => void;
  promoting: boolean;
}) {
  const { t } = useTranslation();

  const contractsQ = useQuery({
    queryKey: ['variations', 'promote-contracts', projectId],
    queryFn: () => listContracts({ project_id: projectId, limit: 200 }),
    enabled: Boolean(projectId),
  });

  const boqQ = useQuery<VariationBOQ>({
    queryKey: ['variations', 'request-boq', request.id],
    queryFn: () => getVariationRequestBOQ(request.id),
  });

  // The contract the priced scope traces back to, when the traces agree on
  // one. Two contracts in one bill is a real situation and the answer there
  // is to make the reader choose, not to pick the first one.
  const tracedContractId = useMemo(() => {
    const ids = new Set(
      (boqQ.data?.traces ?? [])
        .map((trace) => trace.contract_id)
        .filter((id): id is string => Boolean(id)),
    );
    return ids.size === 1 ? [...ids][0] : '';
  }, [boqQ.data]);

  useEffect(() => {
    if (tracedContractId && !contractId) onContractIdChange(tracedContractId);
  }, [tracedContractId, contractId, onContractIdChange]);

  const contracts = contractsQ.data?.items ?? [];

  return (
    <Card padding="sm" className="w-full">
      <p className="text-xs font-semibold uppercase tracking-wide text-content-secondary mb-2">
        {t('variations.promote_to_order', { defaultValue: 'Promote to order' })}
      </p>
      <div className="space-y-2">
        <div>
          <label
            htmlFor={`affected-contract-${request.id}`}
            className="text-xs uppercase tracking-wide text-content-tertiary"
          >
            {t('variations.affected_contract', {
              defaultValue: 'Contract this order amends',
            })}
          </label>
          <select
            id={`affected-contract-${request.id}`}
            value={contractId}
            onChange={(e) => onContractIdChange(e.target.value)}
            className={clsx(inputCls, 'mt-0.5')}
          >
            <option value="">
              {t('variations.affected_contract_none', {
                defaultValue: 'Not linked to a contract',
              })}
            </option>
            {contracts.map((contract) => (
              <option key={contract.id} value={contract.id}>
                {[contract.code, contract.title].filter(Boolean).join(' - ') || contract.id}
              </option>
            ))}
          </select>
        </div>
        <p className="text-xs text-content-secondary">
          {t('variations.affected_contract_hint', {
            defaultValue:
              'Completing an order that names a contract is what moves the contract sum. An order left unlinked never posts to one.',
          })}
        </p>
        <Button
          variant="primary"
          icon={<ArrowRight size={14} />}
          onClick={onPromote}
          loading={promoting}
        >
          {t('variations.convert_to_vo', { defaultValue: 'Convert to Order' })}
        </Button>
      </div>
    </Card>
  );
}

export function DetailDrawer({
  selected,
  projectId,
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
  projectId: string;
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

  // Read once, here, rather than inside the pill's onClick: narrowing a
  // nullable property does not survive into a callback, and a plain const does.
  const linkedChangeOrderId = order?.reference_change_order_id ?? null;
  const linkedContractId = order?.affected_contract_id ?? null;

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
  // The request's approval carries an agreed amount and the reason for it, so
  // its payload is built by the decision panel that collected them rather than
  // read off a single shared notes box. The EoT decision below still uses
  // `decisionNotes`, which is why that state stays here.
  const approveMut = useMutation({
    mutationFn: (payload: ApproveVRPayload) => approveVR(selected.id, payload),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['variations'] });
      addToast({ type: 'success', title: t('variations.vr_approved', { defaultValue: 'Request approved' }) });
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });
  const rejectMut = useMutation({
    mutationFn: (notes: string | undefined) => rejectVR(selected.id, notes),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['variations'] });
      addToast({ type: 'success', title: t('variations.vr_rejected', { defaultValue: 'Request rejected' }) });
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });
  // The contract a promoted order lands on. Nothing set it, so an order made
  // through this screen reached no contract and never posted to one - the
  // third of the three fields the API accepts and the screen left empty.
  const [promoteContractId, setPromoteContractId] = useState('');
  const convertMut = useMutation({
    mutationFn: () =>
      convertVRToVO(
        selected.id,
        request
          ? {
              currency: request.currency || currency,
              ...(promoteContractId ? { affected_contract_id: promoteContractId } : {}),
            }
          : {},
      ),
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
              changeOrderId={chainOrder?.reference_change_order_id}
              contractId={chainOrder?.affected_contract_id}
            />
          )}

          {/* Claims evidence: how provable this variation is from the record,
              and the reconciled evidence thread around it, ready to export for
              a claim. Only for the contractual chain (notice / request / order);
              day-works and EOT claims have no provability mapping. */}
          {(selected.kind === 'notices' ||
            selected.kind === 'requests' ||
            selected.kind === 'orders') &&
            (() => {
              const provKind: SubjectKind =
                selected.kind === 'notices'
                  ? 'variation_notice'
                  : selected.kind === 'requests'
                    ? 'variation_request'
                    : 'variation_order';
              const reconstructType = reconstructTypeForKind(provKind);
              return (
                <div className="space-y-3">
                  <ProvabilityGauge projectId={projectId} subjectKind={provKind} subjectId={selected.id} />
                  {reconstructType ? (
                    <EvidenceThreadPanel
                      projectId={projectId}
                      subjectType={reconstructType}
                      subjectId={selected.id}
                    />
                  ) : null}
                </div>
              );
            })()}

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
                      {statusLabel(notice.status, t)}
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
                  value={classLabel(request.classification, t)}
                />
                <Field
                  label={t('variations.urgency', { defaultValue: 'Urgency' })}
                  value={urgencyLabel(request.urgency, t)}
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
                      {statusLabel(request.status, t)}
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
              <AgreedValueCard request={request} currency={currency} />
              <PricedScope request={request} currency={currency} />
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
                  <ApprovalDecisionPanel
                    request={request}
                    currency={currency}
                    approving={approveMut.isPending}
                    rejecting={rejectMut.isPending}
                    onApprove={(payload) => approveMut.mutate(payload)}
                    onReject={(notes) => rejectMut.mutate(notes)}
                  />
                )}
                {request.status === 'approved' && (
                  <PromoteToOrderCard
                    request={request}
                    projectId={projectId}
                    contractId={promoteContractId}
                    onContractIdChange={setPromoteContractId}
                    onPromote={() => convertMut.mutate()}
                    promoting={convertMut.isPending}
                  />
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
                      {statusLabel(order.status, t)}
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
                  {linkedChangeOrderId && (
                    <button
                      type="button"
                      className="flex items-center gap-1.5 rounded-lg border border-blue-200 bg-blue-50 dark:bg-blue-950/20 dark:border-blue-800 px-2.5 py-1.5 text-xs text-blue-700 dark:text-blue-300 hover:bg-blue-100 transition-colors"
                      onClick={() => navigate(changeOrderDeepLink(linkedChangeOrderId))}
                    >
                      <ArrowRight size={12} />
                      {t('variations.linked_change_order', { defaultValue: 'Change order' })}
                    </button>
                  )}
                  {/* The contract register reads ?highlight= since Issue #435's
                      navigation pass, so this lands on the contract the order
                      amends rather than on the register it lives in. */}
                  {linkedContractId && (
                    <button
                      type="button"
                      className="flex items-center gap-1.5 rounded-lg border border-blue-200 bg-blue-50 dark:bg-blue-950/20 dark:border-blue-800 px-2.5 py-1.5 text-xs text-blue-700 dark:text-blue-300 hover:bg-blue-100 transition-colors"
                      onClick={() => navigate(contractDeepLink(linkedContractId))}
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
                      {statusLabel(sheet.status, t)}
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
                      {statusLabel(claim.status, t)}
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

/* ── Form initializers ──────────────────────────────────────────────────
 * Pure so they can serve twice: once to seed the form and once to hold the
 * untouched baseline `submit` compares against. A single definition is the
 * point. If the baseline were built any other way, a field the user never
 * touched could still read as changed and get written back.
 * ---------------------------------------------------------------------- */

export function initNoticeForm(n: Notice | null) {
  return {
    title: n?.title ?? '',
    description: n?.description ?? '',
    recipient_type: (n?.recipient_type ?? 'owner') as Notice['recipient_type'],
    recipient_name: n?.recipient_name ?? '',
    target_response_date: toDateInput(n?.target_response_date),
  };
}

export function initVrForm(r: VariationRequest | null, currency: string) {
  return {
    title: r?.title ?? '',
    description: r?.description ?? '',
    notice_id: r?.notice_id ?? '',
    classification: (r?.classification ?? 'scope_change') as VariationRequest['classification'],
    urgency: (r?.urgency ?? 'med') as VariationRequest['urgency'],
    estimated_cost_impact: r != null ? String(r.estimated_cost_impact ?? '0') : '0',
    estimated_schedule_days: r != null ? String(r.estimated_schedule_days ?? '0') : '0',
    currency: r?.currency || currency,
  };
}

export function initVoForm(o: VariationOrder | null, currency: string) {
  return {
    title: o?.title ?? '',
    variation_request_id: o?.variation_request_id ?? '',
    final_cost_impact: o != null ? String(o.final_cost_impact ?? '0') : '0',
    final_schedule_days: o != null ? String(o.final_schedule_days ?? '0') : '0',
    currency: o?.currency || currency,
  };
}

export function initDayworkForm(d: DayworkSheet | null, currency: string) {
  return {
    work_date: toDateInput(d?.work_date),
    description: d?.description ?? '',
    currency: d?.currency || currency,
  };
}

export function initEotForm(e: ExtensionOfTimeClaim | null) {
  return {
    description: e?.description ?? '',
    root_cause_category: (e?.root_cause_category ??
      'neutral') as ExtensionOfTimeClaim['root_cause_category'],
    requested_days: e != null ? String(e.requested_days ?? '0') : '0',
    critical_path_impact: e?.critical_path_impact ?? false,
    claim_period_start: toDateInput(e?.claim_period_start),
    claim_period_end: toDateInput(e?.claim_period_end),
  };
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

  // Each form keeps the state it was initialized with. Comparing against that
  // baseline rather than against the raw row is what makes the change detection
  // in `submit` trustworthy: both sides have been through the same defaulting
  // and date formatting, so an untouched field always compares equal.
  const noticeBase = useMemo(
    () => initNoticeForm(editTarget?.kind === 'notices' ? editTarget.row : null),
    [editTarget],
  );
  const [noticeForm, setNoticeForm] = useState(noticeBase);

  const vrBase = useMemo(
    () => initVrForm(editTarget?.kind === 'requests' ? editTarget.row : null, currency),
    [editTarget, currency],
  );
  const [vrForm, setVrForm] = useState(vrBase);

  const voBase = useMemo(
    () => initVoForm(editTarget?.kind === 'orders' ? editTarget.row : null, currency),
    [editTarget, currency],
  );
  const [voForm, setVoForm] = useState(voBase);

  const dwBase = useMemo(
    () => initDayworkForm(editTarget?.kind === 'daywork' ? editTarget.row : null, currency),
    [editTarget, currency],
  );
  const [dwForm, setDwForm] = useState(dwBase);

  const eotBase = useMemo(
    () => initEotForm(editTarget?.kind === 'eot' ? editTarget.row : null),
    [editTarget],
  );
  const [eotForm, setEotForm] = useState(eotBase);

  const submit = async () => {
    setBusy(true);
    try {
      const editId = editTarget?.row.id ?? '';
      if (kind === 'notices') {
        if (isEdit && editTarget?.kind === 'notices') {
          await updateNotice(
            editId,
            onlyChangedFields(
              {
                title: noticeForm.title.trim(),
                description: noticeForm.description.trim(),
                recipient_type: noticeForm.recipient_type,
                recipient_name: noticeForm.recipient_name.trim(),
                target_response_date: noticeForm.target_response_date || null,
              },
              noticeForm,
              noticeBase,
            ),
          );
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
          await updateVR(
            editId,
            onlyChangedFields(
              {
                title: vrForm.title.trim(),
                description: vrForm.description.trim(),
                classification: vrForm.classification,
                urgency: vrForm.urgency,
                estimated_cost_impact: Number(vrForm.estimated_cost_impact) || 0,
                estimated_schedule_days: Number(vrForm.estimated_schedule_days) || 0,
                currency: vrForm.currency,
              },
              vrForm,
              vrBase,
            ),
          );
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
          await updateVO(
            editId,
            onlyChangedFields(
              {
                title: voForm.title.trim(),
                final_cost_impact: Number(voForm.final_cost_impact) || 0,
                final_schedule_days: Number(voForm.final_schedule_days) || 0,
                currency: voForm.currency,
              },
              voForm,
              voBase,
            ),
          );
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
          await updateDaywork(
            editId,
            onlyChangedFields(
              {
                work_date: dwForm.work_date || null,
                description: dwForm.description.trim(),
                currency: dwForm.currency,
              },
              dwForm,
              dwBase,
            ),
          );
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
          await updateEoT(
            editId,
            onlyChangedFields(
              {
                description: eotForm.description.trim(),
                root_cause_category: eotForm.root_cause_category,
                requested_days: Number(eotForm.requested_days) || 0,
                critical_path_impact: eotForm.critical_path_impact,
              },
              eotForm,
              eotBase,
            ),
          );
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
                    {classLabel(c, t)}
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
                    {urgencyLabel(u, t)}
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
