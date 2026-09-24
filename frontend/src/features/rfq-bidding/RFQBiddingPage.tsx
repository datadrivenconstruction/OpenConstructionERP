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
import { Link } from 'react-router-dom';
import { fmtDate, getIntlLocale } from '@/shared/lib/formatters';
import { Badge, CollapsibleSection, EmptyState, StatCard, Button } from '@/shared/ui';
import type { BadgeVariant } from '@/shared/ui';
import { PageHeader } from '@/shared/ui/PageHeader';
import { TabBar, tabIds } from '@/shared/ui/TabBar';
import type { TabBarTab } from '@/shared/ui/TabBar';
import { MoneyDisplay } from '@/shared/ui/MoneyDisplay';
import { useActiveProjectId } from '@/shared/hooks/useActiveProjectId';
import { useToastStore } from '@/stores/useToastStore';
import {
  fetchRFQs,
  createRFQ,
  issueRFQ,
  deleteRFQ,
  fetchComparison,
  fetchBids,
  awardBid,
  type RFQ,
  type RFQStatus,
  RFQ_OPEN_STATUSES,
  RFQ_AWARDED_STATUSES,
  RFQ_FILTER_STATUSES,
  type RFQCreatePayload,
  type Bid,
  type ComparisonMatrix,
} from './api';

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

  // ── Data fetching ─────────────────────────────────────────────────────

  const { data: rfqPage, isLoading: rfqLoading, error: rfqError } = useQuery({
    queryKey: ['rfq-bidding', projectId, statusFilter],
    queryFn: () => fetchRFQs(projectId || undefined, statusFilter || undefined),
    enabled: !!projectId,
    staleTime: 30_000,
  });

  const rfqs = rfqPage?.items ?? [];
  const rfqTotal = rfqPage?.total ?? 0;

  const firstRfqId = rfqs[0]?.id;

  const { data: bidsPage } = useQuery({
    queryKey: ['rfq-bidding-bids', projectId, firstRfqId],
    queryFn: () => fetchBids(firstRfqId!),
    enabled: !!projectId && !!firstRfqId,
    staleTime: 30_000,
  });

  const allBids = bidsPage?.items ?? [];

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
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['rfq-bidding'] });
      queryClient.invalidateQueries({ queryKey: ['rfq-bidding-bids'] });
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
            onIssue={(id) => issueMutation.mutate(id)}
            onDelete={(id) => deleteMutation.mutate(id)}
            onSelectForComparison={(id) => {
              setComparisonRfqId(id);
              setActiveTab('comparison');
            }}
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
            bids={allBids}
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
  t,
}: {
  rfqs: RFQ[];
  isLoading: boolean;
  error: Error | null;
  search: string;
  onSearchChange: (v: string) => void;
  statusFilter: RFQStatus | '';
  onStatusFilterChange: (v: RFQStatus | '') => void;
  onIssue: (id: string) => void;
  onDelete: (id: string) => void;
  onSelectForComparison: (id: string) => void;
  t: (k: string, o?: Record<string, unknown>) => string;
}) {
  const ALL_STATUSES = RFQ_FILTER_STATUSES;

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
              className="flex items-center gap-4 rounded-xl border border-border-light bg-surface-elevated/90 px-4 py-3
                shadow-xs transition-shadow duration-normal ease-oe hover:shadow-sm"
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
                  {rfq.due_date && (
                    <span className="flex items-center gap-1">
                      <Clock className="h-3 w-3" aria-hidden />
                      {t('rfq_bidding.due', { defaultValue: 'Due' })}: {fmtDate(rfq.due_date)}
                    </span>
                  )}
                  <span>
                    {t('rfq_bidding.vendors_count', { defaultValue: '{{count}} vendors', count: rfq.vendors_count })}
                  </span>
                  <span>
                    {t('rfq_bidding.bids_count', { defaultValue: '{{count}} bids', count: rfq.bids_count })}
                  </span>
                </div>
              </div>

              {/* Actions */}
              <div className="flex shrink-0 items-center gap-1.5">
                {rfq.status === 'draft' && (
                  <button
                    onClick={() => onIssue(rfq.id)}
                    className="flex items-center gap-1 rounded-lg bg-oe-blue px-2.5 py-1.5 text-xs font-medium text-white
                      hover:bg-oe-blue/90 transition-colors"
                    title={t('rfq_bidding.issue_action', { defaultValue: 'Issue to vendors' })}
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
  t,
}: {
  rfqs: RFQ[];
  selectedRfqId: string | null;
  onSelectRfq: (id: string | null) => void;
  comparison: ComparisonMatrix | null;
  isLoading: boolean;
  onAward: (bidId: string) => void;
  awarding: boolean;
  t: (k: string, o?: Record<string, unknown>) => string;
}) {
  // Only show RFQs that have bids to compare
  const comparableRfqs = rfqs.filter(
    (r) => RFQ_OPEN_STATUSES.has(r.status) || RFQ_AWARDED_STATUSES.has(r.status),
  );

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

      {/* Comparison matrix */}
      {selectedRfqId && !isLoading && comparison && (
        <ComparisonTable
          comparison={comparison}
          onAward={onAward}
          awarding={awarding}
          t={t}
        />
      )}

      {/* No bids */}
      {selectedRfqId && !isLoading && comparison && comparison.bids.length === 0 && (
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

function ComparisonTable({
  comparison,
  onAward,
  awarding,
  t,
}: {
  comparison: ComparisonMatrix;
  onAward: (bidId: string) => void;
  awarding: boolean;
  t: (k: string, o?: Record<string, unknown>) => string;
}) {
  if (comparison.bids.length === 0) return null;

  // Find lowest total for highlighting
  const totals = comparison.bids.map((b) => Number(b.total_amount) || 0);
  const lowestTotal = Math.min(...totals);

  return (
    <div className="overflow-x-auto rounded-xl border border-border-light">
      <table className="w-full text-sm">
        <thead>
          <tr className="bg-surface-secondary text-content-secondary">
            <th className="px-4 py-3 text-left font-medium">
              {t('rfq_bidding.scope_line', { defaultValue: 'Scope Line' })}
            </th>
            {comparison.bids.map((bid) => (
              <th key={bid.id} className="px-4 py-3 text-right font-medium">
                <div className="flex items-center justify-end gap-2">
                  <span>{bid.vendor_name}</span>
                  {Number(bid.total_amount) === lowestTotal && totals.length > 1 && (
                    <Badge variant="success" size="sm">
                      {t('rfq_bidding.lowest', { defaultValue: 'Lowest' })}
                    </Badge>
                  )}
                </div>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {comparison.scope_lines.map((line) => (
            <tr key={line.id} className="border-t border-border-light">
              <td className="px-4 py-2.5 text-content-primary">
                <div>{line.description}</div>
                <div className="text-xs text-content-tertiary">
                  {line.quantity} {line.unit}
                </div>
              </td>
              {comparison.bids.map((bid) => {
                const price = comparison.matrix?.[line.id]?.[bid.id];
                return (
                  <td key={bid.id} className="px-4 py-2.5 text-right tabular-nums text-content-primary">
                    {price != null ? (
                      <MoneyDisplay amount={price} currency={bid.currency_code} />
                    ) : (
                      <span className="text-content-tertiary">-</span>
                    )}
                  </td>
                );
              })}
            </tr>
          ))}

          {/* Totals row */}
          <tr className="border-t-2 border-border-light bg-surface-secondary/50 font-semibold">
            <td className="px-4 py-3 text-content-primary">
              {t('rfq_bidding.total', { defaultValue: 'Total' })}
            </td>
            {comparison.bids.map((bid) => {
              const isLowest = Number(bid.total_amount) === lowestTotal && totals.length > 1;
              return (
                <td
                  key={bid.id}
                  className={clsx(
                    'px-4 py-3 text-right tabular-nums',
                    isLowest ? 'text-semantic-success' : 'text-content-primary',
                  )}
                >
                  <MoneyDisplay amount={bid.total_amount} currency={bid.currency_code} />
                </td>
              );
            })}
          </tr>
        </tbody>
      </table>

      {/* Award buttons */}
      <div className="flex flex-wrap items-center gap-2 border-t border-border-light bg-surface-primary px-4 py-3">
        <span className="text-xs font-medium text-content-tertiary">
          {t('rfq_bidding.award_action', { defaultValue: 'Award to' })}:
        </span>
        {comparison.bids.map((bid) => (
          <button
            key={bid.id}
            onClick={() => onAward(bid.id)}
            disabled={awarding}
            className="flex items-center gap-1 rounded-lg border border-border-light px-3 py-1.5 text-xs
              font-medium text-content-secondary hover:border-semantic-success/40 hover:text-semantic-success
              disabled:opacity-40 transition-colors"
          >
            <Trophy className="h-3 w-3" aria-hidden />
            {bid.vendor_name}
          </button>
        ))}
      </div>
    </div>
  );
}

/* ── Awards panel ─────────────────────────────────────────────────────── */

function AwardsPanel({
  rfqs,
  bids,
  t,
}: {
  rfqs: RFQ[];
  bids: Bid[];
  t: (k: string, o?: Record<string, unknown>) => string;
}) {
  // Match awarded RFQs with their winning bids
  const awardedBids = bids.filter((b) => b.status === 'awarded');

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
        const winningBid = awardedBids.find((b) => b.rfq_id === rfq.id);
        return (
          <div
            key={rfq.id}
            className="rounded-xl border border-border-light bg-surface-elevated/90 px-4 py-4
              shadow-xs transition-shadow duration-normal ease-oe hover:shadow-sm"
          >
            <div className="flex items-start justify-between gap-4">
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <CheckCircle2 className="h-4 w-4 text-semantic-success" aria-hidden />
                  <span className="text-sm font-semibold text-content-primary">{rfq.title}</span>
                  <Badge variant="success" dot size="sm">
                    {statusLabel('awarded', t)}
                  </Badge>
                </div>
                {rfq.awarded_at && (
                  <p className="mt-1 text-xs text-content-tertiary">
                    {t('rfq_bidding.awarded_on', { defaultValue: 'Awarded on' })}{' '}
                    {new Date(rfq.awarded_at).toLocaleDateString(getIntlLocale())}
                  </p>
                )}
              </div>
              {winningBid && (
                <div className="shrink-0 text-right">
                  <p className="text-xs font-medium text-content-secondary">
                    {winningBid.vendor_name}
                  </p>
                  <p className="mt-0.5 text-sm font-semibold tabular-nums text-semantic-success">
                    <MoneyDisplay amount={winningBid.total_amount} currency={winningBid.currency_code} />
                  </p>
                </div>
              )}
            </div>
            {winningBid?.notes && (
              <p className="mt-2 text-xs text-content-secondary">{winningBid.notes}</p>
            )}
          </div>
        );
      })}
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
        due_date: dueDate || undefined,
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
