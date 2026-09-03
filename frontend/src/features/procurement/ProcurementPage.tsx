// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { useState, useMemo, useEffect, useRef, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useLocation, useNavigate } from 'react-router-dom';
import clsx from 'clsx';
import {
  Package,
  ClipboardCheck,
  Search,
  FileText,
  Wallet,
  Plus,
  X,
  Loader2,
  Trash2,
  Pencil,
  Send,
  CheckCircle2,
  Ban,
} from 'lucide-react';
import {
  Button,
  Card,
  Badge,
  EmptyState,
  Breadcrumb,
  RecoveryCard,
  SkeletonTable,
  DismissibleInfo,
  IntroRichText,
  ModuleGuideButton,
} from '@/shared/ui';
import { RequiresProject } from '@/shared/auth/RequiresProject';
import { PageHeader } from '@/shared/ui/PageHeader';
import { MoneyDisplay } from '@/shared/ui/MoneyDisplay';
import { DateDisplay } from '@/shared/ui/DateDisplay';
import { ContactSearchInput } from '@/shared/ui/ContactSearchInput';
import { apiGet, apiPost, apiPatch, type Page } from '@/shared/lib/api';
import { TruncationNotice } from '@/shared/ui/TruncationNotice';
import { useToastStore } from '@/stores/useToastStore';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { useActiveProjectId } from '@/shared/hooks/useActiveProjectId';
import { useAuthStore } from '@/stores/useAuthStore';
import { getPOMatchStatus, type POLineMatchTag } from './api';
import { PORemovalDialog, removalVerbFor } from './PORemovalDialog';
import { procurementGuide } from './procurementGuide';
import { SupplierScorecardModal } from './SupplierScorecardModal';
import { InsightsPanel, InsightsToggleButton, useModuleInsights } from '@/features/insights';
import { buildProcurementInsights } from './procurementInsights';
import { VendorPrequalBadge } from './VendorPrequalBadge';
import { BillPositionPicker } from './BillPositionPicker';
import { RetainagePanel, RetainageBadge } from './RetainagePanel';
import { POStatusPipeline } from './POStatusPipeline';
import { DeliveryCountdownBadge } from './DeliveryCountdownBadge';
import { RecordDeliveryModal } from './RecordDeliveryModal';
import { fmtFixed } from '@/shared/lib/formatters';
import { useRegisterLinks } from '@/modules/comms-intelligence/useRegisterLinks';
import { RegisterChip } from '@/modules/comms-intelligence/RegisterChip';
import type { LinkedItem } from '@/modules/comms-intelligence/registers-api';

// English fallbacks for the computed `procurement.gr_status_*` keys. The default used to be
// the raw value, so until the key lands in a locale the screen shows the bare
// enum token to every reader, English included. Unknown values still fall
// through to the previous default.
const GR_STATUS_LABELS: Record<string, string> = {
  draft: 'Draft', confirmed: 'Confirmed'
};


/* ── Types ─────────────────────────────────────────────────────────────── */

interface PurchaseOrder {
  id: string;
  project_id: string;
  po_number: string;
  vendor_name: string;
  vendor_contact_id?: string | null;
  issue_date: string;
  delivery_date: string | null;
  // Money bug fix: the list endpoint (POResponse in backend/.../schemas.py)
  // returns `amount_total` + `currency_code` (amount is a Decimal-serialized
  // STRING), NOT `total_amount`/`currency`. The old field names were always
  // undefined, so MoneyDisplay rendered an em-dash for every PO. Match the
  // real wire contract here.
  amount_total: string | number;
  currency_code: string;
  status: string;
  description: string;
  line_items_count: number;
  // ── Retainage (Gap F) ──────────────────────────────────────────────────
  // retention_percent / retain_on_receipt are persisted; retainage_amount /
  // retainage_held are computed by the backend. All Decimal-as-string.
  retention_percent?: string;
  retain_on_receipt?: boolean;
  retainage_amount?: string;
  retainage_held?: string;
  created_at: string;
  updated_at: string;
}

/**
 * One page of a project's purchase orders, envelope intact.
 *
 * Two useQuery calls in this file cache under `['procurement-po', projectId]`:
 * the Insights panel at page level and the Purchase Orders tab. React Query
 * keys are strings, so whichever runs first hands its value to the other -
 * they cannot hold different shapes. Both went through their own inline
 * `apiGet(...).then((res) => res.items.map(...))`, which agreed only because
 * someone kept them in step by hand. One function now, so the shape is not a
 * thing two call sites can disagree about, and the total survives.
 */
type POPage = Page<PurchaseOrder & { vendor_contact_id?: string | null }>;

async function fetchPOPage(projectId: string): Promise<POPage> {
  const page = await apiGet<POPage>(`/v1/procurement/?project_id=${projectId}`);
  return {
    ...page,
    items: page.items.map((po) => ({
      ...po,
      vendor_name: po.vendor_name ?? po.vendor_contact_id ?? '',
    })),
  };
}

interface POItemResponse {
  id: string;
  description: string;
  quantity: string | number;
  unit: string | null;
  unit_rate: string | number;
  amount: string | number;
  // Derived server-side from the cost line the item commits against, because
  // the money row holds no position column. Null for a line bought outside the
  // bill, and for one whose cost line came from no position.
  boq_position_id: string | null;
  sort_order: number;
}

/** Full PO detail returned by GET /v1/procurement/{po_id} (includes line items
 *  the list endpoint omits) - used to prefill the Edit form. */
interface POResponse {
  id: string;
  vendor_contact_id: string | null;
  vendor_name: string | null;
  po_number: string;
  po_type: string | null;
  issue_date: string;
  delivery_date: string | null;
  currency_code: string;
  amount_subtotal: string | number;
  tax_amount: string | number;
  amount_total: string | number;
  status: string;
  payment_terms: string | null;
  notes: string | null;
  items: POItemResponse[];
}

interface GoodsReceipt {
  id: string;
  po_id: string;
  po_number: string;
  // Aliased from the nullable delivery_note_number on the wire, so a receipt
  // recorded without a delivery note has no reference.
  gr_reference: string | null;
  receipt_date: string;
  status: string;
  // Decimal quantities arrive as STRINGS on the wire (GRResponse serialises
  // received_qty / ordered_qty via format(Decimal, "f")). Typing them as
  // `number` made the row's "fully received" highlight compare them
  // LEXICOGRAPHICALLY ("9" >= "100" -> true), so compare them numerically.
  received_qty: string | null;
  ordered_qty: string | null;
  description: string;
  created_at: string;
}

interface POLineItemForm {
  description: string;
  quantity: string;
  unit: string;
  unit_rate: string;
  amount: string;
  /**
   * The bill position this line is bought against, or null when the buyer has
   * not attributed it. Sent as `boq_position_id`; the server resolves it to the
   * cost line the money is committed to, which is why no cost line appears in
   * this form. See `backend/app/modules/procurement/cost_spine.py`.
   */
  boq_position_id: string | null;
}

/** The purchase-order fields the shared create / edit modal holds. */
interface POFormState {
  vendor_contact_id: string;
  vendor_display: string;
  po_type: 'standard' | 'blanket' | 'service';
  delivery_date: string;
  currency: string;
  payment_terms: string;
  notes: string;
  items: POLineItemForm[];
}

/**
 * The form state an existing purchase order opens with.
 *
 * Pure and exported so the save can rebuild the same baseline the modal was
 * seeded from and send only what the user actually changed. Correcting a
 * delivery date used to PATCH the vendor, the terms, the notes and every line
 * back, exactly as they stood when this copy was fetched, undoing anyone else's
 * edit to them without a word. The update route dumps with `exclude_unset=True`,
 * so a field left out of the body is left alone in the database.
 *
 * The payment terms round-trip through a sentence (`Net 30`), so the number is
 * dug back out here and nowhere else; two readings of that string would make an
 * untouched field look edited.
 */
function poFormFromResponse(po: POResponse, projectCurrency: string): POFormState {
  const payTermMatch = (po.payment_terms ?? '').match(/(\d+)/);
  return {
    vendor_contact_id: po.vendor_contact_id ?? '',
    vendor_display: po.vendor_name ?? '',
    po_type: po.po_type === 'blanket' || po.po_type === 'service' ? po.po_type : 'standard',
    delivery_date: po.delivery_date ?? '',
    currency: po.currency_code || projectCurrency || '',
    payment_terms: payTermMatch?.[1] ?? '30',
    notes: po.notes ?? '',
    items:
      po.items && po.items.length > 0
        ? po.items.map((it) => ({
            description: it.description ?? '',
            quantity: it.quantity != null ? String(it.quantity) : '1',
            unit: it.unit ?? '',
            unit_rate: it.unit_rate != null ? String(it.unit_rate) : '',
            amount: it.amount != null ? String(it.amount) : '',
            // Read back so an edit that touches the delivery date does not
            // quietly send the line back unattributed. The picker resolves the
            // id to a readable position even when it sorts past the first page.
            boq_position_id: it.boq_position_id ?? null,
          }))
        : [{ description: '', quantity: '1', unit: '', unit_rate: '', amount: '', boq_position_id: null }],
  };
}

/**
 * True when a goods receipt's received quantity covers (>=) the ordered
 * quantity. ``received_qty`` / ``ordered_qty`` are Decimal STRINGS on the
 * wire, so they MUST be parsed to numbers before comparing - a raw string
 * ``>=`` compares lexicographically ("9" >= "100" -> true). Returns false
 * when nothing was ordered so empty rows are never highlighted as complete.
 */
