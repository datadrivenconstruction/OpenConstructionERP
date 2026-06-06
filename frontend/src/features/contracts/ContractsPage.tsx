import { useState, useMemo, useEffect } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import type { TFunction } from 'i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import clsx from 'clsx';
import {
  FileText,
  Receipt,
  Archive,
  Plus,
  Search,
  X,
  Loader2,
  PenLine,
  PauseCircle,
  PlayCircle,
  XCircle,
  CheckCircle2,
  Send,
  DollarSign,
  Users,
  FilePlus2,
  Copy,
  BookOpen,
} from 'lucide-react';
import {
  Button,
  Card,
  Badge,
  EmptyState,
  Breadcrumb,
  RecoveryCard,
  SkeletonTable,
  DismissibleInfo,
  IntroRichText,
} from '@/shared/ui';
import { RequiresProject } from '@/shared/auth/RequiresProject';
import {
  WideModal,
  WideModalSection,
  WideModalField,
} from '@/shared/ui/WideModal';
import { MoneyDisplay } from '@/shared/ui/MoneyDisplay';
import { MultiCurrencyTotal } from '@/shared/ui/MultiCurrencyTotal';
import { DateDisplay } from '@/shared/ui/DateDisplay';
import { PageHeader } from '@/shared/ui/PageHeader';
import { ContractStatusPipeline } from './ContractStatusPipeline';
import { ContractExpiryBadge } from './ContractExpiryBadge';
import { ComplianceGate } from './ComplianceGate';
import { useToastStore } from '@/stores/useToastStore';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { useAuthStore } from '@/stores/useAuthStore';
import { getErrorMessage } from '@/shared/lib/api';
import { projectsApi } from '@/features/projects/api';
import { listSubcontractors } from '@/features/subcontractors/api';
import { fetchContacts } from '@/features/contacts/api';
import {
  listContracts,
  listProgressClaims,
  listContractLines,
  createContract,
  createProgressClaim,
  suspendContract,
  resumeContract,
  terminateContract,
  closeContract,
  cloneContract,
  listClauseTemplates,
  submitClaim,
  approveClaim,
  certifyClaim,
  rejectClaim,
  markClaimPaid,
  getContractDashboard,
  type ContractItem,
  type ContractLine,
  type ProgressClaimItem,
  type ContractType,
  type ContractStatus,
  type ClaimStatus,
  type CounterpartyType,
  type ContractDashboard,
} from './api';

type Tab = 'contracts' | 'claims' | 'final_accounts';

const CONTRACT_TYPE_COLORS: Record<
  ContractType,
  { bg: string; ring: string; text: string }
> = {
  lump_sum: { bg: 'bg-blue-50 dark:bg-blue-950/40', ring: 'ring-blue-200 dark:ring-blue-800', text: 'text-blue-700 dark:text-blue-300' },
  gmp: { bg: 'bg-violet-50 dark:bg-violet-950/40', ring: 'ring-violet-200 dark:ring-violet-800', text: 'text-violet-700 dark:text-violet-300' },
  cost_plus: { bg: 'bg-amber-50 dark:bg-amber-950/40', ring: 'ring-amber-200 dark:ring-amber-800', text: 'text-amber-700 dark:text-amber-300' },
  tm: { bg: 'bg-emerald-50 dark:bg-emerald-950/40', ring: 'ring-emerald-200 dark:ring-emerald-800', text: 'text-emerald-700 dark:text-emerald-300' },
  unit_price: { bg: 'bg-sky-50 dark:bg-sky-950/40', ring: 'ring-sky-200 dark:ring-sky-800', text: 'text-sky-700 dark:text-sky-300' },
  design_build: { bg: 'bg-fuchsia-50 dark:bg-fuchsia-950/40', ring: 'ring-fuchsia-200 dark:ring-fuchsia-800', text: 'text-fuchsia-700 dark:text-fuchsia-300' },
  combination: { bg: 'bg-slate-50 dark:bg-slate-800/60', ring: 'ring-slate-200 dark:ring-slate-700', text: 'text-slate-700 dark:text-slate-300' },
  remeasurement: { bg: 'bg-teal-50 dark:bg-teal-950/40', ring: 'ring-teal-200 dark:ring-teal-800', text: 'text-teal-700 dark:text-teal-300' },
};

/** Neutral fallback so an unknown/missing contract type never crashes the chip. */
const CONTRACT_TYPE_FALLBACK = {
  bg: 'bg-slate-50 dark:bg-slate-800/60',
  ring: 'ring-slate-200 dark:ring-slate-700',
  text: 'text-slate-700 dark:text-slate-300',
};

const CONTRACT_STATUS_VARIANT: Record<
  ContractStatus,
  'neutral' | 'blue' | 'success' | 'warning' | 'error'
> = {
  draft: 'neutral',
  active: 'success',
  suspended: 'warning',
  completed: 'blue',
  terminated: 'error',
};

const CLAIM_STATUS_VARIANT: Record<
  ClaimStatus,
  'neutral' | 'blue' | 'success' | 'warning' | 'error'
> = {
  draft: 'neutral',
  submitted: 'blue',
  approved: 'success',
  certified: 'success',
  paid: 'success',
  rejected: 'error',
};

const CONTRACT_TYPES: ContractType[] = [
  'lump_sum',
  'gmp',
  'cost_plus',
  'tm',
  'unit_price',
  'design_build',
  'combination',
  'remeasurement',
];

const CONTRACT_STATUSES: ContractStatus[] = [
  'draft',
  'active',
  'suspended',
  'completed',
  'terminated',
];

const CLAIM_STATUSES: ClaimStatus[] = [
  'draft',
  'submitted',
  'approved',
  'certified',
  'paid',
  'rejected',
];

/** Lifecycle statuses relevant to the Final Accounts tab (closed contracts). */
const FINAL_ACCOUNT_CONTRACT_STATUSES: ContractStatus[] = ['completed', 'terminated'];

/** Human-readable English fallbacks for raw enum tokens. */
const CONTRACT_STATUS_LABELS: Record<ContractStatus, string> = {
  draft: 'Draft',
  active: 'Active',
  suspended: 'Suspended',
  completed: 'Completed',
  terminated: 'Terminated',
};

const CLAIM_STATUS_LABELS: Record<ClaimStatus, string> = {
  draft: 'Draft',
  submitted: 'Submitted',
  approved: 'Approved',
  certified: 'Certified',
  paid: 'Paid',
  rejected: 'Rejected',
};

/**
 * Translate a contract status via the established `module.status_*` i18n
 * convention used across sibling modules (finance / changeorders / tendering).
 * Falls back to a humanised English label so non-English locales never see a
 * raw snake_case enum token.
 */
function contractStatusLabel(t: TFunction, status: ContractStatus): string {
  return t(`contracts.status_${status}`, {
    defaultValue: CONTRACT_STATUS_LABELS[status] ?? status,
  });
}

function claimStatusLabel(t: TFunction, status: ClaimStatus): string {
  return t(`contracts.claim_status_${status}`, {
    defaultValue: CLAIM_STATUS_LABELS[status] ?? status,
  });
}

const inputCls =
  'h-9 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';

function toNum(v: number | string | null | undefined): number {
  if (v === null || v === undefined) return 0;
  const n = typeof v === 'string' ? Number(v) : v;
  return Number.isFinite(n) ? n : 0;
}

function todayIso(): string {
  return new Date().toISOString().slice(0, 10);
}

