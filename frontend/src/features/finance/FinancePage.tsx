import { useState, useMemo, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { useParams } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  Wallet,
  FileText,
  CreditCard,
  BarChart3,
  Search,
  ArrowUpRight,
  ArrowDownRight,
  Download,
  Upload,
  Loader2,
  X,
  Plus,
} from 'lucide-react';
import clsx from 'clsx';
import {
  Button,
  Card,
  Badge,
  EmptyState,
  Breadcrumb,
  SkeletonTable,
  ConfirmDialog,
} from '@/shared/ui';
import { useConfirm } from '@/shared/hooks/useConfirm';
import { MoneyDisplay } from '@/shared/ui/MoneyDisplay';
import { DateDisplay } from '@/shared/ui/DateDisplay';
import { apiGet, apiPost, apiPatch, triggerDownload } from '@/shared/lib/api';
import { ContactSearchInput } from '@/shared/ui/ContactSearchInput';
import { useToastStore } from '@/stores/useToastStore';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { useAuthStore } from '@/stores/useAuthStore';

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

/* ── Export / Import helpers ──────────────────────────────────────────── */

async function fetchBlobWithAuth(url: string, fallbackFilename: string): Promise<void> {
  const token = useAuthStore.getState().accessToken;
  const headers: Record<string, string> = { Accept: 'application/octet-stream' };
  if (token) headers['Authorization'] = `Bearer ${token}`;

  const response = await fetch(url, { method: 'GET', headers });
  if (!response.ok) {
    let detail = 'Export failed';
    try {
      const body = await response.json();
      detail = body.detail || detail;
    } catch {
      // ignore parse error
    }
    throw new Error(detail);
  }

  const blob = await response.blob();
  const disposition = response.headers.get('Content-Disposition');
  const filename = disposition?.match(/filename="?(.+)"?/)?.[1] || fallbackFilename;
  triggerDownload(blob, filename);
}

interface BudgetImportResult {
  imported: number;
  skipped: number;
  errors: { row: number; error: string; data: Record<string, string> }[];
  total_rows: number;
}

async function importBudgetsFile(
  file: File,
  projectId: string,
): Promise<BudgetImportResult> {
  const token = useAuthStore.getState().accessToken;
  const formData = new FormData();
  formData.append('file', file);

  const headers: Record<string, string> = {};
  if (token) headers['Authorization'] = `Bearer ${token}`;

  const response = await fetch(
    `/api/v1/finance/budgets/import/file?project_id=${encodeURIComponent(projectId)}`,
    { method: 'POST', headers, body: formData },
  );

  if (!response.ok) {
    let detail = 'Import failed';
    try {
      const body = await response.json();
      detail = body.detail || detail;
    } catch {
      // ignore parse error
    }
    throw new Error(detail);
  }

  return response.json();
}

/* ── Main Page ────────────────────────────────────────────────────────── */

const inputCls =
  'h-10 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';

