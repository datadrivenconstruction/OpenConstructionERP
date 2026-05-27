import { useState, useMemo, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { normalizeListResponse } from '@/shared/lib/apiHelpers';
import {
  FileEdit,
  Plus,
  Send,
  CheckCircle2,
  XCircle,
  ChevronRight,
  ArrowLeft,
  DollarSign,
  Clock,
  AlertTriangle,
  Trash2,
  Download,
} from 'lucide-react';
import { Button, Card, Badge, EmptyState, Breadcrumb, InfoHint, ConfirmDialog, RecoveryCard, SkeletonTable, SkeletonCard } from '@/shared/ui';
import { RequiresProject } from '@/shared/auth/RequiresProject';
import {
  WideModal,
  WideModalSection,
  WideModalField,
} from '@/shared/ui/WideModal';
import { useConfirm } from '@/shared/hooks/useConfirm';
import { apiGet, apiPost, apiDelete } from '@/shared/lib/api';
import { getIntlLocale } from '@/shared/lib/formatters';
import { useToastStore } from '@/stores/useToastStore';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { useAuthStore } from '@/stores/useAuthStore';
import { ApprovalTimeline } from './ApprovalTimeline';
import {
  advanceApproval,
  getApprovals,
  startApprovalChain,
  type ApprovalRow,
} from './api';

/* ── Types ─────────────────────────────────────────────────────────────── */

interface Project {
  id: string;
  name: string;
  currency: string;
}

interface ChangeOrderItem {
  id: string;
  change_order_id: string;
  description: string;
  change_type: string;
  original_quantity: number;
  new_quantity: number;
  original_rate: number;
  new_rate: number;
  cost_delta: number;
  unit: string;
  sort_order: number;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

interface ChangeOrder {
  id: string;
  project_id: string;
  code: string;
  title: string;
  description: string;
  reason_category: string;
  status: string;
  submitted_by: string | null;
  approved_by: string | null;
  submitted_at: string | null;
  approved_at: string | null;
  cost_impact: number;
  schedule_impact_days: number;
  currency: string;
  metadata: Record<string, unknown>;
  item_count: number;
  created_at: string;
  updated_at: string;
  // T3: Procore-style approval chain + commitment / RFI links.
  linked_po_ids?: string[];
  linked_rfi_ids?: string[];
  current_approval_step?: number | null;
}

/**
 * Decode the ``sub`` (subject / user id) claim from a JWT access token.
 *
 * Backend ``CurrentUserId`` reads the same claim, so matching against it
 * client-side is the cleanest way to tell whether the logged-in user is
 * the active approver. Returns ``null`` on any decoding error.
 */
function decodeUserIdFromToken(token: string | null): string | null {
  if (!token) return null;
  try {
    const parts = token.split('.');
    if (parts.length !== 3) return null;
    const payload = parts[1]!.replace(/-/g, '+').replace(/_/g, '/');
    const padded = payload + '='.repeat((4 - (payload.length % 4)) % 4);
    const json = JSON.parse(atob(padded)) as { sub?: string };
    return typeof json.sub === 'string' ? json.sub : null;
  } catch {
    return null;
  }
}

interface ChangeOrderWithItems extends ChangeOrder {
  items: ChangeOrderItem[];
}

interface Summary {
  total_orders: number;
  draft_count: number;
  submitted_count: number;
  approved_count: number;
  rejected_count: number;
  total_cost_impact: number;
  total_schedule_impact_days: number;
  currency: string;
}

/* ── Helpers ───────────────────────────────────────────────────────────── */

const STATUS_COLORS: Record<string, 'neutral' | 'blue' | 'success' | 'warning' | 'error'> = {
  draft: 'neutral',
  submitted: 'blue',
  under_review: 'warning',
  approved: 'success',
  rejected: 'error',
};

function getReasonLabels(t: (key: string, opts?: Record<string, unknown>) => string): Record<string, string> {
  return {
    client_request: t('changeorders.reason_client_request', { defaultValue: 'Client Request' }),
    design_change: t('changeorders.reason_design_change', { defaultValue: 'Design Change' }),
    unforeseen: t('changeorders.reason_unforeseen', { defaultValue: 'Unforeseen Conditions' }),
    regulatory: t('changeorders.reason_regulatory', { defaultValue: 'Regulatory' }),
    error: t('changeorders.reason_error', { defaultValue: 'Error/Omission' }),
  };
}

function translateStatus(status: string, t: (key: string, opts?: Record<string, unknown>) => string): string {
  const map: Record<string, string> = {
    draft: t('changeorders.status_draft', { defaultValue: 'Draft' }),
    submitted: t('changeorders.status_submitted', { defaultValue: 'Submitted' }),
    under_review: t('changeorders.status_under_review', { defaultValue: 'Under Review' }),
    approved: t('changeorders.status_approved', { defaultValue: 'Approved' }),
    rejected: t('changeorders.status_rejected', { defaultValue: 'Rejected' }),
  };
  return map[status] || status;
}

function formatCurrency(amount: number, currency?: string): string {
  // NEVER hard-fallback to 'EUR' (task #217): a project priced in BRL/USD
  // must not render its change-order amounts with a Euro sign. When the
  // currency is unknown, show a plain decimal number with no symbol.
  const code = (currency || '').trim().toUpperCase();
  if (!/^[A-Z]{3}$/.test(code)) {
    return new Intl.NumberFormat(getIntlLocale(), {
      minimumFractionDigits: 0,
      maximumFractionDigits: 0,
    }).format(amount);
  }
  try {
    return new Intl.NumberFormat(getIntlLocale(), {
      style: 'currency',
      currency: code,
      minimumFractionDigits: 0,
      maximumFractionDigits: 0,
    }).format(amount);
  } catch {
    return `${amount.toFixed(0)} ${code}`;
  }
}

function formatDate(iso: string | null): string {
  if (!iso) return '-';
  try {
    return new Date(iso).toLocaleDateString(getIntlLocale(), {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
    });
  } catch {
    return iso;
  }
}

/* ── Create Dialog ─────────────────────────────────────────────────────── */

function CreateDialog({
  projectId,
  currency,
  onClose,
  onCreated,
}: {
  projectId: string;
  currency: string;
  onClose: () => void;
  onCreated: () => void;
}) {
  const { t } = useTranslation();
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [reason, setReason] = useState('client_request');
  const [scheduleDays, setScheduleDays] = useState(0);
  const addToast = useToastStore((s) => s.addToast);

  const mutation = useMutation({
    mutationFn: () =>
      apiPost<ChangeOrder>('/v1/changeorders/', {
        project_id: projectId,
        title,
        description,
        reason_category: reason,
        schedule_impact_days: scheduleDays,
        currency,
      }),
    onSuccess: () => {
      onCreated();
      onClose();
      addToast({
        type: 'success',
        title: t('changeorders.created', { defaultValue: 'Change order created' }),
      });
    },
    onError: (err: Error) => {
      addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: err.message });
    },
  });

  const fieldCls =
    'h-10 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';

  return (
    <WideModal
      open
      onClose={onClose}
      title={t('changeorders.new', { defaultValue: 'New Change Order' })}
      size="lg"
      busy={mutation.isPending}
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={mutation.isPending}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button
            variant="primary"
            disabled={!title.trim() || mutation.isPending}
            onClick={() => mutation.mutate()}
          >
            {mutation.isPending
              ? t('common.creating', { defaultValue: 'Creating...' })
              : t('common.create', { defaultValue: 'Create' })}
          </Button>
        </>
      }
    >
      <WideModalSection columns={2}>
        <WideModalField
          label={t('common.title')}
          required
          span={2}
          htmlFor="co-title"
        >
          <input
            id="co-title"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder={t('changeorders.title_placeholder', { defaultValue: 'e.g. Additional foundation work' })}
            className={fieldCls}
          />
        </WideModalField>
        <WideModalField
          label={t('common.description')}
          span={2}
          htmlFor="co-description"
        >
          <textarea
            id="co-description"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            rows={3}
            className="w-full rounded-lg border border-border bg-surface-primary px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue resize-none"
          />
        </WideModalField>
        <WideModalField
          label={t('changeorders.reason', { defaultValue: 'Reason' })}
          htmlFor="co-reason"
        >
          <select
            id="co-reason"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            className={fieldCls}
          >
            {Object.entries(getReasonLabels(t)).map(([k, v]) => (
              <option key={k} value={k}>
                {v}
              </option>
            ))}
          </select>
        </WideModalField>
        <WideModalField
          label={t('changeorders.schedule_days', { defaultValue: 'Schedule Impact (days)' })}
          htmlFor="co-schedule-days"
        >
          <input
            id="co-schedule-days"
            type="number"
            min={0}
            value={scheduleDays}
            onChange={(e) => setScheduleDays(parseInt(e.target.value) || 0)}
            className={fieldCls}
          />
        </WideModalField>
      </WideModalSection>
    </WideModal>
  );
}