export function isGoodsReceiptFullyReceived(
  receivedQty: string | number | null | undefined,
  orderedQty: string | number | null | undefined,
): boolean {
  const ordered = Number(orderedQty ?? 0);
  const received = Number(receivedQty ?? 0);
  if (!Number.isFinite(ordered) || !Number.isFinite(received)) return false;
  return ordered > 0 && received >= ordered;
}

/**
 * Normalise a router-state buy-list handoff (from the Resource Summary
 * buy-list, F4 interop) into PO line-item form rows. Router state is untyped,
 * so every field is validated defensively: a non-array input, or an entry with
 * no description, is dropped. Quantities are the Decimal STRINGS the backend
 * served - carried through verbatim (never parsed to a float); unit_rate and
 * amount are left blank for the buyer to fill in from the supplier quote.
 */
export function parseIncomingBuyList(raw: unknown): POLineItemForm[] {
  if (!Array.isArray(raw)) return [];
  const lines: POLineItemForm[] = [];
  for (const entry of raw) {
    if (!entry || typeof entry !== 'object') continue;
    const rec = entry as Record<string, unknown>;
    const description = typeof rec.description === 'string' ? rec.description.trim() : '';
    if (!description) continue;
    const unit = typeof rec.unit === 'string' ? rec.unit : '';
    const quantity =
      typeof rec.quantity === 'string'
        ? rec.quantity
        : typeof rec.quantity === 'number'
          ? String(rec.quantity)
          : '';
    lines.push({
      description,
      quantity: quantity || '1',
      unit,
      unit_rate: '',
      amount: '',
      // The buy-list hands over a resource, not a bill position, so the buyer
      // still attributes each line themselves.
      boq_position_id: null,
    });
  }
  return lines;
}

/* ── Constants ────────────────────────────────────────────────────────── */

const inputCls =
  'h-10 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';

/** Common currency shortlist - NOT a default. The PO's actual currency is
 *  inherited from the project (task #217); the project's resolved currency
 *  is merged in so any project currency stays selectable. */
const COMMON_CURRENCIES = [
  'EUR', 'USD', 'GBP', 'CHF', 'PLN', 'CZK', 'SEK', 'NOK', 'DKK', 'AED', 'SAR',
] as const;

function currencyOptions(active: string): string[] {
  const a = (active || '').trim().toUpperCase();
  if (a && /^[A-Z]{3}$/.test(a) && !COMMON_CURRENCIES.includes(a as never)) {
    return [a, ...COMMON_CURRENCIES];
  }
  return [...COMMON_CURRENCIES];
}

type ProcurementTab = 'purchase-orders' | 'goods-receipts';

const PO_STATUS_COLORS: Record<
  string,
  'neutral' | 'blue' | 'success' | 'warning' | 'error'
> = {
  draft: 'neutral',
  pending: 'warning',
  approved: 'blue',
  issued: 'blue',
  partial: 'warning',
  received: 'success',
  completed: 'success',
  cancelled: 'error',
  closed: 'neutral',
};

const GR_STATUS_COLORS: Record<
  string,
  'neutral' | 'blue' | 'success' | 'warning' | 'error'
> = {
  // The GR FSM the backend actually emits is draft -> confirmed (see the
  // GoodsReceipt model). A draft delivery is awaiting confirmation (amber);
  // a confirmed one has rolled up into the PO + budget (green). Without
  // these two keys both statuses fell through to a neutral grey badge.
  draft: 'warning',
  confirmed: 'success',
  // Legacy / forward-compat tags kept so a future status set still colours.
  pending: 'warning',
  partial: 'warning',
  complete: 'success',
  rejected: 'error',
};

/* ── Main Page ────────────────────────────────────────────────────────── */

export function ProcurementPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const location = useLocation();
  const projectId = useActiveProjectId();
  const projectName = useProjectContextStore((s) => s.activeProjectName);

  const [activeTab, setActiveTab] = useState<ProcurementTab>('purchase-orders');

  // F4 interop: the Resource Summary buy-list hands its material lines over as
  // router state so a buyer can turn the estimate straight into a draft PO.
  // Parse it once per state change; the Purchase Orders tab consumes it and
  // pre-fills the create flow. We then clear the state (below) so a refresh or
  // back-navigation doesn't reopen the draft.
  const incomingBuyList = useMemo(
    () => parseIncomingBuyList((location.state as { buyList?: unknown } | null)?.buyList),
    [location.state],
  );

  const clearIncomingBuyList = useCallback(() => {
    navigate(location.pathname, { replace: true, state: null });
  }, [navigate, location.pathname]);

  // Module Insights panel. Charts the purchase orders THIS PAGE LOADED - the
  // register that carries each order's committed value, supplier and delivery
  // status - so a chart slice reads like the status badge on the row it came
  // from. The list reuses the ['procurement-po', projectId] query the Purchase
  // Orders tab already loads (same key and queryFn, so it is a cache hit and
  // the tab's own invalidations keep it fresh). Currency rides the finance
  // dashboard query. These hooks sit with the other top-level hooks, above any
  // conditional render, so the hook order stays stable.
  //
  // Known limit, stated rather than papered over: the list endpoint returns 50
  // orders by default and caps at 100, so on a project past that the totals
  // this panel reduces out of `insightOrders` describe a page, not a project.
  // A TruncationNotice next to a wrong number would read as coverage. The real
  // fix is server-side aggregates, and /v1/procurement/stats/ already computes
  // some of them for the reporting page - backend scope, not this wave.
  const { data: insightPage } = useQuery({
    queryKey: ['procurement-po', projectId],
    queryFn: () => fetchPOPage(projectId!),
    enabled: !!projectId,
  });
  const insightOrders = useMemo(() => insightPage?.items ?? [], [insightPage]);
  const { data: insightDashboard } = useQuery({
    queryKey: ['finance', 'dashboard', projectId],
    queryFn: () =>
      apiGet<{ currency: string }>(`/v1/finance/dashboard/?project_id=${projectId}`),
    enabled: !!projectId,
  });
  const insights = useModuleInsights('procurement', { defaultOpen: true });
  const { datasets: insightDatasets, builtins: insightBuiltins } = useMemo(
    () => buildProcurementInsights(insightOrders, insightDashboard?.currency || 'EUR', t),
    [insightOrders, insightDashboard, t],
  );

  const tabs: { key: ProcurementTab; label: string; icon: React.ReactNode }[] = [
    {
      key: 'purchase-orders',
      label: t('procurement.purchase_orders', { defaultValue: 'Purchase Orders' }),
      icon: <Package size={15} />,
    },
    {
      key: 'goods-receipts',
      label: t('procurement.goods_receipts', { defaultValue: 'Goods Receipts' }),
      icon: <ClipboardCheck size={15} />,
    },
  ];

  return (
    <div className="space-y-5 animate-fade-in">
      <Breadcrumb
        items={[
          ...(projectName
            ? [{ label: projectName, to: `/projects/${projectId}` }]
            : []),
          { label: t('procurement.title', { defaultValue: 'Procurement' }) },
        ]}
      />

      {/* Header - the module name + icon live in the global top bar; the
          page renders only its subtitle. Project selection is global too.
          srTitle gives the page its single semantic <h1> (sr-only) for a11y. */}
      <PageHeader
        srTitle={t('procurement.title', { defaultValue: 'Procurement' })}
        subtitle={t('procurement.subtitle', {
          defaultValue: 'Purchase orders and goods receipts',
        })}
        actions={
          <>
            <InsightsToggleButton open={insights.open} onClick={insights.toggle} />
            <ModuleGuideButton content={procurementGuide} />
          </>
        }
      />

      {/* Module Insights panel - toggled by the header button. Placed high so
          its charts are visible the moment Procurement opens. */}
      <InsightsPanel
        open={insights.open}
        title={t('procurement.insights.title', { defaultValue: 'Procurement insights' })}
        datasets={insightDatasets}
        builtins={insightBuiltins}
        custom={insights.custom}
        onAdd={insights.addCustom}
        onUpdate={insights.updateCustom}
        onRemove={insights.removeCustom}
        onCollapse={() => insights.setOpen(false)}
      />

      {/* Canonical info block - where procurement sits in the money flow,
          with cross-module pills for the routes its results flow to. */}
      <DismissibleInfo
        storageKey="procurement"
        title={t('procurement.intro_title', {
          defaultValue: 'See committed spend before the invoice lands',
        })}
        more={
          t('procurement.intro_more', { defaultValue: '' })
            ? <IntroRichText text={t('procurement.intro_more')} />
            : undefined
        }
        links={[
          {
            label: t('nav.finance', { defaultValue: 'Finance' }),
            onClick: () => navigate('/finance'),
          },
          {
            label: t('nav.supplier_catalogs', { defaultValue: 'Supplier Catalogs' }),
            onClick: () => navigate('/supplier-catalogs'),
          },
          {
            label: t('nav.contacts', { defaultValue: 'Contacts' }),
            onClick: () => navigate('/contacts'),
          },
        ]}
      >
        {t('procurement.intro_body', {
          defaultValue:
            'Raise a purchase order to commit budget with a vendor, record a goods receipt when the delivery arrives, then create an invoice from the PO to push the amount into Finance as a payable. PO totals roll up into the project budget as committed and become actual once the invoice is paid.',
        })}
      </DismissibleInfo>

      {/* No-project warning */}
      {!projectId && (
        <div className="rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800 dark:border-amber-800 dark:bg-amber-950/30 dark:text-amber-300">
          {t('common.select_project_hint', { defaultValue: 'Select a project from the header to get started.' })}
        </div>
      )}

      {/* Tab Bar */}
      <div
        className="flex items-center gap-1 border-b border-border-light"
        role="tablist"
        aria-label={t('procurement.title', { defaultValue: 'Procurement' })}
      >
        {tabs.map((tab) => (
          <button
            key={tab.key}
            type="button"
            role="tab"
            aria-selected={activeTab === tab.key}
            onClick={() => setActiveTab(tab.key)}
            className={`
              flex items-center gap-2 px-4 py-2.5 text-sm font-medium border-b-2 transition-all
              ${
                activeTab === tab.key
                  ? 'border-oe-blue text-oe-blue'
                  : 'border-transparent text-content-tertiary hover:text-content-primary hover:bg-surface-secondary'
              }
            `}
          >
            {tab.icon}
            {tab.label}
          </button>
        ))}
      </div>

      {/* Tab Content */}
      {!projectId ? (
        <RequiresProject
          emptyHint={t('procurement.select_project', {
            defaultValue:
              'Open a project first to view its procurement data',
          })}
        >{null}</RequiresProject>
      ) : (
        <>
          {activeTab === 'purchase-orders' && (
            <PurchaseOrdersTab
              projectId={projectId}
              incomingBuyList={incomingBuyList}
              onBuyListConsumed={clearIncomingBuyList}
            />
          )}
          {activeTab === 'goods-receipts' && (
            <GoodsReceiptsTab
              projectId={projectId}
              onGoToPurchaseOrders={() => setActiveTab('purchase-orders')}
            />
          )}
        </>
      )}
    </div>
  );
}

