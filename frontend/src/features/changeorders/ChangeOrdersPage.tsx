import { useState, useMemo, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { normalizeListResponse } from '@/shared/lib/apiHelpers';
import {
  FileEdit,
  FileText,
  Plus,
  Send,
  CheckCircle2,
  CheckCheck,
  XCircle,
  ChevronRight,
  ArrowLeft,
  ArrowUp,
  ArrowDown,
  DollarSign,
  Clock,
  AlertTriangle,
  Trash2,
  Download,
  Sparkles,
  ShoppingCart,
  HelpCircle,
  GitBranch,
} from 'lucide-react';
import { Button, Card, Badge, EmptyState, Breadcrumb, InfoHint, DismissibleInfo, IntroRichText, ConfirmDialog, RecoveryCard, SkeletonTable, SkeletonCard } from '@/shared/ui';
import { useNavigate } from 'react-router-dom';
import { PageHeader } from '@/shared/ui/PageHeader';
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
import { listContracts } from '@/features/contracts/api';
import { ApprovalTimeline } from './ApprovalTimeline';
import { ImpactSimulator, type SavedScenario } from './ImpactSimulator';
import { AIDraftModal } from './AIDraftModal';
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
  // Money / quantity fields are serialized by the backend as canonical
  // decimal STRINGS (NUMERIC(18,6) / String(50)) — never JS numbers. Typing
  // them as `string` here forces every use site to coerce explicitly with
  // `Number(...)` before arithmetic / `.toFixed`, which is the root-cause
  // fix for the Export-CSV crash and any future blended math.
  original_quantity: string;
  new_quantity: string;
  original_rate: string;
  new_rate: string;
  cost_delta: string;
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
  // BUG-351: rejection now has its own audit columns on the backend. A CO
  // rejected straight from 'submitted' populates only these — gating the
  // audit card on approved_at hid the rejection entirely.
  rejected_by: string | null;
  submitted_at: string | null;
  approved_at: string | null;
  rejected_at: string | null;
  // Backend emits cost_impact as a canonical decimal string (see schemas.py
  // ChangeOrderResponse.cost_impact:str). Coerce with Number(...) at use.
  cost_impact: string;
  schedule_impact_days: number;
  currency: string;
  metadata: Record<string, unknown>;
  item_count: number;
  created_at: string;
  updated_at: string;
  // T3: construction-management-platform-style approval chain + commitment / RFI links.
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
  // Decimal string from the backend (ChangeOrderSummary.total_cost_impact:str).
  total_cost_impact: string;
  total_schedule_impact_days: number;
  // The project BASE currency — the only currency total_cost_impact is in.
  currency: string;
  // Approved COs in a foreign currency with no FX rate, grouped by ISO code
  // as decimal strings, e.g. { USD: '5000.00' }. These are NOT folded into
  // total_cost_impact (no blending currencies without conversion).
  unconverted_by_currency?: Record<string, string>;
}

/* ── Helpers ───────────────────────────────────────────────────────────── */

// Status vocabulary mirrors the backend FSM exactly
// (service.VALID_TRANSITIONS: draft -> submitted -> approved -> executed,
// with rejected as a terminal branch). There is no 'under_review' state on
// the backend, so it is intentionally absent here.
const STATUS_COLORS: Record<string, 'neutral' | 'blue' | 'success' | 'warning' | 'error'> = {
  draft: 'neutral',
  submitted: 'blue',
  approved: 'success',
  executed: 'success',
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
    approved: t('changeorders.status_approved', { defaultValue: 'Approved' }),
    executed: t('changeorders.status_executed', { defaultValue: 'Executed' }),
    rejected: t('changeorders.status_rejected', { defaultValue: 'Rejected' }),
  };
  return map[status] || status;
}

function formatCurrency(amount: number, currency?: string): string {
  // NEVER hard-fallback to 'EUR' (task #217): a project priced in BRL/USD
  // must not render its change-order amounts with a Euro sign. When the
  // currency is unknown, show a plain decimal number with no symbol.
  //
  // Cents matter for contractual change-order amounts (task: a 1250.50
  // impact must not collapse to "1,251"). We drop the explicit fraction
  // overrides so Intl applies the currency's own minor-unit count (2 for
  // EUR/USD, 0 for JPY, 3 for KWD, …) — that's the correct behaviour for
  // every currency without hard-coding it.
  const safe = Number.isFinite(amount) ? amount : 0;
  const code = (currency || '').trim().toUpperCase();
  if (!/^[A-Z]{3}$/.test(code)) {
    return new Intl.NumberFormat(getIntlLocale(), {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }).format(safe);
  }
  try {
    return new Intl.NumberFormat(getIntlLocale(), {
      style: 'currency',
      currency: code,
    }).format(safe);
  } catch {
    return `${safe.toFixed(2)} ${code}`;
  }
}

/**
 * Format a numeric quantity stored as a NUMERIC(18,6) decimal string.
 *
 * The backend serializes quantities verbatim ('5.000000'), so rendering
 * them raw reads as '5.000000 m2'. We trim trailing zeros (up to 6
 * fraction digits) so a clean integer reads '5 m2' while a genuine
 * fractional quantity (e.g. '5.250000') still shows as '5.25 m2'.
 */
