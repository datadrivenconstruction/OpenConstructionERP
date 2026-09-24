// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { useState, useMemo, useCallback, useEffect, Fragment, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
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
  ArrowRight,
  Users,
  Check,
  Search,
  Loader2,
  Trash2,
  Inbox,
  Network,
  XCircle,
  CheckCircle2,
} from 'lucide-react';
import { Button, Card, Badge, EmptyState, RecoveryCard, DismissibleInfo, IntroRichText, SkeletonTable, Breadcrumb, ConfirmDialog, ModuleGuideButton, CollapsibleSection } from '@/shared/ui';
import { RequiresProject } from '@/shared/auth/RequiresProject';
import { PageHeader } from '@/shared/ui/PageHeader';
import { TruncationNotice } from '@/shared/ui/TruncationNotice';
import {
  WideModal,
  WideModalSection,
  WideModalField,
} from '@/shared/ui/WideModal';
import { useConfirm } from '@/shared/hooks/useConfirm';
import { apiGet, apiPost, apiPatch, getAuthToken, triggerDownload } from '@/shared/lib/api';
import { fetchProjectList } from '@/shared/lib/projectList';
import { useToastStore } from '@/stores/useToastStore';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { BidComparisonChart } from './BidComparisonChart';
import { AddendumList } from './AddendumList';
import { AwardRecordPanel } from './AwardRecordPanel';
import { LevelingMatrix } from './LevelingMatrix';
import { classifyCell, recommend } from './analysis';
import { tenderingGuide } from './tenderingGuide';
import {
  listRecipients,
  addRecipient,
  removeRecipient,
  distributePackage,
  getPackageScope,
  type Recipient,
  type DistributeResponse,
} from './api';
import { fmtList, fmtPercent, getIntlLocale } from '@/shared/lib/formatters';
import {
  listSubcontractors,
  type Subcontractor,
  type PrequalStatus,
} from '@/features/subcontractors/api';
import { InsightsPanel, InsightsToggleButton, useModuleInsights } from '@/features/insights';
import { buildTenderingInsights } from './tenderingInsights';
import { getNumberLocale } from '@/stores/usePreferencesStore';
import { formatCurrency as formatMoney } from '@/shared/lib/money';

// English fallbacks for the computed `tendering.prequal_*` keys. The default used to be
// the raw value, so until the key lands in a locale the screen shows the bare
// enum token to every reader, English included. Unknown values still fall
// through to the previous default.
const TENDERING_PREQUAL_LABELS: Record<string, string> = {
  pending: 'Pending', approved: 'Approved', suspended: 'Suspended', rejected: 'Rejected'
};


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
  // The strict-currency policy is unchanged and is the shared formatter's
  // policy too (task #217): a project priced in BRL/INR must never render its
  // tender amounts with a Euro sign, so an unknown code yields a plain grouped
  // number with no symbol rather than a substituted one.
  //
  // What is removed is the digit count. Both ends were pinned to zero against
  // a currency arriving as a variable, which posted every tender amount on
  // this page as a whole unit - the TOTAL row of the comparison table reading
  // "1.235 €" beneath rate cells written to two decimals. How many minor units
  // a currency has is a property of the currency, so the shared formatter
  // answers it; nothing here decides which currency gets how many.
  //
  // The unit-rate cells above that footer keep their own two decimals on
  // purpose. A rate is a derived working figure and a posted amount is not,
  // and that asymmetry is the one commit 8bbd6daf3 named as deliberate.
  return formatMoney(amount, currency);
}

