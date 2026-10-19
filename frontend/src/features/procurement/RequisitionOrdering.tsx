// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// RequisitionOrdering - who approves a requisition, where it is ordered and
// how much of it is on order (issue #516).
//
// Designated approvers decide in their order: each approval but the last is an
// intermediate step and the requisition stays submitted until the last one.
// A requisition is ordered here (purchase orders, possibly several and in part)
// or in an external purchasing system, which reports its order lines back; no
// local order and no second commitment exists for those. The project settings
// hold the default for both.

import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { AlertTriangle, ArrowUp, Loader2, Plus, Trash2, X } from 'lucide-react';
import { Badge, Button, WideModal, type BadgeVariant } from '@/shared/ui';
import { DateDisplay } from '@/shared/ui/DateDisplay';
import { QuantityDisplay } from '@/shared/ui/QuantityDisplay';
import { getErrorMessage } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import {
  EXTERNAL_ORDER_STATUSES,
  getProcurementSettings,
  isPositiveDecimal,
  listProjectMemberOptions,
  reportExternalOrder,
  updateProcurementSettings,
  type ExternalOrderStatus,
  type OrderOwner,
  type Requisition,
  type RequisitionApprovalStep,
  type RequisitionLine,
} from './requisitionsApi';

const fieldCls =
  'h-9 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';
const smallFieldCls =
  'h-8 w-full rounded-md border border-border bg-surface-primary px-2 text-xs text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';

type Translate = ReturnType<typeof useTranslation>['t'];

/* ── Order owner ────────────────────────────────────────────────────────── */

export function orderOwnerLabel(t: Translate, owner: OrderOwner): string {
  return owner === 'external'
    ? t('procurement.requisitions.owner_external', { defaultValue: 'External purchasing system' })
    : t('procurement.requisitions.owner_ocerp', { defaultValue: 'Purchase orders in this project' });
}

interface OrderOwnerSelectProps {
  id?: string;
  value: OrderOwner;
  onChange: (owner: OrderOwner) => void;
  disabled?: boolean;
}

export function OrderOwnerSelect({ id, value, onChange, disabled }: OrderOwnerSelectProps) {
  const { t } = useTranslation();
  return (
    <select
      id={id}
      className={fieldCls}
      value={value}
      disabled={disabled}
      onChange={(e) => onChange(e.target.value as OrderOwner)}
    >
      <option value="ocerp">{orderOwnerLabel(t, 'ocerp')}</option>
      <option value="external">{orderOwnerLabel(t, 'external')}</option>
    </select>
  );
}

/* ── Approvers ──────────────────────────────────────────────────────────── */

export function useProjectMembers(projectId: string, enabled = true) {
  return useQuery({
    queryKey: ['project-members', projectId],
    queryFn: () => listProjectMemberOptions(projectId),
    enabled: enabled && !!projectId,
    staleTime: 60_000,
  });
}

interface ApproverChainEditorProps {
  projectId: string;
  value: string[];
  onChange: (chain: string[]) => void;
  /** Names the server already resolved, for approvers the member list does not show. */
  knownNames?: Record<string, string | null>;
  /** People who may not approve this one (the requester); left out of the choice. */
  excluded?: string[];
  disabled?: boolean;
  idPrefix: string;
}

/**
 * Pick designated approvers in order. Only project members are offered; the
 * server still checks that each one holds the approval permission.
 */