function formatQuantity(value: string | number): string {
  const n = Number(value);
  if (!Number.isFinite(n)) return String(value);
  return n.toLocaleString(getIntlLocale(), { maximumFractionDigits: 6 });
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
  // Optional link to a commercial contract. Stored as metadata.contract_id
  // (the CO create schema has a free-form `metadata: dict`); on approval the
  // backend subscriber revises the linked contract's total_value.
  const [contractId, setContractId] = useState('');
  const addToast = useToastStore((s) => s.addToast);

  const { data: contracts = [] } = useQuery({
    queryKey: ['changeorders', 'contract-options', projectId],
    queryFn: () => listContracts({ project_id: projectId, limit: 200 }),
    enabled: Boolean(projectId),
  });
  // Change orders are only valid on commercially-live contracts (same
  // amendability rule as the contracts module: active / suspended).
  const linkableContracts = useMemo(
    () => contracts.filter((c) => c.status === 'active' || c.status === 'suspended'),
    [contracts],
  );

  const mutation = useMutation({
    mutationFn: () =>
      apiPost<ChangeOrder>('/v1/changeorders/', {
        project_id: projectId,
        title,
        description,
        reason_category: reason,
        schedule_impact_days: scheduleDays,
        currency,
        ...(contractId ? { metadata: { contract_id: contractId } } : {}),
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
        {linkableContracts.length > 0 && (
          <WideModalField
            label={t('changeorders.apply_to_contract', { defaultValue: 'Apply to contract (optional)' })}
            hint={t('changeorders.apply_to_contract_hint', {
              defaultValue: 'On approval, the cost impact also revises the selected contract value.',
            })}
            span={2}
            htmlFor="co-contract"
          >
            <select
              id="co-contract"
              value={contractId}
              onChange={(e) => setContractId(e.target.value)}
              className={fieldCls}
            >
              <option value="">
                {t('changeorders.apply_to_contract_none', { defaultValue: 'None - project budget only' })}
              </option>
              {linkableContracts.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.code} - {c.title}
                </option>
              ))}
            </select>
          </WideModalField>
        )}
      </WideModalSection>
    </WideModal>
  );
}

/* ── Add Item Dialog ───────────────────────────────────────────────────── */

function AddItemDialog({
  orderId,
  projectId,
  currency,
  onClose,
  onCreated,
}: {
  orderId: string;
  // CONN-45: needed to list the project's BOQs in the "Pick from BOQ" flow.
  projectId: string;
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
  // CONN-45: provenance of a picked BOQ position, stamped onto item metadata
  // so the change order line stays traceable back to the estimate it amends.
  const [boqSource, setBoqSource] = useState<BoqPositionPick | null>(null);
  const [showBoqPicker, setShowBoqPicker] = useState(false);
  const addToast = useToastStore((s) => s.addToast);

  // Pre-fill the form from a chosen BOQ position. The position's quantity/rate
  // become the ORIGINAL (pre-change) values; the New Qty defaults to the same
  // so a pure rate change or quantity change is one edit away.
  const applyBoqPick = (pick: BoqPositionPick) => {
    setBoqSource(pick);
    setDesc(pick.description);
    setUnit(pick.unit);
    setOrigQty(pick.quantity);
    setNewQty(pick.quantity);
    setOrigRate(pick.unit_rate);
    setNewRate(pick.unit_rate);
    setShowBoqPicker(false);
  };

  const clearBoqSource = () => setBoqSource(null);

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
        // Stamp BOQ provenance when the line was seeded from an estimate
        // position. The backend item schema already accepts a free-form
        // metadata dict, so no model/schema change is needed.
        ...(boqSource
          ? {
              metadata: {
                boq_id: boqSource.boqId,
                boq_position_id: boqSource.id,
                boq_position_ordinal: boqSource.ordinal,
              },
            }
          : {}),
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
    <>
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
        {/* CONN-45: seed this line from a BOQ position so the original
            quantity and rate come straight from the estimate being amended,
            instead of being re-keyed by hand. */}
        <div className="sm:col-span-2">
          {boqSource ? (
            <div className="flex items-center justify-between gap-2 rounded-lg border border-blue-200 bg-blue-50 dark:bg-blue-950/20 dark:border-blue-800 px-3 py-2 text-xs">
              <span className="flex min-w-0 items-center gap-2 text-blue-700 dark:text-blue-300">
                <FileText size={14} className="shrink-0" />
                <span className="truncate">
                  {t('changeorders.boq_source_label', {
                    position: boqSource.ordinal || boqSource.id.slice(0, 8),
                  })}
                </span>
              </span>
              <button
                type="button"
                onClick={clearBoqSource}
                className="shrink-0 text-content-tertiary hover:text-semantic-error"
                aria-label={t('changeorders.boq_source_clear', { defaultValue: 'Clear BOQ link' })}
              >
                <XCircle size={14} />
              </button>
            </div>
          ) : (
            <Button
              type="button"
              variant="secondary"
              size="sm"
              onClick={() => setShowBoqPicker(true)}
            >
              <FileText size={14} className="mr-1.5" />
              {t('changeorders.pick_from_boq', { defaultValue: 'Pick from BOQ' })}
            </Button>
          )}
        </div>
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
    {showBoqPicker && (
      <BoqPositionPickerDialog
        projectId={projectId}
        currency={currency}
        onClose={() => setShowBoqPicker(false)}
        onPick={applyBoqPick}
      />
    )}
    </>
  );
}

/* ── BOQ position picker (CONN-45) ─────────────────────────────────────── */

