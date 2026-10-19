// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// RequisitionsTab - the project's material requisitions inside Procurement.
//
// A requisition is a request for material, not an order. The list shows each
// one with its status and how much of what was requested has been ordered and
// received. Opening one shows its lines with the BOQ positions they came from;
// a draft can be edited (header, quantities, explicit line merge) and
// submitted, a submitted one withdrawn back to draft, and either cancelled.
// Submitting never approves: with no approval configured it waits in
// "submitted", and the requisition rules run first.
//
// Approval is a separate person's act: a manager approves (comment optional)
// or rejects (reason required), and the submitter cannot decide their own.
// Approved requisitions are selected in the list and turned into one draft
// purchase order at project level; each PO line remembers the requisition
// line, and through it the BOQ positions, it came from.
//
// Each line also shows its suggested supplier and its own needed-by date,
// which RequisitionSupply renders (issue #516).
//
// Designated approvers decide in order, a line can be ordered in parts over
// several orders, and a project that orders in an external purchasing system
// records those orders instead of converting; RequisitionOrdering renders
// those parts.

import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ClipboardList, Loader2, GitMerge, Send, Undo2, Ban, Trash2, Check, X, ShoppingCart, Settings, ExternalLink } from 'lucide-react';
import { Badge, Button, Card, EmptyState, SkeletonTable, WideModal, type BadgeVariant } from '@/shared/ui';
import { DateDisplay } from '@/shared/ui/DateDisplay';
import { QuantityDisplay } from '@/shared/ui/QuantityDisplay';
import { apiGet, getErrorMessage } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import { useAuthStore } from '@/stores/useAuthStore';
import { ROLE_RANK, normalizeRole } from '@/shared/lib/roles';
import {
  REQUISITION_STATUSES,
  approveRequisition,
  canConvertTogether,
  convertRequisitionsToPurchaseOrder,
  rejectRequisition,
  cancelRequisition,
  getRequisition,
  lineToInput,
  listRequisitions,
  mergeRequisitionLines,
  newIdempotencyKey,
  parseRequisitionRuleErrors,
  plannedConvertLines,
  submitRequisition,
  updateRequisition,
  withdrawRequisition,
  type ConvertBlockReason,
  type OrderOwner,
  type Requisition,
  type RequisitionLineIn,
  type RequisitionRuleError,
  type RequisitionStatus,
} from './requisitionsApi';
import { fmtList } from '@/shared/lib/formatters';
import { LineSupplyCell, SuggestedSupplierHint, VendorSelect } from './RequisitionSupply';
import {
  ApprovalChainView,
  ApproverChainEditor,
  ConvertLinesTable,
  ExternalOrderModal,
  LineOrderFlags,
  OrderOwnerSelect,
  ProcurementSettingsModal,
  RequisitionOrderList,
  orderOwnerLabel,
} from './RequisitionOrdering';

const fieldCls =
  'h-9 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';

const STATUS_VARIANT: Record<RequisitionStatus, BadgeVariant> = {
  draft: 'neutral',
  submitted: 'warning',
  approved: 'blue',
  ordered: 'purple',
  received: 'success',
  consumed: 'success',
  rejected: 'error',
  cancelled: 'error',
};

const STATUS_DEFAULT: Record<RequisitionStatus, string> = {
  draft: 'Draft',
  submitted: 'Submitted',
  approved: 'Approved',
  ordered: 'Ordered',
  received: 'Received',
  consumed: 'Consumed',
  rejected: 'Rejected',
  cancelled: 'Cancelled',
};

/**
 * The one unit every line of a requisition shares, or null when they differ.
 * Header totals are only shown under a shared unit: summing tonnes and cubic
 * metres gives a number that means nothing.
 */
function sharedUnit(req: Requisition): string | null {
  const units = new Set(req.items.map((i) => (i.unit ?? '').trim()));
  if (units.size !== 1) return null;
  return [...units][0] ?? null;
}

function HeaderQuantity({ req, value }: { req: Requisition; value: string | undefined }) {
  const unit = sharedUnit(req);
  if (unit === null) return <>-</>;
  return <QuantityDisplay value={value ?? '0'} unit={unit} precision={2} />;
}

function StatusBadge({ status }: { status: RequisitionStatus }) {
  const { t } = useTranslation();
  return (
    <Badge variant={STATUS_VARIANT[status] ?? 'neutral'} size="sm">
      {t(`procurement.requisitions.status.${status}`, { defaultValue: STATUS_DEFAULT[status] ?? status })}
    </Badge>
  );
}

function RuleErrorList({ errors, title }: { errors: RequisitionRuleError[]; title: string }) {
  if (!errors.length) return null;
  return (
    <div role="alert" className="rounded-lg border border-semantic-error/40 bg-semantic-error/5 p-3 text-sm">
      <p className="mb-1 font-medium text-semantic-error">{title}</p>
      <ul className="list-disc space-y-1 pl-5 text-content-secondary">
        {errors.map((e, i) => (
          <li key={`${e.rule_id}-${i}`}>
            {e.message}
            {e.suggestion ? <span className="text-content-tertiary"> - {e.suggestion}</span> : null}
          </li>
        ))}
      </ul>
    </div>
  );
}

type Translate = ReturnType<typeof useTranslation>['t'];

/** Why a selection cannot be ordered, each key written out so the locale gates can see it. */
function convertBlockMessage(t: Translate, reason: ConvertBlockReason): string {
  switch (reason) {
    case 'empty':
      return t('procurement.requisitions.convert_blocked_empty', {
        defaultValue: 'Select at least one approved requisition.',
      });
    case 'not_approved':
      return t('procurement.requisitions.convert_blocked_not_approved', {
        defaultValue: 'Only approved requisitions can be ordered.',
      });
    case 'mixed_projects':
      return t('procurement.requisitions.convert_blocked_mixed_projects', {
        defaultValue: 'The selected requisitions belong to different projects.',
      });
    case 'vendor_conflict':
      return t('procurement.requisitions.convert_blocked_vendor_conflict', {
        defaultValue: 'The selected requisitions name different vendors. Order them separately.',
      });
    case 'external_owner':
      return t('procurement.requisitions.convert_blocked_external', {
        defaultValue: 'A selected requisition is ordered in an external purchasing system. Record its external order on the requisition instead.',
      });
  }
}

