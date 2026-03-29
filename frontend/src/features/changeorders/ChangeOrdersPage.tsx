import { useState, useMemo, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
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
  X,
} from 'lucide-react';
import { Button, Card, Badge, EmptyState, Breadcrumb } from '@/shared/ui';
import { apiGet, apiPost, apiDelete } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import { useProjectContextStore } from '@/stores/useProjectContextStore';

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

const REASON_LABELS: Record<string, string> = {
  client_request: 'Client Request',
  design_change: 'Design Change',
  unforeseen: 'Unforeseen Conditions',
  regulatory: 'Regulatory',
  error: 'Error/Omission',
};

function formatCurrency(amount: number, currency: string = 'EUR'): string {
  const safe = /^[A-Z]{3}$/.test(currency) ? currency : 'EUR';
  try {
    return new Intl.NumberFormat(undefined, {
      style: 'currency',
      currency: safe,
      minimumFractionDigits: 0,
      maximumFractionDigits: 0,
    }).format(amount);
  } catch {
    return `${amount.toFixed(0)} ${safe}`;
  }
}

function formatDate(iso: string | null): string {
  if (!iso) return '-';
  try {
    return new Date(iso).toLocaleDateString(undefined, {
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

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40" onClick={onClose}>
      <div
        className="w-full max-w-lg rounded-xl bg-surface-primary p-6 shadow-xl border border-border"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between mb-5">
          <h2 className="text-lg font-semibold text-content-primary">
            {t('changeorders.new', { defaultValue: 'New Change Order' })}
          </h2>
          <button onClick={onClose} className="text-content-tertiary hover:text-content-primary">
            <X size={18} />
          </button>
        </div>

        <div className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-content-secondary mb-1">
              {t('common.title', { defaultValue: 'Title' })} *
            </label>
            <input
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder={t('changeorders.title_placeholder', { defaultValue: 'e.g. Additional foundation work' })}
              className="h-10 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-content-secondary mb-1">
              {t('common.description', { defaultValue: 'Description' })}
            </label>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={3}
              className="w-full rounded-lg border border-border bg-surface-primary px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue resize-none"
            />
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-content-secondary mb-1">
                {t('changeorders.reason', { defaultValue: 'Reason' })}
              </label>
              <select
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                className="h-10 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue"
              >
                {Object.entries(REASON_LABELS).map(([k, v]) => (
                  <option key={k} value={k}>
                    {t(`changeorders.reason_${k}`, { defaultValue: v })}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="block text-sm font-medium text-content-secondary mb-1">
                {t('changeorders.schedule_days', { defaultValue: 'Schedule Impact (days)' })}
              </label>
              <input
                type="number"
                min={0}
                value={scheduleDays}
                onChange={(e) => setScheduleDays(parseInt(e.target.value) || 0)}
                className="h-10 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue"
              />
            </div>
          </div>
        </div>

        <div className="mt-6 flex justify-end gap-3">
          <Button variant="ghost" onClick={onClose}>
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
        </div>
      </div>
    </div>
  );
}

/* ── Add Item Dialog ───────────────────────────────────────────────────── */

function AddItemDialog({
  orderId,
  onClose,
  onCreated,
}: {
  orderId: string;
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
      apiPost<ChangeOrderItem>(`/v1/changeorders/${orderId}/items`, {
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

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40" onClick={onClose}>
      <div
        className="w-full max-w-lg rounded-xl bg-surface-primary p-6 shadow-xl border border-border"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between mb-5">
          <h2 className="text-lg font-semibold text-content-primary">
            {t('changeorders.add_item', { defaultValue: 'Add Item' })}
          </h2>
          <button onClick={onClose} className="text-content-tertiary hover:text-content-primary">
            <X size={18} />
          </button>
        </div>

        <div className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-content-secondary mb-1">
              {t('common.description', { defaultValue: 'Description' })} *
            </label>
            <input
              value={desc}
              onChange={(e) => setDesc(e.target.value)}
              className="h-10 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue"
            />
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-content-secondary mb-1">
                {t('changeorders.change_type', { defaultValue: 'Change Type' })}
              </label>
              <select
                value={changeType}
                onChange={(e) => setChangeType(e.target.value)}
                className="h-10 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue"
              >
                <option value="added">{t('changeorders.type_added', { defaultValue: 'Added' })}</option>
                <option value="removed">{t('changeorders.type_removed', { defaultValue: 'Removed' })}</option>
                <option value="modified">{t('changeorders.type_modified', { defaultValue: 'Modified' })}</option>
              </select>
            </div>
            <div>
              <label className="block text-sm font-medium text-content-secondary mb-1">
                {t('common.unit', { defaultValue: 'Unit' })}
              </label>
              <input
                value={unit}
                onChange={(e) => setUnit(e.target.value)}
                placeholder="m2, m3, pcs..."
                className="h-10 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue"
              />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-content-secondary mb-1">
                {t('changeorders.orig_qty', { defaultValue: 'Original Qty' })}
              </label>
              <input
                type="number"
                min={0}
                step="any"
                value={origQty}
                onChange={(e) => setOrigQty(parseFloat(e.target.value) || 0)}
                className="h-10 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-content-secondary mb-1">
                {t('changeorders.new_qty', { defaultValue: 'New Qty' })}
              </label>
              <input
                type="number"
                min={0}
                step="any"
                value={newQty}
                onChange={(e) => setNewQty(parseFloat(e.target.value) || 0)}
                className="h-10 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue"
              />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-content-secondary mb-1">
                {t('changeorders.orig_rate', { defaultValue: 'Original Rate' })}
              </label>
              <input
                type="number"
                min={0}
                step="any"
                value={origRate}
                onChange={(e) => setOrigRate(parseFloat(e.target.value) || 0)}
                className="h-10 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-content-secondary mb-1">
                {t('changeorders.new_rate', { defaultValue: 'New Rate' })}
              </label>
              <input
                type="number"
                min={0}
                step="any"
                value={newRate}
                onChange={(e) => setNewRate(parseFloat(e.target.value) || 0)}
                className="h-10 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue"
              />
            </div>
          </div>

          <div className="rounded-lg bg-surface-secondary p-3 text-sm">
            <span className="text-content-secondary">{t('changeorders.cost_delta', { defaultValue: 'Cost Delta' })}:</span>{' '}
            <span className={costDelta >= 0 ? 'font-semibold text-semantic-error' : 'font-semibold text-[#15803d]'}>
              {costDelta >= 0 ? '+' : ''}{costDelta.toFixed(2)}
            </span>
          </div>
        </div>

        <div className="mt-6 flex justify-end gap-3">
          <Button variant="ghost" onClick={onClose}>
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
        </div>
      </div>
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
  const [showAddItem, setShowAddItem] = useState(false);

  const { data: order, isLoading } = useQuery({
    queryKey: ['changeorder', orderId],
    queryFn: () => apiGet<ChangeOrderWithItems>(`/v1/changeorders/${orderId}`),
  });

  const submitMut = useMutation({
    mutationFn: () => apiPost<ChangeOrder>(`/v1/changeorders/${orderId}/submit`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['changeorder', orderId] });
      queryClient.invalidateQueries({ queryKey: ['changeorders'] });
      addToast({ type: 'success', title: t('changeorders.submitted', { defaultValue: 'Change order submitted' }) });
    },
    onError: (err: Error) => addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: err.message }),
  });

  const approveMut = useMutation({
    mutationFn: () => apiPost<ChangeOrder>(`/v1/changeorders/${orderId}/approve`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['changeorder', orderId] });
      queryClient.invalidateQueries({ queryKey: ['changeorders'] });
      addToast({ type: 'success', title: t('changeorders.approved', { defaultValue: 'Change order approved' }) });
    },
    onError: (err: Error) => addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: err.message }),
  });

  const rejectMut = useMutation({
    mutationFn: () => apiPost<ChangeOrder>(`/v1/changeorders/${orderId}/reject`),
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

  if (isLoading || !order) {
    return (
      <div className="flex items-center justify-center py-20">
        <div className="h-6 w-6 animate-spin rounded-full border-2 border-oe-blue border-t-transparent" />
      </div>
    );
  }

  const canEdit = order.status === 'draft' || order.status === 'submitted';

  return (
    <div>
      {/* Header */}
      <div className="mb-6">
        <button
          onClick={onBack}
          className="inline-flex items-center gap-1.5 text-sm text-content-secondary hover:text-content-primary mb-3"
        >
          <ArrowLeft size={14} />
          {t('common.back', { defaultValue: 'Back' })}
        </button>

        <div className="flex items-start justify-between">
          <div>
            <div className="flex items-center gap-3">
              <h2 className="text-xl font-semibold text-content-primary">{order.code}</h2>
              <Badge variant={STATUS_COLORS[order.status] || 'neutral'}>{order.status}</Badge>
            </div>
            <h3 className="mt-1 text-lg text-content-secondary">{order.title}</h3>
            {order.description && (
              <p className="mt-2 text-sm text-content-tertiary max-w-2xl">{order.description}</p>
            )}
          </div>

          <div className="flex gap-2">
            {order.status === 'draft' && (
              <Button variant="primary" size="sm" onClick={() => submitMut.mutate()} disabled={submitMut.isPending}>
                <Send size={14} className="mr-1.5" />
                {t('changeorders.submit', { defaultValue: 'Submit' })}
              </Button>
            )}
            {order.status === 'submitted' && (
              <>
                <Button variant="primary" size="sm" onClick={() => approveMut.mutate()} disabled={approveMut.isPending}>
                  <CheckCircle2 size={14} className="mr-1.5" />
                  {t('changeorders.approve', { defaultValue: 'Approve' })}
                </Button>
                <Button variant="ghost" size="sm" onClick={() => rejectMut.mutate()} disabled={rejectMut.isPending}>
                  <XCircle size={14} className="mr-1.5" />
                  {t('changeorders.reject', { defaultValue: 'Reject' })}
                </Button>
              </>
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
              defaultValue: REASON_LABELS[order.reason_category] || order.reason_category,
            })}
          </p>
        </Card>
        <Card className="p-4">
          <p className="text-xs text-content-tertiary uppercase tracking-wide">
            {t('changeorders.cost_impact', { defaultValue: 'Cost Impact' })}
          </p>
          <p className={`mt-1 text-sm font-semibold ${order.cost_impact >= 0 ? 'text-semantic-error' : 'text-[#15803d]'}`}>
            {order.cost_impact >= 0 ? '+' : ''}{formatCurrency(order.cost_impact, order.currency)}
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
            icon={<FileEdit size={24} />}
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
            <table className="w-full text-sm">
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
                    <td className={`px-4 py-3 text-right font-medium tabular-nums ${item.cost_delta >= 0 ? 'text-semantic-error' : 'text-[#15803d]'}`}>
                      {item.cost_delta >= 0 ? '+' : ''}{item.cost_delta.toFixed(2)}
                    </td>
                    {canEdit && (
                      <td className="px-4 py-3 text-center">
                        <button
                          onClick={() => deleteItemMut.mutate(item.id)}
                          className="text-content-tertiary hover:text-semantic-error transition-colors"
                          title={t('common.delete', { defaultValue: 'Delete' })}
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
          onClose={() => setShowAddItem(false)}
          onCreated={() => {
            queryClient.invalidateQueries({ queryKey: ['changeorder', orderId] });
            queryClient.invalidateQueries({ queryKey: ['changeorders'] });
          }}
        />
      )}
    </div>
  );
}

/* ── Main Page ─────────────────────────────────────────────────────────── */

export function ChangeOrdersPage() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const activeProjectId = useProjectContextStore((s) => s.activeProjectId);

  const [showCreate, setShowCreate] = useState(false);
  const [selectedOrderId, setSelectedOrderId] = useState<string | null>(null);

  // Fetch projects
  const { data: projects = [] } = useQuery({
    queryKey: ['projects'],
    queryFn: () => apiGet<Project[]>('/v1/projects/'),
  });

  const projectId = activeProjectId || projects[0]?.id || '';
  const project = useMemo(() => projects.find((p) => p.id === projectId), [projects, projectId]);

  // Fetch change orders
  const { data: orders = [], isLoading } = useQuery({
    queryKey: ['changeorders', projectId],
    queryFn: () => apiGet<ChangeOrder[]>(`/v1/changeorders/?project_id=${projectId}`),
    enabled: !!projectId,
  });

  // Fetch summary
  const { data: summary } = useQuery({
    queryKey: ['changeorders-summary', projectId],
    queryFn: () => apiGet<Summary>(`/v1/changeorders/summary?project_id=${projectId}`),
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

  // Detail view
  if (selectedOrderId) {
    return (
      <div className="mx-auto max-w-5xl px-6 py-6">
        <DetailView orderId={selectedOrderId} onBack={() => setSelectedOrderId(null)} />
      </div>
    );
  }

  const currency = project?.currency || summary?.currency || 'EUR';

  return (
    <div className="mx-auto max-w-5xl px-6 py-6">
      <Breadcrumb items={[
        { label: t('nav.dashboard', { defaultValue: 'Dashboard' }), to: '/' },
        { label: t('nav.change_orders', { defaultValue: 'Change Orders' }) },
      ]} />

      {/* Header */}
      <div className="mt-4 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-content-primary">
            {t('nav.change_orders', { defaultValue: 'Change Orders' })}
          </h1>
          {project && (
            <p className="mt-1 text-sm text-content-secondary">{project.name}</p>
          )}
        </div>
        <Button variant="primary" onClick={() => setShowCreate(true)} disabled={!projectId}>
          <Plus size={16} className="mr-1.5" />
          {t('changeorders.new', { defaultValue: 'New Change Order' })}
        </Button>
      </div>

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
                <p className={`text-lg font-semibold ${summary.total_cost_impact >= 0 ? 'text-semantic-error' : 'text-[#15803d]'}`}>
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

      {/* Orders table */}
      <div className="mt-6">
        {isLoading ? (
          <div className="flex items-center justify-center py-20">
            <div className="h-6 w-6 animate-spin rounded-full border-2 border-oe-blue border-t-transparent" />
          </div>
        ) : orders.length === 0 ? (
          <Card>
            <EmptyState
              icon={<FileEdit size={24} />}
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
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border bg-surface-secondary/50">
                    <th className="px-4 py-3 text-left font-medium text-content-secondary">
                      {t('changeorders.code', { defaultValue: 'Code' })}
                    </th>
                    <th className="px-4 py-3 text-left font-medium text-content-secondary">
                      {t('common.title', { defaultValue: 'Title' })}
                    </th>
                    <th className="px-4 py-3 text-left font-medium text-content-secondary">
                      {t('common.status', { defaultValue: 'Status' })}
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
                  {orders.map((order) => (
                    <tr
                      key={order.id}
                      className="border-b border-border last:border-0 hover:bg-surface-secondary/30 cursor-pointer"
                      onClick={() => setSelectedOrderId(order.id)}
                    >
                      <td className="px-4 py-3 font-mono text-xs text-content-secondary">{order.code}</td>
                      <td className="px-4 py-3 text-content-primary font-medium max-w-[200px] truncate">
                        {order.title}
                      </td>
                      <td className="px-4 py-3">
                        <Badge variant={STATUS_COLORS[order.status] || 'neutral'}>{order.status}</Badge>
                      </td>
                      <td className="px-4 py-3 text-content-secondary text-xs">
                        {t(`changeorders.reason_${order.reason_category}`, {
                          defaultValue: REASON_LABELS[order.reason_category] || order.reason_category,
                        })}
                      </td>
                      <td className={`px-4 py-3 text-right font-medium tabular-nums ${order.cost_impact >= 0 ? 'text-semantic-error' : 'text-[#15803d]'}`}>
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
                              onClick={(e) => {
                                e.stopPropagation();
                                deleteMut.mutate(order.id);
                              }}
                              className="text-content-tertiary hover:text-semantic-error transition-colors p-1"
                              title={t('common.delete', { defaultValue: 'Delete' })}
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
    </div>
  );
}

export default ChangeOrdersPage;