function ContractTypeChip({ type }: { type: ContractType }) {
  const { t } = useTranslation();
  const c = CONTRACT_TYPE_COLORS[type] ?? CONTRACT_TYPE_FALLBACK;
  const safeType = type || 'unknown';
  const label = t(`contracts.type_${safeType}`, {
    defaultValue: safeType === 'tm' ? 'T&M' : safeType.replace(/_/g, ' '),
  });
  return (
    <span
      className={clsx(
        'inline-flex items-center rounded-md px-2 py-0.5 text-xs font-medium ring-1 ring-inset',
        c.bg,
        c.ring,
        c.text,
      )}
    >
      {label}
    </span>
  );
}

/**
 * Resolve a contract counterparty (a bare UUID on the wire that may point at a
 * subcontractor OR a contact, see contracts/models.py) to its firm name and a
 * deep link. Subcontractor counterparties open the Subcontractors register with
 * the row highlighted; client counterparties open the matching Contacts record.
 * Falls back to a plain type word when there is no id or no resolved name, so a
 * legacy contract with an unresolvable counterparty never shows a dead UUID.
 */
function CounterpartyLink({
  type,
  id,
}: {
  type: CounterpartyType;
  id: string | null;
}) {
  const { t } = useTranslation();

  const subsQ = useQuery({
    queryKey: ['contracts', 'counterparty-subs'],
    queryFn: () => listSubcontractors({ limit: 500 }),
    enabled: type === 'subcontractor' && !!id,
    staleTime: 5 * 60_000,
  });
  const contactsQ = useQuery({
    queryKey: ['contracts', 'counterparty-contacts'],
    queryFn: () => fetchContacts({ limit: 500 }),
    enabled: type === 'client' && !!id,
    staleTime: 5 * 60_000,
  });

  const typeWord =
    type === 'subcontractor'
      ? t('contracts.cp_subcontractor', { defaultValue: 'Subcontractor' })
      : t('contracts.cp_client', { defaultValue: 'Client' });

  if (!id) {
    return <span className="capitalize">{typeWord}</span>;
  }

  if (type === 'subcontractor') {
    const match = (subsQ.data ?? []).find((s) => s.id === id);
    if (!match) {
      return <span className="capitalize">{typeWord}</span>;
    }
    return (
      <Link
        to={`/subcontractors?highlight=${id}`}
        className="text-oe-blue hover:underline"
      >
        {match.legal_name}
      </Link>
    );
  }

  const contact = (contactsQ.data ?? []).find((c) => c.id === id);
  const contactName =
    contact?.company_name ||
    contact?.legal_name ||
    [contact?.first_name, contact?.last_name].filter(Boolean).join(' ') ||
    null;
  if (!contactName) {
    return <span className="capitalize">{typeWord}</span>;
  }
  return (
    <Link to={`/contacts?contactId=${id}`} className="text-oe-blue hover:underline">
      {contactName}
    </Link>
  );
}

/* ─── Page ─── */