export function ApproverChainEditor({
  projectId,
  value,
  onChange,
  knownNames,
  excluded = [],
  disabled,
  idPrefix,
}: ApproverChainEditorProps) {
  const { t } = useTranslation();
  const { data: members = [], isLoading } = useProjectMembers(projectId);
  const [adding, setAdding] = useState('');
  const nameOf = (id: string) =>
    members.find((m) => m.user_id === id)?.full_name || members.find((m) => m.user_id === id)?.email || knownNames?.[id] || id.slice(0, 8);
  const choices = members.filter((m) => !value.includes(m.user_id) && !excluded.includes(m.user_id));
  const move = (index: number) => {
    if (index <= 0) return;
    const next = [...value];
    [next[index - 1], next[index]] = [next[index]!, next[index - 1]!];
    onChange(next);
  };
  return (
    <div className="space-y-2">
      {value.length === 0 ? (
        <p className="text-xs text-content-tertiary">
          {t('procurement.requisitions.approvers_none', {
            defaultValue: 'No designated approvers: anyone allowed to approve requisitions decides in one step.',
          })}
        </p>
      ) : (
        <ol className="space-y-1">
          {value.map((id, index) => (
            <li key={id} className="flex items-center gap-2 text-sm">
              <span className="w-5 text-right tabular-nums text-content-tertiary">{index + 1}.</span>
              <span className="flex-1 text-content-primary">{nameOf(id)}</span>
              {!disabled && (
                <>
                  <button
                    type="button"
                    className="text-content-tertiary hover:text-content-primary disabled:opacity-30"
                    aria-label={t('procurement.requisitions.approver_move_up', { defaultValue: 'Move up' })}
                    disabled={index === 0}
                    onClick={() => move(index)}
                  >
                    <ArrowUp size={14} />
                  </button>
                  <button
                    type="button"
                    className="text-content-tertiary hover:text-semantic-error"
                    aria-label={t('procurement.requisitions.approver_remove', { defaultValue: 'Remove approver' })}
                    onClick={() => onChange(value.filter((v) => v !== id))}
                  >
                    <Trash2 size={14} />
                  </button>
                </>
              )}
            </li>
          ))}
        </ol>
      )}
      {!disabled && value.length < 10 && (
        <div className="flex items-center gap-2">
          <select
            id={`${idPrefix}-add-approver`}
            aria-label={t('procurement.requisitions.approver_add_label', { defaultValue: 'Approver to add' })}
            className={smallFieldCls}
            value={adding}
            disabled={isLoading || choices.length === 0}
            onChange={(e) => setAdding(e.target.value)}
          >
            <option value="">
              {isLoading
                ? t('procurement.requisitions.approver_loading', { defaultValue: 'Loading project members' })
                : t('procurement.requisitions.approver_pick', { defaultValue: 'Choose a project member' })}
            </option>
            {choices.map((m) => (
              <option key={m.user_id} value={m.user_id}>
                {m.full_name || m.email}
              </option>
            ))}
          </select>
          <Button
            size="sm"
            variant="secondary"
            icon={<Plus size={14} />}
            disabled={!adding}
            onClick={() => {
              onChange([...value, adding]);
              setAdding('');
            }}
          >
            {t('procurement.requisitions.approver_add', { defaultValue: 'Add' })}
          </Button>
        </div>
      )}
    </div>
  );
}

const STEP_VARIANT: Record<RequisitionApprovalStep['state'], BadgeVariant> = {
  approved: 'success',
  next: 'warning',
  waiting: 'neutral',
};

function stepLabel(t: Translate, state: RequisitionApprovalStep['state']): string {
  switch (state) {
    case 'approved':
      return t('procurement.requisitions.step_approved', { defaultValue: 'Approved' });
    case 'next':
      return t('procurement.requisitions.step_next', { defaultValue: 'Decides now' });
    case 'waiting':
      return t('procurement.requisitions.step_waiting', { defaultValue: 'Waiting' });
  }
}

/** The designated approvers of a requisition and how far they have got. */
export function ApprovalChainView({ steps }: { steps: RequisitionApprovalStep[] }) {
  const { t } = useTranslation();
  if (!steps.length) return null;
  return (
    <ol className="space-y-1 text-sm">
      {steps.map((s, index) => (
        <li key={`${s.user_id}-${index}`} className="flex flex-wrap items-center gap-2">
          <span className="w-5 text-right tabular-nums text-content-tertiary">{index + 1}.</span>
          <span className="text-content-primary">{s.name || s.user_id.slice(0, 8)}</span>
          <Badge variant={STEP_VARIANT[s.state]} size="sm">
            {stepLabel(t, s.state)}
          </Badge>
          {s.decided_at && (
            <span className="text-xs text-content-tertiary">
              <DateDisplay value={s.decided_at} />
            </span>
          )}
          {s.comment && <span className="text-xs text-content-secondary">{s.comment}</span>}
        </li>
      ))}
    </ol>
  );
}

/* ── Order progress per line ────────────────────────────────────────────── */