/* ── Purchase Orders Tab ──────────────────────────────────────────────── */

function PurchaseOrdersTab({
  projectId,
  incomingBuyList,
  onBuyListConsumed,
}: {
  projectId: string;
  incomingBuyList: POLineItemForm[];
  onBuyListConsumed: () => void;
}) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [search, setSearch] = useState('');
  const addToast = useToastStore((s) => s.addToast);
  const userRole = useAuthStore((s) => s.userRole);
  const isManager = userRole === 'admin' || userRole === 'manager';
  // Which POs were raised through the order register - one call for the
  // page, keyed by PO id, so each row can wear its REG-ORD chip.
  const registerLinks = useRegisterLinks(projectId, 'order');

  // 3-way match: rows hovered or focused fetch their match status on demand
  // (we never bulk-fetch on list load to avoid N×fetch on big projects).
  const [matchActive, setMatchActive] = useState<Record<string, boolean>>({});
  // Supplier scorecard modal - opened from the supplier name link in a row.
  const [scorecardOpen, setScorecardOpen] = useState<
    { contactId: string; name?: string | null } | null
  >(null);
  // Retainage panel (Gap F) - opened from a PO row's "Retainage" action.
  const [retainagePO, setRetainagePO] = useState<PurchaseOrder | null>(null);
  // Removal confirm - opened from a PO row's delete / cancel action. Which of
  // the two verbs it offers is decided from the row's status by
  // `removalVerbFor`; the backend has the final say and refuses with a 409
  // that the dialog renders as readable text.
  const [removingPO, setRemovingPO] = useState<PurchaseOrder | null>(null);

  // Resolve the project's currency from the finance dashboard so new POs
  // default to it instead of a hardcoded EUR (task #217). Empty string when
  // the project has no priced financial records yet.
  const { data: poDashboard } = useQuery({
    queryKey: ['finance', 'dashboard', projectId],
    queryFn: () =>
      apiGet<{ currency: string }>(`/v1/finance/dashboard/?project_id=${projectId}`),
  });
  const projectCurrency = poDashboard?.currency || '';

  /* ── PO create / edit modal state ──
     The same modal serves both flows. When `editingPO` holds a PO id the
     form was prefilled from GET /{po_id} and the submit button PATCHes that
     order; otherwise it POSTs a new one. */
  const [showCreate, setShowCreate] = useState(false);
  const [editingPO, setEditingPO] = useState<string | null>(null);
  // True only while the create modal is showing lines handed over from the
  // Resource Summary buy-list (F4 interop), so we can surface a one-line hint
  // telling the buyer to add a supplier + rates. Reset whenever the modal closes.
  const [prefilledFromBuyList, setPrefilledFromBuyList] = useState(false);
  const todayStr = new Date().toISOString().split('T')[0];
  const emptyLine: POLineItemForm = {
    description: '', quantity: '1', unit: '', unit_rate: '', amount: '', boq_position_id: null,
  };

  const [poForm, setPoForm] = useState<POFormState>({
    vendor_contact_id: '',
    vendor_display: '',
    po_type: 'standard' as 'standard' | 'blanket' | 'service',
    delivery_date: '',
    currency: '',
    payment_terms: '30',
    notes: '',
    items: [{ ...emptyLine }] as POLineItemForm[],
  });
  // The state an edit prefill left the form in, so the save can send only what
  // the user actually changed. `null` outside edit mode. See
  // `poFormFromResponse`.
  const [poBase, setPoBase] = useState<{ form: POFormState; tax: string } | null>(null);
  const [poErrors, setPoErrors] = useState<Record<string, string>>({});
  const [poTaxInput, setPoTaxInput] = useState('0');
  const firstFieldRef = useRef<HTMLDivElement>(null);

  const emptyPoForm = {
    vendor_contact_id: '', vendor_display: '', po_type: 'standard' as 'standard' | 'blanket' | 'service',
    delivery_date: '', currency: '', payment_terms: '30',
    notes: '', items: [{ ...emptyLine }] as POLineItemForm[],
  };

  // Seed the currency from the resolved project currency when the create
  // modal opens with a blank form (never overrides an edit prefill or a
  // value the user already picked).
  useEffect(() => {
    if (showCreate && !editingPO && !poForm.currency && projectCurrency) {
      setPoForm((f) => ({ ...f, currency: projectCurrency }));
    }
  }, [showCreate, editingPO, projectCurrency, poForm.currency]);

  const closeModal = () => {
    setShowCreate(false);
    setEditingPO(null);
    setPrefilledFromBuyList(false);
    setPoForm({ ...emptyPoForm, items: [{ ...emptyLine }] });
    setPoBase(null);
    setPoTaxInput('0');
    setPoErrors({});
  };

  // Escape key handler
  useEffect(() => {
    if (!showCreate) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') closeModal();
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [showCreate]);

  // F4 interop: when Procurement was opened from the Resource Summary buy-list,
  // pre-fill the create flow with those material lines and open it. A ref makes
  // this a once-only hand-off, so reopening or editing the modal afterwards is
  // never clobbered; once consumed we ask the parent to clear the router state
  // so the draft is not reopened on a refresh or back-navigation.
  const buyListConsumedRef = useRef(false);
  useEffect(() => {
    if (buyListConsumedRef.current) return;
    if (incomingBuyList.length === 0) return;
    buyListConsumedRef.current = true;
    setEditingPO(null);
    setPoForm((f) => ({ ...f, items: incomingBuyList.map((li) => ({ ...li })) }));
    setPrefilledFromBuyList(true);
    setShowCreate(true);
    onBuyListConsumed();
  }, [incomingBuyList, onBuyListConsumed]);

  // Auto-calc line amounts
  const updateLineItem = (idx: number, field: keyof POLineItemForm, value: string) => {
    setPoForm((prev) => {
      const items: POLineItemForm[] = prev.items.map((li, i) => (i === idx ? { ...li, [field]: value } : li));
      const updated = items[idx];
      if (updated && (field === 'quantity' || field === 'unit_rate')) {
        const qty = parseFloat(updated.quantity || '0');
        const rate = parseFloat(updated.unit_rate || '0');
        updated.amount = (qty * rate).toFixed(2);
      }
      return { ...prev, items };
    });
  };

  // Its own setter rather than a `updateLineItem` call: that one takes a
  // string and recomputes the amount from qty x rate, and neither applies to a
  // position id that may legitimately be null.
  const setLinePosition = (idx: number, boqPositionId: string | null) => {
    setPoForm((prev) => ({
      ...prev,
      items: prev.items.map((li, i) => (i === idx ? { ...li, boq_position_id: boqPositionId } : li)),
    }));
  };

  const addLineItem = () => {
    setPoForm((prev) => ({ ...prev, items: [...prev.items, { ...emptyLine }] }));
  };

  const removeLineItem = (idx: number) => {
    setPoForm((prev) => {
      const items = prev.items.filter((_, i) => i !== idx);
      return { ...prev, items: items.length === 0 ? [{ ...emptyLine }] : items };
    });
  };

  // Computed totals
  const poSubtotal = poForm.items.reduce((s, li) => s + parseFloat(li.amount || '0'), 0);
  const poTotal = poSubtotal + parseFloat(poTaxInput || '0');
  // What to show as the amount prefix in the modal - the chosen currency,
  // else the resolved project currency, else a neutral label (never EUR).
  const displayCurrency =
    poForm.currency ||
    projectCurrency ||
    t('procurement.project_currency', { defaultValue: 'project currency' });

  const canSubmitPO = poForm.items.some((li) => li.description.trim().length > 0);

  // Surface the non-blocking vendor-prequalification warnings the PO
  // create/update gate returns (TOP-30 #20). A hard-blocked vendor never
  // reaches here - the backend raises 409 and the error toast fires instead.
  const warnIfVendorFlagged = (warnings?: string[]) => {
    if (!warnings || warnings.length === 0) return;
    addToast({
      type: 'warning',
      title: t('procurement.vendor_not_prequalified_warning_title', {
        defaultValue: 'Vendor not prequalified',
      }),
      message: t('procurement.vendor_not_prequalified_warning', {
        defaultValue:
          'This vendor is not prequalified. The purchase order was saved, but review the vendor before issuing it.',
      }),
    });
  };

  const validatePO = (): boolean => {
    const e: Record<string, string> = {};
    const hasAnyItem = poForm.items.some((li) => li.description.trim());
    if (!hasAnyItem) e.items = t('validation.required', { defaultValue: 'Add at least one item' });
    setPoErrors(e);
    return Object.keys(e).length === 0;
  };

  const createPOMut = useMutation({
    mutationFn: (data: typeof poForm) =>
      apiPost<{ vendor_warnings?: string[] }>('/v1/procurement/', {
        project_id: projectId,
        vendor_contact_id: data.vendor_contact_id || undefined,
        po_type: data.po_type,
        issue_date: todayStr,
        delivery_date: data.delivery_date || undefined,
        currency_code: data.currency,
        amount_subtotal: String(poSubtotal.toFixed(2)),
        tax_amount: poTaxInput || '0',
        amount_total: String(poTotal.toFixed(2)),
        payment_terms: `Net ${data.payment_terms}`,
        notes: data.notes || undefined,
        status: 'draft',
        items: data.items
          .filter((li) => li.description.trim())
          .map((li, idx) => ({
            description: li.description,
            quantity: li.quantity || '1',
            unit: li.unit || undefined,
            unit_rate: li.unit_rate || '0',
            amount: li.amount || '0',
            // Omitted rather than sent as null when the line is unattributed:
            // the field is optional on POItemCreate and an absent one reads the
            // same as an unlinked line without asking the server to resolve it.
            boq_position_id: li.boq_position_id || undefined,
            sort_order: idx,
          })),
      }),
    onSuccess: (res) => {
      queryClient.invalidateQueries({ queryKey: ['procurement-po', projectId] });
      closeModal();
      addToast({ type: 'success', title: t('procurement.po_created', { defaultValue: 'Purchase order created' }) });
      warnIfVendorFlagged(res?.vendor_warnings);
    },
    onError: (e: Error) =>
      addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: e.message }),
  });

  /* ── PO edit ──
     Every field except `status` is freely editable here. Status transitions go
     through the dedicated workflow actions (approve / issue / cancel /
     create-invoice), so we deliberately omit `status` from this body.
     Removal is its own affordance: `PORemovalDialog` deletes a never-issued
     draft and cancels anything else, and both are refused with a 409 when
     another record still points at the order. */
  const editPOMut = useMutation({
    mutationFn: ({ id, data }: { id: string; data: POFormState }) => {
      // Only what the user actually edited goes back. The baseline is the state
      // the prefill left the form in, so a field nobody opened is omitted and
      // whatever somebody else did to it in the meantime survives.
      const base = poBase?.form ?? data;
      const baseTax = poBase?.tax ?? poTaxInput;
      const itemsChanged = JSON.stringify(data.items) !== JSON.stringify(base.items);
      const taxChanged = poTaxInput !== baseTax;
      const body: Record<string, unknown> = {};
      if (data.vendor_contact_id !== base.vendor_contact_id) {
        body.vendor_contact_id = data.vendor_contact_id || undefined;
      }
      if (data.po_type !== base.po_type) body.po_type = data.po_type;
      if (data.delivery_date !== base.delivery_date) {
        body.delivery_date = data.delivery_date || undefined;
      }
      if (data.currency !== base.currency) body.currency_code = data.currency;
      if (data.payment_terms !== base.payment_terms) {
        body.payment_terms = `Net ${data.payment_terms}`;
      }
      if (data.notes !== base.notes) body.notes = data.notes || undefined;
      if (itemsChanged) {
        body.items = data.items
          .filter((li) => li.description.trim())
          .map((li, idx) => ({
            description: li.description,
            quantity: li.quantity || '1',
            unit: li.unit || undefined,
            amount: li.amount || '0',
            unit_rate: li.unit_rate || '0',
            boq_position_id: li.boq_position_id || undefined,
            sort_order: idx,
          }));
        body.amount_subtotal = String(poSubtotal.toFixed(2));
      }
      if (taxChanged) body.tax_amount = poTaxInput || '0';
      // The total is the sum of the two, so it moves whenever either does.
      if (itemsChanged || taxChanged) body.amount_total = String(poTotal.toFixed(2));
      return apiPatch<{ vendor_warnings?: string[] }>(`/v1/procurement/${id}`, body);
    },
    onSuccess: (res) => {
      queryClient.invalidateQueries({ queryKey: ['procurement-po', projectId] });
      closeModal();
      addToast({ type: 'success', title: t('procurement.po_updated', { defaultValue: 'Purchase order updated' }) });
      warnIfVendorFlagged(res?.vendor_warnings);
    },
    onError: (e: Error) =>
      addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: e.message }),
  });

  /* Fetch full PO (incl. line items the list omits) then prefill the shared
     create form and switch the modal into edit mode. */
  const openEditMut = useMutation({
    mutationFn: (poId: string) => apiGet<POResponse>(`/v1/procurement/${poId}`),
    onSuccess: (po) => {
      // Seeded from the same function the save compares against, so the two
      // can never drift apart. See `poFormFromResponse`.
      const seeded = poFormFromResponse(po, projectCurrency);
      const tax = po.tax_amount != null ? String(po.tax_amount) : '0';
      setPoForm(seeded);
      setPoBase({ form: seeded, tax });
      setPoTaxInput(tax);
      setPoErrors({});
      setEditingPO(po.id);
      setShowCreate(true);
    },
    onError: (e: Error) =>
      addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: e.message }),
  });

  /* ── PO approve ──
     Transitions a draft PO to `approved`. This is the commitment moment
     (TOP-30 #10): the backend publishes procurement.po.approved, which
     finance turns into a live ProjectBudget.committed increase. A PO must
     be approved before it can be issued, so the budget reflects authorised
     spend the instant it is approved, not when paperwork is sent. We refresh
     the PO list (status pipeline + Approve→Issue button swap) and the finance
     dashboard so the committed figure updates without a manual reload. */
  const approvePOMut = useMutation({
    mutationFn: (poId: string) =>
      apiPost(`/v1/procurement/${poId}/approve/`, {}),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['procurement-po', projectId] });
      queryClient.invalidateQueries({ queryKey: ['finance', 'dashboard', projectId] });
      addToast({
        type: 'success',
        title: t('procurement.po_approved_toast', {
          defaultValue: 'Purchase order approved',
        }),
        message: t('procurement.po_approved_committed', {
          defaultValue: 'Budget committed. You can now issue it to the vendor.',
        }),
      });
    },
    onError: (e: Error) =>
      addToast({
        type: 'error',
        title: t('common.error', { defaultValue: 'Error' }),
        message: e.message,
      }),
  });

  /* ── PO issue ──
     Transitions an approved PO to `issued`. The backend enforces the FSM
     (only approved→issued; see _PO_STATUS_TRANSITIONS in service.py) and
     audit-logs the transition. After success we re-run the PO list query
     so the status pipeline and Issue/Invoice button visibility update
     in place. */
  const issuePOMut = useMutation({
    mutationFn: (poId: string) =>
      apiPost(`/v1/procurement/${poId}/issue/`, {}),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['procurement-po', projectId] });
      addToast({
        type: 'success',
        title: t('procurement.po_issued_toast', {
          defaultValue: 'Purchase order issued',
        }),
      });
    },
    onError: (e: Error) =>
      addToast({
        type: 'error',
        title: t('common.error', { defaultValue: 'Error' }),
        message: e.message,
      }),
  });

  const createInvoiceMut = useMutation({
    mutationFn: (poId: string) =>
      apiPost<{ invoice_id: string; invoice_number: string; po_number: string }>(
        `/v1/procurement/${poId}/create-invoice/`,
        {},
      ),
    onSuccess: (data) => {
      // Creating an invoice can advance PO-derived counts and posts a new
      // payable, so refresh both the PO list and the Finance views that
      // surface it (dashboard rollup + invoice list).
      queryClient.invalidateQueries({ queryKey: ['procurement-po', projectId] });
      queryClient.invalidateQueries({ queryKey: ['finance', 'dashboard', projectId] });
      queryClient.invalidateQueries({ queryKey: ['finance-invoices', projectId] });
      addToast({
        type: 'success',
        title: t('procurement.invoice_created', { defaultValue: 'Invoice created' }),
        message: `${data.invoice_number} from PO ${data.po_number}`,
      });
    },
    onError: (e: Error) =>
      addToast({
        type: 'error',
        title: t('common.error', { defaultValue: 'Error' }),
        message: e.message,
      }),
  });

  const { data: ordersPage, isLoading, isError, error, refetch } = useQuery({
    queryKey: ['procurement-po', projectId],
    queryFn: () => fetchPOPage(projectId),
  });
  const orders = ordersPage?.items;

  const filtered = useMemo(() => {
    if (!orders) return [];
    if (!search) return orders;
    const q = search.toLowerCase();
    return orders.filter(
      (po) =>
        (po.po_number ?? '').toLowerCase().includes(q) ||
        (po.vendor_name ?? '').toLowerCase().includes(q),
    );
  }, [orders, search]);

  if (isLoading) return <SkeletonTable rows={5} columns={6} />;

  if (isError) {
    return (
      <Card className="py-12">
        <RecoveryCard error={error} onRetry={() => refetch()} />
      </Card>
    );
  }

  if (!orders || orders.length === 0) {
    return (
      <>
        <EmptyState
          icon={<Package size={28} strokeWidth={1.5} />}
          title={t('procurement.no_po', {
            defaultValue: 'No purchase orders yet',
          })}
          description={t('procurement.no_po_desc', {
            defaultValue: 'Create your first purchase order to start tracking procurement.',
          })}
          action={{
            label: t('procurement.new_po', { defaultValue: 'New Purchase Order' }),
            onClick: () => setShowCreate(true),
          }}
        />
        {showCreate && renderPOModal()}
      </>
    );
  }

  /* ── Render PO create / edit modal ── */
  function renderPOModal() {
    const isEdit = editingPO !== null;
    const modalTitle = isEdit
      ? t('procurement.edit_po', { defaultValue: 'Edit purchase order' })
      : t('procurement.new_po', { defaultValue: 'New Purchase Order' });
    return (
      <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-lg animate-fade-in">
        <div className="w-full max-w-5xl bg-surface-elevated rounded-xl shadow-xl border border-border animate-card-in mx-4 max-h-[88vh] flex flex-col" role="dialog" aria-modal="true" aria-label={modalTitle}>
          <div className="flex items-center justify-between px-6 py-4 border-b border-border-light sticky top-0 z-10 bg-surface-elevated rounded-t-xl">
            <h2 className="text-lg font-semibold text-content-primary">
              {modalTitle}
            </h2>
            <button
              onClick={closeModal}
              aria-label={t('common.close', { defaultValue: 'Close' })}
              className="flex h-8 w-8 items-center justify-center rounded-lg text-content-tertiary hover:bg-surface-secondary hover:text-content-primary transition-colors"
            >
              <X size={18} />
            </button>
          </div>
          <div className="px-6 py-5 space-y-5 overflow-y-auto flex-1">
            {/* F4 interop hint: shown only when the lines were pre-filled from
                the Resource Summary buy-list, to explain the auto-opened modal
                and prompt the buyer for the supplier + rates the buy-list omits. */}
            {prefilledFromBuyList && !isEdit && (
              <div className="rounded-lg border border-oe-blue/30 bg-oe-blue/5 px-3.5 py-2.5 text-xs text-content-secondary">
                {t('procurement.prefilled_from_buy_list', {
                  defaultValue:
                    'These lines came from the estimate buy-list. Pick a supplier and enter rates, then save to create the draft purchase order.',
                })}
              </div>
            )}
            {/* ── Section: Order Details ──
                The widened modal (max-w-5xl) gives us room to surface
                vendor + PO type + delivery date as a single 3-column row
                on >=lg breakpoints, while still collapsing cleanly on
                phones. The previous single-column stack made the form
                feel "narrow" even on a 27" monitor. */}
            <div>
              <h3 className="text-xs font-semibold uppercase tracking-wider text-content-tertiary mb-3">
                {t('procurement.section_order_details', { defaultValue: 'Order Details' })}
              </h3>
              <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
                {/* Vendor - takes 2 columns on lg to keep the search input usable */}
                <div ref={firstFieldRef} className="lg:col-span-2">
                  <label className="block text-sm font-medium text-content-primary mb-1.5">
                    {t('procurement.vendor', { defaultValue: 'Vendor' })}
                  </label>
                  <ContactSearchInput
                    value={poForm.vendor_contact_id}
                    displayValue={poForm.vendor_display}
                    onChange={(id, name) => setPoForm((f) => ({ ...f, vendor_contact_id: id, vendor_display: name }))}
                    placeholder={t('procurement.search_vendor', { defaultValue: 'Search vendor...' })}
                    showBrowse
                    browseContactTypes={['supplier', 'subcontractor']}
                  />
                </div>
                {/* Delivery date */}
                <div>
                  <label className="block text-sm font-medium text-content-primary mb-1.5">
                    {t('procurement.delivery_date', { defaultValue: 'Delivery Date' })}
                  </label>
                  <input
                    type="date"
                    value={poForm.delivery_date}
                    onChange={(e) => setPoForm((f) => ({ ...f, delivery_date: e.target.value }))}
                    className={inputCls}
                  />
                </div>
                {/* PO Type - visual toggle, full-row */}
                <div className="lg:col-span-3">
                  <label className="block text-sm font-medium text-content-primary mb-2">
                    {t('procurement.po_type', { defaultValue: 'PO Type' })}
                  </label>
                  <div className="flex flex-wrap items-center gap-2">
                    {(['standard', 'blanket', 'service'] as const).map((typ) => (
                      <button
                        key={typ}
                        type="button"
                        onClick={() => setPoForm((f) => ({ ...f, po_type: typ }))}
                        className={clsx(
                          'rounded-lg px-3.5 py-1.5 text-xs font-medium border transition-all',
                          poForm.po_type === typ
                            ? 'bg-oe-blue text-white border-oe-blue shadow-sm'
                            : 'border-border text-content-secondary hover:border-oe-blue/40 hover:bg-surface-secondary',
                        )}
                      >
                        {t(`procurement.po_type_${typ}`, { defaultValue: typ.charAt(0).toUpperCase() + typ.slice(1) })}
                      </button>
                    ))}
                  </div>
                </div>
              </div>
            </div>

            {/* ── Section: Items ── */}
            <div>
              <h3 className="text-xs font-semibold uppercase tracking-wider text-content-tertiary mb-3">
                {t('procurement.section_items', { defaultValue: 'Items' })} <span className="text-semantic-error">*</span>
              </h3>
              <div className="space-y-2">
                {/* Header row */}
                <div className="hidden sm:grid grid-cols-[1fr_70px_60px_80px_80px_32px] gap-2 text-2xs font-medium text-content-tertiary uppercase tracking-wider px-1">
                  <span>{t('procurement.item_description', { defaultValue: 'Description' })}</span>
                  <span>{t('procurement.item_qty', { defaultValue: 'Qty' })}</span>
                  <span>{t('procurement.item_unit', { defaultValue: 'Unit' })}</span>
                  <span>{t('procurement.item_rate', { defaultValue: 'Rate' })}</span>
                  <span>{t('procurement.item_amount', { defaultValue: 'Amount' })}</span>
                  <span />
                </div>
                {/* Keyed by position alone. The key used to carry the
                    description, which changes on every keystroke, so React
                    unmounted the row and mounted a replacement for each
                    character typed - the input lost focus, and the bill-position
                    picker below lost its search box mid-word. The rows are
                    controlled state rebuilt by `removeLineItem`, so the index is
                    a stable identity here. */}
                {poForm.items.map((li, idx) => (
                  <div key={`po-line-${idx}`} className="grid grid-cols-1 sm:grid-cols-[1fr_70px_60px_80px_80px_32px] gap-2 items-start">
                    {/* Description and the position it is bought against share
                        the first column: the picker is a second line of the
                        same thought, and giving it a column of its own would
                        squeeze the four numeric ones. Renders nothing when the
                        project has no cost spine. */}
                    <div className="flex flex-col gap-1">
                      <input
                        value={li.description}
                        onChange={(e) => updateLineItem(idx, 'description', e.target.value)}
                        placeholder={t('procurement.item_desc_placeholder', { defaultValue: 'Item description' })}
                        aria-label={t('procurement.item_description_for', {
                          defaultValue: 'Description for line {{line}}',
                          line: idx + 1,
                        })}
                        className={clsx(inputCls, 'h-9 text-xs')}
                      />
                      <BillPositionPicker
                        projectId={projectId}
                        value={li.boq_position_id}
                        onChange={(boqPositionId) => setLinePosition(idx, boqPositionId)}
                        line={idx + 1}
                      />
                    </div>
                    <input
                      type="number"
                      step="any"
                      value={li.quantity}
                      onChange={(e) => updateLineItem(idx, 'quantity', e.target.value)}
                      placeholder="1"
                      aria-label={t('procurement.item_qty_for', {
                        defaultValue: 'Quantity for line {{line}}',
                        line: idx + 1,
                      })}
                      className={clsx(inputCls, 'h-9 text-xs')}
                    />
                    <input
                      value={li.unit}
                      onChange={(e) => updateLineItem(idx, 'unit', e.target.value)}
                      placeholder="pcs"
                      aria-label={t('procurement.item_unit_for', {
                        defaultValue: 'Unit for line {{line}}',
                        line: idx + 1,
                      })}
                      className={clsx(inputCls, 'h-9 text-xs')}
                    />
                    <input
                      type="number"
                      step="0.01"
                      value={li.unit_rate}
                      onChange={(e) => updateLineItem(idx, 'unit_rate', e.target.value)}
                      placeholder="0.00"
                      aria-label={t('procurement.item_rate_for', {
                        defaultValue: 'Unit rate for line {{line}}',
                        line: idx + 1,
                      })}
                      className={clsx(inputCls, 'h-9 text-xs')}
                    />
                    <input
                      type="text"
                      readOnly
                      value={li.amount && li.amount !== '0.00' ? li.amount : ''}
                      placeholder="0.00"
                      aria-label={t('procurement.item_amount_for', {
                        defaultValue: 'Amount for line {{line}}',
                        line: idx + 1,
                      })}
                      className={clsx(inputCls, 'h-9 text-xs bg-surface-secondary/50 cursor-default')}
                      tabIndex={-1}
                    />
                    <button
                      type="button"
                      onClick={() => removeLineItem(idx)}
                      className="flex h-9 w-8 items-center justify-center rounded-lg text-content-tertiary hover:text-semantic-error hover:bg-red-50 dark:hover:bg-red-950/20 transition-colors"
                      title={t('common.remove', { defaultValue: 'Remove' })}
                      aria-label={t('procurement.remove_line', {
                        defaultValue: 'Remove line {{line}}',
                        line: idx + 1,
                      })}
                    >
                      <Trash2 size={14} />
                    </button>
                  </div>
                ))}
                <Button
                  variant="ghost"
                  size="sm"
                  icon={<Plus size={14} />}
                  onClick={addLineItem}
                  className="mt-1"
                >
                  {t('procurement.add_item', { defaultValue: 'Add Item' })}
                </Button>
              </div>
              {poErrors.items && <p className="mt-1.5 text-xs text-semantic-error">{poErrors.items}</p>}

              {/* Totals */}
              <div className="mt-4 space-y-2">
                <div className="flex items-center justify-between text-sm">
                  <span className="text-content-secondary">{t('procurement.subtotal', { defaultValue: 'Subtotal' })}</span>
                  <span className="tabular-nums font-medium text-content-primary">{displayCurrency} {fmtFixed(poSubtotal, 2)}</span>
                </div>
                <div className="flex items-center justify-between text-sm">
                  <span className="text-content-secondary">{t('procurement.tax', { defaultValue: 'Tax' })}</span>
                  <div className="relative w-32">
                    <span className="pointer-events-none absolute inset-y-0 left-0 flex items-center pl-2.5 text-2xs text-content-tertiary font-medium">
                      {poForm.currency || projectCurrency}
                    </span>
                    <input
                      type="number"
                      step="0.01"
                      value={poTaxInput}
                      onChange={(e) => setPoTaxInput(e.target.value)}
                      className={clsx(inputCls, 'h-8 text-xs pl-10 text-right')}
                      placeholder="0.00"
                    />
                  </div>
                </div>
                <div className="flex items-center justify-between rounded-lg bg-surface-secondary/60 px-3 py-2.5">
                  <span className="text-sm font-semibold text-content-primary">{t('procurement.total', { defaultValue: 'Total' })}</span>
                  <span className="text-base font-bold tabular-nums text-content-primary">{displayCurrency} {fmtFixed(poTotal, 2)}</span>
                </div>
              </div>
            </div>

            {/* ── Section: Terms ── */}
            <div>
              <h3 className="text-xs font-semibold uppercase tracking-wider text-content-tertiary mb-3">
                {t('procurement.section_terms', { defaultValue: 'Terms' })}
              </h3>
              <div className="space-y-3">
                <div className="grid grid-cols-2 gap-3">
                  {/* Currency */}
                  <div>
                    <label className="block text-sm font-medium text-content-primary mb-1.5">
                      {t('procurement.currency', { defaultValue: 'Currency' })}
                    </label>
                    <select
                      value={poForm.currency}
                      onChange={(e) => setPoForm((f) => ({ ...f, currency: e.target.value }))}
                      className={inputCls}
                    >
                      {!poForm.currency && (
                        <option value="">
                          {t('procurement.currency_from_project', {
                            defaultValue: 'Use project currency',
                          })}
                        </option>
                      )}
                      {currencyOptions(poForm.currency).map((c) => (
                        <option key={c} value={c}>
                          {c}
                        </option>
                      ))}
                    </select>
                  </div>
                  {/* Payment terms */}
                  <div>
                    <label className="block text-sm font-medium text-content-primary mb-1.5">
                      {t('procurement.payment_terms', { defaultValue: 'Payment Terms' })}
                    </label>
                    <select
                      value={poForm.payment_terms}
                      onChange={(e) => setPoForm((f) => ({ ...f, payment_terms: e.target.value }))}
                      className={inputCls}
                    >
                      <option value="30">{t('procurement.net_days', { defaultValue: 'Net {{days}} days', days: 30 })}</option>
                      <option value="45">{t('procurement.net_days', { defaultValue: 'Net {{days}} days', days: 45 })}</option>
                      <option value="60">{t('procurement.net_days', { defaultValue: 'Net {{days}} days', days: 60 })}</option>
                      <option value="90">{t('procurement.net_days', { defaultValue: 'Net {{days}} days', days: 90 })}</option>
                    </select>
                  </div>
                </div>
                {/* Notes */}
                <div>
                  <label className="block text-sm font-medium text-content-primary mb-1.5">
                    {t('procurement.notes', { defaultValue: 'Notes' })}
                  </label>
                  <textarea
                    value={poForm.notes}
                    onChange={(e) => setPoForm((f) => ({ ...f, notes: e.target.value }))}
                    rows={2}
                    className={clsx(inputCls, 'h-auto py-2.5 resize-none')}
                    placeholder={t('procurement.notes_placeholder', { defaultValue: 'Optional notes or special instructions...' })}
                  />
                </div>
              </div>
            </div>
          </div>
          <div className="flex items-center justify-end gap-3 px-6 py-4 border-t border-border-light sticky bottom-0 z-10 bg-surface-elevated rounded-b-xl">
            <Button variant="ghost" onClick={closeModal} disabled={createPOMut.isPending || editPOMut.isPending}>
              {t('common.cancel', { defaultValue: 'Cancel' })}
            </Button>
            <Button
              variant="primary"
              onClick={() => {
                if (!validatePO()) return;
                if (isEdit && editingPO) {
                  editPOMut.mutate({ id: editingPO, data: poForm });
                } else {
                  createPOMut.mutate(poForm);
                }
              }}
              disabled={createPOMut.isPending || editPOMut.isPending || !canSubmitPO}
            >
              {createPOMut.isPending || editPOMut.isPending ? (
                <Loader2 size={16} className="animate-spin mr-1.5" />
              ) : isEdit ? (
                <Pencil size={16} className="mr-1.5" />
              ) : (
                <Plus size={16} className="mr-1.5" />
              )}
              <span>
                {isEdit
                  ? t('common.save', { defaultValue: 'Save' })
                  : t('common.create', { defaultValue: 'Create' })}
              </span>
            </Button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <>
    <Card padding="none">
      {/* Search + New PO button */}
      <div className="p-4 border-b border-border-light flex flex-col sm:flex-row sm:items-center gap-3">
        <div className="relative flex-1 max-w-sm">
          <div className="pointer-events-none absolute inset-y-0 start-0 flex items-center pl-3 text-content-tertiary">
            <Search size={16} />
          </div>
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder={t('procurement.search_po', {
              defaultValue: 'Search by PO # or vendor...',
            })}
            aria-label={t('procurement.search_po', {
              defaultValue: 'Search by PO # or vendor...',
            })}
            className="h-10 w-full rounded-lg border border-border bg-surface-primary ps-10 pe-3 text-sm text-content-primary placeholder:text-content-tertiary focus:outline-none focus:ring-2 focus:ring-oe-blue focus:border-transparent"
          />
        </div>
        <div className="shrink-0">
          <Button
            variant="primary"
            size="sm"
            icon={<Plus size={14} />}
            onClick={() => setShowCreate(true)}
          >
            {t('procurement.new_po', { defaultValue: 'New Purchase Order' })}
          </Button>
        </div>
      </div>

      {/* Table */}
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border-light bg-surface-secondary/50">
              <th className="px-4 py-3 text-left font-medium text-content-tertiary">
                {t('procurement.po_number', { defaultValue: 'PO #' })}
              </th>
              <th className="px-4 py-3 text-left font-medium text-content-tertiary">
                {t('procurement.vendor', { defaultValue: 'Vendor' })}
              </th>
              <th className="px-4 py-3 text-left font-medium text-content-tertiary">
                {t('procurement.issue_date', { defaultValue: 'Date' })}
              </th>
              <th className="px-4 py-3 text-left font-medium text-content-tertiary">
                {t('procurement.delivery_date', { defaultValue: 'Delivery' })}
              </th>
              <th className="px-4 py-3 text-right font-medium text-content-tertiary">
                {t('procurement.amount', { defaultValue: 'Amount' })}
              </th>
              <th className="px-4 py-3 text-center font-medium text-content-tertiary">
                {t('common.status', { defaultValue: 'Status' })}
              </th>
              <th className="px-4 py-3 text-right font-medium text-content-tertiary">
                {t('common.actions', { defaultValue: 'Actions' })}
              </th>
            </tr>
          </thead>
          <tbody>
            {filtered.length === 0 ? (
              <tr>
                <td colSpan={7} className="px-4 py-8 text-center text-sm text-content-tertiary">
                  {t('procurement.no_po_match', { defaultValue: 'No matching purchase orders' })}
                </td>
              </tr>
            ) : filtered.map((po) => (
              <tr
                key={po.id}
                className="border-b border-border-light hover:bg-surface-secondary/30 transition-colors"
                onMouseEnter={() => setMatchActive((m) => ({ ...m, [po.id]: true }))}
                onFocus={() => setMatchActive((m) => ({ ...m, [po.id]: true }))}
              >
                <td className="px-4 py-3 font-mono text-xs text-content-primary">
                  <span className="inline-flex flex-wrap items-center gap-1.5">
                    {po.po_number}
                    {registerLinks.get(po.id) && (
                      <RegisterChip item={registerLinks.get(po.id) as LinkedItem} />
                    )}
                  </span>
                </td>
                <td className="px-4 py-3 text-content-secondary">
                  <div className="flex flex-wrap items-center gap-1.5">
                    {po.vendor_contact_id ? (
                      <button
                        type="button"
                        onClick={() =>
                          setScorecardOpen({
                            contactId: po.vendor_contact_id as string,
                            name: po.vendor_name,
                          })
                        }
                        className="text-left text-oe-blue hover:underline focus:underline focus:outline-none"
                        title={t('procurement.open_scorecard', {
                          defaultValue: 'Open supplier scorecard',
                        })}
                      >
                        {po.vendor_name}
                      </button>
                    ) : (
                      po.vendor_name
                    )}
                    <VendorPrequalBadge
                      contactId={po.vendor_contact_id}
                      hideWhenEligible
                    />
                  </div>
                </td>
                <td className="px-4 py-3 text-content-secondary">
                  <DateDisplay value={po.issue_date} />
                </td>
                <td className="px-4 py-3 text-content-secondary">
                  <div className="flex flex-col items-start gap-1">
                    <DateDisplay value={po.delivery_date} />
                    <DeliveryCountdownBadge
                      deliveryDate={po.delivery_date}
                      status={po.status}
                    />
                  </div>
                </td>
                <td className="px-4 py-3 text-right">
                  {/* Money bug fix: feed MoneyDisplay the REAL wire fields
                      `amount_total` (Decimal string) + `currency_code`. The
                      old `po.total_amount`/`po.currency` did not exist on the
                      list response, so every row showed an em-dash. MoneyDisplay
                      accepts string amounts and parses them internally, so no
                      Number() wrapping is needed here. */}
                  <MoneyDisplay amount={po.amount_total} currency={po.currency_code} />
                </td>
                <td className="px-4 py-3 text-center">
                  <div className="flex flex-col items-center gap-1">
                    <div className="flex items-center justify-center gap-1.5">
                      <Badge
                        variant={PO_STATUS_COLORS[po.status] ?? 'neutral'}
                        size="sm"
                      >
                        {t(`procurement.po_status_${po.status}`, {
                          defaultValue: po.status,
                        })}
                      </Badge>
                      <MatchStatusBadge
                        poId={po.id}
                        active={Boolean(matchActive[po.id])}
                      />
                    </div>
                    {/* Visual life-cycle pipeline - collapses to a red bar
                        when cancelled, otherwise shows the four-stage dot
                        progression (draft → issued → partial → completed).
                        Mirrors backend _PO_STATUS_TRANSITIONS in service.py. */}
                    <POStatusPipeline status={po.status} />
                    {/* Amber retainage chip (Gap F) - only when retention > 0. */}
                    <RetainageBadge percent={po.retention_percent} />
                  </div>
                </td>
                <td className="px-4 py-3 text-right">
                  {isManager && (
                  <div className="flex items-center justify-end gap-1 flex-wrap">
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => openEditMut.mutate(po.id)}
                      disabled={openEditMut.isPending || editPOMut.isPending}
                      title={t('procurement.edit_po', { defaultValue: 'Edit purchase order' })}
                      className="!p-1.5 text-content-tertiary hover:text-oe-blue"
                    >
                      {openEditMut.isPending && openEditMut.variables === po.id ? (
                        <Loader2 size={14} className="animate-spin" />
                      ) : (
                        <Pencil size={14} />
                      )}
                    </Button>
                    {/* Commitment gate (TOP-30 #10): a draft PO must be
                        approved before it can be issued. Approval is what
                        commits budget in finance, so draft rows show Approve
                        and only approved rows show Issue - matching the
                        backend FSM (draft→approved→issued). The chip stays
                        tappable at 44x32 when the row stacks on phones. */}
                    {po.status === 'draft' && (
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => approvePOMut.mutate(po.id)}
                        disabled={approvePOMut.isPending}
                        title={t('procurement.action_approve', {
                          defaultValue: 'Approve PO (commits budget)',
                        })}
                        aria-label={t('procurement.action_approve', {
                          defaultValue: 'Approve PO (commits budget)',
                        })}
                      >
                        {approvePOMut.isPending && approvePOMut.variables === po.id ? (
                          <Loader2 size={14} className="animate-spin mr-1" />
                        ) : (
                          <CheckCircle2 size={14} className="mr-1" />
                        )}
                        {t('procurement.action_approve_short', { defaultValue: 'Approve' })}
                      </Button>
                    )}
                    {po.status === 'approved' && (
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => issuePOMut.mutate(po.id)}
                        disabled={issuePOMut.isPending}
                        title={t('procurement.action_issue', { defaultValue: 'Issue PO' })}
                        aria-label={t('procurement.action_issue', { defaultValue: 'Issue PO' })}
                      >
                        {issuePOMut.isPending && issuePOMut.variables === po.id ? (
                          <Loader2 size={14} className="animate-spin mr-1" />
                        ) : (
                          <Send size={14} className="mr-1" />
                        )}
                        {t('procurement.action_issue_short', { defaultValue: 'Issue' })}
                      </Button>
                    )}
                    {/* Invoicing is only valid once the PO has been issued -
                        a draft/cancelled PO must never become a payable
                        (mirrors the backend status guard). Keep the control
                        visible but disabled so the reason is explained. */}
                    {(() => {
                      const invoiceable = ['issued', 'partially_received', 'completed'].includes(
                        po.status,
                      );
                      return (
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => createInvoiceMut.mutate(po.id)}
                          disabled={createInvoiceMut.isPending || !invoiceable}
                          title={
                            invoiceable
                              ? t('procurement.create_invoice', {
                                  defaultValue: 'Create Invoice from PO',
                                })
                              : t('procurement.invoice_requires_issue', {
                                  defaultValue: 'Issue the purchase order before invoicing',
                                })
                          }
                        >
                          <FileText size={14} className="mr-1" />
                          {t('procurement.create_invoice_short', { defaultValue: 'Invoice' })}
                        </Button>
                      );
                    })()}
                    {/* Retainage (Gap F): only meaningful when the PO carries
                        retention. Opens the release panel; the release form
                        inside is MANAGER-gated server-side and UI-side. */}
                    {Number(po.retention_percent ?? '0') > 0 && (
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => setRetainagePO(po)}
                        title={t('procurement.open_retainage', {
                          defaultValue: 'Manage retainage',
                        })}
                      >
                        <Wallet size={14} className="mr-1" />
                        {t('procurement.retainage_short', { defaultValue: 'Retainage' })}
                      </Button>
                    )}
                    {/* Removal. A draft offers Delete, anything approved or
                        issued offers Cancel, and a completed or already
                        cancelled order offers neither - a completed PO records
                        what was actually bought and there is nothing left to
                        take back. The confirm step says which verb it is about
                        to use and what goes with it. */}
                    {(() => {
                      const verb = removalVerbFor(po.status);
                      if (!verb) return null;
                      const isDelete = verb === 'delete';
                      const label = isDelete
                        ? t('procurement.remove_po_action_delete', {
                            defaultValue: 'Delete purchase order',
                          })
                        : t('procurement.remove_po_action_cancel', {
                            defaultValue: 'Cancel purchase order',
                          });
                      return (
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => setRemovingPO(po)}
                          title={label}
                          aria-label={label}
                          className="!p-1.5 text-content-tertiary hover:text-semantic-error"
                        >
                          {isDelete ? <Trash2 size={14} /> : <Ban size={14} />}
                        </Button>
                      );
                    })()}
                  </div>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {/* The search box above filters the rows already loaded, so a register
          cut at 50 answers "no matching purchase orders" for a PO that exists
          on page 2. Reads the server page, not `filtered`. */}
      {ordersPage && <TruncationNotice page={ordersPage} className="mt-3" />}
    </Card>

    {/* PO Create Modal */}
    {showCreate && renderPOModal()}

    {/* Supplier scorecard modal */}
    {scorecardOpen && (
      <SupplierScorecardModal
        open
        onClose={() => setScorecardOpen(null)}
        contactId={scorecardOpen.contactId}
        contactName={scorecardOpen.name ?? undefined}
        projectId={projectId}
      />
    )}

    {/* Retainage panel (Gap F) - release withheld retention + audit log */}
    {retainagePO && (
      <RetainagePanel
        open
        onClose={() => setRetainagePO(null)}
        poId={retainagePO.id}
        poNumber={retainagePO.po_number}
        currency={retainagePO.currency_code}
        retainageAmount={retainagePO.retainage_amount ?? '0'}
        retainageHeld={retainagePO.retainage_held ?? '0'}
        retentionPercent={retainagePO.retention_percent ?? '0'}
        canRelease={isManager}
      />
    )}

    {/* Removal confirm - delete a never-issued draft, or void anything else */}
    <PORemovalDialog
      po={removingPO}
      projectId={projectId}
      onClose={() => setRemovingPO(null)}
    />
    </>
  );
}

