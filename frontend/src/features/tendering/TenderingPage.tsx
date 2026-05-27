import { useState, useMemo, useCallback, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  Package,
  Plus,
  ChevronDown,
  ChevronRight,
  Send,
  Award,
  BarChart3,
  Clock,
  Mail,
  Building2,
  ArrowUpRight,
  ArrowDownRight,
  Minus,
  Download,
  FileText,
  AlertTriangle,
} from 'lucide-react';
import { Button, Card, Badge, EmptyState, RecoveryCard, Skeleton, InfoHint, SkeletonTable, Breadcrumb, ConfirmDialog } from '@/shared/ui';
import { RequiresProject } from '@/shared/auth/RequiresProject';
import {
  WideModal,
  WideModalSection,
  WideModalField,
} from '@/shared/ui/WideModal';
import { useConfirm } from '@/shared/hooks/useConfirm';
import { apiGet, apiPost, apiPatch, getAuthToken, triggerDownload } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { BidComparisonChart } from './BidComparisonChart';
import { AddendumList } from './AddendumList';
import { LevelingMatrix } from './LevelingMatrix';
import { classifyCell, recommend } from './analysis';
import { getIntlLocale } from '@/shared/lib/formatters';

/* ── Types ─────────────────────────────────────────────────────────────── */

interface Project {
  id: string;
  name: string;
  description: string;
  currency: string;
}

interface BOQ {
  id: string;
  project_id: string;
  name: string;
  description: string;
  status: string;
}

interface BidData {
  id: string;
  package_id: string;
  company_name: string;
  contact_email: string;
  total_amount: string;
  currency: string;
  submitted_at: string | null;
  status: string;
  notes: string;
  line_items: LineItem[];
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

interface LineItem {
  position_id?: string;
  description: string;
  unit: string;
  quantity: number;
  unit_rate: number;
  total: number;
}

interface TenderPackage {
  id: string;
  project_id: string;
  boq_id: string;
  name: string;
  description: string;
  status: string;
  deadline: string | null;
  metadata: Record<string, unknown>;
  bid_count: number;
  created_at: string;
  updated_at: string;
}

interface PackageWithBids extends TenderPackage {
  bids: BidData[];
}

interface BidComparisonRow {
  position_id: string | null;
  description: string;
  unit: string;
  budget_quantity: number;
  budget_rate: number;
  budget_total: number;
  bids: {
    company_name: string;
    bid_id: string;
    unit_rate: number;
    total: number;
    deviation_pct: number;
  }[];
}

interface BidComparison {
  package_id: string;
  package_name: string;
  bid_count: number;
  bid_companies: string[];
  budget_total: number;
  rows: BidComparisonRow[];
  bid_totals: {
    bid_id: string;
    company_name: string;
    total: number;
    currency: string;
    deviation_pct: number;
    status: string;
  }[];
}

/* ── Helpers ───────────────────────────────────────────────────────────── */

const STATUS_COLORS: Record<string, 'neutral' | 'blue' | 'success' | 'warning' | 'error'> = {
  draft: 'neutral',
  issued: 'blue',
  collecting: 'blue',
  evaluating: 'warning',
  awarded: 'success',
  closed: 'neutral',
  pending: 'neutral',
  submitted: 'blue',
  accepted: 'success',
  rejected: 'error',
};

function formatCurrency(amount: number | string, currency?: string): string {
  const num = typeof amount === 'string' ? parseFloat(amount) || 0 : amount;
  const code = (currency || '').trim().toUpperCase();
  // NEVER hard-fallback to EUR (task #217): a project priced in BRL/INR
  // must not render its tender amounts with a Euro sign. When the currency
  // is unknown, show a plain decimal number with no symbol.
  if (!/^[A-Z]{3}$/.test(code)) {
    return new Intl.NumberFormat(getIntlLocale(), {
      minimumFractionDigits: 0,
      maximumFractionDigits: 0,
    }).format(num);
  }
  try {
    return new Intl.NumberFormat(getIntlLocale(), {
      style: 'currency',
      currency: code,
      minimumFractionDigits: 0,
      maximumFractionDigits: 0,
    }).format(num);
  } catch {
    return `${num.toFixed(0)} ${code}`;
  }
}

function formatNumber(n: number, decimals: number = 2): string {
  return new Intl.NumberFormat(getIntlLocale(), {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  }).format(n);
}

function DeviationBadge({ pct }: { pct: number }) {
  if (Math.abs(pct) < 0.1) {
    return (
      <span className="inline-flex items-center gap-0.5 text-xs text-content-tertiary">
        <Minus size={10} /> 0%
      </span>
    );
  }
  if (pct < 0) {
    return (
      <span className="inline-flex items-center gap-0.5 text-xs font-medium text-semantic-success">
        <ArrowDownRight size={12} /> {pct.toFixed(1)}%
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-0.5 text-xs font-medium text-semantic-error">
      <ArrowUpRight size={12} /> +{pct.toFixed(1)}%
    </span>
  );
}

function translateStatus(status: string, t: ReturnType<typeof useTranslation>['t']): string {
  const STATUS_I18N: Record<string, string> = {
    draft: t('tendering.status_draft', 'Draft'),
    issued: t('tendering.status_issued', 'Issued'),
    collecting: t('tendering.status_collecting', 'Collecting'),
    evaluating: t('tendering.status_evaluating', 'Evaluating'),
    awarded: t('tendering.status_awarded', 'Awarded'),
    closed: t('tendering.status_closed', 'Closed'),
    pending: t('tendering.status_pending', 'Pending'),
    submitted: t('tendering.status_submitted', 'Submitted'),
    accepted: t('tendering.status_accepted', 'Accepted'),
    rejected: t('tendering.status_rejected', 'Rejected'),
  };
  return STATUS_I18N[status] || status;
}

function formatDate(dateStr: string): string {
  try {
    return new Intl.DateTimeFormat(getIntlLocale(), { dateStyle: 'medium' }).format(new Date(dateStr));
  } catch {
    return dateStr;
  }
}

/* ── Select Dropdown ──────────────────────────────────────────────────── */

function SelectDropdown({
  value,
  onChange,
  options,
  placeholder,
}: {
  value: string;
  onChange: (value: string) => void;
  options: { value: string; label: string }[];
  placeholder: string;
}) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className={`h-10 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm transition-all duration-normal ease-oe focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue hover:border-content-tertiary ${
        !value ? 'text-content-tertiary' : 'text-content-primary'
      }`}
    >
      <option value="">{placeholder}</option>
      {options.map((opt) => (
        <option key={opt.value} value={opt.value}>
          {opt.label}
        </option>
      ))}
    </select>
  );
}