export const APPROVE_REQUISITION_PERMISSION = 'procurement.approve_requisition';

/**
 * Whether to offer Approve and Reject. The server decides (it refuses the
 * submitter with a 403 and needs `procurement.approve_requisition`); this only
 * stops offering a button that is certain to fail. When the caller's
 * permission list from `/v1/users/me/` is known it is the answer, otherwise
 * the role rank stands in until it loads.
 */
export function canOfferDecision(
  req: Pick<Requisition, 'status' | 'submitted_by'> & Pick<Partial<Requisition>, 'next_approver_id'>,
  userId: string | null,
  userRole: string | null,
  permissions?: readonly string[] | null,
): boolean {
  if (req.status !== 'submitted') return false;
  if (userId && req.submitted_by && req.submitted_by === userId) return false;
  // With designated approvers only the next one in the chain decides.
  if (req.next_approver_id && req.next_approver_id !== userId) return false;
  if (Array.isArray(permissions)) {
    return normalizeRole(userRole) === 'admin' || permissions.includes(APPROVE_REQUISITION_PERMISSION);
  }
  const rank = (ROLE_RANK as Record<string, number>)[normalizeRole(userRole)];
  return rank !== undefined && rank >= ROLE_RANK.manager;
}

interface ConvertModalProps {
  projectId: string;
  requisitions: Requisition[];
  open: boolean;
  onClose: () => void;
  onConverted: () => void;
}

/** Turn the selected approved requisitions into one draft purchase order. */
export function ConvertToPOModal({ projectId, requisitions, open, onClose, onConverted }: ConvertModalProps) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const check = canConvertTogether(requisitions);
  const [vendorId, setVendorId] = useState('');
  const [deliveryDate, setDeliveryDate] = useState('');
  const [ruleErrors, setRuleErrors] = useState<RequisitionRuleError[]>([]);
  const [chosen, setChosen] = useState<Record<string, string>>({});
  // One key per opening: a double click or a retry after a lost answer is one order.
  const [idempotencyKey, setIdempotencyKey] = useState('');

  useEffect(() => {
    if (!open) return;
    setVendorId(check.vendorId ?? '');
    setDeliveryDate('');
    setRuleErrors([]);
    setChosen({});
    setIdempotencyKey(newIdempotencyKey());
  }, [open, check.vendorId]);

  const plannedLines = plannedConvertLines(requisitions, chosen);
  const invalidQuantity = Object.values(chosen).some((v) => v.trim() !== '' && !/^\d+(\.\d+)?$/.test(v.trim()));

  const convert = useMutation({
    mutationFn: () =>
      convertRequisitionsToPurchaseOrder({
        project_id: projectId,
        requisition_ids: requisitions.map((r) => r.id),
        vendor_id: vendorId || null,
        delivery_date: deliveryDate || null,
        lines: plannedLines,
        idempotency_key: idempotencyKey || null,
      }),
    onSuccess: (res) => {
      queryClient.invalidateQueries({ queryKey: ['procurement-requisitions', projectId] });
      queryClient.invalidateQueries({ queryKey: ['procurement-requisition'] });
      queryClient.invalidateQueries({ queryKey: ['procurement-po', projectId] });
      addToast({
        type: 'success',
        title: t('procurement.requisitions.convert_done', {
          defaultValue: 'Purchase order {{number}} created as a draft.',
          number: res.po_number,
        }),
      });
      onConverted();
    },
    onError: (e: unknown) => {
      const errors = parseRequisitionRuleErrors(e);
      setRuleErrors(errors);
      if (!errors.length) {
        addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: getErrorMessage(e) });
      }
    },
  });

  const lineCount = plannedLines ? plannedLines.length : requisitions.reduce((n, r) => n + r.items.length, 0);
  const blocked = !check.ok || invalidQuantity || (plannedLines !== undefined && plannedLines.length === 0);
  return (
    <WideModal
      open={open}
      onClose={onClose}
      busy={convert.isPending}
      size="lg"
      title={t('procurement.requisitions.convert_title', { defaultValue: 'Create purchase order' })}
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={convert.isPending}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button
            icon={<ShoppingCart size={14} />}
            onClick={() => convert.mutate()}
            disabled={blocked || !vendorId || convert.isPending}
          >
            {convert.isPending && <Loader2 size={14} className="mr-1 animate-spin" />}
            {t('procurement.requisitions.convert_confirm', { defaultValue: 'Create draft order' })}
          </Button>
        </>
      }
    >
      <div className="space-y-3 text-sm">
        <p className="text-content-secondary">
          {t('procurement.requisitions.convert_summary', {
            defaultValue:
              'Requisitions {{numbers}} become one draft purchase order (order lines: {{lines}}). Each line keeps its quantity, unit and the BOQ positions it came from.',
            numbers: fmtList(requisitions.map((r) => r.req_number ?? r.id.slice(0, 8))),
            lines: lineCount,
          })}
        </p>
        {blocked && check.reason && (
          <p role="alert" className="text-semantic-error">
            {convertBlockMessage(t, check.reason)}
          </p>
        )}
        {check.ok && (
          <>
            <p className="text-xs text-content-tertiary">
              {t('procurement.requisitions.convert_lines_hint', {
                defaultValue:
                  'Each line starts at what is still to order. Lower a quantity to order part of it now, or clear it to leave the line for a later order.',
              })}
            </p>
            <ConvertLinesTable
              requisitions={requisitions}
              chosen={chosen}
              onChange={(id, quantity) => setChosen((prev) => ({ ...prev, [id]: quantity }))}
            />
          </>
        )}
        <label className="block text-xs font-medium text-content-secondary" htmlFor="convert-vendor">
          {t('procurement.requisitions.field_vendor', { defaultValue: 'Vendor' })}
        </label>
        <VendorSelect
          id="convert-vendor"
          value={vendorId}
          onChange={setVendorId}
          disabled={blocked}
          fallbackName={requisitions.find((r) => r.vendor_id === vendorId)?.vendor_name}
        />
        <label className="block text-xs font-medium text-content-secondary">
          {t('procurement.requisitions.convert_delivery', { defaultValue: 'Delivery date (optional)' })}
          <input
            type="date"
            className={`${fieldCls} mt-1`}
            value={deliveryDate}
            onChange={(e) => setDeliveryDate(e.target.value)}
          />
        </label>
        <RuleErrorList
          errors={ruleErrors}
          title={t('procurement.requisitions.convert_rules_failed', {
            defaultValue: 'The purchase order was not created:',
          })}
        />
      </div>
    </WideModal>
  );
}

