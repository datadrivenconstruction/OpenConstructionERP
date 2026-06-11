import { useState, useMemo, useEffect, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { useParams, useNavigate, useSearchParams, Link } from 'react-router-dom';
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
  Pencil,
  Plug,
} from 'lucide-react';
import clsx from 'clsx';
import {
  Button,
  Card,
  Badge,
  EmptyState,
  Breadcrumb,
  DismissibleInfo,
  IntroRichText,
  RecoveryCard,
  SkeletonTable,
  ConfirmDialog,
  TabBar,
  tabIds,
} from '@/shared/ui';
import { PageHeader } from '@/shared/ui/PageHeader';
import { RequiresProject } from '@/shared/auth/RequiresProject';
import {
  WideModal,
  WideModalSection,
  WideModalField,
} from '@/shared/ui/WideModal';
import { useConfirm } from '@/shared/hooks/useConfirm';
import { MoneyDisplay } from '@/shared/ui/MoneyDisplay';
import { MultiCurrencyTotal } from '@/shared/ui/MultiCurrencyTotal';
import { DateDisplay } from '@/shared/ui/DateDisplay';
import { apiGet, apiPost, apiPatch, triggerDownload, extractErrorMessageFromBody } from '@/shared/lib/api';
import { ContactSearchInput } from '@/shared/ui/ContactSearchInput';
import { useToastStore } from '@/stores/useToastStore';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { useAuthStore } from '@/stores/useAuthStore';
import { ConnectorsTab } from './ConnectorsTab';

/* ── Types ─────────────────────────────────────────────────────────────── */

interface BudgetLine {
  id: string;
  project_id: string;
  wbs_id: string | null;
  wbs_code?: string;
  category: string;
  original_budget: number;
  revised_budget: number;
  committed: number;
  actual: number;
  forecast: number;
  forecast_final?: number;
  variance: number;
  currency_code?: string;
  currency?: string;
  metadata?: Record<string, unknown> | null;
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
  // Gap B link to a costmodel.CostLine (already serialized on
  // InvoiceLineItemResponse). When present the line can deep-link to the
  // 5D cost spine row it posts actuals onto.
  cost_line_id: string | null;
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
  // Gap E: the certified progress claim this receivable was raised from
  // (serialized on InvoiceResponse). When set the invoice deep-links back
  // to that claim. NULL on every non-claim invoice.
  source_claim_id?: string | null;
  line_items?: InvoiceLineItem[];
  // Raw wire fields from InvoiceResponse — the API uses these names
  // (invoice_date / currency_code / amount_total / amount_subtotal /
  // tax_amount / notes / contact_id) rather than the legacy display
  // aliases above. Used to prefill the edit form so it round-trips the
  // same fields the create form exposes.
  amount_subtotal?: string | null;
  tax_amount?: string | null;
  amount_total?: string | null;
  contact_id?: string | null;
  invoice_date?: string | null;
  currency_code?: string | null;
  notes?: string | null;
  created_at: string;
  updated_at: string;
}

// The API (InvoiceResponse) emits the canonical wire names —
// invoice_direction / invoice_date / currency_code / amount_total — rather
// than the legacy display aliases the table reads (direction / issue_date /
// currency / amount). The list/table columns and totals consume the display
// aliases, so normaliseInvoice MUST map every one of them, not just the
// counterparty name. Reading inv.amount / inv.currency / inv.issue_date off a
// raw wire row otherwise yields undefined (em-dash amount, blank date).
type InvoiceWire = Omit<
  Invoice,
  'counterparty_name' | 'direction' | 'issue_date' | 'amount' | 'currency'
> & {
  counterparty_name?: string | null;
  contact_id?: string | null;
  direction?: 'payable' | 'receivable';
  invoice_direction?: 'payable' | 'receivable';
  issue_date?: string | null;
  invoice_date?: string | null;
  amount?: number | string | null;
  amount_total?: string | null;
  currency?: string | null;
  currency_code?: string | null;
};

function normaliseInvoice(i: InvoiceWire): Invoice {
  const amountRaw = i.amount_total ?? i.amount;
  return {
    ...i,
    counterparty_name: i.counterparty_name ?? i.contact_id ?? '',
    direction: i.invoice_direction ?? i.direction ?? 'payable',
    issue_date: i.invoice_date ?? i.issue_date ?? '',
    amount: amountRaw != null ? Number(amountRaw) : 0,
    currency: i.currency_code ?? i.currency ?? '',
  } as Invoice;
}

interface Payment {
  id: string;
  invoice_id: string;
  // Enriched server-side from the parent invoice (PaymentResponse.invoice_number).
  invoice_number?: string | null;
  // Backend serialises Decimal as string ("250000.00") per Wave 8 sweep.
  // Accept both for back-compat with older fixtures.
  amount: string | number;
  // Backend field is `currency_code`; older payloads used `currency`.
  currency?: string;
  currency_code?: string;
  payment_date: string;
  reference?: string | null;
  // Derived lifecycle label from PaymentResponse: "completed" | "refunded".
  // (A payment is an immutable ledger entry, so it has no pending state.)
  status?: string;
  is_refund?: boolean;
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

type FinanceTab = 'budgets' | 'invoices' | 'payments' | 'evm' | 'connectors';
type InvoiceSubTab = 'payable' | 'receivable';

/** Common currency shortlist for the create/edit selects. NOT a default —
 *  the actual default always comes from project data (task #217). The
 *  project's resolved currency is merged in dynamically so a project priced
 *  in e.g. BRL/INR still has its own currency selectable. */
const COMMON_CURRENCIES = [
  // Construction-market headliners. BRL added 2026-05-27 in response to
  // a Brazilian user reporting "there is no invoice support for BRL" —
  // the picker still allowed entering BRL via the project-currency
  // injection below, but having it in the shortlist saves the click and
  // signals first-class support.
  'EUR', 'USD', 'GBP', 'CHF', 'BRL', 'PLN', 'CZK', 'SEK', 'NOK', 'DKK', 'AED', 'SAR',
] as const;

function currencyOptions(active: string): string[] {
  const a = (active || '').trim().toUpperCase();
  if (a && /^[A-Z]{3}$/.test(a) && !COMMON_CURRENCIES.includes(a as never)) {
    return [a, ...COMMON_CURRENCIES];
  }
  return [...COMMON_CURRENCIES];
}

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
    let detail = `Export failed (HTTP ${response.status})`;
    try {
      const body = await response.json();
      detail = extractErrorMessageFromBody(body) ?? detail;
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
    `/api/v1/finance/budgets/import/file/?project_id=${encodeURIComponent(projectId)}`,
    { method: 'POST', headers, body: formData },
  );

