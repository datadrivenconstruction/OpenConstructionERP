// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction

import { useState, useMemo, useCallback, useEffect, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import clsx from 'clsx';
import {
  FileText,
  Plus,
  Search,
  X,
  Loader2,
  Send,
  Trophy,
  BarChart3,
  Clock,
  CheckCircle2,
} from 'lucide-react';
import { Link, useSearchParams } from 'react-router-dom';
import { PROCUREMENT_LINK, purchaseOrderDeepLink } from '@/shared/lib/awardChainLinks';
import { RelatedRecordLink } from '@/shared/ui/RelatedRecordLink';
import { fmtDate } from '@/shared/lib/formatters';
import { Badge, CollapsibleSection, ConfirmDialog, EmptyState, StatCard, Button } from '@/shared/ui';
import { useConfirm } from '@/shared/hooks/useConfirm';
import type { BadgeVariant } from '@/shared/ui';
import { PageHeader } from '@/shared/ui/PageHeader';
import { TabBar, tabIds } from '@/shared/ui/TabBar';
import type { TabBarTab } from '@/shared/ui/TabBar';
import { MoneyDisplay } from '@/shared/ui/MoneyDisplay';
import { useActiveProjectId } from '@/shared/hooks/useActiveProjectId';
import { useToastStore } from '@/stores/useToastStore';
import { fetchContacts, type Contact } from '@/features/contacts/api';
import {
  fetchRFQs,
  createRFQ,
  issueRFQ,
  deleteRFQ,
  fetchComparison,
  awardBid,
  type RFQ,
  type RFQStatus,
  RFQ_OPEN_STATUSES,
  RFQ_AWARDED_STATUSES,
  RFQ_FILTER_STATUSES,
  type RFQCreatePayload,
  type ComparisonResponse,
  type QuoteComparison,
} from './api';
import { useRfqAwardOrders, type RfqOrderLookup } from './useRfqAwardOrders';
import type { AwardLookup, AwardOrderLite } from '@/shared/hooks/useAwardOutcome';

/** A bidder is stored as a contact id; this is how the page names it. */
type BidderName = (contactId: string) => string;

function contactDisplayName(contact: Contact | undefined): string | null {
  if (!contact) return null;
  return (
    contact.company_name ||
    contact.legal_name ||
    [contact.first_name, contact.last_name].filter(Boolean).join(' ') ||
    null
  );
}

/* ── Status badge mapping ─────────────────────────────────────────────── */

const STATUS_BADGE: Record<RFQStatus, BadgeVariant> = {
  draft: 'neutral',
  published: 'blue',
  bids_received: 'purple',
  awarded: 'success',
  po_issued: 'success',
  completed: 'neutral',
  cancelled: 'error',
  issued: 'blue',
  evaluating: 'purple',
  closed: 'neutral',
};

function statusLabel(status: RFQStatus, t: (k: string, o?: Record<string, unknown>) => string): string {
  const labels: Record<RFQStatus, string> = {
    draft: t('rfq_bidding.status_draft', { defaultValue: 'Draft' }),
    // The page's own verb for publishing is "Issue", so the published status
    // reads as issued, under the key already translated for it.
    published: t('rfq_bidding.status_issued', { defaultValue: 'Issued' }),
    bids_received: t('rfq_bidding.status_bids_received', { defaultValue: 'Bids received' }),
    awarded: t('rfq_bidding.status_awarded', { defaultValue: 'Awarded' }),
    po_issued: t('rfq_bidding.status_po_issued', { defaultValue: 'PO issued' }),
    completed: t('rfq_bidding.status_completed', { defaultValue: 'Completed' }),
    cancelled: t('rfq_bidding.status_cancelled', { defaultValue: 'Cancelled' }),
    issued: t('rfq_bidding.status_issued', { defaultValue: 'Issued' }),
    evaluating: t('rfq_bidding.status_evaluating', { defaultValue: 'Evaluating' }),
    closed: t('rfq_bidding.status_closed', { defaultValue: 'Closed' }),
  };
  return labels[status] ?? status;
}

/* ── Tab identifiers ──────────────────────────────────────────────────── */

type RFQTab = 'list' | 'comparison' | 'awards';

const TAB_IDS = tabIds('rfq-bidding');

/* ── Explainer ────────────────────────────────────────────────────────── */

function RFQBiddingExplainer() {
  const { t } = useTranslation();

  const steps = [
    {
      num: 1,
      title: t('rfq_bidding.flow_step_1', { defaultValue: 'Draft the RFQ' }),
      desc: t('rfq_bidding.flow_step_1_desc', {
        defaultValue:
          'Describe the scope, set a due date and list the vendors you want to invite. The RFQ stays in draft until you are ready.',
      }),
    },
    {
      num: 2,
      title: t('rfq_bidding.flow_step_2', { defaultValue: 'Issue to vendors' }),
      desc: t('rfq_bidding.flow_step_2_desc', {
        defaultValue:
          'Issue the RFQ and vendors receive an invitation to bid. They submit pricing against each scope line before the due date.',
      }),
    },
    {
      num: 3,
      title: t('rfq_bidding.flow_step_3', { defaultValue: 'Compare bids' }),
      desc: t('rfq_bidding.flow_step_3_desc', {
        defaultValue:
          'Open the comparison matrix to see every vendor side by side, line by line. The lowest total is highlighted automatically.',
      }),
    },
    {
      num: 4,
      title: t('rfq_bidding.flow_step_4', { defaultValue: 'Award and track' }),
      desc: t('rfq_bidding.flow_step_4_desc', {
        defaultValue:
          'Select the winning bid, and the award is recorded with the vendor, amount and date. Past awards are available for audit on the Awards tab.',
      }),
    },
  ];

  return (
    <CollapsibleSection
      storageKey="rfq_bidding.how"
      icon={<FileText size={15} className="text-oe-blue" />}
      title={t('rfq_bidding.flow_title', { defaultValue: 'How RFQ bidding works' })}
    >
      <p className="text-xs text-content-tertiary">
        {t('rfq_bidding.flow_intro', {
          defaultValue:
            'Create a request for quotation, send it to vendors, collect and compare their bids, then award the best offer - all in one place.',
        })}
      </p>
      <ol className="mt-3 space-y-2">
        {steps.map((s) => (
          <li key={s.num} className="flex gap-3 text-xs">
            <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-oe-blue/10 text-[10px] font-bold text-oe-blue-text">
              {s.num}
            </span>
            <div>
              <span className="font-medium text-content-primary">{s.title}</span>
              <span className="text-content-tertiary"> - {s.desc}</span>
            </div>
          </li>
        ))}
      </ol>
      <div className="mt-3 border-t border-border-light pt-3 text-2xs text-content-tertiary">
        <span className="font-medium text-content-secondary">
          {t('rfq_bidding.flow_related', { defaultValue: 'Related:' })}
        </span>{' '}
        <Link to="/tendering" className="font-medium text-oe-blue-text hover:underline">
          {t('rfq_bidding.mod_tendering', { defaultValue: 'Tendering' })}
        </Link>
        {' · '}
        <Link to="/bid-management" className="font-medium text-oe-blue-text hover:underline">
          {t('rfq_bidding.mod_bid_management', { defaultValue: 'Bid Management' })}
        </Link>
        {' · '}
        <Link to="/contracts" className="font-medium text-oe-blue-text hover:underline">
          {t('rfq_bidding.mod_contracts', { defaultValue: 'Contracts' })}
        </Link>
        {' · '}
        <Link to="/subcontractors" className="font-medium text-oe-blue-text hover:underline">
          {t('rfq_bidding.mod_subcontractors', { defaultValue: 'Subcontractors' })}
        </Link>
        {' · '}
        <Link to={PROCUREMENT_LINK} className="font-medium text-oe-blue-text hover:underline">
          {t('rfq_bidding.mod_procurement', { defaultValue: 'Procurement' })}
        </Link>
      </div>
    </CollapsibleSection>
  );
}

/* ── Page component ───────────────────────────────────────────────────── */

export function RFQBiddingPage() {
  const { t } = useTranslation();
  const projectId = useActiveProjectId();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);

  // Tab state
  const [activeTab, setActiveTab] = useState<RFQTab>('list');

  // Search / filter
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState<RFQStatus | ''>('');

  // Dialog state
  const [showCreate, setShowCreate] = useState(false);

  // Comparison selection
  const [comparisonRfqId, setComparisonRfqId] = useState<string | null>(null);

  // The RFQ awarded on this screen, so the Awards tab keeps looking for the
  // purchase order its award drafts until that order appears.
  const [justAwardedRfqId, setJustAwardedRfqId] = useState<string | null>(null);

  // `?rfq=<id>` opens the register on one RFQ: the tab it lives on, marked.
  // A purchase order drafted from an award links back here this way.
  const [searchParams] = useSearchParams();
  const focusRfqId = searchParams.get('rfq');
  const appliedFocusRef = useRef<string | null>(null);

  // ── Data fetching ─────────────────────────────────────────────────────

  const { data: rfqPage, isLoading: rfqLoading, error: rfqError } = useQuery({
    queryKey: ['rfq-bidding', projectId, statusFilter],
    queryFn: () => fetchRFQs(projectId || undefined, statusFilter || undefined),
    enabled: !!projectId,
    staleTime: 30_000,
  });

  const rfqs = rfqPage?.items ?? [];
  const rfqTotal = rfqPage?.total ?? 0;

  // Every RFQ in the list carries its own bids, so the awards need no second
  // request. Bidders are contact ids; one shared page of contacts names them,
  // and an id that is not on it is shown as it is rather than hidden.
  const { data: contactsPage } = useQuery({
    queryKey: ['rfq-bidding', 'bidder-contacts'],
    queryFn: () => fetchContacts({ limit: 500 }),
    enabled: !!projectId,
    staleTime: 5 * 60_000,
  });

  const bidderName = useCallback<BidderName>(
    (contactId) =>
      contactDisplayName((contactsPage?.items ?? []).find((c) => c.id === contactId)) ?? contactId,
    [contactsPage],
  );

  const { data: comparison, isLoading: comparisonLoading } = useQuery({
    queryKey: ['rfq-bidding-comparison', comparisonRfqId],
    queryFn: () => fetchComparison(comparisonRfqId!),
    enabled: !!comparisonRfqId,
    staleTime: 30_000,
  });

  // ── Statistics ────────────────────────────────────────────────────────

  const stats = useMemo(() => {
    const total = rfqs.length;
    const open = rfqs.filter((r) => RFQ_OPEN_STATUSES.has(r.status)).length;
    const awarded = rfqs.filter((r) => RFQ_AWARDED_STATUSES.has(r.status)).length;
    return { total, open, awarded };
  }, [rfqs]);

  // ── Filtered list ─────────────────────────────────────────────────────

  const filtered = useMemo(() => {
    if (!search) return rfqs;
    const q = search.toLowerCase();
    return rfqs.filter(
      (r) =>
        r.title.toLowerCase().includes(q) ||
        r.description?.toLowerCase().includes(q),
    );
  }, [rfqs, search]);

  // ── Award tracking data ───────────────────────────────────────────────

  const awardedRfqs = useMemo(
    () => rfqs.filter((r) => RFQ_AWARDED_STATUSES.has(r.status)),
    [rfqs],
  );

  // The purchase order each award drafted, read once for the whole tab.
  const orderFor = useRfqAwardOrders(
    projectId,
    activeTab === 'awards' && awardedRfqs.length > 0,
    justAwardedRfqId,
  );

  useEffect(() => {
    if (!focusRfqId || appliedFocusRef.current === focusRfqId) return;
    const target = rfqs.find((r) => r.id === focusRfqId);
    if (!target) return;
    appliedFocusRef.current = focusRfqId;
    setActiveTab(RFQ_AWARDED_STATUSES.has(target.status) ? 'awards' : 'list');
  }, [focusRfqId, rfqs]);

  // ── Mutations ─────────────────────────────────────────────────────────

  const createMutation = useMutation({
    mutationFn: (payload: RFQCreatePayload) => createRFQ(payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['rfq-bidding'] });
      setShowCreate(false);
      addToast({ type: 'success', title: t('rfq_bidding.created_success', { defaultValue: 'RFQ created successfully' }) });
    },
    onError: () => {
      addToast({ type: 'error', title: t('rfq_bidding.created_error', { defaultValue: 'Failed to create RFQ' }) });
    },
  });

  const issueMutation = useMutation({
    mutationFn: (id: string) => issueRFQ(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['rfq-bidding'] });
      addToast({ type: 'success', title: t('rfq_bidding.issued_success', { defaultValue: 'RFQ issued to vendors' }) });
    },
    onError: () => {
      addToast({ type: 'error', title: t('rfq_bidding.issued_error', { defaultValue: 'Failed to issue RFQ' }) });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => deleteRFQ(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['rfq-bidding'] });
      addToast({ type: 'success', title: t('rfq_bidding.deleted_success', { defaultValue: 'RFQ deleted' }) });
    },
    onError: () => {
      addToast({ type: 'error', title: t('rfq_bidding.deleted_error', { defaultValue: 'Failed to delete RFQ' }) });
    },
  });

  const awardMutation = useMutation({
    mutationFn: (bidId: string) => awardBid(bidId),
    onSuccess: (bid) => {
      setJustAwardedRfqId(bid?.rfq_id ?? null);
      queryClient.invalidateQueries({ queryKey: ['rfq-bidding'] });
      queryClient.invalidateQueries({ queryKey: ['rfq-bidding-comparison'] });
      addToast({ type: 'success', title: t('rfq_bidding.award_success', { defaultValue: 'Bid awarded successfully' }) });
    },
    onError: () => {
      addToast({ type: 'error', title: t('rfq_bidding.award_error', { defaultValue: 'Failed to award bid' }) });
    },
  });

  // ── Tabs definition ───────────────────────────────────────────────────

  const tabs: TabBarTab<RFQTab>[] = useMemo(() => [
    {
      id: 'list',
      label: t('rfq_bidding.tab_list', { defaultValue: 'RFQ List' }),
      icon: <FileText className="h-4 w-4" />,
      badge: rfqTotal > 0 ? (
        <Badge variant="neutral" size="sm">{rfqTotal}</Badge>
      ) : undefined,
    },
    {
      id: 'comparison',
      label: t('rfq_bidding.tab_comparison', { defaultValue: 'Bid Comparison' }),
      icon: <BarChart3 className="h-4 w-4" />,
    },
    {
      id: 'awards',
      label: t('rfq_bidding.tab_awards', { defaultValue: 'Awards' }),
      icon: <Trophy className="h-4 w-4" />,
      badge: stats.awarded > 0 ? (
        <Badge variant="success" size="sm">{stats.awarded}</Badge>
      ) : undefined,
    },
  ], [t, rfqTotal, stats.awarded]);

  // ── Handlers ──────────────────────────────────────────────────────────

  const handleCreateSubmit = useCallback(
    (payload: RFQCreatePayload) => {
      createMutation.mutate(payload);
    },
    [createMutation],
  );

  const { confirm, ...confirmProps } = useConfirm();

  // Issuing cannot be undone: the server deletes only drafts. An RFQ with no
  // scope lines gives vendors nothing to price, so it is not offered at all.
  const handleIssue = useCallback(
    async (rfq: RFQ) => {
      if ((rfq.lines?.length ?? 0) === 0) return;
      const ok = await confirm({
        title: t('rfq_bidding.issue_confirm_title', { defaultValue: 'Issue this RFQ?' }),
        message: t('rfq_bidding.issue_confirm_message', {
          defaultValue:
            'Vendors can bid once it is issued. An issued RFQ is no longer a draft and cannot be deleted.',
        }),
        confirmLabel: t('rfq_bidding.issue', { defaultValue: 'Issue' }),
        variant: 'warning',
      });
      if (ok) issueMutation.mutate(rfq.id);
    },
    [confirm, issueMutation, t],
  );

  // ── No-project guard (all hooks above) ────────────────────────────────

  if (!projectId) {
    return (
      <div className="mx-auto max-w-6xl space-y-5 px-4 py-6">
        <PageHeader
          srTitle={t('rfq_bidding.title', { defaultValue: 'RFQ Bidding' })}
          subtitle={t('rfq_bidding.subtitle', {
            defaultValue: 'Manage requests for quotation, compare bids and track awards',
          })}
        />
        <RFQBiddingExplainer />
        <EmptyState
          icon={<FileText className="h-12 w-12" />}
          title={t('rfq_bidding.no_project', { defaultValue: 'Select a project' })}
          description={t('rfq_bidding.no_project_desc', {
            defaultValue: 'Choose a project from the header to manage its RFQs.',
          })}
        />
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-6xl space-y-5 px-4 py-6">
      <PageHeader
        srTitle={t('rfq_bidding.title', { defaultValue: 'RFQ Bidding' })}
        subtitle={t('rfq_bidding.subtitle', {
          defaultValue: 'Manage requests for quotation, compare bids and track awards',
        })}
        actions={
          <Button variant="primary" onClick={() => setShowCreate(true)}>
            <Plus className="h-4 w-4" aria-hidden />
            {t('rfq_bidding.create', { defaultValue: 'New RFQ' })}
          </Button>
        }
      />

      {/* Statistics cards */}
      {!rfqLoading && rfqs.length > 0 && (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
          <StatCard
            label={t('rfq_bidding.stat_total', { defaultValue: 'Total RFQs' })}
            value={stats.total}
            icon={FileText}
            tone="blue"
          />
          <StatCard
            label={t('rfq_bidding.stat_open', { defaultValue: 'Open' })}
            value={stats.open}
            icon={Clock}
            tone="warning"
            tintValue={stats.open > 0}
          />
          <StatCard
            label={t('rfq_bidding.stat_awarded', { defaultValue: 'Awarded' })}
            value={stats.awarded}
            icon={Trophy}
            tone="success"
            tintValue={stats.awarded > 0}
          />
        </div>
      )}

      <RFQBiddingExplainer />

      {/* Tab bar */}
      <TabBar
        tabs={tabs}
        activeId={activeTab}
        onChange={setActiveTab}
        ariaLabel={t('rfq_bidding.tabs_label', { defaultValue: 'RFQ Bidding tabs' })}
      />

      {/* Tab panels */}
      {activeTab === 'list' && (
        <div
          role="tabpanel"
          id={TAB_IDS.panelId('list')}
          aria-labelledby={TAB_IDS.tabId('list')}
        >
          <RFQListPanel
            rfqs={filtered}
            isLoading={rfqLoading}
            error={rfqError}
            search={search}
            onSearchChange={setSearch}
            statusFilter={statusFilter}
            onStatusFilterChange={setStatusFilter}
            onIssue={handleIssue}
            onDelete={(id) => deleteMutation.mutate(id)}
            onSelectForComparison={(id) => {
              setComparisonRfqId(id);
              setActiveTab('comparison');
            }}
            focusRfqId={focusRfqId}
            t={t}
          />
        </div>
      )}

      {activeTab === 'comparison' && (
        <div
          role="tabpanel"
          id={TAB_IDS.panelId('comparison')}
          aria-labelledby={TAB_IDS.tabId('comparison')}
        >
          <ComparisonPanel
            rfqs={rfqs}
            selectedRfqId={comparisonRfqId}
            onSelectRfq={setComparisonRfqId}
            comparison={comparison ?? null}
            isLoading={comparisonLoading}
            onAward={(bidId) => awardMutation.mutate(bidId)}
            awarding={awardMutation.isPending}
            bidderName={bidderName}
            t={t}
          />
        </div>
      )}

      {activeTab === 'awards' && (
        <div
          role="tabpanel"
          id={TAB_IDS.panelId('awards')}
          aria-labelledby={TAB_IDS.tabId('awards')}
        >
          <AwardsPanel
            rfqs={awardedRfqs}
            bidderName={bidderName}
            orderFor={orderFor}
            focusRfqId={focusRfqId}
            t={t}
          />
        </div>
      )}

      {/* Create RFQ dialog */}
      {showCreate && (
        <CreateRFQDialog
          projectId={projectId}
          onSubmit={handleCreateSubmit}
          onClose={() => setShowCreate(false)}
          loading={createMutation.isPending}
          t={t}
        />
      )}

      <ConfirmDialog {...confirmProps} />
    </div>
  );
}