/* ── Create Package Dialog ────────────────────────────────────────────── */

function CreatePackageDialog({
  projectId,
  boqs,
  onClose,
  onCreated,
}: {
  projectId: string;
  boqs: BOQ[];
  onClose: () => void;
  onCreated: () => void;
}) {
  const { t } = useTranslation();
  const [name, setName] = useState('');
  const [boqId, setBoqId] = useState('');
  const [description, setDescription] = useState('');
  const [deadline, setDeadline] = useState('');

  const addToast = useToastStore((s) => s.addToast);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [onClose]);

  const createMutation = useMutation({
    mutationFn: () =>
      apiPost<TenderPackage>('/v1/tendering/packages/', {
        project_id: projectId,
        boq_id: boqId,
        name,
        description,
        deadline: deadline || null,
      }),
    onSuccess: () => {
      onCreated();
      onClose();
      addToast({ type: 'success', title: t('toasts.package_created', { defaultValue: 'Tender package created' }) });
    },
    onError: (error: Error) => {
      addToast({ type: 'error', title: t('toasts.error', { defaultValue: 'Error' }), message: error.message });
    },
  });

  const fieldCls =
    'h-10 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm text-content-primary placeholder:text-content-tertiary transition-all focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';

  return (
    <WideModal
      open
      onClose={onClose}
      title={t('tendering.new_package', 'New Tender Package')}
      size="lg"
      busy={createMutation.isPending}
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={createMutation.isPending}>
            {t('common.cancel', 'Cancel')}
          </Button>
          <Button
            variant="primary"
            disabled={!name.trim() || !boqId}
            loading={createMutation.isPending}
            onClick={() => createMutation.mutate()}
          >
            {t('tendering.create_package', 'Create Package')}
          </Button>
        </>
      }
    >
      <WideModalSection columns={2}>
        <WideModalField
          label={t('tendering.package_name', 'Package Name')}
          required
          span={2}
        >
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder={t('tendering.package_name_placeholder', 'e.g. Concrete Works Package')}
            className={fieldCls}
          />
        </WideModalField>
        <WideModalField label={t('tendering.source_boq', 'Source BOQ')} required>
          <SelectDropdown
            value={boqId}
            onChange={setBoqId}
            options={boqs.map((b) => ({ value: b.id, label: b.name }))}
            placeholder={t('tendering.select_boq', 'Select a BOQ...')}
          />
        </WideModalField>
        <WideModalField label={t('tendering.deadline', 'Deadline')}>
          <input
            type="date"
            value={deadline}
            onChange={(e) => setDeadline(e.target.value)}
            className={fieldCls}
          />
        </WideModalField>
        <WideModalField
          label={t('tendering.description', 'Description')}
          span={2}
        >
          <textarea
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            rows={3}
            className="w-full rounded-lg border border-border bg-surface-primary px-3 py-2 text-sm text-content-primary placeholder:text-content-tertiary transition-all focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue resize-none"
            placeholder={t('tendering.description_placeholder', 'Brief description of the package scope...')}
          />
        </WideModalField>
      </WideModalSection>
    </WideModal>
  );
}

/* ── Add Bid Dialog ───────────────────────────────────────────────────── */

function AddBidDialog({
  packageId,
  currency,
  onClose,
  onCreated,
}: {
  packageId: string;
  currency: string;
  onClose: () => void;
  onCreated: () => void;
}) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const [companyName, setCompanyName] = useState('');
  const [contactEmail, setContactEmail] = useState('');
  const [totalAmount, setTotalAmount] = useState('');
  const [notes, setNotes] = useState('');

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [onClose]);

  const createMutation = useMutation({
    mutationFn: () =>
      apiPost<BidData>(`/v1/tendering/packages/${packageId}/bids/`, {
        company_name: companyName,
        contact_email: contactEmail,
        total_amount: totalAmount || '0',
        currency,
        submitted_at: new Date().toISOString().slice(0, 10),
        status: 'submitted',
        notes,
      }),
    onSuccess: () => {
      onCreated();
      onClose();
      addToast({ type: 'success', title: t('toasts.bid_submitted', { defaultValue: 'Bid submitted' }) });
    },
    onError: (error: Error) => {
      addToast({ type: 'error', title: t('toasts.error', { defaultValue: 'Error' }), message: error.message });
    },
  });

  const fieldCls =
    'h-10 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm text-content-primary placeholder:text-content-tertiary transition-all focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';

  return (
    <WideModal
      open
      onClose={onClose}
      title={t('tendering.add_bid', 'Add Bid')}
      size="lg"
      busy={createMutation.isPending}
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={createMutation.isPending}>
            {t('common.cancel', 'Cancel')}
          </Button>
          <Button
            variant="primary"
            disabled={!companyName.trim()}
            loading={createMutation.isPending}
            onClick={() => createMutation.mutate()}
          >
            {t('tendering.submit_bid', 'Submit Bid')}
          </Button>
        </>
      }
    >
      <WideModalSection columns={2}>
        <WideModalField
          label={t('tendering.company_name', 'Company Name')}
          required
          span={2}
        >
          <input
            type="text"
            value={companyName}
            onChange={(e) => setCompanyName(e.target.value)}
            placeholder={t('tendering.company_placeholder', 'e.g. Schmidt Bau GmbH')}
            className={fieldCls}
          />
        </WideModalField>
        <WideModalField label={t('tendering.contact_email', 'Contact Email')}>
          <input
            type="email"
            value={contactEmail}
            onChange={(e) => setContactEmail(e.target.value)}
            placeholder="contact@example.com"
            className={fieldCls}
          />
        </WideModalField>
        <WideModalField
          label={
            currency
              ? `${t('tendering.total_amount', 'Total Amount')} (${currency})`
              : t('tendering.total_amount', 'Total Amount')
          }
        >
          <input
            type="number"
            value={totalAmount}
            onChange={(e) => setTotalAmount(e.target.value)}
            placeholder="0"
            className={fieldCls}
          />
        </WideModalField>
        <WideModalField label={t('tendering.notes', 'Notes')} span={2}>
          <textarea
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            rows={2}
            className="w-full rounded-lg border border-border bg-surface-primary px-3 py-2 text-sm text-content-primary placeholder:text-content-tertiary transition-all focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue resize-none"
            placeholder={t('tendering.notes_placeholder', 'Optional notes...')}
          />
        </WideModalField>
      </WideModalSection>
    </WideModal>
  );
}

