import { useState, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  Wallet,
  FileText,
  CreditCard,
  BarChart3,
  Search,
  ArrowUpRight,
  ArrowDownRight,
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
import { apiGet, apiPatch } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import { useProjectContextStore } from '@/stores/useProjectContextStore';

/* ── Types ─────────────────────────────────────────────────────────────── */

interface BudgetLine {
  id: string;
  project_id: string;
  wbs_code: string;
  category: string;
  original_budget: number;
  revised_budget: number;
  committed: number;
  actual: number;
  forecast: number;
  variance: number;
  currency: string;
  created_at: string;
  updated_at: string;
}

interface Invoice {
  id: string;
  project_id: string;
  invoice_number: string;
  direction: 'payable' | 'receivable';
  counterparty_name: string;
  issue_date: string;
  due_date: string;
  amount: number;
  currency: string;
  status: string;
  description: string;
  created_at: string;
  updated_at: string;
}

interface Payment {
  id: string;
  invoice_id: string;
  invoice_number: string;
  amount: number;
  currency: string;
  payment_date: string;
  method: string;
  reference: string;
  status: string;
  created_at: string;
}

interface EVMData {
  project_id: string;
  bac: number;
  pv: number;
  ev: number;
  ac: number;
  sv: number;
  cv: number;
  spi: number;
  cpi: number;
  eac: number;
  etc: number;
  vac: number;
  tcpi: number;
  currency: string;
  data_date: string;
}

/* ── Constants ────────────────────────────────────────────────────────── */

type FinanceTab = 'budgets' | 'invoices' | 'payments' | 'evm';
type InvoiceSubTab = 'payable' | 'receivable';

const INVOICE_STATUS_COLORS: Record<
  string,
  'neutral' | 'blue' | 'success' | 'warning' | 'error'
> = {
  draft: 'neutral',
  pending: 'warning',
  approved: 'blue',
  paid: 'success',
  disputed: 'error',
  cancelled: 'neutral',
};

/* ── Main Page ────────────────────────────────────────────────────────── */

export function FinancePage() {
  const { t } = useTranslation();
  const projectId = useProjectContextStore((s) => s.activeProjectId);
  const projectName = useProjectContextStore((s) => s.activeProjectName);

  const [activeTab, setActiveTab] = useState<FinanceTab>('budgets');

  const tabs: { key: FinanceTab; label: string; icon: React.ReactNode }[] = [
    {
      key: 'budgets',
      label: t('finance.budgets', { defaultValue: 'Budgets' }),
      icon: <Wallet size={15} />,
    },
    {
      key: 'invoices',
      label: t('finance.invoices', { defaultValue: 'Invoices' }),
      icon: <FileText size={15} />,
    },
    {
      key: 'payments',
      label: t('finance.payments', { defaultValue: 'Payments' }),
      icon: <CreditCard size={15} />,
    },
    {
      key: 'evm',
      label: t('finance.evm_dashboard', { defaultValue: 'EVM Dashboard' }),
      icon: <BarChart3 size={15} />,
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
          { label: t('finance.title', { defaultValue: 'Finance' }) },
        ]}
        className="mb-4"
      />

      {/* Header */}
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-content-primary">
          {t('finance.title', { defaultValue: 'Finance' })}
        </h1>
        <p className="mt-1 text-sm text-content-secondary">
          {t('finance.subtitle', {
            defaultValue:
              'Budgets, invoices, payments, and earned value management',
          })}
        </p>
      </div>

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
          icon={<Wallet size={24} strokeWidth={1.5} />}
          title={t('finance.no_project', {
            defaultValue: 'No project selected',
          })}
          description={t('finance.select_project', {
            defaultValue:
              'Open a project first to view its financial data',
          })}
        />
      ) : (
        <>
          {activeTab === 'budgets' && <BudgetsTab projectId={projectId} />}
          {activeTab === 'invoices' && <InvoicesTab projectId={projectId} />}
          {activeTab === 'payments' && <PaymentsTab projectId={projectId} />}
          {activeTab === 'evm' && <EVMTab projectId={projectId} />}
        </>
      )}
    </div>
  );
}