interface DecisionModalProps {
  mode: 'approve' | 'reject' | null;
  busy: boolean;
  onClose: () => void;
  onConfirm: (comment: string) => void;
}

/** Approve with an optional comment, or reject with a required reason. */
export function DecisionModal({ mode, busy, onClose, onConfirm }: DecisionModalProps) {
  const { t } = useTranslation();
  const [comment, setComment] = useState('');
  useEffect(() => {
    if (mode) setComment('');
  }, [mode]);
  const isReject = mode === 'reject';
  const canConfirm = !busy && (!isReject || comment.trim().length > 0);
  return (
    <WideModal
      open={mode !== null}
      onClose={onClose}
      busy={busy}
      size="sm"
      title={
        isReject
          ? t('procurement.requisitions.reject_title', { defaultValue: 'Reject requisition' })
          : t('procurement.requisitions.approve_title', { defaultValue: 'Approve requisition' })
      }
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={busy}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button
            variant={isReject ? 'danger' : 'primary'}
            icon={isReject ? <X size={14} /> : <Check size={14} />}
            onClick={() => onConfirm(comment)}
            disabled={!canConfirm}
          >
            {isReject
              ? t('procurement.requisitions.reject', { defaultValue: 'Reject' })
              : t('procurement.requisitions.approve', { defaultValue: 'Approve' })}
          </Button>
        </>
      }
    >
      <label className="block text-xs font-medium text-content-secondary">
        {isReject
          ? t('procurement.requisitions.reject_reason', { defaultValue: 'Reason (required)' })
          : t('procurement.requisitions.approve_comment', { defaultValue: 'Comment (optional)' })}
        <textarea
          className="mt-1 min-h-[4rem] w-full rounded-lg border border-border bg-surface-primary px-3 py-2 text-sm"
          value={comment}
          maxLength={2000}
          onChange={(e) => setComment(e.target.value)}
        />
      </label>
    </WideModal>
  );
}

interface RequisitionsTabProps {
  projectId: string;
  /** `?requisition=<id>` opens that requisition on arrival (the buy-list hand-off). */
  focusRequisitionId?: string | null;
}