export function ContractsPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const [tab, setTab] = useState<Tab>('contracts');
  const activeProjectId = useProjectContextStore((s) => s.activeProjectId);

  // CONN-43 consumer: a subcontractor's "Subcontract agreement" pill deep-links
  // here with ?counterparty=<id> so the register opens scoped to that firm's
  // contracts. The filter is cleared via the dismiss chip below (replace, so
  // back-navigation does not re-apply it).
  const counterpartyFilter = searchParams.get('counterparty');
  const clearCounterpartyFilter = () =>
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        next.delete('counterparty');
        return next;
      },
      { replace: true },
    );
  const [projectId, setProjectId] = useState<string>('');
  const [search, setSearch] = useState('');
  const [typeFilter, setTypeFilter] = useState<ContractType | ''>('');
  const [statusFilter, setStatusFilter] = useState<string>('');
  const [selectedContractId, setSelectedContractId] = useState<string | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [newClaimOpen, setNewClaimOpen] = useState(false);

  const projectsQ = useQuery({
    queryKey: ['contracts', 'projects'],
    queryFn: () => projectsApi.list(),
  });

  // Project selection lives in the global top bar (useProjectContextStore).
  // Follow the active project when it changes; otherwise fall back to the
  // first project the user can see so the page is never blank for a
  // single-project tenant. No in-page project picker is rendered.
  useEffect(() => {
    const seed = activeProjectId || projectsQ.data?.[0]?.id;
    if (seed && seed !== projectId) setProjectId(seed);
  }, [activeProjectId, projectsQ.data, projectId]);

  const contractsQ = useQuery({
    queryKey: ['contracts', 'list', projectId],
    queryFn: () => listContracts({ project_id: projectId, limit: 200 }),
    enabled: !!projectId,
  });

  const contracts = contractsQ.data ?? [];
  const selectedProject = useMemo(
    () => (projectsQ.data ?? []).find((p) => p.id === projectId),
    [projectsQ.data, projectId],
  );
  const [claimsContractId, setClaimsContractId] = useState<string>('');
  const effectiveClaimsContract = claimsContractId || contracts[0]?.id || '';

  const claimsQ = useQuery({
    queryKey: ['contracts', 'claims', effectiveClaimsContract],
    queryFn: () =>
      listProgressClaims({ contract_id: effectiveClaimsContract, limit: 200 }),
    enabled: tab !== 'contracts' && !!effectiveClaimsContract,
  });

  const filteredContracts = useMemo(() => {
    const s = search.toLowerCase();
    return contracts.filter((c) => {
      if (counterpartyFilter && c.counterparty_id !== counterpartyFilter) {
        return false;
      }
      if (typeFilter && c.contract_type !== typeFilter) return false;
      if (statusFilter && c.status !== statusFilter) return false;
      if (!s) return true;
      return (
        c.code.toLowerCase().includes(s) ||
        c.title.toLowerCase().includes(s)
      );
    });
  }, [contracts, search, typeFilter, statusFilter, counterpartyFilter]);

  const filteredClaims = useMemo(() => {
    const items = claimsQ.data ?? [];
    const s = search.toLowerCase();
    return items.filter((c) => {
      if (statusFilter && c.status !== statusFilter) return false;
      if (!s) return true;
      return c.claim_number.toLowerCase().includes(s);
    });
  }, [claimsQ.data, search, statusFilter]);

  // Final accounts are opened for closed contracts (completed / terminated).
  // The status filter and search box both narrow this list so the dropdown is
  // a live control rather than dead UI.
  const finalAccountContracts = useMemo(() => {
    const s = search.toLowerCase();
    return contracts.filter((c) => {
      if (c.status !== 'completed' && c.status !== 'terminated') return false;
      if (statusFilter && c.status !== statusFilter) return false;
      if (!s) return true;
      return (
        c.code.toLowerCase().includes(s) || c.title.toLowerCase().includes(s)
      );
    });
  }, [contracts, search, statusFilter]);

  const isLoading =
    (tab === 'contracts' && contractsQ.isLoading) ||
    (tab !== 'contracts' && (contractsQ.isLoading || claimsQ.isLoading));

  // A failed query must NOT look like an empty success — surface it with a
  // retry, matching the established sibling error-state pattern.
  const loadError =
    tab === 'claims'
      ? contractsQ.error ?? claimsQ.error
      : contractsQ.error;
  const isError =
    tab === 'claims'
      ? contractsQ.isError || claimsQ.isError
      : contractsQ.isError;
  const retryLoad = () => {
    void contractsQ.refetch();
    if (tab === 'claims') void claimsQ.refetch();
  };

  return (
    <div className="space-y-5 animate-fade-in">
      <Breadcrumb
        items={[
          ...(selectedProject
            ? [{ label: selectedProject.name, to: `/projects/${selectedProject.id}` }]
            : []),
          { label: t('nav.contracts', { defaultValue: 'Contracts' }) },
        ]}
      />

      <PageHeader
        subtitle={t('contracts.subtitle', {
          defaultValue:
            'Type-aware contracts with schedule of values, retention, claims and final accounts.',
        })}
        actions={
          <Button
            variant="primary"
            icon={<Plus size={14} />}
            onClick={() => {
              if (tab === 'claims') setNewClaimOpen(true);
              else setCreateOpen(true);
            }}
            disabled={!projectId}
          >
            {tab === 'claims'
              ? t('contracts.new_claim', { defaultValue: 'New Claim' })
              : t('contracts.new_contract', { defaultValue: 'New Contract' })}
          </Button>
        }
      />

      <DismissibleInfo
        storageKey="contracts"
        title={t('contracts.intro_title', {
          defaultValue: 'Keep the contract sum honest end to end',
        })}
        more={
          t('contracts.intro_more', { defaultValue: '' })
            ? <IntroRichText text={t('contracts.intro_more')} />
            : undefined
        }
        links={[
          {
            label: t('nav.variations', { defaultValue: 'Variations' }),
            onClick: () => navigate('/variations'),
          },
          {
            label: t('nav.bid_management', { defaultValue: 'Bid Management' }),
            onClick: () => navigate('/bid-management'),
          },
          {
            label: t('nav.finance', { defaultValue: 'Finance' }),
            onClick: () => navigate('/finance'),
          },
        ]}
      >
        {t('contracts.intro_body', {
          defaultValue:
            'Set up each commercial agreement with its type-aware schedule of values, retention and lifecycle, then bill the work through progress claims and settle in the final account. Variations adjust the contract sum mid-flight and approved claims push their net due into Finance, so what you signed and what you owe never drift apart.',
        })}
      </DismissibleInfo>

      {/* Tabs */}
      <div className="border-b border-border-light">
        <nav className="flex gap-1 -mb-px">
          {(
            [
              {
                id: 'contracts',
                label: t('contracts.tab_contracts', { defaultValue: 'Contracts' }),
                icon: FileText,
              },
              {
                id: 'claims',
                label: t('contracts.tab_claims', { defaultValue: 'Progress Claims' }),
                icon: Receipt,
              },
              {
                id: 'final_accounts',
                label: t('contracts.tab_final_accounts', { defaultValue: 'Final Accounts' }),
                icon: Archive,
              },
            ] as { id: Tab; label: string; icon: React.ElementType }[]
          ).map((it) => {
            const Icon = it.icon;
            return (
              <button
                key={it.id}
                type="button"
                onClick={() => {
                  setTab(it.id);
                  setSearch('');
                  setStatusFilter('');
                }}
                className={clsx(
                  'flex items-center gap-2 px-4 py-2.5 text-sm font-medium border-b-2 transition-colors',
                  tab === it.id
                    ? 'border-oe-blue text-oe-blue'
                    : 'border-transparent text-content-secondary hover:text-content-primary',
                )}
              >
                <Icon size={14} />
                {it.label}
              </button>
            );
          })}
        </nav>
      </div>

      {/* Filters — the project is chosen in the global top bar, so the
          previous in-page project select is gone; only entity-level filters
          (search / type / status) remain here. */}
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative flex-1 min-w-[200px] max-w-md">
          <Search
            size={14}
            className="absolute left-3 top-1/2 -translate-y-1/2 text-content-tertiary"
          />
          <input
            type="text"
            placeholder={t('common.search', { defaultValue: 'Search…' })}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className={clsx(inputCls, 'pl-8')}
          />
        </div>

        {tab === 'contracts' && (
          <select
            value={typeFilter}
            onChange={(e) => setTypeFilter(e.target.value as ContractType | '')}
            aria-label={t('a11y.contracts.type_filter', {
              defaultValue: 'Filter contracts by type',
            })}
            className={clsx(inputCls, 'max-w-[200px]')}
          >
            <option value="">
              {t('contracts.all_types', { defaultValue: 'All types' })}
            </option>
            {CONTRACT_TYPES.map((tp) => (
              <option key={tp} value={tp}>
                {t(`contracts.type_${tp}`, {
                  defaultValue: tp === 'tm' ? 'T&M' : tp.replace(/_/g, ' '),
                })}
              </option>
            ))}
          </select>
        )}

        {tab !== 'contracts' && contracts.length > 0 && (
          <select
            value={effectiveClaimsContract}
            onChange={(e) => setClaimsContractId(e.target.value)}
            aria-label={t('a11y.contracts.claims_contract_filter', {
              defaultValue: 'Filter by claims contract',
            })}
            className={clsx(inputCls, 'max-w-[260px]')}
          >
            {contracts.map((c) => (
              <option key={c.id} value={c.id}>
                {c.code} — {c.title || 'Untitled'}
              </option>
            ))}
          </select>
        )}

        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          aria-label={t('a11y.contracts.status_filter', {
            defaultValue: 'Filter contracts by status',
          })}
          className={clsx(inputCls, 'max-w-[180px]')}
        >
          <option value="">
            {t('common.all_statuses', { defaultValue: 'All statuses' })}
          </option>
          {tab === 'contracts' &&
            CONTRACT_STATUSES.map((s) => (
              <option key={s} value={s}>
                {contractStatusLabel(t, s)}
              </option>
            ))}
          {tab === 'claims' &&
            CLAIM_STATUSES.map((s) => (
              <option key={s} value={s}>
                {claimStatusLabel(t, s)}
              </option>
            ))}
          {tab === 'final_accounts' &&
            FINAL_ACCOUNT_CONTRACT_STATUSES.map((s) => (
              <option key={s} value={s}>
                {contractStatusLabel(t, s)}
              </option>
            ))}
        </select>
      </div>

      {/* CONN-43: active counterparty deep-link filter, dismissible. */}
      {counterpartyFilter && (
        <div className="flex items-center gap-2 text-xs">
          <span className="inline-flex items-center gap-1.5 rounded-full bg-oe-blue-subtle px-2.5 py-1 text-oe-blue-text">
            <Users size={12} />
            {t('contracts.filtered_to_counterparty', {
              defaultValue: 'Showing contracts for one counterparty',
            })}
            <button
              type="button"
              onClick={clearCounterpartyFilter}
              className="ml-0.5 rounded-full p-0.5 hover:bg-oe-blue/10"
              aria-label={t('common.clear', { defaultValue: 'Clear' })}
            >
              <X size={12} />
            </button>
          </span>
        </div>
      )}

      {/* Body */}
      <Card padding="none">
        {!projectId ? (
          <RequiresProject
            emptyHint={t('contracts.no_project_desc', {
              defaultValue: 'Pick a project above to view its contracts.',
            })}
          >{null}</RequiresProject>
        ) : isLoading ? (
          <div className="p-4">
            <SkeletonTable rows={8} columns={6} />
          </div>
        ) : isError ? (
          <RecoveryCard error={loadError} onRetry={retryLoad} />
        ) : tab === 'contracts' ? (
          <ContractTable
            rows={filteredContracts}
            onSelect={setSelectedContractId}
            emptyAction={() => setCreateOpen(true)}
          />
        ) : tab === 'claims' ? (
          <ClaimsTable
            rows={filteredClaims}
            onCreate={() => setNewClaimOpen(true)}
            hasContract={!!effectiveClaimsContract}
            projectId={projectId}
          />
        ) : (
          <FinalAccountsView
            contracts={finalAccountContracts}
            onSelect={setSelectedContractId}
          />
        )}
      </Card>

      {/* Detail drawer */}
      {selectedContractId && (
        <ContractDetailDrawer
          contractId={selectedContractId}
          contracts={contracts}
          onClose={() => setSelectedContractId(null)}
        />
      )}

      {/* Create contract modal */}
      {createOpen && (
        <CreateContractModal
          projectId={projectId}
          onClose={() => setCreateOpen(false)}
        />
      )}

      {/* New claim modal */}
      {newClaimOpen && (
        <NewClaimModal
          contracts={contracts.filter((c) => c.status === 'active')}
          defaultContractId={effectiveClaimsContract}
          onClose={() => setNewClaimOpen(false)}
        />
      )}
    </div>
  );
}