/** Warnings and external order lines under a requisition line. */
export function LineOrderFlags({ line }: { line: RequisitionLine }) {
  const { t } = useTranslation();
  const mismatched = (line.po_items ?? []).filter((p) => p.unit_mismatch && p.po_status !== 'cancelled');
  const externalMismatch = (line.external_orders ?? []).filter((e) => e.unit_mismatch && e.status !== 'cancelled');
  return (
    <>
      {(line.external_orders ?? []).map((e) => (
        <div key={e.id} className="mt-0.5 text-content-secondary">
          {t('procurement.requisitions.external_line_ref', {
            defaultValue: '{{system}} {{number}}: {{quantity}} {{unit}}',
            system: e.external_system,
            number: e.external_line_ref ? `${e.external_order_number}/${e.external_line_ref}` : e.external_order_number,
            quantity: e.quantity_ordered,
            unit: e.unit ?? line.unit ?? '',
          })}{' '}
          <span className="text-content-tertiary">({externalStatusLabel(t, e.status)})</span>
        </div>
      ))}
      {line.over_ordered && (
        <div className="mt-0.5 flex items-center gap-1 text-semantic-warning">
          <AlertTriangle size={12} />
          {t('procurement.requisitions.over_ordered', { defaultValue: 'More on order than requested' })}
        </div>
      )}
      {(mismatched.length > 0 || externalMismatch.length > 0) && (
        <div className="mt-0.5 flex items-center gap-1 text-semantic-warning">
          <AlertTriangle size={12} />
          {t('procurement.requisitions.unit_mismatch', {
            defaultValue: 'An order line is in a unit that cannot be converted, so it is not counted',
          })}
        </div>
      )}
    </>
  );
}

function externalStatusLabel(t: Translate, status: ExternalOrderStatus): string {
  switch (status) {
    case 'open':
      return t('procurement.requisitions.external_status_open', { defaultValue: 'Open' });
    case 'confirmed':
      return t('procurement.requisitions.external_status_confirmed', { defaultValue: 'Confirmed' });
    case 'partially_received':
      return t('procurement.requisitions.external_status_partially_received', { defaultValue: 'Partly received' });
    case 'received':
      return t('procurement.requisitions.external_status_received', { defaultValue: 'Received' });
    case 'cancelled':
      return t('procurement.requisitions.external_status_cancelled', { defaultValue: 'Cancelled' });
  }
}

/** The purchase orders raised from a requisition. */
export function RequisitionOrderList({ req }: { req: Requisition }) {
  const { t } = useTranslation();
  const orders = req.purchase_orders ?? [];
  if (!orders.length) return null;
  return (
    <div className="text-sm text-content-secondary">
      <span className="mr-2 font-medium">
        {t('procurement.requisitions.orders_title', { defaultValue: 'Purchase orders' })}:
      </span>
      {orders.map((o, index) => (
        <span key={o.po_id} className={o.status === 'cancelled' ? 'text-content-tertiary line-through' : undefined}>
          {index > 0 ? ', ' : ''}
          <span className="font-mono text-xs">{o.po_number ?? o.po_id.slice(0, 8)}</span>
        </span>
      ))}
      {req.order_progress === 'partial' && (
        <span className="ml-2">
          <Badge variant="warning" size="sm">
            {t('procurement.requisitions.partly_ordered', { defaultValue: 'Partly ordered' })}
          </Badge>
        </span>
      )}
    </div>
  );
}

/* ── Convert: per-line quantities ───────────────────────────────────────── */

interface ConvertLinesTableProps {
  requisitions: Requisition[];
  chosen: Record<string, string>;
  onChange: (itemId: string, quantity: string) => void;
}