/* ── Budgets Tab ──────────────────────────────────────────────────────── */

function BudgetsTab({ projectId }: { projectId: string }) {
  const { t } = useTranslation();
  const [search, setSearch] = useState('');

  const { data: budgets, isLoading } = useQuery({
    queryKey: ['finance-budgets', projectId],
    queryFn: () =>
      apiGet<BudgetLine[]>(
        `/v1/finance/budgets?project_id=${projectId}`,
      ),
  });

  const filtered = useMemo(() => {
    if (!budgets) return [];
    if (!search) return budgets;
    const q = search.toLowerCase();
    return budgets.filter(
      (b) =>
        b.wbs_code.toLowerCase().includes(q) ||
        b.category.toLowerCase().includes(q),
    );
  }, [budgets, search]);

  const totals = useMemo(() => {
    if (!filtered.length) return null;
    return {
      original: filtered.reduce((s, b) => s + b.original_budget, 0),
      revised: filtered.reduce((s, b) => s + b.revised_budget, 0),
      committed: filtered.reduce((s, b) => s + b.committed, 0),
      actual: filtered.reduce((s, b) => s + b.actual, 0),
      forecast: filtered.reduce((s, b) => s + b.forecast, 0),
      variance: filtered.reduce((s, b) => s + b.variance, 0),
      currency: filtered[0]?.currency ?? 'EUR',
    };
  }, [filtered]);

  if (isLoading) return <SkeletonTable rows={6} columns={8} />;

  if (!budgets || budgets.length === 0) {
    return (
      <EmptyState
        icon={<Wallet size={24} strokeWidth={1.5} />}
        title={t('finance.no_budgets', { defaultValue: 'No budgets yet' })}
        description={t('finance.no_budgets_desc', {
          defaultValue: 'Budget lines will appear here when configured',
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
            placeholder={t('finance.search_budgets', {
              defaultValue: 'Search by WBS or category...',
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
                {t('finance.wbs', { defaultValue: 'WBS' })}
              </th>
              <th className="px-4 py-3 text-left font-medium text-content-tertiary">
                {t('finance.category', { defaultValue: 'Category' })}
              </th>
              <th className="px-4 py-3 text-right font-medium text-content-tertiary">
                {t('finance.original', { defaultValue: 'Original' })}
              </th>
              <th className="px-4 py-3 text-right font-medium text-content-tertiary">
                {t('finance.revised', { defaultValue: 'Revised' })}
              </th>
              <th className="px-4 py-3 text-right font-medium text-content-tertiary">
                {t('finance.committed', { defaultValue: 'Committed' })}
              </th>
              <th className="px-4 py-3 text-right font-medium text-content-tertiary">
                {t('finance.actual', { defaultValue: 'Actual' })}
              </th>
              <th className="px-4 py-3 text-right font-medium text-content-tertiary">
                {t('finance.forecast', { defaultValue: 'Forecast' })}
              </th>
              <th className="px-4 py-3 text-right font-medium text-content-tertiary">
                {t('finance.variance', { defaultValue: 'Variance' })}
              </th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((b) => (
              <tr
                key={b.id}
                className="border-b border-border-light hover:bg-surface-secondary/30 transition-colors"
              >
                <td className="px-4 py-3 font-mono text-xs text-content-primary">
                  {b.wbs_code}
                </td>
                <td className="px-4 py-3 text-content-secondary">{b.category}</td>
                <td className="px-4 py-3 text-right">
                  <MoneyDisplay amount={b.original_budget} currency={b.currency} />
                </td>
                <td className="px-4 py-3 text-right">
                  <MoneyDisplay amount={b.revised_budget} currency={b.currency} />
                </td>
                <td className="px-4 py-3 text-right">
                  <MoneyDisplay amount={b.committed} currency={b.currency} />
                </td>
                <td className="px-4 py-3 text-right">
                  <MoneyDisplay amount={b.actual} currency={b.currency} />
                </td>
                <td className="px-4 py-3 text-right">
                  <MoneyDisplay amount={b.forecast} currency={b.currency} />
                </td>
                <td className="px-4 py-3 text-right">
                  <span
                    className={
                      b.variance >= 0
                        ? 'text-[#15803d] font-medium'
                        : 'text-semantic-error font-medium'
                    }
                  >
                    <MoneyDisplay
                      amount={b.variance}
                      currency={b.currency}
                      colorize
                    />
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
          {totals && (
            <tfoot>
              <tr className="bg-surface-secondary/60 font-semibold">
                <td className="px-4 py-3 text-content-primary" colSpan={2}>
                  {t('common.total', { defaultValue: 'Total' })}
                </td>
                <td className="px-4 py-3 text-right">
                  <MoneyDisplay amount={totals.original} currency={totals.currency} />
                </td>
                <td className="px-4 py-3 text-right">
                  <MoneyDisplay amount={totals.revised} currency={totals.currency} />
                </td>
                <td className="px-4 py-3 text-right">
                  <MoneyDisplay amount={totals.committed} currency={totals.currency} />
                </td>
                <td className="px-4 py-3 text-right">
                  <MoneyDisplay amount={totals.actual} currency={totals.currency} />
                </td>
                <td className="px-4 py-3 text-right">
                  <MoneyDisplay amount={totals.forecast} currency={totals.currency} />
                </td>
                <td className="px-4 py-3 text-right">
                  <MoneyDisplay
                    amount={totals.variance}
                    currency={totals.currency}
                    colorize
                  />
                </td>
              </tr>
            </tfoot>
          )}
        </table>
      </div>
    </Card>
  );
}

/* ── Invoices Tab ─────────────────────────────────────────────────────── */

function InvoicesTab({ projectId }: { projectId: string }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [subTab, setSubTab] = useState<InvoiceSubTab>('payable');
  const [search, setSearch] = useState('');

  const { data: invoices, isLoading } = useQuery({
    queryKey: ['finance-invoices', projectId, subTab],
    queryFn: () =>
      apiGet<Invoice[]>(
        `/v1/finance/invoices?project_id=${projectId}&direction=${subTab}`,
      ),
  });

  const filtered = useMemo(() => {
    if (!invoices) return [];
    if (!search) return invoices;
    const q = search.toLowerCase();
    return invoices.filter(
      (inv) =>
        inv.invoice_number.toLowerCase().includes(q) ||
        inv.counterparty_name.toLowerCase().includes(q),
    );
  }, [invoices, search]);

  const approveMutation = useMutation({
    mutationFn: (invoiceId: string) =>
      apiPatch(`/v1/finance/invoices/${invoiceId}`, { status: 'approved' }),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ['finance-invoices', projectId],
      });
      addToast({
        type: 'success',
        title: t('finance.invoice_approved', {
          defaultValue: 'Invoice approved',
        }),
      });
    },
    onError: (e: Error) =>
      addToast({ type: 'error', title: t('common.error', 'Error'), message: e.message }),
  });

  const markPaidMutation = useMutation({
    mutationFn: (invoiceId: string) =>
      apiPatch(`/v1/finance/invoices/${invoiceId}`, { status: 'paid' }),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ['finance-invoices', projectId],
      });
      addToast({
        type: 'success',
        title: t('finance.invoice_paid', { defaultValue: 'Invoice marked as paid' }),
      });
    },
    onError: (e: Error) =>
      addToast({ type: 'error', title: t('common.error', 'Error'), message: e.message }),
  });

  return (
    <div className="space-y-4">
      {/* Sub-tabs: Payable / Receivable */}
      <div className="flex items-center gap-2">
        <button
          onClick={() => setSubTab('payable')}
          className={`rounded-lg px-3 py-1.5 text-sm font-medium transition-colors ${
            subTab === 'payable'
              ? 'bg-oe-blue-subtle text-oe-blue'
              : 'text-content-tertiary hover:text-content-primary hover:bg-surface-secondary'
          }`}
        >
          {t('finance.payable', { defaultValue: 'Payable' })}
        </button>
        <button
          onClick={() => setSubTab('receivable')}
          className={`rounded-lg px-3 py-1.5 text-sm font-medium transition-colors ${
            subTab === 'receivable'
              ? 'bg-oe-blue-subtle text-oe-blue'
              : 'text-content-tertiary hover:text-content-primary hover:bg-surface-secondary'
          }`}
        >
          {t('finance.receivable', { defaultValue: 'Receivable' })}
        </button>
      </div>

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
              placeholder={t('finance.search_invoices', {
                defaultValue: 'Search invoices...',
              })}
              className="h-10 w-full rounded-lg border border-border bg-surface-primary pl-10 pr-3 text-sm text-content-primary placeholder:text-content-tertiary focus:outline-none focus:ring-2 focus:ring-oe-blue focus:border-transparent"
            />
          </div>
        </div>

        {isLoading ? (
          <SkeletonTable rows={5} columns={6} />
        ) : !filtered.length ? (
          <div className="p-8">
            <EmptyState
              icon={<FileText size={24} strokeWidth={1.5} />}
              title={t('finance.no_invoices', {
                defaultValue: 'No invoices found',
              })}
              description={t('finance.no_invoices_desc', {
                defaultValue: 'Invoices will appear here when created',
              })}
            />
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border-light bg-surface-secondary/50">
                  <th className="px-4 py-3 text-left font-medium text-content-tertiary">
                    {t('finance.invoice_number', { defaultValue: 'Invoice #' })}
                  </th>
                  <th className="px-4 py-3 text-left font-medium text-content-tertiary">
                    {subTab === 'payable'
                      ? t('finance.vendor', { defaultValue: 'Vendor' })
                      : t('finance.client', { defaultValue: 'Client' })}
                  </th>
                  <th className="px-4 py-3 text-left font-medium text-content-tertiary">
                    {t('finance.issue_date', { defaultValue: 'Date' })}
                  </th>
                  <th className="px-4 py-3 text-left font-medium text-content-tertiary">
                    {t('finance.due_date', { defaultValue: 'Due Date' })}
                  </th>
                  <th className="px-4 py-3 text-right font-medium text-content-tertiary">
                    {t('finance.amount', { defaultValue: 'Amount' })}
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
                {filtered.map((inv) => (
                  <tr
                    key={inv.id}
                    className="border-b border-border-light hover:bg-surface-secondary/30 transition-colors"
                  >
                    <td className="px-4 py-3 font-mono text-xs text-content-primary">
                      {inv.invoice_number}
                    </td>
                    <td className="px-4 py-3 text-content-secondary">
                      {inv.counterparty_name}
                    </td>
                    <td className="px-4 py-3 text-content-secondary">
                      <DateDisplay value={inv.issue_date} />
                    </td>
                    <td className="px-4 py-3 text-content-secondary">
                      <DateDisplay value={inv.due_date} />
                    </td>
                    <td className="px-4 py-3 text-right">
                      <MoneyDisplay amount={inv.amount} currency={inv.currency} />
                    </td>
                    <td className="px-4 py-3 text-center">
                      <Badge
                        variant={INVOICE_STATUS_COLORS[inv.status] ?? 'neutral'}
                        size="sm"
                      >
                        {t(`finance.status_${inv.status}`, {
                          defaultValue: inv.status,
                        })}
                      </Badge>
                    </td>
                    <td className="px-4 py-3 text-right">
                      <div className="flex items-center justify-end gap-1">
                        {inv.status === 'pending' && (
                          <Button
                            variant="secondary"
                            size="sm"
                            onClick={() => approveMutation.mutate(inv.id)}
                            loading={approveMutation.isPending}
                          >
                            {t('finance.approve', { defaultValue: 'Approve' })}
                          </Button>
                        )}
                        {inv.status === 'approved' && (
                          <Button
                            variant="primary"
                            size="sm"
                            onClick={() => markPaidMutation.mutate(inv.id)}
                            loading={markPaidMutation.isPending}
                          >
                            {t('finance.mark_paid', { defaultValue: 'Mark Paid' })}
                          </Button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}

/* ── Payments Tab ─────────────────────────────────────────────────────── */

function PaymentsTab({ projectId }: { projectId: string }) {
  const { t } = useTranslation();

  const { data: payments, isLoading } = useQuery({
    queryKey: ['finance-payments', projectId],
    queryFn: () =>
      apiGet<Payment[]>(`/v1/finance/payments?project_id=${projectId}`),
  });

  if (isLoading) return <SkeletonTable rows={5} columns={6} />;

  if (!payments || payments.length === 0) {
    return (
      <EmptyState
        icon={<CreditCard size={24} strokeWidth={1.5} />}
        title={t('finance.no_payments', { defaultValue: 'No payments yet' })}
        description={t('finance.no_payments_desc', {
          defaultValue: 'Payments will appear here once invoices are paid',
        })}
      />
    );
  }

  return (
    <Card padding="none">
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border-light bg-surface-secondary/50">
              <th className="px-4 py-3 text-left font-medium text-content-tertiary">
                {t('finance.invoice_ref', { defaultValue: 'Invoice Ref' })}
              </th>
              <th className="px-4 py-3 text-left font-medium text-content-tertiary">
                {t('finance.payment_date', { defaultValue: 'Payment Date' })}
              </th>
              <th className="px-4 py-3 text-right font-medium text-content-tertiary">
                {t('finance.amount', { defaultValue: 'Amount' })}
              </th>
              <th className="px-4 py-3 text-left font-medium text-content-tertiary">
                {t('finance.method', { defaultValue: 'Method' })}
              </th>
              <th className="px-4 py-3 text-left font-medium text-content-tertiary">
                {t('finance.reference', { defaultValue: 'Reference' })}
              </th>
              <th className="px-4 py-3 text-center font-medium text-content-tertiary">
                {t('common.status', { defaultValue: 'Status' })}
              </th>
            </tr>
          </thead>
          <tbody>
            {payments.map((p) => (
              <tr
                key={p.id}
                className="border-b border-border-light hover:bg-surface-secondary/30 transition-colors"
              >
                <td className="px-4 py-3 font-mono text-xs text-content-primary">
                  {p.invoice_number}
                </td>
                <td className="px-4 py-3 text-content-secondary">
                  <DateDisplay value={p.payment_date} />
                </td>
                <td className="px-4 py-3 text-right">
                  <MoneyDisplay amount={p.amount} currency={p.currency} />
                </td>
                <td className="px-4 py-3 text-content-secondary capitalize">
                  {p.method}
                </td>
                <td className="px-4 py-3 text-content-secondary font-mono text-xs">
                  {p.reference || '\u2014'}
                </td>
                <td className="px-4 py-3 text-center">
                  <Badge
                    variant={p.status === 'completed' ? 'success' : 'warning'}
                    size="sm"
                  >
                    {t(`finance.payment_status_${p.status}`, {
                      defaultValue: p.status,
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

/* ── EVM Dashboard Tab ────────────────────────────────────────────────── */

function EVMTab({ projectId }: { projectId: string }) {
  const { t } = useTranslation();

  const { data: evm, isLoading } = useQuery({
    queryKey: ['finance-evm', projectId],
    queryFn: () =>
      apiGet<EVMData>(`/v1/finance/evm?project_id=${projectId}`),
  });

  if (isLoading) {
    return (
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-4">
        {Array.from({ length: 8 }).map((_, i) => (
          <div
            key={i}
            className="h-28 animate-pulse rounded-xl bg-surface-secondary"
          />
        ))}
      </div>
    );
  }

  if (!evm) {
    return (
      <EmptyState
        icon={<BarChart3 size={24} strokeWidth={1.5} />}
        title={t('finance.no_evm', { defaultValue: 'No EVM data available' })}
        description={t('finance.no_evm_desc', {
          defaultValue:
            'Earned value data requires schedule and cost baseline setup',
        })}
      />
    );
  }

  const kpiCards: {
    label: string;
    value: number;
    isCurrency: boolean;
    isIndex?: boolean;
    good?: 'high' | 'low';
  }[] = [
    {
      label: t('finance.evm_bac', { defaultValue: 'BAC (Budget at Completion)' }),
      value: evm.bac,
      isCurrency: true,
    },
    {
      label: t('finance.evm_pv', { defaultValue: 'PV (Planned Value)' }),
      value: evm.pv,
      isCurrency: true,
    },
    {
      label: t('finance.evm_ev', { defaultValue: 'EV (Earned Value)' }),
      value: evm.ev,
      isCurrency: true,
    },
    {
      label: t('finance.evm_ac', { defaultValue: 'AC (Actual Cost)' }),
      value: evm.ac,
      isCurrency: true,
    },
    {
      label: t('finance.evm_spi', { defaultValue: 'SPI (Schedule Performance)' }),
      value: evm.spi,
      isCurrency: false,
      isIndex: true,
      good: 'high',
    },
    {
      label: t('finance.evm_cpi', { defaultValue: 'CPI (Cost Performance)' }),
      value: evm.cpi,
      isCurrency: false,
      isIndex: true,
      good: 'high',
    },
    {
      label: t('finance.evm_sv', { defaultValue: 'SV (Schedule Variance)' }),
      value: evm.sv,
      isCurrency: true,
    },
    {
      label: t('finance.evm_cv', { defaultValue: 'CV (Cost Variance)' }),
      value: evm.cv,
      isCurrency: true,
    },
    {
      label: t('finance.evm_eac', { defaultValue: 'EAC (Estimate at Completion)' }),
      value: evm.eac,
      isCurrency: true,
    },
    {
      label: t('finance.evm_etc', { defaultValue: 'ETC (Estimate to Complete)' }),
      value: evm.etc,
      isCurrency: true,
    },
    {
      label: t('finance.evm_vac', { defaultValue: 'VAC (Variance at Completion)' }),
      value: evm.vac,
      isCurrency: true,
    },
    {
      label: t('finance.evm_tcpi', { defaultValue: 'TCPI (To-Complete Performance)' }),
      value: evm.tcpi,
      isCurrency: false,
      isIndex: true,
      good: 'low',
    },
  ];

  return (
    <div className="space-y-6">
      {/* Data date */}
      <div className="text-sm text-content-tertiary">
        {t('finance.data_date', { defaultValue: 'Data Date' })}:{' '}
        <DateDisplay value={evm.data_date} className="font-medium text-content-secondary" />
      </div>

      {/* KPI Cards */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-4">
        {kpiCards.map((kpi) => {
          let indicatorColor = '';
          if (kpi.isIndex) {
            indicatorColor =
              kpi.value >= 1.0 ? 'text-[#15803d]' : 'text-semantic-error';
          } else if (kpi.isCurrency && kpi.label.includes('Variance')) {
            indicatorColor =
              kpi.value >= 0 ? 'text-[#15803d]' : 'text-semantic-error';
          }

          return (
            <Card key={kpi.label} className="p-4">
              <div className="text-2xs font-medium text-content-tertiary uppercase tracking-wider mb-2">
                {kpi.label}
              </div>
              <div
                className={`text-xl font-bold tabular-nums ${indicatorColor || 'text-content-primary'}`}
              >
                {kpi.isCurrency ? (
                  <MoneyDisplay
                    amount={kpi.value}
                    currency={evm.currency}
                    compact
                    colorize={kpi.label.includes('Variance')}
                  />
                ) : (
                  kpi.value.toFixed(2)
                )}
              </div>
              {kpi.isIndex && (
                <div className="mt-1 flex items-center gap-1 text-xs">
                  {kpi.value >= 1.0 ? (
                    <ArrowUpRight size={12} className="text-[#15803d]" />
                  ) : (
                    <ArrowDownRight size={12} className="text-semantic-error" />
                  )}
                  <span
                    className={
                      kpi.value >= 1.0 ? 'text-[#15803d]' : 'text-semantic-error'
                    }
                  >
                    {kpi.value >= 1.0
                      ? t('finance.on_track', { defaultValue: 'On track' })
                      : t('finance.behind', { defaultValue: 'Behind' })}
                  </span>
                </div>
              )}
            </Card>
          );
        })}
      </div>
    </div>
  );
}
