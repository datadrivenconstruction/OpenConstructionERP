import { useState, useMemo, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import clsx from 'clsx';
import {
  Wrench,
  ClipboardList,
  FileText,
  Box,
  Plus,
  Search,
  X,
  Loader2,
  Send,
  CheckCircle2,
  DollarSign,
  Trash2,
  ShieldAlert,
  ArrowRight,
  Repeat,
  AlarmClock,
} from 'lucide-react';
import {
  Button,
  Card,
  Badge,
  EmptyState,
  Breadcrumb,
  SkeletonTable,
  WideModal,
  WideModalSection,
  WideModalField,
  ContactSearchInput,
  ConfirmDialog,
} from '@/shared/ui';
import { MoneyDisplay } from '@/shared/ui/MoneyDisplay';
import { DateDisplay } from '@/shared/ui/DateDisplay';
import { useToastStore } from '@/stores/useToastStore';
import { getErrorMessage } from '@/shared/lib/api';
import {
  listContracts,
  listAssets,
  listTickets,
  listWorkOrders,
  createContract,
  createAsset,
  createTicket,
  createWorkOrder,
  deleteContract,
  deleteAsset,
  deleteTicket,
  dispatchTicket,
  resolveTicket,
  closeTicket,
  updateTicket,
  billWorkOrder,
  completeWorkOrder,
  updateWorkOrder,
  type ServiceContract,
  type ServiceAsset,
  type ServiceTicket,
  type WorkOrder,
  type TicketPriority,
  type TicketStatus,
  type ContractStatus,
  type WorkOrderStatus,
} from './api';
import { RecurringSchedulesTab } from './RecurringSchedulesTab';

type Tab = 'tickets' | 'work_orders' | 'contracts' | 'assets' | 'recurring';

const TICKET_STATUS_VARIANT: Record<TicketStatus, 'neutral' | 'blue' | 'success' | 'warning' | 'error'> = {
  new: 'blue',
  assigned: 'warning',
  in_progress: 'warning',
  resolved: 'success',
  closed: 'neutral',
  cancelled: 'neutral',
};

const PRIORITY_VARIANT: Record<TicketPriority, 'neutral' | 'blue' | 'success' | 'warning' | 'error'> = {
  low: 'neutral',
  med: 'blue',
  high: 'warning',
  critical: 'error',
};

const CONTRACT_STATUS_VARIANT: Record<ContractStatus, 'neutral' | 'blue' | 'success' | 'warning' | 'error'> = {
  draft: 'neutral',
  active: 'success',
  expired: 'warning',
  terminated: 'error',
};

const WO_STATUS_VARIANT: Record<WorkOrderStatus, 'neutral' | 'blue' | 'success' | 'warning' | 'error'> = {
  scheduled: 'blue',
  dispatched: 'warning',
  in_progress: 'warning',
  completed: 'success',
  billed: 'success',
  cancelled: 'neutral',
};

const inputCls =
  'h-9 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';

// Note: the legacy `labelCls` style is intentionally no longer used —
// modal forms switched to <WideModalField> which renders the label
// inside the wrapper. Kept as a module-level constant only so that any
// non-modal label callers that still reference it (none today) would
// import the same visual style without redeclaring.
// const labelCls = 'block text-xs font-medium text-content-secondary mb-1';

/* ─── helpers ─── */

/**
 * SLA countdown chip state for a ticket. The dashboard shows:
 *   green  — more than 1h headroom until breach
 *   amber  — under 1h headroom (warning band)
 *   red    — sla_breached_at is set OR sla_due_at is already in the past
 *
 * Returns `null` when no SLA was configured for this ticket (no chip).
 */
type SLAChipState = {
  variant: 'success' | 'warning' | 'error';
  label: string;
  minutes: number;
} | null;

function computeSlaChip(t: ServiceTicket, nowMs: number): SLAChipState {
  if (t.sla_breached_at) {
    return { variant: 'error', label: 'Breached', minutes: 0 };
  }
  if (!t.sla_due_at) return null;
  const dueMs = Date.parse(t.sla_due_at);
  if (Number.isNaN(dueMs)) return null;
  // Tickets in terminal states should not flash as overdue forever.
  if (t.status === 'resolved' || t.status === 'closed' || t.status === 'cancelled') {
    return null;
  }
  const minutes = Math.round((dueMs - nowMs) / 60000);
  if (minutes <= 0) {
    return { variant: 'error', label: `${Math.abs(minutes)}m late`, minutes };
  }
  const variant: 'success' | 'warning' = minutes < 60 ? 'warning' : 'success';
  const label =
    minutes >= 1440
      ? `${Math.round(minutes / 60 / 24)}d`
      : minutes >= 60
        ? `${Math.round(minutes / 60)}h`
        : `${minutes}m`;
  return { variant, label, minutes };
}

function todayIso(offsetDays = 0): string {
  const d = new Date();
  d.setDate(d.getDate() + offsetDays);
  // Use the *local* calendar date — toISOString() would shift to UTC and can
  // land on the wrong day for users far from UTC near midnight.
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${y}-${m}-${day}`;
}

// `<input type="date">` yields a bare `YYYY-MM-DD`, but the backend's
// `scheduled_for` is validated against a full ISO-8601 *datetime* pattern.
// Sending the bare date 422s the request. Normalise a date-only string to a
// UTC midnight datetime so the work-order create / reschedule call validates.
function dateToIsoDatetime(date: string): string | undefined {
  if (!date) return undefined;
  // Already a datetime (defensive — future callers may pass one through).
  if (date.includes('T') || date.includes(' ')) return date;
  return `${date}T00:00:00+00:00`;
}

/* ─── Workflow intro ───────────────────────────────────────────────────
 *
 * Makes the contract → asset → ticket → work order → bill lifecycle
 * explicit so a coordinator knows the order of operations and where the
 * money lands. Links to the modules this depends on: customers come from
 * Contacts, on-site engineers from Subcontractors, and billed work orders
 * roll into Finance. Dismissible per-session.
 */
function WorkflowIntro() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [dismissed, setDismissed] = useState(
    () => sessionStorage.getItem('oe.svc.introDismissed') === '1',
  );
  if (dismissed) return null;
  const dismiss = () => {
    sessionStorage.setItem('oe.svc.introDismissed', '1');
    setDismissed(true);
  };
  return (
    <Card padding="md" className="border-oe-blue/20 bg-oe-blue-subtle/10">
      <div className="flex items-start gap-3">
        <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-oe-blue-subtle text-oe-blue-text">
          <Wrench size={16} />
        </div>
        <div className="min-w-0 flex-1">
          <p className="text-sm font-semibold text-content-primary">
            {t('service.intro_title', {
              defaultValue: 'From customer call to billed visit',
            })}
          </p>
          <p className="mt-1 text-xs leading-relaxed text-content-secondary">
            {t('service.intro_body', {
              defaultValue:
                'Set up a service Contract for a customer, register the Assets it covers, then log a Ticket whenever something needs attention. Dispatching a ticket creates a Work Order that schedules an engineer; once completed with a debrief it can be Billed. Work the tabs left-to-right — each step unlocks the next.',
            })}
          </p>
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <span className="text-2xs font-medium uppercase tracking-wide text-content-tertiary">
              {t('service.intro_connects', { defaultValue: 'Connects to' })}
            </span>
            <button
              type="button"
              onClick={() => navigate('/contacts')}
              className="inline-flex items-center gap-1 rounded-full border border-border-light bg-surface-primary px-2.5 py-1 text-xs font-medium text-content-secondary transition-colors hover:border-oe-blue hover:text-oe-blue"
            >
              {t('service.intro_link_contacts', {
                defaultValue: 'Customers (Contacts)',
              })}
              <ArrowRight size={11} />
            </button>
            <button
              type="button"
              onClick={() => navigate('/subcontractors')}
              className="inline-flex items-center gap-1 rounded-full border border-border-light bg-surface-primary px-2.5 py-1 text-xs font-medium text-content-secondary transition-colors hover:border-oe-blue hover:text-oe-blue"
            >
              {t('service.intro_link_subs', {
                defaultValue: 'Subcontractors',
              })}
              <ArrowRight size={11} />
            </button>
            <button
              type="button"
              onClick={() => navigate('/finance')}
              className="inline-flex items-center gap-1 rounded-full border border-border-light bg-surface-primary px-2.5 py-1 text-xs font-medium text-content-secondary transition-colors hover:border-oe-blue hover:text-oe-blue"
            >
              {t('service.intro_link_finance', { defaultValue: 'Finance' })}
              <ArrowRight size={11} />
            </button>
          </div>
        </div>
        <button
          type="button"
          onClick={dismiss}
          className="shrink-0 rounded-md p-1 text-content-tertiary transition-colors hover:bg-surface-secondary hover:text-content-primary"
          aria-label={t('common.dismiss', { defaultValue: 'Dismiss' })}
        >
          <X size={14} />
        </button>
      </div>
    </Card>
  );
}

/* ─── Page ─── */

export function ServicePage() {
  const { t } = useTranslation();
  const [tab, setTab] = useState<Tab>('tickets');
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState<string>('');
  const [overdueOnly, setOverdueOnly] = useState(false);
  const [selected, setSelected] = useState<{ kind: Tab; id: string } | null>(null);
  const [createOpen, setCreateOpen] = useState(false);

  // The tickets list is needed both on its own tab and as the parent picker
  // when creating a work order — keep it enabled on the WO tab too, otherwise
  // the "New Work Order" modal renders an empty ticket dropdown.
  const ticketsQ = useQuery({
    queryKey: ['service', 'tickets'],
    queryFn: () => listTickets({ limit: 100 }),
    enabled: tab === 'tickets' || tab === 'work_orders',
  });
  const workOrdersQ = useQuery({
    queryKey: ['service', 'workOrders'],
    queryFn: () => listWorkOrders({ limit: 100 }),
    enabled: tab === 'work_orders',
  });
  // Contracts back the picker in the ticket/asset create modals, so they must
  // be loaded on every tab whose "New …" action needs to choose a contract.
  const contractsQ = useQuery({
    queryKey: ['service', 'contracts'],
    queryFn: () => listContracts({ limit: 100 }),
    enabled: true,
  });
  const contracts = contractsQ.data ?? [];
  const [selectedContractId, setSelectedContractId] = useState<string>('');
  const effectiveContractId = selectedContractId || contracts[0]?.id || '';

  const assetsQ = useQuery({
    queryKey: ['service', 'assets', effectiveContractId],
    queryFn: () => listAssets({ contract_id: effectiveContractId, limit: 200 }),
    enabled: tab === 'assets' && !!effectiveContractId,
  });

  const filteredTickets = useMemo(() => {
    const items = ticketsQ.data ?? [];
    const s = search.toLowerCase();
    const nowMs = Date.now();
    return items.filter((it) => {
      if (statusFilter && it.status !== statusFilter) return false;
      if (overdueOnly) {
        // A ticket is "overdue" if it carries the explicit breach stamp OR
        // its sla_due_at has already passed and it's still actionable.
        const isBreached =
          !!it.sla_breached_at ||
          (!!it.sla_due_at &&
            Date.parse(it.sla_due_at) < nowMs &&
            it.status !== 'resolved' &&
            it.status !== 'closed' &&
            it.status !== 'cancelled');
        if (!isBreached) return false;
      }
      if (!s) return true;
      return (
        it.ticket_number.toLowerCase().includes(s) ||
        it.title.toLowerCase().includes(s) ||
        (it.description || '').toLowerCase().includes(s)
      );
    });
  }, [ticketsQ.data, search, statusFilter, overdueOnly]);

  const filteredWOs = useMemo(() => {
    const items = workOrdersQ.data ?? [];
    const s = search.toLowerCase();
    return items.filter((it) => {
      if (statusFilter && it.status !== statusFilter) return false;
      if (!s) return true;
      return (
        it.work_order_number.toLowerCase().includes(s) ||
        (it.debrief_summary || '').toLowerCase().includes(s)
      );
    });
  }, [workOrdersQ.data, search, statusFilter]);

  const filteredContracts = useMemo(() => {
    const s = search.toLowerCase();
    return contracts.filter((it) => {
      if (statusFilter && it.status !== statusFilter) return false;
      if (!s) return true;
      return (
        it.contract_number.toLowerCase().includes(s) ||
        (it.title || '').toLowerCase().includes(s)
      );
    });
  }, [contracts, search, statusFilter]);

  const filteredAssets = useMemo(() => {
    const items = assetsQ.data ?? [];
    const s = search.toLowerCase();
    return items.filter((it) => {
      if (statusFilter && it.status !== statusFilter) return false;
      if (!s) return true;
      return (
        (it.name || '').toLowerCase().includes(s) ||
        (it.asset_tag || '').toLowerCase().includes(s) ||
        it.asset_type.toLowerCase().includes(s)
      );
    });
  }, [assetsQ.data, search, statusFilter]);

  const isLoading =
    (tab === 'tickets' && ticketsQ.isLoading) ||
    (tab === 'work_orders' && workOrdersQ.isLoading) ||
    (tab === 'contracts' && contractsQ.isLoading) ||
    (tab === 'assets' && (contractsQ.isLoading || assetsQ.isLoading));
  // ``recurring`` tab manages its own query — it's not surfaced here.

  // Surface load failures honestly instead of rendering the "no data yet"
  // empty state over a server/network error.
  const activeQuery =
    tab === 'tickets'
      ? ticketsQ
      : tab === 'work_orders'
        ? workOrdersQ
        : tab === 'contracts'
          ? contractsQ
          : tab === 'recurring'
            ? contractsQ  // recurring tab self-loads; this is just a placeholder for the error shell
            : assetsQ.isError || !effectiveContractId
              ? contractsQ
              : assetsQ;
  const isError = !isLoading && activeQuery.isError;

  return (
    <div className="space-y-5">
      <Breadcrumb
        items={[
          { label: t('service.title', { defaultValue: 'Service & Maintenance' }) },
        ]}
      />

      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-2xl font-semibold text-content-primary">
            {t('service.title', { defaultValue: 'Service & Maintenance' })}
          </h1>
          <p className="mt-1 text-sm text-content-secondary">
            {t('service.subtitle', {
              defaultValue: 'Manage service contracts, assets, tickets and work orders.',
            })}
          </p>
        </div>
        {tab !== 'recurring' && (
          <Button
            variant="primary"
            icon={<Plus size={14} />}
            onClick={() => setCreateOpen(true)}
          >
            {tab === 'tickets'
              ? t('service.new_ticket', { defaultValue: 'New Ticket' })
              : tab === 'work_orders'
                ? t('service.new_work_order', { defaultValue: 'New Work Order' })
                : tab === 'contracts'
                  ? t('service.new_contract', { defaultValue: 'New Contract' })
                  : t('service.new_asset', { defaultValue: 'New Asset' })}
          </Button>
        )}
      </div>

      <WorkflowIntro />

      {/* Tabs */}
      <div className="border-b border-border-light">
        <nav className="flex gap-1 -mb-px">
          {(
            [
              { id: 'tickets', label: t('service.tickets', { defaultValue: 'Tickets' }), icon: Wrench },
              { id: 'work_orders', label: t('service.work_orders', { defaultValue: 'Work Orders' }), icon: ClipboardList },
              { id: 'contracts', label: t('service.contracts', { defaultValue: 'Contracts' }), icon: FileText },
              { id: 'assets', label: t('service.assets', { defaultValue: 'Assets' }), icon: Box },
              { id: 'recurring', label: t('service.recurring_tab', { defaultValue: 'Recurring' }), icon: Repeat },
            ] as { id: Tab; label: string; icon: React.ElementType }[]
          ).map((tabItem) => {
            const Icon = tabItem.icon;
            return (
              <button
                key={tabItem.id}
                type="button"
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

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative flex-1 min-w-[200px] max-w-md">
          <Search
            size={14}
            className="absolute left-3 top-1/2 -translate-y-1/2 text-content-tertiary"
          />
          <input
            type="text"
            placeholder={t('common.search', { defaultValue: 'Search…' })}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className={clsx(inputCls, 'pl-8')}
          />
        </div>
        {tab === 'assets' && contracts.length > 0 && (
          <select
            value={effectiveContractId}
            onChange={(e) => setSelectedContractId(e.target.value)}
            className={clsx(inputCls, 'max-w-[260px]')}
          >
            {contracts.map((c) => (
              <option key={c.id} value={c.id}>
                {c.contract_number} — {c.title || 'Untitled'}
              </option>
            ))}
          </select>
        )}
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          className={clsx(inputCls, 'max-w-[180px]')}
        >
          <option value="">{t('common.all_statuses', { defaultValue: 'All statuses' })}</option>
          {tab === 'tickets' && ['new', 'assigned', 'in_progress', 'resolved', 'closed', 'cancelled'].map((s) => (
            <option key={s} value={s}>{s}</option>
          ))}
          {tab === 'work_orders' && ['scheduled', 'dispatched', 'in_progress', 'completed', 'billed', 'cancelled'].map((s) => (
            <option key={s} value={s}>{s}</option>
          ))}
          {tab === 'contracts' && ['draft', 'active', 'expired', 'terminated'].map((s) => (
            <option key={s} value={s}>{s}</option>
          ))}
          {tab === 'assets' && ['active', 'maintenance', 'decommissioned'].map((s) => (
            <option key={s} value={s}>{s}</option>
          ))}
        </select>
        {tab === 'tickets' && (
          <button
            type="button"
            onClick={() => setOverdueOnly((v) => !v)}
            className={clsx(
              'inline-flex items-center gap-1.5 rounded-lg border px-3 h-9 text-sm font-medium transition-colors',
              overdueOnly
                ? 'border-status-error/40 bg-status-error/10 text-status-error'
                : 'border-border bg-surface-primary text-content-secondary hover:text-content-primary',
            )}
            aria-pressed={overdueOnly}
          >
            <AlarmClock size={14} />
            {t('service.overdue_only', { defaultValue: 'Overdue only' })}
          </button>
        )}
      </div>

      {/* Body */}
      {tab === 'recurring' ? (
        <RecurringSchedulesTab contracts={contracts} />
      ) : (
      <Card padding="none">
        {isLoading ? (
          <div className="p-4"><SkeletonTable rows={8} columns={5} /></div>
        ) : isError ? (
          <EmptyState
            icon={<ShieldAlert size={22} />}
            title={t('service.load_error', {
              defaultValue: 'Could not load service data',
            })}
            description={getErrorMessage(activeQuery.error)}
            action={{
              label: t('common.retry', { defaultValue: 'Retry' }),
              onClick: () => {
                void activeQuery.refetch();
              },
            }}
          />
        ) : tab === 'tickets' ? (
          <TicketTable
            rows={filteredTickets}
            onSelect={(id) => setSelected({ kind: 'tickets', id })}
            emptyAction={() => setCreateOpen(true)}
          />
        ) : tab === 'work_orders' ? (
          <WorkOrderTable
            rows={filteredWOs}
            onSelect={(id) => setSelected({ kind: 'work_orders', id })}
            emptyAction={() => setCreateOpen(true)}
          />
        ) : tab === 'contracts' ? (
          <ContractTable
            rows={filteredContracts}
            onSelect={(id) => setSelected({ kind: 'contracts', id })}
            emptyAction={() => setCreateOpen(true)}
          />
        ) : (
          <AssetTable
            rows={filteredAssets}
            onSelect={(id) => setSelected({ kind: 'assets', id })}
            emptyAction={() => setCreateOpen(true)}
            hasContract={!!effectiveContractId}
          />
        )}
      </Card>
      )}

      {/* Detail Drawer */}
      {selected && (
        <DetailDrawer
          kind={selected.kind}
          id={selected.id}
          tickets={ticketsQ.data ?? []}
          workOrders={workOrdersQ.data ?? []}
          contracts={contracts}
          assets={assetsQ.data ?? []}
          onClose={() => setSelected(null)}
        />
      )}

      {/* Create modal — recurring tab has its own scheduling modal */}
      {createOpen && tab !== 'recurring' && (
        <CreateModal
          kind={tab}
          contracts={contracts}
          tickets={ticketsQ.data ?? []}
          defaultContractId={effectiveContractId}
          onClose={() => setCreateOpen(false)}
        />
      )}
    </div>
  );
}

/* ─── tables ─── */

function TicketTable({
  rows,
  onSelect,
  emptyAction,
}: {
  rows: ServiceTicket[];
  onSelect: (id: string) => void;
  emptyAction: () => void;
}) {
  const { t } = useTranslation();
  if (rows.length === 0) {
    return (
      <EmptyState
        icon={<Wrench size={22} />}
        title={t('service.empty_tickets', { defaultValue: 'No tickets yet' })}
        description={t('service.empty_tickets_desc', {
          defaultValue: 'Log a service ticket against a contract to dispatch a technician.',
        })}
        action={{
          label: t('service.new_ticket', { defaultValue: 'New Ticket' }),
          onClick: emptyAction,
        }}
      />
    );
  }
  // Drive the SLA-chip refresh once a minute so a row reading "12m" does not
  // sit there for an hour after navigation. Stored as ms so computeSlaChip
  // sees a stable nowMs across the render's rows.
  const nowMs = useNowMs(60_000);
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead className="bg-surface-secondary text-content-tertiary text-xs uppercase tracking-wide">
          <tr>
            <th className="px-4 py-2.5 text-left">{t('service.ticket', { defaultValue: 'Ticket' })}</th>
            <th className="px-4 py-2.5 text-left">{t('service.title_col', { defaultValue: 'Title' })}</th>
            <th className="px-4 py-2.5 text-left">{t('service.priority', { defaultValue: 'Priority' })}</th>
            <th className="px-4 py-2.5 text-left">{t('service.status', { defaultValue: 'Status' })}</th>
            <th className="px-4 py-2.5 text-left">{t('service.sla_chip', { defaultValue: 'SLA' })}</th>
            <th className="px-4 py-2.5 text-left">{t('service.reported_at', { defaultValue: 'Reported' })}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => {
            const chip = computeSlaChip(r, nowMs);
            return (
            <tr
              key={r.id}
              onClick={() => onSelect(r.id)}
              className="border-t border-border-light hover:bg-surface-secondary cursor-pointer"
            >
              <td className="px-4 py-2 font-mono text-xs text-content-secondary">{r.ticket_number}</td>
              <td className="px-4 py-2 font-medium text-content-primary truncate max-w-[360px]">{r.title}</td>
              <td className="px-4 py-2">
                <Badge variant={PRIORITY_VARIANT[r.priority]}>{r.priority}</Badge>
              </td>
              <td className="px-4 py-2">
                <Badge variant={TICKET_STATUS_VARIANT[r.status]} dot>{r.status}</Badge>
              </td>
              <td className="px-4 py-2">
                {chip ? (
                  <Badge variant={chip.variant} dot>
                    {chip.label}
                  </Badge>
                ) : (
                  <span className="text-content-tertiary text-xs">—</span>
                )}
              </td>
              <td className="px-4 py-2 text-content-secondary text-xs">
                <DateDisplay value={r.reported_at} />
              </td>
            </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

/** Returns Date.now() refreshed on a periodic tick (default 60s). */
function useNowMs(intervalMs = 60_000): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), intervalMs);
    return () => window.clearInterval(id);
  }, [intervalMs]);
  return now;
}

function WorkOrderTable({
  rows,
  onSelect,
  emptyAction,
}: {
  rows: WorkOrder[];
  onSelect: (id: string) => void;
  emptyAction: () => void;
}) {
  const { t } = useTranslation();
  if (rows.length === 0) {
    return (
      <EmptyState
        icon={<ClipboardList size={22} />}
        title={t('service.empty_work_orders', { defaultValue: 'No work orders yet' })}
        description={t('service.empty_work_orders_desc', {
          defaultValue: 'Work orders are created from dispatched tickets to track on-site work.',
        })}
        action={{
          label: t('service.new_work_order', { defaultValue: 'New Work Order' }),
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
            <th className="px-4 py-2.5 text-left">{t('service.wo_number', { defaultValue: 'WO #' })}</th>
            <th className="px-4 py-2.5 text-left">{t('service.scheduled_for', { defaultValue: 'Scheduled' })}</th>
            <th className="px-4 py-2.5 text-left">{t('service.technician', { defaultValue: 'Technician' })}</th>
            <th className="px-4 py-2.5 text-left">{t('service.status', { defaultValue: 'Status' })}</th>
            <th className="px-4 py-2.5 text-right">{t('service.billed', { defaultValue: 'Billed' })}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr
              key={r.id}
              onClick={() => onSelect(r.id)}
              className="border-t border-border-light hover:bg-surface-secondary cursor-pointer"
            >
              <td className="px-4 py-2 font-mono text-xs text-content-secondary">{r.work_order_number}</td>
              <td className="px-4 py-2 text-xs text-content-secondary">
                {r.scheduled_for ? <DateDisplay value={r.scheduled_for} /> : '—'}
              </td>
              <td className="px-4 py-2 text-content-secondary text-xs">{r.technician_id || '—'}</td>
              <td className="px-4 py-2">
                <Badge variant={WO_STATUS_VARIANT[r.status]} dot>{r.status}</Badge>
              </td>
              <td className="px-4 py-2 text-right">
                <MoneyDisplay amount={Number(r.billed_amount) || 0} currency={r.currency || undefined} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ContractTable({
  rows,
  onSelect,
  emptyAction,
}: {
  rows: ServiceContract[];
  onSelect: (id: string) => void;
  emptyAction: () => void;
}) {
  const { t } = useTranslation();
  if (rows.length === 0) {
    return (
      <EmptyState
        icon={<FileText size={22} />}
        title={t('service.empty_contracts', { defaultValue: 'No service contracts yet' })}
        description={t('service.empty_contracts_desc', {
          defaultValue: 'Create a contract to associate assets, SLA tiers and recurring work.',
        })}
        action={{
          label: t('service.new_contract', { defaultValue: 'New Contract' }),
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
            <th className="px-4 py-2.5 text-left">{t('service.contract_number', { defaultValue: 'Contract #' })}</th>
            <th className="px-4 py-2.5 text-left">{t('service.title_col', { defaultValue: 'Title' })}</th>
            <th className="px-4 py-2.5 text-left">{t('service.period', { defaultValue: 'Period' })}</th>
            <th className="px-4 py-2.5 text-left">{t('service.sla_tier', { defaultValue: 'SLA' })}</th>
            <th className="px-4 py-2.5 text-left">{t('service.status', { defaultValue: 'Status' })}</th>
            <th className="px-4 py-2.5 text-right">{t('service.value', { defaultValue: 'Value' })}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr
              key={r.id}
              onClick={() => onSelect(r.id)}
              className="border-t border-border-light hover:bg-surface-secondary cursor-pointer"
            >
              <td className="px-4 py-2 font-mono text-xs text-content-secondary">{r.contract_number}</td>
              <td className="px-4 py-2 font-medium truncate max-w-[280px]">{r.title || '—'}</td>
              <td className="px-4 py-2 text-xs text-content-secondary">
                {r.period_start} → {r.period_end}
              </td>
              <td className="px-4 py-2 text-xs text-content-secondary">{r.sla_tier}</td>
              <td className="px-4 py-2">
                <Badge variant={CONTRACT_STATUS_VARIANT[r.status]} dot>{r.status}</Badge>
              </td>
              <td className="px-4 py-2 text-right">
                <MoneyDisplay amount={Number(r.value) || 0} currency={r.currency || undefined} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function AssetTable({
  rows,
  onSelect,
  emptyAction,
  hasContract,
}: {
  rows: ServiceAsset[];
  onSelect: (id: string) => void;
  emptyAction: () => void;
  hasContract: boolean;
}) {
  const { t } = useTranslation();
  if (!hasContract) {
    return (
      <EmptyState
        icon={<FileText size={22} />}
        title={t('service.no_contract_selected', { defaultValue: 'No contract selected' })}
        description={t('service.no_contract_selected_desc', {
          defaultValue: 'Create a contract first to track its assets.',
        })}
      />
    );
  }
  if (rows.length === 0) {
    return (
      <EmptyState
        icon={<Box size={22} />}
        title={t('service.empty_assets', { defaultValue: 'No assets under this contract' })}
        description={t('service.empty_assets_desc', {
          defaultValue: 'Register the equipment you maintain — HVAC, lifts, generators, etc.',
        })}
        action={{
          label: t('service.new_asset', { defaultValue: 'New Asset' }),
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
            <th className="px-4 py-2.5 text-left">{t('service.asset_tag', { defaultValue: 'Tag' })}</th>
            <th className="px-4 py-2.5 text-left">{t('service.name', { defaultValue: 'Name' })}</th>
            <th className="px-4 py-2.5 text-left">{t('service.asset_type', { defaultValue: 'Type' })}</th>
            <th className="px-4 py-2.5 text-left">{t('service.location', { defaultValue: 'Location' })}</th>
            <th className="px-4 py-2.5 text-left">{t('service.status', { defaultValue: 'Status' })}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr
              key={r.id}
              onClick={() => onSelect(r.id)}
              className="border-t border-border-light hover:bg-surface-secondary cursor-pointer"
            >
              <td className="px-4 py-2 font-mono text-xs text-content-secondary">{r.asset_tag || '—'}</td>
              <td className="px-4 py-2 font-medium">{r.name || '—'}</td>
              <td className="px-4 py-2 text-content-secondary text-xs">{r.asset_type}</td>
              <td className="px-4 py-2 text-content-secondary text-xs">{r.location || '—'}</td>
              <td className="px-4 py-2">
                <Badge variant={r.status === 'active' ? 'success' : r.status === 'maintenance' ? 'warning' : 'neutral'} dot>
                  {r.status}
                </Badge>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/* ─── Detail Drawer ─── */

function DetailDrawer({
  kind,
  id,
  tickets,
  workOrders,
  contracts,
  assets,
  onClose,
}: {
  kind: Tab;
  id: string;
  tickets: ServiceTicket[];
  workOrders: WorkOrder[];
  contracts: ServiceContract[];
  assets: ServiceAsset[];
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);

  const ticket = kind === 'tickets' ? tickets.find((x) => x.id === id) : null;
  const wo = kind === 'work_orders' ? workOrders.find((x) => x.id === id) : null;
  const contract = kind === 'contracts' ? contracts.find((x) => x.id === id) : null;
  const asset = kind === 'assets' ? assets.find((x) => x.id === id) : null;

  const dispatchMut = useMutation({
    mutationFn: (technicianId: string) =>
      dispatchTicket(id, { technician_id: technicianId }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['service', 'tickets'] });
      addToast({ type: 'success', title: t('service.dispatched', { defaultValue: 'Ticket dispatched' }) });
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  const startTicketMut = useMutation({
    mutationFn: () => updateTicket(id, { status: 'in_progress' }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['service', 'tickets'] });
      addToast({
        type: 'success',
        title: t('service.ticket_started', { defaultValue: 'Work started' }),
      });
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  const resolveMut = useMutation({
    mutationFn: () => resolveTicket(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['service', 'tickets'] });
      addToast({ type: 'success', title: t('service.resolved', { defaultValue: 'Ticket resolved' }) });
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  const closeMut = useMutation({
    mutationFn: () => closeTicket(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['service', 'tickets'] });
      addToast({ type: 'success', title: t('service.ticket_closed', { defaultValue: 'Ticket closed' }) });
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  const billMut = useMutation({
    mutationFn: () => billWorkOrder(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['service', 'workOrders'] });
      addToast({ type: 'success', title: t('service.billed_ok', { defaultValue: 'Work order billed' }) });
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  const completeMut = useMutation({
    mutationFn: (debrief: { problem: string; cause: string; solution: string }) =>
      completeWorkOrder(id, debrief),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['service', 'workOrders'] });
      addToast({ type: 'success', title: t('service.completed_ok', { defaultValue: 'Work order completed' }) });
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  const advanceWoMut = useMutation({
    mutationFn: (next: WorkOrderStatus) => updateWorkOrder(id, { status: next }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['service', 'workOrders'] });
      addToast({
        type: 'success',
        title: t('service.wo_advanced', { defaultValue: 'Work order updated' }),
      });
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  const [tech, setTech] = useState('');
  const [debrief, setDebrief] = useState({ problem: '', cause: '', solution: '' });
  // Destructive action gate. WOs intentionally have no delete here — they
  // cascade from a ticket; a stand-alone WO delete would orphan the ticket
  // history. WO cancellation should flow through the ticket's "cancel".
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [deleting, setDeleting] = useState(false);

  // Escape closes the drawer — but not while the delete confirm is open
  // (ConfirmDialog owns Escape then) or a destructive op is in flight.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !deleteOpen && !deleting) {
        onClose();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [deleteOpen, deleting, onClose]);

  // Resolve the human label + delete function for the open entity.
  const deletable =
    kind === 'tickets'
      ? ticket
        ? {
            id: ticket.id,
            label: ticket.ticket_number,
            displayName: ticket.title || ticket.ticket_number,
            fn: deleteTicket,
            queryKey: ['service', 'tickets'] as const,
            kindLabel: t('service.ticket', { defaultValue: 'Ticket' }),
          }
        : null
      : kind === 'contracts'
        ? contract
          ? {
              id: contract.id,
              label: contract.contract_number,
              displayName: contract.title || contract.contract_number,
              fn: deleteContract,
              queryKey: ['service', 'contracts'] as const,
              kindLabel: t('service.contract', { defaultValue: 'Contract' }),
            }
          : null
        : kind === 'assets'
          ? asset
            ? {
                id: asset.id,
                label: asset.asset_tag || asset.name,
                displayName: asset.name || asset.asset_tag || asset.id,
                fn: deleteAsset,
                queryKey: ['service', 'assets'] as const,
                kindLabel: t('service.asset', { defaultValue: 'Asset' }),
              }
            : null
          : null;

  const handleDelete = async () => {
    if (!deletable) return;
    setDeleting(true);
    try {
      await deletable.fn(deletable.id);
      addToast({
        type: 'success',
        title: t('service.deleted', {
          defaultValue: '{{kind}} "{{name}}" deleted',
          kind: deletable.kindLabel,
          name: deletable.displayName,
        }),
      });
      qc.invalidateQueries({ queryKey: deletable.queryKey });
      // Contracts cascade to assets/tickets/work-orders via FK ondelete
      // CASCADE, so we widen the invalidation when a contract goes.
      if (kind === 'contracts') {
        qc.invalidateQueries({ queryKey: ['service'] });
      }
      setDeleteOpen(false);
      onClose();
    } catch (err) {
      addToast({ type: 'error', title: getErrorMessage(err) });
    } finally {
      setDeleting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex justify-end" onClick={onClose}>
      <div className="absolute inset-0 bg-black/30" aria-hidden="true" />
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="service-detail-drawer-title"
        className="relative h-full w-full max-w-lg overflow-y-auto bg-surface-elevated shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="sticky top-0 z-10 flex items-center justify-between border-b border-border-light bg-surface-elevated px-5 py-3 gap-3">
          <h2
            id="service-detail-drawer-title"
            className="text-base font-semibold truncate min-w-0 flex-1"
          >
            {kind === 'tickets' && ticket?.ticket_number}
            {kind === 'work_orders' && wo?.work_order_number}
            {kind === 'contracts' && contract?.contract_number}
            {kind === 'assets' && (asset?.asset_tag || asset?.name)}
          </h2>
          <div className="flex items-center gap-1 shrink-0">
            {deletable && (
              <button
                type="button"
                onClick={() => setDeleteOpen(true)}
                className="inline-flex items-center gap-1.5 rounded-md border border-border-light bg-surface-primary px-2.5 py-1.5 text-xs font-medium text-content-secondary hover:text-rose-600 hover:border-rose-300 hover:bg-rose-50 dark:hover:bg-rose-950/30 transition-colors"
                aria-label={t('common.delete', { defaultValue: 'Delete' })}
              >
                <Trash2 size={12} />
                {t('common.delete', { defaultValue: 'Delete' })}
              </button>
            )}
            <button
              type="button"
              onClick={onClose}
              className="ml-1 rounded p-1 hover:bg-surface-secondary"
              aria-label={t('common.close', { defaultValue: 'Close' })}
            >
              <X size={16} />
            </button>
          </div>
        </div>

        <div className="space-y-4 p-5">
          {ticket && (
            <>
              <div>
                <p className="text-lg font-semibold">{ticket.title}</p>
                <p className="mt-1 text-sm text-content-secondary whitespace-pre-wrap">{ticket.description}</p>
              </div>
              <div className="grid grid-cols-2 gap-3 text-sm">
                <Field label={t('service.priority')} value={<Badge variant={PRIORITY_VARIANT[ticket.priority]}>{ticket.priority}</Badge>} />
                <Field label={t('service.status')} value={<Badge variant={TICKET_STATUS_VARIANT[ticket.status]} dot>{ticket.status}</Badge>} />
                <Field label={t('service.reported_at')} value={<DateDisplay value={ticket.reported_at} />} />
                <Field label={t('service.assigned_to', { defaultValue: 'Assigned to' })} value={ticket.assigned_to || '—'} />
                <Field label={t('service.sla_due', { defaultValue: 'SLA due' })} value={ticket.sla_due_at ? <DateDisplay value={ticket.sla_due_at} /> : '—'} />
                {ticket.resolved_at && <Field label={t('service.resolved_at', { defaultValue: 'Resolved at' })} value={<DateDisplay value={ticket.resolved_at} />} />}
              </div>

              {ticket.status === 'new' && (
                <Card padding="sm">
                  <p className="text-xs font-semibold text-content-secondary uppercase tracking-wide mb-2">
                    {t('service.dispatch_ticket', { defaultValue: 'Dispatch to technician' })}
                  </p>
                  <div className="flex gap-2">
                    <input
                      type="text"
                      value={tech}
                      onChange={(e) => setTech(e.target.value)}
                      placeholder={t('service.technician_id', { defaultValue: 'Technician ID / email' })}
                      className={inputCls}
                    />
                    <Button
                      variant="primary"
                      icon={<Send size={14} />}
                      disabled={!tech || dispatchMut.isPending}
                      onClick={() => dispatchMut.mutate(tech)}
                    >
                      {t('service.dispatch', { defaultValue: 'Dispatch' })}
                    </Button>
                  </div>
                </Card>
              )}

              <div className="flex flex-wrap gap-2 pt-2">
                {ticket.status === 'assigned' && (
                  <Button
                    variant="secondary"
                    icon={<Wrench size={14} />}
                    onClick={() => startTicketMut.mutate()}
                    loading={startTicketMut.isPending}
                  >
                    {t('service.start_ticket', { defaultValue: 'Start Work' })}
                  </Button>
                )}
                {ticket.status === 'in_progress' && (
                  <Button
                    variant="secondary"
                    icon={<CheckCircle2 size={14} />}
                    onClick={() => resolveMut.mutate()}
                    loading={resolveMut.isPending}
                  >
                    {t('service.mark_resolved', { defaultValue: 'Mark Resolved' })}
                  </Button>
                )}
                {ticket.status === 'resolved' && (
                  <Button
                    variant="secondary"
                    onClick={() => closeMut.mutate()}
                    loading={closeMut.isPending}
                  >
                    {t('service.close_ticket', { defaultValue: 'Close Ticket' })}
                  </Button>
                )}
              </div>
            </>
          )}

          {wo && (
            <>
              <div className="grid grid-cols-2 gap-3 text-sm">
                <Field label={t('service.status')} value={<Badge variant={WO_STATUS_VARIANT[wo.status]} dot>{wo.status}</Badge>} />
                <Field label={t('service.scheduled_for')} value={wo.scheduled_for ? <DateDisplay value={wo.scheduled_for} /> : '—'} />
                <Field label={t('service.technician')} value={wo.technician_id || '—'} />
                <Field label={t('service.billed')} value={<MoneyDisplay amount={Number(wo.billed_amount) || 0} currency={wo.currency || undefined} />} />
              </div>
              {wo.debrief_summary && (
                <Card padding="sm">
                  <p className="text-xs font-semibold uppercase tracking-wide text-content-secondary mb-1">
                    {t('service.debrief', { defaultValue: 'Debrief' })}
                  </p>
                  <p className="text-sm whitespace-pre-wrap">{wo.debrief_summary}</p>
                </Card>
              )}

              {wo.status === 'scheduled' && (
                <Button
                  variant="secondary"
                  icon={<Send size={14} />}
                  onClick={() => advanceWoMut.mutate('dispatched')}
                  loading={advanceWoMut.isPending}
                >
                  {t('service.dispatch_wo', { defaultValue: 'Dispatch Work Order' })}
                </Button>
              )}

              {wo.status === 'dispatched' && (
                <Button
                  variant="secondary"
                  icon={<CheckCircle2 size={14} />}
                  onClick={() => advanceWoMut.mutate('in_progress')}
                  loading={advanceWoMut.isPending}
                >
                  {t('service.start_wo', { defaultValue: 'Start Work' })}
                </Button>
              )}

              {wo.status === 'in_progress' && (
                <Card padding="sm">
                  <p className="text-xs font-semibold uppercase tracking-wide text-content-secondary mb-2">
                    {t('service.complete_wo', { defaultValue: 'Complete with debrief' })}
                  </p>
                  <div className="space-y-2">
                    <textarea
                      value={debrief.problem}
                      onChange={(e) => setDebrief((s) => ({ ...s, problem: e.target.value }))}
                      placeholder={t('service.problem', { defaultValue: 'Problem' })}
                      rows={2}
                      className={clsx(inputCls, 'h-auto py-2')}
                    />
                    <textarea
                      value={debrief.cause}
                      onChange={(e) => setDebrief((s) => ({ ...s, cause: e.target.value }))}
                      placeholder={t('service.cause', { defaultValue: 'Cause' })}
                      rows={2}
                      className={clsx(inputCls, 'h-auto py-2')}
                    />
                    <textarea
                      value={debrief.solution}
                      onChange={(e) => setDebrief((s) => ({ ...s, solution: e.target.value }))}
                      placeholder={t('service.solution', { defaultValue: 'Solution' })}
                      rows={2}
                      className={clsx(inputCls, 'h-auto py-2')}
                    />
                    <Button
                      variant="primary"
                      icon={<CheckCircle2 size={14} />}
                      onClick={() => completeMut.mutate(debrief)}
                      loading={completeMut.isPending}
                      disabled={!debrief.solution.trim()}
                    >
                      {t('service.complete', { defaultValue: 'Complete' })}
                    </Button>
                  </div>
                </Card>
              )}

              {wo.status === 'completed' && (
                <Button
                  variant="primary"
                  icon={<DollarSign size={14} />}
                  onClick={() => billMut.mutate()}
                  loading={billMut.isPending}
                >
                  {t('service.bill_wo', { defaultValue: 'Bill Work Order' })}
                </Button>
              )}
            </>
          )}

          {contract && (
            <div className="grid grid-cols-2 gap-3 text-sm">
              <Field label={t('service.title_col')} value={contract.title || '—'} />
              <Field label={t('service.status')} value={<Badge variant={CONTRACT_STATUS_VARIANT[contract.status]} dot>{contract.status}</Badge>} />
              <Field label={t('service.period_start', { defaultValue: 'Start' })} value={contract.period_start} />
              <Field label={t('service.period_end', { defaultValue: 'End' })} value={contract.period_end} />
              <Field label={t('service.sla_tier')} value={contract.sla_tier} />
              <Field label={t('service.value')} value={<MoneyDisplay amount={Number(contract.value) || 0} currency={contract.currency || undefined} />} />
              <Field label={t('service.auto_renew', { defaultValue: 'Auto renew' })} value={contract.auto_renew ? '✓' : '—'} />
            </div>
          )}

          {asset && (
            <div className="grid grid-cols-2 gap-3 text-sm">
              <Field label={t('service.name')} value={asset.name || '—'} />
              <Field label={t('service.asset_type')} value={asset.asset_type} />
              <Field label={t('service.manufacturer', { defaultValue: 'Manufacturer' })} value={asset.manufacturer || '—'} />
              <Field label={t('service.model', { defaultValue: 'Model' })} value={asset.model || '—'} />
              <Field label={t('service.serial', { defaultValue: 'Serial' })} value={asset.serial || '—'} />
              <Field label={t('service.location')} value={asset.location || '—'} />
              <Field label={t('service.install_date', { defaultValue: 'Installed' })} value={asset.install_date || '—'} />
              <Field label={t('service.warranty_until', { defaultValue: 'Warranty until' })} value={asset.warranty_until || '—'} />
              <Field label={t('service.status')} value={<Badge variant={asset.status === 'active' ? 'success' : 'warning'} dot>{asset.status}</Badge>} />
            </div>
          )}

          {!ticket && !wo && !contract && !asset && (
            <EmptyState
              icon={<ShieldAlert size={20} />}
              title={t('service.detail_not_found', {
                defaultValue: 'This record is no longer available',
              })}
              description={t('service.detail_not_found_desc', {
                defaultValue:
                  'It may have been deleted, or it is outside the current filter or page. Close this panel and refresh the list.',
              })}
              action={{
                label: t('common.close', { defaultValue: 'Close' }),
                onClick: onClose,
              }}
            />
          )}
        </div>
      </div>

      {/* Destructive delete — second click required. ConfirmDialog already
          handles focus trapping + Escape. */}
      <ConfirmDialog
        open={deleteOpen}
        title={
          deletable
            ? t('service.delete_title', {
                defaultValue: 'Delete {{kind}}?',
                kind: deletable.kindLabel.toLowerCase(),
              })
            : ''
        }
        message={
          deletable
            ? kind === 'contracts'
              ? t('service.delete_contract_message', {
                  defaultValue:
                    'Delete contract "{{name}}"? This also removes every linked asset, ticket, and work order. This action cannot be undone.',
                  name: deletable.displayName,
                })
              : t('service.delete_message', {
                  defaultValue:
                    'Delete {{kind}} "{{name}}"? This action cannot be undone.',
                  kind: deletable.kindLabel.toLowerCase(),
                  name: deletable.displayName,
                })
            : ''
        }
        confirmLabel={t('common.delete', { defaultValue: 'Delete' })}
        cancelLabel={t('common.cancel', { defaultValue: 'Cancel' })}
        variant="danger"
        onConfirm={handleDelete}
        onCancel={() => setDeleteOpen(false)}
        loading={deleting}
      />
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

/* ─── Create modal ─── */

function CreateModal({
  kind,
  contracts,
  tickets,
  defaultContractId,
  onClose,
}: {
  kind: Tab;
  contracts: ServiceContract[];
  tickets: ServiceTicket[];
  defaultContractId: string;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [busy, setBusy] = useState(false);

  // Ticket
  const [ticketForm, setTicketForm] = useState({
    contract_id: defaultContractId,
    title: '',
    description: '',
    priority: 'med' as TicketPriority,
  });

  // Work order
  const [woForm, setWoForm] = useState({
    ticket_id: tickets[0]?.id || '',
    scheduled_for: todayIso(),
    technician_id: '',
  });

  // Contract
  const [contractForm, setContractForm] = useState({
    customer_id: '',
    title: '',
    description: '',
    period_start: todayIso(),
    period_end: todayIso(365),
    sla_tier: 'standard',
    value: '0',
    // Data-driven, never hardcoded to EUR — the backend default is "" and the
    // tenant/contract supplies the currency. Placeholder is a hint only.
    currency: '',
  });

  // Asset
  const [assetForm, setAssetForm] = useState({
    contract_id: defaultContractId,
    asset_type: 'hvac',
    name: '',
    location: '',
  });

  const validate = (): string | null => {
    if (kind === 'tickets') {
      if (!ticketForm.contract_id) {
        return t('service.validation_contract_required', {
          defaultValue: 'Select a contract for this ticket.',
        });
      }
      if (!ticketForm.title.trim()) {
        return t('service.validation_title_required', {
          defaultValue: 'Enter a short title for this ticket.',
        });
      }
    } else if (kind === 'work_orders') {
      if (!woForm.ticket_id) {
        return t('service.validation_ticket_required', {
          defaultValue: 'Select the ticket this work order delivers on.',
        });
      }
    } else if (kind === 'contracts') {
      if (!contractForm.customer_id) {
        return t('service.validation_customer_required', {
          defaultValue: 'Pick the customer this contract is for.',
        });
      }
      if (contractForm.period_end < contractForm.period_start) {
        return t('service.validation_period_order', {
          defaultValue: 'The contract end date must be on or after the start date.',
        });
      }
    } else if (kind === 'assets') {
      if (!assetForm.contract_id) {
        return t('service.validation_contract_required_asset', {
          defaultValue: 'Select the contract this asset belongs to.',
        });
      }
    }
    return null;
  };

  const submit = async () => {
    const validationError = validate();
    if (validationError) {
      addToast({ type: 'error', title: validationError });
      return;
    }
    setBusy(true);
    try {
      if (kind === 'tickets') {
        await createTicket(ticketForm);
        addToast({ type: 'success', title: t('service.ticket_created', { defaultValue: 'Ticket created' }) });
        qc.invalidateQueries({ queryKey: ['service', 'tickets'] });
      } else if (kind === 'work_orders') {
        await createWorkOrder({
          ticket_id: woForm.ticket_id,
          scheduled_for: dateToIsoDatetime(woForm.scheduled_for),
          // Don't send an empty technician_id — the backend caps it at 36
          // chars but an empty string is meaningless and muddies audit.
          technician_id: woForm.technician_id.trim() || undefined,
        });
        addToast({ type: 'success', title: t('service.wo_created', { defaultValue: 'Work order created' }) });
        qc.invalidateQueries({ queryKey: ['service', 'workOrders'] });
      } else if (kind === 'contracts') {
        await createContract({
          ...contractForm,
          value: Number(contractForm.value) || 0,
        });
        addToast({ type: 'success', title: t('service.contract_created', { defaultValue: 'Contract created' }) });
        qc.invalidateQueries({ queryKey: ['service', 'contracts'] });
      } else if (kind === 'assets') {
        await createAsset(assetForm);
        addToast({ type: 'success', title: t('service.asset_created', { defaultValue: 'Asset created' }) });
        qc.invalidateQueries({ queryKey: ['service', 'assets'] });
      }
      onClose();
    } catch (err) {
      addToast({ type: 'error', title: getErrorMessage(err) });
    } finally {
      setBusy(false);
    }
  };

  // Asset type options — these come from the backend `service.asset_type`
  // canonical set. The old form had a free-text input ("hvac / lift /
  // generator / …") which let users persist typos that no analytics
  // query could group on. A dropdown locks down the canonical vocabulary
  // while still letting installers add custom types via the catalogue.
  const ASSET_TYPE_OPTIONS: Array<{ value: string; label: string }> = [
    { value: 'hvac', label: t('service.asset_type_hvac', { defaultValue: 'HVAC' }) },
    { value: 'lift', label: t('service.asset_type_lift', { defaultValue: 'Lift / elevator' }) },
    { value: 'generator', label: t('service.asset_type_generator', { defaultValue: 'Generator' }) },
    { value: 'fire_protection', label: t('service.asset_type_fire', { defaultValue: 'Fire protection' }) },
    { value: 'plumbing', label: t('service.asset_type_plumbing', { defaultValue: 'Plumbing' }) },
    { value: 'electrical', label: t('service.asset_type_electrical', { defaultValue: 'Electrical' }) },
    { value: 'cctv', label: t('service.asset_type_cctv', { defaultValue: 'CCTV / surveillance' }) },
    { value: 'access_control', label: t('service.asset_type_access', { defaultValue: 'Access control' }) },
    { value: 'bms', label: t('service.asset_type_bms', { defaultValue: 'BMS / automation' }) },
    { value: 'other', label: t('service.asset_type_other', { defaultValue: 'Other' }) },
  ];

  const modalSize = kind === 'contracts' ? 'xl' : 'lg';
  // ``recurring`` is unreachable here — the page-level guard short-circuits
  // before this modal ever mounts on the recurring tab — but TypeScript
  // needs the key present in the Record<Tab,…> so we add a placeholder.
  const titleByKind: Record<Tab, string> = {
    tickets: t('service.new_ticket', { defaultValue: 'New service ticket' }),
    work_orders: t('service.new_work_order', { defaultValue: 'New work order' }),
    contracts: t('service.new_contract', { defaultValue: 'New service contract' }),
    assets: t('service.new_asset', { defaultValue: 'New serviced asset' }),
    recurring: '',
  };
  const subtitleByKind: Record<Tab, string> = {
    tickets: t('service.new_ticket_subtitle', {
      defaultValue: 'Log a customer request under one of the active service contracts.',
    }),
    work_orders: t('service.new_work_order_subtitle', {
      defaultValue: 'Schedule a technician visit to deliver on a logged ticket.',
    }),
    contracts: t('service.new_contract_subtitle', {
      defaultValue:
        'A service contract groups recurring work for one customer. Pick the customer from the contacts list — no more pasting UUIDs.',
    }),
    assets: t('service.new_asset_subtitle', {
      defaultValue: 'Register a piece of equipment that this contract covers.',
    }),
    recurring: '',
  };

  return (
    <WideModal
      open
      onClose={onClose}
      title={titleByKind[kind]}
      subtitle={subtitleByKind[kind]}
      size={modalSize}
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
            icon={busy ? <Loader2 size={14} /> : <Plus size={14} />}
          >
            {t('common.create', { defaultValue: 'Create' })}
          </Button>
        </>
      }
    >
      {kind === 'tickets' && (
        <WideModalSection columns={2}>
          <WideModalField
            label={t('service.contract', { defaultValue: 'Contract' })}
            required
            hint={t('service.contract_hint', {
              defaultValue: 'The service agreement this ticket bills under.',
            })}
            span={2}
          >
            <select
              value={ticketForm.contract_id}
              onChange={(e) => setTicketForm({ ...ticketForm, contract_id: e.target.value })}
              className={inputCls}
            >
              <option value="">— {t('common.select', { defaultValue: 'Select' })} —</option>
              {contracts.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.contract_number} — {c.title || ''}
                </option>
              ))}
            </select>
          </WideModalField>
          <WideModalField
            label={t('service.title_col', { defaultValue: 'Title' })}
            required
            span={2}
          >
            <input
              value={ticketForm.title}
              onChange={(e) => setTicketForm({ ...ticketForm, title: e.target.value })}
              className={inputCls}
              placeholder={t('service.title_placeholder', {
                defaultValue: 'AC unit not cooling — Floor 3',
              })}
            />
          </WideModalField>
          <WideModalField
            label={t('service.description', { defaultValue: 'Description' })}
            hint={t('service.description_hint', {
              defaultValue: 'Anything the technician needs to know before arriving.',
            })}
            span={2}
          >
            <textarea
              value={ticketForm.description}
              onChange={(e) => setTicketForm({ ...ticketForm, description: e.target.value })}
              rows={4}
              className={clsx(inputCls, 'h-auto py-2 resize-y')}
            />
          </WideModalField>
          <WideModalField
            label={t('service.priority', { defaultValue: 'Priority' })}
          >
            <select
              value={ticketForm.priority}
              onChange={(e) => setTicketForm({ ...ticketForm, priority: e.target.value as TicketPriority })}
              className={inputCls}
            >
              <option value="low">{t('service.priority_low', { defaultValue: 'Low' })}</option>
              <option value="med">{t('service.priority_med', { defaultValue: 'Medium' })}</option>
              <option value="high">{t('service.priority_high', { defaultValue: 'High' })}</option>
              <option value="critical">{t('service.priority_critical', { defaultValue: 'Critical' })}</option>
            </select>
          </WideModalField>
        </WideModalSection>
      )}

      {kind === 'work_orders' && (
        <WideModalSection columns={2}>
          <WideModalField
            label={t('service.ticket', { defaultValue: 'Ticket' })}
            required
            span={2}
          >
            <select
              value={woForm.ticket_id}
              onChange={(e) => setWoForm({ ...woForm, ticket_id: e.target.value })}
              className={inputCls}
            >
              <option value="">— {t('common.select', { defaultValue: 'Select' })} —</option>
              {tickets.map((tk) => (
                <option key={tk.id} value={tk.id}>
                  {tk.ticket_number} — {tk.title}
                </option>
              ))}
            </select>
          </WideModalField>
          <WideModalField
            label={t('service.scheduled_for', { defaultValue: 'Scheduled for' })}
          >
            <input
              type="date"
              value={woForm.scheduled_for}
              onChange={(e) => setWoForm({ ...woForm, scheduled_for: e.target.value })}
              className={inputCls}
            />
          </WideModalField>
          <WideModalField
            label={t('service.technician', { defaultValue: 'Technician' })}
            hint={t('service.technician_hint', {
              defaultValue: 'Optional — assign on-site engineer.',
            })}
          >
            <input
              value={woForm.technician_id}
              onChange={(e) => setWoForm({ ...woForm, technician_id: e.target.value })}
              className={inputCls}
              placeholder={t('service.technician_placeholder', {
                defaultValue: 'John Doe',
              })}
            />
          </WideModalField>
        </WideModalSection>
      )}

      {kind === 'contracts' && (
        <>
          <WideModalSection
            title={t('service.contract_customer_section', {
              defaultValue: 'Customer & scope',
            })}
            columns={2}
          >
            <WideModalField
              label={t('service.customer', { defaultValue: 'Customer' })}
              required
              hint={t('service.customer_hint', {
                defaultValue:
                  'Pick from your contacts — searches as you type. Need to add a new one? Open Contacts in a new tab.',
              })}
              span={2}
            >
              <ContactSearchInput
                value={contractForm.customer_id}
                onChange={(id) =>
                  setContractForm({ ...contractForm, customer_id: id })
                }
                placeholder={t('service.customer_search_placeholder', {
                  defaultValue: 'Search company or contact name...',
                })}
                showBrowse
                browseContactTypes={["customer", "client", "company"]}
              />
            </WideModalField>
            <WideModalField
              label={t('service.title_col', { defaultValue: 'Title' })}
              hint={t('service.contract_title_hint', {
                defaultValue: 'Short label shown in lists, e.g. "HVAC maintenance — HQ 2026".',
              })}
              span={2}
            >
              <input
                value={contractForm.title}
                onChange={(e) => setContractForm({ ...contractForm, title: e.target.value })}
                className={inputCls}
                placeholder={t('service.contract_title_placeholder', {
                  defaultValue: 'HVAC maintenance — HQ 2026',
                })}
              />
            </WideModalField>
          </WideModalSection>

          <WideModalSection
            title={t('service.contract_period_section', {
              defaultValue: 'Period & SLA',
            })}
            columns={3}
          >
            <WideModalField label={t('service.period_start', { defaultValue: 'Period start' })}>
              <input
                type="date"
                value={contractForm.period_start}
                onChange={(e) => setContractForm({ ...contractForm, period_start: e.target.value })}
                className={inputCls}
              />
            </WideModalField>
            <WideModalField label={t('service.period_end', { defaultValue: 'Period end' })}>
              <input
                type="date"
                value={contractForm.period_end}
                onChange={(e) => setContractForm({ ...contractForm, period_end: e.target.value })}
                className={inputCls}
              />
            </WideModalField>
            <WideModalField
              label={t('service.sla_tier', { defaultValue: 'SLA tier' })}
              hint={t('service.sla_hint', {
                defaultValue: 'Response time commitment.',
              })}
            >
              <select
                value={contractForm.sla_tier}
                onChange={(e) => setContractForm({ ...contractForm, sla_tier: e.target.value })}
                className={inputCls}
              >
                <option value="standard">{t('service.sla_standard', { defaultValue: 'Standard (next business day)' })}</option>
                <option value="priority">{t('service.sla_priority', { defaultValue: 'Priority (same business day)' })}</option>
                <option value="critical">{t('service.sla_critical', { defaultValue: 'Critical (4 hours)' })}</option>
                <option value="24x7">{t('service.sla_24x7', { defaultValue: '24×7 emergency' })}</option>
              </select>
            </WideModalField>
          </WideModalSection>

          <WideModalSection
            title={t('service.contract_value_section', {
              defaultValue: 'Contract value',
            })}
            columns={2}
          >
            <WideModalField
              label={t('service.value', { defaultValue: 'Annual value' })}
              hint={t('service.value_hint', {
                defaultValue: 'Used for billing & revenue forecasting.',
              })}
            >
              <input
                type="number"
                min="0"
                step="0.01"
                value={contractForm.value}
                onChange={(e) => setContractForm({ ...contractForm, value: e.target.value })}
                className={inputCls}
              />
            </WideModalField>
            <WideModalField
              label={t('common.currency', { defaultValue: 'Currency' })}
              hint={t('service.currency_hint', { defaultValue: 'ISO-4217 3-letter code.' })}
            >
              <input
                value={contractForm.currency}
                onChange={(e) =>
                  setContractForm({ ...contractForm, currency: e.target.value.toUpperCase() })
                }
                className={inputCls}
                maxLength={3}
                placeholder="EUR"
              />
            </WideModalField>
          </WideModalSection>
        </>
      )}

      {kind === 'assets' && (
        <WideModalSection columns={2}>
          <WideModalField
            label={t('service.contract', { defaultValue: 'Contract' })}
            required
            span={2}
          >
            <select
              value={assetForm.contract_id}
              onChange={(e) => setAssetForm({ ...assetForm, contract_id: e.target.value })}
              className={inputCls}
            >
              <option value="">— {t('common.select', { defaultValue: 'Select' })} —</option>
              {contracts.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.contract_number}
                  {c.title ? ` — ${c.title}` : ''}
                </option>
              ))}
            </select>
          </WideModalField>
          <WideModalField
            label={t('service.asset_type', { defaultValue: 'Asset type' })}
            required
            hint={t('service.asset_type_hint', {
              defaultValue: 'Drives KPI grouping & spare-parts catalogue.',
            })}
          >
            <select
              value={assetForm.asset_type}
              onChange={(e) => setAssetForm({ ...assetForm, asset_type: e.target.value })}
              className={inputCls}
            >
              {ASSET_TYPE_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>{opt.label}</option>
              ))}
            </select>
          </WideModalField>
          <WideModalField
            label={t('service.name', { defaultValue: 'Name' })}
            hint={t('service.asset_name_hint', {
              defaultValue: 'How site staff recognise this unit.',
            })}
          >
            <input
              value={assetForm.name}
              onChange={(e) => setAssetForm({ ...assetForm, name: e.target.value })}
              className={inputCls}
              placeholder={t('service.asset_name_placeholder', {
                defaultValue: 'RTU-1, Boiler #2, …',
              })}
            />
          </WideModalField>
          <WideModalField
            label={t('service.location', { defaultValue: 'Location' })}
            span={2}
          >
            <input
              value={assetForm.location}
              onChange={(e) => setAssetForm({ ...assetForm, location: e.target.value })}
              className={inputCls}
              placeholder={t('service.location_placeholder', {
                defaultValue: 'Roof, Floor 3 — North wing, …',
              })}
            />
          </WideModalField>
        </WideModalSection>
      )}
    </WideModal>
  );
}
