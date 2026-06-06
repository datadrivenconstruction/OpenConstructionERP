import { useState, useMemo, useEffect } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import clsx from 'clsx';
import {
  Package as PackageIcon,
  Mail,
  Inbox,
  HelpCircle,
  Plus,
  Search,
  X,
  Send,
  XCircle,
  Loader2,
  Calculator,
  Award,
  ArrowRight,
  ListPlus,
  FileText,
  Info,
  Users,
  Check,
} from 'lucide-react';
import {
  Button,
  Card,
  Badge,
  DismissibleInfo,
  EmptyState,
  Breadcrumb,
  RecoveryCard,
  SkeletonTable,
  WideModal,
  WideModalSection,
  WideModalField,
} from '@/shared/ui';
import { MoneyDisplay } from '@/shared/ui/MoneyDisplay';
import { DateDisplay } from '@/shared/ui/DateDisplay';
import { PageHeader } from '@/shared/ui/PageHeader';
import { apiGet, getErrorMessage } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { useTabKeyboardNav } from '@/shared/hooks/useTabKeyboardNav';
import {
  listPackages,
  getPackage,
  createPackage,
  publishPackage,
  // dead_button fix: openBids was exported but never wired into the page, so a
  // published package could never advance to "open" — the only path that marks
  // submissions is_valid=True. Without it leveling stayed empty and award blocked.
  openBids,
  closePackage,
  awardPackage,
  packageDashboard,
  createBidder,
  createInvitation,
  createQA,
  answerQA,
  getOrCreateComparison,
  computeLeveling,
  levelingTable,
  levelingMatrix,
  createLineItem,
  createSubmission,
  bulkCreateSubmissionLines,
  type BidPackage,
  type BidPackageStatus,
  type BidInvitationStatus,
  type BidConfidentiality,
  type Bidder,
  type BidInvitation,
  type BidSubmission,
  type BidQA,
  type BidPackageLineItem,
  type LevelingTable as LevelingTableData,
} from './api';
import {
  listSubcontractors,
  type Subcontractor,
  type PrequalStatus,
} from '@/features/subcontractors/api';

const BID_TAB_IDS = ['packages', 'invitations', 'submissions', 'qa'] as const;
type Tab = (typeof BID_TAB_IDS)[number];

const PACKAGE_STATUS_VARIANT: Record<
  BidPackageStatus,
  'neutral' | 'blue' | 'success' | 'warning' | 'error'
> = {
  draft: 'neutral',
  published: 'blue',
  open: 'warning',
  closed: 'neutral',
  cancelled: 'error',
  awarded: 'success',
};

const INVITATION_STATUS_VARIANT: Record<
  BidInvitationStatus,
  'neutral' | 'blue' | 'success' | 'warning' | 'error'
> = {
  pending: 'neutral',
  sent: 'blue',
  opened: 'warning',
  submitted: 'success',
  declined: 'error',
  expired: 'neutral',
};

const PACKAGE_STATUSES: BidPackageStatus[] = [
  'draft',
  'published',
  'open',
  'closed',
  'cancelled',
  'awarded',
];

type TFn = (key: string, options?: Record<string, string | number>) => string;

const PACKAGE_STATUS_LABEL_FALLBACK: Record<BidPackageStatus, string> = {
  draft: 'Draft',
  published: 'Published',
  open: 'Open',
  closed: 'Closed',
  cancelled: 'Cancelled',
  awarded: 'Awarded',
};

const INVITATION_STATUS_LABEL_FALLBACK: Record<BidInvitationStatus, string> = {
  pending: 'Pending',
  sent: 'Sent',
  opened: 'Opened',
  submitted: 'Submitted',
  declined: 'Declined',
  expired: 'Expired',
};

const CONFIDENTIALITY_LABEL_FALLBACK: Record<BidConfidentiality, string> = {
  public: 'Public',
  limited: 'Limited',
  confidential: 'Confidential',
};

function packageStatusLabel(t: TFn, status: BidPackageStatus): string {
  return t(`bid_management.status_${status}`, {
    defaultValue: PACKAGE_STATUS_LABEL_FALLBACK[status] ?? status,
  });
}

function invitationStatusLabel(t: TFn, status: BidInvitationStatus): string {
  return t(`bid_management.inv_status_${status}`, {
    defaultValue: INVITATION_STATUS_LABEL_FALLBACK[status] ?? status,
  });
}

function confidentialityLabel(t: TFn, level: BidConfidentiality): string {
  return t(`bid_management.confidentiality_${level}`, {
    defaultValue: CONFIDENTIALITY_LABEL_FALLBACK[level] ?? level,
  });
}

const inputCls =
  'h-9 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';

const labelCls = 'block text-xs font-medium text-content-secondary mb-1';

interface ProjectStub {
  id: string;
  name: string;
  currency?: string;
}

function listProjectsLite(): Promise<ProjectStub[]> {
  return apiGet<ProjectStub[]>('/v1/projects/?limit=200').catch(() => [] as ProjectStub[]);
}

function listInvitationsForPackage(packageId: string): Promise<BidInvitation[]> {
  return apiGet<BidInvitation[]>(
    `/v1/bid-management/invitations/?package_id=${packageId}&limit=200`,
  ).catch(() => [] as BidInvitation[]);
}

function listBiddersForPackage(packageId: string): Promise<Bidder[]> {
  return apiGet<Bidder[]>(
    `/v1/bid-management/bidders/?package_id=${packageId}&limit=200`,
  ).catch(() => [] as Bidder[]);
}

function listSubmissionsForPackage(packageId: string): Promise<BidSubmission[]> {
  return apiGet<BidSubmission[]>(
    `/v1/bid-management/submissions/?package_id=${packageId}&limit=200`,
  ).catch(() => [] as BidSubmission[]);
}

function listLineItemsForPackage(packageId: string): Promise<BidPackageLineItem[]> {
  return apiGet<BidPackageLineItem[]>(
    `/v1/bid-management/bid-package-line-items/?package_id=${packageId}&limit=500`,
  ).catch(() => [] as BidPackageLineItem[]);
}

function listQAForPackage(packageId: string): Promise<BidQA[]> {
  return apiGet<BidQA[]>(
    `/v1/bid-management/q-and-a/?package_id=${packageId}&limit=200`,
  ).catch(() => [] as BidQA[]);
}

/* ── Subcontractor directory picker ─────────────────────────────────────── */