  if (!response.ok) {
    let detail = 'Import failed';
    try {
      const body = await response.json();
      detail = extractErrorMessageFromBody(body) ?? detail;
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

interface FinanceDashboardData {
  total_payable: number;
  total_receivable: number;
  total_overdue: number;
  overdue_count: number;
  invoices_draft: number;
  invoices_pending: number;
  invoices_approved: number;
  invoices_paid: number;
  total_budget_original: number;
  total_budget_revised: number;
  total_committed: number;
  total_actual: number;
  total_variance: number;
  budget_consumed_pct: number;
  budget_warning_level: string;
  total_payments: number;
  cash_flow_net: number;
  /** Base currency the totals are expressed in. For a project-scoped
   *  dashboard the server FX-converts every foreign record into this
   *  currency via Project.fx_rates; empty when no record carries one. */
  currency: string;
  /** True when financial records span more than one currency (totals are
   *  still in `currency`, converted where an FX rate exists). */
  mixed_currencies?: boolean;
  /** Foreign currency codes present but with no FX rate configured — their
   *  amounts are summed unconverted, so the total is approximate. */
  missing_fx_rates?: string[];
}

function FinanceSummaryCards({ projectId }: { projectId: string }) {
  const { t } = useTranslation();

  const { data: dashboard } = useQuery({
    queryKey: ['finance', 'dashboard', projectId],
    queryFn: () =>
      apiGet<FinanceDashboardData>(`/v1/finance/dashboard/?project_id=${projectId}`),
  });

  const totalBudget = Number(dashboard?.total_budget_original ?? 0);
  const totalRevised = Number(dashboard?.total_budget_revised ?? 0);
  const totalActual = Number(dashboard?.total_actual ?? 0);
  const totalInvoiced = Number(dashboard?.total_payable ?? 0);
  const totalReceivable = Number(dashboard?.total_receivable ?? 0);
  const remaining = (totalRevised || totalBudget) - totalActual;
  // Currency comes from the data (task #217) — never hardcoded. When the
  // backend cannot resolve one (no priced records yet) MoneyDisplay still
  // renders, falling back to the user's preferred currency for the symbol.
  //
  // The backend now FX-converts every foreign-currency record into the
  // project base currency (via Project.fx_rates, mirroring boq.service) and
  // returns the totals already expressed in `currency`, so the single-
  // currency cards below are correct. When records span more than one
  // currency it also returns `mixed_currencies` / `missing_fx_rates` so we
  // can surface an honest "converted / approximate" hint rather than passing
  // off a blended number as a native-currency sum.
  const currency = dashboard?.currency || undefined;
  const consumedPct = Number(dashboard?.budget_consumed_pct ?? 0);
  const warningLevel = dashboard?.budget_warning_level ?? 'normal';
  const mixedCurrencies = !!dashboard?.mixed_currencies;
  const missingFx = dashboard?.missing_fx_rates ?? [];

  if (
    !dashboard ||
    (totalBudget === 0 &&
      totalRevised === 0 &&
      totalInvoiced === 0 &&
      totalReceivable === 0)
  ) {
    return null;
  }

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

  const barColor =
    warningLevel === 'critical'
      ? 'bg-red-500'
      : warningLevel === 'caution'
        ? 'bg-amber-500'
        : 'bg-oe-blue';

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {cards.map((card) => (
          <div
            key={card.label}
            className="relative overflow-hidden rounded-xl border border-border-light bg-surface-elevated/90 shadow-xs transition-shadow duration-normal ease-oe hover:shadow-sm"
          >
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
          </div>
        ))}
      </div>

      {/* Mixed-currency honesty hint. When records span several currencies
          the totals above are FX-converted into the project currency; if a
          currency has no configured rate it was summed unconverted, so we
          flag the figure as approximate rather than presenting it as exact. */}
      {mixedCurrencies && (
        <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800 dark:border-amber-900/40 dark:bg-amber-950/30 dark:text-amber-300">
          {missingFx.length > 0
            ? t('finance.mixed_currency_missing_fx', {
                defaultValue:
                  'Totals are converted to {{currency}}. No FX rate is set for {{codes}}, so amounts in those currencies are added unconverted and the total is approximate.',
                currency: currency || '',
                codes: missingFx.join(', '),
              })
            : t('finance.mixed_currency_converted', {
                defaultValue:
                  'Records span multiple currencies; totals are converted to {{currency}} using the project exchange rates.',
                currency: currency || '',
              })}
        </div>
      )}

      {/* Budget consumption — makes the budget→actual money flow legible at
          a glance and surfaces the over-budget risk the cards only imply. */}
      {(totalRevised > 0 || totalBudget > 0) && (
        <Card padding="none" className="overflow-hidden">
          <div className="p-4">
            <div className="flex items-center justify-between mb-2 text-xs">
              <span className="font-medium text-content-secondary">
                {t('finance.budget_consumption', { defaultValue: 'Budget consumed' })}
              </span>
              <span className="tabular-nums font-semibold text-content-primary">
                {consumedPct.toFixed(1)}%
                {warningLevel !== 'normal' && (
                  <span
                    className={clsx(
                      'ml-2 rounded-full px-2 py-0.5 text-2xs font-medium',
                      warningLevel === 'critical'
                        ? 'bg-red-100 text-red-700 dark:bg-red-950/40 dark:text-red-300'
                        : 'bg-amber-100 text-amber-700 dark:bg-amber-950/40 dark:text-amber-300',
                    )}
                  >
                    {warningLevel === 'critical'
                      ? t('finance.budget_critical', { defaultValue: 'Over 95% - critical' })
                      : t('finance.budget_caution', { defaultValue: 'Over 80% - watch' })}
                  </span>
                )}
              </span>
            </div>
            <div className="h-2 w-full overflow-hidden rounded-full bg-surface-secondary">
              <div
                className={clsx('h-full rounded-full transition-all', barColor)}
                style={{ width: `${Math.min(100, Math.max(0, consumedPct))}%` }}
              />
            </div>
            <p className="mt-2 text-2xs text-content-tertiary">
              {t('finance.budget_consumption_hint', {
                defaultValue:
                  'Actual cost vs revised budget. Lock a BOQ to seed budget lines; invoices roll up into Actual when paid.',
              })}
            </p>
          </div>
        </Card>
      )}
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
  const navigate = useNavigate();
  const { projectId: routeProjectId } = useParams<{ projectId?: string }>();
  const activeProjectId = useProjectContextStore((s) => s.activeProjectId);
  const projectId = routeProjectId || activeProjectId || '';
  const projectName = useProjectContextStore((s) => s.activeProjectName);
  const [searchParams, setSearchParams] = useSearchParams();

  const [activeTab, setActiveTab] = useState<FinanceTab>('budgets');

  // Honour a ?tab= deep link once on mount so the Reporting Finance dashboard
  // (and any other caller) can drill straight into a specific Finance section.
  // The param is consumed and cleared with replace so a refresh / share keeps
  // the user wherever they navigated to next (CONN-74 consumer).
  const VALID_TABS: readonly FinanceTab[] = ['budgets', 'invoices', 'payments', 'evm', 'connectors'];
  useEffect(() => {
    const requested = searchParams.get('tab');
    if (requested && VALID_TABS.includes(requested as FinanceTab)) {
      setActiveTab(requested as FinanceTab);
      const next = new URLSearchParams(searchParams);
      next.delete('tab');
      setSearchParams(next, { replace: true });
    }
    // Run once on mount; the param is cleared immediately after it is read.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

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
    {
      key: 'connectors',
      label: t('finance.connectors.tab', { defaultValue: 'Connectors' }),
      icon: <Plug size={15} />,
    },
  ];

  return (
    <div className="space-y-5 animate-fade-in">
      <Breadcrumb
        items={[
          ...(projectName
            ? [{ label: projectName, to: `/projects/${projectId}` }]
            : []),
          { label: t('finance.title', { defaultValue: 'Finance' }) },
        ]}
      />

      {/* Header + Module Links */}
      <PageHeader
        srTitle={t('finance.title', { defaultValue: 'Finance' })}
        subtitle={t('finance.subtitle', {
          defaultValue:
            'Budgets, invoices, payments, and earned value management',
        })}
        actions={projectId ? <FinanceModuleLinks projectId={projectId} /> : undefined}
      />

      {/* Canonical module intro — pain-named, copy from MODULE_INTRO_COPY.
          Replaces the bespoke gradient "How it works" workflow guide. */}
      <DismissibleInfo
        storageKey="finance"
        title={t('finance.intro_title', {
          defaultValue: 'See where the money actually went',
        })}
        more={
          t('finance.intro_more', { defaultValue: '' })
            ? <IntroRichText text={t('finance.intro_more')} />
            : undefined
        }
        links={[
          { label: t('nav.boq', { defaultValue: 'BOQ' }), onClick: () => navigate('/boq') },
          { label: t('nav.5d', { defaultValue: '5D Cost Model' }), onClick: () => navigate('/5d') },
          {
            label: t('nav.procurement', { defaultValue: 'Procurement' }),
            onClick: () => navigate('/procurement'),
          },
        ]}
      >
        {t('finance.intro_body', {
          defaultValue:
            'Set budget lines against your WBS, then track invoices and payments as they land so committed, actual and forecast sit next to the original budget with the variance called out. The earned value dashboard turns that into cost and schedule performance, and budgets can pull straight from the BOQ estimate and 5D cost model.',
        })}
      </DismissibleInfo>

      {/* No-project case is handled by the RequiresProject empty state below;
          the single global project selector is the one source of truth, so
          there is no duplicate amber banner here (audit: finance-top). */}

      {/* Summary Cards */}
      {projectId && <FinanceSummaryCards projectId={projectId} />}

      {/* Tab Bar */}
      <TabBar<FinanceTab>
        ariaLabel={t('finance.tabs_aria', { defaultValue: 'Finance sections' })}
        idPrefix="finance"
        tabs={tabs.map((tab) => ({ id: tab.key, label: tab.label, icon: tab.icon }))}
        activeId={activeTab}
        onChange={setActiveTab}
      />

      {/* Tab Content */}
      <RequiresProject
        emptyHint={t('finance.select_project', {
          defaultValue:
            'Track invoices, budgets, and payments here. Select a project to view its financial data, or lock a BOQ to auto-generate budget lines.',
        })}
      >
        <div
          role="tabpanel"
          id={tabIds('finance').panelId(activeTab)}
          aria-labelledby={tabIds('finance').tabId(activeTab)}
        >
          {projectId && activeTab === 'budgets' && <BudgetsTab projectId={projectId} />}
          {projectId && activeTab === 'invoices' && <InvoicesTab projectId={projectId} />}
          {projectId && activeTab === 'payments' && (
            <PaymentsTab
              projectId={projectId}
              onGoToInvoices={() => setActiveTab('invoices')}
            />
          )}
          {projectId && activeTab === 'evm' && (
            <EVMTab
              projectId={projectId}
              onGoToBudgets={() => setActiveTab('budgets')}
            />
          )}
          {projectId && activeTab === 'connectors' && <ConnectorsTab projectId={projectId} />}
        </div>
      </RequiresProject>
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
  // When set, the budget modal is in edit mode for this existing line.
  const [editing, setEditing] = useState<BudgetLine | null>(null);
  const [budgetForm, setBudgetForm] = useState(INITIAL_BUDGET_FORM);
  const [budgetErrors, setBudgetErrors] = useState<Record<string, string>>({});
  const budgetFirstRef = useRef<HTMLInputElement>(null);
  const isEditingBudget = editing !== null;

  // Auto-focus budget WBS input when modal opens (create or edit)
  useEffect(() => {
    if ((showCreate || isEditingBudget) && budgetFirstRef.current) {
      setTimeout(() => budgetFirstRef.current?.focus(), 100);
    }
  }, [showCreate, isEditingBudget]);

  // Prefill the form when entering edit mode — mirrors every field the
  // create form exposes (WBS, category, original budget, notes).
  const openEditBudget = (b: BudgetLine) => {
    const notes =
      b.metadata && typeof b.metadata === 'object' && b.metadata !== null
        ? String((b.metadata as Record<string, unknown>).notes ?? '')
        : '';
    setBudgetForm({
      wbs_code: b.wbs_id ?? '',
      category: b.category ?? '',
      original_budget:
        b.original_budget != null ? String(b.original_budget) : '',
      notes,
    });
    setBudgetErrors({});
    setEditing(b);
  };

  const closeBudgetModal = () => {
    setShowCreate(false);
    setEditing(null);
    setBudgetForm(INITIAL_BUDGET_FORM);
    setBudgetErrors({});
  };

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
    if (!showCreate && !showImport && !isEditingBudget) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        if (showCreate || isEditingBudget) closeBudgetModal();
        if (showImport) setShowImport(false);
      }
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [showCreate, showImport, isEditingBudget]);

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
      // The summary cards (Total Budget / Remaining / consumed %) read the
      // dashboard query, so refresh it too - otherwise the top cards stay
      // stale after adding a budget line while the table below updates.
      queryClient.invalidateQueries({ queryKey: ['finance', 'dashboard', projectId] });
      setShowCreate(false);
      setBudgetForm(INITIAL_BUDGET_FORM);
      addToast({ type: 'success', title: t('finance.budget_created', { defaultValue: 'Budget line created successfully' }) });
    },
    onError: (e: Error) =>
      addToast({ type: 'error', title: t('finance.budget_create_failed', { defaultValue: 'Failed to create budget line' }), message: e.message }),
  });