/* ── Add Item Dialog ───────────────────────────────────────────────────── */

function AddItemDialog({
  orderId,
  currency,
  onClose,
  onCreated,
}: {
  orderId: string;
  currency: string;
  onClose: () => void;
  onCreated: () => void;
}) {
  const { t } = useTranslation();
  const [desc, setDesc] = useState('');
  const [changeType, setChangeType] = useState('modified');
  const [origQty, setOrigQty] = useState(0);
  const [newQty, setNewQty] = useState(0);
  const [origRate, setOrigRate] = useState(0);
  const [newRate, setNewRate] = useState(0);
  const [unit, setUnit] = useState('');
  const addToast = useToastStore((s) => s.addToast);

  const mutation = useMutation({
    mutationFn: () =>
      apiPost<ChangeOrderItem>(`/v1/changeorders/${orderId}/items/`, {
        description: desc,
        change_type: changeType,
        original_quantity: origQty,
        new_quantity: newQty,
        original_rate: origRate,
        new_rate: newRate,
        unit,
      }),
    onSuccess: () => {
      onCreated();
      onClose();
      addToast({
        type: 'success',
        title: t('changeorders.item_added', { defaultValue: 'Item added' }),
      });
    },
    onError: (err: Error) => {
      addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: err.message });
    },
  });

  const costDelta = (newQty * newRate) - (origQty * origRate);

  const fieldCls =
    'h-10 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';

  return (
    <WideModal
      open
      onClose={onClose}
      title={t('changeorders.add_item', { defaultValue: 'Add Item' })}
      size="xl"
      busy={mutation.isPending}
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={mutation.isPending}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button
            variant="primary"
            disabled={!desc.trim() || mutation.isPending}
            onClick={() => mutation.mutate()}
          >
            {mutation.isPending
              ? t('common.adding', { defaultValue: 'Adding...' })
              : t('changeorders.add_item', { defaultValue: 'Add Item' })}
          </Button>
        </>
      }
    >
      <WideModalSection
        title={t('changeorders.section_basic', { defaultValue: 'Item details' })}
        columns={2}
      >
        <WideModalField
          label={t('common.description', { defaultValue: 'Description' })}
          required
          span={2}
          htmlFor="item-description"
        >
          <input
            id="item-description"
            value={desc}
            onChange={(e) => setDesc(e.target.value)}
            className={fieldCls}
          />
        </WideModalField>
        <WideModalField
          label={t('changeorders.change_type', { defaultValue: 'Change Type' })}
          htmlFor="item-change-type"
        >
          <select
            id="item-change-type"
            value={changeType}
            onChange={(e) => setChangeType(e.target.value)}
            className={fieldCls}
          >
            <option value="added">{t('changeorders.type_added', { defaultValue: 'Added' })}</option>
            <option value="removed">{t('changeorders.type_removed', { defaultValue: 'Removed' })}</option>
            <option value="modified">{t('changeorders.type_modified', { defaultValue: 'Modified' })}</option>
          </select>
        </WideModalField>
        <WideModalField
          label={t('common.unit')}
          htmlFor="item-unit"
        >
          <input
            id="item-unit"
            value={unit}
            onChange={(e) => setUnit(e.target.value)}
            placeholder={t('changeorders.unit_placeholder', { defaultValue: 'm2, m3, pcs...' })}
            className={fieldCls}
          />
        </WideModalField>
      </WideModalSection>

      <WideModalSection
        title={t('changeorders.section_quantities', { defaultValue: 'Quantities & rates' })}
        columns={2}
      >
        <WideModalField
          label={t('changeorders.orig_qty', { defaultValue: 'Original Qty' })}
          htmlFor="item-orig-qty"
        >
          <input
            id="item-orig-qty"
            type="number"
            min={0}
            step="any"
            value={origQty}
            onChange={(e) => setOrigQty(parseFloat(e.target.value) || 0)}
            className={fieldCls}
          />
        </WideModalField>
        <WideModalField
          label={t('changeorders.new_qty', { defaultValue: 'New Qty' })}
          htmlFor="item-new-qty"
        >
          <input
            id="item-new-qty"
            type="number"
            min={0}
            step="any"
            value={newQty}
            onChange={(e) => setNewQty(parseFloat(e.target.value) || 0)}
            className={fieldCls}
          />
        </WideModalField>
        <WideModalField
          label={t('changeorders.orig_rate', { defaultValue: 'Original Rate' })}
          htmlFor="item-orig-rate"
        >
          <input
            id="item-orig-rate"
            type="number"
            min={0}
            step="any"
            value={origRate}
            onChange={(e) => setOrigRate(parseFloat(e.target.value) || 0)}
            className={fieldCls}
          />
        </WideModalField>
        <WideModalField
          label={t('changeorders.new_rate', { defaultValue: 'New Rate' })}
          htmlFor="item-new-rate"
        >
          <input
            id="item-new-rate"
            type="number"
            min={0}
            step="any"
            value={newRate}
            onChange={(e) => setNewRate(parseFloat(e.target.value) || 0)}
            className={fieldCls}
          />
        </WideModalField>
        <div className="sm:col-span-2 rounded-lg bg-surface-secondary p-3 text-sm">
          <span className="text-content-secondary">{t('changeorders.cost_delta', { defaultValue: 'Cost Delta' })}:</span>{' '}
          <span className={costDelta >= 0 ? 'font-semibold text-semantic-error' : 'font-semibold text-semantic-success'}>
            {costDelta >= 0 ? '+' : ''}{formatCurrency(costDelta, currency)}
          </span>
        </div>
      </WideModalSection>
    </WideModal>
  );
}