/* ── Package Card ─────────────────────────────────────────────────────── */

function PackageCard({
  pkg,
  isSelected,
  onClick,
}: {
  pkg: TenderPackage;
  isSelected: boolean;
  onClick: () => void;
}) {
  const { t } = useTranslation();

  return (
    <Card
      hoverable
      padding="none"
      className={`cursor-pointer transition-all ${
        isSelected ? 'ring-2 ring-oe-blue/40 border-oe-blue/40' : ''
      }`}
      onClick={onClick}
    >
      <div className="flex items-center gap-3 px-5 py-4">
        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-oe-blue-subtle text-oe-blue-text">
          <Package size={18} />
        </div>
        <div className="min-w-0 flex-1">
          <h3 className="text-sm font-semibold text-content-primary truncate">
            {pkg.name}
          </h3>
          <div className="mt-0.5 flex items-center gap-3 text-xs text-content-secondary">
            <span className="flex items-center gap-1">
              <FileText size={12} />
              {t('tendering.bid_count', { defaultValue: '{{count}} bids', count: pkg.bid_count })}
            </span>
            {pkg.deadline && (
              <span className="flex items-center gap-1">
                <Clock size={12} />
                {formatDate(pkg.deadline)}
              </span>
            )}
          </div>
        </div>
        <Badge variant={STATUS_COLORS[pkg.status] || 'neutral'} size="sm">
          {translateStatus(pkg.status, t)}
        </Badge>
        <span className="text-content-tertiary">
          {isSelected ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
        </span>
      </div>
    </Card>
  );
}

/* ── Bid Comparison Table ─────────────────────────────────────────────── */

function BidComparisonTable({
  comparison,
  currency,
}: {
  comparison: BidComparison;
  currency: string;
}) {
  const { t } = useTranslation();
  const [hideLowVariance, setHideLowVariance] = useState(false);
  const [varianceThreshold, setVarianceThreshold] = useState(5);

  const visibleRows = useMemo(() => {
    if (!hideLowVariance) return comparison.rows;
    return comparison.rows.filter((row) => {
      const rates = row.bids.map((b) => b.unit_rate).filter((r) => r > 0);
      if (rates.length < 2) return true;
      const mean = rates.reduce((s, r) => s + r, 0) / rates.length;
      if (mean === 0) return true;
      const min = Math.min(...rates);
      const max = Math.max(...rates);
      const spreadPct = ((max - min) / mean) * 100;
      return spreadPct > varianceThreshold;
    });
  }, [comparison.rows, hideLowVariance, varianceThreshold]);

  if (comparison.bid_count === 0) {
    return (
      <EmptyState
        icon={<BarChart3 size={28} strokeWidth={1.5} />}
        title={t('tendering.no_bids_yet', 'No bids yet')}
        description={t(
          'tendering.no_bids_description',
          'Add bids to see a side-by-side comparison.',
        )}
      />
    );
  }

  const stickyColClass =
    'sticky left-0 z-10 bg-surface-primary shadow-[2px_0_3px_-2px_rgba(0,0,0,0.1)]';
  const hiddenCount = comparison.rows.length - visibleRows.length;

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center justify-end gap-3 text-xs">
        <label className="inline-flex items-center gap-2 text-content-secondary cursor-pointer select-none">
          <input
            type="checkbox"
            checked={hideLowVariance}
            onChange={(e) => setHideLowVariance(e.target.checked)}
            className="h-3.5 w-3.5 rounded border-border text-oe-blue focus:ring-oe-blue/30"
          />
          {t('tendering.compare.collapseLowVariance', 'Hide low-variance positions')}
        </label>
        <label
          className={`inline-flex items-center gap-2 transition-opacity ${
            hideLowVariance ? 'text-content-secondary' : 'text-content-tertiary opacity-60'
          }`}
        >
          <span>{t('tendering.compare.varianceThreshold', 'Variance threshold')}</span>
          <select
            value={varianceThreshold}
            onChange={(e) => setVarianceThreshold(Number(e.target.value))}
            disabled={!hideLowVariance}
            className="h-7 rounded border border-border bg-surface-primary px-1.5 text-xs text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue/30 disabled:cursor-not-allowed"
          >
            <option value={5}>5%</option>
            <option value={10}>10%</option>
            <option value={15}>15%</option>
            <option value={20}>20%</option>
            <option value={25}>25%</option>
          </select>
        </label>
        {hideLowVariance && hiddenCount > 0 && (
          <span className="text-content-tertiary">
            {t('tendering.compare.hiddenCount', { defaultValue: '{{count}} hidden', count: hiddenCount })}
          </span>
        )}
      </div>
      <div className="overflow-x-auto relative">
        <table className="w-full text-sm">
          <thead className="sticky top-0 z-10 bg-surface-primary">
            <tr className="border-b border-border-light">
              <th
                className={`whitespace-nowrap px-3 py-2.5 text-left font-semibold text-content-primary ${stickyColClass} z-20`}
              >
                {t('tendering.position', 'Position')}
              </th>
              <th className="whitespace-nowrap px-3 py-2.5 text-right font-semibold text-content-primary">
                {t('tendering.budget', 'Budget')}
              </th>
              {comparison.bid_companies.map((company) => (
                <th
                  key={company}
                  className="whitespace-nowrap px-3 py-2.5 text-right font-semibold text-content-primary"
                >
                  <span className="flex items-center justify-end gap-1.5">
                    <Building2 size={12} className="text-content-tertiary" />
                    {company}
                  </span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {visibleRows.map((row, idx) => (
              <tr
                key={`${row.description}-${row.unit}-${idx}`}
                className="group border-b border-border-light/50 transition-colors hover:bg-surface-secondary/30"
              >
                <td className={`px-3 py-2.5 ${stickyColClass} z-20 group-hover:bg-surface-secondary/30`}>
                  <span className="text-content-primary">{row.description || '-'}</span>
                  <span className="ml-2 text-xs text-content-tertiary">{row.unit}</span>
                </td>
                <td className="whitespace-nowrap px-3 py-2.5 text-right tabular-nums text-content-secondary">
                  {formatNumber(row.budget_rate)}
                </td>
                {row.bids.map((bid, bi) => {
                  const rates = row.bids.map((b) => b.unit_rate);
                  const flag = classifyCell(bid.unit_rate, rates);
                  const flagCls =
                    flag === 'high'
                      ? 'bg-semantic-error-bg/50'
                      : flag === 'low'
                        ? 'bg-semantic-warning-bg/40'
                        : '';
                  const flagLabel =
                    flag === 'high'
                      ? t('tendering.outlier_high', 'High outlier vs median')
                      : flag === 'low'
                        ? t('tendering.outlier_low', 'Low outlier vs median')
                        : undefined;
                  return (
                    <td
                      key={`bid-${comparison.bid_companies[bi]}`}
                      className={`whitespace-nowrap px-3 py-2.5 text-right tabular-nums ${flagCls}`}
                      title={flagLabel}
                      aria-label={flagLabel}
                    >
                      <span className="text-content-primary">{formatNumber(bid.unit_rate)}</span>
                      {flag && (
                        <span className="ml-1 text-xs" aria-hidden="true">
                          {flag === 'high' ? '▲' : '▼'}
                        </span>
                      )}
                      {bid.unit_rate > 0 && (
                        <span className="ml-1.5">
                          <DeviationBadge pct={bid.deviation_pct} />
                        </span>
                      )}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr className="border-t-2 border-border bg-surface-secondary/30">
              <td
                className={`px-3 py-3 font-bold text-content-primary sticky left-0 z-20 bg-surface-secondary shadow-[2px_0_3px_-2px_rgba(0,0,0,0.1)]`}
              >
                {t('tendering.total', 'TOTAL')}
              </td>
              <td className="whitespace-nowrap px-3 py-3 text-right font-bold tabular-nums text-content-primary">
                {formatCurrency(comparison.budget_total, currency)}
              </td>
              {comparison.bid_totals.map((bt, i) => (
                <td
                  key={`total-${comparison.bid_companies[i]}`}
                  className="whitespace-nowrap px-3 py-3 text-right tabular-nums"
                >
                  <span className="font-bold text-content-primary">
                    {formatCurrency(bt.total, bt.currency)}
                  </span>
                  <span className="ml-1.5">
                    <DeviationBadge pct={bt.deviation_pct} />
                  </span>
                </td>
              ))}
            </tr>
          </tfoot>
        </table>
      </div>
    </div>
  );
}

/* ── Package Detail ───────────────────────────────────────────────────── */

function PackageDetail({
  packageId,
  currency,
}: {
  packageId: string;
  currency: string;
}) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const { confirm, ...confirmProps } = useConfirm();
  const [showAddBid, setShowAddBid] = useState(false);
  // Sub-tab on the package detail view — bids/comparison ↔ addenda ↔
  // leveling matrix. Defaults to "bids" so existing muscle memory keeps
  // working; the two new tabs are additive.
  const [activeTab, setActiveTab] = useState<'bids' | 'addenda' | 'leveling'>(
    'bids',
  );

  // Fetch package with bids
  const { data: pkg, isLoading: pkgLoading, isError: pkgError } = useQuery({
    queryKey: ['tendering-package', packageId],
    queryFn: () => apiGet<PackageWithBids>(`/v1/tendering/packages/${packageId}`),
  });

  // Fetch comparison
  const {
    data: comparison,
    isLoading: comparisonLoading,
    isError: comparisonError,
  } = useQuery({
    queryKey: ['tendering-comparison', packageId],
    queryFn: () => apiGet<BidComparison>(`/v1/tendering/packages/${packageId}/comparison/`),
  });

  // Award mutation — routes through the dedicated apply-winner endpoint so
  // the server performs the full transactional award (BOQ rate write-back,
  // package → awarded, winning bid → accepted, competing bids → rejected).
  // Previously this only PATCHed the bid status, leaving the package and
  // losing bids in a stale state and never writing rates back to the BOQ.
  const awardMutation = useMutation({
    mutationFn: (bidId: string) =>
      apiPost<{ positions_updated: number }>(
        `/v1/tendering/packages/${packageId}/apply-winner/?bid_id=${bidId}`,
        {},
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['tendering-package', packageId] });
      queryClient.invalidateQueries({ queryKey: ['tendering-comparison', packageId] });
      queryClient.invalidateQueries({ queryKey: ['tendering-packages'] });
      addToast({ type: 'success', title: t('toasts.bid_awarded', { defaultValue: 'Bid awarded' }) });
    },
    onError: (error: Error) => {
      addToast({ type: 'error', title: t('toasts.error', { defaultValue: 'Error' }), message: error.message });
    },
  });

  // Update package status
  const updateStatusMutation = useMutation({
    mutationFn: (newStatus: string) =>
      apiPatch<TenderPackage>(`/v1/tendering/packages/${packageId}`, {
        status: newStatus,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['tendering-package', packageId] });
      queryClient.invalidateQueries({ queryKey: ['tendering-packages'] });
      addToast({ type: 'success', title: t('toasts.status_updated', { defaultValue: 'Status updated' }) });
    },
    onError: (error: Error) => {
      addToast({ type: 'error', title: t('toasts.error', { defaultValue: 'Error' }), message: error.message });
    },
  });

  const handleBidCreated = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: ['tendering-package', packageId] });
    queryClient.invalidateQueries({ queryKey: ['tendering-comparison', packageId] });
    queryClient.invalidateQueries({ queryKey: ['tendering-packages'] });
  }, [queryClient, packageId]);

  const handleExport = useCallback(() => {
    if (!comparison) return;
    const headers = ['Position', 'Unit', 'Budget Rate', ...comparison.bid_companies.map(c => `${c} Rate`)];
    const rows = comparison.rows.map(row => [
      row.description,
      row.unit,
      row.budget_rate.toFixed(2),
      ...row.bids.map(b => b.unit_rate.toFixed(2)),
    ]);
    const footer = ['TOTAL', '', comparison.budget_total.toFixed(0), ...comparison.bid_totals.map(bt => bt.total.toFixed(0))];
    const csv = [headers, ...rows, footer].map(r => r.join(',')).join('\n');
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `bid-comparison-${pkg?.name || 'export'}.csv`;
    a.click();
    URL.revokeObjectURL(url);
    addToast({ type: 'success', title: t('tendering.exported', { defaultValue: 'Comparison exported' }) });
  }, [comparison, pkg, addToast, t]);

  // Smarter award recommendation: ranks by total but tags confidence so a
  // suspiciously low bid (>20% under the median) is flagged rather than
  // silently rubber-stamped. ``recommend()`` is unit-tested in
  // analysis.test.ts so the heuristic stays auditable.
  const recommendation = useMemo(() => {
    if (!comparison || comparison.bid_totals.length === 0) return null;
    return recommend(comparison.bid_totals);
  }, [comparison]);

  // Authenticated file download — ``window.open`` would lose the Bearer
  // token (JWT lives in localStorage, not a cookie) and silently 401 in a
  // blank tab. We fetch with the auth header, then trigger a regular
  // anchor-based download (Wave 12 audit fix).
  const handleDownloadPdf = useCallback(async () => {
    try {
      const token = getAuthToken();
      const r = await fetch(
        `/api/v1/tendering/packages/${packageId}/export/pdf/`,
        { headers: token ? { Authorization: `Bearer ${token}` } : {} },
      );
      if (!r.ok) {
        addToast({ type: 'error', title: t('tendering.export_failed', { defaultValue: 'Export failed' }) });
        return;
      }
      const blob = await r.blob();
      const name = pkg?.name?.replace(/[^a-z0-9_-]+/gi, '_') || 'tender';
      triggerDownload(blob, `${name}.pdf`);
    } catch {
      addToast({ type: 'error', title: t('tendering.export_failed', { defaultValue: 'Export failed' }) });
    }
  }, [packageId, pkg?.name, addToast, t]);

  const handleDownloadGaeb = useCallback(async () => {
    if (!pkg?.boq_id) return;
    try {
      const token = getAuthToken();
      const r = await fetch(`/api/v1/boq/boqs/${pkg.boq_id}/export/gaeb/`, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      if (!r.ok) {
        addToast({ type: 'error', title: t('tendering.export_failed', { defaultValue: 'Export failed' }) });
        return;
      }
      const blob = await r.blob();
      const name = pkg?.name?.replace(/[^a-z0-9_-]+/gi, '_') || 'tender';
      triggerDownload(blob, `${name}.xml`);
    } catch {
      addToast({ type: 'error', title: t('tendering.export_failed', { defaultValue: 'Export failed' }) });
    }
  }, [pkg?.boq_id, pkg?.name, addToast, t]);

  if (pkgLoading || (!pkg && !pkgError)) {
    return (
      <div className="mt-4">
        <SkeletonTable rows={4} columns={5} />
      </div>
    );
  }

  if (pkgError || !pkg) {
    return (
      <div className="mt-4">
        <Card className="py-12">
          <EmptyState
            icon={<AlertTriangle size={28} strokeWidth={1.5} />}
            title={t('common.error', { defaultValue: 'Error' })}
            description={t('tendering.package_load_error', {
              defaultValue: 'Failed to load this tender package. Please try again.',
            })}
          />
        </Card>
      </div>
    );
  }

  const awardablePackage = pkg.status === 'collecting' || pkg.status === 'evaluating';

  return (
    <div className="mt-4 space-y-4 animate-fade-in">
      {/* Package info + actions */}
      <Card>
        <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h3 className="text-lg font-semibold text-content-primary">{pkg.name}</h3>
            {pkg.description && (
              <p className="mt-0.5 text-sm text-content-secondary">{pkg.description}</p>
            )}
            <div className="mt-2 flex flex-wrap items-center gap-3 text-xs text-content-tertiary">
              <Badge variant={STATUS_COLORS[pkg.status] || 'neutral'} size="sm">
                {translateStatus(pkg.status, t)}
              </Badge>
              {pkg.deadline && (
                <span className="flex items-center gap-1">
                  <Clock size={12} />
                  {t('tendering.deadline', 'Deadline')}: {formatDate(pkg.deadline)}
                </span>
              )}
              <span>{t('tendering.bid_count', { defaultValue: '{{count}} bids', count: pkg.bids.length })}</span>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <Button
              variant="secondary"
              size="sm"
              icon={<Plus size={14} />}
              onClick={() => setShowAddBid(true)}
            >
              {t('tendering.add_bid', 'Add Bid')}
            </Button>
            {pkg.boq_id && (
              <Button
                variant="ghost"
                size="sm"
                icon={<Download size={14} />}
                onClick={handleDownloadGaeb}
                title={t('tendering.export_gaeb_title', 'Export the source BOQ as GAEB XML 3.3 (X83)')}
              >
                {t('tendering.export_gaeb', 'GAEB X83')}
              </Button>
            )}
            <Button
              variant="ghost"
              size="sm"
              icon={<FileText size={14} />}
              onClick={handleDownloadPdf}
              title={t('tendering.export_pdf_title', 'Download the tender summary PDF')}
            >
              {t('tendering.export_pdf', 'PDF')}
            </Button>
            {pkg.status === 'draft' && (
              <Button
                variant="primary"
                size="sm"
                icon={<Send size={14} />}
                loading={updateStatusMutation.isPending}
                onClick={() => updateStatusMutation.mutate('issued')}
              >
                {t('tendering.issue', 'Issue')}
              </Button>
            )}
            {pkg.status === 'issued' && (
              <Button
                variant="primary"
                size="sm"
                icon={<Clock size={14} />}
                loading={updateStatusMutation.isPending}
                onClick={() => updateStatusMutation.mutate('collecting')}
              >
                {t('tendering.start_collecting', 'Start Collecting')}
              </Button>
            )}
            {pkg.status === 'collecting' && (
              <Button
                variant="primary"
                size="sm"
                icon={<BarChart3 size={14} />}
                loading={updateStatusMutation.isPending}
                onClick={() => updateStatusMutation.mutate('evaluating')}
              >
                {t('tendering.evaluate', 'Evaluate Bids')}
              </Button>
            )}
            {pkg.status === 'evaluating' && (
              <Button
                variant="primary"
                size="sm"
                icon={<Award size={14} />}
                loading={updateStatusMutation.isPending}
                onClick={() => updateStatusMutation.mutate('awarded')}
              >
                {t('tendering.mark_awarded', 'Mark Awarded')}
              </Button>
            )}
            {(pkg.status === 'awarded' || pkg.status === 'evaluating') && (
              <Button
                variant="ghost"
                size="sm"
                loading={updateStatusMutation.isPending}
                onClick={() => updateStatusMutation.mutate('closed')}
              >
                {t('tendering.close_package', 'Close')}
              </Button>
            )}
          </div>
        </div>
      </Card>

      {/* Sub-tab strip — RIB iTWO-style: bids ↔ addenda ↔ leveling.
          Addenda and Leveling are hidden until their backend routes ship
          (the matching ``/addenda/`` and ``/leveling-matrix/`` endpoints
          do not exist on tendering/router.py yet — Wave 12 audit found
          the tabs were silently 404-ing). Set ``VITE_TENDERING_ADDENDA``
          / ``VITE_TENDERING_LEVELING`` to ``"1"`` to opt-in for QA. */}
      <div className="flex items-center gap-1 border-b border-border-light">
        {([
          { id: 'bids' as const, label: t('tendering.tab_bids', 'Bids & Comparison') },
          ...(import.meta.env.VITE_TENDERING_ADDENDA === '1'
            ? [{ id: 'addenda' as const, label: t('tendering.tab_addenda', 'Addenda') }]
            : []),
          ...(import.meta.env.VITE_TENDERING_LEVELING === '1'
            ? [{ id: 'leveling' as const, label: t('tendering.tab_leveling', 'Leveling') }]
            : []),
        ]).map((tab) => (
          <button
            key={tab.id}
            type="button"
            onClick={() => setActiveTab(tab.id)}
            className={`-mb-px border-b-2 px-4 py-2 text-sm font-medium transition-colors ${
              activeTab === tab.id
                ? 'border-oe-blue text-oe-blue'
                : 'border-transparent text-content-secondary hover:text-content-primary'
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Bids list */}
      {activeTab === 'bids' && pkg.bids.length > 0 && (
        <div className="space-y-2">
          <h4 className="text-sm font-semibold text-content-primary">
            {t('tendering.bids_received', 'Bids Received')}
          </h4>
          {pkg.bids.map((bid) => (
            <Card key={bid.id} padding="none">
              <div className="flex items-center gap-3 px-4 py-3">
                <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-surface-secondary text-content-tertiary">
                  <Building2 size={14} />
                </div>
                <div className="min-w-0 flex-1">
                  <span className="text-sm font-medium text-content-primary">
                    {bid.company_name}
                  </span>
                  {bid.contact_email && (
                    <span className="ml-2 text-xs text-content-tertiary flex items-center gap-1 inline-flex">
                      <Mail size={10} />
                      {bid.contact_email}
                    </span>
                  )}
                </div>
                <span className="text-sm font-semibold tabular-nums text-content-primary">
                  {formatCurrency(bid.total_amount, bid.currency)}
                </span>
                <Badge variant={STATUS_COLORS[bid.status] || 'neutral'} size="sm">
                  {translateStatus(bid.status, t)}
                </Badge>
                {bid.status !== 'accepted' && bid.status !== 'rejected' && awardablePackage && (
                  <Button
                    variant="ghost"
                    size="sm"
                    icon={<Award size={14} />}
                    loading={awardMutation.isPending}
                    onClick={async () => {
                      const ok = await confirm({
                        title: t('tendering.award_confirm_title', { defaultValue: 'Award contract?' }),
                        message: t('tendering.award_confirm', { defaultValue: 'Award this contract to {{company}}? Winning rates are written back to the BOQ and other bids are rejected. This action cannot be undone.', company: bid.company_name }),
                        variant: 'warning',
                      });
                      if (ok) awardMutation.mutate(bid.id);
                    }}
                    title={t('tendering.award_bid', 'Award this bid')}
                  >
                    {t('tendering.award', 'Award')}
                  </Button>
                )}
              </div>
            </Card>
          ))}
        </div>
      )}

      {/* Comparison chart + table */}
      {activeTab === 'bids' && (
      <Card>
        <div className="flex items-center justify-between mb-4">
          <h4 className="text-sm font-semibold text-content-primary flex items-center gap-2">
            <BarChart3 size={16} className="text-oe-blue" />
            {t('tendering.bid_comparison', 'Bid Comparison')}
          </h4>
          <Button variant="ghost" size="sm" icon={<Download size={14} />} onClick={handleExport}>
            {t('tendering.export_comparison', 'Export')}
          </Button>
        </div>
        {comparisonLoading ? (
          <SkeletonTable rows={4} columns={4} />
        ) : comparisonError ? (
          <EmptyState
            icon={<AlertTriangle size={28} strokeWidth={1.5} />}
            title={t('common.error', { defaultValue: 'Error' })}
            description={t('tendering.comparison_load_error', {
              defaultValue: 'Failed to load the bid comparison. Please try again.',
            })}
          />
        ) : comparison ? (
          <>
            <BidComparisonChart
              bidTotals={comparison.bid_totals}
              budgetTotal={comparison.budget_total}
              currency={currency}
            />
            <BidComparisonTable comparison={comparison} currency={currency} />
          </>
        ) : null}
      </Card>
      )}

      {/* Addenda sub-tab */}
      {activeTab === 'addenda' && <AddendumList packageId={packageId} />}

      {/* Leveling matrix sub-tab */}
      {activeTab === 'leveling' && (
        <LevelingMatrix packageId={packageId} currency={currency} />
      )}

      {/* Award recommendation — see analysis.ts for the confidence rules */}
      {activeTab === 'bids' && recommendation && comparison && (() => {
        const { winner, runnerUp, confidence, reasonKey, belowMedianPct } =
          recommendation;
        const palette =
          confidence === 'high'
            ? 'border-semantic-success/20 bg-semantic-success-bg/30 text-semantic-success'
            : confidence === 'low'
              ? 'border-semantic-error/20 bg-semantic-error-bg/30 text-semantic-error'
              : 'border-semantic-warning/20 bg-semantic-warning-bg/30 text-semantic-warning';
        const Icon = confidence === 'low' ? AlertTriangle : Award;
        const confidenceLabel =
          confidence === 'high'
            ? t('tendering.confidence_high', 'High confidence')
            : confidence === 'low'
              ? t('tendering.confidence_low', 'Low confidence — review carefully')
              : t('tendering.confidence_medium', 'Medium confidence');
        const reasonText: Record<typeof reasonKey, string> = {
          single_bid: t('tendering.reason_single_bid', 'Only one eligible bid received.'),
          clear_winner: t('tendering.reason_clear_winner', 'Clearly the lowest competitive offer.'),
          narrow_gap: t('tendering.reason_narrow_gap', 'Winner and runner-up are within 2% — consider non-price factors.'),
          suspicious_low: t('tendering.reason_suspicious_low', 'Lowest bid is {{pct}}% below the median — verify scope and pricing before awarding.', { pct: belowMedianPct }),
        };
        return (
          <Card className={`border ${palette}`}>
            <div className="flex items-start gap-3">
              <Icon size={20} className="mt-0.5" />
              <div className="flex-1">
                <div className="flex items-center gap-2">
                  <p className="text-sm font-semibold">
                    {t('tendering.recommendation', 'Recommendation')}
                  </p>
                  <Badge
                    variant={
                      confidence === 'high'
                        ? 'success'
                        : confidence === 'low'
                          ? 'error'
                          : 'warning'
                    }
                    size="sm"
                  >
                    {confidenceLabel}
                  </Badge>
                </div>
                <p className="mt-1 text-xs text-content-secondary">
                  <strong>{winner.company_name}</strong>{' '}
                  {t('tendering.at', 'at')}{' '}
                  {formatCurrency(winner.total, winner.currency)}{' '}
                  (<DeviationBadge pct={winner.deviation_pct} />{' '}
                  {t('tendering.vs_budget', 'vs budget')})
                  {runnerUp && (
                    <>
                      {' · '}
                      {t('tendering.runner_up', 'Runner-up:')}{' '}
                      {runnerUp.company_name}{' '}
                      ({formatCurrency(runnerUp.total, runnerUp.currency)})
                    </>
                  )}
                </p>
                <p className="mt-1 text-xs text-content-tertiary">
                  {reasonText[reasonKey]}
                </p>
              </div>
            </div>
          </Card>
        );
      })()}

      {/* Add bid dialog */}
      {showAddBid && (
        <AddBidDialog
          packageId={packageId}
          currency={currency}
          onClose={() => setShowAddBid(false)}
          onCreated={handleBidCreated}
        />
      )}
      <ConfirmDialog {...confirmProps} />
    </div>
  );
}

/* ── Main Page ─────────────────────────────────────────────────────────── */

export function TenderingPage() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const { activeProjectId, setActiveProject } = useProjectContextStore();

  const selectedProjectId = activeProjectId ?? '';
  const [selectedPackageId, setSelectedPackageId] = useState('');
  const [showCreateDialog, setShowCreateDialog] = useState(false);

  // Fetch projects
  const { data: projects, isLoading: projectsLoading } = useQuery({
    queryKey: ['projects'],
    queryFn: () => apiGet<Project[]>('/v1/projects/'),
    staleTime: 5 * 60_000,
  });

  // Fetch BOQs for selected project (needed for create dialog)
  const { data: boqs } = useQuery({
    queryKey: ['boqs', selectedProjectId],
    queryFn: () => apiGet<BOQ[]>(`/v1/boq/boqs/?project_id=${selectedProjectId}`),
    enabled: !!selectedProjectId,
  });

  // Fetch packages for selected project
  const {
    data: packages,
    isLoading: packagesLoading,
    isError: packagesError,
    error: packagesErrorObj,
    refetch: refetchPackages,
  } = useQuery({
    queryKey: ['tendering-packages', selectedProjectId],
    queryFn: () =>
      apiGet<TenderPackage[]>(
        `/v1/tendering/packages/?project_id=${selectedProjectId}`,
      ),
    enabled: !!selectedProjectId,
  });

  const selectedProject = useMemo(
    () => projects?.find((p) => p.id === selectedProjectId),
    [projects, selectedProjectId],
  );

  // Currency comes from the selected project — never hardcoded (task #217).
  // Empty string when the project has none; formatCurrency then renders a
  // symbol-less number rather than mislabelling amounts as EUR.
  const currency = selectedProject?.currency || '';

  const handleProjectChange = useCallback((id: string) => {
    const name = projects?.find((p) => p.id === id)?.name ?? '';
    if (id) {
      setActiveProject(id, name);
    } else {
      useProjectContextStore.getState().clearProject();
    }
    setSelectedPackageId('');
  }, [projects, setActiveProject]);

  const handlePackageCreated = useCallback(() => {
    queryClient.invalidateQueries({
      queryKey: ['tendering-packages', selectedProjectId],
    });
  }, [queryClient, selectedProjectId]);

  const projectOptions = (projects || []).map((p) => ({
    value: p.id,
    label: p.name,
  }));

  return (
    <div className="w-full animate-fade-in">
      <Breadcrumb items={[
        { label: t('nav.dashboard', 'Dashboard'), to: '/' },
        { label: t('tendering.title', 'Tendering') },
      ]} className="mb-4" />

      {/* Header */}
      <div className="mb-6 flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold text-content-primary">
            {t('tendering.title', 'Tendering')}
          </h1>
          <p className="mt-1 text-sm text-content-secondary">
            {t(
              'tendering.subtitle',
              'Manage bid packages, collect and compare subcontractor offers',
            )}
          </p>
        </div>
      </div>

      {/* Workflow explanation */}
      <InfoHint className="mb-6" text={t('tendering.workflow_desc', { defaultValue: 'Tendering workflow: Draft (prepare package) → Issued (send to bidders) → Collecting (receive bids) → Evaluating (compare offers side-by-side) → Awarded (select winner). Create a package from a BOQ, add subcontractor bids, then use the comparison table to identify the best offer. Add 2+ bids to see a side-by-side analysis.' })} />

      {/* Project selector + New package button */}
      <div className="mb-6 flex flex-col gap-4 sm:flex-row sm:items-end">
        <div className="flex-1">
          {projectsLoading ? (
            <Skeleton height={40} className="w-full" rounded="md" />
          ) : (
            <div>
              <label className="text-sm font-medium text-content-primary block mb-1.5">
                {t('tendering.select_project', 'Project')}
              </label>
              <SelectDropdown
                value={selectedProjectId}
                onChange={handleProjectChange}
                options={projectOptions}
                placeholder={t('tendering.select_project_placeholder', 'Choose a project...')}
              />
            </div>
          )}
        </div>
        <span title={!selectedProjectId ? t('tendering.select_project_first', { defaultValue: 'Select a project first' }) : undefined}>
          <Button
            variant="primary"
            size="md"
            icon={<Plus size={16} />}
            disabled={!selectedProjectId}
            onClick={() => setShowCreateDialog(true)}
          >
            {t('tendering.new_package', 'New Tender Package')}
          </Button>
        </span>
      </div>

      {/* Empty state when no project chosen (page-internal selector above) */}
      {!selectedProjectId && (
        <RequiresProject
          emptyHint={t('tendering.select_project_desc', {
            defaultValue: 'Select a project and create a tender from a BOQ to get started',
          })}
        >
          {null}
        </RequiresProject>
      )}

      {/* Loading packages */}
      {selectedProjectId && packagesLoading && (
        <SkeletonTable rows={2} columns={4} />
      )}

      {/* Failed to load packages */}
      {selectedProjectId && !packagesLoading && packagesError && (
        <Card className="py-12">
          <RecoveryCard error={packagesErrorObj} onRetry={() => refetchPackages()} />
        </Card>
      )}

      {/* No packages */}
      {selectedProjectId && !packagesLoading && !packagesError && packages && packages.length === 0 && (
        <EmptyState
          icon={<FileText size={28} strokeWidth={1.5} />}
          title={t('tendering.no_packages', { defaultValue: 'No tenders yet' })}
          description={t('tendering.no_packages_description', {
            defaultValue: 'Create a tender from a BOQ to start collecting bids',
          })}
          action={{
            label: t('tendering.new_package', { defaultValue: 'New Tender Package' }),
            onClick: () => setShowCreateDialog(true),
          }}
        />
      )}

      {/* Packages list */}
      {packages && packages.length > 0 && (
        <div>
          <h2 className="mb-3 text-sm font-semibold text-content-primary">
            {t('tendering.packages', 'Packages')}
          </h2>
          <div className="space-y-2">
            {packages.map((pkg) => (
              <PackageCard
                key={pkg.id}
                pkg={pkg}
                isSelected={selectedPackageId === pkg.id}
                onClick={() =>
                  setSelectedPackageId(
                    selectedPackageId === pkg.id ? '' : pkg.id,
                  )
                }
              />
            ))}
          </div>

          {/* Selected package detail */}
          {selectedPackageId && (
            <PackageDetail
              packageId={selectedPackageId}
              currency={currency}
            />
          )}
        </div>
      )}

      {/* Create package dialog */}
      {showCreateDialog && selectedProjectId && (
        <CreatePackageDialog
          projectId={selectedProjectId}
          boqs={boqs || []}
          onClose={() => setShowCreateDialog(false)}
          onCreated={handlePackageCreated}
        />
      )}
    </div>
  );
}