export function RequisitionsTab({ projectId, focusRequisitionId }: RequisitionsTabProps) {
  const { t } = useTranslation();
  const [statusFilter, setStatusFilter] = useState<RequisitionStatus | ''>('');
  const [openId, setOpenId] = useState<string | null>(focusRequisitionId ?? null);
  const [picked, setPicked] = useState<string[]>([]);
  const [converting, setConverting] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const userRole = useAuthStore((s) => s.userRole);
  // The server decides (procurement.manage_settings, manager and above); this only hides a button certain to fail.
  const canManageSettings = ((ROLE_RANK as Record<string, number>)[normalizeRole(userRole)] ?? 0) >= ROLE_RANK.manager;

  useEffect(() => {
    if (focusRequisitionId) setOpenId(focusRequisitionId);
  }, [focusRequisitionId]);

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ['procurement-requisitions', projectId, statusFilter],
    queryFn: () => listRequisitions(projectId, statusFilter),
  });

  const pickedReqs = useMemo(
    () => (data?.items ?? []).filter((r) => picked.includes(r.id) && r.status === 'approved'),
    [data, picked],
  );
  const pickCheck = canConvertTogether(pickedReqs);

  if (isLoading) return <SkeletonTable rows={5} columns={6} />;

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm text-content-secondary">
          {t('procurement.requisitions.intro', {
            defaultValue:
              'Requests for material, raised from the buy-list or by hand. A request is not an order: purchasing takes it from here.',
          })}
        </p>
        <div className="flex items-center gap-2">
        {canManageSettings && (
          <Button size="sm" variant="secondary" icon={<Settings size={14} />} onClick={() => setSettingsOpen(true)}>
            {t('procurement.requisitions.settings', { defaultValue: 'Settings' })}
          </Button>
        )}
        <label className="flex items-center gap-2 text-xs text-content-secondary">
          {t('procurement.requisitions.filter_status', { defaultValue: 'Status' })}
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value as RequisitionStatus | '')}
            className="h-8 rounded-lg border border-border bg-surface-primary px-2 text-sm"
          >
            <option value="">{t('procurement.requisitions.filter_all', { defaultValue: 'All' })}</option>
            {REQUISITION_STATUSES.map((s) => (
              <option key={s} value={s}>
                {t(`procurement.requisitions.status.${s}`, { defaultValue: STATUS_DEFAULT[s] })}
              </option>
            ))}
          </select>
        </label>
        </div>
      </div>

      {(data?.items ?? []).some((r) => r.status === 'approved' && r.order_owner !== 'external') && (
        <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border-light bg-surface-secondary/40 px-3 py-2 text-xs text-content-secondary">
          <span>
            {t('procurement.requisitions.convert_hint', {
              defaultValue: 'Select approved requisitions to order them together in one purchase order.',
            })}
          </span>
          <Button
            size="sm"
            icon={<ShoppingCart size={14} />}
            onClick={() => setConverting(true)}
            disabled={!pickCheck.ok}
            title={
              pickCheck.reason ? convertBlockMessage(t, pickCheck.reason) : undefined
            }
          >
            {t('procurement.requisitions.convert', { defaultValue: 'Create purchase order' })}
          </Button>
        </div>
      )}

      {isError ? (
        <Card padding="sm">
          <div className="flex items-center justify-between gap-2 text-sm text-semantic-error">
            {t('procurement.requisitions.load_error', { defaultValue: 'Could not load the requisitions.' })}
            <Button size="sm" variant="secondary" onClick={() => refetch()}>
              {t('common.retry', { defaultValue: 'Retry' })}
            </Button>
          </div>
        </Card>
      ) : !data || data.items.length === 0 ? (
        <EmptyState
          icon={<ClipboardList className="h-6 w-6" />}
          title={t('procurement.requisitions.empty_title', { defaultValue: 'No requisitions yet' })}
          description={t('procurement.requisitions.empty_description', {
            defaultValue: 'Open the material buy-list in Resource Summary, select materials and create a requisition.',
          })}
        />
      ) : (
        <Card padding="none">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border-light text-left text-2xs uppercase tracking-wide text-content-tertiary">
                  <th className="w-8 px-2 py-2" />
                  <th className="px-4 py-2 font-medium">{t('procurement.requisitions.col_number', { defaultValue: 'Number' })}</th>
                  <th className="px-4 py-2 font-medium">{t('procurement.requisitions.col_title', { defaultValue: 'Title' })}</th>
                  <th className="px-4 py-2 font-medium">{t('procurement.requisitions.col_vendor', { defaultValue: 'Vendor' })}</th>
                  <th className="px-4 py-2 font-medium">{t('procurement.requisitions.col_status', { defaultValue: 'Status' })}</th>
                  <th className="px-4 py-2 font-medium">{t('procurement.requisitions.col_needed_by', { defaultValue: 'Needed by' })}</th>
                  <th className="px-4 py-2 text-right font-medium">{t('procurement.requisitions.col_lines', { defaultValue: 'Lines' })}</th>
                  <th className="px-4 py-2 text-right font-medium">{t('procurement.requisitions.col_requested', { defaultValue: 'Requested' })}</th>
                  <th className="px-4 py-2 text-right font-medium">{t('procurement.requisitions.col_ordered', { defaultValue: 'Ordered' })}</th>
                  <th className="px-4 py-2 text-right font-medium">{t('procurement.requisitions.col_received', { defaultValue: 'Received' })}</th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((r) => (
                  <tr
                    key={r.id}
                    className="cursor-pointer border-b border-border-light/60 last:border-0 hover:bg-surface-secondary"
                    onClick={() => setOpenId(r.id)}
                  >
                    <td className="px-2 py-2" onClick={(e) => e.stopPropagation()}>
                      {r.status === 'approved' && r.order_owner !== 'external' && (
                        <input
                          type="checkbox"
                          aria-label={t('procurement.requisitions.select_for_order', {
                            defaultValue: 'Select {{number}} for a purchase order',
                            number: r.req_number ?? r.id.slice(0, 8),
                          })}
                          checked={picked.includes(r.id)}
                          onChange={(e) =>
                            setPicked((prev) => (e.target.checked ? [...prev, r.id] : prev.filter((id) => id !== r.id)))
                          }
                        />
                      )}
                    </td>
                    <td className="px-4 py-2 font-mono text-xs text-content-primary">
                      <button type="button" className="text-oe-blue hover:underline" onClick={() => setOpenId(r.id)}>
                        {r.req_number ?? r.id.slice(0, 8)}
                      </button>
                    </td>
                    <td className="px-4 py-2 text-content-primary">{r.title || '-'}</td>
                    <td className="px-4 py-2 text-content-secondary">{r.vendor_name || '-'}</td>
                    <td className="px-4 py-2">
                      <StatusBadge status={r.status} />
                      {r.order_progress === 'partial' && r.status === 'approved' && (
                        <span className="ml-1 inline-block">
                          <Badge variant="warning" size="sm">
                            {t('procurement.requisitions.partly_ordered', { defaultValue: 'Partly ordered' })}
                          </Badge>
                        </span>
                      )}
                      {r.po_number && (
                        <span className="ml-2 font-mono text-2xs text-content-tertiary">{r.po_number}</span>
                      )}
                    </td>
                    <td className="px-4 py-2 text-content-secondary">
                      {r.required_date ? <DateDisplay value={r.required_date} /> : '-'}
                    </td>
                    <td className="px-4 py-2 text-right tabular-nums">{r.items.length}</td>
                    <td className="px-4 py-2 text-right tabular-nums">
                      <HeaderQuantity req={r} value={r.reconciliation.requested} />
                    </td>
                    <td className="px-4 py-2 text-right tabular-nums">
                      <HeaderQuantity req={r} value={r.reconciliation.ordered} />
                    </td>
                    <td className="px-4 py-2 text-right tabular-nums">
                      <HeaderQuantity req={r} value={r.reconciliation.received} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {data.total > data.items.length && (
            <p className="px-4 py-2 text-xs text-content-tertiary">
              {t('procurement.requisitions.truncated', {
                defaultValue: 'Showing the newest {{shown}} of {{total}} requisitions.',
                shown: data.items.length,
                total: data.total,
              })}
            </p>
          )}
        </Card>
      )}

      <RequisitionDetailModal projectId={projectId} requisitionId={openId} onClose={() => setOpenId(null)} />
      <ConvertToPOModal
        projectId={projectId}
        requisitions={pickedReqs}
        open={converting}
        onClose={() => setConverting(false)}
        onConverted={() => {
          setConverting(false);
          setPicked([]);
        }}
      />
      {canManageSettings && (
        <ProcurementSettingsModal projectId={projectId} open={settingsOpen} onClose={() => setSettingsOpen(false)} />
      )}
    </div>
  );
}