/* ── Match status badge (lazy fetch per row) ──────────────────────────── */

const MATCH_BADGE_VARIANT: Record<POLineMatchTag, 'neutral' | 'success' | 'warning' | 'error'> = {
  ok: 'success',
  partial: 'warning',
  unmatched: 'neutral',
  over_received: 'warning',
  over_invoiced: 'error',
};

function MatchStatusBadge({ poId, active }: { poId: string; active: boolean }) {
  const { t } = useTranslation();
  const { data, isLoading } = useQuery({
    queryKey: ['procurement-match', poId],
    queryFn: () => getPOMatchStatus(poId),
    enabled: active,
    staleTime: 30_000,
  });

  if (!active && !data) return null;
  if (isLoading || !data) {
    return (
      <span className="inline-flex items-center text-2xs text-content-tertiary">
        <Loader2 size={10} className="animate-spin" />
      </span>
    );
  }

  const tag = data.overall_status;
  // Explicit defaults keep the badge readable when a brand-new locale
  // ships before its `procurement.match_*` entries land.
  const MATCH_LABEL_DEFAULTS: Record<POLineMatchTag, string> = {
    ok: 'Matched',
    partial: 'Partial match',
    unmatched: 'Not matched',
    over_received: 'Over-received',
    over_invoiced: 'Over-invoiced',
  };
  return (
    <Badge variant={MATCH_BADGE_VARIANT[tag] ?? 'neutral'} size="sm" dot>
      {t(`procurement.match_${tag}`, {
        defaultValue: MATCH_LABEL_DEFAULTS[tag] ?? tag.replace('_', ' '),
      })}
    </Badge>
  );
}

