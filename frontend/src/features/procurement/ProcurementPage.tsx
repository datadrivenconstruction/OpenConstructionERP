import { useState, useMemo, useEffect, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import clsx from 'clsx';
import {
  Package,
  ClipboardCheck,
  Search,
  FileText,
  Wallet,
  Contact,
  Plus,
  X,
  Loader2,
  Trash2,
} from 'lucide-react';
import {
  Button,
  Card,
  Badge,
  EmptyState,
  Breadcrumb,
  SkeletonTable,
} from '@/shared/ui';
import { MoneyDisplay } from '@/shared/ui/MoneyDisplay';
import { DateDisplay } from '@/shared/ui/DateDisplay';
import { ContactSearchInput } from '@/shared/ui/ContactSearchInput';
import { apiGet, apiPost } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { useAuthStore } from '@/stores/useAuthStore';

/* ── Types ─────────────────────────────────────────────────────────────── */

interface PurchaseOrder {
  id: string;
  project_id: string;
  po_number: string;
  vendor_name: string;
  issue_date: string;
  delivery_date: string | null;
  total_amount: number;
  currency: string;
  status: string;
  description: string;
  line_items_count: number;
  created_at: string;
  updated_at: string;
}

interface GoodsReceipt {
  id: string;
  po_id: string;
  po_number: string;
  gr_reference: string;
  receipt_date: string;
  status: string;
  received_qty: number;
  ordered_qty: number;
  description: string;
  created_at: string;
}

interface POLineItemForm {
  description: string;
  quantity: string;
  unit: string;
  unit_rate: string;
  amount: string;
}

/* ── Constants ────────────────────────────────────────────────────────── */

const inputCls =
  'h-10 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';

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
  pending: 'warning',
  partial: 'warning',
  complete: 'success',
  rejected: 'error',
};

/* ── Main Page ────────────────────────────────────────────────────────── */

export function ProcurementPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const projectId = useProjectContextStore((s) => s.activeProjectId);
  const projectName = useProjectContextStore((s) => s.activeProjectName);

  const [activeTab, setActiveTab] = useState<ProcurementTab>('purchase-orders');

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
    <div className="w-full animate-fade-in">
      <Breadcrumb
        items={[
          { label: t('nav.dashboard', 'Dashboard'), to: '/' },
          ...(projectName
            ? [{ label: projectName, to: `/projects/${projectId}` }]
            : []),
          { label: t('procurement.title', { defaultValue: 'Procurement' }) },
        ]}
        className="mb-4"
      />

      {/* Header */}
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-content-primary">
          {t('procurement.title', { defaultValue: 'Procurement' })}
        </h1>
        <p className="mt-1 text-sm text-content-secondary">
          {t('procurement.subtitle', {
            defaultValue: 'Purchase orders and goods receipts',
          })}
        </p>
      </div>

      {/* Cross-module links */}
      <div className="flex flex-wrap gap-1.5 mb-4">
        <Button variant="ghost" size="sm" className="text-xs" onClick={() => navigate('/finance')}>
          <Wallet size={13} className="me-1" />
          {t('procurement.link_finance', { defaultValue: 'Finance' })}
        </Button>
        <Button variant="ghost" size="sm" className="text-xs" onClick={() => navigate('/contacts')}>
          <Contact size={13} className="me-1" />
          {t('procurement.link_contacts', { defaultValue: 'Contacts' })}
        </Button>
      </div>

      {/* No-project warning */}
      {!projectId && (
        <div className="mb-6 rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800 dark:border-amber-800 dark:bg-amber-950/30 dark:text-amber-300">
          {t('common.select_project_hint', { defaultValue: 'Select a project from the header to get started.' })}
        </div>
      )}

      {/* Tab Bar */}
      <div className="flex items-center gap-1 mb-6 border-b border-border-light">
        {tabs.map((tab) => (
          <button
            key={tab.key}
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
        <EmptyState
          icon={<Package size={28} strokeWidth={1.5} />}
          title={t('procurement.no_project', {
            defaultValue: 'No project selected',
          })}
          description={t('procurement.select_project', {
            defaultValue:
              'Open a project first to view its procurement data',
          })}
        />
      ) : (
        <>
          {activeTab === 'purchase-orders' && (
            <PurchaseOrdersTab projectId={projectId} />
          )}
          {activeTab === 'goods-receipts' && (
            <GoodsReceiptsTab projectId={projectId} />
          )}
        </>
      )}
    </div>
  );
}

/* ── Purchase Orders Tab ──────────────────────────────────────────────── */