/** What each line puts on the new order; it starts at what is still to order. */
export function ConvertLinesTable({ requisitions, chosen, onChange }: ConvertLinesTableProps) {
  const { t } = useTranslation();
  const rows = requisitions.flatMap((r) =>
    r.items
      .filter((i) => isPositiveDecimal(i.quantity_to_order ?? i.quantity_outstanding))
      .map((i) => ({ req: r, item: i })),
  );
  if (!rows.length) return null;
  return (
    <div className="max-h-72 overflow-auto rounded-lg border border-border-light">
      <table className="w-full text-xs">
        <thead>
          <tr className="border-b border-border-light text-left uppercase tracking-wide text-content-tertiary">
            <th className="px-2 py-1.5 font-medium">{t('procurement.requisitions.col_number', { defaultValue: 'Number' })}</th>
            <th className="px-2 py-1.5 font-medium">{t('procurement.requisitions.col_material', { defaultValue: 'Material' })}</th>
            <th className="px-2 py-1.5 text-right font-medium">
              {t('procurement.requisitions.col_to_order', { defaultValue: 'Still to order' })}
            </th>
            <th className="px-2 py-1.5 text-right font-medium">
              {t('procurement.requisitions.col_order_now', { defaultValue: 'Order now' })}
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map(({ req, item }) => {
            const value = chosen[item.id] ?? item.quantity_to_order ?? '';
            const invalid = value.trim() !== '' && !/^\d+(\.\d+)?$/.test(value.trim());
            return (
              <tr key={item.id} className="border-b border-border-light/60 last:border-0">
                <td className="px-2 py-1 font-mono text-content-tertiary">{req.req_number ?? req.id.slice(0, 8)}</td>
                <td className="px-2 py-1 text-content-primary">{item.description}</td>
                <td className="px-2 py-1 text-right tabular-nums">
                  <QuantityDisplay value={item.quantity_to_order ?? '0'} unit={item.unit ?? ''} precision={2} />
                </td>
                <td className="px-2 py-1 text-right">
                  <input
                    className={`${smallFieldCls} w-28 text-right ${invalid ? 'border-semantic-error' : ''}`}
                    inputMode="decimal"
                    aria-label={t('procurement.requisitions.order_now_for', {
                      defaultValue: 'Quantity to order now for {{line}}',
                      line: item.description,
                    })}
                    value={value}
                    onChange={(e) => onChange(item.id, e.target.value)}
                  />
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

/* ── External order report ──────────────────────────────────────────────── */

interface ExternalLineDraft {
  include: boolean;
  ref: string;
  status: ExternalOrderStatus;
  ordered: string;
  received: string;
  unit: string;
  confirmed: string;
}

interface ExternalOrderModalProps {
  req: Requisition;
  open: boolean;
  onClose: () => void;
  onSaved: (updated: Requisition) => void;
}

/**
 * Record an order placed in the external purchasing system. Reporting the
 * same order line again updates it; nothing here creates a purchase order.
 */
export function ExternalOrderModal({ req, open, onClose, onSaved }: ExternalOrderModalProps) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const [system, setSystem] = useState('');
  const [orderNumber, setOrderNumber] = useState('');
  const [drafts, setDrafts] = useState<Record<string, ExternalLineDraft>>({});

  useEffect(() => {
    if (!open) return;
    setSystem('');
    setOrderNumber('');
    setDrafts(
      Object.fromEntries(
        req.items.map((i) => [
          i.id,
          {
            include: isPositiveDecimal(i.quantity_to_order),
            ref: '',
            status: 'open' as ExternalOrderStatus,
            ordered: i.quantity_to_order ?? '',
            received: '0',
            unit: i.unit ?? '',
            confirmed: '',
          },
        ]),
      ),
    );
    // Reset on opening or on another requisition only, so a refetch keeps what was typed.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, req.id]);

  const lines = useMemo(
    () =>
      req.items.flatMap((i) => {
        const d = drafts[i.id];
        if (!d || !d.include) return [];
        return [
          {
            requisition_item_id: i.id,
            external_line_ref: d.ref.trim(),
            status: d.status,
            quantity_ordered: d.ordered.trim(),
            quantity_received: d.received.trim() || '0',
            unit: d.unit.trim() || null,
            confirmed_delivery_date: d.confirmed || null,
          },
        ];
      }),
    [drafts, req.items],
  );
  const valid =
    system.trim().length > 0 &&
    orderNumber.trim().length > 0 &&
    lines.length > 0 &&
    lines.every((l) => /^\d+(\.\d+)?$/.test(l.quantity_ordered) && /^\d+(\.\d+)?$/.test(l.quantity_received));

  const save = useMutation({
    mutationFn: () =>
      reportExternalOrder(req.id, {
        external_system: system.trim(),
        external_order_number: orderNumber.trim(),
        lines,
      }),
    onSuccess: (updated) => {
      addToast({
        type: 'success',
        title: t('procurement.requisitions.external_saved', { defaultValue: 'External order recorded' }),
      });
      onSaved(updated);
    },
    onError: (e: unknown) =>
      addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: getErrorMessage(e) }),
  });

  const patch = (id: string, p: Partial<ExternalLineDraft>) =>
    setDrafts((prev) => ({ ...prev, [id]: { ...prev[id]!, ...p } }));

  return (
    <WideModal
      open={open}
      onClose={onClose}
      busy={save.isPending}
      size="xl"
      title={t('procurement.requisitions.external_title', { defaultValue: 'Record external order' })}
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={save.isPending}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button onClick={() => save.mutate()} disabled={!valid || save.isPending}>
            {save.isPending && <Loader2 size={14} className="mr-1 animate-spin" />}
            {t('procurement.requisitions.external_save', { defaultValue: 'Record order' })}
          </Button>
        </>
      }
    >
      <div className="space-y-3 text-sm">
        <p className="text-content-secondary">
          {t('procurement.requisitions.external_intro', {
            defaultValue:
              'This project orders in an external purchasing system. Enter its order here so requested, ordered and received quantities reconcile. No purchase order is created in this project.',
          })}
        </p>
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="block text-xs font-medium text-content-secondary">
            {t('procurement.requisitions.external_system', { defaultValue: 'System' })}
            <input className={`${fieldCls} mt-1`} value={system} maxLength={100} onChange={(e) => setSystem(e.target.value)} />
          </label>
          <label className="block text-xs font-medium text-content-secondary">
            {t('procurement.requisitions.external_order_number', { defaultValue: 'Order number' })}
            <input
              className={`${fieldCls} mt-1`}
              value={orderNumber}
              maxLength={100}
              onChange={(e) => setOrderNumber(e.target.value)}
            />
          </label>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[48rem] text-xs">
            <thead>
              <tr className="border-b border-border-light text-left uppercase tracking-wide text-content-tertiary">
                <th className="w-8 py-1.5" />
                <th className="py-1.5 pr-2 font-medium">{t('procurement.requisitions.col_material', { defaultValue: 'Material' })}</th>
                <th className="py-1.5 pr-2 font-medium">{t('procurement.requisitions.external_line', { defaultValue: 'Line' })}</th>
                <th className="py-1.5 pr-2 font-medium">{t('procurement.requisitions.col_status', { defaultValue: 'Status' })}</th>
                <th className="py-1.5 pr-2 text-right font-medium">{t('procurement.requisitions.col_ordered', { defaultValue: 'Ordered' })}</th>
                <th className="py-1.5 pr-2 text-right font-medium">{t('procurement.requisitions.col_received', { defaultValue: 'Received' })}</th>
                <th className="py-1.5 pr-2 font-medium">{t('procurement.requisitions.col_unit', { defaultValue: 'Unit' })}</th>
                <th className="py-1.5 pr-2 font-medium">
                  {t('procurement.requisitions.external_confirmed', { defaultValue: 'Confirmed delivery' })}
                </th>
              </tr>
            </thead>
            <tbody>
              {req.items.map((i) => {
                const d = drafts[i.id];
                if (!d) return null;
                return (
                  <tr key={i.id} className="border-b border-border-light/60 last:border-0">
                    <td className="py-1">
                      <input
                        type="checkbox"
                        aria-label={t('procurement.requisitions.external_include', {
                          defaultValue: 'Include {{line}}',
                          line: i.description,
                        })}
                        checked={d.include}
                        onChange={(e) => patch(i.id, { include: e.target.checked })}
                      />
                    </td>
                    <td className="py-1 pr-2 text-content-primary">{i.description}</td>
                    <td className="py-1 pr-2">
                      <input
                        className={`${smallFieldCls} w-16`}
                        aria-label={`${t('procurement.requisitions.external_line', { defaultValue: 'Line' })}: ${i.description}`}
                        value={d.ref}
                        maxLength={100}
                        disabled={!d.include}
                        onChange={(e) => patch(i.id, { ref: e.target.value })}
                      />
                    </td>
                    <td className="py-1 pr-2">
                      <select
                        className={smallFieldCls}
                        aria-label={`${t('procurement.requisitions.col_status', { defaultValue: 'Status' })}: ${i.description}`}
                        value={d.status}
                        disabled={!d.include}
                        onChange={(e) => patch(i.id, { status: e.target.value as ExternalOrderStatus })}
                      >
                        {EXTERNAL_ORDER_STATUSES.map((s) => (
                          <option key={s} value={s}>
                            {externalStatusLabel(t, s)}
                          </option>
                        ))}
                      </select>
                    </td>
                    <td className="py-1 pr-2">
                      <input
                        className={`${smallFieldCls} w-24 text-right`}
                        inputMode="decimal"
                        aria-label={`${t('procurement.requisitions.col_ordered', { defaultValue: 'Ordered' })}: ${i.description}`}
                        value={d.ordered}
                        disabled={!d.include}
                        onChange={(e) => patch(i.id, { ordered: e.target.value })}
                      />
                    </td>
                    <td className="py-1 pr-2">
                      <input
                        className={`${smallFieldCls} w-24 text-right`}
                        inputMode="decimal"
                        aria-label={`${t('procurement.requisitions.col_received', { defaultValue: 'Received' })}: ${i.description}`}
                        value={d.received}
                        disabled={!d.include}
                        onChange={(e) => patch(i.id, { received: e.target.value })}
                      />
                    </td>
                    <td className="py-1 pr-2">
                      <input
                        className={`${smallFieldCls} w-16`}
                        aria-label={`${t('procurement.requisitions.col_unit', { defaultValue: 'Unit' })}: ${i.description}`}
                        value={d.unit}
                        maxLength={20}
                        disabled={!d.include}
                        onChange={(e) => patch(i.id, { unit: e.target.value })}
                      />
                    </td>
                    <td className="py-1 pr-2">
                      <input
                        type="date"
                        className={smallFieldCls}
                        aria-label={`${t('procurement.requisitions.external_confirmed', { defaultValue: 'Confirmed delivery' })}: ${i.description}`}
                        value={d.confirmed}
                        disabled={!d.include}
                        onChange={(e) => patch(i.id, { confirmed: e.target.value })}
                      />
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    </WideModal>
  );
}

/* ── Project settings ───────────────────────────────────────────────────── */

interface SettingsModalProps {
  projectId: string;
  open: boolean;
  onClose: () => void;
}

/** Where the project orders, and who approves new requisitions by default. */
export function ProcurementSettingsModal({ projectId, open, onClose }: SettingsModalProps) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const { data, isLoading } = useQuery({
    queryKey: ['procurement-settings', projectId],
    queryFn: () => getProcurementSettings(projectId),
    enabled: open,
  });
  const [owner, setOwner] = useState<OrderOwner>('ocerp');
  const [chain, setChain] = useState<string[]>([]);

  useEffect(() => {
    if (!open || !data) return;
    setOwner(data.order_owner);
    setChain(data.default_approvers.map((a) => a.user_id));
  }, [open, data]);

  const save = useMutation({
    mutationFn: () => updateProcurementSettings(projectId, { order_owner: owner, default_approval_chain: chain }),
    onSuccess: (saved) => {
      queryClient.setQueryData(['procurement-settings', projectId], saved);
      addToast({
        type: 'success',
        title: t('procurement.requisitions.settings_saved', { defaultValue: 'Requisition settings saved' }),
      });
      onClose();
    },
    onError: (e: unknown) =>
      addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: getErrorMessage(e) }),
  });

  const names = Object.fromEntries((data?.default_approvers ?? []).map((a) => [a.user_id, a.name]));
  return (
    <WideModal
      open={open}
      onClose={onClose}
      busy={save.isPending}
      size="md"
      title={t('procurement.requisitions.settings_title', { defaultValue: 'Requisition settings' })}
      footer={
        <>
          <Button variant="secondary" icon={<X size={14} />} onClick={onClose} disabled={save.isPending}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button onClick={() => save.mutate()} disabled={isLoading || !data || save.isPending}>
            {save.isPending && <Loader2 size={14} className="mr-1 animate-spin" />}
            {t('common.save', { defaultValue: 'Save' })}
          </Button>
        </>
      }
    >
      {isLoading || !data ? (
        <Loader2 size={18} className="animate-spin text-content-tertiary" />
      ) : (
        <div className="space-y-4 text-sm">
          <label className="block text-xs font-medium text-content-secondary" htmlFor="settings-owner">
            {t('procurement.requisitions.field_order_owner', { defaultValue: 'Orders are placed in' })}
          </label>
          <OrderOwnerSelect id="settings-owner" value={owner} onChange={setOwner} />
          <p className="text-xs text-content-tertiary">
            {t('procurement.requisitions.settings_owner_hint', {
              defaultValue:
                'With an external system, requisitions are not turned into purchase orders here and tender or RFQ awards draft no order. Existing requisitions keep the setting they were created with.',
            })}
          </p>
          <div>
            <p className="mb-1 text-xs font-medium text-content-secondary">
              {t('procurement.requisitions.settings_approvers', { defaultValue: 'Default approvers for new requisitions' })}
            </p>
            <ApproverChainEditor
              projectId={projectId}
              value={chain}
              onChange={setChain}
              knownNames={names}
              idPrefix="settings"
            />
          </div>
        </div>
      )}
    </WideModal>
  );
}