/* ─── Contract table ─── */

function ContractTable({
  rows,
  onSelect,
  emptyAction,
}: {
  rows: ContractItem[];
  onSelect: (id: string) => void;
  emptyAction: () => void;
}) {
  const { t } = useTranslation();
  // Pre-fetch clause templates for the empty-state hint chips. The
  // query is cheap (in-memory dict on the backend) and is shared with
  // the CreateContractModal via React Query's cache.
  const templatesQ = useQuery({
    queryKey: ['contracts', 'clause-templates'],
    queryFn: listClauseTemplates,
    staleTime: 60 * 60 * 1000,
  });

  if (rows.length === 0) {
    const families = Array.from(
      new Set((templatesQ.data ?? []).map((tpl) => tpl.family.toUpperCase())),
    ).slice(0, 5);
    return (
      <div className="relative">
        <EmptyState
          icon={<FileText size={22} />}
          title={t('contracts.empty', { defaultValue: 'No contracts yet' })}
          description={t('contracts.empty_desc', {
            defaultValue:
              'Create your first contract, pick the contract type and the engine wires up the right schedule of values, fees and gainshare rules.',
          })}
          action={{
            label: t('contracts.new_contract', { defaultValue: 'New Contract' }),
            onClick: emptyAction,
          }}
        />
        {families.length > 0 && (
          <div
            data-testid="contracts-template-chips"
            className="mx-auto -mt-6 mb-12 flex max-w-md flex-wrap items-center justify-center gap-1.5 text-xs"
          >
            <BookOpen
              size={12}
              className="text-content-tertiary"
              aria-hidden
            />
            <span className="text-content-tertiary">
              {t('contracts.empty_templates_hint', {
                defaultValue: 'Clause templates available:',
              })}
            </span>
            {families.map((fam) => (
              <span
                key={fam}
                className="inline-flex items-center rounded-md bg-surface-secondary px-1.5 py-0.5 font-medium text-content-secondary ring-1 ring-inset ring-border-light"
              >
                {fam}
              </span>
            ))}
          </div>
        )}
      </div>
    );
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead className="bg-surface-secondary text-content-tertiary text-xs uppercase tracking-wide">
          <tr>
            <th className="px-4 py-2.5 text-left">
              {t('contracts.code', { defaultValue: 'Code' })}
            </th>
            <th className="px-4 py-2.5 text-left">
              {t('contracts.title_col', { defaultValue: 'Title' })}
            </th>
            <th className="px-4 py-2.5 text-left">
              {t('contracts.type', { defaultValue: 'Type' })}
            </th>
            <th className="px-4 py-2.5 text-left">
              {t('contracts.counterparty', { defaultValue: 'Counterparty' })}
            </th>
            <th className="px-4 py-2.5 text-left">
              {t('contracts.status', { defaultValue: 'Status' })}
            </th>
            <th className="px-4 py-2.5 text-right">
              {t('contracts.value', { defaultValue: 'Value' })}
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
              <td className="px-4 py-2 font-mono text-xs text-content-secondary">
                {r.code}
              </td>
              <td className="px-4 py-2 font-medium text-content-primary truncate max-w-[320px]">
                {r.title || '—'}
              </td>
              <td className="px-4 py-2">
                <ContractTypeChip type={r.contract_type} />
              </td>
              <td className="px-4 py-2 text-xs text-content-secondary capitalize">
                {r.counterparty_type}
              </td>
              <td className="px-4 py-2">
                <div className="flex items-center gap-2">
                  <Badge variant={CONTRACT_STATUS_VARIANT[r.status]} dot>
                    {contractStatusLabel(t, r.status)}
                  </Badge>
                  <ContractStatusPipeline status={r.status} />
                  <ContractExpiryBadge endDate={r.end_date} status={r.status} />
                </div>
              </td>
              <td className="px-4 py-2 text-right">
                <MoneyDisplay
                  amount={toNum(r.total_value)}
                  currency={r.currency || undefined}
                />
              </td>
            </tr>
          ))}
        </tbody>
        {/* Honest cross-currency rollup — never silently sums mixed
            currencies into a single number (the previous footer would
            have done arithmetic on €+$ values without warning). */}
        <tfoot className="bg-surface-secondary/60">
          <tr className="border-t border-border-light">
            <td colSpan={5} className="px-4 py-2 text-xs uppercase tracking-wide text-content-tertiary">
              {t('contracts.register_total', { defaultValue: 'Register total' })}
              <span className="ml-2 normal-case text-content-secondary">
                ({rows.length}{' '}
                {t('contracts.contracts_label', { defaultValue: 'contracts' })})
              </span>
            </td>
            <td className="px-4 py-2 text-right text-sm font-medium">
              <MultiCurrencyTotal
                items={rows.map((r) => ({
                  amount: r.total_value,
                  currency: r.currency,
                }))}
                variant="inline"
                compact
              />
            </td>
          </tr>
        </tfoot>
      </table>
    </div>
  );
}

/* ─── Claims table ─── */