/** A BOQ position chosen in the picker, flattened to just the fields a
 *  change-order line seeds from plus enough provenance to deep-link back. */
interface BoqPositionPick {
  id: string;
  boqId: string;
  ordinal: string;
  description: string;
  unit: string;
  quantity: number;
  unit_rate: number;
}

interface BoqListItem {
  id: string;
  name: string;
}

interface BoqPositionRow {
  id: string;
  boq_id: string;
  parent_id: string | null;
  ordinal: string;
  description: string;
  unit: string;
  quantity: number;
  unit_rate: number;
}

interface BoqWithPositions {
  positions: BoqPositionRow[];
}

/**
 * Two-step picker: choose one of the project's BOQs, then a leaf position
 * within it. Picking a position pre-fills the change-order line's
 * description, unit and original quantity/rate. Sections (rows with a 0 rate
 * and 0 quantity that carry children) are still selectable but the buyer
 * normally picks a priced leaf.
 */
function BoqPositionPickerDialog({
  projectId,
  currency,
  onClose,
  onPick,
}: {
  projectId: string;
  currency: string;
  onClose: () => void;
  onPick: (pick: BoqPositionPick) => void;
}) {
  const { t } = useTranslation();
  const [boqId, setBoqId] = useState('');
  const [search, setSearch] = useState('');

  const { data: boqs = [], isLoading: boqsLoading } = useQuery({
    queryKey: ['changeorders', 'boqs', projectId],
    queryFn: () => apiGet<BoqListItem[]>(`/v1/boq/boqs/?project_id=${projectId}`),
    select: (d): BoqListItem[] => normalizeListResponse(d),
    enabled: !!projectId,
  });

  const { data: boqDetail, isLoading: posLoading } = useQuery({
    queryKey: ['changeorders', 'boq-positions', boqId],
    queryFn: () => apiGet<BoqWithPositions>(`/v1/boq/boqs/${boqId}`),
    enabled: !!boqId,
  });

  const positions = useMemo(() => {
    const rows = boqDetail?.positions ?? [];
    const q = search.trim().toLowerCase();
    const filtered = q
      ? rows.filter(
          (p) =>
            (p.description || '').toLowerCase().includes(q) ||
            (p.ordinal || '').toLowerCase().includes(q),
        )
      : rows;
    return filtered.slice(0, 300);
  }, [boqDetail, search]);

  const fieldCls =
    'h-10 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';

  return (
    <WideModal
      open
      onClose={onClose}
      title={t('changeorders.boq_picker_title', { defaultValue: 'Pick from BOQ' })}
      size="lg"
      footer={
        <Button variant="ghost" onClick={onClose}>
          {t('common.cancel', { defaultValue: 'Cancel' })}
        </Button>
      }
    >
      <WideModalSection columns={1}>
        <WideModalField
          label={t('changeorders.boq_picker_boq', { defaultValue: 'BOQ' })}
          htmlFor="boq-picker-boq"
          span={1}
        >
          <select
            id="boq-picker-boq"
            value={boqId}
            onChange={(e) => setBoqId(e.target.value)}
            disabled={boqsLoading}
            className={fieldCls}
          >
            <option value="">
              {boqsLoading
                ? t('common.loading', { defaultValue: 'Loading...' })
                : boqs.length > 0
                  ? t('common.select_boq', { defaultValue: 'Select BOQ...' })
                  : t('boq.no_boqs', { defaultValue: 'No BOQs found' })}
            </option>
            {boqs.map((b) => (
              <option key={b.id} value={b.id}>
                {b.name}
              </option>
            ))}
          </select>
        </WideModalField>

        {boqId && (
          <WideModalField
            label={t('common.search', { defaultValue: 'Search' })}
            htmlFor="boq-picker-search"
            span={1}
          >
            <input
              id="boq-picker-search"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder={t('changeorders.boq_picker_search_placeholder', {
                defaultValue: 'Filter by description or ordinal…',
              })}
              className={fieldCls}
              autoComplete="off"
            />
          </WideModalField>
        )}

        {boqId && (
          posLoading ? (
            <SkeletonTable rows={6} columns={3} />
          ) : positions.length === 0 ? (
            <p className="rounded-lg border border-dashed border-border px-3 py-6 text-center text-xs text-content-tertiary">
              {t('changeorders.boq_picker_empty', {
                defaultValue: 'No positions match. Pick another BOQ or clear the filter.',
              })}
            </p>
          ) : (
            <div className="max-h-80 overflow-y-auto rounded-lg border border-border">
              <table className="w-full text-sm">
                <thead className="sticky top-0 bg-surface-secondary text-content-tertiary text-xs uppercase tracking-wide">
                  <tr>
                    <th className="px-3 py-2 text-left">
                      {t('changeorders.boq_picker_ordinal', { defaultValue: 'Ord.' })}
                    </th>
                    <th className="px-3 py-2 text-left">
                      {t('common.description', { defaultValue: 'Description' })}
                    </th>
                    <th className="px-3 py-2 text-right">
                      {t('changeorders.boq_picker_qty', { defaultValue: 'Qty' })}
                    </th>
                    <th className="px-3 py-2 text-right">
                      {t('changeorders.boq_picker_rate', { defaultValue: 'Rate' })}
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {positions.map((p) => (
                    <tr
                      key={p.id}
                      onClick={() =>
                        onPick({
                          id: p.id,
                          boqId: p.boq_id || boqId,
                          ordinal: p.ordinal,
                          description: p.description,
                          unit: p.unit,
                          quantity: Number(p.quantity) || 0,
                          unit_rate: Number(p.unit_rate) || 0,
                        })
                      }
                      className="cursor-pointer border-t border-border-light hover:bg-surface-secondary"
                    >
                      <td className="px-3 py-2 font-mono text-xs text-content-secondary whitespace-nowrap">
                        {p.ordinal}
                      </td>
                      <td className="px-3 py-2 text-content-primary">{p.description}</td>
                      <td className="px-3 py-2 text-right tabular-nums text-content-secondary">
                        {formatQuantity(p.quantity)} {p.unit}
                      </td>
                      <td className="px-3 py-2 text-right tabular-nums text-content-secondary">
                        {formatCurrency(Number(p.unit_rate) || 0, currency)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )
        )}
      </WideModalSection>
    </WideModal>
  );
}

/* ── Approval Chain Builder ────────────────────────────────────────────── */

interface DirectoryUser {
  id: string;
  email: string;
  full_name: string;
  role: string;
  is_active: boolean;
}

/** Friendly display name for a directory user. */
function userLabel(u: DirectoryUser): string {
  return (u.full_name || '').trim() || u.email || u.id;
}

/**
 * Approver picker — searches the user directory by name/email and lets the
 * admin add approvers in step order (reorder + remove). This replaces the
 * old raw-UUID textarea so a real PM can build the chain by name.
 *
 * If the directory cannot be loaded (e.g. the caller lacks the users.list
 * permission), it degrades to a paste-UUID textarea so the feature still
 * works rather than dead-ending.
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
  const [search, setSearch] = useState('');
  // Ordered approver list (step 1 first). Holds the full user object so the
  // chip can show a name without a second lookup.
  const [chosen, setChosen] = useState<DirectoryUser[]>([]);
  // Fallback textarea state (only used when the directory query failed).
  const [raw, setRaw] = useState('');

  const { data: users = [], isError: dirError } = useQuery({
    queryKey: ['users-directory'],
    queryFn: () => apiGet<DirectoryUser[]>('/v1/users/?limit=200&is_active=true'),
    staleTime: 60_000,
  });

  const chosenIds = useMemo(() => new Set(chosen.map((u) => u.id)), [chosen]);
  const matches = useMemo(() => {
    const q = search.trim().toLowerCase();
    const pool = users.filter((u) => !chosenIds.has(u.id));
    if (!q) return pool.slice(0, 8);
    return pool
      .filter(
        (u) =>
          userLabel(u).toLowerCase().includes(q) ||
          (u.email || '').toLowerCase().includes(q) ||
          (u.role || '').toLowerCase().includes(q),
      )
      .slice(0, 8);
  }, [users, chosenIds, search]);

  const addUser = (u: DirectoryUser) => {
    if (chosen.length >= 20 || chosenIds.has(u.id)) return;
    setChosen((prev) => [...prev, u]);
    setSearch('');
  };
  const removeAt = (idx: number) =>
    setChosen((prev) => prev.filter((_, i) => i !== idx));
  const moveUp = (idx: number) =>
    setChosen((prev) => {
      if (idx <= 0) return prev;
      const next = [...prev];
      [next[idx - 1], next[idx]] = [next[idx]!, next[idx - 1]!];
      return next;
    });
  const moveDown = (idx: number) =>
    setChosen((prev) => {
      if (idx >= prev.length - 1) return prev;
      const next = [...prev];
      [next[idx + 1], next[idx]] = [next[idx]!, next[idx + 1]!];
      return next;
    });

  // Fallback parsing (raw textarea).
  const rawIds = useMemo(
    () =>
      raw
        .split(/[\s,;]+/)
        .map((x) => x.trim())
        .filter((x) => x.length > 0),
    [raw],
  );
  const rawLooksValid =
    rawIds.length > 0 &&
    rawIds.length <= 20 &&
    rawIds.every((id) => /^[0-9a-f-]{32,36}$/i.test(id));

  const usePicker = !dirError;
  const canSubmit = usePicker ? chosen.length > 0 : rawLooksValid;
  const handleConfirm = () =>
    onConfirm(usePicker ? chosen.map((u) => u.id) : rawIds);

  const fieldCls =
    'h-10 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';

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
            disabled={!canSubmit || busy}
            onClick={handleConfirm}
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
        <p className="text-xs text-content-tertiary">
          {t('changeorders.approver_user_ids_hint', {
            defaultValue:
              'Steps run sequentially: step 1 acts first, then step 2, etc. Each approver only sees the change order when their step becomes active.',
          })}
        </p>

        {usePicker ? (
          <>
            <WideModalField
              label={t('changeorders.approver_search_label', {
                defaultValue: 'Add approver (search by name or email)',
              })}
              htmlFor="approver-search"
              span={1}
            >
              <input
                id="approver-search"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                disabled={busy}
                placeholder={t('changeorders.approver_search_placeholder', {
                  defaultValue: 'Start typing a name…',
                })}
                className={fieldCls}
                autoComplete="off"
              />
            </WideModalField>

            {/* Suggestion list */}
            {matches.length > 0 && (
              <ul className="max-h-44 overflow-y-auto rounded-lg border border-border divide-y divide-border-light">
                {matches.map((u) => (
                  <li key={u.id}>
                    <button
                      type="button"
                      onClick={() => addUser(u)}
                      disabled={busy || chosen.length >= 20}
                      className="flex w-full items-center justify-between gap-2 px-3 py-2 text-left text-sm hover:bg-surface-secondary disabled:opacity-50"
                    >
                      <span className="min-w-0">
                        <span className="block truncate font-medium text-content-primary">{userLabel(u)}</span>
                        <span className="block truncate text-xs text-content-tertiary">{u.email} · {u.role}</span>
                      </span>
                      <Plus size={14} className="shrink-0 text-content-tertiary" />
                    </button>
                  </li>
                ))}
              </ul>
            )}
            {search.trim() && matches.length === 0 && (
              <p className="text-xs text-content-tertiary">
                {t('changeorders.approver_no_match', { defaultValue: 'No matching active users.' })}
              </p>
            )}

            {/* Chosen approvers, in step order */}
            {chosen.length === 0 ? (
              <p className="rounded-lg border border-dashed border-border px-3 py-4 text-center text-xs text-content-tertiary">
                {t('changeorders.approver_chain_empty', {
                  defaultValue: 'No approvers added yet. Search above and add them in the order they should sign off.',
                })}
              </p>
            ) : (
              <ol className="space-y-2">
                {chosen.map((u, idx) => (
                  <li
                    key={u.id}
                    className="flex items-center gap-2 rounded-lg border border-border bg-surface-secondary/40 px-3 py-2"
                  >
                    <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-oe-blue-subtle text-2xs font-bold text-oe-blue-text">
                      {idx + 1}
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-sm font-medium text-content-primary">{userLabel(u)}</span>
                      <span className="block truncate text-xs text-content-tertiary">{u.email}</span>
                    </span>
                    <button
                      type="button"
                      onClick={() => moveUp(idx)}
                      disabled={busy || idx === 0}
                      aria-label={t('changeorders.approver_move_up', { defaultValue: 'Move up' })}
                      className="text-content-tertiary hover:text-content-primary disabled:opacity-30"
                    >
                      <ArrowUp size={14} />
                    </button>
                    <button
                      type="button"
                      onClick={() => moveDown(idx)}
                      disabled={busy || idx === chosen.length - 1}
                      aria-label={t('changeorders.approver_move_down', { defaultValue: 'Move down' })}
                      className="text-content-tertiary hover:text-content-primary disabled:opacity-30"
                    >
                      <ArrowDown size={14} />
                    </button>
                    <button
                      type="button"
                      onClick={() => removeAt(idx)}
                      disabled={busy}
                      aria-label={t('changeorders.approver_remove', { defaultValue: 'Remove approver' })}
                      className="text-content-tertiary hover:text-semantic-error"
                    >
                      <Trash2 size={14} />
                    </button>
                  </li>
                ))}
              </ol>
            )}
          </>
        ) : (
          // Directory unavailable (no users.list permission) — fall back to
          // pasting UUIDs so the feature is never a dead end.
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
            <p className="mt-1 text-xs text-content-tertiary">
              {t('changeorders.approver_directory_unavailable', {
                defaultValue: 'The user directory is unavailable, so paste approver ids one per line in step order.',
              })}
            </p>
          </WideModalField>
        )}
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
    { key: 'executed', label: t('changeorders.status_executed', { defaultValue: 'Executed' }) },
  ];

  // Map status to step index — mirrors the backend FSM. A rejected CO sits on
  // the step it was rejected from (submitted) so the cross renders in place.
  const statusIndex: Record<string, number> = { draft: 0, submitted: 1, approved: 2, executed: 3, rejected: 1 };
  const currentIdx = statusIndex[status] ?? 0;
  const isRejected = status === 'rejected';

  return (
    <div className="flex items-center gap-0 mb-6" role="list" aria-label={t('changeorders.workflow', { defaultValue: 'Workflow' })}>
      {steps.map((step, i) => {
        const isActive = i === currentIdx;
        const isCompleted = i < currentIdx;
        const isLast = i === steps.length - 1;
        // A rejected CO marks the step it stalled on (currentIdx) with a cross
        // rather than the final step, so the workflow reads truthfully.
        const showRejected = isRejected && i === currentIdx;

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
  const navigate = useNavigate();
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
  // Marking a CO executed is an editor-level operation (changeorders.update),
  // so it is available to editors too, not just approvers.
  const canExecute = userRole === 'admin' || userRole === 'manager' || userRole === 'editor';
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
      // Approval may revise a linked contract's total via the backend
      // subscriber - refresh contract views so the bumped value shows.
      queryClient.invalidateQueries({ queryKey: ['contracts'] });
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

  // Terminal FSM step approved -> executed: the work has actually been carried
  // out on site. Needs changeorders.update (editor level) on the backend; the
  // button is shown to admins/managers/editors so a controller can close it out.
  const executeMut = useMutation({
    mutationFn: () => apiPost<ChangeOrder>(`/v1/changeorders/${orderId}/execute/`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['changeorder', orderId] });
      queryClient.invalidateQueries({ queryKey: ['changeorders'] });
      queryClient.invalidateQueries({ queryKey: ['changeorders-summary'] });
      addToast({ type: 'success', title: t('changeorders.executed', { defaultValue: 'Change order marked as executed' }) });
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

  // ── T3: construction-management-platform-style approval chain ──────────
  // Fetched alongside the order detail so the timeline is always in sync
  // with the cursor. Cheap query — typically 1-5 rows.
  const { data: approvals = [] } = useQuery<ApprovalRow[]>({
    queryKey: ['changeorder-approvals', orderId],
    queryFn: () => getApprovals(orderId),
  });

  // Resolve approver UUIDs to display names for the timeline. Best-effort:
  // if the directory is unavailable (no users.list permission) the timeline
  // falls back to the id snippet on its own.
  const { data: directory = [] } = useQuery<DirectoryUser[]>({
    queryKey: ['users-directory'],
    queryFn: () => apiGet<DirectoryUser[]>('/v1/users/?limit=200&is_active=true'),
    staleTime: 60_000,
    enabled: approvals.length > 0,
  });
  const approverNames = useMemo(() => {
    const map: Record<string, string> = {};
    for (const u of directory) map[u.id] = userLabel(u);
    return map;
  }, [directory]);

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
            {/* Single-step Approve/Reject only applies to PLAIN change orders
                (no multi-step approval chain). Once an admin starts a chain,
                `approve_order` rejects this legacy path with HTTP 409 — so we
                hide these buttons and drive the decision through the
                ApprovalTimeline instead. */}
            {order.status === 'submitted' &&
              !order.current_approval_step &&
              approvals.length === 0 && (
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
            {/* Terminal step: an approved CO whose work has been done on site.
                Moves it approved -> executed so dashboards can tell committed
                from realised scope. */}
            {order.status === 'approved' && canExecute && (
              <Button variant="secondary" size="sm" onClick={async () => {
                const ok = await confirm({
                  title: t('changeorders.execute_confirm_title', { defaultValue: 'Mark as executed?' }),
                  message: t('changeorders.execute_confirm', { defaultValue: 'Mark this change order as executed? This records that the scope change has been carried out on site. It cannot be undone.' }),
                  variant: 'warning',
                });
                if (ok) executeMut.mutate();
              }} disabled={executeMut.isPending}>
                <CheckCheck size={14} className="mr-1.5" />
                {t('changeorders.mark_executed', { defaultValue: 'Mark as executed' })}
              </Button>
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
          {(() => {
            const impact = Number(order.cost_impact);
            return (
              <p className={`mt-1 text-sm font-semibold ${impact >= 0 ? 'text-semantic-error' : 'text-semantic-success'}`}>
                {impact >= 0 ? '+' : ''}{formatCurrency(impact, order.currency)}
              </p>
            );
          })()}
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

      {/* What-If impact simulator (TOP-30 #11). Hidden once a CO is rejected:
          there is nothing left to forecast. Publishing a scenario is allowed
          while the CO can still change (draft / submitted); the backend also
          enforces the changeorders.update permission. */}
      {order.status !== 'rejected' && (
        <ImpactSimulator
          orderId={orderId}
          defaultCost={order.cost_impact}
          defaultDays={order.schedule_impact_days}
          canPublish={order.status === 'draft' || order.status === 'submitted'}
          savedScenarios={
            Array.isArray((order.metadata as { simulations?: unknown[] })?.simulations)
              ? ((order.metadata as { simulations: SavedScenario[] }).simulations)
              : []
          }
        />
      )}

      {/* Audit trail. Each milestone has its own dedicated card keyed on its
          own timestamp column — a CO rejected straight from 'submitted' has
          only rejected_at, so reusing approved_at (BUG-351) used to hide the
          rejection entirely. */}
      {(order.submitted_at || order.approved_at || order.rejected_at) && (
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
                {t('changeorders.approved_at', { defaultValue: 'Approved' })}
              </p>
              <p className="mt-1 text-sm font-medium text-content-primary">{formatDate(order.approved_at)}</p>
              {order.approved_by && (
                <p className="mt-0.5 text-xs text-content-tertiary">{order.approved_by}</p>
              )}
            </Card>
          )}
          {order.rejected_at && (
            <Card className="p-4">
              <p className="text-xs text-semantic-error uppercase tracking-wide">
                {t('changeorders.rejected_at', { defaultValue: 'Rejected' })}
              </p>
              <p className="mt-1 text-sm font-medium text-content-primary">{formatDate(order.rejected_at)}</p>
              {order.rejected_by && (
                <p className="mt-0.5 text-xs text-content-tertiary">{order.rejected_by}</p>
              )}
            </Card>
          )}
        </div>
      )}

      {/* Related records — the commitment (PO) and RFI links the CO ties to,
          plus the source variation when this CO was mirrored from a variation
          order (service stamps origin + variation ids onto metadata). All ids
          are already on the GET /{id} payload; we just turn them into chips. */}
      {(() => {
        const poIds = order.linked_po_ids ?? [];
        const rfiIds = order.linked_rfi_ids ?? [];
        const meta = (order.metadata ?? {}) as {
          origin?: string;
          variation_order_id?: string;
          variation_request_id?: string;
          contract_id?: string;
        };
        const fromVariation =
          meta.origin === 'variations.convert_vr_to_vo' &&
          (meta.variation_order_id || meta.variation_request_id);
        const linkedContractId = meta.contract_id || '';
        if (poIds.length === 0 && rfiIds.length === 0 && !fromVariation && !linkedContractId) {
          return null;
        }
        const chipCls =
          'flex items-center gap-1.5 rounded-lg border border-blue-200 bg-blue-50 dark:bg-blue-950/20 dark:border-blue-800 px-2.5 py-1.5 text-xs text-blue-700 dark:text-blue-300 hover:bg-blue-100 transition-colors';
        return (
          <div className="mb-6">
            <h3 className="text-base font-semibold text-content-primary mb-3">
              {t('changeorders.related_records', { defaultValue: 'Related' })}
            </h3>
            <div className="flex flex-wrap items-center gap-2">
              {fromVariation && (
                <button
                  type="button"
                  className={chipCls}
                  onClick={() => navigate('/variations')}
                  title={t('changeorders.from_variation_hint', {
                    defaultValue: 'Open the variation order this change order was created from',
                  })}
                >
                  <GitBranch size={12} />
                  {t('changeorders.from_variation', { defaultValue: 'From variation' })}
                </button>
              )}
              {linkedContractId && (
                <button
                  type="button"
                  className={chipCls}
                  onClick={() => navigate('/contracts')}
                  title={linkedContractId}
                >
                  <FileText size={12} />
                  {t('changeorders.applies_to_contract', { defaultValue: 'Applies to contract' })}
                </button>
              )}
              {poIds.map((poId, i) => (
                <button
                  key={`po-${poId}`}
                  type="button"
                  className={chipCls}
                  onClick={() => navigate('/procurement')}
                  title={poId}
                >
                  <ShoppingCart size={12} />
                  {t('changeorders.linked_po', {
                    defaultValue: 'PO {{n}}',
                    n: i + 1,
                  })}
                </button>
              ))}
              {rfiIds.map((rfiId, i) => (
                <button
                  key={`rfi-${rfiId}`}
                  type="button"
                  className={chipCls}
                  onClick={() => navigate('/rfi')}
                  title={rfiId}
                >
                  <HelpCircle size={12} />
                  {t('changeorders.linked_rfi', {
                    defaultValue: 'RFI {{n}}',
                    n: i + 1,
                  })}
                </button>
              ))}
            </div>
          </div>
        );
      })()}

      {/* T3: construction-management-platform-style approval chain. Shown when the CO has either
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
          <InfoHint
            className="mb-3"
            text={
              approvals.length === 0
                ? t('changeorders.approval_chain_help_start', {
                    defaultValue:
                      'Optional: route this submitted change order through named approvers in sequence. Starting a chain replaces the single Approve/Reject buttons above - each approver then signs off step by step in the timeline below.',
                  })
                : t('changeorders.approval_chain_help_active', {
                    defaultValue:
                      'This change order is on a step-by-step approval chain. The single Approve/Reject buttons are disabled - the assigned approver records each decision in the timeline below, and a rejection at any step stops the chain.',
                  })
            }
          />
          <ApprovalTimeline
            rows={approvals}
            currentApprovalStep={order.current_approval_step ?? null}
            currentUserId={currentUserId}
            approverNames={approverNames}
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
                {order.items.map((item) => {
                  const costDelta = Number(item.cost_delta);
                  return (
                  <tr key={item.id} className="border-b border-border last:border-0 hover:bg-surface-secondary/30">
                    <td className="px-4 py-3 text-content-primary">{item.description}</td>
                    <td className="px-4 py-3">
                      <Badge variant={item.change_type === 'added' ? 'success' : item.change_type === 'removed' ? 'error' : 'neutral'}>
                        {t(`changeorders.type_${item.change_type}`, { defaultValue: item.change_type })}
                      </Badge>
                    </td>
                    <td className="px-4 py-3 text-right text-content-secondary tabular-nums">
                      {formatQuantity(item.original_quantity)} {item.unit}
                    </td>
                    <td className="px-4 py-3 text-right text-content-secondary tabular-nums">
                      {formatQuantity(item.new_quantity)} {item.unit}
                    </td>
                    <td className={`px-4 py-3 text-right font-medium tabular-nums ${costDelta >= 0 ? 'text-semantic-error' : 'text-semantic-success'}`}>
                      {costDelta >= 0 ? '+' : ''}{formatCurrency(costDelta, order.currency)}
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
                  );
                })}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      {showAddItem && (
        <AddItemDialog
          orderId={orderId}
          projectId={order.project_id}
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
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const activeProjectId = useProjectContextStore((s) => s.activeProjectId);
  const { confirm: confirmList, ...confirmListProps } = useConfirm();

  const [showCreate, setShowCreate] = useState(false);
  const [showAIDraft, setShowAIDraft] = useState(false);
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
    try {
      // Quote any field that may contain a comma / quote so a translated
      // reason label (some locales use commas) can't shift columns.
      const csvCell = (v: string) => `"${String(v).replace(/"/g, '""')}"`;
      const reasonLabels = getReasonLabels(t);
      const headers = [
        t('changeorders.code', { defaultValue: 'Code' }),
        t('common.title', { defaultValue: 'Title' }),
        t('common.status', { defaultValue: 'Status' }),
        t('changeorders.reason', { defaultValue: 'Reason' }),
        t('changeorders.cost_impact', { defaultValue: 'Cost Impact' }),
        t('changeorders.schedule_days', { defaultValue: 'Schedule Days' }),
        t('changeorders.items', { defaultValue: 'Line Items' }),
        t('common.created', { defaultValue: 'Created' }),
      ];
      const rows = filteredOrders.map((o) =>
        [
          csvCell(o.code),
          csvCell(o.title),
          csvCell(translateStatus(o.status, t)),
          csvCell(reasonLabels[o.reason_category] || o.reason_category),
          // cost_impact is a decimal STRING — coerce before toFixed or it
          // throws "toFixed is not a function" and aborts the whole export.
          Number(o.cost_impact).toFixed(2),
          String(o.schedule_impact_days),
          String(o.item_count),
          o.created_at?.slice(0, 10) || '',
        ].join(','),
      );
      const csv = [headers.map(csvCell).join(','), ...rows].join('\n');
      const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `change_orders_${project?.name || 'export'}.csv`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      addToast({
        type: 'error',
        title: t('changeorders.export_failed', { defaultValue: 'Export failed' }),
        message: err instanceof Error ? err.message : String(err),
      });
    }
  }, [filteredOrders, project, t, addToast]);

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
    <div className="space-y-5 animate-fade-in">
      <Breadcrumb items={[
        ...(project ? [{ label: project.name, to: `/projects/${project.id}` }] : []),
        { label: t('nav.change_orders', { defaultValue: 'Change Orders' }) },
      ]} />

      {/* Header — project selection lives in the global top bar; the page
          reads the shared project context and falls back to the first
          project, so no in-page project picker is rendered here. */}
      <PageHeader
        subtitle={t('changeorders.subtitle', { defaultValue: 'Track scope changes with cost and schedule impact' })}
        actions={
          <>
            <Button variant="secondary" icon={<Download size={14} />} onClick={handleExportCSV} disabled={!filteredOrders || filteredOrders.length === 0}>
              {t('changeorders.export_csv', { defaultValue: 'Export CSV' })}
            </Button>
            <Button variant="secondary" onClick={() => setShowAIDraft(true)} disabled={!projectId}>
              <Sparkles size={16} className="mr-1.5" />
              {t('changeorders.ai_draft', { defaultValue: 'AI Draft' })}
            </Button>
            <Button variant="primary" onClick={() => setShowCreate(true)} disabled={!projectId}>
              <Plus size={16} className="mr-1.5" />
              {t('changeorders.new', { defaultValue: 'New Change Order' })}
            </Button>
          </>
        }
      />

      <DismissibleInfo
        storageKey="changeorders"
        title={t('changeorders.intro_title', {
          defaultValue: 'Price every scope change before you commit it',
        })}
        more={
          t('changeorders.intro_more', { defaultValue: '' })
            ? <IntroRichText text={t('changeorders.intro_more')} />
            : undefined
        }
        links={[
          {
            label: t('nav.finance', { defaultValue: 'Finance' }),
            onClick: () => navigate('/finance'),
          },
          {
            label: t('nav.variations', { defaultValue: 'Variations' }),
            onClick: () => navigate('/variations'),
          },
          {
            // CONN-48: the three change pipelines (MoC, Variations, Change
            // Orders) stay connected. An approved Management-of-Change item is
            // the upstream decision a change order commits; surface it here so
            // the trail is one click away in either direction.
            label: t('moc.title', { defaultValue: 'Management of Change' }),
            onClick: () => navigate('/moc'),
          },
        ]}
      >
        {t('changeorders.intro_body', {
          defaultValue:
            'Capture each scope change with its line items, original versus new quantities and rates, and the system computes the cost delta and schedule impact for you. Route it through Draft, Submitted, Approved and Executed, optionally via a named approval chain, and an approved order is applied to the project budget as a revised commitment.',
        })}
      </DismissibleInfo>

      {/* Summary cards */}
      {summary && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
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
                {(() => {
                  const totalImpact = Number(summary.total_cost_impact);
                  const unconverted = Object.entries(summary.unconverted_by_currency ?? {});
                  return (
                    <>
                      <p className={`text-lg font-semibold ${totalImpact >= 0 ? 'text-semantic-error' : 'text-semantic-success'}`}>
                        {totalImpact >= 0 ? '+' : ''}{formatCurrency(totalImpact, summary.currency || currency)}
                      </p>
                      {unconverted.length > 0 && (
                        <p
                          className="mt-0.5 text-2xs text-content-tertiary leading-snug"
                          title={t('changeorders.unconverted_hint', {
                            defaultValue:
                              'Approved in a currency with no exchange rate. Add the rate in Project Settings to include it in the total.',
                          })}
                        >
                          {t('changeorders.plus_unconverted', { defaultValue: 'plus' })}{' '}
                          {unconverted
                            .map(([code, amount]) => `${formatCurrency(Number(amount), code)}`)
                            .join(', ')}
                        </p>
                      )}
                    </>
                  );
                })()}
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
      <div className="flex items-center gap-3">
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
                  {filteredOrders.map((order) => {
                    const impact = Number(order.cost_impact);
                    return (
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
                      <td className={`px-4 py-3 text-right font-medium tabular-nums ${impact >= 0 ? 'text-semantic-error' : 'text-semantic-success'}`}>
                        {impact >= 0 ? '+' : ''}{formatCurrency(impact, order.currency)}
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
                    );
                  })}
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
      {showAIDraft && projectId && (
        <AIDraftModal
          projectId={projectId}
          currency={currency}
          onClose={() => setShowAIDraft(false)}
          onCreated={(orderId) => {
            setShowAIDraft(false);
            handleRefresh();
            setSelectedOrderId(orderId);
          }}
        />
      )}
      <ConfirmDialog {...confirmListProps} />
    </div>
  );
}

export default ChangeOrdersPage;