/* ── Goods Receipts Tab ───────────────────────────────────────────────── */

function GoodsReceiptsTab({
  projectId,
  onGoToPurchaseOrders,
}: {
  projectId: string;
  onGoToPurchaseOrders: () => void;
}) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const userRole = useAuthStore((s) => s.userRole);
  // Recording + confirming a goods receipt are EDITOR-level permissions
  // (procurement.create / procurement.confirm_receipt), so the controls are
  // shown to editors and above - not just managers. The backend remains
  // authoritative and an error toast surfaces any server-side denial.
  const canReceive =
    userRole === 'admin' || userRole === 'manager' || userRole === 'editor';
  const [search, setSearch] = useState('');
  const [showRecord, setShowRecord] = useState(false);

  const { data: receiptsPage, isLoading, isError, error, refetch } = useQuery({
    queryKey: ['procurement-gr', projectId],
    queryFn: () =>
      apiGet<Page<GoodsReceipt>>(
        `/v1/procurement/goods-receipts/?project_id=${projectId}`,
      ),
  });
  const receipts = receiptsPage?.items;

  /* ── Confirm a draft goods receipt ──
     Confirmation is the load-bearing step: only it runs the over-receipt
     cap, rolls the PO up to partially_received/completed and fires the
     finance event that flips committed -> actual. Refresh both the GR list
     and the PO list (its status pipeline changes) plus the finance
     dashboard. */
  const confirmGRMut = useMutation({
    mutationFn: (grId: string) =>
      apiPost(`/v1/procurement/goods-receipts/${grId}/confirm/`, {}),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['procurement-gr', projectId] });
      queryClient.invalidateQueries({ queryKey: ['procurement-po', projectId] });
      queryClient.invalidateQueries({ queryKey: ['finance', 'dashboard', projectId] });
      addToast({
        type: 'success',
        title: t('procurement.gr_confirmed_toast', {
          defaultValue: 'Goods receipt confirmed',
        }),
      });
    },
    onError: (e: Error) =>
      addToast({
        type: 'error',
        title: t('common.error', { defaultValue: 'Error' }),
        message: e.message,
      }),
  });

  const filtered = useMemo(() => {
    if (!receipts) return [];
    if (!search) return receipts;
    const q = search.toLowerCase();
    // gr_reference is aliased from the nullable delivery_note_number, so a
    // receipt recorded without a delivery note has no reference - guard the
    // ?? so the search filter never calls .toLowerCase() on null.
    return receipts.filter(
      (gr) =>
        (gr.gr_reference ?? '').toLowerCase().includes(q) ||
        (gr.po_number ?? '').toLowerCase().includes(q),
    );
  }, [receipts, search]);

  if (isLoading) return <SkeletonTable rows={5} columns={5} />;

  if (isError) {
    return (
      <Card className="py-12">
        <RecoveryCard error={error} onRetry={() => refetch()} />
      </Card>
    );
  }

  if (!receipts || receipts.length === 0) {
    return (
      <>
        <EmptyState
          icon={<ClipboardCheck size={28} strokeWidth={1.5} />}
          title={t('procurement.no_gr', {
            defaultValue: 'No goods receipts yet',
          })}
          description={t('procurement.no_gr_desc', {
            defaultValue:
              'Goods receipts record deliveries against a purchase order. Record a delivery against an issued PO, or open the Purchase Orders tab to issue one first.',
          })}
          action={
            canReceive
              ? {
                  label: t('procurement.record_delivery', {
                    defaultValue: 'Record Delivery',
                  }),
                  onClick: () => setShowRecord(true),
                }
              : {
                  label: t('procurement.view_purchase_orders', {
                    defaultValue: 'View Purchase Orders',
                  }),
                  onClick: onGoToPurchaseOrders,
                }
          }
        />
        {showRecord && (
          <RecordDeliveryModal
            open
            onClose={() => setShowRecord(false)}
            projectId={projectId}
          />
        )}
      </>
    );
  }

  return (
    <>
    <Card padding="none">
      {/* Search + Record Delivery */}
      <div className="p-4 border-b border-border-light flex flex-col sm:flex-row sm:items-center gap-3">
        <div className="relative flex-1 max-w-sm">
          <div className="pointer-events-none absolute inset-y-0 start-0 flex items-center pl-3 text-content-tertiary">
            <Search size={16} />
          </div>
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder={t('procurement.search_gr', {
              defaultValue: 'Search by GR reference or PO #...',
            })}
            aria-label={t('procurement.search_gr', {
              defaultValue: 'Search by GR reference or PO #...',
            })}
            className="h-10 w-full rounded-lg border border-border bg-surface-primary ps-10 pe-3 text-sm text-content-primary placeholder:text-content-tertiary focus:outline-none focus:ring-2 focus:ring-oe-blue focus:border-transparent"
          />
        </div>
        {canReceive && (
          <div className="shrink-0">
            <Button
              variant="primary"
              size="sm"
              icon={<Plus size={14} />}
              onClick={() => setShowRecord(true)}
            >
              {t('procurement.record_delivery', { defaultValue: 'Record Delivery' })}
            </Button>
          </div>
        )}
      </div>

      {/* Table */}
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border-light bg-surface-secondary/50">
              <th className="px-4 py-3 text-left font-medium text-content-tertiary">
                {t('procurement.gr_ref', { defaultValue: 'GR Reference' })}
              </th>
              <th className="px-4 py-3 text-left font-medium text-content-tertiary">
                {t('procurement.po_ref', { defaultValue: 'PO Reference' })}
              </th>
              <th className="px-4 py-3 text-left font-medium text-content-tertiary">
                {t('procurement.receipt_date', { defaultValue: 'Date' })}
              </th>
              <th className="px-4 py-3 text-center font-medium text-content-tertiary">
                {t('procurement.quantities', { defaultValue: 'Qty (Recv / Ord)' })}
              </th>
              <th className="px-4 py-3 text-center font-medium text-content-tertiary">
                {t('common.status', { defaultValue: 'Status' })}
              </th>
              {canReceive && (
                <th className="px-4 py-3 text-right font-medium text-content-tertiary">
                  {t('common.actions', { defaultValue: 'Actions' })}
                </th>
              )}
            </tr>
          </thead>
          <tbody>
            {filtered.length === 0 ? (
              <tr>
                <td colSpan={canReceive ? 6 : 5} className="px-4 py-8 text-center text-sm text-content-tertiary">
                  {t('procurement.no_gr_match', { defaultValue: 'No matching goods receipts' })}
                </td>
              </tr>
            ) : filtered.map((gr) => (
              <tr
                key={gr.id}
                className="border-b border-border-light hover:bg-surface-secondary/30 transition-colors"
              >
                <td className="px-4 py-3 font-mono text-xs text-content-primary">
                  {gr.gr_reference || (
                    <span className="text-content-tertiary">-</span>
                  )}
                </td>
                <td className="px-4 py-3 font-mono text-xs text-content-secondary">
                  {gr.po_number}
                </td>
                <td className="px-4 py-3 text-content-secondary">
                  <DateDisplay value={gr.receipt_date} />
                </td>
                <td className="px-4 py-3 text-center tabular-nums">
                  <span
                    className={
                      isGoodsReceiptFullyReceived(gr.received_qty, gr.ordered_qty)
                        ? 'text-semantic-success'
                        : 'text-content-primary'
                    }
                  >
                    {gr.received_qty ?? '0'}
                  </span>
                  <span className="text-content-tertiary mx-1">/</span>
                  <span className="text-content-secondary">{gr.ordered_qty ?? '0'}</span>
                </td>
                <td className="px-4 py-3 text-center">
                  <Badge
                    variant={GR_STATUS_COLORS[gr.status] ?? 'neutral'}
                    size="sm"
                  >
                    {t(`procurement.gr_status_${gr.status}`, {
                      defaultValue: GR_STATUS_LABELS[gr.status] ?? gr.status,
                    })}
                  </Badge>
                </td>
                {canReceive && (
                  <td className="px-4 py-3 text-right">
                    {/* A draft goods receipt is awaiting confirmation - the
                        load-bearing step that rolls the PO up and moves the
                        budget from committed to actual. Already-confirmed
                        receipts show nothing actionable. */}
                    {gr.status === 'draft' ? (
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => confirmGRMut.mutate(gr.id)}
                        disabled={confirmGRMut.isPending}
                        title={t('procurement.gr_confirm', {
                          defaultValue: 'Confirm goods receipt',
                        })}
                        aria-label={t('procurement.gr_confirm', {
                          defaultValue: 'Confirm goods receipt',
                        })}
                      >
                        {confirmGRMut.isPending && confirmGRMut.variables === gr.id ? (
                          <Loader2 size={14} className="animate-spin mr-1" />
                        ) : (
                          <CheckCircle2 size={14} className="mr-1" />
                        )}
                        {t('procurement.gr_confirm_short', { defaultValue: 'Confirm' })}
                      </Button>
                    ) : (
                      <span className="text-content-tertiary text-xs">-</span>
                    )}
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {/* Same shape as the PO tab: the search box filters loaded rows only,
          so the register has to admit when the server sent a slice. */}
      {receiptsPage && <TruncationNotice page={receiptsPage} className="mt-3" />}
    </Card>

    {/* Record-delivery modal (create a draft goods receipt) */}
    {showRecord && (
      <RecordDeliveryModal
        open
        onClose={() => setShowRecord(false)}
        projectId={projectId}
      />
    )}
    </>
  );
}