function formatNumber(n: number, decimals: number = 2): string {
  return new Intl.NumberFormat(getNumberLocale(), {
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
        <ArrowDownRight size={12} /> {fmtPercent(pct)}
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-0.5 text-xs font-medium text-semantic-error">
      <ArrowUpRight size={12} /> +{fmtPercent(pct)}
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

/* ── Subcontractor directory picker ───────────────────────────────────── */

// CONN-41: add a bid against a known subcontractor instead of retyping the
// company by hand. Resolves the firm's primary contact email and shows the
// prequalification status so you compare like for like.
interface SubcontractorContactLite {
  id: string;
  email: string | null;
  primary: boolean;
}

const PREQUAL_PICKER_VARIANT: Record<
  PrequalStatus,
  'neutral' | 'blue' | 'success' | 'warning' | 'error'
> = {
  pending: 'warning',
  approved: 'success',
  suspended: 'warning',
  rejected: 'error',
};

async function resolveSubcontractorEmail(subId: string): Promise<string> {
  const contacts = await apiGet<SubcontractorContactLite[]>(
    `/v1/subcontractors/subcontractors/${subId}/contacts`,
  ).catch(() => [] as SubcontractorContactLite[]);
  const primary = contacts.find((c) => c.primary && c.email);
  return (primary?.email || contacts.find((c) => c.email)?.email || '').trim();
}

function SubcontractorPickerModal({
  onPick,
  onClose,
}: {
  onPick: (sub: Subcontractor, email: string) => void;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const [search, setSearch] = useState('');
  const [resolvingId, setResolvingId] = useState<string | null>(null);

  const subsQ = useQuery({
    queryKey: ['tendering', 'subcontractor-directory'],
    queryFn: () => listSubcontractors({ active_only: true, limit: 200 }),
    staleTime: 60_000,
  });

  const rows = useMemo(() => {
    const items = subsQ.data?.items ?? [];
    const s = search.trim().toLowerCase();
    if (!s) return items;
    return items.filter(
      (it) =>
        it.legal_name.toLowerCase().includes(s) ||
        (it.trade_name || '').toLowerCase().includes(s) ||
        it.trade_categories.some((c) => c.toLowerCase().includes(s)),
    );
  }, [subsQ.data, search]);

  const pick = async (sub: Subcontractor) => {
    setResolvingId(sub.id);
    const email = await resolveSubcontractorEmail(sub.id);
    setResolvingId(null);
    onPick(sub, email);
    onClose();
  };

  const fieldCls =
    'h-10 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm text-content-primary placeholder:text-content-tertiary transition-all focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';

  return (
    <WideModal
      open
      onClose={onClose}
      title={t('tendering.pick_sub_title', {
        defaultValue: 'Add bid from Subcontractor Directory',
      })}
      subtitle={t('tendering.pick_sub_subtitle', {
        defaultValue:
          'Pick a prequalified subcontractor. The prequalification status is shown so you compare like for like.',
      })}
      size="lg"
      footer={
        <Button variant="ghost" onClick={onClose}>
          {t('common.cancel', 'Cancel')}
        </Button>
      }
    >
      <div className="space-y-3">
        <div className="relative">
          <Search
            size={14}
            className="absolute left-3 top-1/2 -translate-y-1/2 text-content-tertiary"
          />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder={t('tendering.pick_sub_search', {
              defaultValue: 'Search subcontractors by name or trade…',
            })}
            className={`${fieldCls} pl-8`}
            autoFocus
          />
        </div>
        {subsQ.isLoading ? (
          <SkeletonTable rows={5} columns={3} />
        ) : rows.length === 0 ? (
          <EmptyState
            icon={<Users size={22} />}
            title={t('tendering.pick_sub_empty', {
              defaultValue: 'No subcontractors found',
            })}
            description={t('tendering.pick_sub_empty_desc', {
              defaultValue: 'Add subcontractors in the directory, then add their bids here.',
            })}
          />
        ) : (
          <div className="max-h-[420px] overflow-y-auto rounded-lg border border-border-light divide-y divide-border-light">
            {rows.map((sub) => (
              <button
                key={sub.id}
                type="button"
                onClick={() => pick(sub)}
                disabled={resolvingId !== null}
                className="flex w-full items-center justify-between gap-3 px-3 py-2.5 text-left hover:bg-surface-secondary disabled:opacity-60"
              >
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm font-medium text-content-primary">
                    {sub.legal_name}
                  </span>
                  {sub.trade_categories.length > 0 && (
                    <span className="block truncate text-xs text-content-tertiary">
                      {fmtList(sub.trade_categories.slice(0, 3))}
                    </span>
                  )}
                </span>
                <Badge variant={PREQUAL_PICKER_VARIANT[sub.prequalification_status]} dot>
                  {t(`tendering.prequal_${sub.prequalification_status}`, {
                    defaultValue: TENDERING_PREQUAL_LABELS[sub.prequalification_status] ?? sub.prequalification_status,
                  })}
                </Badge>
                {resolvingId === sub.id ? (
                  <Loader2 size={14} className="shrink-0 animate-spin text-content-tertiary" />
                ) : (
                  <Check size={14} className="shrink-0 text-content-tertiary" />
                )}
              </button>
            ))}
          </div>
        )}
        {/* The picker cannot page, so the only honest thing it can do about a
            yard bigger than one page is say so. The search box filters what
            arrived, not the register, which is exactly the state a reader
            reads as "this firm is not set up yet". */}
        {subsQ.data && <TruncationNotice page={subsQ.data} className="mt-2" />}
      </div>
    </WideModal>
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
  // CONN-41: pick a bidder straight from the Subcontractor Directory rather
  // than retyping the company and email.
  const [pickerOpen, setPickerOpen] = useState(false);

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
        <WideModalField label={t('tendering.bidder_source', 'Bidder')} span={2}>
          <Button
            variant="secondary"
            size="sm"
            icon={<Users size={14} />}
            onClick={() => setPickerOpen(true)}
            type="button"
          >
            {t('tendering.select_from_subs', 'Select from Subcontractors')}
          </Button>
        </WideModalField>
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
      {pickerOpen && (
        <SubcontractorPickerModal
          onPick={(sub, resolvedEmail) => {
            setCompanyName(sub.legal_name);
            if (resolvedEmail) setContactEmail(resolvedEmail);
            if (!resolvedEmail) {
              addToast({
                type: 'info',
                title: t('tendering.sub_no_email', {
                  defaultValue: 'No contact email on file - enter one if needed.',
                }),
              });
            }
          }}
          onClose={() => setPickerOpen(false)}
        />
      )}
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
              {comparison.bid_totals.map((bt) => (
                <th
                  key={bt.bid_id}
                  className="whitespace-nowrap px-3 py-2.5 text-right font-semibold text-content-primary"
                >
                  <span className="flex items-center justify-end gap-1.5">
                    <Building2 size={12} className="text-content-tertiary" />
                    {bt.company_name}
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
                {row.bids.map((bid) => {
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
                      key={`bid-${bid.bid_id}`}
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
              {comparison.bid_totals.map((bt) => (
                <td
                  key={`total-${bt.bid_id}`}
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

/* ── Distribution Panel ───────────────────────────────────────────────── */

// Wires the "issue to subcontractors" gap: manage a recipient list and email
// the package out. Sending reuses the platform mailer server-side; when SMTP
// is not configured the backend falls back to the console backend and reports
// it here, so the action never silently fails.
function RecipientStatusBadge({ status }: { status: string }) {
  const { t } = useTranslation();
  if (status === 'sent') {
    return (
      <Badge variant="success" size="sm" dot>
        {t('tendering.recipient_sent', { defaultValue: 'Sent' })}
      </Badge>
    );
  }
  if (status === 'failed') {
    return (
      <Badge variant="error" size="sm" dot>
        {t('tendering.recipient_failed', { defaultValue: 'Failed' })}
      </Badge>
    );
  }
  return (
    <Badge variant="neutral" size="sm" dot>
      {t('tendering.recipient_pending', { defaultValue: 'Not sent' })}
    </Badge>
  );
}

function DistributionPanel({ packageId }: { packageId: string }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const { confirm, ...confirmProps } = useConfirm();
  const [pickerOpen, setPickerOpen] = useState(false);
  const [manualCompany, setManualCompany] = useState('');
  const [manualEmail, setManualEmail] = useState('');
  const [message, setMessage] = useState('');
  const [lastResult, setLastResult] = useState<DistributeResponse | null>(null);

  const recipientsQ = useQuery({
    queryKey: ['tendering-recipients', packageId],
    queryFn: () => listRecipients(packageId),
  });

  const invalidate = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: ['tendering-recipients', packageId] });
  }, [queryClient, packageId]);

  const addMutation = useMutation({
    mutationFn: (body: { company_name: string; email: string; subcontractor_id?: string | null }) =>
      addRecipient(packageId, body),
    onSuccess: () => {
      invalidate();
      setManualCompany('');
      setManualEmail('');
    },
    onError: (error: Error) => {
      addToast({ type: 'error', title: t('toasts.error', { defaultValue: 'Error' }), message: error.message });
    },
  });

  const removeMutation = useMutation({
    mutationFn: (recipientId: string) => removeRecipient(packageId, recipientId),
    onSuccess: invalidate,
    onError: (error: Error) => {
      addToast({ type: 'error', title: t('toasts.error', { defaultValue: 'Error' }), message: error.message });
    },
  });

  const distributeMutation = useMutation({
    mutationFn: (resend: boolean) =>
      distributePackage(packageId, { resend, message: message.trim() || undefined }),
    onSuccess: (res) => {
      setLastResult(res);
      invalidate();
      queryClient.invalidateQueries({ queryKey: ['tendering-package', packageId] });
      queryClient.invalidateQueries({ queryKey: ['tendering-packages'] });
      if (res.sent_count > 0) {
        addToast({
          type: 'success',
          title: t('tendering.distribute_done', {
            defaultValue: 'Sent to {{count}} recipient(s)',
            count: res.sent_count,
          }),
          message: res.smtp_configured
            ? undefined
            : t('tendering.distribute_console', {
                defaultValue:
                  'SMTP is not configured, so emails were logged to the server console (dev mode). Set SMTP_HOST for real delivery.',
              }),
        });
      } else if (res.failed_count > 0) {
        addToast({
          type: 'error',
          title: t('tendering.distribute_failed', { defaultValue: 'Distribution failed' }),
        });
      } else {
        addToast({
          type: 'info',
          title: t('tendering.distribute_nothing', { defaultValue: 'Nothing to send' }),
        });
      }
    },
    onError: (error: Error) => {
      addToast({ type: 'error', title: t('toasts.error', { defaultValue: 'Error' }), message: error.message });
    },
  });

  const recipients = recipientsQ.data ?? [];
  const fieldCls =
    'h-10 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm text-content-primary placeholder:text-content-tertiary transition-all focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';

  return (
    <div className="space-y-4">
      {/* Add recipient */}
      <Card>
        <h4 className="mb-3 text-sm font-semibold text-content-primary flex items-center gap-2">
          <Users size={16} className="text-oe-blue" />
          {t('tendering.recipients', { defaultValue: 'Distribution list' })}
        </h4>
        <div className="flex flex-col gap-2 sm:flex-row sm:items-end">
          <div className="flex-1">
            <label className="mb-1 block text-xs text-content-secondary">
              {t('tendering.company_name', 'Company Name')}
            </label>
            <input
              type="text"
              value={manualCompany}
              onChange={(e) => setManualCompany(e.target.value)}
              placeholder={t('tendering.company_placeholder', 'e.g. Schmidt Bau GmbH')}
              className={fieldCls}
            />
          </div>
          <div className="flex-1">
            <label className="mb-1 block text-xs text-content-secondary">
              {t('tendering.contact_email', 'Contact Email')}
            </label>
            <input
              type="email"
              value={manualEmail}
              onChange={(e) => setManualEmail(e.target.value)}
              placeholder="contact@example.com"
              className={fieldCls}
            />
          </div>
          <Button
            variant="secondary"
            disabled={!manualCompany.trim() || !manualEmail.trim() || addMutation.isPending}
            loading={addMutation.isPending}
            onClick={() =>
              addMutation.mutate({ company_name: manualCompany.trim(), email: manualEmail.trim() })
            }
          >
            {t('tendering.add_recipient', { defaultValue: 'Add' })}
          </Button>
          <Button
            variant="ghost"
            icon={<Users size={14} />}
            onClick={() => setPickerOpen(true)}
            type="button"
          >
            {t('tendering.select_from_subs', 'Select from Subcontractors')}
          </Button>
        </div>

        {/* Recipient rows */}
        <div className="mt-4">
          {recipientsQ.isLoading ? (
            <SkeletonTable rows={3} columns={3} />
          ) : recipients.length === 0 ? (
            <EmptyState
              icon={<Inbox size={22} />}
              title={t('tendering.no_recipients', { defaultValue: 'No recipients yet' })}
              description={t('tendering.no_recipients_desc', {
                defaultValue: 'Add subcontractors above, then send the package out.',
              })}
            />
          ) : (
            <div className="divide-y divide-border-light rounded-lg border border-border-light">
              {recipients.map((r: Recipient) => (
                <div key={r.id} className="flex items-center gap-3 px-3 py-2.5">
                  <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-surface-secondary text-content-tertiary">
                    <Building2 size={14} />
                  </div>
                  <div className="min-w-0 flex-1">
                    <span className="block truncate text-sm font-medium text-content-primary">
                      {r.company_name}
                    </span>
                    <span className="block truncate text-xs text-content-tertiary">{r.email}</span>
                    {r.status === 'failed' && r.last_error && (
                      <span className="block truncate text-xs text-semantic-error">{r.last_error}</span>
                    )}
                    {r.status === 'sent' && r.sent_at && (
                      <span className="block truncate text-xs text-content-tertiary">
                        {t('tendering.recipient_sent_at', {
                          defaultValue: 'Sent {{date}}',
                          date: formatDate(r.sent_at),
                        })}
                      </span>
                    )}
                  </div>
                  <RecipientStatusBadge status={r.status} />
                  <button
                    type="button"
                    aria-label={t('tendering.remove_recipient', { defaultValue: 'Remove recipient' })}
                    title={t('tendering.remove_recipient', { defaultValue: 'Remove recipient' })}
                    className="shrink-0 rounded-md p-1.5 text-content-tertiary transition-colors hover:bg-semantic-error-bg/40 hover:text-semantic-error disabled:opacity-50"
                    disabled={removeMutation.isPending}
                    onClick={async () => {
                      const ok = await confirm({
                        title: t('tendering.remove_recipient', { defaultValue: 'Remove recipient' }),
                        message: t('tendering.remove_recipient_confirm', {
                          defaultValue: 'Remove {{company}} from the distribution list?',
                          company: r.company_name,
                        }),
                        variant: 'warning',
                      });
                      if (ok) removeMutation.mutate(r.id);
                    }}
                  >
                    <Trash2 size={15} />
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Optional cover message + send */}
        {recipients.length > 0 && (
          <div className="mt-4 space-y-3">
            <div>
              <label className="mb-1 block text-xs text-content-secondary">
                {t('tendering.cover_message', { defaultValue: 'Cover message (optional)' })}
              </label>
              <textarea
                value={message}
                onChange={(e) => setMessage(e.target.value)}
                rows={2}
                className="w-full rounded-lg border border-border bg-surface-primary px-3 py-2 text-sm text-content-primary placeholder:text-content-tertiary transition-all focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue resize-none"
                placeholder={t('tendering.cover_message_placeholder', {
                  defaultValue: 'Add a short note to include in the invitation email…',
                })}
              />
            </div>
            <div className="flex items-center gap-2">
              <Button
                variant="primary"
                icon={<Send size={14} />}
                loading={distributeMutation.isPending}
                onClick={() => distributeMutation.mutate(false)}
              >
                {t('tendering.distribute', { defaultValue: 'Send to recipients' })}
              </Button>
              {recipients.some((r) => r.status === 'sent') && (
                <Button
                  variant="ghost"
                  loading={distributeMutation.isPending}
                  onClick={() => distributeMutation.mutate(true)}
                  title={t('tendering.resend_all_title', {
                    defaultValue: 'Re-send to everyone, including those already sent',
                  })}
                >
                  {t('tendering.resend_all', { defaultValue: 'Re-send all' })}
                </Button>
              )}
            </div>
          </div>
        )}

        {/* Last run summary */}
        {lastResult && (
          <div className="mt-4 rounded-lg border border-border-light bg-surface-secondary/40 p-3 text-xs text-content-secondary">
            <div className="flex flex-wrap items-center gap-3">
              <span className="inline-flex items-center gap-1 text-semantic-success">
                <CheckCircle2 size={13} /> {lastResult.sent_count}{' '}
                {t('tendering.recipient_sent', { defaultValue: 'Sent' })}
              </span>
              {lastResult.failed_count > 0 && (
                <span className="inline-flex items-center gap-1 text-semantic-error">
                  <XCircle size={13} /> {lastResult.failed_count}{' '}
                  {t('tendering.recipient_failed', { defaultValue: 'Failed' })}
                </span>
              )}
              {lastResult.skipped_count > 0 && (
                <span className="inline-flex items-center gap-1">
                  <Minus size={13} /> {lastResult.skipped_count}{' '}
                  {t('tendering.recipient_skipped', { defaultValue: 'Skipped' })}
                </span>
              )}
              <span className="text-content-tertiary">
                {t('tendering.distribute_backend', {
                  defaultValue: 'via {{backend}}',
                  backend: lastResult.backend,
                })}
              </span>
            </div>
            {!lastResult.smtp_configured && (
              <p className="mt-2 text-content-tertiary">
                {t('tendering.distribute_console', {
                  defaultValue:
                    'SMTP is not configured, so emails were logged to the server console (dev mode). Set SMTP_HOST for real delivery.',
                })}
              </p>
            )}
          </div>
        )}
      </Card>

      {pickerOpen && (
        <SubcontractorPickerModal
          onPick={(sub, resolvedEmail) => {
            if (!resolvedEmail) {
              addToast({
                type: 'info',
                title: t('tendering.sub_no_email', {
                  defaultValue: 'No contact email on file - enter one if needed.',
                }),
              });
              setManualCompany(sub.legal_name);
              return;
            }
            addMutation.mutate({
              company_name: sub.legal_name,
              email: resolvedEmail,
              subcontractor_id: sub.id,
            });
          }}
          onClose={() => setPickerOpen(false)}
        />
      )}
      <ConfirmDialog {...confirmProps} />
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
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const { confirm, ...confirmProps } = useConfirm();
  const [showAddBid, setShowAddBid] = useState(false);
  // Sub-tab on the package detail view — bids/comparison ↔ distribution ↔
  // addenda ↔ leveling matrix ↔ award record. Defaults to "bids" so existing
  // muscle memory keeps working; the other tabs are additive. The award record
  // only loads when its tab is opened, so a package nobody keeps a record for
  // costs no request and stores nothing.
  const [activeTab, setActiveTab] = useState<
    'bids' | 'distribution' | 'addenda' | 'leveling' | 'award-record'
  >('bids');

  // Fetch package with bids
  const { data: pkg, isLoading: pkgLoading, isError: pkgError } = useQuery({
    queryKey: ['tendering-package', packageId],
    queryFn: () => apiGet<PackageWithBids>(`/v1/tendering/packages/${packageId}`),
  });

  // Which part of the bill this package was raised over. Levelling already
  // narrows to it, so a reader comparing bids is comparing them over this
  // scope whether or not anyone told them what it is.
  const { data: scope } = useQuery({
    queryKey: ['tendering-package-scope', packageId],
    queryFn: () => getPackageScope(packageId),
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
      // The award also writes rates back to the BOQ and the procurement
      // module auto-creates a draft PO from the winning bid. Tell the user
      // about the PO and offer a one-click jump to Procurement so the
      // hand-off is visible instead of silent.
      addToast(
        {
          type: 'success',
          title: t('toasts.bid_awarded', { defaultValue: 'Bid awarded' }),
          message: t('tendering.po_created_msg', {
            defaultValue: 'A draft purchase order is being prepared in Procurement from the winning bid.',
          }),
          action: {
            label: t('tendering.view_po', { defaultValue: 'View purchase orders' }),
            onClick: () => navigate('/procurement'),
          },
        },
        { duration: 8000 },
      );
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
    // RFC-4180 escaping: wrap fields containing comma/quote/newline in
    // double quotes and double any embedded quotes, so company names or
    // descriptions with commas don't shift the columns.
    const esc = (v: string | number) => {
      const s = String(v);
      return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
    };
    const rateSuffix = t('tendering.export_rate_suffix', { defaultValue: 'Rate' });
    const headers = [
      t('tendering.position', 'Position'),
      t('tendering.export_unit', { defaultValue: 'Unit' }),
      t('tendering.export_budget_rate', { defaultValue: 'Budget Rate' }),
      ...comparison.bid_totals.map((bt) => `${bt.company_name} ${rateSuffix}`),
    ];
    const rows = comparison.rows.map(row => [
      row.description,
      row.unit,
      Number(row.budget_rate).toFixed(2),
      ...row.bids.map(b => Number(b.unit_rate).toFixed(2)),
    ]);
    const footer = [
      t('tendering.total', 'TOTAL'),
      '',
      Number(comparison.budget_total).toFixed(0),
      ...comparison.bid_totals.map(bt => Number(bt.total).toFixed(0)),
    ];
    const csv = [headers, ...rows, footer].map(r => r.map(esc).join(',')).join('\n');
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

  // Award / rejection decision documents — generated server-side as PDFs
  // (reportlab), fetched with the Bearer token like the tender summary PDF.
  const handleDownloadDecisionDoc = useCallback(
    async (bidId: string, kind: 'award-letter' | 'rejection-letter', company: string) => {
      try {
        const token = getAuthToken();
        const r = await fetch(
          `/api/v1/tendering/packages/${packageId}/bids/${bidId}/${kind}/pdf/`,
          { headers: token ? { Authorization: `Bearer ${token}` } : {} },
        );
        if (!r.ok) {
          addToast({ type: 'error', title: t('tendering.export_failed', { defaultValue: 'Export failed' }) });
          return;
        }
        const blob = await r.blob();
        const safeCompany = company.replace(/[^a-z0-9_-]+/gi, '_') || 'bidder';
        const prefix = kind === 'award-letter' ? 'award_letter' : 'rejection_notice';
        triggerDownload(blob, `${prefix}_${safeCompany}.pdf`);
      } catch {
        addToast({ type: 'error', title: t('tendering.export_failed', { defaultValue: 'Export failed' }) });
      }
    },
    [packageId, addToast, t],
  );

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
            {/* A package over one trade is compared against that trade, not
                against the whole bill. That was already true of the numbers
                and invisible on the screen. */}
            {scope && !scope.covers_whole_bill && scope.sections.length > 0 && (
              <p
                className="mt-2 text-xs text-content-tertiary"
                title={
                  scope.sections_recorded
                    ? undefined
                    : t('tendering.scope_derived_hint', {
                        defaultValue:
                          'This package records the lines it covers rather than the sections, so the sections are read from those lines.',
                      })
                }
              >
                {t('tendering.scope_partial', {
                  defaultValue:
                    'Covers part of the bill: {{sections}} ({{included}} of {{total}} positions)',
                  sections: fmtList(scope.sections
                    .map((s) => [s.ordinal, s.description].filter(Boolean).join(' '))),
                  included: scope.included_position_count,
                  total: scope.boq_position_count,
                })}
              </p>
            )}
          </div>
          <div className="flex items-center gap-2">
            {/* An awarded or closed tender is decided: the server refuses a
                new bid there, so the button is not offered. */}
            {pkg.status !== 'awarded' && pkg.status !== 'closed' && (
              <Button
                variant="secondary"
                size="sm"
                icon={<Plus size={14} />}
                onClick={() => setShowAddBid(true)}
              >
                {t('tendering.add_bid', 'Add Bid')}
              </Button>
            )}
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
            {/* CONN-40: once a tender is awarded, take the winning scope into
                Contracts instead of dead-ending. The awarded rates already
                live on the BOQ, so the contract is formalised downstream. */}
            {pkg.status === 'awarded' && (
              <Button
                variant="primary"
                size="sm"
                icon={<ArrowRight size={14} />}
                onClick={() => navigate('/contracts')}
                title={t('tendering.formalise_contract_title', {
                  defaultValue: 'Open Contracts to formalise the awarded scope',
                })}
              >
                {t('tendering.formalise_contract', 'Formalise as Contract')}
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

      {/* Sub-tab strip — integrated-5D-estimating-suite-style: bids ↔ addenda ↔ leveling.
          Addenda (``/packages/{id}/addenda/``) and Leveling
          (``/packages/{id}/leveling-matrix/`` + ``/level-bids/``) are now
          backed by real endpoints on tendering/router.py, so the tabs are
          always shown. */}
      <div className="flex items-center gap-1 border-b border-border-light">
        {([
          { id: 'bids' as const, label: t('tendering.tab_bids', 'Bids & Comparison') },
          { id: 'distribution' as const, label: t('tendering.tab_distribution', { defaultValue: 'Distribution' }) },
          { id: 'addenda' as const, label: t('tendering.tab_addenda', 'Addenda') },
          { id: 'leveling' as const, label: t('tendering.tab_leveling', 'Leveling') },
          {
            id: 'award-record' as const,
            label: t('tendering.tab_award_record', { defaultValue: 'Award record' }),
          },
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
                    <span className="ml-2 text-xs text-content-tertiary items-center gap-1 inline-flex">
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
                {/* Decision documents — award letter for the winner, rejection
                    notice for the others, once a winner has been chosen. */}
                {bid.status === 'accepted' && (
                  <Button
                    variant="ghost"
                    size="sm"
                    icon={<FileText size={14} />}
                    onClick={() => handleDownloadDecisionDoc(bid.id, 'award-letter', bid.company_name)}
                    title={t('tendering.award_letter_title', {
                      defaultValue: 'Download the letter of award (PDF)',
                    })}
                  >
                    {t('tendering.award_letter', { defaultValue: 'Award letter' })}
                  </Button>
                )}
                {bid.status === 'rejected' && (
                  <Button
                    variant="ghost"
                    size="sm"
                    icon={<FileText size={14} />}
                    onClick={() => handleDownloadDecisionDoc(bid.id, 'rejection-letter', bid.company_name)}
                    title={t('tendering.rejection_letter_title', {
                      defaultValue: 'Download the rejection notice (PDF)',
                    })}
                  >
                    {t('tendering.rejection_letter', { defaultValue: 'Rejection notice' })}
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

      {/* Distribution sub-tab */}
      {activeTab === 'distribution' && <DistributionPanel packageId={packageId} />}

      {/* Addenda sub-tab */}
      {activeTab === 'addenda' && <AddendumList packageId={packageId} />}

      {/* Leveling matrix sub-tab */}
      {activeTab === 'leveling' && (
        <LevelingMatrix packageId={packageId} currency={currency} />
      )}

      {/* Award record sub-tab — the written record of how this award was
          reached, assembled from the procedure. Mounted (and therefore
          fetched) only when the tab is opened. */}
      {activeTab === 'award-record' && <AwardRecordPanel packageId={packageId} />}

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
              ? t('tendering.confidence_low', 'Low confidence - review carefully')
              : t('tendering.confidence_medium', 'Medium confidence');
        const reasonText: Record<typeof reasonKey, string> = {
          single_bid: t('tendering.reason_single_bid', 'Only one eligible bid received.'),
          clear_winner: t('tendering.reason_clear_winner', 'Clearly the lowest competitive offer.'),
          narrow_gap: t('tendering.reason_narrow_gap', 'Winner and runner-up are within 2% - consider non-price factors.'),
          suspicious_low: t('tendering.reason_suspicious_low', 'Lowest bid is {{pct}}% below the median - verify scope and pricing before awarding.', { pct: belowMedianPct }),
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

/* ── How-it-works flow + module integrations ───────────────────────────── */

/** A compact inline link to a sibling module (keeps the flow copy readable). */
function ModLink({ to, children }: { to: string; children: ReactNode }) {
  return (
    <Link to={to} className="font-medium text-oe-blue-text hover:underline">
      {children}
    </Link>
  );
}

/**
 * One-glance explainer: what tendering does and how it connects to the rest of
 * the platform. A priced BOQ is packaged, issued to subcontractors, their bids
 * are collected and compared, and the winner is awarded, which writes rates
 * back to the BOQ and formalises a contract. Every connected module is a link.
 */
function HowTenderingWorks() {
  const { t } = useTranslation();

  const steps: { icon: ReactNode; title: string; desc: string }[] = [
    {
      icon: <Package size={14} className="text-oe-blue" />,
      title: t('tendering.how_step1_title', { defaultValue: 'Package from BOQ' }),
      desc: t('tendering.how_step1_desc', {
        defaultValue: 'Bundle priced BOQ positions into a bid package to take to market.',
      }),
    },
    {
      icon: <Send size={14} className="text-oe-blue" />,
      title: t('tendering.how_step2_title', { defaultValue: 'Issue to subcontractors' }),
      desc: t('tendering.how_step2_desc', {
        defaultValue: 'Send the package to a distribution list of subcontractors to invite offers.',
      }),
    },
    {
      icon: <Inbox size={14} className="text-oe-blue" />,
      title: t('tendering.how_step3_title', { defaultValue: 'Collect bids' }),
      desc: t('tendering.how_step3_desc', {
        defaultValue: 'Gather offers as they come in, each priced against the same scope.',
      }),
    },
    {
      icon: <BarChart3 size={14} className="text-oe-blue" />,
      title: t('tendering.how_step4_title', { defaultValue: 'Compare & level' }),
      desc: t('tendering.how_step4_desc', {
        defaultValue: 'Line offers up side by side, flag outliers and level the scope.',
      }),
    },
    {
      icon: <Award size={14} className="text-oe-blue" />,
      title: t('tendering.how_step5_title', { defaultValue: 'Award' }),
      desc: t('tendering.how_step5_desc', {
        defaultValue: 'Award the winner; rates write back to the BOQ and a contract follows.',
      }),
    },
  ];

  return (
    <CollapsibleSection
      storageKey="tendering.how"
      icon={<Network size={15} className="text-oe-blue" />}
      title={t('tendering.how_title', { defaultValue: 'How tendering fits together' })}
      subtitle={t('tendering.how_subtitle', {
        defaultValue: 'From a priced BOQ to an awarded contract, in five steps',
      })}
    >
      <p className="text-xs text-content-tertiary">
        {t('tendering.how_intro', {
          defaultValue:
            'Take a priced BOQ to market: package the work, invite subcontractors, compare their offers and award the winner, which writes the agreed rates back to the BOQ.',
        })}
      </p>

      <ol className="mt-3 flex flex-col gap-2 lg:flex-row lg:items-stretch">
        {steps.map((s, i) => (
          <Fragment key={s.title}>
            <li className="flex-1 rounded-lg border border-border-light bg-surface-primary p-3">
              <div className="flex items-center gap-2">
                <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-lg bg-oe-blue-subtle">
                  {s.icon}
                </span>
                <span className="text-xs font-semibold text-content-primary">{s.title}</span>
              </div>
              <p className="mt-1.5 text-2xs leading-relaxed text-content-tertiary">{s.desc}</p>
            </li>
            {i < steps.length - 1 && (
              <li
                aria-hidden="true"
                className="hidden shrink-0 items-center self-center text-content-quaternary lg:flex"
              >
                <ArrowRight size={16} />
              </li>
            )}
          </Fragment>
        ))}
      </ol>

      <div className="mt-3 border-t border-border-light pt-3 text-2xs text-content-tertiary">
        <span className="font-medium text-content-secondary">
          {t('tendering.how_connects', { defaultValue: 'Connects with:' })}
        </span>{' '}
        <ModLink to="/boq">{t('tendering.how_mod_boq', { defaultValue: 'BOQ' })}</ModLink> ·{' '}
        <ModLink to="/subcontractors">
          {t('tendering.how_mod_subs', { defaultValue: 'Subcontractors' })}
        </ModLink>{' '}
        ·{' '}
        <ModLink to="/contracts">
          {t('tendering.how_mod_contracts', { defaultValue: 'Contracts' })}
        </ModLink>{' '}
        ·{' '}
        <ModLink to="/reports">{t('tendering.how_mod_reports', { defaultValue: 'Reports' })}</ModLink>
      </div>
    </CollapsibleSection>
  );
}

/* ── Main Page ─────────────────────────────────────────────────────────── */

export function TenderingPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { activeProjectId } = useProjectContextStore();

  const selectedProjectId = activeProjectId ?? '';
  const [selectedPackageId, setSelectedPackageId] = useState('');
  const [showCreateDialog, setShowCreateDialog] = useState(false);
  const [searchParams, setSearchParams] = useSearchParams();
  const deepLinkPackageId = searchParams.get('package');

  // Fetch projects — used to resolve the active project's name + currency.
  // Project SELECTION happens in the global top bar, not here.
  const { data: projects } = useQuery({
    queryKey: ['projects'],
    queryFn: () => fetchProjectList<Project[]>(),
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

  // Consume a ?package=<id> deep link (e.g. from "Send to tender" in the BOQ
  // editor): open that package once it appears in the loaded list, then drop
  // the param so a later manual selection is not overridden on re-render.
  useEffect(() => {
    if (!deepLinkPackageId) return;
    if (packages?.some((p) => p.id === deepLinkPackageId)) {
      setSelectedPackageId(deepLinkPackageId);
      setSearchParams(
        (prev) => {
          prev.delete('package');
          return prev;
        },
        { replace: true },
      );
    }
  }, [deepLinkPackageId, packages, setSearchParams]);

  const selectedProject = useMemo(
    () => projects?.find((p) => p.id === selectedProjectId),
    [projects, selectedProjectId],
  );

  // Currency comes from the selected project — never hardcoded (task #217).
  // Empty string when the project has none; formatCurrency then renders a
  // symbol-less number rather than mislabelling amounts as EUR.
  const currency = selectedProject?.currency || '';

  // Module Insights - the toggleable visualization panel for this module. Its
  // charts are built client-side from the packages already loaded; when the
  // project has none the panel draws nothing rather than inventing rows to fill
  // it. Open state and any user-built charts persist per module via
  // useModuleInsights.
  const insights = useModuleInsights('tendering', { defaultOpen: true });
  const { datasets: insightDatasets, builtins: insightBuiltins } = useMemo(
    () => buildTenderingInsights(packages ?? [], currency, t),
    [packages, currency, t],
  );

  const handlePackageCreated = useCallback(() => {
    queryClient.invalidateQueries({
      queryKey: ['tendering-packages', selectedProjectId],
    });
  }, [queryClient, selectedProjectId]);

  return (
    <div className="space-y-5 animate-fade-in">
      <Breadcrumb items={[
        ...(selectedProject ? [{ label: selectedProject.name, to: `/projects/${selectedProject.id}` }] : []),
        { label: t('tendering.title', 'Tendering') },
      ]} />

      {/* Header — project selection lives in the global top bar; the page
          reads the shared project context, so there is no in-page project
          picker. */}
      <PageHeader
        srTitle={t('tendering.title', 'Tendering')}
        subtitle={t(
          'tendering.subtitle',
          'Manage bid packages, collect and compare subcontractor offers',
        )}
        actions={
          <>
            {/* Insights toggle - shows or hides this module's visualization
                panel. Leads the cluster so charts are one obvious click away. */}
            <InsightsToggleButton open={insights.open} onClick={insights.toggle} />
            {/* How it works guide - explains the package -> issue -> collect ->
                compare -> award flow. Leads the action cluster as the help pill;
                the CTA opens the New Tender Package dialog. */}
            <ModuleGuideButton
              content={tenderingGuide}
              onCta={() => {
                if (selectedProjectId) setShowCreateDialog(true);
              }}
            />
            <span title={!selectedProjectId ? t('tendering.select_project_first', { defaultValue: 'Select a project first' }) : undefined}>
              <Button
                variant="primary"
                icon={<Plus size={16} />}
                disabled={!selectedProjectId}
                onClick={() => setShowCreateDialog(true)}
                data-guide="tendering-new"
              >
                {t('tendering.new_package', 'New Tender Package')}
              </Button>
            </span>
          </>
        }
      />

      {/* Module Insights panel - toggled by the header button. Placed high and
          before the no-project gate so its charts are visible the moment the
          module opens. */}
      <InsightsPanel
        open={insights.open}
        title={t('tendering.insights.title', { defaultValue: 'Tendering insights' })}
        datasets={insightDatasets}
        builtins={insightBuiltins}
        custom={insights.custom}
        onAdd={insights.addCustom}
        onUpdate={insights.updateCustom}
        onRemove={insights.removeCustom}
        onCollapse={() => insights.setOpen(false)}
      />

      {/* Workflow explanation */}
      <DismissibleInfo
        storageKey="tendering"
        title={t('tendering.intro_title', {
          defaultValue: 'Take a priced BOQ to market and back',
        })}
        more={
          t('tendering.intro_more', { defaultValue: '' })
            ? <IntroRichText text={t('tendering.intro_more')} />
            : undefined
        }
        links={[
          {
            label: t('nav.boq', { defaultValue: 'BOQ' }),
            onClick: () => navigate('/boq'),
          },
          {
            label: t('nav.procurement', { defaultValue: 'Procurement' }),
            onClick: () => navigate('/procurement'),
          },
          {
            label: t('nav.contracts', { defaultValue: 'Contracts' }),
            onClick: () => navigate('/contracts'),
          },
          {
            label: t('nav.bid_management', { defaultValue: 'Bid Management' }),
            onClick: () => navigate('/bid-management'),
          },
        ]}
      >
        {t('tendering.intro_body', {
          defaultValue:
            'Build bid packages straight from a project BOQ, issue them to subcontractors, and compare offers side by side through Draft, Issued, Collecting, Evaluating and Awarded. Awarding a winner writes the agreed rates back to the BOQ and drafts a purchase order in Procurement, which is what sets this apart from the subcontractor-package flow in Bid Management.',
        })}
      </DismissibleInfo>

      <HowTenderingWorks />

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
        <div data-guide="tendering-packages">
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