  // PATCH /v1/finance/budgets/{id} — the only mutating endpoint the budget
  // API exposes for an existing line (there is no DELETE). Status is not a
  // budget concept here, so we only send the create-form fields back.
  const updateBudgetMut = useMutation({
    mutationFn: (data: {
      id: string;
      wbs_id: string | null;
      category: string | null;
      original_budget: string;
      notes: string | null;
      existingMetadata: Record<string, unknown> | null;
    }) =>
      apiPatch(`/v1/finance/budgets/${data.id}`, {
        wbs_id: data.wbs_id,
        category: data.category,
        original_budget: data.original_budget,
        metadata: {
          ...(data.existingMetadata ?? {}),
          ...(data.notes != null ? { notes: data.notes } : {}),
        },
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['finance-budgets', projectId] });
      queryClient.invalidateQueries({ queryKey: ['finance', 'dashboard', projectId] });
      closeBudgetModal();
      addToast({ type: 'success', title: t('finance.budget_updated', { defaultValue: 'Budget line updated successfully' }) });
    },
    onError: (e: Error) =>
      addToast({ type: 'error', title: t('finance.budget_update_failed', { defaultValue: 'Failed to update budget line' }), message: e.message }),
  });

  const exportBudgetsMut = useMutation({
    mutationFn: () =>
      fetchBlobWithAuth(
        `/api/v1/finance/budgets/export/?project_id=${encodeURIComponent(projectId)}`,
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

  const budgetMutPending = isEditingBudget
    ? updateBudgetMut.isPending
    : createBudgetMut.isPending;

  const submitBudget = () => {
    if (!validateBudget()) return;
    if (isEditingBudget && editing) {
      updateBudgetMut.mutate({
        id: editing.id,
        wbs_id: budgetForm.wbs_code || null,
        category: budgetForm.category,
        original_budget: budgetForm.original_budget,
        notes: budgetForm.notes || null,
        existingMetadata:
          editing.metadata && typeof editing.metadata === 'object'
            ? (editing.metadata as Record<string, unknown>)
            : null,
      });
    } else {
      createBudgetMut.mutate({
        wbs_id: budgetForm.wbs_code || null,
        category: budgetForm.category,
        original_budget: budgetForm.original_budget,
        notes: budgetForm.notes || null,
      });
    }
  };

  const renderBudgetModal = () => (
    <WideModal
      open
      onClose={closeBudgetModal}
      title={
        isEditingBudget
          ? t('finance.edit_budget', { defaultValue: 'Edit Budget Line' })
          : t('finance.new_budget', { defaultValue: 'New Budget Line' })
      }
      size="lg"
      busy={budgetMutPending}
      footer={
        <>
          <Button variant="ghost" onClick={closeBudgetModal} disabled={budgetMutPending}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button
            variant="primary"
            onClick={submitBudget}
            disabled={budgetMutPending || !canSubmitBudget}
          >
            {budgetMutPending ? (
              <Loader2 size={16} className="animate-spin mr-1.5" />
            ) : isEditingBudget ? (
              <Pencil size={16} className="mr-1.5" />
            ) : (
              <Plus size={16} className="mr-1.5" />
            )}
            <span>
              {isEditingBudget
                ? t('common.save', { defaultValue: 'Save Changes' })
                : t('common.create', { defaultValue: 'Create' })}
            </span>
          </Button>
        </>
      }
    >
      <WideModalSection columns={2}>
        {/* Category badge picker spans the full width so all 4-6 chips lay
            out horizontally rather than wrapping to multiple lines. */}
        <WideModalField
          label={t('finance.category', { defaultValue: 'Category' })}
          required
          error={budgetErrors.category}
          span={2}
        >
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
        </WideModalField>

        <WideModalField label={t('finance.wbs', { defaultValue: 'WBS Code' })}>
          <input
            ref={budgetFirstRef}
            value={budgetForm.wbs_code}
            onChange={(e) => setBudgetForm((p) => ({ ...p, wbs_code: e.target.value }))}
            className={inputCls}
            placeholder={t('finance.wbs_placeholder', { defaultValue: 'e.g., 01.02' })}
          />
        </WideModalField>

        <WideModalField
          label={t('finance.original', { defaultValue: 'Original Budget' })}
          required
          error={budgetErrors.original_budget}
        >
          <div className="relative">
            <span className="pointer-events-none absolute inset-y-0 left-0 flex items-center pl-3 text-xs text-content-tertiary font-medium">
              {budgets?.[0]?.currency_code ||
                budgets?.[0]?.currency ||
                t('finance.project_currency', { defaultValue: 'project currency' })}
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
        </WideModalField>

        <WideModalField
          label={t('finance.notes', { defaultValue: 'Notes' })}
          span={2}
        >
          <textarea
            value={budgetForm.notes}
            onChange={(e) => setBudgetForm((p) => ({ ...p, notes: e.target.value }))}
            rows={2}
            className={clsx(inputCls, 'h-auto py-2.5 resize-none')}
            placeholder={t('finance.budget_notes_placeholder', { defaultValue: 'e.g., Includes contingency for weather delays' })}
          />
        </WideModalField>
      </WideModalSection>
    </WideModal>
  );

  const budgetsQuery = useQuery({
    queryKey: ['finance-budgets', projectId],
    queryFn: () =>
      apiGet<BudgetLine[]>(
        `/v1/finance/budgets/?project_id=${projectId}`,
      ),
    select: (d): BudgetLine[] => normalizeListResponse(d),
  });
  const { data: budgets, isLoading, isError, error, refetch } = budgetsQuery;

  const filtered = useMemo(() => {
    if (!budgets) return [];
    if (!search) return budgets;
    const q = search.toLowerCase();
    return budgets.filter(
      (b) =>
        (b.wbs_id ?? '').toLowerCase().includes(q) ||
        b.category.toLowerCase().includes(q),
    );
  }, [budgets, search]);

  const totals = useMemo(() => {
    if (!filtered.length) return null;
    // Each budget line carries its own currency; summing rows into one
    // scalar and stamping the first row's code is financially meaningless
    // across mixed currencies. Build per-column {amount, currency} item
    // lists and let <MultiCurrencyTotal> group + render per ISO code
    // (degrading to a single MoneyDisplay when only one currency is used).
    const cur = (b: BudgetLine) => b.currency_code || b.currency || undefined;
    return {
      original: filtered.map((b) => ({ amount: Number(b.original_budget ?? 0), currency: cur(b) })),
      revised: filtered.map((b) => ({ amount: Number(b.revised_budget ?? 0), currency: cur(b) })),
      committed: filtered.map((b) => ({ amount: Number(b.committed ?? 0), currency: cur(b) })),
      actual: filtered.map((b) => ({ amount: Number(b.actual ?? 0), currency: cur(b) })),
      forecast: filtered.map((b) => ({ amount: Number(b.forecast_final ?? b.forecast ?? 0), currency: cur(b) })),
      variance: filtered.map((b) => ({ amount: Number(b.variance ?? 0), currency: cur(b) })),
    };
  }, [filtered]);

  if (isLoading) return <SkeletonTable rows={6} columns={8} />;

  if (isError) return <RecoveryCard error={error} onRetry={() => refetch()} />;

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
        {(showCreate || isEditingBudget) && renderBudgetModal()}
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

      {/* Desktop table */}
      <div className="hidden md:block overflow-x-auto">
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
              <th className="px-4 py-3 text-right font-medium text-content-tertiary">
                {t('common.actions', { defaultValue: 'Actions' })}
              </th>
            </tr>
          </thead>
          <tbody>
            {filtered.length === 0 ? (
              <tr>
                <td colSpan={9} className="px-4 py-8 text-center text-sm text-content-tertiary">
                  {t('finance.no_budget_match', { defaultValue: 'No matching budget lines' })}
                </td>
              </tr>
            ) : filtered.map((b) => {
              const rowCurrency = b.currency_code || b.currency || undefined;
              const forecastValue = b.forecast_final ?? b.forecast ?? 0;
              return (
                <tr
                  key={b.id}
                  className="border-b border-border-light hover:bg-surface-secondary/30 transition-colors"
                >
                  <td className="px-4 py-3 font-mono text-xs text-content-primary">
                    {b.wbs_id ?? b.wbs_code ?? ''}
                  </td>
                  <td className="px-4 py-3 text-content-secondary">{b.category}</td>
                  <td className="px-4 py-3 text-right">
                    <MoneyDisplay amount={b.original_budget} currency={rowCurrency} />
                  </td>
                  <td className="px-4 py-3 text-right">
                    <MoneyDisplay amount={b.revised_budget} currency={rowCurrency} />
                  </td>
                  <td className="px-4 py-3 text-right">
                    <MoneyDisplay amount={b.committed} currency={rowCurrency} />
                  </td>
                  <td className="px-4 py-3 text-right">
                    <MoneyDisplay amount={b.actual} currency={rowCurrency} />
                  </td>
                  <td className="px-4 py-3 text-right">
                    <MoneyDisplay amount={forecastValue} currency={rowCurrency} />
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
                        currency={rowCurrency}
                        colorize
                      />
                    </span>
                  </td>
                  <td className="px-4 py-3 text-right">
                    <button
                      type="button"
                      onClick={() => openEditBudget(b)}
                      title={t('finance.edit_budget', { defaultValue: 'Edit Budget Line' })}
                      aria-label={t('finance.edit_budget', { defaultValue: 'Edit Budget Line' })}
                      className="inline-flex h-7 w-7 items-center justify-center rounded-lg text-content-tertiary hover:bg-surface-secondary hover:text-oe-blue transition-colors"
                    >
                      <Pencil size={14} />
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
          {totals && (
            <tfoot>
              <tr className="bg-surface-secondary/60 font-semibold">
                <td className="px-4 py-3 text-content-primary" colSpan={2}>
                  {t('common.total')}
                </td>
                <td className="px-4 py-3 text-right">
                  <MultiCurrencyTotal items={totals.original} variant="inline" compact />
                </td>
                <td className="px-4 py-3 text-right">
                  <MultiCurrencyTotal items={totals.revised} variant="inline" compact />
                </td>
                <td className="px-4 py-3 text-right">
                  <MultiCurrencyTotal items={totals.committed} variant="inline" compact />
                </td>
                <td className="px-4 py-3 text-right">
                  <MultiCurrencyTotal items={totals.actual} variant="inline" compact />
                </td>
                <td className="px-4 py-3 text-right">
                  <MultiCurrencyTotal items={totals.forecast} variant="inline" compact />
                </td>
                <td className="px-4 py-3 text-right">
                  <MultiCurrencyTotal items={totals.variance} variant="inline" compact />
                </td>
                <td />
              </tr>
            </tfoot>
          )}
        </table>
      </div>

      {/* Mobile card view */}
      <div className="md:hidden p-4 space-y-3">
        {filtered.length === 0 ? (
          <p className="px-2 py-6 text-center text-sm text-content-tertiary">
            {t('finance.no_budget_match', { defaultValue: 'No matching budget lines' })}
          </p>
        ) : filtered.map((b) => {
          const rowCurrency = b.currency_code || b.currency || undefined;
          const forecastValue = b.forecast_final ?? b.forecast ?? 0;
          return (
            <Card key={b.id} className="p-4">
              <div className="flex items-start justify-between gap-2 mb-2">
                <div className="min-w-0">
                  <span className="text-xs font-mono text-content-tertiary">
                    {b.wbs_id ?? b.wbs_code ?? ''}
                  </span>
                  <h4 className="text-sm font-semibold text-content-primary truncate">
                    {b.category}
                  </h4>
                </div>
                <div className="flex items-center gap-2 shrink-0">
                  {rowCurrency && (
                    <span className="text-2xs font-medium text-content-tertiary">
                      {rowCurrency}
                    </span>
                  )}
                  <button
                    type="button"
                    onClick={() => openEditBudget(b)}
                    title={t('finance.edit_budget', { defaultValue: 'Edit Budget Line' })}
                    aria-label={t('finance.edit_budget', { defaultValue: 'Edit Budget Line' })}
                    className="inline-flex h-7 w-7 items-center justify-center rounded-lg text-content-tertiary hover:bg-surface-secondary hover:text-oe-blue transition-colors"
                  >
                    <Pencil size={14} />
                  </button>
                </div>
              </div>
              <div className="grid grid-cols-2 gap-x-3 gap-y-1.5 text-xs">
                <div className="flex justify-between">
                  <span className="text-content-tertiary">
                    {t('finance.original', { defaultValue: 'Original' })}
                  </span>
                  <MoneyDisplay amount={b.original_budget} currency={rowCurrency} />
                </div>
                <div className="flex justify-between">
                  <span className="text-content-tertiary">
                    {t('finance.committed', { defaultValue: 'Committed' })}
                  </span>
                  <MoneyDisplay amount={b.committed} currency={rowCurrency} />
                </div>
                <div className="flex justify-between">
                  <span className="text-content-tertiary">
                    {t('finance.actual', { defaultValue: 'Actual' })}
                  </span>
                  <MoneyDisplay amount={b.actual} currency={rowCurrency} />
                </div>
                <div className="flex justify-between">
                  <span className="text-content-tertiary">
                    {t('finance.forecast', { defaultValue: 'Forecast' })}
                  </span>
                  <MoneyDisplay amount={forecastValue} currency={rowCurrency} />
                </div>
                <div className="col-span-2 flex justify-between border-t border-border-light pt-1.5 mt-0.5">
                  <span className="text-content-secondary font-medium">
                    {t('finance.variance', { defaultValue: 'Variance' })}
                  </span>
                  <span
                    className={
                      b.variance >= 0
                        ? 'text-semantic-success font-medium'
                        : 'text-semantic-error font-medium'
                    }
                  >
                    <MoneyDisplay amount={b.variance} currency={rowCurrency} colorize />
                  </span>
                </div>
              </div>
            </Card>
          );
        })}
      </div>
    </Card>

    {/* New / Edit Budget Line Modal */}
    {(showCreate || isEditingBudget) && renderBudgetModal()}

    {/* Budget Import Modal */}
    {showImport && (
      <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-lg animate-fade-in">
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

  // Resolve the project's currency (budgets → invoices) so new invoices
  // default to it rather than a hardcoded EUR (task #217). Shares the
  // dashboard query key, so this is a cache hit alongside the summary cards.
  const { data: invDashboard } = useQuery({
    queryKey: ['finance', 'dashboard', projectId],
    queryFn: () =>
      apiGet<FinanceDashboardData>(`/v1/finance/dashboard/?project_id=${projectId}`),
  });
  const projectCurrency = invDashboard?.currency || '';

  const [invoiceForm, setInvoiceForm] = useState({
    direction: 'payable' as 'payable' | 'receivable',
    counterparty: '',
    contact_id: '',
    invoice_date: todayStr,
    due_date: '',
    subtotal: '',
    tax: '',
    amount: '',
    currency: '',
    description: '',
  });
  const [invoiceErrors, setInvoiceErrors] = useState<Record<string, string>>({});
  const invoiceDateRef = useRef<HTMLInputElement>(null);
  // When set, the invoice modal is in edit mode for this existing invoice.
  const [editingInvoice, setEditingInvoice] = useState<Invoice | null>(null);
  const isEditingInvoice = editingInvoice !== null;
  const invoiceModalOpen = showCreate || isEditingInvoice;

  // Prefill the form when entering edit mode — mirrors every field the
  // create form exposes (direction, counterparty, dates, amounts, notes).
  const openEditInvoice = (inv: Invoice) => {
    // The API serialises invoices with InvoiceResponse field names
    // (invoice_direction/invoice_date/currency_code/amount_*); fall back
    // to the legacy display aliases for safety.
    const wire = inv as unknown as { invoice_direction?: string };
    const direction: 'payable' | 'receivable' =
      wire.invoice_direction === 'receivable' || inv.direction === 'receivable'
        ? 'receivable'
        : 'payable';
    const subtotal = inv.amount_subtotal != null ? String(inv.amount_subtotal) : '';
    const tax = inv.tax_amount != null ? String(inv.tax_amount) : '';
    const total =
      inv.amount_total != null
        ? String(inv.amount_total)
        : inv.amount != null
          ? String(inv.amount)
          : '';
    const issueDate = (inv.invoice_date ?? inv.issue_date ?? '').split('T')[0] || '';
    const dueDate = (inv.due_date ?? '').split('T')[0] || '';
    setInvoiceForm({
      direction,
      counterparty: inv.counterparty_name ?? '',
      contact_id: inv.contact_id ?? '',
      invoice_date: issueDate,
      due_date: dueDate,
      subtotal,
      tax,
      amount: total,
      // Never hardcode EUR — fall back to the project's resolved currency so
      // an editor on a BRL/USD/etc. project keeps that currency (task #217).
      currency: inv.currency_code || inv.currency || projectCurrency || '',
      description: inv.notes ?? inv.description ?? '',
    });
    setInvoiceErrors({});
    setEditingInvoice(inv);
  };

  const closeInvoiceModal = () => {
    setShowCreate(false);
    setEditingInvoice(null);
    setInvoiceErrors({});
  };

  // Auto-focus invoice date when modal opens (create or edit)
  useEffect(() => {
    if (invoiceModalOpen && invoiceDateRef.current) {
      setTimeout(() => invoiceDateRef.current?.focus(), 100);
    }
  }, [invoiceModalOpen]);

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

  // Escape key handler for inline modal (create or edit)
  useEffect(() => {
    if (!invoiceModalOpen) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') closeInvoiceModal();
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [invoiceModalOpen]);

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
        // Send the chosen currency; empty string lets the backend
        // resolve the project currency (never hardcode EUR — task #217).
        currency_code: data.currency || projectCurrency || '',
        notes: data.description || undefined,
        status: 'draft',
      });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['finance-invoices', projectId] });
      queryClient.invalidateQueries({ queryKey: ['finance', 'dashboard', projectId] });
      setShowCreate(false);
      setInvoiceForm({ direction: 'payable', counterparty: '', contact_id: '', invoice_date: todayStr, due_date: '', subtotal: '', tax: '', amount: '', currency: projectCurrency, description: '' });
      addToast({ type: 'success', title: t('finance.invoice_created', { defaultValue: 'Invoice created successfully' }) });
    },
    onError: (e: Error) =>
      addToast({ type: 'error', title: t('finance.invoice_create_failed', { defaultValue: 'Failed to create invoice' }), message: e.message }),
  });

  // PATCH /v1/finance/{id} — the invoice API has no DELETE endpoint, so
  // editing is the only mutating control we expose on an existing row.
  // `status` is intentionally NOT sent: status transitions stay in the
  // Approve / Mark Paid workflow actions (the backend rejects illegal
  // status changes anyway).
  const updateInvoiceMut = useMutation({
    mutationFn: (data: { id: string; form: typeof invoiceForm }) => {
      const sub = parseFloat(data.form.subtotal || '0');
      const tax = parseFloat(data.form.tax || '0');
      const total = data.form.amount ? parseFloat(data.form.amount) : sub + tax;
      return apiPatch(`/v1/finance/${data.id}`, {
        contact_id: data.form.contact_id || null,
        invoice_direction: data.form.direction,
        invoice_date: data.form.invoice_date,
        due_date: data.form.due_date || null,
        amount_subtotal: String(sub),
        tax_amount: String(tax),
        amount_total: String(total),
        currency_code: data.form.currency || projectCurrency || '',
        notes: data.form.description || null,
      });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['finance-invoices', projectId] });
      queryClient.invalidateQueries({ queryKey: ['finance', 'dashboard', projectId] });
      closeInvoiceModal();
      addToast({ type: 'success', title: t('finance.invoice_updated', { defaultValue: 'Invoice updated successfully' }) });
    },
    onError: (e: Error) =>
      addToast({ type: 'error', title: t('finance.invoice_update_failed', { defaultValue: 'Failed to update invoice' }), message: e.message }),
  });

  const exportInvoicesMut = useMutation({
    mutationFn: () =>
      fetchBlobWithAuth(
        `/api/v1/finance/invoices/export/?project_id=${encodeURIComponent(projectId)}&direction=${subTab}`,
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

  const {
    data: invoices,
    isLoading,
    isError,
    error,
    refetch,
  } = useQuery({
    queryKey: ['finance-invoices', projectId, subTab],
    queryFn: () =>
      apiGet<InvoiceWire[]>(
        `/v1/finance/?project_id=${projectId}&direction=${subTab}`,
      ),
    select: (d): Invoice[] =>
      normalizeListResponse<InvoiceWire>(d).map(normaliseInvoice),
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
          (inv.invoice_number ?? '').toLowerCase().includes(q) ||
          (inv.counterparty_name ?? '').toLowerCase().includes(q),
      );
    }
    return result;
  }, [invoices, search, statusFilter]);

  const invoiceTotals = useMemo(() => {
    if (!filtered.length) return null;
    // Invoices can be in different currencies; summing them into one
    // scalar and stamping the first row's code blends currencies. Build
    // per-column {amount, currency} item lists for <MultiCurrencyTotal>,
    // which groups per ISO code (single MoneyDisplay when homogeneous).
    const totalAmount = filtered.map((inv) => ({
      amount: Number(inv.amount ?? 0),
      currency: inv.currency || projectCurrency || undefined,
    }));
    const totalPaid = filtered
      .filter((inv) => inv.status === 'paid')
      .map((inv) => ({
        amount: Number(inv.amount ?? 0),
        currency: inv.currency || projectCurrency || undefined,
      }));
    return { totalAmount, totalPaid };
  }, [filtered, projectCurrency]);

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
      {/* Explanation */}
      <p className="text-sm text-content-secondary">
        {t('finance.invoices_explanation', {
          defaultValue: 'Track all project invoices in one place. Payable = invoices from subcontractors/vendors. Receivable = invoices you send to clients. Mark invoices as paid to auto-generate payment records.',
        })}
      </p>

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
              setInvoiceForm({ direction: subTab, counterparty: '', contact_id: '', invoice_date: todayStr, due_date: '', subtotal: '', tax: '', amount: '', currency: projectCurrency, description: '' });
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
              <option value="cancelled">{t('finance.status_cancelled', { defaultValue: 'Cancelled' })}</option>
            </select>
            <div className="pointer-events-none absolute inset-y-0 right-0 flex items-center pr-2.5 text-content-tertiary">
              <ChevronDown size={14} />
            </div>
          </div>
        </div>

        {isLoading ? (
          <SkeletonTable rows={5} columns={6} />
        ) : isError ? (
          <RecoveryCard error={error} onRetry={() => refetch()} />
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
                        setInvoiceForm({ direction: subTab, counterparty: '', contact_id: '', invoice_date: todayStr, due_date: '', subtotal: '', tax: '', amount: '', currency: projectCurrency, description: '' });
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
                        {/* Gap E: a receivable raised from a certified progress
                            claim deep-links straight back to that claim, instead
                            of leaving the link as a dead figure (CONN-75). */}
                        {inv.source_claim_id && (
                          <Link
                            to={`/projects/${projectId}/contracts/claims/${inv.source_claim_id}`}
                            className="inline-flex items-center gap-0.5 text-2xs text-oe-blue hover:underline mt-0.5"
                            title={t('finance.view_source_claim', { defaultValue: 'View source progress claim' })}
                            onClick={(e) => e.stopPropagation()}
                          >
                            <ExternalLink size={10} />
                            <span>{t('finance.from_claim', { defaultValue: 'From claim' })}</span>
                          </Link>
                        )}
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
                        {/* Gap B: when a line item is linked to a 5D cost-spine
                            line, link to that cost model so the posted actual is
                            traceable to its budget row. The /5d consumer of
                            ?lineId lands separately (CONN-38). */}
                        {(() => {
                          const costLineId = inv.line_items?.find((li) => li.cost_line_id)?.cost_line_id;
                          if (!costLineId) return null;
                          return (
                            <Link
                              to={`/5d?lineId=${costLineId}`}
                              className="inline-flex items-center gap-0.5 text-2xs text-oe-blue hover:underline mt-0.5"
                              title={t('finance.view_cost_line', { defaultValue: 'View linked cost line in 5D' })}
                              onClick={(e) => e.stopPropagation()}
                            >
                              <ExternalLink size={10} />
                              <span>{t('finance.cost_line', { defaultValue: 'Cost line' })}</span>
                            </Link>
                          );
                        })()}
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
                          <button
                            type="button"
                            onClick={() => openEditInvoice(inv)}
                            title={t('finance.edit_invoice', { defaultValue: 'Edit Invoice' })}
                            aria-label={t('finance.edit_invoice', { defaultValue: 'Edit Invoice' })}
                            className="inline-flex h-7 w-7 items-center justify-center rounded-lg text-content-tertiary hover:bg-surface-secondary hover:text-oe-blue transition-colors"
                          >
                            <Pencil size={14} />
                          </button>
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
                        {t('common.total')}
                      </td>
                      <td className="px-4 py-3 text-right">
                        <MultiCurrencyTotal items={invoiceTotals.totalAmount} variant="inline" compact />
                      </td>
                      <td className="px-4 py-3 text-center text-xs text-content-tertiary">
                        {t('finance.total_paid', { defaultValue: 'Paid' })}:{' '}
                        <MultiCurrencyTotal items={invoiceTotals.totalPaid} variant="inline" compact />
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
                    <div className="flex items-center gap-2 shrink-0">
                      <Badge variant={INVOICE_STATUS_COLORS[inv.status] ?? 'neutral'} size="sm">
                        {t(`finance.status_${inv.status}`, { defaultValue: inv.status })}
                      </Badge>
                      <button
                        type="button"
                        onClick={() => openEditInvoice(inv)}
                        title={t('finance.edit_invoice', { defaultValue: 'Edit Invoice' })}
                        aria-label={t('finance.edit_invoice', { defaultValue: 'Edit Invoice' })}
                        className="inline-flex h-7 w-7 items-center justify-center rounded-lg text-content-tertiary hover:bg-surface-secondary hover:text-oe-blue transition-colors"
                      >
                        <Pencil size={14} />
                      </button>
                    </div>
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

      {/* New / Edit Invoice Modal — the edit form reuses this exact create
          form, prefilled via openEditInvoice(). */}
      {invoiceModalOpen && (
        <WideModal
          open
          onClose={closeInvoiceModal}
          title={
            isEditingInvoice
              ? t('finance.edit_invoice', { defaultValue: 'Edit Invoice' })
              : t('finance.new_invoice', { defaultValue: 'New Invoice' })
          }
          subtitle={
            isEditingInvoice
              ? editingInvoice?.invoice_number || undefined
              : invoiceProjectName
                ? t('common.creating_in_project', {
                    defaultValue: 'In {{project}}',
                    project: invoiceProjectName,
                  })
                : undefined
          }
          size="xl"
          busy={isEditingInvoice ? updateInvoiceMut.isPending : createInvoiceMut.isPending}
          footer={
            <>
              <Button
                variant="ghost"
                onClick={closeInvoiceModal}
                disabled={isEditingInvoice ? updateInvoiceMut.isPending : createInvoiceMut.isPending}
              >
                {t('common.cancel', { defaultValue: 'Cancel' })}
              </Button>
              <Button
                variant="primary"
                onClick={() => {
                  if (!validateInvoice()) return;
                  if (isEditingInvoice && editingInvoice) {
                    updateInvoiceMut.mutate({ id: editingInvoice.id, form: invoiceForm });
                  } else {
                    createInvoiceMut.mutate(invoiceForm);
                  }
                }}
                disabled={
                  (isEditingInvoice ? updateInvoiceMut.isPending : createInvoiceMut.isPending) ||
                  !canSubmitInvoice
                }
              >
                {(isEditingInvoice ? updateInvoiceMut.isPending : createInvoiceMut.isPending) ? (
                  <Loader2 size={16} className="animate-spin mr-1.5" />
                ) : isEditingInvoice ? (
                  <Pencil size={16} className="mr-1.5" />
                ) : (
                  <Plus size={16} className="mr-1.5" />
                )}
                <span>
                  {isEditingInvoice
                    ? t('common.save', { defaultValue: 'Save Changes' })
                    : t('common.create', { defaultValue: 'Create' })}
                </span>
              </Button>
            </>
          }
        >
          {/* Direction picker — full-width two-card visual selector. */}
          <WideModalSection columns={2}>
            <WideModalField
              label={t('finance.direction', { defaultValue: 'Direction' })}
              span={2}
            >
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
            </WideModalField>
          </WideModalSection>

          <WideModalSection
            title={t('finance.section_invoice_details', { defaultValue: 'Invoice Details' })}
            columns={2}
          >
            <WideModalField
              label={
                invoiceForm.direction === 'payable'
                  ? t('finance.vendor', { defaultValue: 'Vendor' })
                  : t('finance.client', { defaultValue: 'Client' })
              }
            >
              <ContactSearchInput
                value={invoiceForm.counterparty}
                onChange={(id, name) => setInvoiceForm((f) => ({ ...f, counterparty: name, contact_id: id }))}
                placeholder={
                  invoiceForm.direction === 'payable'
                    ? t('finance.search_vendor', { defaultValue: 'Search vendor...' })
                    : t('finance.search_client', { defaultValue: 'Search client...' })
                }
              />
            </WideModalField>
            <WideModalField
              label={t('finance.issue_date', { defaultValue: 'Invoice Date' })}
              required
              error={invoiceErrors.invoice_date}
            >
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
            </WideModalField>
          </WideModalSection>

          <WideModalSection
            title={t('finance.section_amounts', { defaultValue: 'Amounts' })}
            columns={3}
          >
            <WideModalField
              label={t('finance.currency', { defaultValue: 'Currency' })}
            >
              <select
                value={invoiceForm.currency}
                onChange={(e) => setInvoiceForm((f) => ({ ...f, currency: e.target.value }))}
                className={inputCls}
              >
                {!invoiceForm.currency && (
                  <option value="">
                    {t('finance.currency_from_project', {
                      defaultValue: 'Use project currency',
                    })}
                  </option>
                )}
                {currencyOptions(invoiceForm.currency).map((c) => (
                  <option key={c} value={c}>
                    {c}
                  </option>
                ))}
              </select>
            </WideModalField>
            <WideModalField
              label={t('finance.subtotal', { defaultValue: 'Subtotal' })}
              required
              error={invoiceErrors.subtotal}
            >
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
            </WideModalField>
            <WideModalField label={t('finance.tax', { defaultValue: 'Tax' })}>
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
            </WideModalField>
            <div className="sm:col-span-2 lg:col-span-3 rounded-lg bg-surface-secondary/60 px-4 py-3 flex items-center justify-between">
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
          </WideModalSection>

          <WideModalSection columns={2}>
            <WideModalField
              label={t('finance.due_date', { defaultValue: 'Due Date' })}
              span={2}
            >
              <input
                type="date"
                value={invoiceForm.due_date}
                onChange={(e) => setInvoiceForm((f) => ({ ...f, due_date: e.target.value }))}
                className={inputCls}
              />
            </WideModalField>
            <WideModalField
              label={t('finance.notes', { defaultValue: 'Notes / Description' })}
              span={2}
            >
              <textarea
                value={invoiceForm.description}
                onChange={(e) => setInvoiceForm((f) => ({ ...f, description: e.target.value }))}
                rows={3}
                className={clsx(inputCls, 'h-auto py-2.5 resize-none')}
                placeholder={t('finance.invoice_desc_placeholder', { defaultValue: 'e.g., Progress payment for concrete works - Phase 2' })}
              />
            </WideModalField>
          </WideModalSection>
        </WideModal>
      )}

      {/* Confirm Dialog */}
      <ConfirmDialog {...confirmProps} />
    </div>
  );
}

/* ── Payments Tab ─────────────────────────────────────────────────────── */

function PaymentsTab({
  projectId,
  onGoToInvoices,
}: {
  projectId: string;
  onGoToInvoices: () => void;
}) {
  const { t } = useTranslation();

  const {
    data: payments,
    isLoading,
    isError,
    error,
    refetch,
  } = useQuery({
    queryKey: ['finance-payments', projectId],
    queryFn: () =>
      apiGet<Payment[]>(`/v1/finance/payments/?project_id=${projectId}`),
    select: (d): Payment[] => normalizeListResponse(d),
  });

  const paymentTotals = useMemo(() => {
    if (!payments || !payments.length) return null;
    // Payments may be recorded in different currencies; summing into one
    // scalar and stamping the first row's code blends them. Map rows to
    // {amount, currency} for <MultiCurrencyTotal>, which groups per ISO
    // code (and degrades to a single MoneyDisplay when homogeneous).
    const total = payments.map((p) => ({
      amount: Number(p.amount ?? 0),
      currency: p.currency_code || p.currency || undefined,
    }));
    return { total };
  }, [payments]);

  if (isLoading) return <SkeletonTable rows={5} columns={5} />;

  if (isError) return <RecoveryCard error={error} onRetry={() => refetch()} />;

  if (!payments || payments.length === 0) {
    return (
      <EmptyState
        icon={<CreditCard size={28} strokeWidth={1.5} />}
        title={t('finance.no_payments', { defaultValue: 'No payments yet' })}
        description={t('finance.no_payments_desc', {
          defaultValue:
            'Payments are recorded automatically when you mark invoices as paid. Go to the Invoices tab to approve and pay invoices.',
        })}
        action={{
          label: t('finance.go_to_invoices', { defaultValue: 'Go to Invoices' }),
          onClick: onGoToInvoices,
        }}
      />
    );
  }

  return (
    <Card padding="none">
      {/* Header bar */}
      <div className="p-4 border-b border-border-light flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <p className="text-sm text-content-secondary">
          {t('finance.payments_explanation', {
            defaultValue:
              'Payments are read-only ledger entries created automatically when an invoice is marked as paid in the Invoices tab. To record a new payment, approve and pay its invoice.',
          })}
        </p>
        <Button
          variant="secondary"
          size="sm"
          icon={<FileText size={14} />}
          onClick={onGoToInvoices}
          className="shrink-0"
        >
          {t('finance.go_to_invoices', { defaultValue: 'Go to Invoices' })}
        </Button>
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
                  {p.invoice_number || '\u2014'}
                </td>
                <td className="px-4 py-3 text-content-secondary">
                  <DateDisplay value={p.payment_date} />
                </td>
                <td className="px-4 py-3 text-right">
                  <MoneyDisplay amount={p.amount} currency={p.currency_code || p.currency} />
                </td>
                <td className="px-4 py-3 text-content-secondary font-mono text-xs">
                  {p.reference || '\u2014'}
                </td>
                <td className="px-4 py-3 text-center">
                  {(() => {
                    // PaymentResponse derives status server-side: "completed"
                    // for a forward payment, "refunded" for a refund. Fall
                    // back to the is_refund flag for older payloads.
                    const status = p.status || (p.is_refund ? 'refunded' : 'completed');
                    return (
                      <Badge variant={status === 'refunded' ? 'warning' : 'success'} size="sm">
                        {t(`finance.payment_status_${status}`, { defaultValue: status })}
                      </Badge>
                    );
                  })()}
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
                  <MultiCurrencyTotal items={paymentTotals.total} variant="inline" compact />
                </td>
                <td colSpan={2} />
              </tr>
            </tfoot>
          )}
        </table>
      </div>
    </Card>
  );
}