function PurchaseOrdersTab({ projectId }: { projectId: string }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [search, setSearch] = useState('');
  const addToast = useToastStore((s) => s.addToast);
  const userRole = useAuthStore((s) => s.userRole);
  const isManager = userRole === 'admin' || userRole === 'manager';

  /* ── PO create modal state ── */
  const [showCreate, setShowCreate] = useState(false);
  const todayStr = new Date().toISOString().split('T')[0];
  const emptyLine: POLineItemForm = { description: '', quantity: '1', unit: '', unit_rate: '', amount: '' };

  const [poForm, setPoForm] = useState({
    vendor_contact_id: '',
    vendor_display: '',
    po_type: 'standard' as 'standard' | 'blanket' | 'service',
    delivery_date: '',
    currency: 'EUR',
    payment_terms: '30',
    notes: '',
    items: [{ ...emptyLine }] as POLineItemForm[],
  });
  const [poErrors, setPoErrors] = useState<Record<string, string>>({});
  const firstFieldRef = useRef<HTMLDivElement>(null);

  // Escape key handler
  useEffect(() => {
    if (!showCreate) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setShowCreate(false);
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [showCreate]);

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
  const [poTaxInput, setPoTaxInput] = useState('0');
  const poTotal = poSubtotal + parseFloat(poTaxInput || '0');

  const canSubmitPO = poForm.items.some((li) => li.description.trim().length > 0);

  const validatePO = (): boolean => {
    const e: Record<string, string> = {};
    const hasAnyItem = poForm.items.some((li) => li.description.trim());
    if (!hasAnyItem) e.items = t('validation.required', { defaultValue: 'Add at least one item' });
    setPoErrors(e);
    return Object.keys(e).length === 0;
  };

  const createPOMut = useMutation({
    mutationFn: (data: typeof poForm) =>
      apiPost('/v1/procurement/', {
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
            sort_order: idx,
          })),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['procurement-po', projectId] });
      setShowCreate(false);
      setPoForm({
        vendor_contact_id: '', vendor_display: '', po_type: 'standard',
        delivery_date: '', currency: 'EUR', payment_terms: '30',
        notes: '', items: [{ ...emptyLine }],
      });
      setPoTaxInput('0');
      addToast({ type: 'success', title: t('procurement.po_created', { defaultValue: 'Purchase order created' }) });
    },
    onError: (e: Error) =>
      addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: e.message }),
  });

  const createInvoiceMut = useMutation({
    mutationFn: (poId: string) =>
      apiPost<{ invoice_id: string; invoice_number: string; po_number: string }>(
        `/v1/procurement/${poId}/create-invoice`,
        {},
      ),
    onSuccess: (data) => {
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

  const { data: orders, isLoading } = useQuery({
    queryKey: ['procurement-po', projectId],
    queryFn: () =>
      apiGet<{ items: PurchaseOrder[]; total: number }>(
        `/v1/procurement/?project_id=${projectId}`,
      ).then((res) => res.items),
  });

  const filtered = useMemo(() => {
    if (!orders) return [];
    if (!search) return orders;
    const q = search.toLowerCase();
    return orders.filter(
      (po) =>
        po.po_number.toLowerCase().includes(q) ||
        po.vendor_name.toLowerCase().includes(q),
    );
  }, [orders, search]);

  if (isLoading) return <SkeletonTable rows={5} columns={6} />;

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

  /* ── Render PO create modal ── */
  function renderPOModal() {
    return (
      <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm animate-fade-in">
        <div className="w-full max-w-2xl bg-surface-elevated rounded-xl shadow-xl border border-border animate-card-in mx-4 max-h-[85vh] flex flex-col" role="dialog" aria-label={t('procurement.new_po', { defaultValue: 'New Purchase Order' })}>
          <div className="flex items-center justify-between px-6 py-4 border-b border-border-light sticky top-0 z-10 bg-surface-elevated rounded-t-xl">
            <h2 className="text-lg font-semibold text-content-primary">
              {t('procurement.new_po', { defaultValue: 'New Purchase Order' })}
            </h2>
            <button
              onClick={() => setShowCreate(false)}
              aria-label={t('common.close', { defaultValue: 'Close' })}
              className="flex h-8 w-8 items-center justify-center rounded-lg text-content-tertiary hover:bg-surface-secondary hover:text-content-primary transition-colors"
            >
              <X size={18} />
            </button>
          </div>
          <div className="px-6 py-5 space-y-5 overflow-y-auto flex-1">
            {/* ── Section: Order Details ── */}
            <div>
              <h3 className="text-xs font-semibold uppercase tracking-wider text-content-tertiary mb-3">
                {t('procurement.section_order_details', { defaultValue: 'Order Details' })}
              </h3>
              <div className="space-y-3">
                {/* Vendor */}
                <div ref={firstFieldRef}>
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
                {/* PO Type — visual toggle */}
                <div>
                  <label className="block text-sm font-medium text-content-primary mb-2">
                    {t('procurement.po_type', { defaultValue: 'PO Type' })}
                  </label>
                  <div className="flex items-center gap-2">
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
                {poForm.items.map((li, idx) => (
                  <div key={`item-${li.description.slice(0, 20)}-${idx}`} className="grid grid-cols-1 sm:grid-cols-[1fr_70px_60px_80px_80px_32px] gap-2 items-start">
                    <input
                      value={li.description}
                      onChange={(e) => updateLineItem(idx, 'description', e.target.value)}
                      placeholder={t('procurement.item_desc_placeholder', { defaultValue: 'Item description' })}
                      className={clsx(inputCls, 'h-9 text-xs')}
                    />
                    <input
                      type="number"
                      step="any"
                      value={li.quantity}
                      onChange={(e) => updateLineItem(idx, 'quantity', e.target.value)}
                      placeholder="1"
                      className={clsx(inputCls, 'h-9 text-xs')}
                    />
                    <input
                      value={li.unit}
                      onChange={(e) => updateLineItem(idx, 'unit', e.target.value)}
                      placeholder="pcs"
                      className={clsx(inputCls, 'h-9 text-xs')}
                    />
                    <input
                      type="number"
                      step="0.01"
                      value={li.unit_rate}
                      onChange={(e) => updateLineItem(idx, 'unit_rate', e.target.value)}
                      placeholder="0.00"
                      className={clsx(inputCls, 'h-9 text-xs')}
                    />
                    <input
                      type="text"
                      readOnly
                      value={li.amount && li.amount !== '0.00' ? li.amount : ''}
                      placeholder="0.00"
                      className={clsx(inputCls, 'h-9 text-xs bg-surface-secondary/50 cursor-default')}
                      tabIndex={-1}
                    />
                    <button
                      type="button"
                      onClick={() => removeLineItem(idx)}
                      className="flex h-9 w-8 items-center justify-center rounded-lg text-content-tertiary hover:text-semantic-error hover:bg-red-50 dark:hover:bg-red-950/20 transition-colors"
                      title={t('common.remove', { defaultValue: 'Remove' })}
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
                  <span className="tabular-nums font-medium text-content-primary">{poForm.currency} {poSubtotal.toFixed(2)}</span>
                </div>
                <div className="flex items-center justify-between text-sm">
                  <span className="text-content-secondary">{t('procurement.tax', { defaultValue: 'Tax' })}</span>
                  <div className="relative w-32">
                    <span className="pointer-events-none absolute inset-y-0 left-0 flex items-center pl-2.5 text-2xs text-content-tertiary font-medium">
                      {poForm.currency}
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
                  <span className="text-base font-bold tabular-nums text-content-primary">{poForm.currency} {poTotal.toFixed(2)}</span>
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
                      <option value="EUR">EUR</option>
                      <option value="USD">USD</option>
                      <option value="GBP">GBP</option>
                      <option value="CHF">CHF</option>
                      <option value="PLN">PLN</option>
                      <option value="CZK">CZK</option>
                      <option value="SEK">SEK</option>
                      <option value="NOK">NOK</option>
                      <option value="DKK">DKK</option>
                      <option value="AED">AED</option>
                      <option value="SAR">SAR</option>
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
            <Button variant="ghost" onClick={() => setShowCreate(false)} disabled={createPOMut.isPending}>
              {t('common.cancel', { defaultValue: 'Cancel' })}
            </Button>
            <Button
              variant="primary"
              onClick={() => {
                if (!validatePO()) return;
                createPOMut.mutate(poForm);
              }}
              disabled={createPOMut.isPending || !canSubmitPO}
            >
              {createPOMut.isPending ? (
                <Loader2 size={16} className="animate-spin mr-1.5" />
              ) : (
                <Plus size={16} className="mr-1.5" />
              )}
              <span>{t('common.create', { defaultValue: 'Create' })}</span>
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
          <div className="pointer-events-none absolute inset-y-0 left-0 flex items-center pl-3 text-content-tertiary">
            <Search size={16} />
          </div>
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder={t('procurement.search_po', {
              defaultValue: 'Search by PO # or vendor...',
            })}
            className="h-10 w-full rounded-lg border border-border bg-surface-primary pl-10 pr-3 text-sm text-content-primary placeholder:text-content-tertiary focus:outline-none focus:ring-2 focus:ring-oe-blue focus:border-transparent"
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
              >
                <td className="px-4 py-3 font-mono text-xs text-content-primary">
                  {po.po_number}
                </td>
                <td className="px-4 py-3 text-content-secondary">
                  {po.vendor_name}
                </td>
                <td className="px-4 py-3 text-content-secondary">
                  <DateDisplay value={po.issue_date} />
                </td>
                <td className="px-4 py-3 text-content-secondary">
                  <DateDisplay value={po.delivery_date} />
                </td>
                <td className="px-4 py-3 text-right">
                  <MoneyDisplay amount={po.total_amount} currency={po.currency} />
                </td>
                <td className="px-4 py-3 text-center">
                  <Badge
                    variant={PO_STATUS_COLORS[po.status] ?? 'neutral'}
                    size="sm"
                  >
                    {t(`procurement.po_status_${po.status}`, {
                      defaultValue: po.status,
                    })}
                  </Badge>
                </td>
                <td className="px-4 py-3 text-right">
                  {isManager && (
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => createInvoiceMut.mutate(po.id)}
                    disabled={createInvoiceMut.isPending}
                    title={t('procurement.create_invoice', { defaultValue: 'Create Invoice from PO' })}
                  >
                    <FileText size={14} className="mr-1" />
                    {t('procurement.create_invoice_short', { defaultValue: 'Invoice' })}
                  </Button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>

    {/* PO Create Modal */}
    {showCreate && renderPOModal()}
    </>
  );
}

/* ── Goods Receipts Tab ───────────────────────────────────────────────── */

function GoodsReceiptsTab({ projectId }: { projectId: string }) {
  const { t } = useTranslation();
  const [search, setSearch] = useState('');

  const { data: receipts, isLoading } = useQuery({
    queryKey: ['procurement-gr', projectId],
    queryFn: () =>
      apiGet<{ items: GoodsReceipt[]; total: number }>(
        `/v1/procurement/goods-receipts?project_id=${projectId}`,
      ).then((res) => res.items),
  });

  const filtered = useMemo(() => {
    if (!receipts) return [];
    if (!search) return receipts;
    const q = search.toLowerCase();
    return receipts.filter(
      (gr) =>
        gr.gr_reference.toLowerCase().includes(q) ||
        gr.po_number.toLowerCase().includes(q),
    );
  }, [receipts, search]);

  if (isLoading) return <SkeletonTable rows={5} columns={5} />;

  if (!receipts || receipts.length === 0) {
    return (
      <EmptyState
        icon={<ClipboardCheck size={28} strokeWidth={1.5} />}
        title={t('procurement.no_gr', {
          defaultValue: 'No goods receipts yet',
        })}
        description={t('procurement.no_gr_desc', {
          defaultValue: 'Goods receipts will appear when deliveries are recorded',
        })}
      />
    );
  }

  return (
    <Card padding="none">
      {/* Search */}
      <div className="p-4 border-b border-border-light">
        <div className="relative max-w-sm">
          <div className="pointer-events-none absolute inset-y-0 left-0 flex items-center pl-3 text-content-tertiary">
            <Search size={16} />
          </div>
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder={t('procurement.search_gr', {
              defaultValue: 'Search by GR reference or PO #...',
            })}
            className="h-10 w-full rounded-lg border border-border bg-surface-primary pl-10 pr-3 text-sm text-content-primary placeholder:text-content-tertiary focus:outline-none focus:ring-2 focus:ring-oe-blue focus:border-transparent"
          />
        </div>
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
            </tr>
          </thead>
          <tbody>
            {filtered.length === 0 ? (
              <tr>
                <td colSpan={5} className="px-4 py-8 text-center text-sm text-content-tertiary">
                  {t('procurement.no_gr_match', { defaultValue: 'No matching goods receipts' })}
                </td>
              </tr>
            ) : filtered.map((gr) => (
              <tr
                key={gr.id}
                className="border-b border-border-light hover:bg-surface-secondary/30 transition-colors"
              >
                <td className="px-4 py-3 font-mono text-xs text-content-primary">
                  {gr.gr_reference}
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
                      gr.received_qty >= gr.ordered_qty
                        ? 'text-semantic-success'
                        : 'text-content-primary'
                    }
                  >
                    {gr.received_qty}
                  </span>
                  <span className="text-content-tertiary mx-1">/</span>
                  <span className="text-content-secondary">{gr.ordered_qty}</span>
                </td>
                <td className="px-4 py-3 text-center">
                  <Badge
                    variant={GR_STATUS_COLORS[gr.status] ?? 'neutral'}
                    size="sm"
                  >
                    {t(`procurement.gr_status_${gr.status}`, {
                      defaultValue: gr.status,
                    })}
                  </Badge>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}