export function FinancePage() {
  const { t } = useTranslation();
  const { projectId: routeProjectId } = useParams<{ projectId?: string }>();
  const activeProjectId = useProjectContextStore((s) => s.activeProjectId);
  const projectId = routeProjectId || activeProjectId || '';
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
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [search, setSearch] = useState('');
  const [showImport, setShowImport] = useState(false);
  const [importFile, setImportFile] = useState<File | null>(null);
  const [importPending, setImportPending] = useState(false);
  const [importResult, setImportResult] = useState<BudgetImportResult | null>(null);
  const [importError, setImportError] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [budgetForm, setBudgetForm] = useState({ wbs_code: '', category: '', original_budget: '' });

  // Escape key handler for inline modals
  useEffect(() => {
    if (!showCreate && !showImport) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        if (showCreate) setShowCreate(false);
        if (showImport) setShowImport(false);
      }
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [showCreate, showImport]);

  const createBudgetMut = useMutation({
    mutationFn: (data: { wbs_id: string | null; category: string | null; original_budget: string }) =>
      apiPost('/v1/finance/budgets', {
        project_id: projectId,
        wbs_id: data.wbs_id,
        category: data.category,
        original_budget: data.original_budget,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['finance-budgets', projectId] });
      setShowCreate(false);
      setBudgetForm({ wbs_code: '', category: '', original_budget: '' });
      addToast({ type: 'success', title: t('finance.budget_created', { defaultValue: 'Budget line created' }) });
    },
    onError: (e: Error) =>
      addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: e.message }),
  });

  const exportBudgetsMut = useMutation({
    mutationFn: () =>
      fetchBlobWithAuth(
        `/api/v1/finance/budgets/export?project_id=${encodeURIComponent(projectId)}`,
        'budgets_export.xlsx',
      ),
    onSuccess: () =>
      addToast({
        type: 'success',
        title: t('finance.export_success', { defaultValue: 'Export complete' }),
      }),
    onError: (e: Error) =>
      addToast({
        type: 'error',
        title: t('finance.export_failed', { defaultValue: 'Export failed' }),
        message: e.message,
      }),
  });

  const handleBudgetImport = async () => {
    if (!importFile) return;
    setImportPending(true);
    setImportError(null);
    try {
      const res = await importBudgetsFile(importFile, projectId);
      setImportResult(res);
      queryClient.invalidateQueries({ queryKey: ['finance-budgets', projectId] });
    } catch (err: unknown) {
      setImportError(err instanceof Error ? err.message : 'Import failed');
    } finally {
      setImportPending(false);
    }
  };

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
    <>
    <Card padding="none">
      {/* Search + actions */}
      <div className="p-4 border-b border-border-light flex flex-col sm:flex-row sm:items-center gap-3">
        <div className="relative flex-1 max-w-sm">
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
        <div className="flex items-center gap-2 shrink-0">
          <Button
            variant="secondary"
            size="sm"
            icon={
              exportBudgetsMut.isPending ? (
                <Loader2 size={14} className="animate-spin" />
              ) : (
                <Download size={14} />
              )
            }
            onClick={() => exportBudgetsMut.mutate()}
            disabled={exportBudgetsMut.isPending}
          >
            {t('finance.export', { defaultValue: 'Export' })}
          </Button>
          <Button
            variant="secondary"
            size="sm"
            icon={<Upload size={14} />}
            onClick={() => {
              setShowImport(true);
              setImportFile(null);
              setImportResult(null);
              setImportError(null);
            }}
          >
            {t('finance.import', { defaultValue: 'Import' })}
          </Button>
          <Button
            variant="primary"
            size="sm"
            icon={<Plus size={14} />}
            onClick={() => setShowCreate(true)}
          >
            {t('finance.new_budget', { defaultValue: 'New Budget Line' })}
          </Button>
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
            {filtered.length === 0 ? (
              <tr>
                <td colSpan={8} className="px-4 py-8 text-center text-sm text-content-tertiary">
                  {t('finance.no_budget_match', { defaultValue: 'No matching budget lines' })}
                </td>
              </tr>
            ) : filtered.map((b) => (
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

    {/* New Budget Line Modal */}
    {showCreate && (
      <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm animate-fade-in">
        <div className="w-full max-w-lg bg-surface-elevated rounded-xl shadow-xl border border-border animate-card-in mx-4" role="dialog" aria-label={t('finance.new_budget', { defaultValue: 'New Budget Line' })}>
          <div className="flex items-center justify-between px-6 py-4 border-b border-border-light">
            <h2 className="text-lg font-semibold text-content-primary">
              {t('finance.new_budget', { defaultValue: 'New Budget Line' })}
            </h2>
            <button
              onClick={() => setShowCreate(false)}
              aria-label={t('common.close', { defaultValue: 'Close' })}
              className="flex h-8 w-8 items-center justify-center rounded-lg text-content-tertiary hover:bg-surface-secondary hover:text-content-primary transition-colors"
            >
              <X size={18} />
            </button>
          </div>
          <div className="px-6 py-4 space-y-4">
            <div>
              <label className="block text-sm font-medium text-content-secondary mb-1">
                {t('finance.wbs', { defaultValue: 'WBS Code' })}
              </label>
              <input
                value={budgetForm.wbs_code}
                onChange={(e) => setBudgetForm((p) => ({ ...p, wbs_code: e.target.value }))}
                className={inputCls}
                placeholder="e.g. 1.2.3"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-content-secondary mb-1">
                {t('finance.category', { defaultValue: 'Category' })} <span className="text-semantic-error">*</span>
              </label>
              <input
                value={budgetForm.category}
                onChange={(e) => setBudgetForm((p) => ({ ...p, category: e.target.value }))}
                className={inputCls}
                placeholder={t('finance.category_placeholder', { defaultValue: 'e.g. Structural Works' })}
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-content-secondary mb-1">
                {t('finance.original', { defaultValue: 'Original Budget' })} <span className="text-semantic-error">*</span>
              </label>
              <input
                type="number"
                step="0.01"
                value={budgetForm.original_budget}
                onChange={(e) => setBudgetForm((p) => ({ ...p, original_budget: e.target.value }))}
                className={inputCls}
                placeholder="0.00"
              />
            </div>
          </div>
          <div className="flex items-center justify-end gap-3 px-6 py-4 border-t border-border-light">
            <Button variant="ghost" onClick={() => setShowCreate(false)} disabled={createBudgetMut.isPending}>
              {t('common.cancel', { defaultValue: 'Cancel' })}
            </Button>
            <Button
              variant="primary"
              onClick={() => {
                if (!budgetForm.category.trim() || !budgetForm.original_budget.trim()) return;
                createBudgetMut.mutate({
                  wbs_id: budgetForm.wbs_code || null,
                  category: budgetForm.category,
                  original_budget: budgetForm.original_budget,
                });
              }}
              disabled={createBudgetMut.isPending || !budgetForm.category.trim() || !budgetForm.original_budget.trim()}
            >
              {createBudgetMut.isPending ? (
                <Loader2 size={16} className="animate-spin mr-1.5" />
              ) : (
                <Plus size={16} className="mr-1.5" />
              )}
              <span>{t('common.create', { defaultValue: 'Create' })}</span>
            </Button>
          </div>
        </div>
      </div>
    )}

    {/* Budget Import Modal */}
    {showImport && (
      <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm animate-fade-in">
        <div className="w-full max-w-lg bg-surface-elevated rounded-xl shadow-xl border border-border animate-card-in mx-4 max-h-[90vh] overflow-y-auto" role="dialog" aria-label={t('finance.import_budgets', { defaultValue: 'Import Budgets' })}>
          <div className="flex items-center justify-between px-6 py-4 border-b border-border-light">
            <h2 className="text-lg font-semibold text-content-primary">
              {t('finance.import_budgets', { defaultValue: 'Import Budgets' })}
            </h2>
            <button
              onClick={() => setShowImport(false)}
              aria-label={t('common.close', { defaultValue: 'Close' })}
              className="flex h-8 w-8 items-center justify-center rounded-lg text-content-tertiary hover:bg-surface-secondary hover:text-content-primary transition-colors"
            >
              <X size={18} />
            </button>
          </div>
          <div className="px-6 py-4 space-y-4">
            <div
              className="flex flex-col items-center justify-center rounded-lg border-2 border-dashed p-8 transition-colors cursor-pointer border-border hover:border-oe-blue/50"
              onClick={() => {
                const input = document.createElement('input');
                input.type = 'file';
                input.accept = '.xlsx,.csv,.xls';
                input.onchange = (e) => {
                  const f = (e.target as HTMLInputElement).files?.[0];
                  if (f) setImportFile(f);
                };
                input.click();
              }}
            >
              <Upload size={24} className="text-content-tertiary mb-2" />
              <p className="text-sm text-content-secondary text-center">
                {importFile
                  ? importFile.name
                  : t('finance.drop_budget_file', {
                      defaultValue: 'Drop Excel or CSV file here, or click to browse',
                    })}
              </p>
              <p className="text-xs text-content-quaternary mt-1">
                {t('finance.budget_file_hint', {
                  defaultValue: 'Columns: WBS Code, Category, Original Budget, Notes',
                })}
              </p>
            </div>
            {importError && (
              <div className="rounded-lg bg-red-50 dark:bg-red-950/20 border border-red-200 dark:border-red-800 p-3 text-sm text-semantic-error">
                {importError}
              </div>
            )}
            {importResult && (
              <div className="rounded-lg bg-green-50 dark:bg-green-950/20 border border-green-200 dark:border-green-800 p-3 text-sm text-content-primary space-y-1">
                <p>
                  {t('finance.import_result', {
                    defaultValue: 'Imported: {{imported}}, Skipped: {{skipped}}, Errors: {{errors}}',
                    imported: importResult.imported,
                    skipped: importResult.skipped,
                    errors: importResult.errors.length,
                  })}
                </p>
                {importResult.errors.length > 0 && (
                  <details className="text-xs text-content-tertiary">
                    <summary className="cursor-pointer">
                      {t('finance.show_errors', { defaultValue: 'Show error details' })}
                    </summary>
                    <ul className="mt-1 space-y-0.5 max-h-32 overflow-y-auto">
                      {importResult.errors.slice(0, 20).map((err, i) => (
                        <li key={i}>Row {err.row}: {err.error}</li>
                      ))}
                    </ul>
                  </details>
                )}
              </div>
            )}
          </div>
          <div className="flex items-center justify-end gap-3 px-6 py-4 border-t border-border-light">
            <Button variant="ghost" onClick={() => setShowImport(false)}>
              {importResult
                ? t('common.close', { defaultValue: 'Close' })
                : t('common.cancel', { defaultValue: 'Cancel' })}
            </Button>
            {!importResult && (
              <Button
                variant="primary"
                onClick={handleBudgetImport}
                disabled={!importFile || importPending}
              >
                {importPending ? (
                  <Loader2 size={16} className="animate-spin mr-1.5" />
                ) : (
                  <Upload size={16} className="mr-1.5" />
                )}
                <span>{t('finance.import_btn', { defaultValue: 'Import' })}</span>
              </Button>
            )}
          </div>
        </div>
      </div>
    )}
    </>
  );
}

/* ── Invoices Tab ─────────────────────────────────────────────────────── */

function InvoicesTab({ projectId }: { projectId: string }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const { confirm, ...confirmProps } = useConfirm();
  const [subTab, setSubTab] = useState<InvoiceSubTab>('payable');
  const [search, setSearch] = useState('');
  const [showCreate, setShowCreate] = useState(false);
  const [invoiceForm, setInvoiceForm] = useState({
    direction: 'payable' as 'payable' | 'receivable',
    counterparty: '',
    contact_id: '',
    invoice_date: '',
    due_date: '',
    amount: '',
    description: '',
  });

  // Escape key handler for inline modal
  useEffect(() => {
    if (!showCreate) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setShowCreate(false);
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [showCreate]);

  const createInvoiceMut = useMutation({
    mutationFn: (data: typeof invoiceForm) =>
      apiPost('/v1/finance/', {
        project_id: projectId,
        contact_id: data.contact_id || undefined,
        invoice_direction: data.direction,
        invoice_date: data.invoice_date,
        due_date: data.due_date || undefined,
        amount_total: data.amount,
        amount_subtotal: data.amount,
        status: 'draft',
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['finance-invoices', projectId] });
      setShowCreate(false);
      setInvoiceForm({ direction: 'payable', counterparty: '', contact_id: '', invoice_date: '', due_date: '', amount: '', description: '' });
      addToast({ type: 'success', title: t('finance.invoice_created', { defaultValue: 'Invoice created' }) });
    },
    onError: (e: Error) =>
      addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: e.message }),
  });

  const exportInvoicesMut = useMutation({
    mutationFn: () =>
      fetchBlobWithAuth(
        `/api/v1/finance/invoices/export?project_id=${encodeURIComponent(projectId)}&direction=${subTab}`,
        'invoices_export.xlsx',
      ),
    onSuccess: () =>
      addToast({
        type: 'success',
        title: t('finance.export_success', { defaultValue: 'Export complete' }),
      }),
    onError: (e: Error) =>
      addToast({
        type: 'error',
        title: t('finance.export_failed', { defaultValue: 'Export failed' }),
        message: e.message,
      }),
  });

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
      {/* Sub-tabs: Payable / Receivable + Export */}
      <div className="flex items-center justify-between">
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
        <div className="flex items-center gap-2">
          <Button
            variant="secondary"
            size="sm"
            icon={
              exportInvoicesMut.isPending ? (
                <Loader2 size={14} className="animate-spin" />
              ) : (
                <Download size={14} />
              )
            }
            onClick={() => exportInvoicesMut.mutate()}
            disabled={exportInvoicesMut.isPending}
          >
            {t('finance.export', { defaultValue: 'Export' })}
          </Button>
          <Button
            variant="primary"
            size="sm"
            icon={<Plus size={14} />}
            onClick={() => {
              setInvoiceForm((f) => ({ ...f, direction: subTab }));
              setShowCreate(true);
            }}
          >
            {t('finance.new_invoice', { defaultValue: 'New Invoice' })}
          </Button>
        </div>
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
                {filtered.length === 0 ? (
                  <tr>
                    <td colSpan={7} className="px-4 py-8 text-center text-sm text-content-tertiary">
                      {t('finance.no_invoice_match', { defaultValue: 'No matching invoices' })}
                    </td>
                  </tr>
                ) : filtered.map((inv) => (
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
                            onClick={async () => {
                              const ok = await confirm({
                                title: t('finance.confirm_approve_title', { defaultValue: 'Approve invoice?' }),
                                message: t('finance.confirm_approve_msg', { defaultValue: 'This invoice will be approved for payment.' }),
                                confirmLabel: t('finance.approve', { defaultValue: 'Approve' }),
                                variant: 'warning',
                              });
                              if (ok) approveMutation.mutate(inv.id);
                            }}
                            loading={approveMutation.isPending}
                          >
                            {t('finance.approve', { defaultValue: 'Approve' })}
                          </Button>
                        )}
                        {inv.status === 'approved' && (
                          <Button
                            variant="primary"
                            size="sm"
                            onClick={async () => {
                              const ok = await confirm({
                                title: t('finance.confirm_pay_title', { defaultValue: 'Mark as paid?' }),
                                message: t('finance.confirm_pay_msg', { defaultValue: 'This invoice will be recorded as paid.' }),
                                confirmLabel: t('finance.mark_paid', { defaultValue: 'Mark Paid' }),
                                variant: 'warning',
                              });
                              if (ok) markPaidMutation.mutate(inv.id);
                            }}
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

      {/* New Invoice Modal */}
      {showCreate && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm animate-fade-in">
          <div className="w-full max-w-lg bg-surface-elevated rounded-xl shadow-xl border border-border animate-card-in mx-4 max-h-[90vh] overflow-y-auto" role="dialog" aria-label={t('finance.new_invoice', { defaultValue: 'New Invoice' })}>
            <div className="flex items-center justify-between px-6 py-4 border-b border-border-light">
              <h2 className="text-lg font-semibold text-content-primary">
                {t('finance.new_invoice', { defaultValue: 'New Invoice' })}
              </h2>
              <button
                onClick={() => setShowCreate(false)}
                aria-label={t('common.close', { defaultValue: 'Close' })}
                className="flex h-8 w-8 items-center justify-center rounded-lg text-content-tertiary hover:bg-surface-secondary hover:text-content-primary transition-colors"
              >
                <X size={18} />
              </button>
            </div>
            <div className="px-6 py-4 space-y-4">
              {/* Direction */}
              <div>
                <label className="block text-sm font-medium text-content-secondary mb-2">
                  {t('finance.direction', { defaultValue: 'Direction' })}
                </label>
                <div className="flex items-center gap-2">
                  {(['payable', 'receivable'] as const).map((d) => (
                    <button
                      key={d}
                      onClick={() => setInvoiceForm((f) => ({ ...f, direction: d }))}
                      className={clsx(
                        'rounded-lg px-3 py-1.5 text-sm font-medium transition-colors border',
                        invoiceForm.direction === d
                          ? 'bg-oe-blue-subtle text-oe-blue border-oe-blue/30'
                          : 'border-border text-content-tertiary hover:text-content-secondary',
                      )}
                    >
                      {d === 'payable'
                        ? t('finance.payable', { defaultValue: 'Payable' })
                        : t('finance.receivable', { defaultValue: 'Receivable' })}
                    </button>
                  ))}
                </div>
              </div>
              {/* Vendor / Client (contact search) */}
              <div>
                <label className="block text-sm font-medium text-content-secondary mb-1">
                  {invoiceForm.direction === 'payable'
                    ? t('finance.vendor', { defaultValue: 'Vendor' })
                    : t('finance.client', { defaultValue: 'Client' })}
                </label>
                <ContactSearchInput
                  value={invoiceForm.counterparty}
                  onChange={(id, name) => setInvoiceForm((f) => ({ ...f, counterparty: name, contact_id: id }))}
                  placeholder={
                    invoiceForm.direction === 'payable'
                      ? t('finance.search_vendor', { defaultValue: 'Search vendor...' })
                      : t('finance.search_client', { defaultValue: 'Search client...' })
                  }
                />
              </div>
              {/* Invoice date */}
              <div>
                <label className="block text-sm font-medium text-content-secondary mb-1">
                  {t('finance.issue_date', { defaultValue: 'Invoice Date' })} <span className="text-semantic-error">*</span>
                </label>
                <input
                  type="date"
                  value={invoiceForm.invoice_date}
                  onChange={(e) => setInvoiceForm((f) => ({ ...f, invoice_date: e.target.value }))}
                  className={inputCls}
                />
              </div>
              {/* Due date */}
              <div>
                <label className="block text-sm font-medium text-content-secondary mb-1">
                  {t('finance.due_date', { defaultValue: 'Due Date' })}
                </label>
                <input
                  type="date"
                  value={invoiceForm.due_date}
                  onChange={(e) => setInvoiceForm((f) => ({ ...f, due_date: e.target.value }))}
                  className={inputCls}
                />
              </div>
              {/* Amount */}
              <div>
                <label className="block text-sm font-medium text-content-secondary mb-1">
                  {t('finance.amount', { defaultValue: 'Amount' })} <span className="text-semantic-error">*</span>
                </label>
                <input
                  type="number"
                  step="0.01"
                  value={invoiceForm.amount}
                  onChange={(e) => setInvoiceForm((f) => ({ ...f, amount: e.target.value }))}
                  className={inputCls}
                  placeholder="0.00"
                />
              </div>
              {/* Description */}
              <div>
                <label className="block text-sm font-medium text-content-secondary mb-1">
                  {t('tasks.field_description', { defaultValue: 'Description' })}
                </label>
                <input
                  value={invoiceForm.description}
                  onChange={(e) => setInvoiceForm((f) => ({ ...f, description: e.target.value }))}
                  className={inputCls}
                  placeholder={t('finance.invoice_desc_placeholder', { defaultValue: 'Optional description' })}
                />
              </div>
            </div>
            <div className="flex items-center justify-end gap-3 px-6 py-4 border-t border-border-light">
              <Button variant="ghost" onClick={() => setShowCreate(false)} disabled={createInvoiceMut.isPending}>
                {t('common.cancel', { defaultValue: 'Cancel' })}
              </Button>
              <Button
                variant="primary"
                onClick={() => createInvoiceMut.mutate(invoiceForm)}
                disabled={createInvoiceMut.isPending || !invoiceForm.invoice_date || !invoiceForm.amount}
              >
                {createInvoiceMut.isPending ? (
                  <Loader2 size={16} className="animate-spin mr-1.5" />
                ) : (
                  <Plus size={16} className="mr-1.5" />
                )}
                <span>{t('common.create', { defaultValue: 'Create' })}</span>
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* Confirm Dialog */}
      <ConfirmDialog {...confirmProps} />
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