// CONN-39 / CONN-41: invite or add a bid against a known subcontractor instead
// of retyping a company by hand. Resolves the firm's primary contact email so
// the invitation goes to the right place.
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
    queryKey: ['bid-management', 'subcontractor-directory'],
    queryFn: () => listSubcontractors({ active_only: true, limit: 200 }),
    staleTime: 60_000,
  });

  const rows = useMemo(() => {
    const items = subsQ.data ?? [];
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

  return (
    <WideModal
      open
      onClose={onClose}
      title={t('bid_management.pick_sub_title', {
        defaultValue: 'Invite from Subcontractor Directory',
      })}
      subtitle={t('bid_management.pick_sub_subtitle', {
        defaultValue:
          'Pick a prequalified subcontractor. The prequalification status is shown so you compare like for like before inviting.',
      })}
      size="lg"
      footer={
        <Button variant="ghost" onClick={onClose}>
          {t('common.cancel', { defaultValue: 'Cancel' })}
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
            placeholder={t('bid_management.pick_sub_search', {
              defaultValue: 'Search subcontractors by name or trade…',
            })}
            className={clsx(inputCls, 'pl-8')}
            autoFocus
          />
        </div>
        {subsQ.isLoading ? (
          <SkeletonTable rows={5} columns={3} />
        ) : rows.length === 0 ? (
          <EmptyState
            icon={<Users size={22} />}
            title={t('bid_management.pick_sub_empty', {
              defaultValue: 'No subcontractors found',
            })}
            description={t('bid_management.pick_sub_empty_desc', {
              defaultValue: 'Add subcontractors in the directory, then invite them here.',
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
                      {sub.trade_categories.slice(0, 3).join(', ')}
                    </span>
                  )}
                </span>
                <Badge variant={PREQUAL_PICKER_VARIANT[sub.prequalification_status]} dot>
                  {t(`bid_management.prequal_${sub.prequalification_status}`, {
                    defaultValue: sub.prequalification_status,
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
      </div>
    </WideModal>
  );
}

export function BidManagementPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const activeProjectId = useProjectContextStore((s) => s.activeProjectId);

  const projectsQ = useQuery({
    queryKey: ['bid-management', 'projects'],
    queryFn: listProjectsLite,
    staleTime: 60_000,
  });

  const projects = projectsQ.data ?? [];
  const projectId = activeProjectId || projects[0]?.id || '';
  const currentProject = useMemo(
    () => projects.find((p) => p.id === projectId),
    [projects, projectId],
  );

  const [tab, setTab] = useState<Tab>('packages');
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState<string>('');
  // Arrow-key navigation across the 4-tab bid management strip (WCAG 2.1.1).
  const onTabKeyDown = useTabKeyboardNav<Tab>({
    ids: BID_TAB_IDS,
    activeId: tab,
    onChange: (next) => {
      setTab(next);
      setStatusFilter('');
      setSearch('');
    },
    orientation: 'horizontal',
  });
  const [selectedPackageId, setSelectedPackageId] = useState<string | null>(null);
  const [createOpen, setCreateOpen] = useState(false);

  const packagesQ = useQuery({
    queryKey: ['bid-management', 'packages', projectId, statusFilter],
    queryFn: () =>
      listPackages({ project_id: projectId, status: statusFilter || undefined, limit: 200 }),
    enabled: !!projectId,
  });

  const filteredPackages = useMemo(() => {
    const items = packagesQ.data ?? [];
    if (!search.trim()) return items;
    const s = search.toLowerCase();
    return items.filter(
      (p) =>
        p.code.toLowerCase().includes(s) ||
        (p.title || '').toLowerCase().includes(s) ||
        (p.scope_description || '').toLowerCase().includes(s),
    );
  }, [packagesQ.data, search]);

  const isLoading = packagesQ.isLoading || projectsQ.isLoading;

  if (!projectId) {
    return (
      <div className="space-y-5 animate-fade-in">
        <Breadcrumb
          items={[{ label: t('nav.bid_management', { defaultValue: 'Bid Management' }) }]}
        />
        <EmptyState
          icon={<PackageIcon size={22} />}
          title={t('bid_management.no_project', {
            defaultValue: 'Select a project to manage bid packages',
          })}
          description={t('bid_management.no_project_desc', {
            defaultValue:
              'Bid Management is project-scoped, create or open a project, then return here.',
          })}
        />
      </div>
    );
  }

  return (
    <div className="space-y-5 animate-fade-in">
      <Breadcrumb
        items={[
          ...(currentProject
            ? [{ label: currentProject.name, to: `/projects/${currentProject.id}` }]
            : []),
          { label: t('nav.bid_management', { defaultValue: 'Bid Management' }) },
        ]}
      />

      {/* Header — project selection lives in the global top bar; no in-page
          project picker. The page reads the shared project context. */}
      <PageHeader
        subtitle={t('bid_management.subtitle', {
          defaultValue:
            'Run end-to-end tendering: packages, invitations, submissions, Q&A, and bid leveling.',
        })}
        actions={
          <Button variant="primary" icon={<Plus size={14} />} onClick={() => setCreateOpen(true)}>
            {t('bid_management.new_package', { defaultValue: 'New Package' })}
          </Button>
        }
      />

      <DismissibleInfo
        storageKey="bid-management"
        title={t('bid_management.intro_title', {
          defaultValue: 'Pick the right subcontractor like for like',
        })}
        links={[
          {
            label: t('nav.subcontractors', { defaultValue: 'Subcontractors' }),
            onClick: () => navigate('/subcontractors'),
          },
          {
            label: t('nav.contracts', { defaultValue: 'Contracts' }),
            onClick: () => navigate('/contracts'),
          },
          {
            label: t('nav.tendering', { defaultValue: 'Tendering' }),
            onClick: () => navigate('/tendering'),
          },
        ]}
      >
        {t('bid_management.intro_body', {
          defaultValue:
            'Bundle scope into bid packages, invite prequalified subcontractors, collect their priced submissions, handle Q and A, and level the bids side by side before you award. The award flows straight into Contracts. Use Tendering instead when you want a formal BOQ-driven tender that writes rates back and raises a PO.',
        })}
      </DismissibleInfo>

      <div className="border-b border-border-light">
        <nav
          className="flex gap-1 -mb-px"
          role="tablist"
          aria-label={t('bid_management.tabs_aria', {
            defaultValue: 'Bid management sections',
          })}
          onKeyDown={onTabKeyDown}
        >
          {(
            [
              {
                id: 'packages',
                label: t('bid_management.tab_packages', { defaultValue: 'Packages' }),
                icon: PackageIcon,
              },
              {
                id: 'invitations',
                label: t('bid_management.tab_invitations', { defaultValue: 'Invitations' }),
                icon: Mail,
              },
              {
                id: 'submissions',
                label: t('bid_management.tab_submissions', { defaultValue: 'Submissions' }),
                icon: Inbox,
              },
              {
                id: 'qa',
                label: t('bid_management.tab_qa', { defaultValue: 'Q & A' }),
                icon: HelpCircle,
              },
            ] as { id: Tab; label: string; icon: React.ElementType }[]
          ).map((tabItem) => {
            const Icon = tabItem.icon;
            const isActive = tab === tabItem.id;
            return (
              <button
                key={tabItem.id}
                type="button"
                role="tab"
                id={`bid-tab-${tabItem.id}`}
                aria-selected={isActive}
                aria-controls={`bid-panel-${tabItem.id}`}
                tabIndex={isActive ? 0 : -1}
                onClick={() => {
                  setTab(tabItem.id);
                  setStatusFilter('');
                  setSearch('');
                }}
                className={clsx(
                  'flex items-center gap-2 px-4 py-2.5 text-sm font-medium border-b-2 transition-colors',
                  isActive
                    ? 'border-oe-blue text-oe-blue'
                    : 'border-transparent text-content-secondary hover:text-content-primary',
                )}
              >
                <Icon size={14} />
                {tabItem.label}
              </button>
            );
          })}
        </nav>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <div className="relative flex-1 min-w-[200px] max-w-md">
          <Search
            size={14}
            className="absolute left-3 top-1/2 -translate-y-1/2 text-content-tertiary"
          />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder={t('common.search', { defaultValue: 'Search…' })}
            className={clsx(inputCls, 'pl-8')}
          />
        </div>
        {tab === 'packages' && (
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className={clsx(inputCls, 'max-w-[200px]')}
          >
            <option value="">{t('common.all_statuses', { defaultValue: 'All statuses' })}</option>
            {PACKAGE_STATUSES.map((s) => (
              <option key={s} value={s}>
                {packageStatusLabel(t, s)}
              </option>
            ))}
          </select>
        )}
      </div>

      <Card padding="none">
        {isLoading ? (
          <div className="p-4">
            <SkeletonTable rows={8} columns={5} />
          </div>
        ) : packagesQ.isError ? (
          <RecoveryCard error={packagesQ.error} onRetry={() => packagesQ.refetch()} />
        ) : tab === 'packages' ? (
          <PackageTable
            rows={filteredPackages}
            onSelect={(id) => setSelectedPackageId(id)}
            currency={currentProject?.currency || undefined}
            emptyAction={() => setCreateOpen(true)}
          />
        ) : tab === 'invitations' ? (
          <InvitationsView packages={filteredPackages} />
        ) : tab === 'submissions' ? (
          <SubmissionsLevelingView
            packages={filteredPackages}
            currency={currentProject?.currency || undefined}
          />
        ) : (
          <QAView packages={filteredPackages} />
        )}
      </Card>

      {selectedPackageId && (
        <PackageDrawer
          packageId={selectedPackageId}
          onClose={() => setSelectedPackageId(null)}
          currency={currentProject?.currency || undefined}
        />
      )}

      {createOpen && (
        <CreatePackageModal
          projectId={projectId}
          currency={currentProject?.currency || undefined}
          onClose={() => setCreateOpen(false)}
        />
      )}
    </div>
  );
}

/* ─── Package table ─── */

function PackageTable({
  rows,
  onSelect,
  currency,
  emptyAction,
}: {
  rows: BidPackage[];
  onSelect: (id: string) => void;
  currency?: string;
  emptyAction: () => void;
}) {
  const { t } = useTranslation();
  if (rows.length === 0) {
    return (
      <EmptyState
        icon={<PackageIcon size={22} />}
        title={t('bid_management.empty_packages', { defaultValue: 'No bid packages yet' })}
        description={t('bid_management.empty_packages_desc', {
          defaultValue: 'Bundle scope, invite bidders and award the best offer.',
        })}
        action={{
          label: t('bid_management.new_package', { defaultValue: 'New Package' }),
          onClick: emptyAction,
        }}
      />
    );
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead className="bg-surface-secondary text-content-tertiary text-xs uppercase tracking-wide">
          <tr>
            <th className="px-4 py-2.5 text-left">
              {t('bid_management.code', { defaultValue: 'Code' })}
            </th>
            <th className="px-4 py-2.5 text-left">
              {t('bid_management.title_col', { defaultValue: 'Title' })}
            </th>
            <th className="px-4 py-2.5 text-left">
              {t('bid_management.deadline', { defaultValue: 'Deadline' })}
            </th>
            <th className="px-4 py-2.5 text-left">
              {t('bid_management.status', { defaultValue: 'Status' })}
            </th>
            <th className="px-4 py-2.5 text-right">
              {t('bid_management.budget', { defaultValue: 'Budget' })}
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr
              key={r.id}
              onClick={() => onSelect(r.id)}
              className="border-t border-border-light hover:bg-surface-secondary cursor-pointer"
            >
              <td className="px-4 py-2 font-mono text-xs text-content-secondary">{r.code}</td>
              <td className="px-4 py-2 font-medium truncate max-w-[420px]">{r.title || '—'}</td>
              <td className="px-4 py-2 text-xs text-content-secondary">
                {r.submission_deadline ? <DateDisplay value={r.submission_deadline} /> : '—'}
              </td>
              <td className="px-4 py-2">
                <Badge variant={PACKAGE_STATUS_VARIANT[r.status]} dot>
                  {packageStatusLabel(t, r.status)}
                </Badge>
              </td>
              <td className="px-4 py-2 text-right">
                <MoneyDisplay
                  amount={Number(r.total_budget_estimate) || 0}
                  currency={r.currency || currency}
                />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/* ─── Invitations view ─── */

function InvitationsView({ packages }: { packages: BidPackage[] }) {
  const { t } = useTranslation();
  const [openPkg, setOpenPkg] = useState<string | null>(null);

  if (packages.length === 0) {
    return (
      <EmptyState
        icon={<Mail size={22} />}
        title={t('bid_management.empty_invitations', { defaultValue: 'No invitations to show' })}
        description={t('bid_management.empty_invitations_desc', {
          defaultValue: 'Create a bid package first, then invite bidders.',
        })}
      />
    );
  }

  return (
    <div className="divide-y divide-border-light">
      {packages.map((pkg) => (
        <PackageInvitationsRow
          key={pkg.id}
          pkg={pkg}
          open={openPkg === pkg.id}
          onToggle={() => setOpenPkg(openPkg === pkg.id ? null : pkg.id)}
        />
      ))}
    </div>
  );
}

function PackageInvitationsRow({
  pkg,
  open,
  onToggle,
}: {
  pkg: BidPackage;
  open: boolean;
  onToggle: () => void;
}) {
  const { t } = useTranslation();
  const dashQ = useQuery({
    queryKey: ['bid-management', 'dashboard', pkg.id],
    queryFn: () => packageDashboard(pkg.id),
  });
  const invQ = useQuery({
    queryKey: ['bid-management', 'invitations', pkg.id],
    queryFn: () => listInvitationsForPackage(pkg.id),
    enabled: open,
  });
  const stats = dashQ.data;
  const sent = stats?.invitations_count ?? 0;
  const responded = stats?.submissions_count ?? 0;

  return (
    <div>
      <button
        type="button"
        onClick={onToggle}
        className="w-full flex items-center justify-between px-4 py-3 hover:bg-surface-secondary text-left"
        aria-expanded={open}
      >
        <div className="min-w-0">
          <p className="font-mono text-xs text-content-secondary">{pkg.code}</p>
          <p className="text-sm font-medium truncate">{pkg.title || '—'}</p>
        </div>
        <div className="flex items-center gap-3 text-xs">
          <Badge variant="blue">
            {t('bid_management.sent', { defaultValue: 'Sent' })}: {sent}
          </Badge>
          <Badge variant="success">
            {t('bid_management.responded', { defaultValue: 'Responded' })}: {responded}
          </Badge>
        </div>
      </button>
      {open && (
        <div className="px-4 pb-4">
          {invQ.isLoading ? (
            <SkeletonTable rows={3} columns={4} />
          ) : (invQ.data ?? []).length === 0 ? (
            <p className="text-xs text-content-secondary py-2">
              {t('bid_management.no_invitations', {
                defaultValue: 'No invitations sent for this package yet.',
              })}
            </p>
          ) : (
            <table className="w-full text-xs border border-border-light rounded">
              <thead className="bg-surface-secondary text-content-tertiary uppercase tracking-wide">
                <tr>
                  <th className="px-3 py-2 text-left">
                    {t('bid_management.invitee', { defaultValue: 'Invitee' })}
                  </th>
                  <th className="px-3 py-2 text-left">
                    {t('bid_management.email', { defaultValue: 'Email' })}
                  </th>
                  <th className="px-3 py-2 text-left">
                    {t('bid_management.sent_at', { defaultValue: 'Sent' })}
                  </th>
                  <th className="px-3 py-2 text-left">
                    {t('bid_management.status', { defaultValue: 'Status' })}
                  </th>
                </tr>
              </thead>
              <tbody>
                {(invQ.data ?? []).map((inv) => (
                  <tr key={inv.id} className="border-t border-border-light">
                    <td className="px-3 py-1.5">{inv.invitee_company_name || '—'}</td>
                    <td className="px-3 py-1.5 text-content-secondary">{inv.invitee_email}</td>
                    <td className="px-3 py-1.5 text-content-secondary">
                      {inv.sent_at ? <DateDisplay value={inv.sent_at} /> : '—'}
                    </td>
                    <td className="px-3 py-1.5">
                      <Badge variant={INVITATION_STATUS_VARIANT[inv.status]} dot>
                        {invitationStatusLabel(t, inv.status)}
                      </Badge>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </div>
  );
}

/* ─── Submissions + Bid leveling ─── */

function SubmissionsLevelingView({
  packages,
  currency,
}: {
  packages: BidPackage[];
  currency?: string;
}) {
  const { t } = useTranslation();
  // Controlled selection that *defaults* to the first package even when
  // `packages` arrives after first render — a bare useState(packages[0]?.id)
  // would freeze at '' and the dropdown would look broken.
  const [activePkg, setActivePkg] = useState<string>('');
  const pkg =
    packages.find((p) => p.id === activePkg) || packages[0] || undefined;

  if (!pkg) {
    return (
      <EmptyState
        icon={<Inbox size={22} />}
        title={t('bid_management.empty_submissions', { defaultValue: 'No submissions yet' })}
        description={t('bid_management.empty_submissions_desc', {
          defaultValue: 'Submissions show up here once bidders have replied.',
        })}
      />
    );
  }

  return (
    <div className="p-4 space-y-3">
      <div className="flex items-center gap-2">
        <label className={clsx(labelCls, 'mb-0 mr-1')}>
          {t('bid_management.package', { defaultValue: 'Package' })}
        </label>
        <select
          value={pkg.id}
          onChange={(e) => setActivePkg(e.target.value)}
          className={clsx(inputCls, 'max-w-[420px]')}
        >
          {packages.map((p) => (
            <option key={p.id} value={p.id}>
              {p.code} — {p.title || '—'}
            </option>
          ))}
        </select>
      </div>
      {(pkg.status === 'awarded' || pkg.status === 'cancelled') && (
        <div
          className={clsx(
            'rounded-lg border px-3 py-2 text-xs',
            pkg.status === 'awarded'
              ? 'border-emerald-200 bg-emerald-50 text-emerald-800 dark:border-emerald-900/40 dark:bg-emerald-950/20 dark:text-emerald-200'
              : 'border-rose-200 bg-rose-50 text-rose-800 dark:border-rose-900/40 dark:bg-rose-950/20 dark:text-rose-200',
          )}
        >
          {pkg.status === 'awarded'
            ? t('bid_management.already_awarded', {
                defaultValue:
                  'This package has been awarded. Leveling is read-only, open Contracts to manage the awarded scope.',
              })
            : t('bid_management.pkg_cancelled', {
                defaultValue: 'This package was cancelled, no further awards possible.',
              })}
        </div>
      )}
      <LevelingTable
        packageId={pkg.id}
        currency={pkg.currency || currency}
        awardable={pkg.status !== 'awarded' && pkg.status !== 'cancelled'}
      />
    </div>
  );
}

/** Map the persisted recommended_reason into a localized string.
 *
 * The backend now stores a stable token ("leveling.top_rank") instead of
 * baking English into the DB (audit #6). Older rows may still hold raw
 * English — those are passed through verbatim so nothing breaks.
 */
function levelingReasonLabel(
  t: TFn,
  reason: string,
  companyName: string,
): string {
  if (reason === 'leveling.top_rank') {
    return t('bid_management.reason_top_rank', {
      defaultValue: 'Top rank ({{company}})',
      company: companyName,
    });
  }
  return reason;
}

function LevelingTable({
  packageId,
  currency,
  awardable,
}: {
  packageId: string;
  currency?: string;
  awardable: boolean;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);

  // Server-side, valid-only, currency-safe matrix. The backend filters out
  // invalid (late / currency-mismatched / incomplete) submissions, marks
  // the lowest competitive bid per line (is_low), and only valid bids — all
  // necessarily in the package currency — appear as columns (audit #1, #2, #8).
  const matrixQ = useQuery({
    queryKey: ['bid-management', 'leveling-matrix', packageId],
    queryFn: () => levelingMatrix(packageId),
  });
  const biddersQ = useQuery({
    queryKey: ['bid-management', 'bidders', packageId],
    queryFn: () => listBiddersForPackage(packageId),
  });

  const matrix = matrixQ.data;
  const bidders = biddersQ.data ?? [];

  // Authoritative penalty-adjusted leveling (rank, normalized totals,
  // commercial/technical scores, recommended bidder) — rendered when the
  // user has computed it (audit #4).
  const [leveling, setLeveling] = useState<LevelingTableData | null>(null);

  // logic_confusing fix (audit #6): award used to fire on a single click with
  // an empty decision_summary and an irreversible FSM jump. Now it opens a
  // confirmation dialog with an editable amount and a justification field.
  const [awardTarget, setAwardTarget] = useState<{
    bidderId: string;
    name: string;
    amount: number;
  } | null>(null);

  const computeMut = useMutation({
    mutationFn: async () => {
      // Get-or-create: re-running leveling after a prior run must not 409
      // (audit #3). Then recompute the rows and fetch the table.
      const comparison = await getOrCreateComparison({ package_id: packageId });
      await computeLeveling(comparison.id);
      return levelingTable(comparison.id);
    },
    onSuccess: (table) => {
      setLeveling(table);
      qc.invalidateQueries({ queryKey: ['bid-management', 'leveling-matrix', packageId] });
      addToast({
        type: 'success',
        title: t('bid_management.leveling_done', { defaultValue: 'Leveling computed' }),
      });
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  const awardMut = useMutation({
    mutationFn: async (vars: {
      bidderId: string;
      amount: number;
      decisionSummary: string;
    }) => {
      return awardPackage(packageId, {
        package_id: packageId,
        awarded_bidder_id: vars.bidderId,
        awarded_amount: vars.amount,
        currency,
        decision_summary: vars.decisionSummary,
      });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['bid-management'] });
      setAwardTarget(null);
      addToast({
        type: 'success',
        title: t('bid_management.awarded', { defaultValue: 'Package awarded' }),
      });
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  if (matrixQ.isLoading || biddersQ.isLoading) {
    return <SkeletonTable rows={6} columns={4} />;
  }
  if (matrixQ.isError) {
    return <RecoveryCard error={matrixQ.error} onRetry={() => matrixQ.refetch()} />;
  }

  const columns = matrix
    ? matrix.bidder_ids.map((id, i) => ({ id, name: matrix.bidder_names[i] || id.slice(0, 8) }))
    : [];

  // Per-bidder column totals = sum of competitive line cells in the matrix
  // (all in the package currency, since invalid/foreign bids are excluded).
  const columnTotals = new Map<string, number>();
  for (const col of columns) columnTotals.set(col.id, 0);
  if (matrix) {
    for (const row of matrix.rows) {
      for (const cell of row.cells) {
        if (
          ['included', 'alternative', 'noted'].includes(cell.inclusion_status) &&
          Number(cell.total_price) > 0
        ) {
          columnTotals.set(
            cell.bidder_id,
            (columnTotals.get(cell.bidder_id) ?? 0) + (Number(cell.total_price) || 0),
          );
        }
      }
    }
  }
  const totalValues = Array.from(columnTotals.values()).filter((v) => v > 0);
  const totalMin = totalValues.length ? Math.min(...totalValues) : 0;
  const totalMax = totalValues.length ? Math.max(...totalValues) : 0;

  const recommendedName = leveling?.recommended_bidder_id
    ? bidders.find((b) => b.id === leveling.recommended_bidder_id)?.company_name ||
      leveling.recommended_bidder_id.slice(0, 8)
    : '';

  // logic_confusing fix (audit #4): the Technical column implied an evaluation
  // the UI never captures, so for real (non-seeded) data it was always 0.0 and
  // Score == Commercial. Only show it once a technical score actually exists,
  // so the comparison does not advertise a capability that is not in play.
  const hasTechnicalScores =
    !!leveling && leveling.rows.some((r) => Number(r.technical_score) > 0);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-xs text-content-secondary">
          {t('bid_management.leveling_valid_only', {
            defaultValue:
              'Only valid bids (on time, complete, in the package currency) are compared here.',
          })}
        </p>
        <Button
          size="sm"
          variant="secondary"
          icon={<Calculator size={14} />}
          loading={computeMut.isPending}
          onClick={() => computeMut.mutate()}
        >
          {t('bid_management.run_leveling', { defaultValue: 'Compute Leveling' })}
        </Button>
      </div>

      {columns.length === 0 ? (
        <EmptyState
          icon={<Inbox size={22} />}
          title={t('bid_management.no_valid_submissions', {
            defaultValue: 'No valid bids to compare',
          })}
          description={t('bid_management.no_valid_submissions_desc', {
            defaultValue:
              'Once bidders submit valid priced offers and bidding is opened, leveling appears here.',
          })}
        />
      ) : (
        <>
          {leveling && leveling.rows.length > 0 && (
            <div className="overflow-x-auto rounded-lg border border-border-light">
              <table className="w-full text-sm border-collapse">
                <thead className="bg-surface-secondary text-content-tertiary text-xs uppercase tracking-wide">
                  <tr>
                    <th className="px-3 py-2 text-left">
                      {t('bid_management.rank', { defaultValue: 'Rank' })}
                    </th>
                    <th className="px-3 py-2 text-left">
                      {t('bid_management.bidder', { defaultValue: 'Bidder' })}
                    </th>
                    <th className="px-3 py-2 text-right">
                      {t('bid_management.normalized_total', {
                        defaultValue: 'Adjusted total',
                      })}
                    </th>
                    <th className="px-3 py-2 text-right">
                      {t('bid_management.commercial_score', {
                        defaultValue: 'Commercial',
                      })}
                    </th>
                    {hasTechnicalScores && (
                      <th className="px-3 py-2 text-right">
                        {t('bid_management.technical_score', { defaultValue: 'Technical' })}
                      </th>
                    )}
                    <th className="px-3 py-2 text-right">
                      {t('bid_management.total_score', { defaultValue: 'Score' })}
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {[...leveling.rows]
                    .sort((a, b) => a.rank - b.rank)
                    .map((row) => {
                      const name =
                        bidders.find((b) => b.id === row.bidder_id)?.company_name ||
                        row.bidder_id.slice(0, 8);
                      const isRecommended = row.bidder_id === leveling.recommended_bidder_id;
                      return (
                        <tr
                          key={row.id}
                          className={clsx(
                            'border-t border-border-light',
                            isRecommended && 'bg-emerald-50/60 dark:bg-emerald-950/20',
                          )}
                        >
                          <td className="px-3 py-1.5 tabular-nums">{row.rank}</td>
                          <td className="px-3 py-1.5">
                            <span className="font-medium">{name}</span>
                            {isRecommended && (
                              <Badge variant="success" className="ml-2">
                                {t('bid_management.recommended', {
                                  defaultValue: 'Recommended',
                                })}
                              </Badge>
                            )}
                          </td>
                          <td className="px-3 py-1.5 text-right tabular-nums">
                            <MoneyDisplay amount={Number(row.normalized_total) || 0} currency={currency} />
                          </td>
                          <td className="px-3 py-1.5 text-right tabular-nums">
                            {Number(row.commercial_score).toFixed(1)}
                          </td>
                          {hasTechnicalScores && (
                            <td className="px-3 py-1.5 text-right tabular-nums">
                              {Number(row.technical_score).toFixed(1)}
                            </td>
                          )}
                          <td className="px-3 py-1.5 text-right tabular-nums font-semibold">
                            {Number(row.total_score).toFixed(1)}
                          </td>
                        </tr>
                      );
                    })}
                </tbody>
              </table>
              {leveling.recommended_bidder_id && leveling.recommended_reason && (
                <p className="px-3 py-2 text-xs text-content-secondary border-t border-border-light bg-surface-secondary">
                  {levelingReasonLabel(t, leveling.recommended_reason, recommendedName)}
                </p>
              )}
            </div>
          )}

          <div className="overflow-x-auto">
            <table className="w-full text-sm border-collapse">
              <thead className="bg-surface-secondary text-content-tertiary text-xs uppercase tracking-wide">
                <tr>
                  <th className="px-3 py-2 text-left sticky left-0 z-10 bg-surface-secondary">
                    {t('bid_management.scope_line', { defaultValue: 'Scope line' })}
                  </th>
                  {columns.map((col) => (
                    <th key={col.id} className="px-3 py-2 text-right whitespace-nowrap">
                      {col.name}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {(matrix?.rows ?? []).map((row) => {
                  const cellByBidder = new Map(
                    row.cells.map((c) => [c.bidder_id, c] as const),
                  );
                  return (
                    <tr key={row.line_item_id} className="border-t border-border-light">
                      <td className="px-3 py-1.5 sticky left-0 z-10 bg-surface-primary">
                        <div className="font-mono text-xs text-content-tertiary">
                          {row.line_item_code || '—'}
                        </div>
                        <div className="text-xs truncate max-w-[260px]">
                          {row.description || '—'}
                        </div>
                      </td>
                      {columns.map((col) => {
                        const cell = cellByBidder.get(col.id);
                        const price = cell ? Number(cell.total_price) || 0 : 0;
                        const competitive =
                          cell != null &&
                          ['included', 'alternative', 'noted'].includes(cell.inclusion_status);
                        const cls = cell?.is_low
                          ? 'text-green-700 font-semibold'
                          : 'text-content-primary';
                        return (
                          <td
                            key={col.id}
                            className={clsx('px-3 py-1.5 text-right tabular-nums', cls)}
                          >
                            {competitive && price > 0 ? (
                              <MoneyDisplay amount={price} currency={currency} />
                            ) : (
                              <span className="text-content-tertiary">—</span>
                            )}
                          </td>
                        );
                      })}
                    </tr>
                  );
                })}
                <tr className="border-t-2 border-border bg-surface-secondary font-semibold">
                  <td className="px-3 py-2 sticky left-0 bg-surface-secondary">
                    {t('bid_management.total', { defaultValue: 'Total' })}
                  </td>
                  {columns.map((col) => {
                    const v = columnTotals.get(col.id) ?? 0;
                    const cls =
                      v > 0 && v === totalMin
                        ? 'text-green-700'
                        : v > 0 && v === totalMax && totalMin !== totalMax
                          ? 'text-red-700'
                          : '';
                    return (
                      <td key={col.id} className={clsx('px-3 py-2 text-right tabular-nums', cls)}>
                        {v > 0 ? (
                          <MoneyDisplay amount={v} currency={currency} />
                        ) : (
                          <span className="text-content-tertiary">—</span>
                        )}
                      </td>
                    );
                  })}
                </tr>
                <tr className="border-t border-border-light">
                  <td className="px-3 py-2 sticky left-0 bg-surface-primary text-xs text-content-secondary">
                    {t('bid_management.action', { defaultValue: 'Action' })}
                  </td>
                  {columns.map((col) => (
                    <td key={col.id} className="px-3 py-2 text-right">
                      <Button
                        size="sm"
                        variant="secondary"
                        icon={<Award size={12} />}
                        disabled={!awardable}
                        title={
                          awardable
                            ? t('bid_management.award', { defaultValue: 'Award' })
                            : t('bid_management.award_disabled', {
                                defaultValue: 'Package already awarded or cancelled',
                              })
                        }
                        onClick={() =>
                          setAwardTarget({
                            bidderId: col.id,
                            name: col.name,
                            amount: columnTotals.get(col.id) ?? 0,
                          })
                        }
                      >
                        {t('bid_management.award', { defaultValue: 'Award' })}
                      </Button>
                    </td>
                  ))}
                </tr>
              </tbody>
            </table>
          </div>
        </>
      )}

      {awardTarget && (
        <AwardConfirmModal
          target={awardTarget}
          currency={currency}
          levelingComputed={!!leveling && leveling.rows.length > 0}
          busy={awardMut.isPending}
          onClose={() => setAwardTarget(null)}
          onConfirm={(amount, decisionSummary) =>
            awardMut.mutate({
              bidderId: awardTarget.bidderId,
              amount,
              decisionSummary,
            })
          }
        />
      )}
    </div>
  );
}

/* ─── Award confirmation ─── */

function AwardConfirmModal({
  target,
  currency,
  levelingComputed,
  busy,
  onClose,
  onConfirm,
}: {
  target: { bidderId: string; name: string; amount: number };
  currency?: string;
  levelingComputed: boolean;
  busy: boolean;
  onClose: () => void;
  onConfirm: (amount: number, decisionSummary: string) => void;
}) {
  const { t } = useTranslation();
  const [amount, setAmount] = useState(String(target.amount || 0));
  const [summary, setSummary] = useState('');

  return (
    <WideModal
      open
      onClose={onClose}
      title={t('bid_management.award_confirm_title', { defaultValue: 'Award this package' })}
      subtitle={t('bid_management.award_confirm_subtitle', {
        defaultValue:
          'Awarding is final - the package moves to "Awarded" and cannot be re-opened. Review the bidder, amount and reason before confirming.',
      })}
      size="md"
      busy={busy}
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={busy}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button
            variant="primary"
            icon={<Award size={14} />}
            loading={busy}
            onClick={() => onConfirm(Number(amount) || 0, summary.trim())}
          >
            {t('bid_management.confirm_award', { defaultValue: 'Confirm award' })}
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        {!levelingComputed && (
          <div className="flex items-start gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800 dark:border-amber-900/40 dark:bg-amber-950/20 dark:text-amber-200">
            <Info size={14} className="mt-0.5 shrink-0" />
            <span>
              {t('bid_management.award_no_leveling', {
                defaultValue:
                  'Leveling has not been computed yet. Consider running Compute Leveling first so the recommendation is based on adjusted scores.',
              })}
            </span>
          </div>
        )}
        <div>
          <label className={labelCls}>
            {t('bid_management.awarded_bidder', { defaultValue: 'Awarded bidder' })}
          </label>
          <p className="text-sm font-medium text-content-primary">{target.name}</p>
        </div>
        <div>
          <label className={labelCls}>
            {t('bid_management.awarded_amount', { defaultValue: 'Awarded amount' })}
          </label>
          <input
            type="number"
            min="0"
            step="any"
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
            className={clsx(inputCls, 'text-right')}
          />
          <p className="mt-1 text-xs text-content-tertiary">
            {currency || ''} - {t('bid_management.awarded_amount_hint', {
              defaultValue: 'Pre-filled from the column total; adjust if a negotiated figure applies.',
            })}
          </p>
        </div>
        <div>
          <label className={labelCls}>
            {t('bid_management.decision_summary', { defaultValue: 'Decision summary' })}
          </label>
          <textarea
            value={summary}
            onChange={(e) => setSummary(e.target.value)}
            rows={3}
            placeholder={t('bid_management.decision_summary_placeholder', {
              defaultValue: 'Why this bidder was selected (kept on the award record).',
            })}
            className={clsx(inputCls, 'h-auto py-2 resize-y')}
          />
        </div>
      </div>
    </WideModal>
  );
}

/* ─── Q & A view ─── */

function QAView({ packages }: { packages: BidPackage[] }) {
  const { t } = useTranslation();
  const [activePkg, setActivePkg] = useState<string>('');

  if (packages.length === 0) {
    return (
      <EmptyState
        icon={<HelpCircle size={22} />}
        title={t('bid_management.empty_qa', { defaultValue: 'No Q&A to show' })}
        description={t('bid_management.empty_qa_desc', {
          defaultValue: 'Bidder questions and clarifications will appear here.',
        })}
      />
    );
  }

  const pkg = packages.find((p) => p.id === activePkg) ?? packages[0];
  if (!pkg) return null;

  return (
    <div className="p-4 space-y-3">
      <div className="flex items-center gap-2">
        <label className={clsx(labelCls, 'mb-0 mr-1')}>
          {t('bid_management.package', { defaultValue: 'Package' })}
        </label>
        <select
          value={pkg.id}
          onChange={(e) => setActivePkg(e.target.value)}
          className={clsx(inputCls, 'max-w-[420px]')}
        >
          {packages.map((p) => (
            <option key={p.id} value={p.id}>
              {p.code} — {p.title || '—'}
            </option>
          ))}
        </select>
      </div>
      <QAList packageId={pkg.id} />
    </div>
  );
}

function QAList({ packageId }: { packageId: string }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);

  const qaQ = useQuery({
    queryKey: ['bid-management', 'qa', packageId],
    queryFn: () => listQAForPackage(packageId),
  });

  const [question, setQuestion] = useState('');
  const [askerEmail, setAskerEmail] = useState('');
  const askMut = useMutation({
    mutationFn: () =>
      createQA({
        package_id: packageId,
        question: question.trim(),
        asked_by_email: askerEmail.trim(),
        is_public: true,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['bid-management', 'qa', packageId] });
      setQuestion('');
      addToast({
        type: 'success',
        title: t('bid_management.question_posted', { defaultValue: 'Question posted' }),
      });
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  if (qaQ.isLoading) return <SkeletonTable rows={4} columns={2} />;

  const rows = qaQ.data ?? [];

  return (
    <div className="space-y-3">
      <Card padding="sm">
        <p className="text-xs font-semibold text-content-secondary uppercase tracking-wide mb-2">
          {t('bid_management.post_question', { defaultValue: 'Post a question' })}
        </p>
        <div className="space-y-2">
          <input
            value={askerEmail}
            onChange={(e) => setAskerEmail(e.target.value)}
            placeholder={t('bid_management.your_email', { defaultValue: 'Your email' })}
            className={inputCls}
          />
          <textarea
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            placeholder={t('bid_management.question_placeholder', {
              defaultValue: 'Type your question…',
            })}
            rows={2}
            className={clsx(inputCls, 'h-auto py-2')}
          />
          <Button
            variant="primary"
            icon={<Send size={14} />}
            disabled={!question.trim()}
            loading={askMut.isPending}
            onClick={() => askMut.mutate()}
          >
            {t('bid_management.post', { defaultValue: 'Post' })}
          </Button>
        </div>
      </Card>

      {rows.length === 0 ? (
        <EmptyState
          icon={<HelpCircle size={22} />}
          title={t('bid_management.no_questions', { defaultValue: 'No questions yet' })}
          description={t('bid_management.no_questions_desc', {
            defaultValue: 'Be the first to ask. Replies are shared with all bidders by default.',
          })}
        />
      ) : (
        <div className="space-y-2">
          {rows.map((qa) => (
            <QAItem key={qa.id} qa={qa} packageId={packageId} />
          ))}
        </div>
      )}
    </div>
  );
}

function QAItem({ qa, packageId }: { qa: BidQA; packageId: string }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [answer, setAnswer] = useState('');
  const answerMut = useMutation({
    mutationFn: () => answerQA(qa.id, { answer: answer.trim(), is_public: true }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['bid-management', 'qa', packageId] });
      setAnswer('');
      addToast({
        type: 'success',
        title: t('bid_management.answer_posted', { defaultValue: 'Answer posted' }),
      });
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  return (
    <Card padding="sm">
      <div className="flex items-start gap-2">
        <Badge variant={qa.is_public ? 'success' : 'neutral'}>
          {qa.is_public
            ? t('bid_management.public', { defaultValue: 'public' })
            : t('bid_management.private', { defaultValue: 'private' })}
        </Badge>
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium whitespace-pre-wrap">{qa.question}</p>
          <p className="mt-0.5 text-xs text-content-tertiary">
            {qa.asked_by_email || '—'}
            {qa.asked_at && (
              <>
                {' · '}
                <DateDisplay value={qa.asked_at} />
              </>
            )}
          </p>
          {qa.answer ? (
            <div className="mt-2 rounded bg-surface-secondary p-2">
              <p className="text-xs uppercase tracking-wide text-content-tertiary">
                {t('bid_management.answer', { defaultValue: 'Answer' })}
              </p>
              <p className="text-sm whitespace-pre-wrap">{qa.answer}</p>
            </div>
          ) : (
            <div className="mt-2 flex gap-2">
              <input
                value={answer}
                onChange={(e) => setAnswer(e.target.value)}
                placeholder={t('bid_management.answer_placeholder', {
                  defaultValue: 'Write an answer…',
                })}
                className={inputCls}
              />
              <Button
                variant="secondary"
                size="sm"
                disabled={!answer.trim()}
                loading={answerMut.isPending}
                onClick={() => answerMut.mutate()}
              >
                {t('bid_management.reply', { defaultValue: 'Reply' })}
              </Button>
            </div>
          )}
        </div>
      </div>
    </Card>
  );
}

/* ─── Package Drawer ─── */

function PackageDrawer({
  packageId,
  onClose,
  currency,
}: {
  packageId: string;
  onClose: () => void;
  currency?: string;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);

  // unwired fix (audit #1): there was no way to record a bidder's priced
  // submission, so leveling/award were inert for real packages. This holds the
  // invitation a manager is recording a bid against.
  const [recordFor, setRecordFor] = useState<BidInvitation | null>(null);

  const pkgQ = useQuery({
    queryKey: ['bid-management', 'package', packageId],
    queryFn: () => getPackage(packageId),
  });
  const linesQ = useQuery({
    queryKey: ['bid-management', 'lines', packageId],
    queryFn: () => listLineItemsForPackage(packageId),
  });
  const invQ = useQuery({
    queryKey: ['bid-management', 'invitations', packageId],
    queryFn: () => listInvitationsForPackage(packageId),
  });
  const subsQ = useQuery({
    queryKey: ['bid-management', 'submissions', packageId],
    queryFn: () => listSubmissionsForPackage(packageId),
  });

  const publishMut = useMutation({
    mutationFn: () => publishPackage(packageId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['bid-management'] });
      addToast({
        type: 'success',
        title: t('bid_management.published', { defaultValue: 'Package published' }),
      });
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  // dead_button fix: wire the previously-unused openBids() so a published
  // package can advance to "open". open_bids is the ONLY backend path that runs
  // pre-open validation and sets submission.is_valid=True, which leveling and
  // award depend on. Without this button the workflow was unreachable.
  const openBidsMut = useMutation({
    mutationFn: () => openBids(packageId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['bid-management'] });
      addToast({
        type: 'success',
        title: t('bid_management.bids_opened', { defaultValue: 'Bidding opened' }),
      });
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  const closeMut = useMutation({
    mutationFn: () => closePackage(packageId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['bid-management'] });
      addToast({
        type: 'success',
        title: t('bid_management.closed_pkg', { defaultValue: 'Package closed' }),
      });
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  const compareMut = useMutation({
    mutationFn: async () => {
      // Get-or-create so re-running leveling never 409s (audit #3).
      const c = await getOrCreateComparison({ package_id: packageId });
      await computeLeveling(c.id);
      return levelingTable(c.id);
    },
    onSuccess: (table) => {
      qc.invalidateQueries({ queryKey: ['bid-management'] });
      // Surface the authoritative recommendation rather than discarding it
      // (audit #4). The full penalty-adjusted ranking is rendered in the
      // Submissions tab's leveling table.
      addToast({
        type: 'success',
        title:
          table.recommended_bidder_id && table.recommended_reason
            ? t('bid_management.leveling_done_with_rec', {
                defaultValue: 'Leveling computed, top bid identified. Open Submissions to review the ranking.',
              })
            : t('bid_management.leveling_done', { defaultValue: 'Leveling computed' }),
      });
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  const pkg = pkgQ.data;

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-50 flex justify-end" onClick={onClose}>
      <div className="absolute inset-0 bg-black/30" />
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="bid-package-drawer-title"
        className="relative h-full w-full max-w-2xl overflow-y-auto bg-surface-elevated shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="sticky top-0 z-10 flex items-center justify-between border-b border-border-light bg-surface-elevated px-5 py-3">
          <h2 id="bid-package-drawer-title" className="text-base font-semibold">
            {pkg ? pkg.code : '…'}
          </h2>
          <button
            type="button"
            onClick={onClose}
            className="rounded p-1 hover:bg-surface-secondary"
            aria-label={t('common.close', { defaultValue: 'Close' })}
          >
            <X size={16} />
          </button>
        </div>

        <div className="space-y-4 p-5">
          {pkgQ.isError ? (
            <EmptyState
              icon={<XCircle size={22} />}
              title={t('bid_management.package_load_failed', {
                defaultValue: 'Could not load this package',
              })}
              description={getErrorMessage(pkgQ.error)}
              action={{
                label: t('common.retry', { defaultValue: 'Retry' }),
                onClick: () => pkgQ.refetch(),
              }}
            />
          ) : pkgQ.isLoading || !pkg ? (
            <SkeletonTable rows={4} columns={2} />
          ) : (
            <>
              <div>
                <p className="text-lg font-semibold">{pkg.title || '—'}</p>
                <p className="mt-1 text-sm text-content-secondary whitespace-pre-wrap">
                  {pkg.scope_description || '—'}
                </p>
              </div>
              <div className="grid grid-cols-2 gap-3 text-sm">
                <Field
                  label={t('bid_management.status')}
                  value={
                    <Badge variant={PACKAGE_STATUS_VARIANT[pkg.status]} dot>
                      {packageStatusLabel(t, pkg.status)}
                    </Badge>
                  }
                />
                <Field
                  label={t('bid_management.confidentiality', { defaultValue: 'Confidentiality' })}
                  value={confidentialityLabel(t, pkg.confidentiality_level)}
                />
                <Field
                  label={t('bid_management.deadline')}
                  value={pkg.submission_deadline ? <DateDisplay value={pkg.submission_deadline} /> : '—'}
                />
                <Field
                  label={t('bid_management.decision_due', { defaultValue: 'Decision due' })}
                  value={pkg.decision_due_by ? <DateDisplay value={pkg.decision_due_by} /> : '—'}
                />
                <Field
                  label={t('bid_management.budget')}
                  value={
                    <MoneyDisplay
                      amount={Number(pkg.total_budget_estimate) || 0}
                      currency={pkg.currency || currency}
                    />
                  }
                />
                <Field
                  label={t('bid_management.published_at', { defaultValue: 'Published' })}
                  value={pkg.published_at ? <DateDisplay value={pkg.published_at} /> : '—'}
                />
              </div>

              {/* missing_help fix (audit #8): explain the required FSM sequence
                  so a user knows why leveling/award stay empty until they walk
                  publish → open bids → record submissions → level → award. */}
              <div className="flex items-start gap-2 rounded-lg border border-border-light bg-surface-secondary px-3 py-2 text-xs text-content-secondary">
                <Info size={14} className="mt-0.5 shrink-0 text-oe-blue" />
                <span>
                  {t('bid_management.workflow_hint', {
                    defaultValue:
                      "Sequence: Publish the package, add scope lines and invite bidders, then Open Bids (this validates the offers). Record each bidder's priced submission, Compute Leveling, and Award. Leveling and award stay empty until valid submissions exist.",
                  })}
                </span>
              </div>

              <div className="flex flex-wrap gap-2 pt-2 border-t border-border-light">
                {pkg.status === 'draft' && (
                  <Button
                    variant="primary"
                    icon={<Send size={14} />}
                    onClick={() => publishMut.mutate()}
                    loading={publishMut.isPending}
                  >
                    {t('bid_management.publish', { defaultValue: 'Publish' })}
                  </Button>
                )}
                {/* dead_button fix: expose Open Bids (published → open). This is the
                    only action that validates submissions (is_valid) so leveling
                    and award become reachable instead of being silently blocked. */}
                {pkg.status === 'published' && (
                  <Button
                    variant="primary"
                    icon={<Inbox size={14} />}
                    onClick={() => openBidsMut.mutate()}
                    loading={openBidsMut.isPending}
                  >
                    {t('bid_management.open_bids', { defaultValue: 'Open Bids' })}
                  </Button>
                )}
                {/* open_bids is idempotent and re-validates every submission, so
                    expose it again on an already-open package — a bid recorded
                    after opening needs re-validation to become is_valid and
                    appear in leveling. */}
                {pkg.status === 'open' && (
                  <Button
                    variant="secondary"
                    icon={<Inbox size={14} />}
                    onClick={() => openBidsMut.mutate()}
                    loading={openBidsMut.isPending}
                    title={t('bid_management.revalidate_bids_hint', {
                      defaultValue: 'Re-check submitted bids and refresh which ones count as valid.',
                    })}
                  >
                    {t('bid_management.revalidate_bids', { defaultValue: 'Re-validate bids' })}
                  </Button>
                )}
                {(pkg.status === 'open' || pkg.status === 'published') && (
                  <Button
                    variant="secondary"
                    icon={<XCircle size={14} />}
                    onClick={() => closeMut.mutate()}
                    loading={closeMut.isPending}
                  >
                    {t('bid_management.close_pkg', { defaultValue: 'Close Bidding' })}
                  </Button>
                )}
                <Button
                  variant="secondary"
                  icon={<Calculator size={14} />}
                  onClick={() => compareMut.mutate()}
                  loading={compareMut.isPending}
                >
                  {t('bid_management.run_leveling', { defaultValue: 'Compute Leveling' })}
                </Button>
                {pkg.status === 'awarded' && (
                  <Link to="/contracts">
                    <Button variant="primary" icon={<ArrowRight size={14} />}>
                      {t('bid_management.create_contract', {
                        defaultValue: 'Formalise as Contract',
                      })}
                    </Button>
                  </Link>
                )}
              </div>

              <Card padding="sm">
                <p className="text-xs font-semibold uppercase tracking-wide text-content-secondary mb-2">
                  {t('bid_management.scope_lines', { defaultValue: 'Scope lines' })}
                </p>
                {linesQ.isLoading ? (
                  <SkeletonTable rows={3} columns={3} />
                ) : (linesQ.data ?? []).length === 0 ? (
                  <p className="text-xs text-content-tertiary">
                    {t('bid_management.no_lines', {
                      defaultValue:
                        'No scope lines yet. Add the items being tendered below - bidders price these, and they become the rows of the leveling matrix.',
                    })}
                  </p>
                ) : (
                  <table className="w-full text-xs">
                    <thead className="text-content-tertiary uppercase">
                      <tr>
                        <th className="text-left py-1">
                          {t('bid_management.code', { defaultValue: 'Code' })}
                        </th>
                        <th className="text-left py-1">
                          {t('bid_management.description', { defaultValue: 'Description' })}
                        </th>
                        <th className="text-right py-1">
                          {t('bid_management.qty', { defaultValue: 'Qty' })}
                        </th>
                        <th className="text-left py-1">
                          {t('bid_management.unit', { defaultValue: 'Unit' })}
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {(linesQ.data ?? []).map((li) => (
                        <tr key={li.id} className="border-t border-border-light">
                          <td className="py-1 font-mono">{li.code || '—'}</td>
                          <td className="py-1 truncate max-w-[300px]">{li.description || '—'}</td>
                          <td className="py-1 text-right tabular-nums">{Number(li.quantity)}</td>
                          <td className="py-1 text-content-secondary">{li.unit || '—'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
                {/* unwired fix (audit #2): scope lines could only be displayed,
                    never created. createLineItem now wires an inline editor so
                    the leveling matrix has rows for real (non-seeded) packages. */}
                <AddScopeLineForm
                  packageId={packageId}
                  nextOrderIndex={(linesQ.data ?? []).length}
                />
              </Card>

              <Card padding="sm">
                <p className="text-xs font-semibold uppercase tracking-wide text-content-secondary mb-2">
                  {t('bid_management.invitations_list', { defaultValue: 'Invitations' })}
                </p>
                {invQ.isLoading ? (
                  <SkeletonTable rows={3} columns={3} />
                ) : (invQ.data ?? []).length === 0 ? (
                  <p className="text-xs text-content-tertiary">
                    {t('bid_management.no_invitations', {
                      defaultValue: 'No invitations sent for this package yet.',
                    })}
                  </p>
                ) : (
                  <ul className="space-y-1 text-xs">
                    {(invQ.data ?? []).map((inv) => {
                      // An invitation that already produced a submission cannot
                      // be recorded again (the backend enforces one submission
                      // per invitation with a UNIQUE constraint → 409).
                      const hasSubmission = (subsQ.data ?? []).some(
                        (s) => s.invitation_id === inv.id,
                      );
                      const canRecord =
                        !hasSubmission &&
                        !!inv.bidder_ref_id &&
                        pkg.status !== 'awarded' &&
                        pkg.status !== 'cancelled';
                      return (
                        <li
                          key={inv.id}
                          className="flex items-center justify-between gap-2 border-b border-border-light pb-1 last:border-b-0"
                        >
                          <span className="min-w-0 flex-1 truncate">
                            <span className="font-medium">{inv.invitee_company_name || '—'}</span>
                            <span className="ml-2 text-content-tertiary">{inv.invitee_email}</span>
                          </span>
                          <Badge variant={INVITATION_STATUS_VARIANT[inv.status]} dot>
                            {invitationStatusLabel(t, inv.status)}
                          </Badge>
                          {canRecord && (
                            <Button
                              size="sm"
                              variant="ghost"
                              icon={<FileText size={12} />}
                              onClick={() => setRecordFor(inv)}
                            >
                              {t('bid_management.record_bid', { defaultValue: 'Record bid' })}
                            </Button>
                          )}
                        </li>
                      );
                    })}
                  </ul>
                )}
              </Card>

              <InlineInviteForm packageId={packageId} />

              {subsQ.data && subsQ.data.length > 0 && (
                <Card padding="sm">
                  <p className="text-xs font-semibold uppercase tracking-wide text-content-secondary mb-2">
                    {t('bid_management.submissions_summary', {
                      defaultValue: 'Submissions summary',
                    })}
                  </p>
                  <ul className="space-y-1 text-xs">
                    {subsQ.data.map((sub) => (
                      <li key={sub.id} className="flex items-center justify-between">
                        <span className="font-mono text-content-tertiary">
                          {sub.id.slice(0, 8)}
                        </span>
                        <span>
                          <MoneyDisplay
                            amount={Number(sub.total_amount) || 0}
                            currency={sub.currency || currency}
                          />
                        </span>
                      </li>
                    ))}
                  </ul>
                </Card>
              )}
            </>
          )}
        </div>
      </div>

      {recordFor && pkg && (
        <RecordBidModal
          invitation={recordFor}
          currency={pkg.currency || currency}
          lineItems={linesQ.data ?? []}
          onClose={() => setRecordFor(null)}
        />
      )}
    </div>
  );
}

/* ─── Add a scope line (inline editor) ─── */

function AddScopeLineForm({
  packageId,
  nextOrderIndex,
}: {
  packageId: string;
  nextOrderIndex: number;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [code, setCode] = useState('');
  const [description, setDescription] = useState('');
  const [unit, setUnit] = useState('');
  const [quantity, setQuantity] = useState('1');

  const addMut = useMutation({
    mutationFn: () =>
      createLineItem({
        package_id: packageId,
        code: code.trim(),
        description: description.trim(),
        unit: unit.trim(),
        quantity: Number(quantity) || 0,
        order_index: nextOrderIndex,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['bid-management', 'lines', packageId] });
      qc.invalidateQueries({ queryKey: ['bid-management', 'leveling-matrix', packageId] });
      setCode('');
      setDescription('');
      setUnit('');
      setQuantity('1');
      addToast({
        type: 'success',
        title: t('bid_management.scope_line_added', { defaultValue: 'Scope line added' }),
      });
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  return (
    <div className="mt-3 grid grid-cols-[minmax(60px,0.6fr)_minmax(0,2fr)_minmax(50px,0.6fr)_minmax(50px,0.6fr)_auto] items-end gap-2 border-t border-border-light pt-3">
      <div>
        <label className={labelCls}>{t('bid_management.code', { defaultValue: 'Code' })}</label>
        <input
          value={code}
          onChange={(e) => setCode(e.target.value)}
          placeholder="01.001"
          className={inputCls}
        />
      </div>
      <div>
        <label className={labelCls}>
          {t('bid_management.description', { defaultValue: 'Description' })}
        </label>
        <input
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder={t('bid_management.scope_line_desc_placeholder', {
            defaultValue: 'Reinforced concrete wall',
          })}
          className={inputCls}
        />
      </div>
      <div>
        <label className={labelCls}>{t('bid_management.qty', { defaultValue: 'Qty' })}</label>
        <input
          type="number"
          min="0"
          step="any"
          value={quantity}
          onChange={(e) => setQuantity(e.target.value)}
          className={clsx(inputCls, 'text-right')}
        />
      </div>
      <div>
        <label className={labelCls}>{t('bid_management.unit', { defaultValue: 'Unit' })}</label>
        <input
          value={unit}
          onChange={(e) => setUnit(e.target.value)}
          placeholder="m²"
          className={inputCls}
        />
      </div>
      <Button
        size="sm"
        variant="secondary"
        icon={<ListPlus size={14} />}
        disabled={!description.trim()}
        loading={addMut.isPending}
        onClick={() => addMut.mutate()}
      >
        {t('bid_management.add_line', { defaultValue: 'Add' })}
      </Button>
    </div>
  );
}

/* ─── Record a bidder's priced submission ─── */

function RecordBidModal({
  invitation,
  currency,
  lineItems,
  onClose,
}: {
  invitation: BidInvitation;
  currency?: string;
  lineItems: BidPackageLineItem[];
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);

  // One editable unit-price per scope line. The submission total is derived
  // from the priced lines so leveling reads consistent figures (audit #1).
  const [prices, setPrices] = useState<Record<string, string>>({});
  const [notes, setNotes] = useState('');
  const [busy, setBusy] = useState(false);

  const computedTotal = useMemo(() => {
    return lineItems.reduce((acc, li) => {
      const unitPrice = Number(prices[li.id] ?? '');
      if (!Number.isFinite(unitPrice) || unitPrice <= 0) return acc;
      return acc + unitPrice * (Number(li.quantity) || 0);
    }, 0);
  }, [lineItems, prices]);

  const submit = async () => {
    if (!invitation.bidder_ref_id) {
      addToast({
        type: 'error',
        title: t('bid_management.record_bid_no_bidder', {
          defaultValue: 'This invitation has no linked bidder to record against.',
        }),
      });
      return;
    }
    setBusy(true);
    try {
      // 1) Create the submission envelope (priced, in the package currency).
      const submission = await createSubmission({
        invitation_id: invitation.id,
        bidder_id: invitation.bidder_ref_id,
        total_amount: computedTotal,
        currency: currency || '',
        notes_to_owner: notes.trim(),
      });
      // 2) Bulk-create one priced line per scope line that has a price.
      const items = lineItems
        .map((li) => ({
          line_item_id: li.id,
          unit_price: Number(prices[li.id] ?? '') || 0,
          quantity_priced: Number(li.quantity) || 0,
          inclusion_status: 'included',
        }))
        .filter((i) => i.unit_price > 0);
      if (items.length > 0) {
        await bulkCreateSubmissionLines(submission.id, items);
      }
      qc.invalidateQueries({ queryKey: ['bid-management'] });
      addToast({
        type: 'success',
        title: t('bid_management.bid_recorded', { defaultValue: 'Bid recorded' }),
      });
      onClose();
    } catch (err) {
      addToast({ type: 'error', title: getErrorMessage(err) });
    } finally {
      setBusy(false);
    }
  };

  return (
    <WideModal
      open
      onClose={onClose}
      title={t('bid_management.record_bid_title', { defaultValue: 'Record bid' })}
      subtitle={t('bid_management.record_bid_subtitle', {
        defaultValue:
          'Enter the unit prices this bidder quoted for each scope line. The total and the side-by-side leveling matrix are built from these figures.',
      })}
      size="lg"
      busy={busy}
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={busy}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button
            variant="primary"
            onClick={submit}
            loading={busy}
            icon={<FileText size={14} />}
          >
            {t('bid_management.save_bid', { defaultValue: 'Save bid' })}
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        <p className="text-xs text-content-secondary">
          {t('bid_management.record_bid_for', {
            defaultValue: 'Bidder: {{company}} ({{email}})',
            company: invitation.invitee_company_name || '—',
            email: invitation.invitee_email,
          })}
        </p>
        {lineItems.length === 0 ? (
          <EmptyState
            icon={<ListPlus size={22} />}
            title={t('bid_management.no_lines_to_price', {
              defaultValue: 'Add scope lines first',
            })}
            description={t('bid_management.no_lines_to_price_desc', {
              defaultValue:
                'A priced bid needs scope lines. Add them in the package drawer, then record prices here.',
            })}
          />
        ) : (
          <div className="overflow-x-auto rounded-lg border border-border-light">
            <table className="w-full text-sm">
              <thead className="bg-surface-secondary text-content-tertiary text-xs uppercase tracking-wide">
                <tr>
                  <th className="px-3 py-2 text-left">
                    {t('bid_management.scope_line', { defaultValue: 'Scope line' })}
                  </th>
                  <th className="px-3 py-2 text-right">
                    {t('bid_management.qty', { defaultValue: 'Qty' })}
                  </th>
                  <th className="px-3 py-2 text-right">
                    {t('bid_management.unit_price', { defaultValue: 'Unit price' })}
                  </th>
                  <th className="px-3 py-2 text-right">
                    {t('bid_management.line_total', { defaultValue: 'Line total' })}
                  </th>
                </tr>
              </thead>
              <tbody>
                {lineItems.map((li) => {
                  const unitPrice = Number(prices[li.id] ?? '');
                  const lineTotal =
                    Number.isFinite(unitPrice) && unitPrice > 0
                      ? unitPrice * (Number(li.quantity) || 0)
                      : 0;
                  return (
                    <tr key={li.id} className="border-t border-border-light">
                      <td className="px-3 py-1.5">
                        <div className="font-mono text-xs text-content-tertiary">
                          {li.code || '—'}
                        </div>
                        <div className="text-xs truncate max-w-[260px]">
                          {li.description || '—'}
                        </div>
                      </td>
                      <td className="px-3 py-1.5 text-right tabular-nums text-xs text-content-secondary">
                        {Number(li.quantity)} {li.unit}
                      </td>
                      <td className="px-3 py-1.5 text-right">
                        <input
                          type="number"
                          min="0"
                          step="any"
                          value={prices[li.id] ?? ''}
                          onChange={(e) =>
                            setPrices((p) => ({ ...p, [li.id]: e.target.value }))
                          }
                          placeholder="0.00"
                          className={clsx(inputCls, 'h-8 w-28 text-right')}
                        />
                      </td>
                      <td className="px-3 py-1.5 text-right tabular-nums">
                        {lineTotal > 0 ? (
                          <MoneyDisplay amount={lineTotal} currency={currency} />
                        ) : (
                          <span className="text-content-tertiary">—</span>
                        )}
                      </td>
                    </tr>
                  );
                })}
                <tr className="border-t-2 border-border bg-surface-secondary font-semibold">
                  <td className="px-3 py-2" colSpan={3}>
                    {t('bid_management.total', { defaultValue: 'Total' })}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">
                    <MoneyDisplay amount={computedTotal} currency={currency} />
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        )}
        <div>
          <label className={labelCls}>
            {t('bid_management.notes_to_owner', { defaultValue: 'Notes / qualifications' })}
          </label>
          <textarea
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            rows={2}
            className={clsx(inputCls, 'h-auto py-2 resize-y')}
          />
        </div>
      </div>
    </WideModal>
  );
}

function InlineInviteForm({ packageId }: { packageId: string }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [email, setEmail] = useState('');
  const [company, setCompany] = useState('');
  // CONN-39: invite straight from the Subcontractor Directory instead of
  // retyping a firm by hand, prefilling the company and its primary contact.
  const [pickerOpen, setPickerOpen] = useState(false);
  const inviteMut = useMutation({
    mutationFn: async () => {
      const bidder = await createBidder({
        package_id: packageId,
        company_name: company.trim() || email.trim(),
        contact_email: email.trim(),
      });
      return createInvitation({
        package_id: packageId,
        bidder_ref_id: bidder.id,
        invitee_email: email.trim(),
        invitee_company_name: company.trim(),
      });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['bid-management'] });
      setEmail('');
      setCompany('');
      // quick_win clarity (audit #9): the invite is recorded and marked "sent",
      // but actual email delivery depends on SMTP being configured. Say so
      // instead of implying mail definitely went out.
      addToast({
        type: 'success',
        title: t('bid_management.invite_sent', { defaultValue: 'Bidder invited' }),
        message: t('bid_management.invite_sent_detail', {
          defaultValue: 'Recorded as invited. Email delivery requires SMTP to be configured.',
        }),
      });
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  return (
    <Card padding="sm">
      <div className="mb-2 flex items-center justify-between gap-2">
        <p className="text-xs font-semibold uppercase tracking-wide text-content-secondary">
          {t('bid_management.invite_bidder', { defaultValue: 'Invite a bidder' })}
        </p>
        <Button
          size="sm"
          variant="ghost"
          icon={<Users size={14} />}
          onClick={() => setPickerOpen(true)}
        >
          {t('bid_management.pick_from_directory', {
            defaultValue: 'Pick from Subcontractors',
          })}
        </Button>
      </div>
      <div className="space-y-2">
        <input
          value={company}
          onChange={(e) => setCompany(e.target.value)}
          placeholder={t('bid_management.company', { defaultValue: 'Company' })}
          className={inputCls}
        />
        <input
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          placeholder={t('bid_management.email', { defaultValue: 'Email' })}
          className={inputCls}
        />
        <Button
          variant="primary"
          icon={<Send size={14} />}
          disabled={!email.trim()}
          loading={inviteMut.isPending}
          onClick={() => inviteMut.mutate()}
        >
          {t('bid_management.invite', { defaultValue: 'Invite' })}
        </Button>
      </div>
      {pickerOpen && (
        <SubcontractorPickerModal
          onPick={(sub, resolvedEmail) => {
            setCompany(sub.legal_name);
            if (resolvedEmail) setEmail(resolvedEmail);
            if (!resolvedEmail) {
              addToast({
                type: 'info',
                title: t('bid_management.sub_no_email', {
                  defaultValue: 'No contact email on file - enter one to invite.',
                }),
              });
            }
          }}
          onClose={() => setPickerOpen(false)}
        />
      )}
    </Card>
  );
}

function Field({ label, value }: { label: React.ReactNode; value: React.ReactNode }) {
  return (
    <div>
      <p className="text-xs uppercase tracking-wide text-content-tertiary">{label}</p>
      <p className="mt-0.5 text-sm text-content-primary">{value}</p>
    </div>
  );
}

/* ─── Create package modal ─── */

function CreatePackageModal({
  projectId,
  currency,
  onClose,
}: {
  projectId: string;
  currency?: string;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [form, setForm] = useState({
    code: '',
    title: '',
    scope_description: '',
    submission_deadline: '',
    // Seed the currency input from the project currency when known. When
    // the project has none configured, start blank (rather than a guessed
    // EUR) so the user must enter an explicit ISO-4217 code.
    currency: currency ?? '',
    total_budget_estimate: '0',
  });
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    if (!form.code.trim()) {
      addToast({
        type: 'error',
        title: t('bid_management.code_required', { defaultValue: 'Code is required' }),
      });
      return;
    }
    setBusy(true);
    try {
      await createPackage({
        project_id: projectId,
        code: form.code.trim(),
        title: form.title.trim(),
        scope_description: form.scope_description.trim(),
        submission_deadline: form.submission_deadline || null,
        currency: form.currency.trim() || currency,
        total_budget_estimate: Number(form.total_budget_estimate) || 0,
      });
      qc.invalidateQueries({ queryKey: ['bid-management'] });
      addToast({
        type: 'success',
        title: t('bid_management.package_created', { defaultValue: 'Package created' }),
      });
      onClose();
    } catch (err) {
      addToast({ type: 'error', title: getErrorMessage(err) });
    } finally {
      setBusy(false);
    }
  };

  return (
    <WideModal
      open
      onClose={onClose}
      title={t('bid_management.new_package', { defaultValue: 'New bid package' })}
      subtitle={t('bid_management.new_package_subtitle', {
        defaultValue:
          'A bid package groups the scope you are putting out to tender. After you create it, add bidders and send invitations from the package detail view.',
      })}
      size="lg"
      busy={busy}
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={busy}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button
            variant="primary"
            onClick={submit}
            loading={busy}
            icon={busy ? <Loader2 size={14} /> : <Plus size={14} />}
          >
            {t('common.create', { defaultValue: 'Create' })}
          </Button>
        </>
      }
    >
      <WideModalSection columns={2}>
        <WideModalField
          label={t('bid_management.code', { defaultValue: 'Code' })}
          required
          hint={t('bid_management.code_hint', {
            defaultValue: 'Short identifier used in emails, e.g. BP-001.',
          })}
        >
          <input
            value={form.code}
            onChange={(e) => setForm({ ...form, code: e.target.value })}
            className={inputCls}
            placeholder="BP-001"
            autoFocus
          />
        </WideModalField>
        <WideModalField
          label={t('bid_management.title_col', { defaultValue: 'Title' })}
        >
          <input
            value={form.title}
            onChange={(e) => setForm({ ...form, title: e.target.value })}
            className={inputCls}
            placeholder={t('bid_management.title_placeholder', {
              defaultValue: 'Façade cladding works',
            })}
          />
        </WideModalField>
        <WideModalField
          label={t('bid_management.scope', { defaultValue: 'Scope description' })}
          hint={t('bid_management.scope_hint', {
            defaultValue: 'High-level summary sent to all invited bidders.',
          })}
          span={2}
        >
          <textarea
            value={form.scope_description}
            onChange={(e) => setForm({ ...form, scope_description: e.target.value })}
            rows={4}
            className={clsx(inputCls, 'h-auto py-2 resize-y')}
          />
        </WideModalField>
        <WideModalField
          label={t('bid_management.deadline', { defaultValue: 'Submission deadline' })}
        >
          <input
            type="date"
            value={form.submission_deadline}
            onChange={(e) => setForm({ ...form, submission_deadline: e.target.value })}
            className={inputCls}
          />
        </WideModalField>
        <WideModalField
          label={t('common.currency', { defaultValue: 'Currency' })}
          hint={t('bid_management.currency_hint', { defaultValue: 'ISO-4217 3-letter code.' })}
        >
          <input
            value={form.currency}
            onChange={(e) => setForm({ ...form, currency: e.target.value.toUpperCase() })}
            className={inputCls}
            maxLength={3}
          />
        </WideModalField>
        <WideModalField
          label={t('bid_management.budget', { defaultValue: 'Budget estimate' })}
          hint={t('bid_management.budget_hint', {
            defaultValue: 'Internal anchor, not shared with bidders.',
          })}
          span={2}
        >
          <input
            type="number"
            min="0"
            step="0.01"
            value={form.total_budget_estimate}
            onChange={(e) => setForm({ ...form, total_budget_estimate: e.target.value })}
            className={inputCls}
          />
        </WideModalField>
      </WideModalSection>
    </WideModal>
  );
}
