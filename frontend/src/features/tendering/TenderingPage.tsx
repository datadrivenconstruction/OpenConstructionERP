import { useState, useMemo, useCallback } from 'react';
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
  X,
} from 'lucide-react';
import { Button, Card, Badge, EmptyState, Skeleton } from '@/shared/ui';
import { apiGet, apiPost, apiPatch } from '@/shared/lib/api';

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

function formatCurrency(amount: number | string, currency: string = 'EUR'): string {
  const num = typeof amount === 'string' ? parseFloat(amount) || 0 : amount;
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency,
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
  }).format(num);
}

function formatNumber(n: number, decimals: number = 2): string {
  return new Intl.NumberFormat('en-US', {
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
      <span className="inline-flex items-center gap-0.5 text-xs font-medium text-[#15803d]">
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
    },
  });

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 animate-fade-in">
      <Card className="w-full max-w-md animate-scale-in">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold text-content-primary">
            {t('tendering.new_package', 'New Tender Package')}
          </h2>
          <button
            onClick={onClose}
            className="rounded-md p-1 text-content-tertiary hover:bg-surface-secondary hover:text-content-primary transition-colors"
          >
            <X size={18} />
          </button>
        </div>

        <div className="space-y-4">
          <div>
            <label className="text-sm font-medium text-content-primary block mb-1.5">
              {t('tendering.package_name', 'Package Name')}
            </label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder={t('tendering.package_name_placeholder', 'e.g. Concrete Works Package')}
              className="h-10 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm text-content-primary placeholder:text-content-tertiary transition-all focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue"
            />
          </div>

          <div>
            <label className="text-sm font-medium text-content-primary block mb-1.5">
              {t('tendering.source_boq', 'Source BOQ')}
            </label>
            <SelectDropdown
              value={boqId}
              onChange={setBoqId}
              options={boqs.map((b) => ({ value: b.id, label: b.name }))}
              placeholder={t('tendering.select_boq', 'Select a BOQ...')}
            />
          </div>

          <div>
            <label className="text-sm font-medium text-content-primary block mb-1.5">
              {t('tendering.description', 'Description')}
            </label>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={2}
              className="w-full rounded-lg border border-border bg-surface-primary px-3 py-2 text-sm text-content-primary placeholder:text-content-tertiary transition-all focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue resize-none"
              placeholder={t('tendering.description_placeholder', 'Brief description of the package scope...')}
            />
          </div>

          <div>
            <label className="text-sm font-medium text-content-primary block mb-1.5">
              {t('tendering.deadline', 'Deadline')}
            </label>
            <input
              type="date"
              value={deadline}
              onChange={(e) => setDeadline(e.target.value)}
              className="h-10 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm text-content-primary transition-all focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue"
            />
          </div>
        </div>

        <div className="mt-6 flex justify-end gap-3">
          <Button variant="ghost" onClick={onClose}>
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
        </div>
      </Card>
    </div>
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
  const [companyName, setCompanyName] = useState('');
  const [contactEmail, setContactEmail] = useState('');
  const [totalAmount, setTotalAmount] = useState('');
  const [notes, setNotes] = useState('');

  const createMutation = useMutation({
    mutationFn: () =>
      apiPost<BidData>(`/v1/tendering/packages/${packageId}/bids`, {
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
    },
  });

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 animate-fade-in">
      <Card className="w-full max-w-md animate-scale-in">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold text-content-primary">
            {t('tendering.add_bid', 'Add Bid')}
          </h2>
          <button
            onClick={onClose}
            className="rounded-md p-1 text-content-tertiary hover:bg-surface-secondary hover:text-content-primary transition-colors"
          >
            <X size={18} />
          </button>
        </div>

        <div className="space-y-4">
          <div>
            <label className="text-sm font-medium text-content-primary block mb-1.5">
              {t('tendering.company_name', 'Company Name')}
            </label>
            <input
              type="text"
              value={companyName}
              onChange={(e) => setCompanyName(e.target.value)}
              placeholder={t('tendering.company_placeholder', 'e.g. Schmidt Bau GmbH')}
              className="h-10 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm text-content-primary placeholder:text-content-tertiary transition-all focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue"
            />
          </div>

          <div>
            <label className="text-sm font-medium text-content-primary block mb-1.5">
              {t('tendering.contact_email', 'Contact Email')}
            </label>
            <input
              type="email"
              value={contactEmail}
              onChange={(e) => setContactEmail(e.target.value)}
              placeholder="contact@example.com"
              className="h-10 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm text-content-primary placeholder:text-content-tertiary transition-all focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue"
            />
          </div>

          <div>
            <label className="text-sm font-medium text-content-primary block mb-1.5">
              {t('tendering.total_amount', 'Total Amount')} ({currency})
            </label>
            <input
              type="number"
              value={totalAmount}
              onChange={(e) => setTotalAmount(e.target.value)}
              placeholder="0"
              className="h-10 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm text-content-primary placeholder:text-content-tertiary transition-all focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue"
            />
          </div>

          <div>
            <label className="text-sm font-medium text-content-primary block mb-1.5">
              {t('tendering.notes', 'Notes')}
            </label>
            <textarea
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              rows={2}
              className="w-full rounded-lg border border-border bg-surface-primary px-3 py-2 text-sm text-content-primary placeholder:text-content-tertiary transition-all focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue resize-none"
              placeholder={t('tendering.notes_placeholder', 'Optional notes...')}
            />
          </div>
        </div>

        <div className="mt-6 flex justify-end gap-3">
          <Button variant="ghost" onClick={onClose}>
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
        </div>
      </Card>
    </div>
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
        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-oe-blue-subtle text-oe-blue">
          <Package size={18} />
        </div>
        <div className="min-w-0 flex-1">
          <h3 className="text-sm font-semibold text-content-primary truncate">
            {pkg.name}
          </h3>
          <div className="mt-0.5 flex items-center gap-3 text-xs text-content-secondary">
            <span className="flex items-center gap-1">
              <FileText size={12} />
              {pkg.bid_count} {t('tendering.bids_count', 'bids')}
            </span>
            {pkg.deadline && (
              <span className="flex items-center gap-1">
                <Clock size={12} />
                {pkg.deadline}
              </span>
            )}
          </div>
        </div>
        <Badge variant={STATUS_COLORS[pkg.status] || 'neutral'} size="sm">
          {pkg.status}
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

  if (comparison.bid_count === 0) {
    return (
      <EmptyState
        icon={<BarChart3 size={24} strokeWidth={1.5} />}
        title={t('tendering.no_bids_yet', 'No bids yet')}
        description={t(
          'tendering.no_bids_description',
          'Add bids to see a side-by-side comparison.',
        )}
      />
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-border-light">
            <th className="whitespace-nowrap px-3 py-2.5 text-left font-semibold text-content-primary">
              {t('tendering.position', 'Position')}
            </th>
            <th className="whitespace-nowrap px-3 py-2.5 text-right font-semibold text-content-primary">
              {t('tendering.budget', 'Budget')}
            </th>
            {comparison.bid_companies.map((company, i) => (
              <th
                key={i}
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
          {comparison.rows.map((row, idx) => (
            <tr
              key={idx}
              className="border-b border-border-light/50 transition-colors hover:bg-surface-secondary/30"
            >
              <td className="px-3 py-2.5">
                <span className="text-content-primary">{row.description || '-'}</span>
                <span className="ml-2 text-xs text-content-tertiary">{row.unit}</span>
              </td>
              <td className="whitespace-nowrap px-3 py-2.5 text-right tabular-nums text-content-secondary">
                {formatNumber(row.budget_rate)}
              </td>
              {row.bids.map((bid, bi) => (
                <td
                  key={bi}
                  className="whitespace-nowrap px-3 py-2.5 text-right tabular-nums"
                >
                  <span className="text-content-primary">{formatNumber(bid.unit_rate)}</span>
                  {bid.unit_rate > 0 && (
                    <span className="ml-1.5">
                      <DeviationBadge pct={bid.deviation_pct} />
                    </span>
                  )}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
        <tfoot>
          <tr className="border-t-2 border-border bg-surface-secondary/30">
            <td className="px-3 py-3 font-bold text-content-primary">
              {t('tendering.total', 'TOTAL')}
            </td>
            <td className="whitespace-nowrap px-3 py-3 text-right font-bold tabular-nums text-content-primary">
              {formatCurrency(comparison.budget_total, currency)}
            </td>
            {comparison.bid_totals.map((bt, i) => (
              <td
                key={i}
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
  const [showAddBid, setShowAddBid] = useState(false);

  // Fetch package with bids
  const { data: pkg, isLoading: pkgLoading } = useQuery({
    queryKey: ['tendering-package', packageId],
    queryFn: () => apiGet<PackageWithBids>(`/v1/tendering/packages/${packageId}`),
  });

  // Fetch comparison
  const { data: comparison, isLoading: comparisonLoading } = useQuery({
    queryKey: ['tendering-comparison', packageId],
    queryFn: () => apiGet<BidComparison>(`/v1/tendering/packages/${packageId}/comparison`),
  });

  // Award mutation
  const awardMutation = useMutation({
    mutationFn: (bidId: string) =>
      apiPatch<BidData>(`/v1/tendering/bids/${bidId}`, { status: 'accepted' }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['tendering-package', packageId] });
      queryClient.invalidateQueries({ queryKey: ['tendering-comparison', packageId] });
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
    },
  });

  const handleBidCreated = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: ['tendering-package', packageId] });
    queryClient.invalidateQueries({ queryKey: ['tendering-comparison', packageId] });
    queryClient.invalidateQueries({ queryKey: ['tendering-packages'] });
  }, [queryClient, packageId]);

  if (pkgLoading) {
    return (
      <div className="space-y-4 mt-4">
        <Skeleton height={48} className="w-full" rounded="lg" />
        <Skeleton height={200} className="w-full" rounded="lg" />
      </div>
    );
  }

  if (!pkg) return null;

  const lowestBid = useMemo(() => {
    if (!comparison || comparison.bid_totals.length === 0) return undefined;
    let min = comparison.bid_totals[0]!;
    for (const bt of comparison.bid_totals) {
      if (bt.total < min.total) min = bt;
    }
    return min;
  }, [comparison]);

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
                {pkg.status}
              </Badge>
              {pkg.deadline && (
                <span className="flex items-center gap-1">
                  <Clock size={12} />
                  {t('tendering.deadline', 'Deadline')}: {pkg.deadline}
                </span>
              )}
              <span>{pkg.bids.length} {t('tendering.bids_count', 'bids')}</span>
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
          </div>
        </div>
      </Card>

      {/* Bids list */}
      {pkg.bids.length > 0 && (
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
                  {bid.status}
                </Badge>
                {bid.status !== 'accepted' && (
                  <Button
                    variant="ghost"
                    size="sm"
                    icon={<Award size={14} />}
                    loading={awardMutation.isPending}
                    onClick={() => awardMutation.mutate(bid.id)}
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

      {/* Comparison table */}
      <Card>
        <div className="flex items-center justify-between mb-4">
          <h4 className="text-sm font-semibold text-content-primary flex items-center gap-2">
            <BarChart3 size={16} className="text-oe-blue" />
            {t('tendering.bid_comparison', 'Bid Comparison')}
          </h4>
          <Button variant="ghost" size="sm" icon={<Download size={14} />}>
            {t('tendering.export_comparison', 'Export')}
          </Button>
        </div>
        {comparisonLoading ? (
          <Skeleton height={200} className="w-full" rounded="lg" />
        ) : comparison ? (
          <BidComparisonTable comparison={comparison} currency={currency} />
        ) : null}
      </Card>

      {/* Award recommendation */}
      {lowestBid && comparison && comparison.bid_count >= 2 && (
        <Card className="border-semantic-success/20 bg-semantic-success-bg/30">
          <div className="flex items-center gap-3">
            <Award size={20} className="text-[#15803d]" />
            <div>
              <p className="text-sm font-semibold text-[#15803d]">
                {t('tendering.recommendation', 'Recommendation')}
              </p>
              <p className="text-xs text-content-secondary">
                {t('tendering.lowest_bid', 'Lowest bid from')}{' '}
                <strong>{lowestBid.company_name}</strong>{' '}
                {t('tendering.at', 'at')}{' '}
                {formatCurrency(lowestBid.total, lowestBid.currency)}{' '}
                (<DeviationBadge pct={lowestBid.deviation_pct} />
                {' '}{t('tendering.vs_budget', 'vs budget')})
              </p>
            </div>
          </div>
        </Card>
      )}

      {/* Add bid dialog */}
      {showAddBid && (
        <AddBidDialog
          packageId={packageId}
          currency={currency}
          onClose={() => setShowAddBid(false)}
          onCreated={handleBidCreated}
        />
      )}
    </div>
  );
}

/* ── Main Page ─────────────────────────────────────────────────────────── */

export function TenderingPage() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();

  const [selectedProjectId, setSelectedProjectId] = useState('');
  const [selectedPackageId, setSelectedPackageId] = useState('');
  const [showCreateDialog, setShowCreateDialog] = useState(false);

  // Fetch projects
  const { data: projects, isLoading: projectsLoading } = useQuery({
    queryKey: ['projects'],
    queryFn: () => apiGet<Project[]>('/v1/projects/'),
  });

  // Fetch BOQs for selected project (needed for create dialog)
  const { data: boqs } = useQuery({
    queryKey: ['boqs', selectedProjectId],
    queryFn: () => apiGet<BOQ[]>(`/v1/boq/boqs/?project_id=${selectedProjectId}`),
    enabled: !!selectedProjectId,
  });

  // Fetch packages for selected project
  const { data: packages, isLoading: packagesLoading } = useQuery({
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

  const currency = selectedProject?.currency || 'EUR';

  const handleProjectChange = useCallback((id: string) => {
    setSelectedProjectId(id);
    setSelectedPackageId('');
  }, []);

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
    <div className="max-w-content mx-auto animate-fade-in">
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
        <Button
          variant="primary"
          size="md"
          icon={<Plus size={16} />}
          disabled={!selectedProjectId}
          onClick={() => setShowCreateDialog(true)}
        >
          {t('tendering.new_package', 'New Tender Package')}
        </Button>
      </div>

      {/* No project selected */}
      {!selectedProjectId && (
        <EmptyState
          icon={<Package size={24} strokeWidth={1.5} />}
          title={t('tendering.empty_title', 'Select a project')}
          description={t(
            'tendering.empty_description',
            'Choose a project to view or create tender packages.',
          )}
        />
      )}

      {/* Loading packages */}
      {selectedProjectId && packagesLoading && (
        <div className="space-y-3">
          {[1, 2].map((i) => (
            <Skeleton key={i} height={72} className="w-full" rounded="lg" />
          ))}
        </div>
      )}

      {/* No packages */}
      {selectedProjectId && !packagesLoading && packages && packages.length === 0 && (
        <EmptyState
          icon={<Package size={24} strokeWidth={1.5} />}
          title={t('tendering.no_packages', 'No tender packages')}
          description={t(
            'tendering.no_packages_description',
            'Create a tender package from a BOQ to start collecting bids.',
          )}
          action={
            <Button
              variant="primary"
              size="md"
              icon={<Plus size={16} />}
              onClick={() => setShowCreateDialog(true)}
            >
              {t('tendering.new_package', 'New Tender Package')}
            </Button>
          }
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