function ClaimsTable({
  rows,
  onCreate,
  hasContract,
  projectId,
}: {
  rows: ProgressClaimItem[];
  onCreate: () => void;
  hasContract: boolean;
  projectId: string;
}) {
  const { t } = useTranslation();
  if (!hasContract) {
    return (
      <EmptyState
        icon={<Receipt size={22} />}
        title={t('contracts.no_contract_for_claims', {
          defaultValue: 'No contract selected',
        })}
        description={t('contracts.no_contract_for_claims_desc', {
          defaultValue: 'Pick a contract above to view its progress claims.',
        })}
      />
    );
  }
  if (rows.length === 0) {
    return (
      <EmptyState
        icon={<Receipt size={22} />}
        title={t('contracts.empty_claims', { defaultValue: 'No claims yet' })}
        description={t('contracts.empty_claims_desc', {
          defaultValue:
            'Generate a progress claim from the schedule of values to bill completed work.',
        })}
        action={{
          label: t('contracts.new_claim', { defaultValue: 'New Claim' }),
          onClick: onCreate,
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
              {t('contracts.claim_number', { defaultValue: 'Claim #' })}
            </th>
            <th className="px-4 py-2.5 text-left">
              {t('contracts.period', { defaultValue: 'Period' })}
            </th>
            <th className="px-4 py-2.5 text-right">
              {t('contracts.gross', { defaultValue: 'Gross' })}
            </th>
            <th className="px-4 py-2.5 text-right">
              {t('contracts.retention', { defaultValue: 'Retention' })}
            </th>
            <th className="px-4 py-2.5 text-right">
              {t('contracts.net_due', { defaultValue: 'Net due' })}
            </th>
            <th className="px-4 py-2.5 text-left">
              {t('contracts.status', { defaultValue: 'Status' })}
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <ClaimRow key={r.id} claim={r} projectId={projectId} />
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ClaimRow({
  claim,
  projectId,
}: {
  claim: ProgressClaimItem;
  projectId: string;
}) {
  const qc = useQueryClient();
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  // Certify and Mark-paid are MANAGER-gated on the backend
  // (contracts.certify_claim / contracts.mark_paid). Hide the affordances for
  // editors/viewers so they don't click a button that always 403s.
  const userRole = useAuthStore((s) => s.userRole);
  const canManageClaim = userRole === 'admin' || userRole === 'manager';

  const mut = (fn: (id: string) => Promise<ProgressClaimItem>, okMsg: string) =>
    useMutation({
      mutationFn: () => fn(claim.id),
      onSuccess: () => {
        qc.invalidateQueries({ queryKey: ['contracts', 'claims'] });
        addToast({ type: 'success', title: okMsg });
      },
      onError: (err) =>
        addToast({ type: 'error', title: getErrorMessage(err) }),
    });

  const submit = mut(submitClaim, t('contracts.claim_submitted', { defaultValue: 'Claim submitted' }));
  const approve = mut(approveClaim, t('contracts.claim_approved', { defaultValue: 'Claim approved' }));
  const certify = mut(certifyClaim, t('contracts.claim_certified', { defaultValue: 'Claim certified' }));
  const reject = mut(rejectClaim, t('contracts.claim_rejected', { defaultValue: 'Claim rejected' }));
  const paid = mut(markClaimPaid, t('contracts.claim_paid', { defaultValue: 'Claim marked paid' }));

  return (
    <tr className="border-t border-border-light hover:bg-surface-secondary">
      <td className="px-4 py-2 font-mono text-xs">
        {projectId ? (
          <Link
            to={`/projects/${projectId}/contracts/claims/${claim.id}`}
            className="text-oe-blue hover:underline"
          >
            {claim.claim_number}
          </Link>
        ) : (
          <span className="text-content-secondary">{claim.claim_number}</span>
        )}
      </td>
      <td className="px-4 py-2 text-xs text-content-secondary">
        {claim.period_start ? <DateDisplay value={claim.period_start} /> : '—'}
        {' → '}
        {claim.period_end ? <DateDisplay value={claim.period_end} /> : '—'}
      </td>
      <td className="px-4 py-2 text-right">
        <MoneyDisplay
          amount={toNum(claim.gross_amount)}
          currency={claim.currency || undefined}
        />
      </td>
      <td className="px-4 py-2 text-right text-content-secondary">
        <MoneyDisplay
          amount={toNum(claim.retention_amount)}
          currency={claim.currency || undefined}
        />
      </td>
      <td className="px-4 py-2 text-right font-medium">
        <MoneyDisplay
          amount={toNum(claim.net_due)}
          currency={claim.currency || undefined}
        />
      </td>
      <td className="px-4 py-2">
        <div className="flex items-center gap-2">
          <Badge variant={CLAIM_STATUS_VARIANT[claim.status]} dot>
            {claimStatusLabel(t, claim.status)}
          </Badge>
          <div className="flex gap-1">
            {claim.status === 'draft' && (
              <Button
                size="sm"
                variant="ghost"
                onClick={() => submit.mutate()}
                loading={submit.isPending}
                icon={<Send size={12} />}
              >
                {t('contracts.submit', { defaultValue: 'Submit' })}
              </Button>
            )}
            {claim.status === 'submitted' && (
              <>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => approve.mutate()}
                  loading={approve.isPending}
                  icon={<CheckCircle2 size={12} />}
                >
                  {t('contracts.approve', { defaultValue: 'Approve' })}
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => reject.mutate()}
                  loading={reject.isPending}
                  icon={<XCircle size={12} />}
                >
                  {t('contracts.reject', { defaultValue: 'Reject' })}
                </Button>
              </>
            )}
            {claim.status === 'approved' && canManageClaim && (
              <Button
                size="sm"
                variant="ghost"
                onClick={() => certify.mutate()}
                loading={certify.isPending}
              >
                {t('contracts.certify', { defaultValue: 'Certify' })}
              </Button>
            )}
            {claim.status === 'certified' && canManageClaim && (
              <Button
                size="sm"
                variant="ghost"
                onClick={() => paid.mutate()}
                loading={paid.isPending}
                icon={<DollarSign size={12} />}
              >
                {t('contracts.mark_paid', { defaultValue: 'Mark paid' })}
              </Button>
            )}
          </div>
        </div>
      </td>
    </tr>
  );
}

/* ─── Final accounts ─── */

function FinalAccountsView({
  contracts,
  onSelect,
}: {
  contracts: ContractItem[];
  onSelect: (id: string) => void;
}) {
  const { t } = useTranslation();
  if (contracts.length === 0) {
    return (
      <EmptyState
        icon={<Archive size={22} />}
        title={t('contracts.empty_final_accounts', {
          defaultValue: 'No final accounts',
        })}
        description={t('contracts.empty_final_accounts_desc', {
          defaultValue:
            'Final accounts are opened when a contract is closed. Completed or terminated contracts will appear here.',
        })}
      />
    );
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead className="bg-surface-secondary text-content-tertiary text-xs uppercase tracking-wide">
          <tr>
            <th className="px-4 py-2.5 text-left">
              {t('contracts.code', { defaultValue: 'Code' })}
            </th>
            <th className="px-4 py-2.5 text-left">
              {t('contracts.title_col', { defaultValue: 'Title' })}
            </th>
            <th className="px-4 py-2.5 text-left">
              {t('contracts.type', { defaultValue: 'Type' })}
            </th>
            <th className="px-4 py-2.5 text-left">
              {t('contracts.status', { defaultValue: 'Status' })}
            </th>
            <th className="px-4 py-2.5 text-right">
              {t('contracts.value', { defaultValue: 'Value' })}
            </th>
          </tr>
        </thead>
        <tbody>
          {contracts.map((c) => (
            <tr
              key={c.id}
              onClick={() => onSelect(c.id)}
              className="border-t border-border-light hover:bg-surface-secondary cursor-pointer"
            >
              <td className="px-4 py-2 font-mono text-xs text-content-secondary">
                {c.code}
              </td>
              <td className="px-4 py-2 font-medium">{c.title || '—'}</td>
              <td className="px-4 py-2">
                <ContractTypeChip type={c.contract_type} />
              </td>
              <td className="px-4 py-2">
                <Badge variant={CONTRACT_STATUS_VARIANT[c.status]} dot>
                  {contractStatusLabel(t, c.status)}
                </Badge>
              </td>
              <td className="px-4 py-2 text-right">
                <MoneyDisplay
                  amount={toNum(c.total_value)}
                  currency={c.currency || undefined}
                />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/* ─── Detail drawer ─── */

function ContractDetailDrawer({
  contractId,
  contracts,
  onClose,
}: {
  contractId: string;
  contracts: ContractItem[];
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const contract = contracts.find((c) => c.id === contractId);
  // Item #27 — signing goes through the compliance gate modal, which runs
  // the project's compliance rule packs against the SoV and only lets the
  // user sign once there are no blocking errors.
  const [gateOpen, setGateOpen] = useState(false);

  const linesQ = useQuery({
    queryKey: ['contracts', 'lines', contractId],
    queryFn: () => listContractLines(contractId),
  });

  const claimsQ = useQuery({
    queryKey: ['contracts', 'claim-history', contractId],
    queryFn: () => listProgressClaims({ contract_id: contractId, limit: 50 }),
  });

  const dashQ = useQuery<ContractDashboard>({
    queryKey: ['contracts', 'dashboard', contractId],
    queryFn: () => getContractDashboard(contractId),
    retry: false,
  });

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ['contracts', 'list'] });
    qc.invalidateQueries({ queryKey: ['contracts', 'dashboard', contractId] });
  };

  const suspendMut = useMutation({
    mutationFn: () => suspendContract(contractId),
    onSuccess: () => {
      invalidate();
      addToast({
        type: 'success',
        title: t('contracts.suspended_ok', { defaultValue: 'Contract suspended' }),
      });
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  const resumeMut = useMutation({
    mutationFn: () => resumeContract(contractId),
    onSuccess: () => {
      invalidate();
      addToast({
        type: 'success',
        title: t('contracts.resumed_ok', { defaultValue: 'Contract resumed' }),
      });
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  const terminateMut = useMutation({
    mutationFn: () => terminateContract(contractId),
    onSuccess: () => {
      invalidate();
      addToast({
        type: 'success',
        title: t('contracts.terminated_ok', { defaultValue: 'Contract terminated' }),
      });
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  const closeMut = useMutation({
    mutationFn: () =>
      closeContract(contractId, {
        contract_id: contractId,
        final_contract_value: toNum(contract?.total_value),
        status: 'agreed',
      }),
    onSuccess: () => {
      invalidate();
      addToast({
        type: 'success',
        title: t('contracts.closed_ok', { defaultValue: 'Contract closed' }),
      });
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  // Clone uses the existing R7-hardened POST /contracts/{id}/clone
  // endpoint. We default the new code to "<source.code>-COPY" so the
  // mandatory unique-code constraint is satisfied without a second
  // round-trip; in practice the user immediately renames via the detail
  // drawer of the clone. No subconfigs/lines toggle in the UI yet —
  // backend defaults (include_lines=true, copy_subconfigs=true) are
  // the only sensible "clone this contract template" semantics, and
  // the partial-clone variants are power-user / API-only.
  const cloneMut = useMutation({
    mutationFn: () =>
      cloneContract(contractId, {
        new_code: `${contract?.code || 'C'}-COPY`,
        new_title: contract?.title ? `${contract.title} (clone)` : undefined,
        include_lines: true,
        copy_subconfigs: true,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['contracts', 'list'] });
      addToast({
        type: 'success',
        title: t('contracts.cloned_ok', { defaultValue: 'Contract cloned (draft)' }),
      });
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onClose]);

  if (!contract) return null;

  const lineTotal = (linesQ.data ?? []).reduce(
    (acc, l) => acc + toNum(l.total_value),
    0,
  );

  return (
    <div className="fixed inset-0 z-50 flex justify-end" onClick={onClose}>
      <div className="absolute inset-0 bg-black/30" />
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="contract-drawer-title"
        className="relative h-full w-full max-w-2xl overflow-y-auto bg-surface-elevated shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="sticky top-0 z-10 flex items-center justify-between border-b border-border-light bg-surface-elevated px-5 py-3">
          <div>
            <h2 id="contract-drawer-title" className="text-base font-semibold">
              {contract.code} — {contract.title || 'Untitled'}
            </h2>
            <div className="mt-1 flex flex-wrap items-center gap-2">
              <ContractTypeChip type={contract.contract_type} />
              <Badge variant={CONTRACT_STATUS_VARIANT[contract.status]} dot>
                {contractStatusLabel(t, contract.status)}
              </Badge>
              <ContractStatusPipeline status={contract.status} />
              <ContractExpiryBadge endDate={contract.end_date} status={contract.status} />
            </div>
          </div>
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
          {/* Headline KPIs */}
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <KPI
              label={t('contracts.value', { defaultValue: 'Value' })}
              value={
                <MoneyDisplay
                  amount={toNum(contract.total_value)}
                  currency={contract.currency || undefined}
                />
              }
            />
            <KPI
              label={t('contracts.paid_to_date', { defaultValue: 'Paid to date' })}
              value={
                <MoneyDisplay
                  amount={toNum(dashQ.data?.paid_to_date)}
                  currency={contract.currency || undefined}
                />
              }
            />
            <KPI
              label={t('contracts.retention_held', { defaultValue: 'Retention held' })}
              value={
                <MoneyDisplay
                  amount={toNum(dashQ.data?.retention_held)}
                  currency={contract.currency || undefined}
                />
              }
            />
            <KPI
              label={t('contracts.outstanding', { defaultValue: 'Outstanding' })}
              value={
                <MoneyDisplay
                  amount={toNum(dashQ.data?.outstanding)}
                  currency={contract.currency || undefined}
                />
              }
            />
          </div>

          {/* Workflow buttons */}
          <div className="flex flex-wrap gap-2 pt-1">
            {contract.status === 'draft' && (
              <Button
                variant="primary"
                icon={<PenLine size={14} />}
                onClick={() => setGateOpen(true)}
              >
                {t('contracts.sign', { defaultValue: 'Sign' })}
              </Button>
            )}
            {contract.status === 'active' && (
              <Button
                variant="secondary"
                icon={<PauseCircle size={14} />}
                onClick={() => suspendMut.mutate()}
                loading={suspendMut.isPending}
              >
                {t('contracts.suspend', { defaultValue: 'Suspend' })}
              </Button>
            )}
            {contract.status === 'suspended' && (
              <Button
                variant="primary"
                icon={<PlayCircle size={14} />}
                onClick={() => resumeMut.mutate()}
                loading={resumeMut.isPending}
              >
                {t('contracts.resume', { defaultValue: 'Resume' })}
              </Button>
            )}
            {(contract.status === 'active' || contract.status === 'suspended') && (
              <>
                <Button
                  variant="secondary"
                  icon={<Archive size={14} />}
                  onClick={() => closeMut.mutate()}
                  loading={closeMut.isPending}
                >
                  {t('contracts.close', { defaultValue: 'Close' })}
                </Button>
                <Button
                  variant="ghost"
                  icon={<XCircle size={14} />}
                  onClick={() => terminateMut.mutate()}
                  loading={terminateMut.isPending}
                >
                  {t('contracts.terminate', { defaultValue: 'Terminate' })}
                </Button>
              </>
            )}
            {/* Clone is always available — it always produces a draft,
                so cloning a terminated contract to start a renewal is
                a legitimate, common pattern. The backend enforces
                contracts.clone (Role.MANAGER) + cross-tenant IDOR
                checks; the UI just surfaces the action. */}
            <Button
              variant="ghost"
              icon={<Copy size={14} />}
              onClick={() => cloneMut.mutate()}
              loading={cloneMut.isPending}
            >
              {t('contracts.clone', { defaultValue: 'Clone' })}
            </Button>
          </div>

          {/* Cross-module pipeline links */}
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <span className="text-content-tertiary">
              {t('contracts.related', { defaultValue: 'Related:' })}
            </span>
            {contract.counterparty_type === 'subcontractor' && (
              <Link
                to={
                  contract.counterparty_id
                    ? `/subcontractors?highlight=${contract.counterparty_id}`
                    : '/subcontractors'
                }
                className="inline-flex items-center gap-1 rounded-md border border-border-light px-2 py-1 text-content-secondary hover:text-oe-blue hover:border-oe-blue transition-colors"
              >
                <Users size={12} />
                {t('contracts.view_subcontractor', {
                  defaultValue: 'Subcontractor',
                })}
              </Link>
            )}
            <Link
              to="/variations"
              className="inline-flex items-center gap-1 rounded-md border border-border-light px-2 py-1 text-content-secondary hover:text-oe-blue hover:border-oe-blue transition-colors"
            >
              <FilePlus2 size={12} />
              {t('contracts.raise_variation', {
                defaultValue: 'Variations on this contract',
              })}
            </Link>
          </div>

          {/* Header fields */}
          <Card padding="sm">
            <p className="text-xs font-semibold uppercase tracking-wide text-content-secondary mb-2">
              {t('contracts.section_header', { defaultValue: 'Header' })}
            </p>
            <div className="grid grid-cols-2 gap-3 text-sm">
              <Field
                label={t('contracts.counterparty', { defaultValue: 'Counterparty' })}
                value={
                  <CounterpartyLink
                    type={contract.counterparty_type}
                    id={contract.counterparty_id}
                  />
                }
              />
              <Field
                label={t('contracts.currency', { defaultValue: 'Currency' })}
                value={contract.currency || '—'}
              />
              <Field
                label={t('contracts.start_date', { defaultValue: 'Start' })}
                value={
                  contract.start_date ? (
                    <DateDisplay value={contract.start_date} />
                  ) : (
                    '—'
                  )
                }
              />
              <Field
                label={t('contracts.end_date', { defaultValue: 'End' })}
                value={
                  contract.end_date ? (
                    <DateDisplay value={contract.end_date} />
                  ) : (
                    '—'
                  )
                }
              />
              <Field
                label={t('contracts.retention_pct', {
                  defaultValue: 'Retention %',
                })}
                value={`${toNum(contract.retention_percent).toFixed(2)} %`}
              />
              <Field
                label={t('contracts.release_event', {
                  defaultValue: 'Retention release',
                })}
                value={contract.retention_release_event}
              />
            </div>
          </Card>

          {/* SoV */}
          <Card padding="sm">
            <p className="text-xs font-semibold uppercase tracking-wide text-content-secondary mb-2">
              {t('contracts.sov', { defaultValue: 'Schedule of Values' })}
              <span className="ml-2 text-content-tertiary normal-case">
                ({(linesQ.data ?? []).length}{' '}
                {t('contracts.lines', { defaultValue: 'lines' })} ·{' '}
                <MoneyDisplay
                  amount={lineTotal}
                  currency={contract.currency || undefined}
                />
                )
              </span>
            </p>
            {linesQ.isLoading ? (
              <SkeletonTable rows={3} columns={4} />
            ) : (linesQ.data ?? []).length === 0 ? (
              <p className="text-sm text-content-tertiary py-2">
                {t('contracts.no_sov', {
                  defaultValue: 'No schedule of values yet.',
                })}
              </p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="text-xs uppercase tracking-wide text-content-tertiary">
                    <tr>
                      <th className="text-left py-1">
                        {t('contracts.code', { defaultValue: 'Code' })}
                      </th>
                      <th className="text-left py-1">
                        {t('contracts.description', { defaultValue: 'Description' })}
                      </th>
                      <th className="text-right py-1">
                        {t('contracts.qty', { defaultValue: 'Qty' })}
                      </th>
                      <th className="text-right py-1">
                        {t('contracts.unit_rate', { defaultValue: 'Rate' })}
                      </th>
                      <th className="text-right py-1">
                        {t('contracts.total', { defaultValue: 'Total' })}
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {(linesQ.data ?? []).map((l: ContractLine) => (
                      <tr key={l.id} className="border-t border-border-light">
                        <td className="py-1 font-mono text-xs text-content-secondary">
                          {l.code || '—'}
                        </td>
                        <td className="py-1 truncate max-w-[260px]">
                          {l.description || '—'}
                        </td>
                        <td className="py-1 text-right text-content-secondary">
                          {toNum(l.quantity).toLocaleString()} {l.unit || ''}
                        </td>
                        <td className="py-1 text-right text-content-secondary">
                          <MoneyDisplay
                            amount={toNum(l.unit_rate)}
                            currency={contract.currency || undefined}
                          />
                        </td>
                        <td className="py-1 text-right font-medium">
                          <MoneyDisplay
                            amount={toNum(l.total_value)}
                            currency={contract.currency || undefined}
                          />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>

          {/* Retention ledger placeholder */}
          <Card padding="sm">
            <p className="text-xs font-semibold uppercase tracking-wide text-content-secondary mb-2">
              {t('contracts.retention_ledger', { defaultValue: 'Retention ledger' })}
            </p>
            <div className="grid grid-cols-2 gap-3 text-sm">
              <Field
                label={t('contracts.held', { defaultValue: 'Held' })}
                value={
                  <MoneyDisplay
                    amount={toNum(dashQ.data?.retention_held)}
                    currency={contract.currency || undefined}
                  />
                }
              />
              <Field
                label={t('contracts.release_event_short', {
                  defaultValue: 'Release on',
                })}
                value={contract.retention_release_event}
              />
            </div>
          </Card>

          {/* Claim history */}
          <Card padding="sm">
            <p className="text-xs font-semibold uppercase tracking-wide text-content-secondary mb-2">
              {t('contracts.claim_history', { defaultValue: 'Claim history' })}
              <span className="ml-2 text-content-tertiary normal-case">
                ({(claimsQ.data ?? []).length})
              </span>
            </p>
            {(claimsQ.data ?? []).length === 0 ? (
              <p className="text-sm text-content-tertiary py-2">
                {t('contracts.no_claims_yet', {
                  defaultValue: 'No progress claims yet.',
                })}
              </p>
            ) : (
              <ul className="space-y-1 text-sm">
                {(claimsQ.data ?? []).map((c) => (
                  <li
                    key={c.id}
                    className="flex items-center justify-between border-b border-border-light py-1 last:border-0"
                  >
                    <span className="font-mono text-xs text-content-secondary">
                      {c.claim_number}
                    </span>
                    <Badge variant={CLAIM_STATUS_VARIANT[c.status]} dot>
                      {claimStatusLabel(t, c.status)}
                    </Badge>
                    <span className="text-right">
                      <MoneyDisplay
                        amount={toNum(c.net_due)}
                        currency={c.currency || undefined}
                      />
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </Card>

          {/* Gainshare (only for GMP) */}
          {contract.contract_type === 'gmp' && (
            <Card padding="sm">
              <p className="text-xs font-semibold uppercase tracking-wide text-content-secondary mb-2">
                {t('contracts.gainshare', { defaultValue: 'Gainshare config' })}
              </p>
              <p className="text-sm text-content-secondary">
                {t('contracts.gainshare_hint', {
                  defaultValue:
                    'GMP contract, configure target cost, GMP cap and savings split via the API.',
                })}
              </p>
              {dashQ.data?.gainshare_estimate !== null &&
                dashQ.data?.gainshare_estimate !== undefined && (
                  <p className="mt-2 text-sm">
                    {t('contracts.gainshare_estimate', {
                      defaultValue: 'Estimated gainshare',
                    })}
                    :{' '}
                    <strong>
                      <MoneyDisplay
                        amount={toNum(dashQ.data.gainshare_estimate)}
                        currency={contract.currency || undefined}
                      />
                    </strong>
                  </p>
                )}
            </Card>
          )}
        </div>
      </div>

      {/* Compliance gate (Item #27) — runs the project rule packs before
          allowing the draft → active signature. Rendered via a portal so it
          stacks above the detail drawer. */}
      {gateOpen && (
        <ComplianceGate
          contractId={contractId}
          contractCode={contract.code}
          onSigned={() => {
            setGateOpen(false);
            invalidate();
          }}
          onClose={() => setGateOpen(false)}
        />
      )}
    </div>
  );
}

function KPI({ label, value }: { label: React.ReactNode; value: React.ReactNode }) {
  return (
    <div className="rounded-lg border border-border-light bg-surface-secondary px-3 py-2">
      <p className="text-[10px] uppercase tracking-wide text-content-tertiary">
        {label}
      </p>
      <p className="mt-0.5 text-sm font-semibold text-content-primary">
        {value}
      </p>
    </div>
  );
}

function Field({ label, value }: { label: React.ReactNode; value: React.ReactNode }) {
  return (
    <div>
      <p className="text-xs uppercase tracking-wide text-content-tertiary">
        {label}
      </p>
      <p className="mt-0.5 text-sm text-content-primary">{value}</p>
    </div>
  );
}

/* ─── Create modal ─── */

function CreateContractModal({
  projectId,
  onClose,
}: {
  projectId: string;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [busy, setBusy] = useState(false);

  const [form, setForm] = useState({
    code: '',
    title: '',
    contract_type: 'lump_sum' as ContractType,
    counterparty_type: 'subcontractor' as CounterpartyType,
    total_value: '0',
    currency: 'EUR',
    retention_percent: '5',
    start_date: todayIso(),
    end_date: '',
  });

  const submit = async () => {
    if (!form.code.trim()) {
      addToast({
        type: 'error',
        title: t('contracts.code_required', { defaultValue: 'Code is required' }),
      });
      return;
    }
    setBusy(true);
    try {
      await createContract({
        project_id: projectId,
        code: form.code.trim(),
        title: form.title.trim(),
        contract_type: form.contract_type,
        counterparty_type: form.counterparty_type,
        total_value: Number(form.total_value) || 0,
        currency: form.currency.trim().toUpperCase() || undefined,
        retention_percent: Number(form.retention_percent) || 0,
        start_date: form.start_date || null,
        end_date: form.end_date || null,
      });
      addToast({
        type: 'success',
        title: t('contracts.created_ok', { defaultValue: 'Contract created' }),
      });
      qc.invalidateQueries({ queryKey: ['contracts', 'list'] });
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
      title={t('contracts.new_contract', { defaultValue: 'New Contract' })}
      size="xl"
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
      <WideModalSection
        title={t('contracts.section_basic', { defaultValue: 'Basic info' })}
        columns={2}
      >
        <WideModalField
          label={t('contracts.code', { defaultValue: 'Code' })}
          required
        >
          <input
            value={form.code}
            onChange={(e) => setForm({ ...form, code: e.target.value })}
            className={inputCls}
            placeholder="C-2026-001"
          />
        </WideModalField>
        <WideModalField
          label={t('contracts.title_col', { defaultValue: 'Title' })}
        >
          <input
            value={form.title}
            onChange={(e) => setForm({ ...form, title: e.target.value })}
            className={inputCls}
          />
        </WideModalField>
        <WideModalField label={t('contracts.type', { defaultValue: 'Type' })}>
          <select
            value={form.contract_type}
            onChange={(e) =>
              setForm({ ...form, contract_type: e.target.value as ContractType })
            }
            className={inputCls}
          >
            {CONTRACT_TYPES.map((tp) => (
              <option key={tp} value={tp}>
                {t(`contracts.type_${tp}`, {
                  defaultValue: tp === 'tm' ? 'T&M' : tp.replace(/_/g, ' '),
                })}
              </option>
            ))}
          </select>
        </WideModalField>
        <WideModalField
          label={t('contracts.counterparty', { defaultValue: 'Counterparty' })}
        >
          <select
            value={form.counterparty_type}
            onChange={(e) =>
              setForm({
                ...form,
                counterparty_type: e.target.value as CounterpartyType,
              })
            }
            className={inputCls}
          >
            <option value="client">
              {t('contracts.cp_client', { defaultValue: 'Client' })}
            </option>
            <option value="subcontractor">
              {t('contracts.cp_subcontractor', {
                defaultValue: 'Subcontractor',
              })}
            </option>
          </select>
        </WideModalField>
      </WideModalSection>

      <WideModalSection
        title={t('contracts.section_value', { defaultValue: 'Value' })}
        columns={3}
      >
        <WideModalField label={t('contracts.value', { defaultValue: 'Value' })}>
          <input
            type="number"
            value={form.total_value}
            onChange={(e) => setForm({ ...form, total_value: e.target.value })}
            className={inputCls}
          />
        </WideModalField>
        <WideModalField
          label={t('contracts.currency', { defaultValue: 'Currency' })}
        >
          <input
            value={form.currency}
            onChange={(e) => setForm({ ...form, currency: e.target.value })}
            className={inputCls}
            maxLength={3}
          />
        </WideModalField>
        <WideModalField
          label={t('contracts.retention_pct', { defaultValue: 'Retention %' })}
        >
          <input
            type="number"
            step="0.1"
            value={form.retention_percent}
            onChange={(e) =>
              setForm({ ...form, retention_percent: e.target.value })
            }
            className={inputCls}
          />
        </WideModalField>
      </WideModalSection>

      <WideModalSection
        title={t('contracts.section_schedule', { defaultValue: 'Schedule' })}
        columns={2}
      >
        <WideModalField
          label={t('contracts.start_date', { defaultValue: 'Start' })}
        >
          <input
            type="date"
            value={form.start_date}
            onChange={(e) => setForm({ ...form, start_date: e.target.value })}
            className={inputCls}
          />
        </WideModalField>
        <WideModalField
          label={t('contracts.end_date', { defaultValue: 'End' })}
        >
          <input
            type="date"
            value={form.end_date}
            onChange={(e) => setForm({ ...form, end_date: e.target.value })}
            className={inputCls}
          />
        </WideModalField>
      </WideModalSection>
    </WideModal>
  );
}

/* ─── New claim modal ─── */

function NewClaimModal({
  contracts,
  defaultContractId,
  onClose,
}: {
  contracts: ContractItem[];
  defaultContractId: string;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [busy, setBusy] = useState(false);

  // `defaultContractId` is the most-recent contract regardless of status, but
  // claims can only be raised against an ACTIVE contract — and the <select>
  // below only renders active contracts. Seed the form with the default only
  // when it is actually one of the rendered options, otherwise fall back to the
  // first active contract so the select never starts on a blank/mismatched id.
  const initialContractId =
    contracts.find((c) => c.id === defaultContractId)?.id ??
    contracts[0]?.id ??
    '';

  const [form, setForm] = useState({
    contract_id: initialContractId,
    claim_number: '',
    period_start: todayIso(),
    period_end: todayIso(),
    currency: 'EUR',
  });

  const submit = async () => {
    if (!form.contract_id) {
      addToast({
        type: 'error',
        title: t('contracts.contract_required', {
          defaultValue: 'Contract is required',
        }),
      });
      return;
    }
    setBusy(true);
    try {
      await createProgressClaim({
        contract_id: form.contract_id,
        claim_number: form.claim_number || null,
        period_start: form.period_start || null,
        period_end: form.period_end || null,
        currency: form.currency.trim().toUpperCase() || undefined,
      });
      addToast({
        type: 'success',
        title: t('contracts.claim_created', { defaultValue: 'Claim created' }),
      });
      qc.invalidateQueries({ queryKey: ['contracts', 'claims'] });
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
      title={t('contracts.new_claim', { defaultValue: 'New Progress Claim' })}
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
          label={t('contracts.contract', { defaultValue: 'Contract' })}
          required
          span={2}
        >
          <select
            value={form.contract_id}
            onChange={(e) => setForm({ ...form, contract_id: e.target.value })}
            className={inputCls}
          >
            <option value="">
              — {t('common.select', { defaultValue: 'Select' })} —
            </option>
            {contracts.map((c) => (
              <option key={c.id} value={c.id}>
                {c.code} — {c.title || ''}
              </option>
            ))}
          </select>
        </WideModalField>
        <WideModalField
          label={t('contracts.claim_number', { defaultValue: 'Claim number' })}
        >
          <input
            value={form.claim_number}
            onChange={(e) => setForm({ ...form, claim_number: e.target.value })}
            className={inputCls}
            placeholder={t('contracts.auto', { defaultValue: 'auto' })}
          />
        </WideModalField>
        <WideModalField
          label={t('contracts.currency', { defaultValue: 'Currency' })}
        >
          <input
            value={form.currency}
            onChange={(e) => setForm({ ...form, currency: e.target.value })}
            className={inputCls}
            maxLength={3}
          />
        </WideModalField>
        <WideModalField
          label={t('contracts.period_start', { defaultValue: 'Period start' })}
        >
          <input
            type="date"
            value={form.period_start}
            onChange={(e) => setForm({ ...form, period_start: e.target.value })}
            className={inputCls}
          />
        </WideModalField>
        <WideModalField
          label={t('contracts.period_end', { defaultValue: 'Period end' })}
        >
          <input
            type="date"
            value={form.period_end}
            onChange={(e) => setForm({ ...form, period_end: e.target.value })}
            className={inputCls}
          />
        </WideModalField>
      </WideModalSection>
    </WideModal>
  );
}