/* ── Approval Chain Builder ────────────────────────────────────────────── */

/**
 * Minimal approver-id picker — accepts one UUID per line so an admin can
 * paste a list of user ids without needing the full users-directory
 * search-and-select widget. The full picker can replace this textarea
 * later without changing the API surface.
 */
function ApprovalChainBuilderDialog({
  onClose,
  onConfirm,
  busy,
}: {
  onClose: () => void;
  onConfirm: (approverUserIds: string[]) => void;
  busy: boolean;
}) {
  const { t } = useTranslation();
  const [raw, setRaw] = useState('');
  const ids = useMemo(
    () =>
      raw
        .split(/[\s,;]+/)
        .map((x) => x.trim())
        .filter((x) => x.length > 0),
    [raw],
  );
  // Permissive UUID check — back-end Pydantic will reject malformed
  // ones anyway; we just want to catch typos early.
  const looksValid =
    ids.length > 0 &&
    ids.length <= 20 &&
    ids.every((id) => /^[0-9a-f-]{32,36}$/i.test(id));

  return (
    <WideModal
      open
      onClose={onClose}
      title={t('changeorders.approval_chain_builder_title', {
        defaultValue: 'Start approval chain',
      })}
      size="md"
      busy={busy}
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={busy}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button
            variant="primary"
            disabled={!looksValid || busy}
            onClick={() => onConfirm(ids)}
          >
            {busy
              ? t('common.saving', { defaultValue: 'Saving…' })
              : t('changeorders.approval_chain_start_action', {
                  defaultValue: 'Start chain',
                })}
          </Button>
        </>
      }
    >
      <WideModalSection columns={1}>
        <WideModalField
          label={t('changeorders.approver_user_ids_label', {
            defaultValue: 'Approver user ids (one per line, in step order)',
          })}
          htmlFor="approver-user-ids"
          span={1}
        >
          <textarea
            id="approver-user-ids"
            value={raw}
            onChange={(e) => setRaw(e.target.value)}
            rows={5}
            disabled={busy}
            placeholder={'b1f7e8e2-…\n5c0a9d1f-…\n8e4f1a32-…'}
            className="w-full rounded-lg border border-border bg-surface-primary p-2 font-mono text-xs focus:border-oe-blue focus:outline-none focus:ring-2 focus:ring-oe-blue/30"
          />
        </WideModalField>
        <p className="text-xs text-content-tertiary">
          {t('changeorders.approver_user_ids_hint', {
            defaultValue:
              'Steps run sequentially: step 1 acts first, then step 2, etc. Each approver only sees the change order when their step becomes active.',
          })}
        </p>
      </WideModalSection>
    </WideModal>
  );
}

/* ── Workflow Stepper ─────────────────────────────────────────────────── */

function WorkflowStepper({ status, t }: { status: string; t: (key: string, opts?: Record<string, unknown>) => string }) {
  const steps = [
    { key: 'draft', label: t('changeorders.status_draft', { defaultValue: 'Draft' }) },
    { key: 'submitted', label: t('changeorders.status_submitted', { defaultValue: 'Submitted' }) },
    { key: 'approved', label: t('changeorders.status_approved', { defaultValue: 'Approved' }) },
  ];

  // Map status to step index
  const statusIndex: Record<string, number> = { draft: 0, submitted: 1, under_review: 1, approved: 2, rejected: 2 };
  const currentIdx = statusIndex[status] ?? 0;
  const isRejected = status === 'rejected';

  return (
    <div className="flex items-center gap-0 mb-6" role="list" aria-label={t('changeorders.workflow', { defaultValue: 'Workflow' })}>
      {steps.map((step, i) => {
        const isActive = i === currentIdx;
        const isCompleted = i < currentIdx;
        const isLast = i === steps.length - 1;
        const showRejected = isLast && isRejected;

        return (
          <div key={step.key} className="flex items-center" role="listitem">
            <div className="flex flex-col items-center">
              <div className={`flex h-8 w-8 items-center justify-center rounded-full border-2 text-xs font-bold transition-colors ${
                showRejected
                  ? 'border-semantic-error bg-semantic-error-bg text-semantic-error'
                  : isCompleted
                    ? 'border-semantic-success bg-semantic-success-bg text-semantic-success'
                    : isActive
                      ? 'border-oe-blue bg-oe-blue-subtle text-oe-blue-text'
                      : 'border-border-light bg-surface-secondary text-content-tertiary'
              }`}>
                {showRejected ? '\u2715' : isCompleted ? '\u2713' : i + 1}
              </div>
              <span className={`mt-1.5 text-2xs font-medium ${
                showRejected ? 'text-semantic-error' : isActive ? 'text-oe-blue' : isCompleted ? 'text-semantic-success' : 'text-content-tertiary'
              }`}>
                {showRejected ? t('changeorders.status_rejected', { defaultValue: 'Rejected' }) : step.label}
              </span>
            </div>
            {!isLast && (
              <div className={`h-0.5 w-12 mx-2 rounded ${
                isCompleted ? 'bg-semantic-success' : 'bg-border-light'
              }`} />
            )}
          </div>
        );
      })}
    </div>
  );
}

