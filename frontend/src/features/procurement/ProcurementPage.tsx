import { useState, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation } from '@tanstack/react-query';
import {
  Package,
  ClipboardCheck,
  Search,
  FileText,
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
import { apiGet, apiPost } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import { useProjectContextStore } from '@/stores/useProjectContextStore';

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

/* ── Constants ────────────────────────────────────────────────────────── */

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
    <div className="max-w-content mx-auto animate-fade-in">
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

      {/* No-project warning */}
      {!projectId && (
        <div className="mb-6 rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800 dark:border-amber-800 dark:bg-amber-950/30 dark:text-amber-300">
          {t('common.select_project_first', { defaultValue: 'Please select a project to continue.' })}
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
          icon={<Package size={24} strokeWidth={1.5} />}
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
  const [search, setSearch] = useState('');
  const addToast = useToastStore((s) => s.addToast);

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
      apiGet<PurchaseOrder[]>(
        `/v1/procurement/purchase-orders?project_id=${projectId}`,
      ),
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
      <EmptyState
        icon={<Package size={24} strokeWidth={1.5} />}
        title={t('procurement.no_po', {
          defaultValue: 'No purchase orders yet',
        })}
        description={t('procurement.no_po_desc', {
          defaultValue: 'Purchase orders will appear here when created',
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
            placeholder={t('procurement.search_po', {
              defaultValue: 'Search by PO # or vendor...',
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
            {filtered.map((po) => (
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
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

/* ── Goods Receipts Tab ───────────────────────────────────────────────── */

function GoodsReceiptsTab({ projectId }: { projectId: string }) {
  const { t } = useTranslation();
  const [search, setSearch] = useState('');

  const { data: receipts, isLoading } = useQuery({
    queryKey: ['procurement-gr', projectId],
    queryFn: () =>
      apiGet<GoodsReceipt[]>(
        `/v1/procurement/goods-receipts?project_id=${projectId}`,
      ),
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
        icon={<ClipboardCheck size={24} strokeWidth={1.5} />}
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
            {filtered.map((gr) => (
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
                        ? 'text-[#15803d]'
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