/* ── Detail / edit ──────────────────────────────────────────────────────── */

interface DetailProps {
  projectId: string;
  requisitionId: string | null;
  onClose: () => void;
}

function RequisitionDetailModal({ projectId, requisitionId, onClose }: DetailProps) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);

  const { data: req, isLoading } = useQuery({
    queryKey: ['procurement-requisition', requisitionId],
    queryFn: () => getRequisition(requisitionId!),
    enabled: !!requisitionId,
  });

  const [title, setTitle] = useState('');
  const [neededBy, setNeededBy] = useState('');
  const [notes, setNotes] = useState('');
  const [vendorId, setVendorId] = useState('');
  const [orderOwner, setOrderOwner] = useState<OrderOwner>('ocerp');
  const [approvers, setApprovers] = useState<string[]>([]);
  const [recordingExternal, setRecordingExternal] = useState(false);
  const [decision, setDecision] = useState<'approve' | 'reject' | null>(null);
  const userId = useAuthStore((s) => s.userId);
  const userRole = useAuthStore((s) => s.userRole);
  const { data: me } = useQuery({
    queryKey: ['me'],
    queryFn: () => apiGet<{ permissions?: string[] }>('/v1/users/me/'),
    staleTime: 5 * 60_000,
  });
  const [lines, setLines] = useState<RequisitionLineIn[]>([]);
  const [selected, setSelected] = useState<number[]>([]);
  const [dirty, setDirty] = useState(false);
  const [ruleErrors, setRuleErrors] = useState<RequisitionRuleError[]>([]);

  useEffect(() => {
    if (!req) return;
    setTitle(req.title ?? '');
    setNeededBy(req.required_date ?? '');
    setNotes(req.notes ?? '');
    setVendorId(req.vendor_id ?? '');
    setOrderOwner(req.order_owner ?? 'ocerp');
    setApprovers((req.approval_chain ?? []).map((s) => s.user_id));
    setLines(req.items.map(lineToInput));
    setSelected([]);
    setDirty(false);
  }, [req]);

  useEffect(() => {
    setRuleErrors([]);
  }, [requisitionId]);

  const isDraft = req?.status === 'draft';

  const onDone = (updated: Requisition) => {
    queryClient.setQueryData(['procurement-requisition', updated.id], updated);
    queryClient.invalidateQueries({ queryKey: ['procurement-requisitions', projectId] });
  };
  const onFail = (e: unknown) => {
    const errors = parseRequisitionRuleErrors(e);
    setRuleErrors(errors);
    if (!errors.length) {
      addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: getErrorMessage(e) });
    }
  };

  const save = useMutation({
    mutationFn: () =>
      updateRequisition(requisitionId!, {
        title: title.trim() || null,
        required_date: neededBy || null,
        notes: notes.trim() || null,
        vendor_id: vendorId || null,
        items: lines,
        order_owner: orderOwner,
        approval_chain: approvers,
      }),
    onSuccess: (updated) => {
      onDone(updated);
      setRuleErrors([]);
      addToast({ type: 'success', title: t('procurement.requisitions.saved', { defaultValue: 'Draft saved' }) });
    },
    onError: onFail,
  });

  const submit = useMutation({
    mutationFn: async () => {
      if (dirty) await save.mutateAsync();
      return submitRequisition(requisitionId!);
    },
    onSuccess: (updated) => {
      onDone(updated);
      setRuleErrors([]);
      addToast({
        type: 'success',
        title: t('procurement.requisitions.submitted_toast', {
          defaultValue: 'Requisition submitted. It now waits for purchasing; it has not been approved.',
        }),
      });
    },
    onError: onFail,
  });

  const withdraw = useMutation({
    mutationFn: () => withdrawRequisition(requisitionId!),
    onSuccess: onDone,
    onError: onFail,
  });

  const cancel = useMutation({
    mutationFn: () => cancelRequisition(requisitionId!),
    onSuccess: onDone,
    onError: onFail,
  });

  const approve = useMutation({
    mutationFn: (comment: string) => approveRequisition(requisitionId!, comment),
    onSuccess: (updated) => {
      onDone(updated);
      setDecision(null);
      setRuleErrors([]);
      addToast({
        type: 'success',
        title:
          updated.status === 'submitted'
            ? t('procurement.requisitions.approval_step_toast', {
                defaultValue: 'Your approval is recorded. The requisition now waits for the next approver.',
              })
            : t('procurement.requisitions.approved_toast', { defaultValue: 'Requisition approved' }),
      });
    },
    onError: (e: unknown) => {
      setDecision(null);
      onFail(e);
    },
  });

  const reject = useMutation({
    mutationFn: (comment: string) => rejectRequisition(requisitionId!, comment),
    onSuccess: (updated) => {
      onDone(updated);
      setDecision(null);
      addToast({ type: 'success', title: t('procurement.requisitions.rejected_toast', { defaultValue: 'Requisition rejected' }) });
    },
    onError: (e: unknown) => {
      setDecision(null);
      onFail(e);
    },
  });

  const busy =
    save.isPending || submit.isPending || withdraw.isPending || cancel.isPending || approve.isPending || reject.isPending;

  const editLine = (index: number, patch: Partial<RequisitionLineIn>) => {
    setLines((prev) => prev.map((l, i) => (i === index ? { ...l, ...patch } : l)));
    setDirty(true);
  };
  const removeLine = (index: number) => {
    setLines((prev) => prev.filter((_, i) => i !== index));
    setSelected([]);
    setDirty(true);
  };
  const mergeSelected = () => {
    const merged = mergeRequisitionLines(lines, selected);
    if (merged === null) {
      addToast({
        type: 'error',
        title: t('procurement.requisitions.merge_unit_mismatch', {
          defaultValue: 'Only lines in the same unit can be merged.',
        }),
      });
      return;
    }
    setLines(merged);
    setSelected([]);
    setDirty(true);
  };

  const storedLines = useMemo(() => req?.items ?? [], [req]);
  const canRecordExternal =
    !!req &&
    req.order_owner === 'external' &&
    (req.status === 'approved' || req.status === 'ordered' || req.status === 'received') &&
    ((ROLE_RANK as Record<string, number>)[normalizeRole(userRole)] ?? 0) >= ROLE_RANK.editor;

  return (
    <WideModal
      open={requisitionId !== null}
      onClose={onClose}
      busy={busy}
      size="2xl"
      title={
        req
          ? t('procurement.requisitions.detail_title', {
              defaultValue: 'Requisition {{number}}',
              number: req.req_number ?? '',
            })
          : t('procurement.requisitions.loading', { defaultValue: 'Loading requisition' })
      }
      footer={
        req && (
          <>
            {(req.status === 'draft' || req.status === 'submitted' || req.status === 'approved') && (
              <Button variant="danger" icon={<Ban size={14} />} onClick={() => cancel.mutate()} disabled={busy}>
                {t('procurement.requisitions.cancel', { defaultValue: 'Cancel requisition' })}
              </Button>
            )}
            {(req.status === 'submitted' || req.status === 'rejected') && (
              <Button variant="secondary" icon={<Undo2 size={14} />} onClick={() => withdraw.mutate()} disabled={busy}>
                {t('procurement.requisitions.withdraw', { defaultValue: 'Withdraw to draft' })}
              </Button>
            )}
            {canRecordExternal && (
              <Button variant="secondary" icon={<ExternalLink size={14} />} onClick={() => setRecordingExternal(true)} disabled={busy}>
                {t('procurement.requisitions.external_record', { defaultValue: 'Record external order' })}
              </Button>
            )}
            {canOfferDecision(req, userId, userRole, me?.permissions) && (
              <>
                <Button variant="danger" icon={<X size={14} />} onClick={() => setDecision('reject')} disabled={busy}>
                  {t('procurement.requisitions.reject', { defaultValue: 'Reject' })}
                </Button>
                <Button icon={<Check size={14} />} onClick={() => setDecision('approve')} disabled={busy}>
                  {t('procurement.requisitions.approve', { defaultValue: 'Approve' })}
                </Button>
              </>
            )}
            {isDraft && (
              <>
                <Button variant="secondary" onClick={() => save.mutate()} disabled={busy || !dirty}>
                  {t('procurement.requisitions.save', { defaultValue: 'Save draft' })}
                </Button>
                <Button icon={<Send size={14} />} onClick={() => submit.mutate()} disabled={busy || lines.length === 0}>
                  {submit.isPending && <Loader2 size={14} className="mr-1 animate-spin" />}
                  {t('procurement.requisitions.submit', { defaultValue: 'Submit' })}
                </Button>
              </>
            )}
          </>
        )
      }
    >
      {isLoading || !req ? (
        <Loader2 size={18} className="animate-spin text-content-tertiary" />
      ) : (
        <div className="space-y-4">
          <div className="flex flex-wrap items-center gap-3 text-sm">
            <StatusBadge status={req.status} />
            {sharedUnit(req) !== null && (
            <span className="text-content-tertiary">
              {t('procurement.requisitions.progress', {
                defaultValue: 'Requested {{requested}}, ordered {{ordered}}, received {{received}}, outstanding {{outstanding}}',
                requested: req.reconciliation.requested ?? '0',
                ordered: req.reconciliation.ordered ?? '0',
                received: req.reconciliation.received ?? '0',
                outstanding: req.reconciliation.outstanding ?? '0',
              })}{' '}
              {sharedUnit(req)}
            </span>
            )}
          </div>

          {(req.decision_comment || req.decided_at) && (
            <div
              className={`rounded-lg border p-3 text-sm ${
                req.status === 'rejected' ? 'border-semantic-error/40 bg-semantic-error/5' : 'border-border-light bg-surface-secondary/40'
              }`}
            >
              <p className="text-xs font-medium text-content-secondary">
                {req.status === 'rejected'
                  ? t('procurement.requisitions.rejected_note', { defaultValue: 'Rejected' })
                  : t('procurement.requisitions.approved_note', { defaultValue: 'Approved' })}
                {req.approver_name ? ` · ${req.approver_name}` : null}
                {req.decided_at ? (
                  <>
                    {' · '}
                    <DateDisplay value={req.decided_at} />
                  </>
                ) : null}
              </p>
              {req.decision_comment && <p className="mt-1 text-content-primary">{req.decision_comment}</p>}
            </div>
          )}

          {req.po_id && (req.purchase_orders ?? []).length <= 1 && (
            <p className="text-sm text-content-secondary">
              {t('procurement.requisitions.ordered_on_po', {
                defaultValue: 'Ordered on purchase order {{number}}',
                number: req.po_number ?? req.po_id.slice(0, 8),
              })}
            </p>
          )}
          {(req.purchase_orders ?? []).length > 1 && <RequisitionOrderList req={req} />}

          <div className="grid gap-3 sm:grid-cols-2">
            <div className="block text-xs font-medium text-content-secondary">
              <label htmlFor="req-order-owner">
                {t('procurement.requisitions.field_order_owner', { defaultValue: 'Orders are placed in' })}
              </label>
              <div className="mt-1">
                {isDraft ? (
                  <OrderOwnerSelect
                    id="req-order-owner"
                    value={orderOwner}
                    onChange={(owner) => {
                      setOrderOwner(owner);
                      setDirty(true);
                    }}
                  />
                ) : (
                  <span className="text-sm text-content-primary">{orderOwnerLabel(t, req.order_owner ?? 'ocerp')}</span>
                )}
              </div>
            </div>
            <div className="block text-xs font-medium text-content-secondary">
              {t('procurement.requisitions.field_approvers', { defaultValue: 'Designated approvers, in order' })}
              <div className="mt-1 font-normal">
                {isDraft ? (
                  <ApproverChainEditor
                    projectId={projectId}
                    value={approvers}
                    knownNames={Object.fromEntries((req.approval_chain ?? []).map((s) => [s.user_id, s.name]))}
                    excluded={[req.requester_id ?? '', userId ?? ''].filter(Boolean)}
                    idPrefix="req"
                    onChange={(chain) => {
                      setApprovers(chain);
                      setDirty(true);
                    }}
                  />
                ) : (req.approval_chain ?? []).length > 0 ? (
                  <ApprovalChainView steps={req.approval_chain ?? []} />
                ) : (
                  <span className="text-sm text-content-primary">
                    {t('procurement.requisitions.approvers_single', { defaultValue: 'One approval decides' })}
                  </span>
                )}
              </div>
            </div>
          </div>

          <div className="grid gap-3 sm:grid-cols-2">
            <div className="block text-xs font-medium text-content-secondary sm:col-span-2">
              {t('procurement.requisitions.field_vendor', { defaultValue: 'Vendor' })}
              <div className="mt-1">
                {isDraft ? (
                  <VendorSelect
                    value={vendorId}
                    fallbackName={req.vendor_name}
                    onChange={(id) => {
                      setVendorId(id);
                      setDirty(true);
                    }}
                  />
                ) : (
                  <span className="text-sm text-content-primary">
                    {req.vendor_name || t('procurement.requisitions.vendor_none', { defaultValue: 'No vendor chosen yet' })}
                    {req.vendor_status && req.vendor_status !== 'active' && (
                      <span className="ml-2 inline-block">
                        <Badge variant="error" size="sm">
                          {t('procurement.requisitions.vendor_inactive', { defaultValue: 'Not active in the directory' })}
                        </Badge>
                      </span>
                    )}
                  </span>
                )}
                <SuggestedSupplierHint
                  req={req}
                  vendorId={isDraft ? vendorId : (req.vendor_id ?? '')}
                  editable={isDraft}
                  onUse={(id) => {
                    setVendorId(id);
                    setDirty(true);
                  }}
                />
              </div>
            </div>
            <label className="block text-xs font-medium text-content-secondary">
              {t('procurement.requisitions.field_title', { defaultValue: 'Title' })}
              <input
                className={`${fieldCls} mt-1`}
                value={title}
                maxLength={500}
                disabled={!isDraft}
                onChange={(e) => {
                  setTitle(e.target.value);
                  setDirty(true);
                }}
              />
            </label>
            <label className="block text-xs font-medium text-content-secondary">
              {t('procurement.requisitions.field_needed_by', { defaultValue: 'Needed on site by' })}
              <input
                type="date"
                className={`${fieldCls} mt-1`}
                value={neededBy}
                disabled={!isDraft}
                onChange={(e) => {
                  setNeededBy(e.target.value);
                  setDirty(true);
                }}
              />
              {(req.latest_order_date || req.estimated_delivery_date) && (
                <span className="mt-1 block font-normal text-content-tertiary">
                  {req.latest_order_date && (
                    <span className="mr-3">
                      {t('procurement.requisitions.latest_order_date', { defaultValue: 'Order by' })}:{' '}
                      <DateDisplay value={req.latest_order_date} />
                    </span>
                  )}
                  {req.estimated_delivery_date && (
                    <span>
                      {t('procurement.requisitions.supplier_expected', { defaultValue: 'Order delivery date' })}:{' '}
                      <DateDisplay value={req.estimated_delivery_date} />
                    </span>
                  )}
                </span>
              )}
            </label>
            <label className="block text-xs font-medium text-content-secondary sm:col-span-2">
              {t('procurement.requisitions.field_notes', { defaultValue: 'Notes' })}
              <textarea
                className="mt-1 min-h-[3.5rem] w-full rounded-lg border border-border bg-surface-primary px-3 py-2 text-sm"
                value={notes}
                maxLength={5000}
                disabled={!isDraft}
                onChange={(e) => {
                  setNotes(e.target.value);
                  setDirty(true);
                }}
              />
            </label>
          </div>

          <RuleErrorList
            errors={ruleErrors}
            title={t('procurement.requisitions.rules_failed', {
              defaultValue: 'Fix these before submitting:',
            })}
          />

          <div>
            <div className="mb-2 flex items-center justify-between gap-2">
              <h4 className="text-sm font-semibold text-content-primary">
                {t('procurement.requisitions.lines', { defaultValue: 'Lines' })}
              </h4>
              {isDraft && (
                <Button
                  size="sm"
                  variant="secondary"
                  icon={<GitMerge size={14} />}
                  onClick={mergeSelected}
                  disabled={selected.length < 2}
                  title={t('procurement.requisitions.merge_hint', {
                    defaultValue: 'Combine the selected lines into one. Do this only when they are the same material.',
                  })}
                >
                  {t('procurement.requisitions.merge', { defaultValue: 'Merge selected' })}
                </Button>
              )}
            </div>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[56rem] text-sm">
                <thead>
                  <tr className="border-b border-border-light text-left text-2xs uppercase tracking-wide text-content-tertiary">
                    {isDraft && <th className="w-8 py-1.5" />}
                    <th className="py-1.5 pr-3 font-medium">{t('procurement.requisitions.col_material', { defaultValue: 'Material' })}</th>
                    <th className="py-1.5 pr-3 font-medium">{t('procurement.requisitions.col_unit', { defaultValue: 'Unit' })}</th>
                    <th className="py-1.5 pr-3 text-right font-medium">{t('procurement.requisitions.col_requested', { defaultValue: 'Requested' })}</th>
                    <th className="py-1.5 pr-3 text-right font-medium">{t('procurement.requisitions.col_ordered', { defaultValue: 'Ordered' })}</th>
                    <th className="py-1.5 pr-3 text-right font-medium">{t('procurement.requisitions.col_to_order', { defaultValue: 'Still to order' })}</th>
                    <th className="py-1.5 pr-3 text-right font-medium">{t('procurement.requisitions.col_received', { defaultValue: 'Received' })}</th>
                    <th className="py-1.5 pr-3 text-right font-medium">{t('procurement.requisitions.col_outstanding', { defaultValue: 'Outstanding' })}</th>
                    <th className="py-1.5 pr-3 font-medium">{t('procurement.requisitions.col_sources', { defaultValue: 'From the BOQ' })}</th>
                    <th className="py-1.5 pr-3 font-medium">
                      {t('procurement.requisitions.col_supply', { defaultValue: 'Supplier and date' })}
                    </th>
                    {isDraft && <th className="w-8 py-1.5" />}
                  </tr>
                </thead>
                <tbody>
                  {lines.map((line, index) => {
                    // Progress figures belong to the stored line; an unsaved
                    // edit (merge, removal) has none yet.
                    const stored = !dirty ? storedLines[index] : undefined;
                    return (
                      <tr key={index} className="border-b border-border-light/60 align-top last:border-0">
                        {isDraft && (
                          <td className="py-1.5">
                            <input
                              type="checkbox"
                              aria-label={t('procurement.requisitions.select_line', { defaultValue: 'Select line' })}
                              checked={selected.includes(index)}
                              onChange={(e) =>
                                setSelected((prev) => (e.target.checked ? [...prev, index] : prev.filter((i) => i !== index)))
                              }
                            />
                          </td>
                        )}
                        <td className="py-1.5 pr-3">
                          {isDraft ? (
                            <input
                              className={fieldCls}
                              value={line.description}
                              maxLength={500}
                              onChange={(e) => editLine(index, { description: e.target.value })}
                            />
                          ) : (
                            line.description
                          )}
                        </td>
                        <td className="py-1.5 pr-3 text-content-secondary">{line.unit || '-'}</td>
                        <td className="py-1.5 pr-3 text-right tabular-nums">
                          {isDraft ? (
                            <input
                              className={`${fieldCls} w-28 text-right`}
                              inputMode="decimal"
                              value={line.quantity_requested}
                              onChange={(e) => editLine(index, { quantity_requested: e.target.value.trim() })}
                            />
                          ) : (
                            <QuantityDisplay value={line.quantity_requested} unit={line.unit ?? ''} precision={2} />
                          )}
                        </td>
                        <td className="py-1.5 pr-3 text-right tabular-nums text-content-secondary">
                          {stored ? <QuantityDisplay value={stored.quantity_ordered} unit={stored.unit ?? ''} precision={2} /> : '-'}
                        </td>
                        <td className="py-1.5 pr-3 text-right tabular-nums text-content-secondary">
                          {stored ? (
                            <QuantityDisplay value={stored.quantity_to_order ?? '0'} unit={stored.unit ?? ''} precision={2} />
                          ) : (
                            '-'
                          )}
                        </td>
                        <td className="py-1.5 pr-3 text-right tabular-nums text-content-secondary">
                          {stored ? <QuantityDisplay value={stored.quantity_received} unit={stored.unit ?? ''} precision={2} /> : '-'}
                        </td>
                        <td className="py-1.5 pr-3 text-right tabular-nums text-content-secondary">
                          {stored ? <QuantityDisplay value={stored.quantity_outstanding} unit={stored.unit ?? ''} precision={2} /> : '-'}
                        </td>
                        <td className="py-1.5 pr-3 text-xs text-content-tertiary">
                          {line.sources.length === 0
                            ? t('procurement.requisitions.no_sources', { defaultValue: 'Entered by hand' })
                            : t('procurement.requisitions.source_count', {
                                defaultValue: 'BOQ sources: {{n}}',
                                n: line.sources.length,
                              })}
                          {(stored?.po_items ?? []).map((pi) => (
                            <div
                              key={pi.po_item_id}
                              className={`mt-0.5 ${pi.po_status === 'cancelled' ? 'text-content-tertiary line-through' : 'text-content-secondary'}`}
                            >
                              {t('procurement.requisitions.po_line_ref', {
                                defaultValue: 'PO {{number}}: {{quantity}} {{unit}}',
                                number: pi.po_number ?? pi.po_id.slice(0, 8),
                                quantity: pi.quantity,
                                unit: pi.unit ?? '',
                              })}
                            </div>
                          ))}
                          {stored && <LineOrderFlags line={stored} />}
                        </td>
                        <td className="py-1.5 pr-3">
                          <LineSupplyCell
                            projectId={projectId}
                            line={line}
                            stored={stored}
                            headerDate={neededBy}
                            editable={isDraft}
                            onChange={(patch) => editLine(index, patch)}
                          />
                        </td>
                        {isDraft && (
                          <td className="py-1.5">
                            <button
                              type="button"
                              aria-label={t('procurement.requisitions.remove_line', { defaultValue: 'Remove line' })}
                              className="text-content-tertiary hover:text-semantic-error"
                              onClick={() => removeLine(index)}
                            >
                              <Trash2 size={14} />
                            </button>
                          </td>
                        )}
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}
      {req && (
        <ExternalOrderModal
          req={req}
          open={recordingExternal}
          onClose={() => setRecordingExternal(false)}
          onSaved={(updated) => {
            onDone(updated);
            setRecordingExternal(false);
          }}
        />
      )}
      <DecisionModal
        mode={decision}
        busy={approve.isPending || reject.isPending}
        onClose={() => setDecision(null)}
        onConfirm={(comment) => (decision === 'reject' ? reject.mutate(comment) : approve.mutate(comment))}
      />
    </WideModal>
  );
}