/* ── Detail View ───────────────────────────────────────────────────────── */

function DetailView({
  orderId,
  onBack,
}: {
  orderId: string;
  onBack: () => void;
}) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const userRole = useAuthStore((s) => s.userRole);
  const accessToken = useAuthStore((s) => s.accessToken);
  const { confirm, ...confirmProps } = useConfirm();
  const [showAddItem, setShowAddItem] = useState(false);
  const [showChainBuilder, setShowChainBuilder] = useState(false);

  // Only admins and managers can approve/reject change orders. Backend
  // permission `changeorders.approve` enforces this server-side; we hide
  // the buttons in the UI to give a better experience than 403 errors.
  const canApprove = userRole === 'admin' || userRole === 'manager';
  const currentUserId = useMemo(
    () => decodeUserIdFromToken(accessToken),
    [accessToken],
  );

  const { data: order, isLoading, isError } = useQuery({
    queryKey: ['changeorder', orderId],
    queryFn: () => apiGet<ChangeOrderWithItems>(`/v1/changeorders/${orderId}`),
  });

  const submitMut = useMutation({
    mutationFn: () => apiPost<ChangeOrder>(`/v1/changeorders/${orderId}/submit/`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['changeorder', orderId] });
      queryClient.invalidateQueries({ queryKey: ['changeorders'] });
      addToast({ type: 'success', title: t('changeorders.submitted', { defaultValue: 'Change order submitted' }) });
    },
    onError: (err: Error) => addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: err.message }),
  });

  const approveMut = useMutation({
    mutationFn: () => apiPost<ChangeOrder>(`/v1/changeorders/${orderId}/approve/`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['changeorder', orderId] });
      queryClient.invalidateQueries({ queryKey: ['changeorders'] });
      addToast({ type: 'success', title: t('changeorders.approved', { defaultValue: 'Change order approved' }) });
    },
    onError: (err: Error) => addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: err.message }),
  });

  const rejectMut = useMutation({
    mutationFn: () => apiPost<ChangeOrder>(`/v1/changeorders/${orderId}/reject/`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['changeorder', orderId] });
      queryClient.invalidateQueries({ queryKey: ['changeorders'] });
      addToast({ type: 'success', title: t('changeorders.rejected', { defaultValue: 'Change order rejected' }) });
    },
    onError: (err: Error) => addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: err.message }),
  });

  const deleteItemMut = useMutation({
    mutationFn: (itemId: string) => apiDelete(`/v1/changeorders/${orderId}/items/${itemId}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['changeorder', orderId] });
      queryClient.invalidateQueries({ queryKey: ['changeorders'] });
      addToast({ type: 'success', title: t('changeorders.item_deleted', { defaultValue: 'Item deleted' }) });
    },
    onError: (err: Error) => addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: err.message }),
  });

  // ── T3: Procore-style approval chain ───────────────────────────────────
  // Fetched alongside the order detail so the timeline is always in sync
  // with the cursor. Cheap query — typically 1-5 rows.
  const { data: approvals = [] } = useQuery<ApprovalRow[]>({
    queryKey: ['changeorder-approvals', orderId],
    queryFn: () => getApprovals(orderId),
  });

  const startChainMut = useMutation({
    mutationFn: (approverUserIds: string[]) =>
      startApprovalChain(orderId, approverUserIds),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['changeorder', orderId] });
      queryClient.invalidateQueries({
        queryKey: ['changeorder-approvals', orderId],
      });
      setShowChainBuilder(false);
      addToast({
        type: 'success',
        title: t('changeorders.approval_chain_started', {
          defaultValue: 'Approval chain started',
        }),
      });
    },
    onError: (err: Error) =>
      addToast({
        type: 'error',
        title: t('common.error', { defaultValue: 'Error' }),
        message: err.message,
      }),
  });

  const advanceMut = useMutation({
    mutationFn: (input: {
      decision: 'approved' | 'rejected';
      comments: string;
    }) =>
      advanceApproval(orderId, {
        decision: input.decision,
        comments: input.comments || undefined,
      }),
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({ queryKey: ['changeorder', orderId] });
      queryClient.invalidateQueries({
        queryKey: ['changeorder-approvals', orderId],
      });
      queryClient.invalidateQueries({ queryKey: ['changeorders'] });
      addToast({
        type: 'success',
        title:
          variables.decision === 'approved'
            ? t('changeorders.approval_step_approved', {
                defaultValue: 'Step approved',
              })
            : t('changeorders.approval_step_rejected', {
                defaultValue: 'Change order rejected',
              }),
      });
    },
    onError: (err: Error) =>
      addToast({
        type: 'error',
        title: t('common.error', { defaultValue: 'Error' }),
        message: err.message,
      }),
  });

  if (isLoading || (!order && !isError)) {
    return <SkeletonCard className="my-6" />;
  }

  if (isError || !order) {
    return (
      <div>
        <button
          onClick={onBack}
          aria-label={t('changeorders.back_to_list', { defaultValue: 'Back to change orders list' })}
          className="inline-flex items-center gap-1.5 text-sm text-content-secondary hover:text-content-primary mb-3"
        >
          <ArrowLeft size={14} />
          {t('common.back', { defaultValue: 'Back' })}
        </button>
        <Card className="py-12">
          <EmptyState
            icon={<AlertTriangle size={28} strokeWidth={1.5} />}
            title={t('common.error', { defaultValue: 'Error' })}
            description={t('changeorders.load_error', { defaultValue: 'Failed to load change order. Please try again.' })}
          />
        </Card>
      </div>
    );
  }

  const canEdit = order.status === 'draft' || order.status === 'submitted';

  return (
    <div>
      {/* Header */}
      <div className="mb-6">
        <nav className="flex items-center gap-1.5 text-sm mb-4" aria-label="Breadcrumb">
          <button
            onClick={onBack}
            aria-label={t('changeorders.back_to_list', { defaultValue: 'Back to change orders list' })}
            className="text-content-secondary hover:text-oe-blue transition-colors"
          >
            {t('nav.change_orders', { defaultValue: 'Change Orders' })}
          </button>
          <ChevronRight size={12} className="text-content-tertiary" />
          <span className="text-content-primary font-medium">{order.code}</span>
        </nav>

        <WorkflowStepper status={order.status} t={t} />

        <div className="flex items-start justify-between">
          <div>
            <div className="flex items-center gap-3">
              <h2 className="text-xl font-semibold text-content-primary">{order.code}</h2>
              <Badge variant={STATUS_COLORS[order.status] || 'neutral'}>{translateStatus(order.status, t)}</Badge>
            </div>
            <h3 className="mt-1 text-lg text-content-secondary">{order.title}</h3>
            {order.description && (
              <p className="mt-2 text-sm text-content-tertiary max-w-2xl">{order.description}</p>
            )}
          </div>

          <div className="flex gap-2 items-center">
            {order.status === 'draft' && (
              <Button variant="primary" size="sm" onClick={async () => {
                const ok = await confirm({
                  title: t('changeorders.submit_confirm_title', { defaultValue: 'Submit change order?' }),
                  message: t('changeorders.submit_confirm', { defaultValue: 'Submit this change order for review? This cannot be undone.' }),
                  variant: 'warning',
                });
                if (ok) submitMut.mutate();
              }} disabled={submitMut.isPending}>
                <Send size={14} className="mr-1.5" />
                {t('changeorders.submit', { defaultValue: 'Submit' })}
              </Button>
            )}
            {order.status === 'submitted' && (
              canApprove ? (
                <>
                  <Button variant="primary" size="sm" onClick={async () => {
                    const ok = await confirm({
                      title: t('changeorders.approve_confirm_title', { defaultValue: 'Approve change order?' }),
                      message: t('changeorders.approve_confirm', { defaultValue: 'Approve this change order? Cost impact will be applied to the project budget.' }),
                      variant: 'warning',
                    });
                    if (ok) approveMut.mutate();
                  }} disabled={approveMut.isPending}>
                    <CheckCircle2 size={14} className="mr-1.5" />
                    {t('changeorders.approve', { defaultValue: 'Approve' })}
                  </Button>
                  <Button variant="ghost" size="sm" onClick={async () => {
                    const ok = await confirm({
                      title: t('changeorders.reject_confirm_title', { defaultValue: 'Reject change order?' }),
                      message: t('changeorders.reject_confirm', { defaultValue: 'Reject this change order?' }),
                    });
                    if (ok) rejectMut.mutate();
                  }} disabled={rejectMut.isPending}>
                    <XCircle size={14} className="mr-1.5" />
                    {t('changeorders.reject', { defaultValue: 'Reject' })}
                  </Button>
                </>
              ) : (
                // Non-admin/manager: show clear "awaiting approval" state instead
                // of an Approve button that would just return 403.
                <div className="flex items-center gap-2 rounded-lg border border-amber-300 bg-amber-50 dark:bg-amber-900/20 dark:border-amber-800 px-3 py-1.5">
                  <CheckCircle2 size={14} className="text-amber-600 dark:text-amber-400" />
                  <div className="text-xs">
                    <p className="font-medium text-amber-900 dark:text-amber-200">
                      {t('changeorders.pending_approval', { defaultValue: 'Awaiting approval' })}
                    </p>
                    <p className="text-amber-800 dark:text-amber-300">
                      {t('changeorders.pending_approval_hint', {
                        defaultValue: 'Only managers and admins can approve.',
                      })}
                    </p>
                  </div>
                </div>
              )
            )}
          </div>
        </div>
      </div>

      {/* Info cards */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mb-6">
        <Card className="p-4">
          <p className="text-xs text-content-tertiary uppercase tracking-wide">
            {t('changeorders.reason', { defaultValue: 'Reason' })}
          </p>
          <p className="mt-1 text-sm font-medium text-content-primary">
            {t(`changeorders.reason_${order.reason_category}`, {
              defaultValue: getReasonLabels(t)[order.reason_category] || order.reason_category,
            })}
          </p>
        </Card>
        <Card className="p-4">
          <p className="text-xs text-content-tertiary uppercase tracking-wide">
            {t('changeorders.cost_impact', { defaultValue: 'Cost Impact' })}
          </p>
          <p className={`mt-1 text-sm font-semibold ${order.cost_impact >= 0 ? 'text-semantic-error' : 'text-semantic-success'}`}>
            {order.cost_impact >= 0 ? '+' : ''}{formatCurrency(order.cost_impact, order.currency)}
          </p>
          <p className="mt-1 text-2xs text-content-tertiary leading-snug">
            {order.status === 'approved'
              ? t('changeorders.cost_impact_applied', {
                  defaultValue: 'Applied to the project budget (revised budget).',
                })
              : t('changeorders.cost_impact_pending', {
                  defaultValue: 'Applied to the project budget once approved.',
                })}
          </p>
        </Card>
        <Card className="p-4">
          <p className="text-xs text-content-tertiary uppercase tracking-wide">
            {t('changeorders.schedule_impact', { defaultValue: 'Schedule Impact' })}
          </p>
          <p className="mt-1 text-sm font-medium text-content-primary">
            {order.schedule_impact_days} {t('common.days', { defaultValue: 'days' })}
          </p>
        </Card>
        <Card className="p-4">
          <p className="text-xs text-content-tertiary uppercase tracking-wide">
            {t('common.created', { defaultValue: 'Created' })}
          </p>
          <p className="mt-1 text-sm font-medium text-content-primary">{formatDate(order.created_at)}</p>
        </Card>
      </div>

      {/* Audit trail */}
      {(order.submitted_at || order.approved_at) && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mb-6">
          {order.submitted_at && (
            <Card className="p-4">
              <p className="text-xs text-content-tertiary uppercase tracking-wide">
                {t('changeorders.submitted_at', { defaultValue: 'Submitted' })}
              </p>
              <p className="mt-1 text-sm font-medium text-content-primary">{formatDate(order.submitted_at)}</p>
              {order.submitted_by && (
                <p className="mt-0.5 text-xs text-content-tertiary">{order.submitted_by}</p>
              )}
            </Card>
          )}
          {order.approved_at && (
            <Card className="p-4">
              <p className="text-xs text-content-tertiary uppercase tracking-wide">
                {order.status === 'rejected'
                  ? t('changeorders.rejected_at', { defaultValue: 'Rejected' })
                  : t('changeorders.approved_at', { defaultValue: 'Approved' })}
              </p>
              <p className="mt-1 text-sm font-medium text-content-primary">{formatDate(order.approved_at)}</p>
              {order.approved_by && (
                <p className="mt-0.5 text-xs text-content-tertiary">{order.approved_by}</p>
              )}
            </Card>
          )}
        </div>
      )}

      {/* T3: Procore-style approval chain. Shown when the CO has either
          a chain already or is in 'submitted' state (so an admin/manager
          can start one). Hidden on plain draft/approved/rejected COs with
          no chain to avoid cluttering simple workflows. */}
      {(approvals.length > 0 ||
        (order.status === 'submitted' && canApprove)) && (
        <div className="mb-6">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-base font-semibold text-content-primary">
              {t('changeorders.approvals_section', {
                defaultValue: 'Approvals',
              })}
            </h3>
            {approvals.length === 0 &&
              order.status === 'submitted' &&
              canApprove && (
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => setShowChainBuilder(true)}
                  disabled={startChainMut.isPending}
                >
                  {t('changeorders.start_approval_chain', {
                    defaultValue: 'Start approval chain',
                  })}
                </Button>
              )}
          </div>
          <ApprovalTimeline
            rows={approvals}
            currentApprovalStep={order.current_approval_step ?? null}
            currentUserId={currentUserId}
            busy={advanceMut.isPending}
            onDecide={(decision, comments) =>
              advanceMut.mutate({ decision, comments })
            }
          />
        </div>
      )}

      {showChainBuilder && (
        <ApprovalChainBuilderDialog
          onClose={() => setShowChainBuilder(false)}
          onConfirm={(ids) => startChainMut.mutate(ids)}
          busy={startChainMut.isPending}
        />
      )}

      {/* Items */}
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-base font-semibold text-content-primary">
          {t('changeorders.items', { defaultValue: 'Line Items' })} ({order.items.length})
        </h3>
        {canEdit && (
          <Button variant="secondary" size="sm" onClick={() => setShowAddItem(true)}>
            <Plus size={14} className="mr-1.5" />
            {t('changeorders.add_item', { defaultValue: 'Add Item' })}
          </Button>
        )}
      </div>

      {order.items.length === 0 ? (
        <Card className="py-12">
          <EmptyState
            icon={<FileEdit size={28} strokeWidth={1.5} />}
            title={t('changeorders.no_items', { defaultValue: 'No items yet' })}
            description={t('changeorders.no_items_desc', { defaultValue: 'Add line items to define the scope change' })}
            action={
              canEdit
                ? { label: t('changeorders.add_item', { defaultValue: 'Add Item' }), onClick: () => setShowAddItem(true) }
                : undefined
            }
          />
        </Card>
      ) : (
        <Card className="overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm" aria-label={t('changeorders.items_table_aria', { defaultValue: 'Change order line items' })}>
              <thead>
                <tr className="border-b border-border bg-surface-secondary/50">
                  <th className="px-4 py-3 text-left font-medium text-content-secondary">
                    {t('common.description', { defaultValue: 'Description' })}
                  </th>
                  <th className="px-4 py-3 text-left font-medium text-content-secondary">
                    {t('changeorders.type', { defaultValue: 'Type' })}
                  </th>
                  <th className="px-4 py-3 text-right font-medium text-content-secondary">
                    {t('changeorders.orig_qty', { defaultValue: 'Orig Qty' })}
                  </th>
                  <th className="px-4 py-3 text-right font-medium text-content-secondary">
                    {t('changeorders.new_qty', { defaultValue: 'New Qty' })}
                  </th>
                  <th className="px-4 py-3 text-right font-medium text-content-secondary">
                    {t('changeorders.cost_delta', { defaultValue: 'Cost Delta' })}
                  </th>
                  {canEdit && (
                    <th className="px-4 py-3 w-12" />
                  )}
                </tr>
              </thead>
              <tbody>
                {order.items.map((item) => (
                  <tr key={item.id} className="border-b border-border last:border-0 hover:bg-surface-secondary/30">
                    <td className="px-4 py-3 text-content-primary">{item.description}</td>
                    <td className="px-4 py-3">
                      <Badge variant={item.change_type === 'added' ? 'success' : item.change_type === 'removed' ? 'error' : 'neutral'}>
                        {t(`changeorders.type_${item.change_type}`, { defaultValue: item.change_type })}
                      </Badge>
                    </td>
                    <td className="px-4 py-3 text-right text-content-secondary tabular-nums">
                      {item.original_quantity} {item.unit}
                    </td>
                    <td className="px-4 py-3 text-right text-content-secondary tabular-nums">
                      {item.new_quantity} {item.unit}
                    </td>
                    <td className={`px-4 py-3 text-right font-medium tabular-nums ${item.cost_delta >= 0 ? 'text-semantic-error' : 'text-semantic-success'}`}>
                      {item.cost_delta >= 0 ? '+' : ''}{formatCurrency(item.cost_delta, order.currency)}
                    </td>
                    {canEdit && (
                      <td className="px-4 py-3 text-center">
                        <button
                          onClick={async () => {
                            const ok = await confirm({
                              title: t('changeorders.delete_item_confirm_title', { defaultValue: 'Delete item?' }),
                              message: t('changeorders.delete_item_confirm', { defaultValue: 'Delete this item?' }),
                            });
                            if (ok) deleteItemMut.mutate(item.id);
                          }}
                          className="text-content-tertiary hover:text-semantic-error transition-colors"
                          title={t('common.delete', { defaultValue: 'Delete' })}
                          aria-label={t('changeorders.delete_item_aria', {
                            defaultValue: 'Delete item: {{desc}}',
                            desc: item.description,
                          })}
                        >
                          <Trash2 size={14} />
                        </button>
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      {showAddItem && (
        <AddItemDialog
          orderId={orderId}
          currency={order.currency}
          onClose={() => setShowAddItem(false)}
          onCreated={() => {
            queryClient.invalidateQueries({ queryKey: ['changeorder', orderId] });
            queryClient.invalidateQueries({ queryKey: ['changeorders'] });
          }}
        />
      )}
      <ConfirmDialog {...confirmProps} />
    </div>
  );
}

/* ── Main Page ─────────────────────────────────────────────────────────── */

export function ChangeOrdersPage() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const activeProjectId = useProjectContextStore((s) => s.activeProjectId);
  const { confirm: confirmList, ...confirmListProps } = useConfirm();

  const [showCreate, setShowCreate] = useState(false);
  const [selectedOrderId, setSelectedOrderId] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<string>('');

  // Fetch projects
  const { data: projects = [] } = useQuery({
    queryKey: ['projects'],
    queryFn: () => apiGet<Project[]>('/v1/projects/'),
    staleTime: 5 * 60_000,
  });

  const projectId = activeProjectId || projects[0]?.id || '';
  const project = useMemo(() => projects.find((p) => p.id === projectId), [projects, projectId]);

  // Fetch change orders
  const { data: orders = [], isLoading, isError, error, refetch } = useQuery({
    queryKey: ['changeorders', projectId],
    queryFn: () => apiGet<ChangeOrder[]>(`/v1/changeorders/?project_id=${projectId}`),
    select: (d): ChangeOrder[] => normalizeListResponse(d),
    enabled: !!projectId,
  });

  const filteredOrders = useMemo(() => {
    if (!statusFilter) return orders;
    return orders.filter((o) => o.status === statusFilter);
  }, [orders, statusFilter]);

  // Fetch summary
  const { data: summary } = useQuery({
    queryKey: ['changeorders-summary', projectId],
    queryFn: () => apiGet<Summary>(`/v1/changeorders/summary/?project_id=${projectId}`),
    enabled: !!projectId,
  });

  const deleteMut = useMutation({
    mutationFn: (id: string) => apiDelete(`/v1/changeorders/${id}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['changeorders'] });
      queryClient.invalidateQueries({ queryKey: ['changeorders-summary'] });
      addToast({ type: 'success', title: t('changeorders.deleted', { defaultValue: 'Change order deleted' }) });
    },
    onError: (err: Error) => addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: err.message }),
  });

  const handleRefresh = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: ['changeorders'] });
    queryClient.invalidateQueries({ queryKey: ['changeorders-summary'] });
  }, [queryClient]);

  const handleExportCSV = useCallback(() => {
    if (!filteredOrders.length) return;
    const headers = ['Code', 'Title', 'Status', 'Reason', 'Cost Impact', 'Schedule Days', 'Items', 'Created'];
    const rows = filteredOrders.map(o => [
      o.code,
      `"${o.title.replace(/"/g, '""')}"`,
      o.status,
      getReasonLabels(t)[o.reason_category] || o.reason_category,
      o.cost_impact.toFixed(2),
      String(o.schedule_impact_days),
      String(o.item_count),
      o.created_at?.slice(0, 10) || '',
    ].join(','));
    const csv = [headers.join(','), ...rows].join('\n');
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `change_orders_${project?.name || 'export'}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  }, [filteredOrders, project, t]);

  // Detail view
  if (selectedOrderId) {
    return (
      <div className="w-full">
        <DetailView orderId={selectedOrderId} onBack={() => setSelectedOrderId(null)} />
      </div>
    );
  }

  // Empty when the project carries no currency — the backend resolves the
  // project's currency on create, and formatCurrency renders a symbol-less
  // number rather than mis-labelling amounts as EUR (task #217).
  const currency = project?.currency || summary?.currency || '';

  return (
    <div className="w-full animate-fade-in">
      <Breadcrumb items={[
        { label: t('nav.dashboard', { defaultValue: 'Dashboard' }), to: '/' },
        { label: t('nav.change_orders', { defaultValue: 'Change Orders' }) },
      ]} />

      {/* Header */}
      <div className="mt-4 flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold text-content-primary">
            {t('nav.change_orders', { defaultValue: 'Change Orders' })}
          </h1>
          <p className="mt-1 text-sm text-content-secondary">
            {t('changeorders.subtitle', { defaultValue: 'Track scope changes with cost and schedule impact' })}
          </p>
        </div>
        <div className="flex items-end gap-3">
          <div>
            <label htmlFor="co-project-select" className="block text-sm font-medium text-content-primary mb-1.5">
              {t('common.project', { defaultValue: 'Project' })}
            </label>
            <select
              id="co-project-select"
              value={projectId}
              onChange={(e) => {
                const id = e.target.value;
                const name = projects.find((p) => p.id === id)?.name ?? '';
                if (id) {
                  useProjectContextStore.getState().setActiveProject(id, name);
                }
              }}
              className="h-10 w-full min-w-[200px] rounded-lg border border-border bg-surface-primary px-3 text-sm transition-all focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue"
            >
              {projects.map((p) => (
                <option key={p.id} value={p.id}>{p.name}</option>
              ))}
            </select>
          </div>
          <Button variant="secondary" size="sm" icon={<Download size={14} />} onClick={handleExportCSV} disabled={!filteredOrders || filteredOrders.length === 0}>
            {t('changeorders.export_csv', { defaultValue: 'Export CSV' })}
          </Button>
          <Button variant="primary" onClick={() => setShowCreate(true)} disabled={!projectId}>
            <Plus size={16} className="mr-1.5" />
            {t('changeorders.new', { defaultValue: 'New Change Order' })}
          </Button>
        </div>
      </div>

      <InfoHint className="mt-4 mb-2" text={t('changeorders.workflow_desc', { defaultValue: 'Change Order workflow: Draft (prepare scope change) \u2192 Submitted (send for review) \u2192 Approved or Rejected. Each order tracks cost impact and schedule impact in days. Add line items to detail what changed \u2014 original vs new quantities and rates. The cost delta is computed automatically.' })} />

      {/* Summary cards */}
      {summary && (
        <div className="mt-6 grid grid-cols-2 sm:grid-cols-4 gap-4">
          <Card className="p-4">
            <div className="flex items-center gap-2">
              <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-surface-secondary">
                <FileEdit size={16} className="text-content-tertiary" />
              </div>
              <div>
                <p className="text-2xs text-content-tertiary uppercase tracking-wide">
                  {t('changeorders.total', { defaultValue: 'Total Orders' })}
                </p>
                <p className="text-lg font-semibold text-content-primary">{summary.total_orders}</p>
              </div>
            </div>
          </Card>
          <Card className="p-4">
            <div className="flex items-center gap-2">
              <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-surface-secondary">
                <DollarSign size={16} className="text-content-tertiary" />
              </div>
              <div>
                <p className="text-2xs text-content-tertiary uppercase tracking-wide">
                  {t('changeorders.approved_impact', { defaultValue: 'Approved Impact' })}
                </p>
                <p className={`text-lg font-semibold ${summary.total_cost_impact >= 0 ? 'text-semantic-error' : 'text-semantic-success'}`}>
                  {summary.total_cost_impact >= 0 ? '+' : ''}{formatCurrency(summary.total_cost_impact, currency)}
                </p>
              </div>
            </div>
          </Card>
          <Card className="p-4">
            <div className="flex items-center gap-2">
              <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-surface-secondary">
                <Clock size={16} className="text-content-tertiary" />
              </div>
              <div>
                <p className="text-2xs text-content-tertiary uppercase tracking-wide">
                  {t('changeorders.schedule_total', { defaultValue: 'Schedule Days' })}
                </p>
                <p className="text-lg font-semibold text-content-primary">
                  {summary.total_schedule_impact_days} {t('common.days', { defaultValue: 'days' })}
                </p>
              </div>
            </div>
          </Card>
          <Card className="p-4">
            <div className="flex items-center gap-2">
              <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-surface-secondary">
                <AlertTriangle size={16} className="text-content-tertiary" />
              </div>
              <div>
                <p className="text-2xs text-content-tertiary uppercase tracking-wide">
                  {t('changeorders.pending', { defaultValue: 'Pending' })}
                </p>
                <p className="text-lg font-semibold text-content-primary">
                  {summary.submitted_count + summary.draft_count}
                </p>
              </div>
            </div>
          </Card>
        </div>
      )}

      {/* Status filter */}
      <div className="mt-6 flex items-center gap-3 mb-3">
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          className="h-9 rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30"
          aria-label={t('changeorders.filter_status', { defaultValue: 'Filter by status' })}
        >
          <option value="">{t('changeorders.all_statuses', { defaultValue: 'All Statuses' })}</option>
          <option value="draft">{translateStatus('draft', t)}</option>
          <option value="submitted">{translateStatus('submitted', t)}</option>
          <option value="approved">{translateStatus('approved', t)}</option>
          <option value="rejected">{translateStatus('rejected', t)}</option>
        </select>
        <span className="text-xs text-content-tertiary">
          {filteredOrders.length} {t('changeorders.of_total', { defaultValue: 'of' })} {orders.length}
        </span>
      </div>

      {/* Orders table */}
      <div>
        {!projectId ? (
          <RequiresProject
            emptyHint={t('changeorders.no_project_desc', { defaultValue: 'Open a project first to view and manage change orders.' })}
          >{null}</RequiresProject>
        ) : isLoading ? (
          <SkeletonTable rows={6} columns={5} />
        ) : isError ? (
          <Card className="py-12">
            <RecoveryCard error={error} onRetry={() => refetch()} />
          </Card>
        ) : orders.length === 0 ? (
          <Card>
            <EmptyState
              icon={<FileEdit size={28} strokeWidth={1.5} />}
              title={t('changeorders.empty', { defaultValue: 'No change orders' })}
              description={t('changeorders.empty_desc', {
                defaultValue: 'Create a change order to track scope changes with cost and schedule impact',
              })}
              action={{
                label: t('changeorders.new', { defaultValue: 'New Change Order' }),
                onClick: () => setShowCreate(true),
              }}
            />
          </Card>
        ) : (
          <Card className="overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full text-sm" aria-label={t('changeorders.table_aria', { defaultValue: 'Change orders list' })}>
                <thead>
                  <tr className="border-b border-border bg-surface-secondary/50">
                    <th className="px-4 py-3 text-left font-medium text-content-secondary">
                      {t('changeorders.code', { defaultValue: 'Code' })}
                    </th>
                    <th className="px-4 py-3 text-left font-medium text-content-secondary">
                      {t('common.title')}
                    </th>
                    <th className="px-4 py-3 text-left font-medium text-content-secondary">
                      {t('common.status')}
                    </th>
                    <th className="px-4 py-3 text-left font-medium text-content-secondary">
                      {t('changeorders.reason', { defaultValue: 'Reason' })}
                    </th>
                    <th className="px-4 py-3 text-right font-medium text-content-secondary">
                      {t('changeorders.cost_impact', { defaultValue: 'Cost Impact' })}
                    </th>
                    <th className="px-4 py-3 text-right font-medium text-content-secondary">
                      {t('changeorders.schedule', { defaultValue: 'Schedule' })}
                    </th>
                    <th className="px-4 py-3 text-left font-medium text-content-secondary">
                      {t('common.date', { defaultValue: 'Date' })}
                    </th>
                    <th className="px-4 py-3 w-16" />
                  </tr>
                </thead>
                <tbody>
                  {filteredOrders.map((order) => (
                    <tr
                      key={order.id}
                      className="border-b border-border last:border-0 hover:bg-surface-secondary/30 cursor-pointer"
                      onClick={() => setSelectedOrderId(order.id)}
                    >
                      <td className="px-4 py-3 font-mono text-xs text-content-secondary whitespace-nowrap">{order.code}</td>
                      <td className="px-4 py-3 text-content-primary font-medium max-w-[200px] truncate">
                        {order.title}
                      </td>
                      <td className="px-4 py-3">
                        <Badge variant={STATUS_COLORS[order.status] || 'neutral'}>{translateStatus(order.status, t)}</Badge>
                      </td>
                      <td className="px-4 py-3 text-content-secondary text-xs">
                        {t(`changeorders.reason_${order.reason_category}`, {
                          defaultValue: getReasonLabels(t)[order.reason_category] || order.reason_category,
                        })}
                      </td>
                      <td className={`px-4 py-3 text-right font-medium tabular-nums ${order.cost_impact >= 0 ? 'text-semantic-error' : 'text-semantic-success'}`}>
                        {order.cost_impact >= 0 ? '+' : ''}{formatCurrency(order.cost_impact, order.currency)}
                      </td>
                      <td className="px-4 py-3 text-right text-content-secondary tabular-nums">
                        {order.schedule_impact_days > 0
                          ? `+${order.schedule_impact_days}d`
                          : order.schedule_impact_days === 0
                            ? '-'
                            : `${order.schedule_impact_days}d`}
                      </td>
                      <td className="px-4 py-3 text-content-tertiary text-xs">{formatDate(order.created_at)}</td>
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-1">
                          {order.status === 'draft' && (
                            <button
                              onClick={async (e) => {
                                e.stopPropagation();
                                const ok = await confirmList({
                                  title: t('changeorders.delete_confirm_title', { defaultValue: 'Delete change order?' }),
                                  message: t('changeorders.delete_confirm', {
                                    defaultValue: 'Delete change order {{code}}? This cannot be undone.',
                                    code: order.code,
                                  }),
                                });
                                if (ok) deleteMut.mutate(order.id);
                              }}
                              className="text-content-tertiary hover:text-semantic-error transition-colors p-1"
                              title={t('common.delete', { defaultValue: 'Delete' })}
                              aria-label={t('changeorders.delete_order_aria', {
                                defaultValue: 'Delete change order {{code}}',
                                code: order.code,
                              })}
                            >
                              <Trash2 size={14} />
                            </button>
                          )}
                          <ChevronRight size={14} className="text-content-tertiary" />
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        )}
      </div>

      {showCreate && projectId && (
        <CreateDialog
          projectId={projectId}
          currency={currency}
          onClose={() => setShowCreate(false)}
          onCreated={handleRefresh}
        />
      )}
      <ConfirmDialog {...confirmListProps} />
    </div>
  );
}

export default ChangeOrdersPage;