/* ── RFQ List panel ───────────────────────────────────────────────────── */

function RFQListPanel({
  rfqs,
  isLoading,
  error,
  search,
  onSearchChange,
  statusFilter,
  onStatusFilterChange,
  onIssue,
  onDelete,
  onSelectForComparison,
  focusRfqId,
  t,
}: {
  rfqs: RFQ[];
  isLoading: boolean;
  error: Error | null;
  search: string;
  onSearchChange: (v: string) => void;
  statusFilter: RFQStatus | '';
  onStatusFilterChange: (v: RFQStatus | '') => void;
  onIssue: (rfq: RFQ) => void;
  onDelete: (id: string) => void;
  onSelectForComparison: (id: string) => void;
  focusRfqId: string | null;
  t: (k: string, o?: Record<string, unknown>) => string;
}) {
  const ALL_STATUSES = RFQ_FILTER_STATUSES;
  useScrollToFocused(focusRfqId, rfqs.length);

  return (
    <div className="space-y-3">
      {/* Filter bar */}
      <div className="flex flex-wrap items-center gap-3">
        <div className="relative min-w-[200px] flex-1">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-content-tertiary" />
          <input
            type="text"
            placeholder={t('rfq_bidding.search', { defaultValue: 'Search RFQs...' })}
            value={search}
            onChange={(e) => onSearchChange(e.target.value)}
            className="w-full rounded-lg border border-border-light bg-surface-primary py-2 ps-10 pe-4 text-sm
              text-content-primary placeholder:text-content-tertiary
              focus:border-oe-blue focus:outline-none focus:ring-1 focus:ring-oe-blue"
          />
          {search && (
            <button
              onClick={() => onSearchChange('')}
              className="absolute right-3 top-1/2 -translate-y-1/2"
              aria-label={t('common.clear_search', { defaultValue: 'Clear search' })}
            >
              <X className="h-4 w-4 text-content-tertiary hover:text-content-secondary" aria-hidden />
            </button>
          )}
        </div>
        <select
          value={statusFilter}
          onChange={(e) => onStatusFilterChange(e.target.value as RFQStatus | '')}
          className="rounded-lg border border-border-light bg-surface-primary px-3 py-2 text-sm
            text-content-primary focus:border-oe-blue focus:outline-none focus:ring-1 focus:ring-oe-blue"
        >
          <option value="">{t('rfq_bidding.all_statuses', { defaultValue: 'All statuses' })}</option>
          {ALL_STATUSES.map((s) => (
            <option key={s} value={s}>{statusLabel(s, t)}</option>
          ))}
        </select>
      </div>

      {/* Loading */}
      {isLoading && (
        <div className="flex items-center justify-center py-16 text-content-tertiary">
          <Loader2 className="mr-2 h-5 w-5 animate-spin" />
          {t('common.loading', { defaultValue: 'Loading...' })}
        </div>
      )}

      {/* Error */}
      {error && (
        <div className="rounded-lg border border-semantic-error/30 bg-semantic-error-bg p-4 text-sm text-semantic-error">
          {t('rfq_bidding.load_error', { defaultValue: 'Could not load RFQs' })}
        </div>
      )}

      {/* Empty */}
      {!isLoading && !error && rfqs.length === 0 && (
        <EmptyState
          icon={<FileText className="h-12 w-12" />}
          title={t('rfq_bidding.empty', { defaultValue: 'No RFQs yet' })}
          description={t('rfq_bidding.empty_desc', {
            defaultValue: 'Create your first request for quotation to start collecting bids.',
          })}
        />
      )}

      {/* RFQ rows */}
      {!isLoading && rfqs.length > 0 && (
        <div className="space-y-2">
          {rfqs.map((rfq) => (
            <div
              key={rfq.id}
              id={rfqCardId(rfq.id)}
              data-focused={rfq.id === focusRfqId ? 'true' : undefined}
              className={clsx(
                'flex items-center gap-4 rounded-xl border border-border-light bg-surface-elevated/90 px-4 py-3 shadow-xs transition-shadow duration-normal ease-oe hover:shadow-sm',
                rfq.id === focusRfqId && 'ring-2 ring-oe-blue/60',
              )}
            >
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-sm font-semibold text-content-primary">{rfq.title}</span>
                  <Badge variant={STATUS_BADGE[rfq.status]} dot size="sm">
                    {statusLabel(rfq.status, t)}
                  </Badge>
                </div>
                {rfq.description && (
                  <p className="mt-0.5 truncate text-xs text-content-secondary">{rfq.description}</p>
                )}
                <div className="mt-1.5 flex flex-wrap items-center gap-3 text-xs text-content-tertiary">
                  {rfq.submission_deadline && (
                    <span className="flex items-center gap-1">
                      <Clock className="h-3 w-3" aria-hidden />
                      {t('rfq_bidding.due', { defaultValue: 'Due' })}: {fmtDate(rfq.submission_deadline)}
                    </span>
                  )}
                  <span>
                    {t('rfq_bidding.vendors_count', {
                      defaultValue: '{{count}} vendors',
                      count: rfq.issued_to_contacts?.length ?? 0,
                    })}
                  </span>
                  <span>
                    {t('rfq_bidding.bids_count', { defaultValue: '{{count}} bids', count: rfq.bids?.length ?? 0 })}
                  </span>
                </div>
              </div>

              {/* Actions */}
              <div className="flex shrink-0 items-center gap-1.5">
                {rfq.status === 'draft' && (
                  <button
                    onClick={() => onIssue(rfq)}
                    // Issuing is one way: the RFQ can no longer be deleted, and
                    // with no scope lines no vendor has anything to price.
                    disabled={(rfq.lines?.length ?? 0) === 0}
                    className="flex items-center gap-1 rounded-lg bg-oe-blue px-2.5 py-1.5 text-xs font-medium text-white
                      hover:bg-oe-blue/90 transition-colors disabled:cursor-not-allowed disabled:opacity-40"
                    title={
                      (rfq.lines?.length ?? 0) === 0
                        ? t('rfq_bidding.issue_needs_scope', {
                            defaultValue: 'Add at least one scope line before issuing',
                          })
                        : t('rfq_bidding.issue_action', { defaultValue: 'Issue to vendors' })
                    }
                  >
                    <Send className="h-3 w-3" aria-hidden />
                    {t('rfq_bidding.issue', { defaultValue: 'Issue' })}
                  </button>
                )}
                {RFQ_OPEN_STATUSES.has(rfq.status) && (
                  <button
                    onClick={() => onSelectForComparison(rfq.id)}
                    className="flex items-center gap-1 rounded-lg border border-border-light px-2.5 py-1.5 text-xs
                      font-medium text-content-secondary hover:bg-surface-secondary transition-colors"
                    title={t('rfq_bidding.compare_bids', { defaultValue: 'Compare bids' })}
                  >
                    <BarChart3 className="h-3 w-3" aria-hidden />
                    {t('rfq_bidding.compare', { defaultValue: 'Compare' })}
                  </button>
                )}
                {rfq.status === 'draft' && (
                  <button
                    onClick={() => onDelete(rfq.id)}
                    className="rounded-lg border border-border-light px-2 py-1.5 text-xs text-content-tertiary
                      hover:border-semantic-error/40 hover:text-semantic-error transition-colors"
                    title={t('rfq_bidding.delete_action', { defaultValue: 'Delete RFQ' })}
                  >
                    <X className="h-3.5 w-3.5" aria-hidden />
                  </button>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/* ── Comparison panel ─────────────────────────────────────────────────── */

function ComparisonPanel({
  rfqs,
  selectedRfqId,
  onSelectRfq,
  comparison,
  isLoading,
  onAward,
  awarding,
  bidderName,
  t,
}: {
  rfqs: RFQ[];
  selectedRfqId: string | null;
  onSelectRfq: (id: string | null) => void;
  comparison: ComparisonResponse | null;
  isLoading: boolean;
  onAward: (bidId: string) => void;
  awarding: boolean;
  bidderName: BidderName;
  t: (k: string, o?: Record<string, unknown>) => string;
}) {
  // Only show RFQs that have bids to compare
  const comparableRfqs = rfqs.filter(
    (r) => RFQ_OPEN_STATUSES.has(r.status) || RFQ_AWARDED_STATUSES.has(r.status),
  );
  const quoteCount = comparison ? comparison.ranked.length + comparison.excluded.length : 0;

  return (
    <div className="space-y-4">
      {/* RFQ selector */}
      <div className="flex items-center gap-3">
        <label className="text-sm font-medium text-content-secondary">
          {t('rfq_bidding.select_rfq', { defaultValue: 'Select RFQ' })}:
        </label>
        <select
          value={selectedRfqId ?? ''}
          onChange={(e) => onSelectRfq(e.target.value || null)}
          className="rounded-lg border border-border-light bg-surface-primary px-3 py-2 text-sm
            text-content-primary focus:border-oe-blue focus:outline-none focus:ring-1 focus:ring-oe-blue"
        >
          <option value="">{t('rfq_bidding.choose_rfq', { defaultValue: 'Choose an RFQ...' })}</option>
          {comparableRfqs.map((r) => (
            <option key={r.id} value={r.id}>{r.title}</option>
          ))}
        </select>
      </div>

      {/* No selection */}
      {!selectedRfqId && (
        <EmptyState
          icon={<BarChart3 className="h-12 w-12" />}
          title={t('rfq_bidding.no_rfq_selected', { defaultValue: 'Select an RFQ to compare bids' })}
          description={t('rfq_bidding.no_rfq_selected_desc', {
            defaultValue: 'Choose an RFQ from the dropdown above to see a side-by-side bid comparison.',
          })}
        />
      )}

      {/* Loading */}
      {selectedRfqId && isLoading && (
        <div className="flex items-center justify-center py-16 text-content-tertiary">
          <Loader2 className="mr-2 h-5 w-5 animate-spin" />
          {t('common.loading', { defaultValue: 'Loading...' })}
        </div>
      )}

      {/* Ranked and excluded quotes */}
      {selectedRfqId && !isLoading && comparison && quoteCount > 0 && (
        <ComparisonTable
          comparison={comparison}
          onAward={onAward}
          awarding={awarding}
          bidderName={bidderName}
          t={t}
        />
      )}

      {/* No bids */}
      {selectedRfqId && !isLoading && comparison && quoteCount === 0 && (
        <EmptyState
          icon={<BarChart3 className="h-12 w-12" />}
          title={t('rfq_bidding.no_bids', { defaultValue: 'No bids received yet' })}
          description={t('rfq_bidding.no_bids_desc', {
            defaultValue: 'Bids will appear here once vendors submit their quotations.',
          })}
        />
      )}
    </div>
  );
}

/* ── Comparison table ─────────────────────────────────────────────────── */

/**
 * The server's comparison: every quote restated on the RFQ's basis currency,
 * the comparable ones ranked, the rest listed with the reason they could not
 * be ranked. Only a ranked quote can be awarded; the server refuses the others.
 */
function ComparisonTable({
  comparison,
  onAward,
  awarding,
  bidderName,
  t,
}: {
  comparison: ComparisonResponse;
  onAward: (bidId: string) => void;
  awarding: boolean;
  bidderName: BidderName;
  t: (k: string, o?: Record<string, unknown>) => string;
}) {
  const showScore = comparison.ranked.some((q) => q.total_score != null);

  return (
    <div className="space-y-4">
      {comparison.ranked.length > 0 && (
        <div className="overflow-x-auto rounded-xl border border-border-light">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-surface-secondary text-content-secondary">
                <th className="px-4 py-3 text-left font-medium">
                  {t('rfq_bidding.col_rank', { defaultValue: 'Rank' })}
                </th>
                <th className="px-4 py-3 text-left font-medium">
                  {t('rfq_bidding.col_bidder', { defaultValue: 'Bidder' })}
                </th>
                <th className="px-4 py-3 text-right font-medium">
                  {t('rfq_bidding.col_coverage', { defaultValue: 'Scope covered' })}
                </th>
                {showScore && (
                  <th className="px-4 py-3 text-right font-medium">
                    {t('rfq_bidding.col_score', { defaultValue: 'Score' })}
                  </th>
                )}
                <th className="px-4 py-3 text-right font-medium">
                  {t('rfq_bidding.total', { defaultValue: 'Total' })} ({comparison.basis_currency})
                </th>
                <th className="px-4 py-3" />
              </tr>
            </thead>
            <tbody>
              {comparison.ranked.map((quote) => (
                <RankedQuoteRow
                  key={quote.bid_id}
                  quote={quote}
                  basisCurrency={comparison.basis_currency}
                  recommended={quote.bid_id === comparison.recommended_bid_id}
                  showScore={showScore}
                  onAward={onAward}
                  awarding={awarding}
                  bidderName={bidderName}
                  t={t}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}

      {comparison.excluded.length > 0 && (
        <div className="rounded-xl border border-border-light">
          <div className="border-b border-border-light bg-surface-secondary px-4 py-2.5">
            <p className="text-sm font-medium text-content-primary">
              {t('rfq_bidding.excluded_title', { defaultValue: 'Not comparable' })}
            </p>
            <p className="text-xs text-content-tertiary">
              {t('rfq_bidding.excluded_desc', {
                defaultValue: 'These quotes could not be put on the RFQ basis, so they are not ranked and cannot be awarded.',
              })}
            </p>
          </div>
          <ul className="divide-y divide-border-light">
            {comparison.excluded.map((quote) => (
              <li key={quote.bid_id} className="flex flex-wrap items-baseline justify-between gap-2 px-4 py-2.5 text-sm">
                <span className="font-medium text-content-primary">{bidderName(quote.bidder_contact_id)}</span>
                <span className="text-xs text-content-tertiary">
                  {quote.reasons.map((r) => exclusionReason(r, t)).join('; ')}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

/** The comparison's exclusion codes (REASON_* in rfq_bidding/comparison.py), in words. */
function exclusionReason(code: string, t: (k: string, o?: Record<string, unknown>) => string): string {
  const labels: Record<string, string> = {
    withdrawn: t('rfq_bidding.reason_withdrawn', { defaultValue: 'Withdrawn by the bidder' }),
    disqualified: t('rfq_bidding.reason_disqualified', { defaultValue: 'Disqualified' }),
    late_not_admitted: t('rfq_bidding.reason_late_not_admitted', { defaultValue: 'Late and not admitted' }),
    amount_unreadable: t('rfq_bidding.reason_amount_unreadable', { defaultValue: 'Amount could not be read' }),
    currency_not_converted: t('rfq_bidding.reason_currency_not_converted', {
      defaultValue: 'Other currency with no exchange rate recorded',
    }),
    adjustment_unreadable: t('rfq_bidding.reason_adjustment_unreadable', {
      defaultValue: 'An adjustment could not be read',
    }),
    adjustment_currency_not_converted: t('rfq_bidding.reason_adjustment_currency_not_converted', {
      defaultValue: 'An adjustment is in a currency with no exchange rate',
    }),
    unit_not_convertible: t('rfq_bidding.reason_unit_not_convertible', {
      defaultValue: 'A line unit does not convert to the RFQ unit',
    }),
    scope_not_covered: t('rfq_bidding.reason_scope_not_covered', { defaultValue: 'Part of the scope is not priced' }),
    normalised_total_not_positive: t('rfq_bidding.reason_normalised_total_not_positive', {
      defaultValue: 'Restated total is zero or negative',
    }),
    technical_score_missing: t('rfq_bidding.reason_technical_score_missing', {
      defaultValue: 'No technical score recorded',
    }),
  };
  return labels[code] ?? code;
}

function RankedQuoteRow({
  quote,
  basisCurrency,
  recommended,
  showScore,
  onAward,
  awarding,
  bidderName,
  t,
}: {
  quote: QuoteComparison;
  basisCurrency: string;
  recommended: boolean;
  showScore: boolean;
  onAward: (bidId: string) => void;
  awarding: boolean;
  bidderName: BidderName;
  t: (k: string, o?: Record<string, unknown>) => string;
}) {
  const name = bidderName(quote.bidder_contact_id);
  return (
    <tr className={clsx('border-t border-border-light', recommended && 'bg-semantic-success/5')}>
      <td className="px-4 py-2.5 tabular-nums text-content-secondary">{quote.rank ?? '-'}</td>
      <td className="px-4 py-2.5 text-content-primary">
        <div className="flex flex-wrap items-center gap-2">
          <span>{name}</span>
          {recommended && (
            <Badge variant="success" size="sm">
              {t('rfq_bidding.recommended', { defaultValue: 'Recommended' })}
            </Badge>
          )}
        </div>
      </td>
      <td className="px-4 py-2.5 text-right tabular-nums text-content-secondary">
        {quote.lines_covered}/{quote.lines_required}
      </td>
      {showScore && (
        <td className="px-4 py-2.5 text-right tabular-nums text-content-secondary">{quote.total_score ?? '-'}</td>
      )}
      <td
        className={clsx(
          'px-4 py-2.5 text-right font-semibold tabular-nums',
          recommended ? 'text-semantic-success' : 'text-content-primary',
        )}
      >
        {quote.normalised_amount != null ? (
          <MoneyDisplay amount={quote.normalised_amount} currency={basisCurrency} />
        ) : (
          <span className="text-content-tertiary">-</span>
        )}
      </td>
      <td className="px-4 py-2.5 text-right">
        <button
          onClick={() => onAward(quote.bid_id)}
          disabled={awarding}
          className="inline-flex items-center gap-1 rounded-lg border border-border-light px-3 py-1.5 text-xs
            font-medium text-content-secondary hover:border-semantic-success/40 hover:text-semantic-success
            disabled:opacity-40 transition-colors"
          aria-label={`${t('rfq_bidding.award_action', { defaultValue: 'Award to' })} ${name}`}
        >
          <Trophy className="h-3 w-3" aria-hidden />
          {t('rfq_bidding.award', { defaultValue: 'Award' })}
        </button>
      </td>
    </tr>
  );
}

/* ── Awards panel ─────────────────────────────────────────────────────── */

function AwardsPanel({
  rfqs,
  bidderName,
  orderFor,
  focusRfqId,
  t,
}: {
  rfqs: RFQ[];
  bidderName: BidderName;
  orderFor: RfqOrderLookup;
  focusRfqId: string | null;
  t: (k: string, o?: Record<string, unknown>) => string;
}) {
  useScrollToFocused(focusRfqId, rfqs.length);

  if (rfqs.length === 0) {
    return (
      <EmptyState
        icon={<Trophy className="h-12 w-12" />}
        title={t('rfq_bidding.no_awards', { defaultValue: 'No awards yet' })}
        description={t('rfq_bidding.no_awards_desc', {
          defaultValue: 'Awards will appear here once you select winning bids from the comparison view.',
        })}
      />
    );
  }

  return (
    <div className="space-y-3">
      {rfqs.map((rfq) => {
        const winningBid = (rfq.bids ?? []).find((b) => b.is_awarded);
        return (
          <div
            key={rfq.id}
            id={rfqCardId(rfq.id)}
            data-focused={rfq.id === focusRfqId ? 'true' : undefined}
            className={clsx(
              'rounded-xl border border-border-light bg-surface-elevated/90 px-4 py-4 shadow-xs transition-shadow duration-normal ease-oe hover:shadow-sm',
              rfq.id === focusRfqId && 'ring-2 ring-oe-blue/60',
            )}
          >
            <div className="flex items-start justify-between gap-4">
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <CheckCircle2 className="h-4 w-4 text-semantic-success" aria-hidden />
                  <span className="text-sm font-semibold text-content-primary">{rfq.title}</span>
                  <Badge variant="success" dot size="sm">
                    {statusLabel(rfq.status, t)}
                  </Badge>
                </div>
              </div>
              {winningBid && (
                <div className="shrink-0 text-right">
                  <p className="text-xs font-medium text-content-secondary">
                    {bidderName(winningBid.bidder_contact_id)}
                  </p>
                  <p className="mt-0.5 text-sm font-semibold tabular-nums text-semantic-success">
                    <MoneyDisplay amount={winningBid.bid_amount} currency={winningBid.currency_code} />
                  </p>
                </div>
              )}
            </div>
            {winningBid?.notes && (
              <p className="mt-2 text-xs text-content-secondary">{winningBid.notes}</p>
            )}
            <AwardOrderLink rfq={rfq} lookup={orderFor(rfq.id)} t={t} />
          </div>
        );
      })}
    </div>
  );
}

/** The DOM id of an RFQ's row or award card, so a deep link can scroll to it. */
function rfqCardId(rfqId: string): string {
  return `rfq-card-${rfqId}`;
}

/**
 * Scroll the RFQ a deep link named into view once its row is on screen. Runs
 * again when the row count changes, because the list may render empty first.
 */
function useScrollToFocused(focusRfqId: string | null, rowCount: number) {
  const scrolledRef = useRef<string | null>(null);
  useEffect(() => {
    if (!focusRfqId || scrolledRef.current === focusRfqId) return;
    const el = document.getElementById(rfqCardId(focusRfqId));
    if (!el) return;
    scrolledRef.current = focusRfqId;
    el.scrollIntoView?.({ block: 'center', behavior: 'smooth' });
  }, [focusRfqId, rowCount]);
}

/* ── The order an award drafted ───────────────────────────────────────── */

const AWARD_STRIP_CLASS = 'mt-3 flex flex-wrap items-center gap-2 border-t border-border-light pt-2 text-xs';

/**
 * Where an award went next. Awarding drafts a purchase order for the winning
 * supplier (`procurement/rfq_award.py`); this names it and links to it. The
 * register is read rather than trusted to hold the draft, so each state of the
 * lookup is drawn for what it is:
 *
 * - found: the order, by number, opened in Procurement;
 * - loading: the read, or the draft of an award made on this screen, is on
 *   its way;
 * - absent: the register was read in full and no order came from this award
 *   (an award from before drafting existed, or one the draft was refused for),
 *   so the order is still the buyer's to raise;
 * - unknown: the register could not be read in full, so nothing is claimed
 *   and the reader is sent to look.
 *
 * Once the RFQ has moved past `awarded` only a found order is shown: the order
 * step is behind it.
 */
function AwardOrderLink({
  rfq,
  lookup,
  t,
}: {
  rfq: RFQ;
  lookup: AwardLookup<AwardOrderLite>;
  t: (k: string, o?: Record<string, unknown>) => string;
}) {
  if (lookup.state === 'found') {
    const po = lookup.record;
    return (
      <div className={AWARD_STRIP_CLASS} data-testid="rfq-award-order">
        <span className="text-content-tertiary">
          {po.status === 'draft'
            ? t('rfq_bidding.award_po_drafted', { defaultValue: 'Draft purchase order created:' })
            : t('rfq_bidding.award_po', { defaultValue: 'Purchase order:' })}
        </span>
        <RelatedRecordLink
          to={purchaseOrderDeepLink(po.id)}
          icon={<FileText className="h-3 w-3" aria-hidden />}
          title={t('rfq_bidding.award_po_open_hint', {
            defaultValue: 'Open this purchase order in Procurement to review and approve it',
          })}
        >
          {po.po_number}
        </RelatedRecordLink>
      </div>
    );
  }
  if (rfq.status !== 'awarded') return null;
  if (lookup.state === 'loading') {
    return (
      <div className={clsx(AWARD_STRIP_CLASS, 'text-content-tertiary')} role="status">
        <Loader2 className="h-3 w-3 animate-spin" aria-hidden />
        {t('rfq_bidding.award_po_pending', { defaultValue: 'Looking for the draft purchase order...' })}
      </div>
    );
  }
  if (lookup.state === 'unknown') {
    return (
      <div className={AWARD_STRIP_CLASS}>
        <span className="text-content-tertiary">{t('rfq_bidding.award_po', { defaultValue: 'Purchase order:' })}</span>
        <RelatedRecordLink
          to={PROCUREMENT_LINK}
          title={t('rfq_bidding.award_po_find_hint', {
            defaultValue:
              'The purchase order register could not be read in full here. Look for this award in Procurement.',
          })}
        >
          {t('rfq_bidding.award_po_find', { defaultValue: 'Find it in Procurement' })}
        </RelatedRecordLink>
      </div>
    );
  }
  return (
    <div className={AWARD_STRIP_CLASS}>
      <span className="text-content-tertiary">{t('rfq_bidding.award_next', { defaultValue: 'Next step:' })}</span>
      <Link
        to={PROCUREMENT_LINK}
        className="inline-flex items-center gap-1 rounded-md border border-border-light px-2 py-1 text-content-secondary hover:text-oe-blue hover:border-oe-blue transition-colors"
        title={t('rfq_bidding.award_raise_po_hint', {
          defaultValue: 'Open Procurement to raise the purchase order for the awarded vendor',
        })}
      >
        {t('rfq_bidding.award_raise_po', { defaultValue: 'Raise purchase order' })}
      </Link>
    </div>
  );
}

/* ── Create RFQ dialog ────────────────────────────────────────────────── */

function CreateRFQDialog({
  projectId,
  onSubmit,
  onClose,
  loading,
  t,
}: {
  projectId: string;
  onSubmit: (payload: RFQCreatePayload) => void;
  onClose: () => void;
  loading: boolean;
  t: (k: string, o?: Record<string, unknown>) => string;
}) {
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [dueDate, setDueDate] = useState('');
  const dialogRef = useRef<HTMLDivElement>(null);

  // Close on Escape
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        onClose();
      }
    };
    document.addEventListener('keydown', handler, { capture: true });
    return () => document.removeEventListener('keydown', handler, { capture: true });
  }, [onClose]);

  // Close on backdrop click
  const handleBackdropClick = useCallback(
    (e: React.MouseEvent) => {
      if (dialogRef.current && !dialogRef.current.contains(e.target as Node)) {
        onClose();
      }
    },
    [onClose],
  );

  const handleSubmit = useCallback(
    (e: React.FormEvent) => {
      e.preventDefault();
      if (!title.trim()) return;
      onSubmit({
        project_id: projectId,
        title: title.trim(),
        description: description.trim() || undefined,
        submission_deadline: dueDate || undefined,
      });
    },
    [projectId, title, description, dueDate, onSubmit],
  );

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
      onClick={handleBackdropClick}
    >
      <div
        ref={dialogRef}
        className="w-full max-w-lg rounded-2xl border border-border-light bg-surface-primary p-6 shadow-xl"
        role="dialog"
        aria-modal="true"
        aria-label={t('rfq_bidding.create_dialog_title', { defaultValue: 'Create RFQ' })}
      >
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-lg font-semibold text-content-primary">
            {t('rfq_bidding.create_dialog_title', { defaultValue: 'Create RFQ' })}
          </h2>
          <button
            onClick={onClose}
            className="rounded-lg p-1 text-content-tertiary hover:bg-surface-secondary"
            aria-label={t('common.close', { defaultValue: 'Close' })}
          >
            <X className="h-5 w-5" aria-hidden />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="mb-1 block text-sm font-medium text-content-secondary">
              {t('rfq_bidding.field_title', { defaultValue: 'Title' })}
              <span className="text-semantic-error"> *</span>
            </label>
            <input
              type="text"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder={t('rfq_bidding.field_title_placeholder', { defaultValue: 'e.g. Concrete supply for Block A' })}
              required
              autoFocus
              className="w-full rounded-lg border border-border-light bg-surface-primary px-3 py-2 text-sm
                text-content-primary placeholder:text-content-tertiary
                focus:border-oe-blue focus:outline-none focus:ring-1 focus:ring-oe-blue"
            />
          </div>

          <div>
            <label className="mb-1 block text-sm font-medium text-content-secondary">
              {t('rfq_bidding.field_description', { defaultValue: 'Description' })}
            </label>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={3}
              placeholder={t('rfq_bidding.field_description_placeholder', {
                defaultValue: 'Describe the scope and requirements...',
              })}
              className="w-full rounded-lg border border-border-light bg-surface-primary px-3 py-2 text-sm
                text-content-primary placeholder:text-content-tertiary resize-none
                focus:border-oe-blue focus:outline-none focus:ring-1 focus:ring-oe-blue"
            />
          </div>

          <div>
            <label className="mb-1 block text-sm font-medium text-content-secondary">
              {t('rfq_bidding.field_due_date', { defaultValue: 'Due Date' })}
            </label>
            <input
              type="date"
              value={dueDate}
              onChange={(e) => setDueDate(e.target.value)}
              className="w-full rounded-lg border border-border-light bg-surface-primary px-3 py-2 text-sm
                text-content-primary
                focus:border-oe-blue focus:outline-none focus:ring-1 focus:ring-oe-blue"
            />
          </div>

          <div className="flex items-center justify-end gap-2 pt-2">
            <Button variant="ghost" onClick={onClose} type="button">
              {t('common.cancel', { defaultValue: 'Cancel' })}
            </Button>
            <Button variant="primary" type="submit" disabled={!title.trim() || loading}>
              {loading && <Loader2 className="mr-1.5 h-4 w-4 animate-spin" aria-hidden />}
              {t('rfq_bidding.create_submit', { defaultValue: 'Create RFQ' })}
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
}