/* ── EVM Dashboard Tab ────────────────────────────────────────────────── */

function EVMTab({
  projectId,
  onGoToBudgets,
}: {
  projectId: string;
  onGoToBudgets: () => void;
}) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);

  // Resolve the project currency from the finance dashboard so EVM money
  // KPIs are never mislabelled as EUR (task #217). Shares the same query
  // key as the summary cards, so this is a cache hit in practice.
  const { data: dashboard } = useQuery({
    queryKey: ['finance', 'dashboard', projectId],
    queryFn: () =>
      apiGet<FinanceDashboardData>(`/v1/finance/dashboard/?project_id=${projectId}`),
  });
  const evmCurrency = dashboard?.currency || undefined;

  // Backend returns EVMListResponse `{items: EVMSnapshot[], total: int}`
  // sorted by snapshot_date DESC — the most-recent snapshot is items[0].
  // EVM money/index fields ship as Decimal-as-string; coerce to numbers
  // for the KPI cards. Empty list → show the "No EVM data" empty state.
  const {
    data: evm,
    isLoading,
    isError,
    error,
    refetch,
  } = useQuery({
    queryKey: ['finance-evm', projectId],
    queryFn: () =>
      apiGet<{
        items: Array<{
          bac: string; pv: string; ev: string; ac: string; sv: string;
          cv: string; spi: string; cpi: string; eac: string; etc: string;
          vac: string; tcpi: string; snapshot_date: string;
        }>;
        total: number;
      }>(`/v1/finance/evm/?project_id=${projectId}`),
    select: (resp): EVMData | null => {
      const latest = resp?.items?.[0];
      if (!latest) return null;
      const num = (s: string | undefined): number => {
        const n = Number.parseFloat(s ?? '0');
        return Number.isFinite(n) ? n : 0;
      };
      return {
        project_id: projectId,
        bac: num(latest.bac), pv: num(latest.pv), ev: num(latest.ev),
        ac: num(latest.ac), sv: num(latest.sv), cv: num(latest.cv),
        spi: num(latest.spi), cpi: num(latest.cpi), eac: num(latest.eac),
        etc: num(latest.etc), vac: num(latest.vac), tcpi: num(latest.tcpi),
        // Resolved from the dashboard below — kept empty here so the
        // currency is never hardcoded in the data layer (task #217).
        currency: '',
        data_date: latest.snapshot_date,
      };
    },
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

  if (isError) return <RecoveryCard error={error} onRetry={() => refetch()} />;

  if (!evm) {
    const hasBudget =
      (dashboard?.total_budget_revised ?? 0) > 0 ||
      (dashboard?.total_budget_original ?? 0) > 0;
    return (
      <div className="space-y-4">
        <EmptyState
          icon={<BarChart3 size={28} strokeWidth={1.5} />}
          title={t('finance.no_evm', { defaultValue: 'No EVM data available' })}
          description={
            hasBudget
              ? t('finance.no_evm_desc', {
                  defaultValue:
                    'Earned value data requires a cost baseline. Click "Create Snapshot" to compute BAC, SPI, CPI and the forecast metrics from your current budget and paid invoices.',
                })
              : t('finance.no_evm_no_budget_desc', {
                  defaultValue:
                    'EVM is computed from your project budget and paid invoices. Add budget lines first - then create a snapshot to track schedule and cost performance.',
                })
          }
          action={
            hasBudget
              ? {
                  label: t('finance.create_snapshot', { defaultValue: 'Create Snapshot' }),
                  onClick: () => snapshotMut.mutate(),
                }
              : {
                  label: t('finance.go_to_budgets', { defaultValue: 'Go to Budgets' }),
                  onClick: onGoToBudgets,
                }
          }
        />
      </div>
    );
  }

  const kpiCards: {
    label: string;
    value: number;
    isCurrency: boolean;
    isIndex?: boolean;
    /** Variance metrics colorize good=positive / bad=negative. The label
     *  text is translated, so we must NOT match on it (was a bug: German
     *  "Abweichung" never matched "Variance"). */
    isVariance?: boolean;
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
      isVariance: true,
    },
    {
      label: t('finance.evm_cv', { defaultValue: 'CV (Cost Variance)' }),
      value: evm.cv,
      isCurrency: true,
      isVariance: true,
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
      isVariance: true,
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
      {/* Explanation */}
      <div className="rounded-lg border border-oe-blue/15 bg-oe-blue/[0.03] p-3">
        <p className="text-sm text-content-secondary">
          {t('finance.evm_explanation', {
            defaultValue: 'Earned Value Management (EVM) compares planned progress with actual performance. SPI > 1.0 = ahead of schedule. CPI > 1.0 = under budget. Create snapshots periodically to track trends over time.',
          })}
        </p>
        <div className="mt-2 flex flex-wrap gap-3 text-2xs text-content-tertiary">
          <span><strong className="text-content-secondary">SPI</strong> = EV / PV ({t('finance.evm_hint_schedule', { defaultValue: 'schedule efficiency' })})</span>
          <span><strong className="text-content-secondary">CPI</strong> = EV / AC ({t('finance.evm_hint_cost', { defaultValue: 'cost efficiency' })})</span>
          <span><strong className="text-content-secondary">EAC</strong> = AC + (BAC − EV) / CPI ({t('finance.evm_hint_forecast', { defaultValue: 'forecast total cost' })})</span>
        </div>
      </div>

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
            // TCPI is "good" when LOW (≤1 means the remaining work is
            // achievable at or under the planned rate); all other indices
            // are good when ≥1.
            const onTrack =
              kpi.good === 'low' ? kpi.value <= 1.0 : kpi.value >= 1.0;
            indicatorColor = onTrack
              ? 'text-semantic-success'
              : 'text-semantic-error';
          } else if (kpi.isCurrency && kpi.isVariance) {
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
                    currency={evmCurrency}
                    compact
                    colorize={kpi.isVariance}
                  />
                ) : (
                  (kpi.value ?? 0).toFixed(2)
                )}
              </div>
              {kpi.isIndex && (() => {
                const onTrack =
                  kpi.good === 'low' ? kpi.value <= 1.0 : kpi.value >= 1.0;
                return (
                  <div className="mt-1 flex items-center gap-1 text-xs">
                    {onTrack ? (
                      <ArrowUpRight size={12} className="text-semantic-success" />
                    ) : (
                      <ArrowDownRight size={12} className="text-semantic-error" />
                    )}
                    <span
                      className={
                        onTrack ? 'text-semantic-success' : 'text-semantic-error'
                      }
                    >
                      {onTrack
                        ? t('finance.on_track', { defaultValue: 'On track' })
                        : t('finance.behind', { defaultValue: 'Behind' })}
                    </span>
                  </div>
                );
              })()}
            </Card>
          );
        })}
      </div>
    </div>
  );
}
