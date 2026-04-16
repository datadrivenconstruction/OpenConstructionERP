import { useState, useMemo, useEffect, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { useParams, useNavigate, Link } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { normalizeListResponse } from '@/shared/lib/apiHelpers';
import {
  Wallet,
  FileText,
  CreditCard,
  BarChart3,
  Search,
  ArrowUpRight,
  ArrowDownLeft,
  ArrowDownRight,
  Download,
  Upload,
  Loader2,
  X,
  Plus,
  Camera,
  ChevronDown,
  Lightbulb,
  TrendingUp,
  ExternalLink,
  DollarSign,
  Receipt,
  PiggyBank,
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
import { apiGet, apiPost, triggerDownload } from '@/shared/lib/api';
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

interface InvoiceLineItem {
  id: string;
  description: string;
  quantity: string;
  unit: string | null;
  unit_rate: string;
  amount: string;
  wbs_id: string | null;
  cost_category: string | null;
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
  line_items?: InvoiceLineItem[];
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

/* ── Finance Summary Cards ────────────────────────────────────────────── */

function FinanceSummaryCards({ projectId }: { projectId: string }) {
  const { t } = useTranslation();

  const { data: budgets } = useQuery({
    queryKey: ['finance-budgets', projectId],
    queryFn: () =>
      apiGet<BudgetLine[]>(`/v1/finance/budgets?project_id=${projectId}`),
    select: (d): BudgetLine[] => normalizeListResponse(d),
  });

  const { data: invoicesPayable } = useQuery({
    queryKey: ['finance-invoices', projectId, 'payable'],
    queryFn: () =>
      apiGet<Invoice[]>(`/v1/finance/?project_id=${projectId}&direction=payable`),
    select: (d): Invoice[] => normalizeListResponse(d),
  });

  const { data: invoicesReceivable } = useQuery({
    queryKey: ['finance-invoices', projectId, 'receivable'],
    queryFn: () =>
      apiGet<Invoice[]>(`/v1/finance/?project_id=${projectId}&direction=receivable`),
    select: (d): Invoice[] => normalizeListResponse(d),
  });

  const totalBudget = useMemo(
    () => budgets?.reduce((s, b) => s + b.original_budget, 0) ?? 0,
    [budgets],
  );
  const totalActual = useMemo(
    () => budgets?.reduce((s, b) => s + b.actual, 0) ?? 0,
    [budgets],
  );
  const totalInvoiced = useMemo(
    () => (invoicesPayable ?? []).reduce((s, inv) => s + inv.amount, 0),
    [invoicesPayable],
  );
  const totalReceivable = useMemo(
    () => (invoicesReceivable ?? []).reduce((s, inv) => s + inv.amount, 0),
    [invoicesReceivable],
  );
  const remaining = totalBudget - totalActual;
  const currency = budgets?.[0]?.currency || invoicesPayable?.[0]?.currency || 'EUR';

  if (!budgets?.length && !invoicesPayable?.length && !invoicesReceivable?.length) return null;

  const cards = [
    {
      label: t('finance.summary_total_budget', { defaultValue: 'Total Budget' }),
      value: totalBudget,
      icon: <Wallet size={18} />,
      color: 'bg-oe-blue/10 text-oe-blue',
      accent: 'bg-oe-blue',
    },
    {
      label: t('finance.summary_total_invoiced', { defaultValue: 'Total Invoiced (Payable)' }),
      value: totalInvoiced,
      icon: <Receipt size={18} />,
      color: 'bg-amber-50 text-amber-600 dark:bg-amber-950/40 dark:text-amber-400',
      accent: 'bg-amber-500',
    },
    {
      label: t('finance.summary_receivable', { defaultValue: 'Receivable' }),
      value: totalReceivable,
      icon: <PiggyBank size={18} />,
      color: 'bg-green-50 text-green-600 dark:bg-green-950/40 dark:text-green-400',
      accent: 'bg-green-500',
    },
    {
      label: t('finance.summary_remaining', { defaultValue: 'Remaining Budget' }),
      value: remaining,
      icon: <DollarSign size={18} />,
      color: remaining >= 0
        ? 'bg-green-50 text-green-600 dark:bg-green-950/40 dark:text-green-400'
        : 'bg-red-50 text-red-600 dark:bg-red-950/40 dark:text-red-400',
      accent: remaining >= 0 ? 'bg-green-500' : 'bg-red-500',
    },
  ];

  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
      {cards.map((card) => (
        <Card key={card.label} padding="none" className="relative overflow-hidden">
          <div className={`absolute top-0 left-0 right-0 h-1 ${card.accent}`} />
          <div className="p-4 pt-3">
            <div className="flex items-center justify-between mb-2">
              <span className="text-2xs font-medium uppercase tracking-wider text-content-tertiary">
                {card.label}
              </span>
              <div className={`flex h-8 w-8 items-center justify-center rounded-lg ${card.color}`}>
                {card.icon}
              </div>
            </div>
            <div className="text-xl font-bold tabular-nums text-content-primary">
              <MoneyDisplay amount={card.value} currency={currency} />
            </div>
          </div>
        </Card>
      ))}
    </div>
  );
}

/* ── Module Links ────────────────────────────────────────────────────── */

function FinanceModuleLinks({ projectId: _projectId }: { projectId: string }) {
  void _projectId;
  const { t } = useTranslation();

  return (
    <div className="flex flex-wrap items-center gap-3">
      <Link
        to="/boq"
        className="inline-flex items-center gap-1.5 rounded-lg border border-border-light bg-surface-primary px-3 py-1.5 text-xs font-medium text-content-secondary hover:bg-surface-secondary hover:text-oe-blue transition-colors"
      >
        <ExternalLink size={12} />
        {t('finance.link_to_boq', { defaultValue: 'BOQ Estimate' })}
      </Link>
      <Link
        to="/5d"
        className="inline-flex items-center gap-1.5 rounded-lg border border-border-light bg-surface-primary px-3 py-1.5 text-xs font-medium text-content-secondary hover:bg-surface-secondary hover:text-oe-blue transition-colors"
      >
        <TrendingUp size={12} />
        {t('finance.link_to_5d', { defaultValue: '5D Cost Model' })}
      </Link>
    </div>
  );
}

/* ── Main Page ────────────────────────────────────────────────────────── */

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
    <div className="w-full animate-fade-in">
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

      {/* Header + Module Links */}
      <div className="mb-6 flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
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
        {projectId && <FinanceModuleLinks projectId={projectId} />}
      </div>

      {/* No-project warning */}
      {!projectId && (
        <div className="mb-6 rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800 dark:border-amber-800 dark:bg-amber-950/30 dark:text-amber-300">
          {t('common.select_project_hint', { defaultValue: 'Select a project from the header to get started.' })}
        </div>
      )}

      {/* Summary Cards */}
      {projectId && (
        <div className="mb-6">
          <FinanceSummaryCards projectId={projectId} />
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
          icon={<Wallet size={28} strokeWidth={1.5} />}
          title={t('finance.no_project', {
            defaultValue: 'No project selected',
          })}
          description={t('finance.select_project', {
            defaultValue:
              'Track invoices, budgets, and payments here. Select a project to view its financial data, or lock a BOQ to auto-generate budget lines.',
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

const INITIAL_BUDGET_FORM = { wbs_code: '', category: '', original_budget: '', notes: '' };

function BudgetsTab({ projectId }: { projectId: string }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [search, setSearch] = useState('');
  const [showImport, setShowImport] = useState(false);
  const [importFile, setImportFile] = useState<File | null>(null);
  const [importPending, setImportPending] = useState(false);
  const [importResult, setImportResult] = useState<BudgetImportResult | null>(null);
  const [importError, setImportError] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [budgetForm, setBudgetForm] = useState(INITIAL_BUDGET_FORM);
  const [budgetErrors, setBudgetErrors] = useState<Record<string, string>>({});
  const budgetFirstRef = useRef<HTMLInputElement>(null);

  // Auto-focus budget WBS input when modal opens
  useEffect(() => {
    if (showCreate && budgetFirstRef.current) {
      setTimeout(() => budgetFirstRef.current?.focus(), 100);
    }
  }, [showCreate]);

  const canSubmitBudget = budgetForm.category.trim().length > 0 && budgetForm.original_budget.trim().length > 0 && parseFloat(budgetForm.original_budget) > 0;

  const validateBudget = (): boolean => {
    const e: Record<string, string> = {};
    if (!budgetForm.category.trim()) e.category = t('validation.required', { defaultValue: 'This field is required' });
    if (!budgetForm.original_budget.trim()) e.original_budget = t('validation.required', { defaultValue: 'This field is required' });
    else if (parseFloat(budgetForm.original_budget) <= 0) e.original_budget = t('validation.positive_number', { defaultValue: 'Must be a positive number' });
    setBudgetErrors(e);
    return Object.keys(e).length === 0;
  };

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
    mutationFn: (data: { wbs_id: string | null; category: string | null; original_budget: string; notes: string | null }) =>
      apiPost('/v1/finance/budgets/', {
        project_id: projectId,
        wbs_id: data.wbs_id,
        category: data.category,
        original_budget: data.original_budget,
        notes: data.notes || undefined,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['finance-budgets', projectId] });
      setShowCreate(false);
      setBudgetForm(INITIAL_BUDGET_FORM);
      addToast({ type: 'success', title: t('finance.budget_created', { defaultValue: 'Budget line created successfully' }) });
    },
    onError: (e: Error) =>
      addToast({ type: 'error', title: t('finance.budget_create_failed', { defaultValue: 'Failed to create budget line' }), message: e.message }),
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
        title: t('finance.export_success', { defaultValue: 'Budget data exported successfully' }),
      }),
    onError: (e: Error) =>
      addToast({
        type: 'error',
        title: t('finance.export_failed', { defaultValue: 'Failed to export budget data' }),
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

  const BUDGET_CATEGORIES = [
    { key: 'Material', label: t('finance.cat_material', { defaultValue: 'Material' }) },
    { key: 'Labor', label: t('finance.cat_labor', { defaultValue: 'Labor' }) },
    { key: 'Equipment', label: t('finance.cat_equipment', { defaultValue: 'Equipment' }) },
    { key: 'Subcontract', label: t('finance.cat_subcontract', { defaultValue: 'Subcontract' }) },
    { key: 'Overhead', label: t('finance.cat_overhead', { defaultValue: 'Overhead' }) },
    { key: 'Other', label: t('finance.cat_other', { defaultValue: 'Other' }) },
  ];

  const renderBudgetModal = () => (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm animate-fade-in">
      <div className="w-full max-w-lg bg-surface-elevated rounded-xl shadow-xl border border-border animate-card-in mx-4 max-h-[90vh] overflow-y-auto" role="dialog" aria-label={t('finance.new_budget', { defaultValue: 'New Budget Line' })}>
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
        <div className="px-6 py-5 space-y-5">
          {/* Category — visual badges */}
          <div>
            <label className="block text-sm font-medium text-content-primary mb-2">
              {t('finance.category', { defaultValue: 'Category' })} <span className="text-semantic-error">*</span>
            </label>
            <div className="flex flex-wrap gap-2">
              {BUDGET_CATEGORIES.map((cat) => (
                <button
                  key={cat.key}
                  type="button"
                  onClick={() => {
                    setBudgetForm((p) => ({ ...p, category: cat.key }));
                    if (budgetErrors.category) setBudgetErrors((prev) => { const next = { ...prev }; delete next.category; return next; });
                  }}
                  className={clsx(
                    'rounded-full px-3.5 py-1.5 text-xs font-medium border transition-all',
                    budgetForm.category === cat.key
                      ? 'bg-oe-blue text-white border-oe-blue shadow-sm'
                      : 'border-border text-content-secondary hover:border-oe-blue/40 hover:bg-surface-secondary',
                  )}
                >
                  {cat.label}
                </button>
              ))}
            </div>
            {budgetErrors.category && <p className="mt-1.5 text-xs text-semantic-error">{budgetErrors.category}</p>}
          </div>

          {/* WBS Code */}
          <div>
            <label className="block text-sm font-medium text-content-primary mb-1.5">
              {t('finance.wbs', { defaultValue: 'WBS Code' })}
            </label>
            <input
              ref={budgetFirstRef}
              value={budgetForm.wbs_code}
              onChange={(e) => setBudgetForm((p) => ({ ...p, wbs_code: e.target.value }))}
              className={inputCls}
              placeholder={t('finance.wbs_placeholder', { defaultValue: 'e.g., 01.02' })}
            />
          </div>

          {/* Original Budget with currency */}
          <div>
            <label className="block text-sm font-medium text-content-primary mb-1.5">
              {t('finance.original', { defaultValue: 'Original Budget' })} <span className="text-semantic-error">*</span>
            </label>
            <div className="relative">
              <span className="pointer-events-none absolute inset-y-0 left-0 flex items-center pl-3 text-xs text-content-tertiary font-medium">
                {budgets?.[0]?.currency ?? 'EUR'}
              </span>
              <input
                type="number"
                step="0.01"
                value={budgetForm.original_budget}
                onChange={(e) => {
                  setBudgetForm((p) => ({ ...p, original_budget: e.target.value }));
                  if (budgetErrors.original_budget) setBudgetErrors((prev) => { const next = { ...prev }; delete next.original_budget; return next; });
                }}
                className={clsx(inputCls, 'pl-12', budgetErrors.original_budget && 'border-semantic-error focus:ring-red-300 focus:border-semantic-error')}
                placeholder="0.00"
              />
            </div>
            {budgetErrors.original_budget && <p className="mt-1 text-xs text-semantic-error">{budgetErrors.original_budget}</p>}
          </div>

          {/* Notes */}
          <div>
            <label className="block text-sm font-medium text-content-primary mb-1.5">
              {t('finance.notes', { defaultValue: 'Notes' })}
            </label>
            <textarea
              value={budgetForm.notes}
              onChange={(e) => setBudgetForm((p) => ({ ...p, notes: e.target.value }))}
              rows={2}
              className={clsx(inputCls, 'h-auto py-2.5 resize-none')}
              placeholder={t('finance.budget_notes_placeholder', { defaultValue: 'e.g., Includes contingency for weather delays' })}
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
              if (!validateBudget()) return;
              createBudgetMut.mutate({
                wbs_id: budgetForm.wbs_code || null,
                category: budgetForm.category,
                original_budget: budgetForm.original_budget,
                notes: budgetForm.notes || null,
              });
            }}
            disabled={createBudgetMut.isPending || !canSubmitBudget}
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
  );

  const { data: budgets, isLoading } = useQuery({
    queryKey: ['finance-budgets', projectId],
    queryFn: () =>
      apiGet<BudgetLine[]>(
        `/v1/finance/budgets?project_id=${projectId}`,
      ),
    select: (d): BudgetLine[] => normalizeListResponse(d),
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
      <div className="space-y-4">
        {/* BOQ tip */}
        <div className="p-4 bg-blue-50 dark:bg-blue-950/30 rounded-lg border border-blue-200 dark:border-blue-800 text-sm flex items-start gap-3">
          <Lightbulb size={18} className="text-blue-600 dark:text-blue-400 shrink-0 mt-0.5" />
          <div>
            <strong className="text-blue-800 dark:text-blue-200">
              {t('finance.boq_tip_title', { defaultValue: 'Tip:' })}
            </strong>{' '}
            <span className="text-blue-700 dark:text-blue-300">
              {t('finance.boq_tip_desc', {
                defaultValue:
                  'Go to your BOQ \u2192 Lock the estimate \u2192 Click "Create Budget from Estimate" to auto-populate budget lines.',
              })}
            </span>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => navigate('/boq')}
              className="ml-2 text-blue-700 dark:text-blue-300 hover:text-blue-900"
            >
              {t('finance.go_to_boq', { defaultValue: 'Go to BOQ \u2192' })}
            </Button>
          </div>
        </div>

        <EmptyState
          icon={<Wallet size={28} strokeWidth={1.5} />}
          title={t('finance.no_budgets', { defaultValue: 'No budget lines yet' })}
          description={t('finance.no_budgets_desc', {
            defaultValue:
              'Lock your BOQ estimate and click "Create Budget from Estimate" to automatically generate budget lines from your sections. You can also create budget lines manually.',
          })}
          action={{
            label: t('finance.new_budget', { defaultValue: 'New Budget Line' }),
            onClick: () => setShowCreate(true),
          }}
        />

        {/* New Budget Line Modal (also shown from empty state) */}
        {showCreate && renderBudgetModal()}
      </div>
    );
  }

  return (
    <>
    {/* Explanatory text + module link */}
    <div className="flex items-start justify-between gap-3 mb-4">
      <p className="text-sm text-content-secondary">
        {t('finance.budgets_explanation', {
          defaultValue: 'Project budget tracks original vs actual costs by WBS category. Variance is highlighted green when under budget, red when over.',
        })}
      </p>
      <Link
        to="/5d"
        className="shrink-0 inline-flex items-center gap-1.5 rounded-lg bg-oe-blue-subtle/30 px-3 py-1.5 text-xs font-medium text-oe-blue hover:bg-oe-blue-subtle/50 transition-colors"
      >
        <TrendingUp size={12} />
        {t('finance.view_5d_model', { defaultValue: 'Open 5D Cost Model' })}
      </Link>
    </div>

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
            aria-label={t('finance.search_budgets', { defaultValue: 'Search by WBS or category...' })}
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
                        ? 'text-semantic-success font-medium'
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
    {showCreate && renderBudgetModal()}

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
              role="button"
              tabIndex={0}
              aria-label={t('finance.drop_budget_file', { defaultValue: 'Drop Excel or CSV file here, or click to browse' })}
              className="flex flex-col items-center justify-center rounded-lg border-2 border-dashed p-8 transition-colors cursor-pointer border-border hover:border-oe-blue/50 focus:outline-none focus:ring-2 focus:ring-oe-blue/30"
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
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                  e.preventDefault();
                  (e.currentTarget as HTMLElement).click();
                }
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
                      {importResult.errors.slice(0, 20).map((err) => (
                        <li key={`row-${err.row}`}>Row {err.row}: {err.error}</li>
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
  const userRole = useAuthStore((s) => s.userRole);
  const invoiceProjectName = useProjectContextStore((s) => s.activeProjectName);
  const isManager = userRole === 'admin' || userRole === 'manager';
  const [subTab, setSubTab] = useState<InvoiceSubTab>('payable');
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState<string>('');
  const [showCreate, setShowCreate] = useState(false);

  const todayStr = new Date().toISOString().split('T')[0];

  const [invoiceForm, setInvoiceForm] = useState({
    direction: 'payable' as 'payable' | 'receivable',
    counterparty: '',
    contact_id: '',
    invoice_date: todayStr,
    due_date: '',
    subtotal: '',
    tax: '',
    amount: '',
    currency: 'EUR',
    description: '',
  });
  const [invoiceErrors, setInvoiceErrors] = useState<Record<string, string>>({});
  const invoiceDateRef = useRef<HTMLInputElement>(null);

  // Auto-focus invoice date when modal opens
  useEffect(() => {
    if (showCreate && invoiceDateRef.current) {
      setTimeout(() => invoiceDateRef.current?.focus(), 100);
    }
  }, [showCreate]);

  const canSubmitInvoice = !!invoiceForm.invoice_date && (parseFloat(invoiceForm.subtotal || '0') > 0 || parseFloat(invoiceForm.amount || '0') > 0);

  const validateInvoice = (): boolean => {
    const e: Record<string, string> = {};
    if (!invoiceForm.invoice_date) e.invoice_date = t('validation.required', { defaultValue: 'This field is required' });
    if (!invoiceForm.subtotal && !invoiceForm.amount) e.subtotal = t('validation.required', { defaultValue: 'This field is required' });
    else {
      const total = invoiceForm.amount ? parseFloat(invoiceForm.amount) : (parseFloat(invoiceForm.subtotal || '0') + parseFloat(invoiceForm.tax || '0'));
      if (total <= 0) e.subtotal = t('validation.positive_number', { defaultValue: 'Must be a positive number' });
    }
    setInvoiceErrors(e);
    return Object.keys(e).length === 0;
  };

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
    mutationFn: (data: typeof invoiceForm) => {
      const sub = parseFloat(data.subtotal || '0');
      const tax = parseFloat(data.tax || '0');
      const total = data.amount ? parseFloat(data.amount) : sub + tax;
      return apiPost('/v1/finance/', {
        project_id: projectId,
        contact_id: data.contact_id || undefined,
        invoice_direction: data.direction,
        invoice_date: data.invoice_date,
        due_date: data.due_date || undefined,
        amount_subtotal: String(sub),
        tax_amount: String(tax),
        amount_total: String(total),
        currency_code: data.currency || 'EUR',
        notes: data.description || undefined,
        status: 'draft',
      });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['finance-invoices', projectId] });
      setShowCreate(false);
      setInvoiceForm({ direction: 'payable', counterparty: '', contact_id: '', invoice_date: todayStr, due_date: '', subtotal: '', tax: '', amount: '', currency: 'EUR', description: '' });
      addToast({ type: 'success', title: t('finance.invoice_created', { defaultValue: 'Invoice created successfully' }) });
    },
    onError: (e: Error) =>
      addToast({ type: 'error', title: t('finance.invoice_create_failed', { defaultValue: 'Failed to create invoice' }), message: e.message }),
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
        title: t('finance.invoices_export_success', { defaultValue: 'Invoices exported successfully' }),
      }),
    onError: (e: Error) =>
      addToast({
        type: 'error',
        title: t('finance.invoices_export_failed', { defaultValue: 'Failed to export invoices' }),
        message: e.message,
      }),
  });

  const { data: invoices, isLoading } = useQuery({
    queryKey: ['finance-invoices', projectId, subTab],
    queryFn: () =>
      apiGet<Invoice[]>(
        `/v1/finance/?project_id=${projectId}&direction=${subTab}`,
      ),
    select: (d): Invoice[] => normalizeListResponse(d),
  });

  const filtered = useMemo(() => {
    if (!invoices) return [];
    let result = invoices;
    if (statusFilter) {
      result = result.filter((inv) => inv.status === statusFilter);
    }
    if (search) {
      const q = search.toLowerCase();
      result = result.filter(
        (inv) =>
          inv.invoice_number.toLowerCase().includes(q) ||
          inv.counterparty_name.toLowerCase().includes(q),
      );
    }
    return result;
  }, [invoices, search, statusFilter]);

  const invoiceTotals = useMemo(() => {
    if (!filtered.length) return null;
    const totalAmount = filtered.reduce((s, inv) => s + inv.amount, 0);
    const totalPaid = filtered.filter((inv) => inv.status === 'paid').reduce((s, inv) => s + inv.amount, 0);
    const currency = filtered[0]?.currency ?? 'EUR';
    return { totalAmount, totalPaid, currency };
  }, [filtered]);

  const approveMutation = useMutation({
    mutationFn: (invoiceId: string) =>
      apiPost(`/v1/finance/${invoiceId}/approve/`),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ['finance-invoices', projectId],
      });
      addToast({
        type: 'success',
        title: t('finance.invoice_approved', {
          defaultValue: 'Invoice approved successfully',
        }),
      });
    },
    onError: (e: Error) =>
      addToast({ type: 'error', title: t('finance.approve_failed', { defaultValue: 'Failed to approve invoice' }), message: e.message }),
  });

  const markPaidMutation = useMutation({
    mutationFn: (invoiceId: string) =>
      apiPost(`/v1/finance/${invoiceId}/pay/`),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ['finance-invoices', projectId],
      });
      addToast({
        type: 'success',
        title: t('finance.invoice_paid', { defaultValue: 'Invoice marked as paid successfully' }),
      });
    },
    onError: (e: Error) =>
      addToast({ type: 'error', title: t('finance.pay_failed', { defaultValue: 'Failed to mark invoice as paid' }), message: e.message }),
  });

  return (
    <div className="space-y-4">
      {/* Sub-tabs: Payable / Receivable + Export */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2" title={t('finance.payable_receivable_tooltip', { defaultValue: 'Payable = invoices you owe to vendors. Receivable = invoices clients owe to you.' })}>
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
              setInvoiceForm({ direction: subTab, counterparty: '', contact_id: '', invoice_date: todayStr, due_date: '', subtotal: '', tax: '', amount: '', currency: 'EUR', description: '' });
              setInvoiceErrors({});
              setShowCreate(true);
            }}
          >
            {t('finance.new_invoice', { defaultValue: 'New Invoice' })}
          </Button>
        </div>
      </div>

      <Card padding="none">
        {/* Search + Status filter */}
        <div className="p-4 border-b border-border-light flex flex-col sm:flex-row sm:items-center gap-3">
          <div className="relative flex-1 max-w-sm">
            <div className="pointer-events-none absolute inset-y-0 left-0 flex items-center pl-3 text-content-tertiary">
              <Search size={16} />
            </div>
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              aria-label={t('finance.search_invoices', { defaultValue: 'Search invoices...' })}
              placeholder={t('finance.search_invoices', {
                defaultValue: 'Search invoices...',
              })}
              className="h-10 w-full rounded-lg border border-border bg-surface-primary pl-10 pr-3 text-sm text-content-primary placeholder:text-content-tertiary focus:outline-none focus:ring-2 focus:ring-oe-blue focus:border-transparent"
            />
          </div>
          <div className="relative shrink-0">
            <select
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
              aria-label={t('finance.filter_status', { defaultValue: 'Filter by status' })}
              className="h-10 appearance-none rounded-lg border border-border bg-surface-primary pl-3 pr-9 text-sm text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue sm:w-36"
            >
              <option value="">{t('finance.filter_all_statuses', { defaultValue: 'All Statuses' })}</option>
              <option value="draft">{t('finance.status_draft', { defaultValue: 'Draft' })}</option>
              <option value="pending">{t('finance.status_pending', { defaultValue: 'Pending' })}</option>
              <option value="approved">{t('finance.status_approved', { defaultValue: 'Approved' })}</option>
              <option value="paid">{t('finance.status_paid', { defaultValue: 'Paid' })}</option>
            </select>
            <div className="pointer-events-none absolute inset-y-0 right-0 flex items-center pr-2.5 text-content-tertiary">
              <ChevronDown size={14} />
            </div>
          </div>
        </div>

        {isLoading ? (
          <SkeletonTable rows={5} columns={6} />
        ) : !filtered.length ? (
          <div className="p-8">
            <EmptyState
              icon={<FileText size={28} strokeWidth={1.5} />}
              title={
                search || statusFilter
                  ? t('finance.no_invoices_match', { defaultValue: 'No matching invoices' })
                  : t('finance.no_invoices', { defaultValue: 'No invoices yet' })
              }
              description={
                search || statusFilter
                  ? t('finance.no_invoices_match_desc', { defaultValue: 'Try adjusting your search or status filter.' })
                  : t('finance.no_invoices_desc', {
                      defaultValue: 'Create your first invoice to start tracking payables and receivables.',
                    })
              }
              action={
                !search && !statusFilter
                  ? {
                      label: t('finance.new_invoice', { defaultValue: 'New Invoice' }),
                      onClick: () => {
                        setInvoiceForm({ direction: subTab, counterparty: '', contact_id: '', invoice_date: todayStr, due_date: '', subtotal: '', tax: '', amount: '', currency: 'EUR', description: '' });
                        setInvoiceErrors({});
                        setShowCreate(true);
                      },
                    }
                  : undefined
              }
            />
          </div>
        ) : (
          <>
            {/* Desktop table */}
            <div className="hidden md:block overflow-x-auto">
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
                        <div>{inv.counterparty_name}</div>
                        {inv.line_items && inv.line_items.length > 0 && inv.line_items.some((li) => li.cost_category || li.wbs_id) && (
                          <div className="flex items-center gap-1 text-2xs text-content-tertiary mt-0.5">
                            <span>
                              {t('finance.budget_line', { defaultValue: 'Budget' })}:{' '}
                              {inv.line_items
                                .filter((li) => li.cost_category || li.wbs_id)
                                .slice(0, 2)
                                .map((li) => li.cost_category || li.wbs_id)
                                .join(', ')}
                            </span>
                            <Link
                              to="/boq"
                              className="inline-flex items-center gap-0.5 text-oe-blue hover:underline"
                              title={t('finance.view_in_boq', { defaultValue: 'View in BOQ' })}
                              onClick={(e) => e.stopPropagation()}
                            >
                              <ExternalLink size={10} />
                              <span>BOQ</span>
                            </Link>
                          </div>
                        )}
                        {inv.description && (!inv.line_items || !inv.line_items.some((li) => li.cost_category || li.wbs_id)) && (
                          <div className="text-2xs text-content-quaternary mt-0.5 truncate max-w-[200px]">
                            {inv.description}
                          </div>
                        )}
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
                          {inv.status === 'pending' && isManager && (
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
                          {inv.status === 'approved' && isManager && (
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
                {invoiceTotals && (
                  <tfoot>
                    <tr className="bg-surface-secondary/60 font-semibold">
                      <td className="px-4 py-3 text-content-primary" colSpan={4}>
                        {t('common.total', { defaultValue: 'Total' })}
                      </td>
                      <td className="px-4 py-3 text-right">
                        <MoneyDisplay amount={invoiceTotals.totalAmount} currency={invoiceTotals.currency} />
                      </td>
                      <td className="px-4 py-3 text-center text-xs text-content-tertiary">
                        {t('finance.total_paid', { defaultValue: 'Paid' })}:{' '}
                        <MoneyDisplay amount={invoiceTotals.totalPaid} currency={invoiceTotals.currency} />
                      </td>
                      <td />
                    </tr>
                  </tfoot>
                )}
              </table>
            </div>

            {/* Mobile card view */}
            <div className="md:hidden p-4 space-y-3">
              {filtered.map((inv) => (
                <Card key={inv.id} className="p-4">
                  <div className="flex items-start justify-between gap-2 mb-2">
                    <div className="min-w-0">
                      <span className="text-xs font-mono text-content-tertiary">{inv.invoice_number}</span>
                      <h4 className="text-sm font-semibold text-content-primary truncate">{inv.counterparty_name}</h4>
                    </div>
                    <Badge variant={INVOICE_STATUS_COLORS[inv.status] ?? 'neutral'} size="sm">
                      {t(`finance.status_${inv.status}`, { defaultValue: inv.status })}
                    </Badge>
                  </div>
                  <div className="flex items-center justify-between text-xs text-content-tertiary">
                    <span><DateDisplay value={inv.issue_date} /></span>
                    <span className="font-semibold text-content-primary">
                      <MoneyDisplay amount={inv.amount} currency={inv.currency} />
                    </span>
                  </div>
                  {inv.due_date && (
                    <div className="text-xs text-content-tertiary mt-1">
                      {t('finance.due_date', { defaultValue: 'Due' })}: <DateDisplay value={inv.due_date} />
                    </div>
                  )}
                </Card>
              ))}
            </div>
          </>
        )}
      </Card>

      {/* New Invoice Modal */}
      {showCreate && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm animate-fade-in">
          <div className="w-full max-w-xl bg-surface-elevated rounded-xl shadow-xl border border-border animate-card-in mx-4 max-h-[90vh] overflow-y-auto" role="dialog" aria-label={t('finance.new_invoice', { defaultValue: 'New Invoice' })}>
            <div className="flex items-center justify-between px-6 py-4 border-b border-border-light">
              <div>
                <h2 className="text-lg font-semibold text-content-primary">
                  {t('finance.new_invoice', { defaultValue: 'New Invoice' })}
                </h2>
                {invoiceProjectName && (
                  <p className="text-xs text-content-tertiary mt-0.5">
                    {t('common.creating_in_project', {
                      defaultValue: 'In {{project}}',
                      project: invoiceProjectName,
                    })}
                  </p>
                )}
              </div>
              <button
                onClick={() => setShowCreate(false)}
                aria-label={t('common.close', { defaultValue: 'Close' })}
                className="flex h-8 w-8 items-center justify-center rounded-lg text-content-tertiary hover:bg-surface-secondary hover:text-content-primary transition-colors"
              >
                <X size={18} />
              </button>
            </div>
            <div className="px-6 py-5 space-y-5">
              {/* Direction — large visual cards */}
              <div>
                <label className="block text-sm font-medium text-content-secondary mb-2.5">
                  {t('finance.direction', { defaultValue: 'Direction' })}
                </label>
                <div className="grid grid-cols-2 gap-3">
                  <button
                    type="button"
                    onClick={() => setInvoiceForm((f) => ({ ...f, direction: 'payable' }))}
                    className={clsx(
                      'relative flex flex-col items-center gap-2 rounded-xl border-2 p-4 transition-all',
                      invoiceForm.direction === 'payable'
                        ? 'border-red-400 bg-red-50 dark:bg-red-950/20 shadow-sm'
                        : 'border-border hover:border-red-200 dark:hover:border-red-800 hover:bg-surface-secondary',
                    )}
                  >
                    <div className={clsx(
                      'flex h-10 w-10 items-center justify-center rounded-full',
                      invoiceForm.direction === 'payable'
                        ? 'bg-red-100 dark:bg-red-900/40 text-red-600 dark:text-red-400'
                        : 'bg-surface-secondary text-content-tertiary',
                    )}>
                      <ArrowUpRight size={20} />
                    </div>
                    <span className={clsx(
                      'text-sm font-semibold',
                      invoiceForm.direction === 'payable' ? 'text-red-700 dark:text-red-300' : 'text-content-secondary',
                    )}>
                      {t('finance.payable', { defaultValue: 'Payable' })}
                    </span>
                    <span className="text-2xs text-content-tertiary text-center leading-tight">
                      {t('finance.payable_desc', { defaultValue: 'Invoice you need to pay' })}
                    </span>
                  </button>
                  <button
                    type="button"
                    onClick={() => setInvoiceForm((f) => ({ ...f, direction: 'receivable' }))}
                    className={clsx(
                      'relative flex flex-col items-center gap-2 rounded-xl border-2 p-4 transition-all',
                      invoiceForm.direction === 'receivable'
                        ? 'border-emerald-400 bg-emerald-50 dark:bg-emerald-950/20 shadow-sm'
                        : 'border-border hover:border-emerald-200 dark:hover:border-emerald-800 hover:bg-surface-secondary',
                    )}
                  >
                    <div className={clsx(
                      'flex h-10 w-10 items-center justify-center rounded-full',
                      invoiceForm.direction === 'receivable'
                        ? 'bg-emerald-100 dark:bg-emerald-900/40 text-emerald-600 dark:text-emerald-400'
                        : 'bg-surface-secondary text-content-tertiary',
                    )}>
                      <ArrowDownLeft size={20} />
                    </div>
                    <span className={clsx(
                      'text-sm font-semibold',
                      invoiceForm.direction === 'receivable' ? 'text-emerald-700 dark:text-emerald-300' : 'text-content-secondary',
                    )}>
                      {t('finance.receivable', { defaultValue: 'Receivable' })}
                    </span>
                    <span className="text-2xs text-content-tertiary text-center leading-tight">
                      {t('finance.receivable_desc', { defaultValue: "Invoice you're sending" })}
                    </span>
                  </button>
                </div>
              </div>

              {/* ── Section: Invoice Details ── */}
              <div className="pt-1">
                <h3 className="text-xs font-semibold uppercase tracking-wider text-content-tertiary mb-3">
                  {t('finance.section_invoice_details', { defaultValue: 'Invoice Details' })}
                </h3>
                <div className="space-y-3">
                  {/* Contact picker (vendor/client) */}
                  <div>
                    <label className="block text-sm font-medium text-content-primary mb-1.5">
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
                    <label className="block text-sm font-medium text-content-primary mb-1.5">
                      {t('finance.issue_date', { defaultValue: 'Invoice Date' })} <span className="text-semantic-error">*</span>
                    </label>
                    <input
                      ref={invoiceDateRef}
                      type="date"
                      value={invoiceForm.invoice_date}
                      onChange={(e) => {
                        setInvoiceForm((f) => ({ ...f, invoice_date: e.target.value }));
                        if (invoiceErrors.invoice_date) setInvoiceErrors((prev) => { const next = { ...prev }; delete next.invoice_date; return next; });
                      }}
                      className={clsx(inputCls, invoiceErrors.invoice_date && 'border-semantic-error focus:ring-red-300 focus:border-semantic-error')}
                    />
                    {invoiceErrors.invoice_date && <p className="mt-1 text-xs text-semantic-error">{invoiceErrors.invoice_date}</p>}
                  </div>
                </div>
              </div>

              {/* ── Section: Amounts ── */}
              <div className="pt-1">
                <h3 className="text-xs font-semibold uppercase tracking-wider text-content-tertiary mb-3">
                  {t('finance.section_amounts', { defaultValue: 'Amounts' })}
                </h3>
                <div className="space-y-3">
                  {/* Currency */}
                  <div>
                    <label className="block text-sm font-medium text-content-primary mb-1.5">
                      {t('finance.currency', { defaultValue: 'Currency' })}
                    </label>
                    <select
                      value={invoiceForm.currency}
                      onChange={(e) => setInvoiceForm((f) => ({ ...f, currency: e.target.value }))}
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
                  {/* Subtotal */}
                  <div>
                    <label className="block text-sm font-medium text-content-primary mb-1.5">
                      {t('finance.subtotal', { defaultValue: 'Subtotal' })} <span className="text-semantic-error">*</span>
                    </label>
                    <div className="relative">
                      <span className="pointer-events-none absolute inset-y-0 left-0 flex items-center pl-3 text-xs text-content-tertiary font-medium">
                        {invoiceForm.currency}
                      </span>
                      <input
                        type="number"
                        step="0.01"
                        value={invoiceForm.subtotal}
                        onChange={(e) => {
                          const sub = e.target.value;
                          const tax = invoiceForm.tax || '0';
                          const total = (parseFloat(sub || '0') + parseFloat(tax)).toFixed(2);
                          setInvoiceForm((f) => ({ ...f, subtotal: sub, amount: total }));
                          if (invoiceErrors.subtotal) setInvoiceErrors((prev) => { const next = { ...prev }; delete next.subtotal; return next; });
                        }}
                        className={clsx(inputCls, 'pl-12', invoiceErrors.subtotal && 'border-semantic-error focus:ring-red-300 focus:border-semantic-error')}
                        placeholder="0.00"
                      />
                    </div>
                    {invoiceErrors.subtotal && <p className="mt-1 text-xs text-semantic-error">{invoiceErrors.subtotal}</p>}
                  </div>
                  {/* Tax */}
                  <div>
                    <label className="block text-sm font-medium text-content-primary mb-1.5">
                      {t('finance.tax', { defaultValue: 'Tax' })}
                    </label>
                    <div className="relative">
                      <span className="pointer-events-none absolute inset-y-0 left-0 flex items-center pl-3 text-xs text-content-tertiary font-medium">
                        {invoiceForm.currency}
                      </span>
                      <input
                        type="number"
                        step="0.01"
                        value={invoiceForm.tax}
                        onChange={(e) => {
                          const tax = e.target.value;
                          const sub = invoiceForm.subtotal || '0';
                          const total = (parseFloat(sub) + parseFloat(tax || '0')).toFixed(2);
                          setInvoiceForm((f) => ({ ...f, tax, amount: total }));
                        }}
                        className={clsx(inputCls, 'pl-12')}
                        placeholder="0.00"
                      />
                    </div>
                  </div>
                  {/* Total (auto-calculated, read-only) */}
                  <div className="rounded-lg bg-surface-secondary/60 px-4 py-3 flex items-center justify-between">
                    <span className="text-sm font-semibold text-content-primary">
                      {t('finance.total', { defaultValue: 'Total' })}
                    </span>
                    <span className="text-base font-bold tabular-nums text-content-primary">
                      {invoiceForm.currency} {(() => {
                        const sub = parseFloat(invoiceForm.subtotal || '0');
                        const tax = parseFloat(invoiceForm.tax || '0');
                        const total = (Number.isFinite(sub) ? sub : 0) + (Number.isFinite(tax) ? tax : 0);
                        return total.toFixed(2);
                      })()}
                    </span>
                  </div>
                </div>
              </div>

              {/* ── Section: Due Date ── */}
              <div className="pt-1">
                <h3 className="text-xs font-semibold uppercase tracking-wider text-content-tertiary mb-3">
                  {t('finance.section_due_date', { defaultValue: 'Due Date' })}
                </h3>
                <div>
                  <label className="block text-sm font-medium text-content-primary mb-1.5">
                    {t('finance.due_date', { defaultValue: 'Due Date' })}
                  </label>
                  <input
                    type="date"
                    value={invoiceForm.due_date}
                    onChange={(e) => setInvoiceForm((f) => ({ ...f, due_date: e.target.value }))}
                    className={inputCls}
                  />
                </div>
              </div>

              {/* Notes/Description */}
              <div>
                <label className="block text-sm font-medium text-content-primary mb-1.5">
                  {t('finance.notes', { defaultValue: 'Notes / Description' })}
                </label>
                <textarea
                  value={invoiceForm.description}
                  onChange={(e) => setInvoiceForm((f) => ({ ...f, description: e.target.value }))}
                  rows={3}
                  className={clsx(inputCls, 'h-auto py-2.5 resize-none')}
                  placeholder={t('finance.invoice_desc_placeholder', { defaultValue: 'e.g., Progress payment for concrete works - Phase 2' })}
                />
              </div>
            </div>
            <div className="flex items-center justify-end gap-3 px-6 py-4 border-t border-border-light">
              <Button variant="ghost" onClick={() => setShowCreate(false)} disabled={createInvoiceMut.isPending}>
                {t('common.cancel', { defaultValue: 'Cancel' })}
              </Button>
              <Button
                variant="primary"
                onClick={() => {
                  if (!validateInvoice()) return;
                  createInvoiceMut.mutate(invoiceForm);
                }}
                disabled={createInvoiceMut.isPending || !canSubmitInvoice}
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
      apiGet<Payment[]>(`/v1/finance/payments/?project_id=${projectId}`),
    select: (d): Payment[] => normalizeListResponse(d),
  });

  const paymentTotals = useMemo(() => {
    if (!payments || !payments.length) return null;
    const total = payments.reduce((s, p) => s + p.amount, 0);
    const currency = payments[0]?.currency ?? 'EUR';
    return { total, currency };
  }, [payments]);

  if (isLoading) return <SkeletonTable rows={5} columns={6} />;

  if (!payments || payments.length === 0) {
    return (
      <EmptyState
        icon={<CreditCard size={28} strokeWidth={1.5} />}
        title={t('finance.no_payments', { defaultValue: 'No payments yet' })}
        description={t('finance.no_payments_desc', {
          defaultValue:
            'Payments are recorded automatically when you mark invoices as paid. Go to the Invoices tab to approve and pay invoices.',
        })}
      />
    );
  }

  return (
    <Card padding="none">
      {/* Header bar */}
      <div className="p-4 border-b border-border-light flex items-center justify-between">
        <p className="text-sm text-content-secondary">
          {t('finance.payments_explanation', {
            defaultValue: 'Payment records are created when invoices are marked as paid.',
          })}
        </p>
      </div>
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
          {paymentTotals && (
            <tfoot>
              <tr className="bg-surface-secondary/60 font-semibold">
                <td className="px-4 py-3 text-content-primary" colSpan={2}>
                  {t('common.total', { defaultValue: 'Total' })}
                </td>
                <td className="px-4 py-3 text-right">
                  <MoneyDisplay amount={paymentTotals.total} currency={paymentTotals.currency} />
                </td>
                <td colSpan={3} />
              </tr>
            </tfoot>
          )}
        </table>
      </div>
    </Card>
  );
}

/* ── EVM Dashboard Tab ────────────────────────────────────────────────── */

function EVMTab({ projectId }: { projectId: string }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);

  const { data: evm, isLoading } = useQuery({
    queryKey: ['finance-evm', projectId],
    queryFn: () =>
      apiGet<EVMData>(`/v1/finance/evm/?project_id=${projectId}`),
  });

  const snapshotMut = useMutation({
    mutationFn: () =>
      apiPost('/v1/finance/evm/snapshot/', {
        project_id: projectId,
        snapshot_date: new Date().toISOString().split('T')[0],
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['finance-evm', projectId] });
      addToast({
        type: 'success',
        title: t('finance.snapshot_created', { defaultValue: 'EVM snapshot created successfully' }),
      });
    },
    onError: (e: Error) =>
      addToast({
        type: 'error',
        title: t('finance.snapshot_failed', { defaultValue: 'Failed to create EVM snapshot' }),
        message: e.message,
      }),
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
      <div className="space-y-4">
        <EmptyState
          icon={<BarChart3 size={28} strokeWidth={1.5} />}
          title={t('finance.no_evm', { defaultValue: 'No EVM data available' })}
          description={t('finance.no_evm_desc', {
            defaultValue:
              'Earned value data requires budget lines and a cost baseline. Create budget lines first, then click "Create Snapshot" to calculate EVM metrics.',
          })}
          action={{
            label: t('finance.create_snapshot', { defaultValue: 'Create Snapshot' }),
            onClick: () => snapshotMut.mutate(),
          }}
        />
      </div>
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
      {/* Header: Data date + Create Snapshot */}
      <div className="flex items-center justify-between">
        <div className="text-sm text-content-tertiary">
          {t('finance.data_date', { defaultValue: 'Data Date' })}:{' '}
          <DateDisplay value={evm.data_date} className="font-medium text-content-secondary" />
        </div>
        <Button
          variant="secondary"
          size="sm"
          icon={
            snapshotMut.isPending ? (
              <Loader2 size={14} className="animate-spin" />
            ) : (
              <Camera size={14} />
            )
          }
          onClick={() => snapshotMut.mutate()}
          disabled={snapshotMut.isPending}
        >
          {t('finance.create_snapshot', { defaultValue: 'Create Snapshot' })}
        </Button>
      </div>

      {/* KPI Cards */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-4">
        {kpiCards.map((kpi) => {
          let indicatorColor = '';
          if (kpi.isIndex) {
            indicatorColor =
              kpi.value >= 1.0 ? 'text-semantic-success' : 'text-semantic-error';
          } else if (kpi.isCurrency && kpi.label.includes('Variance')) {
            indicatorColor =
              kpi.value >= 0 ? 'text-semantic-success' : 'text-semantic-error';
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
                  (kpi.value ?? 0).toFixed(2)
                )}
              </div>
              {kpi.isIndex && (
                <div className="mt-1 flex items-center gap-1 text-xs">
                  {kpi.value >= 1.0 ? (
                    <ArrowUpRight size={12} className="text-semantic-success" />
                  ) : (
                    <ArrowDownRight size={12} className="text-semantic-error" />
                  )}
                  <span
                    className={
                      kpi.value >= 1.0 ? 'text-semantic-success' : 'text-semantic-error'
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
