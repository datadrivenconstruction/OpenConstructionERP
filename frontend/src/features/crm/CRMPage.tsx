// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * CRM — AmoCRM-style sales pipeline.
 *
 * Centerpiece is a Kanban pipeline board: stages are columns, deals
 * (opportunities) are draggable cards. Drag a card to another column to
 * move its stage (one click → persisted via /move-stage). A fast list
 * view and a deal drawer round it out.
 *
 * Integration, not duplication:
 *   • People/companies live in the Contacts module. A deal references a
 *     contact via ``primary_contact_id``; the drawer resolves it through
 *     the Contacts API (/v1/contacts/{id}) and the quick-add picker pulls
 *     the live Contacts list. CRM never stores its own contact rows.
 *   • A deal links to a delivery/estimate Project via ``project_id``;
 *     the drawer resolves it through the Projects API and deep-links to
 *     /projects/{id}. A won deal still flows on to bid/contracts.
 */

import { useState, useMemo, useEffect, useCallback, Fragment } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import clsx from 'clsx';
import {
  DndContext,
  PointerSensor,
  useSensor,
  useSensors,
  useDraggable,
  useDroppable,
  DragOverlay,
  type DragStartEvent,
  type DragEndEvent,
} from '@dnd-kit/core';
import {
  LayoutGrid,
  List as ListIcon,
  UserPlus,
  Activity as ActivityIcon,
  Plus,
  Search,
  X,
  Loader2,
  Trophy,
  Frown,
  AlertTriangle,
  FolderKanban,
  User,
  Phone,
  Mail,
  ArrowRight,
  GripVertical,
  CheckCircle2,
  XCircle,
  BarChart3,
  History,
  Info,
  Clock,
  Network,
  FileSignature,
  Trash2,
} from 'lucide-react';
import {
  Button,
  Card,
  Badge,
  EmptyState,
  Breadcrumb,
  SkeletonTable,
  DismissibleInfo,
  IntroRichText,
  ModuleGuideButton,
  CollapsibleSection,
} from '@/shared/ui';
import { PageHeader } from '@/shared/ui/PageHeader';
import { ConfirmDialog } from '@/shared/ui/ConfirmDialog';
import { useAuthStore } from '@/stores/useAuthStore';
import { crmGuide } from './crmGuide';
import {
  WideModal,
  WideModalSection,
  WideModalField,
} from '@/shared/ui/WideModal';
import { MoneyDisplay } from '@/shared/ui/MoneyDisplay';
import { MultiCurrencyTotal } from '@/shared/ui/MultiCurrencyTotal';
import { DateDisplay } from '@/shared/ui/DateDisplay';
import { TruncationNotice } from '@/shared/ui/TruncationNotice';
import { useToastStore } from '@/stores/useToastStore';
import { getErrorMessage } from '@/shared/lib/api';
import { fetchContact, fetchContacts, type Contact } from '@/features/contacts/api';
import { projectsApi, type Project } from '@/features/projects/api';
import {
  listAccounts,
  listLeads,
  listOpportunities,
  listActivities,
  listPipelineStages,
  createAccount,
  createLead,
  createOpportunity,
  updateOpportunity,
  createActivity,
  qualifyLead,
  disqualifyLead,
  deleteLead,
  parseRemovalRefusal,
  convertLead,
  moveOpportunityStage,
  winOpportunity,
  loseOpportunity,
  listWinLossReasons,
  getOpportunityHistory,
  getCrmDashboard,
  getWinLossAnalytics,
  type WinLossReason,
  type Account,
  type Lead,
  type Opportunity,
  type Activity,
  type PipelineStage,
  type StageHistory,
  type LeadStatus,
  type LeadSource,
  type OpportunityStatus,
  type ActivityKind,
  type RemovalRefusal,
} from './api';

type View = 'pipeline' | 'list' | 'leads' | 'activities' | 'insights';

const LEAD_STATUS_VARIANT: Record<
  LeadStatus,
  'neutral' | 'blue' | 'success' | 'warning' | 'error'
> = {
  new: 'neutral',
  qualifying: 'warning',
  qualified: 'success',
  disqualified: 'error',
  converted: 'blue',
};

const OPP_STATUS_VARIANT: Record<
  OpportunityStatus,
  'neutral' | 'blue' | 'success' | 'warning' | 'error'
> = {
  open: 'blue',
  won: 'success',
  lost: 'error',
  abandoned: 'neutral',
};

// English fallbacks for the two status enums. The screen always shows the
// translated label — the storage token (``qualifying``, ``won``) is never
// rendered on its own.
const LEAD_STATUS_EN: Record<LeadStatus, string> = {
  new: 'New',
  qualifying: 'Qualifying',
  qualified: 'Qualified',
  disqualified: 'Disqualified',
  converted: 'Converted',
};

const OPP_STATUS_EN: Record<OpportunityStatus, string> = {
  open: 'Open',
  won: 'Won',
  lost: 'Lost',
  abandoned: 'Abandoned',
};

function leadStatusLabel(s: LeadStatus, t: TFn): string {
  return t(`crm.lead_status_${s}`, { defaultValue: LEAD_STATUS_EN[s] });
}

function oppStatusLabel(s: OpportunityStatus, t: TFn): string {
  return t(`crm.opp_status_${s}`, { defaultValue: OPP_STATUS_EN[s] });
}

const LEAD_SOURCES: LeadSource[] = [
  'web',
  'referral',
  'event',
  'cold_outreach',
  'inbound',
];

const ACTIVITY_KINDS: ActivityKind[] = ['call', 'meeting', 'email', 'task', 'note'];

// ISO-4217 codes offered in the deal currency picker. Keeps multi-currency
// rollups (MultiCurrencyTotal / MoneyDisplay) consistent by preventing
// free-text codes that would key the per-currency split incorrectly.
const CURRENCY_CODES = [
  'EUR',
  'USD',
  'GBP',
  'CHF',
  'CAD',
  'AUD',
  'NZD',
  'SEK',
  'NOK',
  'DKK',
  'PLN',
  'CZK',
  'JPY',
  'CNY',
  'INR',
  'BRL',
  'AED',
  'SAR',
  'ZAR',
  'TRY',
];

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

function contactLabel(c: Contact | undefined): string {
  if (!c) return '';
  return (
    c.company_name ||
    [c.first_name, c.last_name].filter(Boolean).join(' ') ||
    c.primary_email ||
    c.id
  );
}

/* ═══════════════ How it works + connects ═══════════════ */

/** Compact inline link to a sibling module (keeps the flow copy readable). */
function ModLink({ to, children }: { to: string; children: React.ReactNode }) {
  return (
    <Link to={to} className="font-medium text-oe-blue-text hover:underline">
      {children}
    </Link>
  );
}

/**
 * One-glance map of what the CRM does and how it connects to the rest of the
 * platform: people come from Contacts, and a won deal flows on to bid packages
 * and contracts. Every connected module is a link so the workflow is obvious
 * without reading the whole page.
 */
function HowCrmWorks() {
  const { t } = useTranslation();

  const steps: { icon: React.ReactNode; title: string; desc: string }[] = [
    {
      icon: <UserPlus size={14} className="text-oe-blue" />,
      title: t('crm.flow_1_title', { defaultValue: 'Capture a lead' }),
      desc: t('crm.flow_1_desc', {
        defaultValue: 'Log an inbound enquiry, with the person pulled from Contacts.',
      }),
    },
    {
      icon: <CheckCircle2 size={14} className="text-oe-blue" />,
      title: t('crm.flow_2_title', { defaultValue: 'Qualify' }),
      desc: t('crm.flow_2_desc', {
        defaultValue: 'Qualify the lead, then convert it into a deal.',
      }),
    },
    {
      icon: <LayoutGrid size={14} className="text-oe-blue" />,
      title: t('crm.flow_3_title', { defaultValue: 'Work the pipeline' }),
      desc: t('crm.flow_3_desc', {
        defaultValue: 'Drag the deal stage by stage, logging each call and email.',
      }),
    },
    {
      icon: <Trophy size={14} className="text-oe-blue" />,
      title: t('crm.flow_4_title', { defaultValue: 'Win or lose' }),
      desc: t('crm.flow_4_desc', {
        defaultValue: 'Close with a win or loss reason so your insights stay honest.',
      }),
    },
    {
      icon: <FileSignature size={14} className="text-oe-blue" />,
      title: t('crm.flow_5_title', { defaultValue: 'Hand off' }),
      desc: t('crm.flow_5_desc', {
        defaultValue: 'A won deal links to its project and flows on to bids and contracts.',
      }),
    },
  ];

  return (
    <CollapsibleSection
      storageKey="crm.how"
      icon={<Network size={15} className="text-oe-blue" />}
      title={t('crm.flow_title', { defaultValue: 'How the CRM fits together' })}
    >
      <p className="text-xs text-content-tertiary">
        {t('crm.flow_intro', {
          defaultValue:
            'The CRM turns an enquiry into a qualified deal, moves it across the pipeline, and hands a win off to delivery. People come from Contacts; won work flows on to bids and contracts.',
        })}
      </p>

      <ol className="mt-3 flex flex-col gap-2 lg:flex-row lg:items-stretch">
        {steps.map((s, i) => (
          <Fragment key={s.title}>
            <li className="flex-1 rounded-lg border border-border-light bg-surface-secondary/40 p-3">
              <div className="flex items-center gap-2">
                <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-oe-blue-subtle text-2xs font-bold text-oe-blue-text">
                  {i + 1}
                </span>
                <span className="flex items-center gap-1 text-xs font-semibold text-content-primary">
                  {s.icon}
                  {s.title}
                </span>
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

      <div className="mt-3 flex flex-col gap-1.5 border-t border-border-light pt-3 text-2xs text-content-tertiary sm:flex-row sm:flex-wrap sm:items-center sm:gap-x-5 sm:gap-y-1">
        <span>
          <span className="font-medium text-content-secondary">
            {t('crm.flow_pulls', { defaultValue: 'Pulls from:' })}
          </span>{' '}
          <ModLink to="/contacts">
            {t('crm.mod_contacts', { defaultValue: 'Contacts' })}
          </ModLink>
        </span>
        <span>
          <span className="font-medium text-content-secondary">
            {t('crm.flow_feeds', { defaultValue: 'Feeds:' })}
          </span>{' '}
          <ModLink to="/bid-management">
            {t('crm.mod_bid', { defaultValue: 'Bid Management' })}
          </ModLink>{' '}
          ·{' '}
          <ModLink to="/contracts">
            {t('crm.mod_contracts', { defaultValue: 'Contracts' })}
          </ModLink>{' '}
          ·{' '}
          <ModLink to="/tendering">
            {t('crm.mod_tendering', { defaultValue: 'Tendering' })}
          </ModLink>
        </span>
      </div>
    </CollapsibleSection>
  );
}

/* ═══════════════ Page ═══════════════ */

export function CRMPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [view, setView] = useState<View>('pipeline');
  const [search, setSearch] = useState('');
  const [createOpen, setCreateOpen] = useState(false);
  const [selectedOpportunityId, setSelectedOpportunityId] = useState<
    string | null
  >(null);
  const [selectedLeadId, setSelectedLeadId] = useState<string | null>(null);

  const accountsQ = useQuery({
    queryKey: ['crm', 'accounts'],
    queryFn: () => listAccounts({ limit: 200 }),
  });
  const stagesQ = useQuery({
    queryKey: ['crm', 'pipeline-stages'],
    queryFn: () => listPipelineStages(),
  });
  const oppsQ = useQuery({
    queryKey: ['crm', 'opportunities'],
    // Backend caps /v1/crm/opportunities/?limit at 200 (422 above it).
    // Passing 500 was a 422 every time the CRM page mounted — see user
    // error log 2026-05-22.
    queryFn: () => listOpportunities({ limit: 200 }),
    enabled: view === 'pipeline' || view === 'list',
  });
  const leadsQ = useQuery({
    queryKey: ['crm', 'leads'],
    queryFn: () => listLeads({ limit: 200 }),
    enabled: view === 'leads',
  });
  const activitiesQ = useQuery({
    queryKey: ['crm', 'activities'],
    queryFn: () => listActivities({ limit: 200 }),
    enabled: view === 'activities',
  });

  const stagesSorted = useMemo<PipelineStage[]>(
    () =>
      [...(stagesQ.data ?? [])].sort(
        (a, b) => a.display_order - b.display_order,
      ),
    [stagesQ.data],
  );
  const stagesById = useMemo<Record<string, PipelineStage>>(() => {
    const m: Record<string, PipelineStage> = {};
    (stagesQ.data ?? []).forEach((s) => (m[s.id] = s));
    return m;
  }, [stagesQ.data]);
  const accountsById = useMemo<Record<string, Account>>(() => {
    const m: Record<string, Account> = {};
    (accountsQ.data ?? []).forEach((a) => (m[a.id] = a));
    return m;
  }, [accountsQ.data]);

  const searchLc = search.trim().toLowerCase();
  const filteredOpps = useMemo(() => {
    return (oppsQ.data ?? []).filter((o) => {
      if (!searchLc) return true;
      return (
        o.title.toLowerCase().includes(searchLc) ||
        (accountsById[o.account_id]?.name || '')
          .toLowerCase()
          .includes(searchLc)
      );
    });
  }, [oppsQ.data, accountsById, searchLc]);

  const filteredLeads = useMemo(() => {
    return (leadsQ.data ?? []).filter((l) => {
      if (!searchLc) return true;
      return (
        l.contact_name.toLowerCase().includes(searchLc) ||
        (l.contact_email || '').toLowerCase().includes(searchLc)
      );
    });
  }, [leadsQ.data, searchLc]);

  const filteredActivities = useMemo(() => {
    return (activitiesQ.data ?? []).filter((a) => {
      if (!searchLc) return true;
      return (
        a.subject.toLowerCase().includes(searchLc) ||
        (a.body || '').toLowerCase().includes(searchLc)
      );
    });
  }, [activitiesQ.data, searchLc]);

  const loading =
    ((view === 'pipeline' || view === 'list') &&
      (oppsQ.isLoading || stagesQ.isLoading || accountsQ.isLoading)) ||
    (view === 'leads' && leadsQ.isLoading) ||
    (view === 'activities' && activitiesQ.isLoading);

  const activeError =
    view === 'pipeline' || view === 'list'
      ? (oppsQ.error ?? stagesQ.error ?? accountsQ.error)
      : view === 'leads'
        ? leadsQ.error
        : view === 'activities'
          ? activitiesQ.error
          : null;
  const isError = !loading && Boolean(activeError);

  const TABS: { id: View; label: string; icon: React.ElementType }[] = [
    {
      id: 'pipeline',
      label: t('crm.tab_pipeline', { defaultValue: 'Pipeline' }),
      icon: LayoutGrid,
    },
    {
      id: 'list',
      label: t('crm.tab_deals', { defaultValue: 'Deals' }),
      icon: ListIcon,
    },
    {
      id: 'leads',
      label: t('crm.tab_leads', { defaultValue: 'Leads' }),
      icon: UserPlus,
    },
    {
      id: 'activities',
      label: t('crm.tab_activities', { defaultValue: 'Activities' }),
      icon: ActivityIcon,
    },
    {
      id: 'insights',
      label: t('crm.tab_insights', { defaultValue: 'Insights' }),
      icon: BarChart3,
    },
  ];

  const newLabel =
    view === 'leads'
      ? t('crm.new_lead', { defaultValue: 'New Lead' })
      : view === 'activities'
        ? t('crm.new_activity', { defaultValue: 'New Activity' })
        : t('crm.new_deal', { defaultValue: 'New Deal' });

  return (
    <div className="space-y-5 animate-fade-in">
      <Breadcrumb items={[{ label: t('nav.crm', { defaultValue: 'CRM' }) }]} />

      <PageHeader
        srTitle={t('nav.crm', { defaultValue: 'CRM' })}
        subtitle={t('crm.subtitle_amo', {
          defaultValue:
            'Drag deals across the pipeline, log activity in a click. People come from Contacts, won deals link to Projects.',
        })}
        actions={
          <>
            <ModuleGuideButton
              content={crmGuide}
              onCta={() => setCreateOpen(true)}
            />
            {view !== 'insights' && (
              <Button
                variant="primary"
                icon={<Plus size={14} />}
                onClick={() => setCreateOpen(true)}
              >
                {newLabel}
              </Button>
            )}
          </>
        }
      />

      <DismissibleInfo
        storageKey="crm"
        title={t('crm.intro_title', {
          defaultValue: 'Stop losing deals between the cracks',
        })}
        more={
          t('crm.intro_more', { defaultValue: '' })
            ? <IntroRichText text={t('crm.intro_more')} />
            : undefined
        }
        links={[
          {
            label: t('contacts.title', { defaultValue: 'Contacts' }),
            onClick: () => navigate('/contacts'),
          },
          {
            label: t('nav.bid_management', { defaultValue: 'Bid Management' }),
            onClick: () => navigate('/bid-management'),
          },
          {
            label: t('nav.contracts', { defaultValue: 'Contracts' }),
            onClick: () => navigate('/contracts'),
          },
        ]}
      >
        {t('crm.intro_body', {
          defaultValue:
            'Qualify a lead and drag the deal stage by stage across the pipeline board, logging each call or email in one click. People and companies come from Contacts, and a won deal links to its delivery project and flows on to bid packages and contracts.',
        })}
      </DismissibleInfo>

      <HowCrmWorks />

      {/* View switcher + search */}
      <div className="flex flex-wrap items-center gap-3">
        <div className="inline-flex rounded-lg border border-border-light bg-surface-secondary p-0.5">
          {TABS.map((it) => {
            const Icon = it.icon;
            const active = view === it.id;
            return (
              <button
                key={it.id}
                type="button"
                onClick={() => {
                  setView(it.id);
                  setSearch('');
                }}
                className={clsx(
                  'inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium transition-colors',
                  active
                    ? 'bg-surface-primary text-oe-blue shadow-sm'
                    : 'text-content-secondary hover:text-content-primary',
                )}
              >
                <Icon size={14} />
                {it.label}
              </button>
            );
          })}
        </div>
        {view !== 'insights' && (
          <div className="relative flex-1 min-w-[200px] max-w-sm">
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
        )}
      </div>

      {/* Body */}
      {loading ? (
        <Card padding="md">
          <SkeletonTable rows={8} columns={5} />
        </Card>
      ) : isError ? (
        <Card padding="none">
          <EmptyState
            icon={<AlertTriangle size={22} />}
            title={t('crm.load_failed', {
              defaultValue: 'Could not load CRM data',
            })}
            description={getErrorMessage(activeError)}
          />
        </Card>
      ) : view === 'pipeline' ? (
        <PipelineBoard
          stages={stagesSorted}
          opportunities={filteredOpps}
          accountsById={accountsById}
          onSelect={setSelectedOpportunityId}
          onCreate={() => setCreateOpen(true)}
        />
      ) : view === 'list' ? (
        <Card padding="none">
          <DealsTable
            rows={filteredOpps}
            accountsById={accountsById}
            stagesById={stagesById}
            onSelect={setSelectedOpportunityId}
            onCreate={() => setCreateOpen(true)}
          />
        </Card>
      ) : view === 'leads' ? (
        <Card padding="none">
          <LeadsTable
            rows={filteredLeads}
            accountsById={accountsById}
            onSelect={setSelectedLeadId}
            onCreate={() => setCreateOpen(true)}
          />
        </Card>
      ) : view === 'activities' ? (
        <Card padding="none">
          <ActivitiesTable
            rows={filteredActivities}
            onCreate={() => setCreateOpen(true)}
          />
        </Card>
      ) : (
        <InsightsPanel stagesById={stagesById} />
      )}

      {selectedOpportunityId && (
        <DealDrawer
          opportunityId={selectedOpportunityId}
          opportunities={oppsQ.data ?? []}
          stages={stagesSorted}
          accountsById={accountsById}
          onClose={() => setSelectedOpportunityId(null)}
        />
      )}
      {selectedLeadId && (
        <LeadDrawer
          leadId={selectedLeadId}
          leads={leadsQ.data ?? []}
          accountsById={accountsById}
          accounts={accountsQ.data ?? []}
          stages={stagesSorted}
          onConverted={(opportunityId) => {
            setSelectedLeadId(null);
            setView('pipeline');
            setSelectedOpportunityId(opportunityId);
          }}
          onClose={() => setSelectedLeadId(null)}
        />
      )}
      {createOpen && (
        <CreateModal
          view={view}
          accounts={accountsQ.data ?? []}
          stages={stagesSorted}
          onClose={() => setCreateOpen(false)}
        />
      )}
    </div>
  );
}

/* ═══════════════ Pipeline board (Kanban, drag-and-drop) ═══════════════ */

function stageAccent(stage: PipelineStage): string {
  if (stage.color && /^#?[0-9a-fA-F]{3,8}$/.test(stage.color)) return stage.color;
  if (stage.is_won) return '#22c55e';
  if (stage.is_lost) return '#ef4444';
  return '#38bdf8';
}

function PipelineBoard({
  stages,
  opportunities,
  accountsById,
  onSelect,
  onCreate,
}: {
  stages: PipelineStage[];
  opportunities: Opportunity[];
  accountsById: Record<string, Account>;
  onSelect: (id: string) => void;
  onCreate: () => void;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [activeId, setActiveId] = useState<string | null>(null);

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 6 } }),
  );

  // Only open deals move through stages; closed deals are read-only here.
  const openOpps = useMemo(
    () => opportunities.filter((o) => o.status === 'open'),
    [opportunities],
  );

  const byStage = useMemo(() => {
    const m: Record<string, Opportunity[]> = {};
    stages.forEach((s) => (m[s.id] = []));
    openOpps.forEach((o) => {
      (m[o.stage_id] = m[o.stage_id] || []).push(o);
    });
    return m;
  }, [stages, openOpps]);

  const moveMut = useMutation({
    mutationFn: ({ id, toStageId }: { id: string; toStageId: string }) =>
      moveOpportunityStage(id, { to_stage_id: toStageId }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['crm', 'opportunities'] });
      addToast({
        type: 'success',
        title: t('crm.stage_moved', { defaultValue: 'Stage updated' }),
      });
    },
    onError: (err) => {
      qc.invalidateQueries({ queryKey: ['crm', 'opportunities'] });
      addToast({ type: 'error', title: getErrorMessage(err) });
    },
  });

  const activeOpp = activeId
    ? openOpps.find((o) => o.id === activeId)
    : undefined;

  const handleDragStart = useCallback((e: DragStartEvent) => {
    setActiveId(String(e.active.id));
  }, []);

  const handleDragEnd = useCallback(
    (e: DragEndEvent) => {
      setActiveId(null);
      const id = String(e.active.id);
      const overId = e.over ? String(e.over.id) : null;
      if (!overId) return;
      const opp = openOpps.find((o) => o.id === id);
      if (!opp || opp.stage_id === overId) return;
      const targetStage = stages.find((s) => s.id === overId);
      // Final won/lost stages must go through the win/lose flow — block
      // the drop and tell the user (mirrors the backend guard).
      if (targetStage && targetStage.is_final && (targetStage.is_won || targetStage.is_lost)) {
        addToast({
          type: 'info',
          title: t('crm.use_close_flow', {
            defaultValue:
              'Open the deal and use Win / Lose to close it.',
          }),
        });
        return;
      }
      moveMut.mutate({ id, toStageId: overId });
    },
    [openOpps, stages, moveMut, addToast, t],
  );

  if (stages.length === 0) {
    return (
      <Card padding="none">
        <EmptyState
          icon={<LayoutGrid size={22} />}
          title={t('crm.no_stages', { defaultValue: 'No pipeline stages' })}
          description={t('crm.no_stages_desc', {
            defaultValue:
              'Pipeline stages are not configured yet. Seed data or add a stage to start.',
          })}
        />
      </Card>
    );
  }

  return (
    <DndContext
      sensors={sensors}
      onDragStart={handleDragStart}
      onDragEnd={handleDragEnd}
      onDragCancel={() => setActiveId(null)}
    >
      <div className="flex gap-3 overflow-x-auto pb-3">
        {stages.map((stage) => {
          const items = byStage[stage.id] ?? [];
          // Wave-10 fix: stage rollups no longer sum mixed-currency
          // opportunities into a single first-seen-code number. The
          // <MultiCurrencyTotal> grouping below honours per-deal codes
          // and renders one chip per currency (sum within each).
          const totalItems = items.map((o) => ({
            amount: toNum(o.estimated_value),
            currency: o.currency || null,
          }));
          const isClosingStage =
            stage.is_final && (stage.is_won || stage.is_lost);
          return (
            <StageColumn
              key={stage.id}
              stage={stage}
              count={items.length}
              totalItems={totalItems}
              droppable={!isClosingStage}
            >
              {items.length === 0 ? (
                <p className="px-1 py-6 text-center text-xs text-content-tertiary">
                  {isClosingStage
                    ? t('crm.close_via_drawer', {
                        defaultValue: 'Close deals from the deal view',
                      })
                    : t('crm.drop_here', {
                        defaultValue: 'Drop a deal here',
                      })}
                </p>
              ) : (
                items.map((o) => (
                  <DealCard
                    key={o.id}
                    opp={o}
                    accountName={accountsById[o.account_id]?.name || ''}
                    onClick={() => onSelect(o.id)}
                  />
                ))
              )}
            </StageColumn>
          );
        })}
        <div className="shrink-0 w-72 pt-1">
          <button
            type="button"
            onClick={onCreate}
            className="flex w-full items-center justify-center gap-1.5 rounded-xl border border-dashed border-border-light px-3 py-3 text-sm text-content-secondary hover:border-oe-blue hover:text-oe-blue transition-colors"
          >
            <Plus size={14} />
            {t('crm.new_deal', { defaultValue: 'New Deal' })}
          </button>
        </div>
      </div>

      <DragOverlay dropAnimation={null}>
        {activeOpp ? (
          <DealCard
            opp={activeOpp}
            accountName={accountsById[activeOpp.account_id]?.name || ''}
            dragging
          />
        ) : null}
      </DragOverlay>
    </DndContext>
  );
}

function StageColumn({
  stage,
  count,
  totalItems,
  droppable,
  children,
}: {
  stage: PipelineStage;
  count: number;
  /** Per-deal {amount, currency} pairs for the rollup. Mixed currencies
   *  render as a chip strip via <MultiCurrencyTotal>; single-currency
   *  columns degrade to a plain MoneyDisplay (no visual churn). */
  totalItems: { amount: number; currency: string | null }[];
  droppable: boolean;
  children: React.ReactNode;
}) {
  const { setNodeRef, isOver } = useDroppable({
    id: stage.id,
    disabled: !droppable,
  });
  const accent = stageAccent(stage);
  return (
    <div className="flex w-72 shrink-0 flex-col">
      <div
        className="flex items-center justify-between rounded-t-xl border border-b-0 border-border-light bg-surface-secondary px-3 py-2"
        style={{ borderTop: `3px solid ${accent}` }}
      >
        <div className="min-w-0">
          <p className="truncate text-sm font-semibold text-content-primary">
            {stage.name}
          </p>
          <p className="text-[11px] text-content-tertiary">
            {count} · <MultiCurrencyTotal variant="inline" items={totalItems} compact />
          </p>
        </div>
        <span className="ml-2 inline-flex h-5 min-w-[20px] items-center justify-center rounded-full bg-surface-primary px-1.5 text-[11px] font-medium text-content-secondary">
          {count}
        </span>
      </div>
      <div
        ref={setNodeRef}
        className={clsx(
          'flex-1 space-y-2 rounded-b-xl border border-border-light bg-surface-secondary/40 p-2 min-h-[140px] transition-colors',
          isOver && droppable && 'bg-oe-blue/10 ring-2 ring-inset ring-oe-blue/40',
        )}
      >
        {children}
      </div>
    </div>
  );
}

function DealCard({
  opp,
  accountName,
  onClick,
  dragging,
}: {
  opp: Opportunity;
  accountName: string;
  onClick?: () => void;
  dragging?: boolean;
}) {
  const { t } = useTranslation();
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({
    id: opp.id,
  });
  return (
    <div
      ref={setNodeRef}
      className={clsx(
        'group rounded-lg border border-border-light bg-surface-primary p-2.5 shadow-sm',
        (isDragging || dragging) && 'opacity-60',
        dragging && 'ring-2 ring-oe-blue/40 cursor-grabbing',
      )}
    >
      <div className="flex items-start gap-1.5">
        <button
          type="button"
          aria-label={t('crm.drag_deal', { defaultValue: 'Drag to move deal' })}
          className="mt-0.5 cursor-grab text-content-tertiary opacity-0 group-hover:opacity-100 touch-none"
          {...attributes}
          {...listeners}
        >
          <GripVertical size={13} />
        </button>
        <button
          type="button"
          onClick={onClick}
          className="min-w-0 flex-1 text-left"
        >
          <p className="truncate text-sm font-medium text-content-primary">
            {opp.title}
          </p>
          {accountName && (
            <p className="mt-0.5 truncate text-xs text-content-secondary">
              {accountName}
            </p>
          )}
          <div className="mt-1.5 flex items-center justify-between gap-2">
            <span className="text-sm font-semibold text-content-primary">
              <MoneyDisplay
                amount={toNum(opp.estimated_value)}
                currency={opp.currency || undefined}
              />
            </span>
            <span className="text-[11px] text-content-tertiary">
              {opp.probability_percent}%
            </span>
          </div>
        </button>
      </div>
    </div>
  );
}

/* ═══════════════ Deals list ═══════════════ */

function DealsTable({
  rows,
  accountsById,
  stagesById,
  onSelect,
  onCreate,
}: {
  rows: Opportunity[];
  accountsById: Record<string, Account>;
  stagesById: Record<string, PipelineStage>;
  onSelect: (id: string) => void;
  onCreate: () => void;
}) {
  const { t } = useTranslation();
  if (rows.length === 0) {
    return (
      <EmptyState
        icon={<ListIcon size={22} />}
        title={t('crm.empty_deals', { defaultValue: 'No deals yet' })}
        description={t('crm.empty_deals_desc', {
          defaultValue:
            'Create a deal and drag it through the pipeline: qualification → proposal → negotiation → won.',
        })}
        action={{
          label: t('crm.new_deal', { defaultValue: 'New Deal' }),
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
              {t('crm.title_col', { defaultValue: 'Deal' })}
            </th>
            <th className="px-4 py-2.5 text-left">
              {t('crm.account', { defaultValue: 'Account' })}
            </th>
            <th className="px-4 py-2.5 text-left">
              {t('crm.stage', { defaultValue: 'Stage' })}
            </th>
            <th className="px-4 py-2.5 text-left">
              {t('crm.status', { defaultValue: 'Status' })}
            </th>
            <th className="px-4 py-2.5 text-right">
              {t('crm.value', { defaultValue: 'Value' })}
            </th>
            <th className="px-4 py-2.5 text-right">
              {t('crm.weighted', { defaultValue: 'Weighted' })}
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => {
            const stage = stagesById[r.stage_id];
            return (
              <tr
                key={r.id}
                onClick={() => onSelect(r.id)}
                className="border-t border-border-light hover:bg-surface-secondary cursor-pointer"
              >
                <td className="px-4 py-2 font-medium text-content-primary truncate max-w-[260px]">
                  {r.title}
                </td>
                <td className="px-4 py-2 text-content-secondary">
                  {accountsById[r.account_id]?.name || '—'}
                </td>
                <td className="px-4 py-2">
                  {stage ? (
                    <span
                      className="inline-flex items-center gap-1.5 rounded-md px-2 py-0.5 text-xs font-medium ring-1 ring-inset ring-border-light"
                    >
                      <span
                        className="h-2 w-2 rounded-full"
                        style={{ backgroundColor: stageAccent(stage) }}
                      />
                      {stage.name} · {r.probability_percent}%
                    </span>
                  ) : (
                    <span className="text-xs text-content-tertiary">
                      {r.probability_percent}%
                    </span>
                  )}
                </td>
                <td className="px-4 py-2">
                  <Badge variant={OPP_STATUS_VARIANT[r.status]} dot>
                    {oppStatusLabel(r.status, t)}
                  </Badge>
                </td>
                <td className="px-4 py-2 text-right">
                  <MoneyDisplay
                    amount={toNum(r.estimated_value)}
                    currency={r.currency || undefined}
                  />
                </td>
                <td className="px-4 py-2 text-right text-content-secondary">
                  <MoneyDisplay
                    amount={toNum(r.weighted_value)}
                    currency={r.currency || undefined}
                  />
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

/* ═══════════════ Leads list ═══════════════ */

function LeadsTable({
  rows,
  accountsById,
  onSelect,
  onCreate,
}: {
  rows: Lead[];
  accountsById: Record<string, Account>;
  onSelect: (id: string) => void;
  onCreate: () => void;
}) {
  const { t } = useTranslation();
  if (rows.length === 0) {
    return (
      <EmptyState
        icon={<UserPlus size={22} />}
        title={t('crm.empty_leads', { defaultValue: 'No leads yet' })}
        description={t('crm.empty_leads_desc', {
          defaultValue:
            'Leads are inbound enquiries - qualify them, then convert to deals.',
        })}
        action={{
          label: t('crm.new_lead', { defaultValue: 'New Lead' }),
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
              {t('crm.contact', { defaultValue: 'Contact' })}
            </th>
            <th className="px-4 py-2.5 text-left">
              {t('crm.account', { defaultValue: 'Account' })}
            </th>
            <th className="px-4 py-2.5 text-left">
              {t('crm.source', { defaultValue: 'Source' })}
            </th>
            <th className="px-4 py-2.5 text-left">
              {t('crm.status', { defaultValue: 'Status' })}
            </th>
            <th className="px-4 py-2.5 text-left">
              {t('crm.created', { defaultValue: 'Created' })}
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
              <td className="px-4 py-2">
                <div className="font-medium">{r.contact_name}</div>
                <div className="text-xs text-content-tertiary">
                  {r.contact_email || r.contact_phone || ''}
                </div>
              </td>
              <td className="px-4 py-2 text-content-secondary">
                {r.account_id ? accountsById[r.account_id]?.name || '—' : '—'}
              </td>
              <td className="px-4 py-2 text-xs text-content-secondary capitalize">
                {r.source.replace(/_/g, ' ')}
              </td>
              <td className="px-4 py-2">
                <Badge variant={LEAD_STATUS_VARIANT[r.status]} dot>
                  {leadStatusLabel(r.status, t)}
                </Badge>
              </td>
              <td className="px-4 py-2 text-xs text-content-secondary">
                <DateDisplay value={r.created_at} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/* ═══════════════ Activities list ═══════════════ */

function ActivitiesTable({
  rows,
  onCreate,
}: {
  rows: Activity[];
  onCreate: () => void;
}) {
  const { t } = useTranslation();
  if (rows.length === 0) {
    return (
      <EmptyState
        icon={<ActivityIcon size={22} />}
        title={t('crm.empty_activities', { defaultValue: 'No activities yet' })}
        description={t('crm.empty_activities_desc', {
          defaultValue:
            'Log calls, meetings, emails and tasks tied to deals or leads.',
        })}
        action={{
          label: t('crm.new_activity', { defaultValue: 'New Activity' }),
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
              {t('crm.kind', { defaultValue: 'Kind' })}
            </th>
            <th className="px-4 py-2.5 text-left">
              {t('crm.subject', { defaultValue: 'Subject' })}
            </th>
            <th className="px-4 py-2.5 text-left">
              {t('crm.due', { defaultValue: 'Due' })}
            </th>
            <th className="px-4 py-2.5 text-left">
              {t('crm.outcome', { defaultValue: 'Outcome' })}
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr
              key={r.id}
              className="border-t border-border-light hover:bg-surface-secondary"
            >
              <td className="px-4 py-2 text-xs text-content-secondary capitalize">
                {r.kind}
              </td>
              <td className="px-4 py-2 font-medium truncate max-w-[360px]">
                {r.subject || '—'}
              </td>
              <td className="px-4 py-2 text-xs text-content-secondary">
                {r.due_at ? <DateDisplay value={r.due_at} /> : '—'}
              </td>
              <td className="px-4 py-2 text-xs text-content-secondary">
                {r.outcome || '—'}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/* ═══════════════ Deal drawer ═══════════════ */

function DealDrawer({
  opportunityId,
  opportunities,
  stages,
  accountsById,
  onClose,
}: {
  opportunityId: string;
  opportunities: Opportunity[];
  stages: PipelineStage[];
  accountsById: Record<string, Account>;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const opp = opportunities.find((o) => o.id === opportunityId);

  const [loseReason, setLoseReason] = useState('');
  const [winReason, setWinReason] = useState('');
  const [noteText, setNoteText] = useState('');
  const [linkOpen, setLinkOpen] = useState(false);

  const activitiesQ = useQuery({
    queryKey: ['crm', 'activities', 'opp', opportunityId],
    queryFn: () => listActivities({ opportunity_id: opportunityId, limit: 50 }),
  });

  // Stage-history audit trail (from→to with dwell time). Backed by
  // GET /opportunities/{id}/history; refetched whenever the opportunity
  // list invalidates after a stage move / win / lose.
  const historyQ = useQuery({
    queryKey: ['crm', 'opp-history', opportunityId],
    queryFn: () => getOpportunityHistory(opportunityId),
  });

  // Loss-reason codes come from the win-loss-reasons catalogue — the backend
  // rejects any code that is not a registered loss reason, so the picker must
  // offer exactly those (a free-text box silently 4xx'd on submit).
  const lossReasonsQ = useQuery({
    queryKey: ['crm', 'win-loss-reasons'],
    queryFn: () => listWinLossReasons(),
  });
  const lossReasons = (lossReasonsQ.data ?? []).filter(
    (r: WinLossReason) => r.is_loss_reason,
  );
  const winReasons = (lossReasonsQ.data ?? []).filter(
    (r: WinLossReason) => r.is_win_reason,
  );

  // Resolve the linked Contact through the Contacts module (no local copy).
  // Asks for the one contact by id. It used to pull 500 rows and search them,
  // which answered "no such contact" for every contact past the page - a
  // silent wrong answer, since the drawer just rendered the empty state.
  const contactQ = useQuery({
    queryKey: ['contacts', 'one', opp?.primary_contact_id],
    queryFn: () => fetchContact(opp!.primary_contact_id as string).catch(() => null),
    enabled: Boolean(opp?.primary_contact_id),
  });

  // Resolve the linked Project through the Projects module.
  const projectQ = useQuery({
    queryKey: ['projects', 'one', opp?.project_id],
    queryFn: () =>
      projectsApi
        .get(opp!.project_id as string)
        .catch(() => null as Project | null),
    enabled: Boolean(opp?.project_id),
  });

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onClose]);

  const moveMut = useMutation({
    mutationFn: (toStageId: string) =>
      moveOpportunityStage(opportunityId, { to_stage_id: toStageId }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['crm', 'opportunities'] });
      qc.invalidateQueries({ queryKey: ['crm', 'opp-history', opportunityId] });
      addToast({
        type: 'success',
        title: t('crm.stage_moved', { defaultValue: 'Stage updated' }),
      });
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  const winMut = useMutation({
    mutationFn: () =>
      winOpportunity(opportunityId, {
        won_at: todayIso(),
        win_reason_code: winReason.trim() || undefined,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['crm', 'opportunities'] });
      qc.invalidateQueries({ queryKey: ['crm', 'opp-history', opportunityId] });
      addToast({
        type: 'success',
        title: t('crm.opportunity_won', { defaultValue: 'Deal won' }),
      });
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  const loseMut = useMutation({
    mutationFn: () =>
      loseOpportunity(opportunityId, {
        lost_reason_code: loseReason.trim(),
        lost_at: todayIso(),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['crm', 'opportunities'] });
      qc.invalidateQueries({ queryKey: ['crm', 'opp-history', opportunityId] });
      addToast({
        type: 'success',
        title: t('crm.opportunity_lost', { defaultValue: 'Deal lost' }),
      });
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  const noteMut = useMutation({
    mutationFn: () =>
      createActivity({
        opportunity_id: opportunityId,
        account_id: opp?.account_id ?? null,
        kind: 'note',
        subject: noteText.trim().slice(0, 80),
        body: noteText.trim(),
      }),
    onSuccess: () => {
      setNoteText('');
      qc.invalidateQueries({
        queryKey: ['crm', 'activities', 'opp', opportunityId],
      });
      addToast({
        type: 'success',
        title: t('crm.note_added', { defaultValue: 'Note added' }),
      });
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  if (!opp) return null;

  const currentIdx = stages.findIndex((s) => s.id === opp.stage_id);

  return (
    <div className="fixed inset-0 z-50 flex justify-end" onClick={onClose}>
      <div className="absolute inset-0 bg-black/30" />
      <div
        role="dialog"
        aria-modal="true"
        aria-label={t('crm.opportunity_detail', {
          defaultValue: 'Deal: {{title}}',
          title: opp.title,
        })}
        className="relative h-full w-full max-w-2xl overflow-y-auto bg-surface-elevated shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="sticky top-0 z-10 flex items-center justify-between border-b border-border-light bg-surface-elevated px-5 py-3">
          <div className="min-w-0">
            <h2 className="truncate text-base font-semibold">{opp.title}</h2>
            <div className="mt-1 flex items-center gap-2">
              <Badge variant={OPP_STATUS_VARIANT[opp.status]} dot>
                {oppStatusLabel(opp.status, t)}
              </Badge>
              <span className="truncate text-xs text-content-tertiary">
                {accountsById[opp.account_id]?.name || ''}
              </span>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label={t('common.close', { defaultValue: 'Close' })}
            className="rounded p-1 hover:bg-surface-secondary"
          >
            <X size={16} />
          </button>
        </div>

        <div className="space-y-4 p-5">
          {/* KPIs */}
          <div className="grid grid-cols-3 gap-3">
            <KPI
              label={t('crm.value', { defaultValue: 'Value' })}
              value={
                <MoneyDisplay
                  amount={toNum(opp.estimated_value)}
                  currency={opp.currency || undefined}
                />
              }
            />
            <KPI
              label={t('crm.weighted', { defaultValue: 'Weighted' })}
              value={
                <MoneyDisplay
                  amount={toNum(opp.weighted_value)}
                  currency={opp.currency || undefined}
                />
              }
            />
            <KPI
              label={t('crm.probability', { defaultValue: 'Probability' })}
              value={`${opp.probability_percent}%`}
            />
          </div>

          {/* Pipeline stepper — one click moves stage */}
          <Card padding="sm">
            <div className="mb-2 flex items-center justify-between gap-2">
              <p className="text-xs font-semibold uppercase tracking-wide text-content-secondary">
                {t('crm.pipeline', { defaultValue: 'Pipeline' })}
              </p>
              <span
                className="inline-flex items-center gap-1 text-[11px] text-content-tertiary"
                title={t('crm.stepper_hint', {
                  defaultValue:
                    'Click a stage to move the deal. Won / lost stages are closed via the Win / Lose buttons below.',
                })}
              >
                <Info size={12} />
                {t('crm.stepper_hint_short', {
                  defaultValue: 'Use Win / Lose below to close',
                })}
              </span>
            </div>
            <div className="flex flex-wrap items-center gap-1">
              {stages.map((s, idx) => {
                const isCurrent = s.id === opp.stage_id;
                const isPast = currentIdx >= 0 && idx < currentIdx;
                const isClosing =
                  s.is_final && (s.is_won || s.is_lost);
                const bg = isCurrent
                  ? s.is_won
                    ? 'bg-emerald-500 text-white ring-emerald-500'
                    : s.is_lost
                      ? 'bg-rose-500 text-white ring-rose-500'
                      : 'bg-oe-blue text-white ring-oe-blue'
                  : isPast
                    ? 'bg-surface-secondary text-content-secondary ring-border-light'
                    : 'bg-transparent text-content-tertiary ring-border-light';
                return (
                  <div key={s.id} className="flex items-center gap-1">
                    <button
                      type="button"
                      disabled={
                        opp.status !== 'open' ||
                        isCurrent ||
                        isClosing ||
                        moveMut.isPending
                      }
                      onClick={() => moveMut.mutate(s.id)}
                      className={clsx(
                        'inline-flex items-center rounded-md px-2.5 py-1 text-xs font-medium ring-1 ring-inset transition-colors',
                        bg,
                        opp.status === 'open' && !isCurrent && !isClosing
                          ? 'hover:opacity-80 cursor-pointer'
                          : 'cursor-default',
                      )}
                    >
                      {s.name}
                    </button>
                    {idx < stages.length - 1 && (
                      <ArrowRight
                        size={12}
                        className="shrink-0 text-content-tertiary"
                      />
                    )}
                  </div>
                );
              })}
            </div>
          </Card>

          {/* Linked Contact (from Contacts module) + Project */}
          <Card padding="sm">
            <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-content-secondary">
              {t('crm.linked', { defaultValue: 'Linked records' })}
            </p>
            <div className="space-y-2">
              {/* Contact */}
              <div className="flex items-start gap-2.5 rounded-lg border border-border-light bg-surface-secondary/50 px-3 py-2">
                <User size={15} className="mt-0.5 text-content-tertiary" />
                <div className="min-w-0 flex-1">
                  <p className="text-[11px] uppercase tracking-wide text-content-tertiary">
                    {t('crm.contact', { defaultValue: 'Contact' })}
                  </p>
                  {opp.primary_contact_id ? (
                    contactQ.isLoading ? (
                      <p className="text-sm text-content-tertiary">…</p>
                    ) : contactQ.data ? (
                      <>
                        <p className="truncate text-sm font-medium text-content-primary">
                          {contactLabel(contactQ.data)}
                        </p>
                        <div className="mt-0.5 flex flex-wrap gap-3 text-xs text-content-secondary">
                          {contactQ.data.primary_email && (
                            <span className="inline-flex items-center gap-1">
                              <Mail size={11} />
                              {contactQ.data.primary_email}
                            </span>
                          )}
                          {contactQ.data.primary_phone && (
                            <span className="inline-flex items-center gap-1">
                              <Phone size={11} />
                              {contactQ.data.primary_phone}
                            </span>
                          )}
                        </div>
                        <Link
                          to="/contacts"
                          className="mt-1 inline-flex items-center gap-1 text-xs text-oe-blue hover:underline"
                        >
                          {t('crm.open_in_contacts', {
                            defaultValue: 'Open in Contacts',
                          })}
                          <ArrowRight size={11} />
                        </Link>
                      </>
                    ) : (
                      <p className="text-sm text-content-tertiary">
                        {t('crm.contact_unavailable', {
                          defaultValue: 'Linked contact not accessible',
                        })}
                      </p>
                    )
                  ) : (
                    <button
                      type="button"
                      onClick={() => setLinkOpen(true)}
                      className="text-sm text-oe-blue hover:underline"
                    >
                      {t('crm.attach_contact', {
                        defaultValue: '+ Attach a contact',
                      })}
                    </button>
                  )}
                </div>
              </div>

              {/* Project */}
              <div className="flex items-start gap-2.5 rounded-lg border border-border-light bg-surface-secondary/50 px-3 py-2">
                <FolderKanban
                  size={15}
                  className="mt-0.5 text-content-tertiary"
                />
                <div className="min-w-0 flex-1">
                  <p className="text-[11px] uppercase tracking-wide text-content-tertiary">
                    {t('crm.project', { defaultValue: 'Project' })}
                  </p>
                  {opp.project_id ? (
                    projectQ.isLoading ? (
                      <p className="text-sm text-content-tertiary">…</p>
                    ) : projectQ.data ? (
                      <Link
                        to={`/projects/${projectQ.data.id}`}
                        className="inline-flex items-center gap-1 text-sm font-medium text-oe-blue hover:underline"
                      >
                        {projectQ.data.name}
                        <ArrowRight size={11} />
                      </Link>
                    ) : (
                      <p className="text-sm text-content-tertiary">
                        {t('crm.project_unavailable', {
                          defaultValue: 'Linked project not accessible',
                        })}
                      </p>
                    )
                  ) : (
                    <button
                      type="button"
                      onClick={() => setLinkOpen(true)}
                      className="text-sm text-oe-blue hover:underline"
                    >
                      {t('crm.attach_project', {
                        defaultValue: '+ Link a project',
                      })}
                    </button>
                  )}
                </div>
              </div>
            </div>
            {(linkOpen ||
              (!opp.primary_contact_id && !opp.project_id)) && (
              <div className="mt-2">
                <LinkRecordsForm
                  opp={opp}
                  onLinked={() => {
                    setLinkOpen(false);
                    qc.invalidateQueries({
                      queryKey: ['crm', 'opportunities'],
                    });
                  }}
                />
              </div>
            )}
          </Card>

          {/* Close the deal */}
          {opp.status === 'open' && (
            <Card padding="sm">
              <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-content-secondary">
                {t('crm.close_deal', { defaultValue: 'Close the deal' })}
              </p>
              <div className="flex flex-wrap items-end gap-2">
                <div className="flex flex-1 flex-col gap-1 max-w-[12rem]">
                  <label className="text-[11px] uppercase tracking-wide text-content-tertiary">
                    {t('crm.win_reason_optional', {
                      defaultValue: 'Win reason (optional)',
                    })}
                  </label>
                  <select
                    value={winReason}
                    onChange={(e) => setWinReason(e.target.value)}
                    className={inputCls}
                  >
                    <option value="">
                      {t('crm.no_reason', { defaultValue: '- none -' })}
                    </option>
                    {winReasons.map((r: WinLossReason) => (
                      <option key={r.id} value={r.code}>
                        {r.label}
                      </option>
                    ))}
                  </select>
                </div>
                <Button
                  variant="primary"
                  icon={<Trophy size={14} />}
                  onClick={() => winMut.mutate()}
                  loading={winMut.isPending}
                >
                  {t('crm.win', { defaultValue: 'Win' })}
                </Button>
                <div className="flex flex-1 gap-1 max-w-md">
                  <select
                    value={loseReason}
                    onChange={(e) => setLoseReason(e.target.value)}
                    aria-label={t('crm.lose_reason', {
                      defaultValue: 'Loss reason code',
                    })}
                    className={inputCls}
                  >
                    <option value="">
                      {t('crm.lose_reason', { defaultValue: 'Loss reason code' })}
                    </option>
                    {lossReasons.map((r: WinLossReason) => (
                      <option key={r.id} value={r.code}>
                        {r.label}
                      </option>
                    ))}
                  </select>
                  <Button
                    variant="ghost"
                    icon={<Frown size={14} />}
                    onClick={() => loseMut.mutate()}
                    loading={loseMut.isPending}
                    disabled={!loseReason.trim()}
                  >
                    {t('crm.lose', { defaultValue: 'Lose' })}
                  </Button>
                </div>
              </div>
            </Card>
          )}

          {opp.status === 'won' && (
            <Card padding="sm">
              <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-content-secondary">
                {t('crm.next_step', { defaultValue: 'Next step' })}
              </p>
              <p className="mb-2 text-sm text-content-secondary">
                {t('crm.won_next_hint', {
                  defaultValue:
                    'Deal won. Take it forward by issuing bid packages, then formalising the award as a contract.',
                })}
              </p>
              <div className="flex flex-wrap gap-2">
                <Link to="/bid-management">
                  <Button variant="secondary" icon={<ArrowRight size={14} />}>
                    {t('crm.go_bid', { defaultValue: 'Bid Management' })}
                  </Button>
                </Link>
                <Link to="/contracts">
                  <Button variant="ghost" icon={<ArrowRight size={14} />}>
                    {t('crm.go_contracts', { defaultValue: 'Contracts' })}
                  </Button>
                </Link>
              </div>
            </Card>
          )}

          {(opp.description || opp.notes) && (
            <Card padding="sm">
              <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-content-secondary">
                {t('crm.description', { defaultValue: 'Description' })}
              </p>
              <p className="whitespace-pre-wrap text-sm">
                {opp.description || opp.notes}
              </p>
            </Card>
          )}

          {/* Quick activity / notes */}
          <Card padding="sm">
            <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-content-secondary">
              {t('crm.activities', { defaultValue: 'Activity' })}
              <span className="ml-2 normal-case text-content-tertiary">
                ({(activitiesQ.data ?? []).length})
              </span>
            </p>
            <div className="mb-3 flex gap-1.5">
              <input
                value={noteText}
                onChange={(e) => setNoteText(e.target.value)}
                onKeyDown={(e) => {
                  if (
                    e.key === 'Enter' &&
                    noteText.trim() &&
                    !noteMut.isPending
                  ) {
                    noteMut.mutate();
                  }
                }}
                placeholder={t('crm.add_note_ph', {
                  defaultValue: 'Log a quick note, then press Enter…',
                })}
                className={inputCls}
              />
              <Button
                variant="primary"
                icon={<Plus size={14} />}
                onClick={() => noteMut.mutate()}
                loading={noteMut.isPending}
                disabled={!noteText.trim()}
              >
                {t('crm.log', { defaultValue: 'Log' })}
              </Button>
            </div>
            {activitiesQ.isLoading ? (
              <SkeletonTable rows={3} columns={2} />
            ) : (activitiesQ.data ?? []).length === 0 ? (
              <p className="py-1 text-sm text-content-tertiary">
                {t('crm.no_activities', {
                  defaultValue: 'No activities logged yet.',
                })}
              </p>
            ) : (
              <ul className="space-y-2">
                {(activitiesQ.data ?? []).map((a) => (
                  <li
                    key={a.id}
                    className="flex gap-3 border-b border-border-light pb-2 last:border-0"
                  >
                    <span className="mt-0.5 w-16 shrink-0 text-[10px] font-semibold uppercase text-content-tertiary">
                      {a.kind}
                    </span>
                    <div className="flex-1">
                      <p className="text-sm font-medium">
                        {a.subject || '—'}
                      </p>
                      {a.body && a.body !== a.subject && (
                        <p className="mt-0.5 whitespace-pre-wrap text-xs text-content-secondary">
                          {a.body}
                        </p>
                      )}
                      <p className="mt-0.5 text-[10px] text-content-tertiary">
                        <DateDisplay value={a.created_at} />
                        {a.outcome && ` · ${a.outcome}`}
                      </p>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </Card>

          {/* Stage-history audit trail */}
          <Card padding="sm">
            <div className="mb-2 flex items-center gap-2">
              <History size={14} className="text-content-tertiary" />
              <p className="text-xs font-semibold uppercase tracking-wide text-content-secondary">
                {t('crm.stage_history', { defaultValue: 'Stage history' })}
              </p>
            </div>
            {historyQ.isLoading ? (
              <SkeletonTable rows={3} columns={2} />
            ) : (historyQ.data ?? []).length === 0 ? (
              <p className="py-1 text-sm text-content-tertiary">
                {t('crm.no_stage_history', {
                  defaultValue: 'No stage changes recorded yet.',
                })}
              </p>
            ) : (
              <ul className="space-y-2">
                {(historyQ.data ?? []).map((h: StageHistory) => {
                  const from = h.from_stage_id
                    ? stages.find((s) => s.id === h.from_stage_id)?.name
                    : null;
                  const to =
                    stages.find((s) => s.id === h.to_stage_id)?.name ||
                    h.to_stage_id;
                  return (
                    <li
                      key={h.id}
                      className="flex items-start gap-2 border-b border-border-light pb-2 text-sm last:border-0"
                    >
                      <ArrowRight
                        size={13}
                        className="mt-0.5 shrink-0 text-content-tertiary"
                      />
                      <div className="flex-1">
                        <p className="text-sm">
                          {from ? (
                            <span className="text-content-secondary">
                              {from}{' '}
                              <ArrowRight
                                size={11}
                                className="inline align-middle text-content-tertiary"
                              />{' '}
                            </span>
                          ) : (
                            <span className="text-content-tertiary">
                              {t('crm.created_in', { defaultValue: 'Created in' })}{' '}
                            </span>
                          )}
                          <span className="font-medium text-content-primary">
                            {to}
                          </span>
                        </p>
                        <p className="mt-0.5 flex items-center gap-2 text-[10px] text-content-tertiary">
                          {h.changed_at && <DateDisplay value={h.changed_at} />}
                          {h.duration_in_previous_seconds != null &&
                            h.duration_in_previous_seconds > 0 && (
                              <span className="inline-flex items-center gap-0.5">
                                <Clock size={10} />
                                {formatDwell(h.duration_in_previous_seconds, t)}
                              </span>
                            )}
                        </p>
                      </div>
                    </li>
                  );
                })}
              </ul>
            )}
          </Card>
        </div>
      </div>
    </div>
  );
}

type TFn = ReturnType<typeof useTranslation>['t'];

/** Human-readable dwell time spent in the previous stage. */
function formatDwell(seconds: number, t: TFn): string {
  const days = Math.floor(seconds / 86400);
  if (days >= 1) {
    return t('crm.dwell_days', { defaultValue: '{{count}}d in prev', count: days });
  }
  const hours = Math.floor(seconds / 3600);
  if (hours >= 1) {
    return t('crm.dwell_hours', { defaultValue: '{{count}}h in prev', count: hours });
  }
  const mins = Math.max(1, Math.floor(seconds / 60));
  return t('crm.dwell_mins', { defaultValue: '{{count}}m in prev', count: mins });
}

/* Inline contact + project linker — reuses Contacts & Projects, never
 * stores a copy: it only PATCHes primary_contact_id / project_id. */
function LinkRecordsForm({
  opp,
  onLinked,
}: {
  opp: Opportunity;
  onLinked: () => void;
}) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const [contactId, setContactId] = useState(opp.primary_contact_id ?? '');
  const [projectId, setProjectId] = useState(opp.project_id ?? '');

  const contactsQ = useQuery({
    queryKey: ['contacts', 'picker'],
    queryFn: () => fetchContacts({ limit: 500 }),
  });
  const projectsQ = useQuery({
    queryKey: ['projects', 'picker'],
    queryFn: () => projectsApi.list(),
  });

  const saveMut = useMutation({
    mutationFn: () =>
      updateOpportunity(opp.id, {
        primary_contact_id: contactId || null,
        project_id: projectId || null,
      }),
    onSuccess: () => {
      addToast({
        type: 'success',
        title: t('crm.link_saved', { defaultValue: 'Links updated' }),
      });
      onLinked();
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  return (
    <div className="space-y-2 rounded-lg border border-border-light bg-surface-secondary/40 p-3">
      <div>
        <p className="mb-1 text-[11px] uppercase tracking-wide text-content-tertiary">
          {t('crm.contact', { defaultValue: 'Contact' })}
        </p>
        <select
          value={contactId}
          onChange={(e) => setContactId(e.target.value)}
          className={inputCls}
        >
          <option value="">
            {t('crm.no_contact', { defaultValue: '- No contact -' })}
          </option>
          {(contactsQ.data?.items ?? []).map((c) => (
            <option key={c.id} value={c.id}>
              {contactLabel(c)}
            </option>
          ))}
        </select>
        {contactsQ.data && <TruncationNotice page={contactsQ.data} className="mt-1" />}
      </div>
      <div>
        <p className="mb-1 text-[11px] uppercase tracking-wide text-content-tertiary">
          {t('crm.project', { defaultValue: 'Project' })}
        </p>
        <select
          value={projectId}
          onChange={(e) => setProjectId(e.target.value)}
          className={inputCls}
        >
          <option value="">
            {t('crm.no_project', { defaultValue: '- No project -' })}
          </option>
          {(projectsQ.data ?? []).map((p) => (
            <option key={p.id} value={p.id}>
              {p.name}
            </option>
          ))}
        </select>
      </div>
      <Button
        variant="primary"
        icon={<CheckCircle2 size={14} />}
        onClick={() => saveMut.mutate()}
        loading={saveMut.isPending}
      >
        {t('crm.save_links', { defaultValue: 'Save links' })}
      </Button>
    </div>
  );
}

/* ═══════════════ Lead drawer ═══════════════ */

function LeadDrawer({
  leadId,
  leads,
  accountsById,
  accounts,
  stages,
  onConverted,
  onClose,
}: {
  leadId: string;
  leads: Lead[];
  accountsById: Record<string, Account>;
  accounts: Account[];
  stages: PipelineStage[];
  onConverted: (opportunityId: string) => void;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const lead = leads.find((l) => l.id === leadId);
  const [notes, setNotes] = useState(lead?.qualification_notes ?? '');
  const [showConvert, setShowConvert] = useState(false);
  // Deleting a lead is gated on MANAGER server-side (`crm.delete`), so the
  // control is hidden below that rather than offered and refused with a 403.
  const userRole = useAuthStore((s) => s.userRole);
  const canDelete = userRole === 'admin' || userRole === 'manager';
  const [confirmDelete, setConfirmDelete] = useState(false);
  // The server's structured 409, kept so the drawer can name what is holding
  // the lead instead of showing a bare error toast that disappears.
  const [deleteRefusal, setDeleteRefusal] = useState<RemovalRefusal | null>(null);
  const [convForm, setConvForm] = useState({
    title: '',
    account_id: '',
    stage_id: '',
    estimated_value: '0',
    currency: 'EUR',
    probability_percent: '20',
  });

  // Seed the convert form once the lead (and stages) are known: pre-fill the
  // deal title from the contact, the account from the lead, and the first
  // pipeline stage so the user can convert in one click.
  useEffect(() => {
    if (!lead) return;
    setConvForm((f) => ({
      ...f,
      title: f.title || `${lead.contact_name} - opportunity`,
      account_id: f.account_id || lead.account_id || accounts[0]?.id || '',
      stage_id: f.stage_id || stages[0]?.id || '',
    }));
  }, [lead, accounts, stages]);

  useEffect(() => {
    setNotes(lead?.qualification_notes ?? '');
  }, [lead?.id, lead?.qualification_notes]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onClose]);

  const qualifyMut = useMutation({
    mutationFn: () => qualifyLead(leadId, { qualification_notes: notes }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['crm', 'leads'] });
      addToast({
        type: 'success',
        title: t('crm.lead_qualified', { defaultValue: 'Lead qualified' }),
      });
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  const disqualifyMut = useMutation({
    mutationFn: () => disqualifyLead(leadId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['crm', 'leads'] });
      addToast({
        type: 'success',
        title: t('crm.lead_disqualified', {
          defaultValue: 'Lead disqualified',
        }),
      });
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  // Delete a lead outright. Reserved for the duplicate and the typo: the
  // backend refuses with a 409 naming the holders when the lead has been
  // converted to a deal or carries logged activities, because deleting either
  // erases the provenance of an open deal or takes the activity log with it.
  const deleteMut = useMutation({
    mutationFn: () => deleteLead(leadId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['crm', 'leads'] });
      addToast({
        type: 'success',
        title: t('crm.lead_deleted', { defaultValue: 'Lead deleted' }),
      });
      setConfirmDelete(false);
      onClose();
    },
    onError: (err) => {
      setConfirmDelete(false);
      const refusal = parseRemovalRefusal(err);
      if (refusal) {
        // Shown in the drawer, not as a toast: the reader needs to be able to
        // re-read what is holding the lead while deciding what to do.
        setDeleteRefusal(refusal);
        return;
      }
      setDeleteRefusal(null);
      addToast({ type: 'error', title: getErrorMessage(err) });
    },
  });

  // Convert a qualified lead into an opportunity — the central CRM workflow.
  // The backend rejects conversion unless the lead is `qualified`, so the
  // button only appears for that status (see render below).
  const convertMut = useMutation({
    mutationFn: () =>
      convertLead(leadId, {
        account_id: convForm.account_id,
        title: convForm.title.trim(),
        stage_id: convForm.stage_id,
        estimated_value: Number(convForm.estimated_value) || 0,
        currency: convForm.currency || 'EUR',
        probability_percent: Number(convForm.probability_percent) || 0,
      }),
    onSuccess: (opp) => {
      qc.invalidateQueries({ queryKey: ['crm', 'leads'] });
      qc.invalidateQueries({ queryKey: ['crm', 'opportunities'] });
      addToast({
        type: 'success',
        title: t('crm.lead_converted', {
          defaultValue: 'Lead converted to deal',
        }),
      });
      onConverted(opp.id);
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  if (!lead) return null;

  const convertDisabled =
    !convForm.title.trim() || !convForm.account_id || !convForm.stage_id;

  return (
    <div className="fixed inset-0 z-50 flex justify-end" onClick={onClose}>
      <div className="absolute inset-0 bg-black/30" />
      <div
        role="dialog"
        aria-modal="true"
        aria-label={t('crm.lead_detail', {
          defaultValue: 'Lead: {{name}}',
          name: lead.contact_name,
        })}
        className="relative h-full w-full max-w-lg overflow-y-auto bg-surface-elevated shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="sticky top-0 z-10 flex items-center justify-between border-b border-border-light bg-surface-elevated px-5 py-3">
          <div>
            <h2 className="text-base font-semibold">{lead.contact_name}</h2>
            <Badge variant={LEAD_STATUS_VARIANT[lead.status]} dot>
              {leadStatusLabel(lead.status, t)}
            </Badge>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label={t('common.close', { defaultValue: 'Close' })}
            className="rounded p-1 hover:bg-surface-secondary"
          >
            <X size={16} />
          </button>
        </div>

        <div className="space-y-4 p-5">
          <div className="grid grid-cols-2 gap-3 text-sm">
            <Field
              label={t('crm.email', { defaultValue: 'Email' })}
              value={lead.contact_email || '—'}
            />
            <Field
              label={t('crm.phone', { defaultValue: 'Phone' })}
              value={lead.contact_phone || '—'}
            />
            <Field
              label={t('crm.source', { defaultValue: 'Source' })}
              value={
                <span className="capitalize">
                  {lead.source.replace(/_/g, ' ')}
                </span>
              }
            />
            <Field
              label={t('crm.account', { defaultValue: 'Account' })}
              value={
                lead.account_id
                  ? accountsById[lead.account_id]?.name || lead.account_id
                  : '—'
              }
            />
          </div>

          {(lead.status === 'new' || lead.status === 'qualifying') && (
            <Card padding="sm">
              <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-content-secondary">
                {t('crm.qualify_lead', { defaultValue: 'Qualify lead' })}
              </p>
              <textarea
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                rows={4}
                placeholder={t('crm.qualification_notes', {
                  defaultValue:
                    'Notes - budget, authority, need, timeline, fit, …',
                })}
                className={clsx(inputCls, 'h-auto py-2')}
              />
              <div className="mt-2 flex gap-2">
                <Button
                  variant="primary"
                  icon={<CheckCircle2 size={14} />}
                  onClick={() => qualifyMut.mutate()}
                  loading={qualifyMut.isPending}
                >
                  {t('crm.qualify', { defaultValue: 'Qualify' })}
                </Button>
                <Button
                  variant="ghost"
                  icon={<XCircle size={14} />}
                  onClick={() => disqualifyMut.mutate()}
                  loading={disqualifyMut.isPending}
                >
                  {t('crm.disqualify', { defaultValue: 'Disqualify' })}
                </Button>
              </div>
            </Card>
          )}

          {lead.status === 'qualified' && (
            <Card padding="sm">
              <div className="mb-1 flex items-center gap-2">
                <ArrowRight size={14} className="text-oe-blue" />
                <p className="text-xs font-semibold uppercase tracking-wide text-content-secondary">
                  {t('crm.convert_to_deal', { defaultValue: 'Convert to deal' })}
                </p>
              </div>
              <p className="mb-2 text-xs text-content-tertiary">
                {t('crm.convert_hint', {
                  defaultValue:
                    'This lead is qualified. Convert it into an open deal on the pipeline - the lead is then marked converted and linked to the new deal.',
                })}
              </p>
              {!showConvert ? (
                <Button
                  variant="primary"
                  icon={<ArrowRight size={14} />}
                  onClick={() => setShowConvert(true)}
                >
                  {t('crm.convert_to_deal', { defaultValue: 'Convert to deal' })}
                </Button>
              ) : (
                <div className="space-y-2">
                  <div>
                    <p className="mb-1 text-[11px] uppercase tracking-wide text-content-tertiary">
                      {t('crm.title_col', { defaultValue: 'Title' })}
                    </p>
                    <input
                      value={convForm.title}
                      onChange={(e) =>
                        setConvForm({ ...convForm, title: e.target.value })
                      }
                      className={inputCls}
                    />
                  </div>
                  <div>
                    <p className="mb-1 text-[11px] uppercase tracking-wide text-content-tertiary">
                      {t('crm.account', { defaultValue: 'Account' })}
                    </p>
                    <select
                      value={convForm.account_id}
                      onChange={(e) =>
                        setConvForm({ ...convForm, account_id: e.target.value })
                      }
                      className={inputCls}
                    >
                      <option value="">
                        {t('crm.select_account', {
                          defaultValue: '- Select account -',
                        })}
                      </option>
                      {accounts.map((a) => (
                        <option key={a.id} value={a.id}>
                          {a.name}
                        </option>
                      ))}
                    </select>
                  </div>
                  <div className="grid grid-cols-2 gap-2">
                    <div>
                      <p className="mb-1 text-[11px] uppercase tracking-wide text-content-tertiary">
                        {t('crm.value', { defaultValue: 'Value' })}
                      </p>
                      <input
                        type="number"
                        value={convForm.estimated_value}
                        onChange={(e) =>
                          setConvForm({
                            ...convForm,
                            estimated_value: e.target.value,
                          })
                        }
                        className={inputCls}
                      />
                    </div>
                    <div>
                      <p className="mb-1 text-[11px] uppercase tracking-wide text-content-tertiary">
                        {t('crm.currency', { defaultValue: 'Currency' })}
                      </p>
                      <select
                        value={convForm.currency}
                        onChange={(e) =>
                          setConvForm({ ...convForm, currency: e.target.value })
                        }
                        className={inputCls}
                      >
                        {CURRENCY_CODES.map((c) => (
                          <option key={c} value={c}>
                            {c}
                          </option>
                        ))}
                      </select>
                    </div>
                  </div>
                  <div className="grid grid-cols-2 gap-2">
                    <div>
                      <p className="mb-1 text-[11px] uppercase tracking-wide text-content-tertiary">
                        {t('crm.stage', { defaultValue: 'Stage' })}
                      </p>
                      <select
                        value={convForm.stage_id}
                        onChange={(e) =>
                          setConvForm({ ...convForm, stage_id: e.target.value })
                        }
                        className={inputCls}
                      >
                        <option value="">—</option>
                        {stages
                          .filter((s) => !(s.is_final && (s.is_won || s.is_lost)))
                          .map((s) => (
                            <option key={s.id} value={s.id}>
                              {s.name}
                            </option>
                          ))}
                      </select>
                    </div>
                    <div>
                      <p className="mb-1 text-[11px] uppercase tracking-wide text-content-tertiary">
                        {t('crm.probability', { defaultValue: 'Probability %' })}
                      </p>
                      <input
                        type="number"
                        min={0}
                        max={100}
                        value={convForm.probability_percent}
                        onChange={(e) =>
                          setConvForm({
                            ...convForm,
                            probability_percent: e.target.value,
                          })
                        }
                        className={inputCls}
                      />
                    </div>
                  </div>
                  <div className="flex gap-2 pt-1">
                    <Button
                      variant="primary"
                      icon={<ArrowRight size={14} />}
                      onClick={() => convertMut.mutate()}
                      loading={convertMut.isPending}
                      disabled={convertDisabled}
                    >
                      {t('crm.convert', { defaultValue: 'Convert' })}
                    </Button>
                    <Button
                      variant="ghost"
                      onClick={() => setShowConvert(false)}
                      disabled={convertMut.isPending}
                    >
                      {t('common.cancel', { defaultValue: 'Cancel' })}
                    </Button>
                  </div>
                </div>
              )}
            </Card>
          )}

          {lead.qualification_notes && (
            <Card padding="sm">
              <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-content-secondary">
                {t('crm.notes', { defaultValue: 'Notes' })}
              </p>
              <p className="whitespace-pre-wrap text-sm">
                {lead.qualification_notes}
              </p>
            </Card>
          )}

          {/* Removing a lead. This is for the duplicate and the mistyped row,
              not for a lead somebody has worked: a converted lead is where an
              open deal came from, and logged activities cascade away with it.
              A lead already converted is not offered the control at all - the
              drawer can see that from `converted_opportunity_id` and there is
              no point offering a button whose only outcome is a refusal. */}
          {canDelete && (
            <Card padding="sm">
              <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-content-secondary">
                {t('crm.remove_lead_heading', { defaultValue: 'Remove lead' })}
              </p>
              {lead.converted_opportunity_id ? (
                <p className="text-xs text-content-tertiary">
                  {t('crm.remove_lead_converted_hint', {
                    defaultValue:
                      'This lead became a deal, so it stays on record. Deleting it would erase where that deal came from.',
                  })}
                </p>
              ) : (
                <>
                  <p className="mb-2 text-xs text-content-tertiary">
                    {t('crm.remove_lead_hint', {
                      defaultValue:
                        'For a duplicate or a mistyped row. A lead that has been converted or has logged activity stays on record.',
                    })}
                  </p>
                  <Button
                    variant="ghost"
                    icon={<Trash2 size={14} />}
                    onClick={() => {
                      setDeleteRefusal(null);
                      setConfirmDelete(true);
                    }}
                    disabled={deleteMut.isPending}
                    className="text-semantic-error hover:bg-semantic-error/10"
                  >
                    {t('crm.remove_lead_action', { defaultValue: 'Delete lead' })}
                  </Button>
                </>
              )}

              {/* The server's refusal, spelled out. Rendered from the
                  structured `holders` list so the counts read in the user's
                  own language rather than as the English sentence the server
                  built for callers that are not this app. */}
              {deleteRefusal && (
                <div
                  role="alert"
                  className="mt-3 rounded-lg border border-semantic-error/40 bg-semantic-error/5 px-3 py-2"
                >
                  <div className="flex items-start gap-2">
                    <AlertTriangle
                      size={14}
                      className="mt-0.5 shrink-0 text-semantic-error"
                    />
                    <div className="min-w-0 flex-1">
                      <p className="text-sm font-semibold text-content-primary">
                        {t('crm.remove_lead_blocked_title', {
                          defaultValue: 'This lead cannot be deleted',
                        })}
                      </p>
                      {deleteRefusal.holders.length > 0 && (
                        <>
                          <p className="mt-1 text-xs text-content-secondary">
                            {t('crm.remove_lead_blocked_intro', {
                              defaultValue: 'These records still refer to it:',
                            })}
                          </p>
                          <ul className="mt-1.5 space-y-1">
                            {deleteRefusal.holders.map((holder) => (
                              <li
                                key={holder.kind}
                                className="flex items-baseline justify-between gap-3 text-xs"
                              >
                                <span className="text-content-secondary">
                                  {holder.kind === 'opportunity'
                                    ? t('crm.holder_opportunity', {
                                        defaultValue: 'Deals',
                                      })
                                    : holder.kind === 'activity'
                                      ? t('crm.holder_activity', {
                                          defaultValue: 'Logged activities',
                                        })
                                      : holder.kind.replace(/_/g, ' ')}
                                </span>
                                <span className="font-semibold tabular-nums text-content-primary">
                                  {holder.count}
                                </span>
                              </li>
                            ))}
                          </ul>
                        </>
                      )}
                      <p className="mt-2 text-xs text-content-tertiary">
                        {deleteRefusal.code === 'lead_has_dependents'
                          ? t('crm.remove_lead_blocked_body', {
                              defaultValue:
                                'Disqualify the lead to take it out of the pipeline instead - that keeps the trail intact.',
                            })
                          : deleteRefusal.message}
                      </p>
                    </div>
                  </div>
                </div>
              )}
            </Card>
          )}
        </div>
      </div>

      {/* Confirm step - says what is about to go before it goes. */}
      <ConfirmDialog
        open={confirmDelete}
        onCancel={() => setConfirmDelete(false)}
        onConfirm={() => deleteMut.mutate()}
        loading={deleteMut.isPending}
        title={t('crm.remove_lead_confirm_title', { defaultValue: 'Delete this lead?' })}
        message={t('crm.remove_lead_confirm_message', {
          defaultValue:
            'The lead {{name}} and everything recorded on it are removed for good. This cannot be undone.',
          name: lead.contact_name,
        })}
        confirmLabel={t('crm.remove_lead_action', { defaultValue: 'Delete lead' })}
      />
    </div>
  );
}

function KPI({
  label,
  value,
}: {
  label: React.ReactNode;
  value: React.ReactNode;
}) {
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

function Field({
  label,
  value,
}: {
  label: React.ReactNode;
  value: React.ReactNode;
}) {
  return (
    <div>
      <p className="text-xs uppercase tracking-wide text-content-tertiary">
        {label}
      </p>
      <p className="mt-0.5 text-sm text-content-primary">{value}</p>
    </div>
  );
}

/* ═══════════════ Insights (analytics surfaced from the backend) ═══════════════ */

function InsightsCard({
  label,
  value,
  hint,
  icon,
}: {
  label: React.ReactNode;
  value: React.ReactNode;
  hint?: React.ReactNode;
  icon?: React.ReactNode;
}) {
  return (
    <div className="rounded-xl border border-border-light bg-surface-primary p-4">
      <div className="flex items-center gap-1.5 text-[11px] uppercase tracking-wide text-content-tertiary">
        {icon}
        {label}
      </div>
      <div className="mt-1 text-xl font-semibold text-content-primary">
        {value}
      </div>
      {hint && (
        <p className="mt-0.5 text-xs text-content-tertiary">{hint}</p>
      )}
    </div>
  );
}

function InsightsPanel({
  stagesById,
}: {
  stagesById: Record<string, PipelineStage>;
}) {
  const { t } = useTranslation();

  const dashQ = useQuery({
    queryKey: ['crm', 'dashboard'],
    queryFn: () => getCrmDashboard(),
  });
  const winLossQ = useQuery({
    queryKey: ['crm', 'win-loss'],
    queryFn: () => getWinLossAnalytics(),
  });

  if (dashQ.isLoading || winLossQ.isLoading) {
    return (
      <Card padding="md">
        <SkeletonTable rows={6} columns={4} />
      </Card>
    );
  }

  if (dashQ.error || winLossQ.error) {
    return (
      <Card padding="none">
        <EmptyState
          icon={<AlertTriangle size={22} />}
          title={t('crm.insights_failed', {
            defaultValue: 'Could not load insights',
          })}
          description={getErrorMessage(dashQ.error ?? winLossQ.error)}
        />
      </Card>
    );
  }

  const dash = dashQ.data;
  const wl = winLossQ.data;

  // Per-currency truth where the backend provides it; fall back to the
  // blended scalar (still labelled honestly) only when absent.
  const pipelineItems =
    dash?.by_currency?.map((c) => ({ amount: c.total, currency: c.currency })) ??
    [];
  const weightedItems =
    dash?.weighted_by_currency?.map((c) => ({
      amount: c.total,
      currency: c.currency,
    })) ?? [];

  const winRate = toNum(dash?.win_rate_30d);
  const stageRows = Object.entries(dash?.by_stage ?? {});

  const lostReasons = Object.entries(wl?.lost_reasons_breakdown ?? {}).sort(
    (a, b) => b[1] - a[1],
  );
  const lostTotal = lostReasons.reduce((sum, [, n]) => sum + n, 0);

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <InsightsCard
          icon={<FolderKanban size={12} />}
          label={t('crm.open_deals', { defaultValue: 'Open deals' })}
          value={dash?.open_opportunities ?? 0}
          hint={
            <span>
              {t('crm.pipeline_value', { defaultValue: 'Pipeline' })}:{' '}
              {pipelineItems.length > 0 ? (
                <MultiCurrencyTotal items={pipelineItems} variant="inline" compact />
              ) : (
                <MoneyDisplay amount={toNum(dash?.pipeline_value)} compact />
              )}
            </span>
          }
        />
        <InsightsCard
          icon={<BarChart3 size={12} />}
          label={t('crm.weighted_forecast', { defaultValue: 'Weighted forecast' })}
          value={
            weightedItems.length > 0 ? (
              <MultiCurrencyTotal
                items={weightedItems}
                variant="inline"
                compact
              />
            ) : (
              <MoneyDisplay amount={toNum(dash?.weighted_value)} compact />
            )
          }
          hint={t('crm.weighted_hint', {
            defaultValue: 'Value × probability across open deals',
          })}
        />
        <InsightsCard
          icon={<Trophy size={12} />}
          label={t('crm.win_rate_30d', { defaultValue: 'Win rate (30d)' })}
          value={`${Math.round(winRate)}%`}
          hint={
            <span>
              {t('crm.won_lost_counts', {
                defaultValue: '{{won}} won · {{lost}} lost',
                won: wl?.won_count ?? 0,
                lost: wl?.lost_count ?? 0,
              })}
            </span>
          }
        />
        <InsightsCard
          icon={<Clock size={12} />}
          label={t('crm.avg_sales_cycle', { defaultValue: 'Avg sales cycle' })}
          value={t('crm.n_days', {
            defaultValue: '{{count}} days',
            count: wl?.average_sales_cycle_days ?? 0,
          })}
          hint={t('crm.leads_open_n', {
            defaultValue: '{{count}} open leads',
            count: dash?.leads_open ?? 0,
          })}
        />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card padding="md">
          <p className="mb-3 text-xs font-semibold uppercase tracking-wide text-content-secondary">
            {t('crm.by_stage', { defaultValue: 'Open value by stage' })}
          </p>
          {stageRows.length === 0 ? (
            <p className="py-2 text-sm text-content-tertiary">
              {t('crm.no_open_deals', { defaultValue: 'No open deals yet.' })}
            </p>
          ) : (
            <ul className="space-y-2">
              {stageRows.map(([stageId, info]) => {
                const stage = stagesById[stageId];
                return (
                  <li
                    key={stageId}
                    className="flex items-center justify-between gap-3 border-b border-border-light pb-2 text-sm last:border-0"
                  >
                    <span className="flex items-center gap-2">
                      <span
                        className="inline-block h-2.5 w-2.5 rounded-full"
                        style={{
                          backgroundColor: stage ? stageAccent(stage) : '#94a3b8',
                        }}
                      />
                      <span className="font-medium text-content-primary">
                        {stage?.name || stageId}
                      </span>
                      <Badge variant="neutral">{info.count}</Badge>
                    </span>
                    <MoneyDisplay amount={toNum(info.total)} compact />
                  </li>
                );
              })}
            </ul>
          )}
        </Card>

        <Card padding="md">
          <p className="mb-3 text-xs font-semibold uppercase tracking-wide text-content-secondary">
            {t('crm.lost_reasons', { defaultValue: 'Why deals are lost' })}
          </p>
          {lostReasons.length === 0 ? (
            <p className="py-2 text-sm text-content-tertiary">
              {t('crm.no_lost_deals', {
                defaultValue: 'No lost deals recorded yet.',
              })}
            </p>
          ) : (
            <ul className="space-y-2">
              {lostReasons.map(([reason, count]) => {
                const pct = lostTotal > 0 ? (count / lostTotal) * 100 : 0;
                return (
                  <li key={reason} className="text-sm">
                    <div className="mb-0.5 flex items-center justify-between gap-3">
                      <span className="truncate capitalize text-content-primary">
                        {reason.replace(/_/g, ' ')}
                      </span>
                      <span className="shrink-0 text-content-tertiary">
                        {count}
                      </span>
                    </div>
                    <div className="h-1.5 w-full overflow-hidden rounded-full bg-surface-secondary">
                      <div
                        className="h-full rounded-full bg-rose-400"
                        style={{ width: `${pct}%` }}
                      />
                    </div>
                  </li>
                );
              })}
            </ul>
          )}
        </Card>
      </div>
    </div>
  );
}

/* ═══════════════ Create modal ═══════════════ */

function CreateModal({
  view,
  accounts,
  stages,
  onClose,
}: {
  view: View;
  accounts: Account[];
  stages: PipelineStage[];
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [busy, setBusy] = useState(false);

  // 'pipeline' and 'list' both create a deal.
  const kind: 'deal' | 'lead' | 'activity' =
    view === 'leads' ? 'lead' : view === 'activities' ? 'activity' : 'deal';

  const contactsQ = useQuery({
    queryKey: ['contacts', 'picker'],
    queryFn: () => fetchContacts({ limit: 500 }),
    enabled: kind === 'deal',
  });
  const projectsQ = useQuery({
    queryKey: ['projects', 'picker'],
    queryFn: () => projectsApi.list(),
    enabled: kind === 'deal',
  });

  const [leadForm, setLeadForm] = useState({
    contact_name: '',
    contact_email: '',
    contact_phone: '',
    account_id: '',
    source: 'inbound' as LeadSource,
  });

  const [dealForm, setDealForm] = useState({
    account_id: accounts[0]?.id || '',
    new_account_name: '',
    title: '',
    estimated_value: '0',
    currency: 'EUR',
    probability_percent: '20',
    stage_id: stages[0]?.id || '',
    expected_close_date: '',
    primary_contact_id: '',
    project_id: '',
  });

  const [actForm, setActForm] = useState({
    kind: 'note' as ActivityKind,
    subject: '',
    body: '',
    due_at: '',
    account_id: '',
  });

  const submit = async () => {
    setBusy(true);
    try {
      if (kind === 'deal') {
        if (!dealForm.title.trim()) throw new Error('Title required');
        if (!dealForm.stage_id) throw new Error('Stage required');
        let accountId = dealForm.account_id;
        // Minimal-click: if no account chosen but a name was typed,
        // spin up an account inline so the user never leaves the modal.
        if (!accountId && dealForm.new_account_name.trim()) {
          const acc = await createAccount({
            name: dealForm.new_account_name.trim(),
          });
          accountId = acc.id;
          qc.invalidateQueries({ queryKey: ['crm', 'accounts'] });
        }
        if (!accountId) throw new Error('Account required');
        await createOpportunity({
          account_id: accountId,
          title: dealForm.title.trim(),
          estimated_value: Number(dealForm.estimated_value) || 0,
          currency: dealForm.currency || 'EUR',
          probability_percent: Number(dealForm.probability_percent) || 0,
          stage_id: dealForm.stage_id,
          expected_close_date: dealForm.expected_close_date || null,
          primary_contact_id: dealForm.primary_contact_id || null,
          project_id: dealForm.project_id || null,
        });
        addToast({
          type: 'success',
          title: t('crm.deal_created', { defaultValue: 'Deal created' }),
        });
        qc.invalidateQueries({ queryKey: ['crm', 'opportunities'] });
      } else if (kind === 'lead') {
        if (!leadForm.contact_name.trim())
          throw new Error('Contact name required');
        await createLead({
          contact_name: leadForm.contact_name.trim(),
          contact_email: leadForm.contact_email || undefined,
          contact_phone: leadForm.contact_phone || undefined,
          account_id: leadForm.account_id || null,
          source: leadForm.source,
        });
        addToast({
          type: 'success',
          title: t('crm.lead_created', { defaultValue: 'Lead created' }),
        });
        qc.invalidateQueries({ queryKey: ['crm', 'leads'] });
      } else {
        await createActivity({
          kind: actForm.kind,
          subject: actForm.subject || undefined,
          body: actForm.body || undefined,
          due_at: actForm.due_at || null,
          account_id: actForm.account_id || null,
        });
        addToast({
          type: 'success',
          title: t('crm.activity_created', {
            defaultValue: 'Activity created',
          }),
        });
        qc.invalidateQueries({ queryKey: ['crm', 'activities'] });
      }
      onClose();
    } catch (err) {
      addToast({ type: 'error', title: getErrorMessage(err) });
    } finally {
      setBusy(false);
    }
  };

  const title =
    kind === 'deal'
      ? t('crm.new_deal', { defaultValue: 'New Deal' })
      : kind === 'lead'
        ? t('crm.new_lead', { defaultValue: 'New Lead' })
        : t('crm.new_activity', { defaultValue: 'New Activity' });

  return (
    <WideModal
      open
      onClose={onClose}
      title={title}
      size={kind === 'deal' ? 'xl' : 'lg'}
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
      {kind === 'deal' && (
        <>
          <WideModalSection
            title={t('crm.section_basic', { defaultValue: 'Deal' })}
            columns={2}
          >
            <WideModalField
              label={t('crm.title_col', { defaultValue: 'Title' })}
              required
              span={2}
            >
              <input
                value={dealForm.title}
                onChange={(e) =>
                  setDealForm({ ...dealForm, title: e.target.value })
                }
                className={inputCls}
              />
            </WideModalField>
            <WideModalField
              label={t('crm.account', { defaultValue: 'Account' })}
            >
              <select
                value={dealForm.account_id}
                onChange={(e) =>
                  setDealForm({ ...dealForm, account_id: e.target.value })
                }
                className={inputCls}
              >
                <option value="">
                  {t('crm.account_new', {
                    defaultValue: '- New account below -',
                  })}
                </option>
                {accounts.map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.name}
                  </option>
                ))}
              </select>
            </WideModalField>
            <WideModalField
              label={t('crm.account_name', {
                defaultValue: 'Or new account name',
              })}
            >
              <input
                value={dealForm.new_account_name}
                onChange={(e) =>
                  setDealForm({
                    ...dealForm,
                    new_account_name: e.target.value,
                  })
                }
                disabled={Boolean(dealForm.account_id)}
                className={inputCls}
              />
            </WideModalField>
          </WideModalSection>

          <WideModalSection
            title={t('crm.section_value', {
              defaultValue: 'Value & pipeline',
            })}
            columns={2}
          >
            <WideModalField label={t('crm.value', { defaultValue: 'Value' })}>
              <input
                type="number"
                value={dealForm.estimated_value}
                onChange={(e) =>
                  setDealForm({
                    ...dealForm,
                    estimated_value: e.target.value,
                  })
                }
                className={inputCls}
              />
            </WideModalField>
            <WideModalField
              label={t('crm.currency', { defaultValue: 'Currency' })}
            >
              <select
                value={dealForm.currency}
                onChange={(e) =>
                  setDealForm({ ...dealForm, currency: e.target.value })
                }
                className={inputCls}
              >
                {CURRENCY_CODES.map((c) => (
                  <option key={c} value={c}>
                    {c}
                  </option>
                ))}
              </select>
            </WideModalField>
            <WideModalField label={t('crm.stage', { defaultValue: 'Stage' })}>
              <select
                value={dealForm.stage_id}
                onChange={(e) =>
                  setDealForm({ ...dealForm, stage_id: e.target.value })
                }
                className={inputCls}
              >
                <option value="">—</option>
                {stages.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name}
                  </option>
                ))}
              </select>
            </WideModalField>
            <WideModalField
              label={t('crm.probability', { defaultValue: 'Probability %' })}
            >
              <input
                type="number"
                min={0}
                max={100}
                value={dealForm.probability_percent}
                onChange={(e) =>
                  setDealForm({
                    ...dealForm,
                    probability_percent: e.target.value,
                  })
                }
                className={inputCls}
              />
            </WideModalField>
            <WideModalField
              label={t('crm.expected_close', {
                defaultValue: 'Expected close',
              })}
              span={2}
            >
              <input
                type="date"
                value={dealForm.expected_close_date}
                onChange={(e) =>
                  setDealForm({
                    ...dealForm,
                    expected_close_date: e.target.value,
                  })
                }
                className={inputCls}
              />
            </WideModalField>
          </WideModalSection>

          <WideModalSection
            title={t('crm.section_links', {
              defaultValue: 'Link records (from Contacts & Projects)',
            })}
            columns={2}
          >
            <WideModalField
              label={t('crm.contact', { defaultValue: 'Contact' })}
            >
              <select
                value={dealForm.primary_contact_id}
                onChange={(e) =>
                  setDealForm({
                    ...dealForm,
                    primary_contact_id: e.target.value,
                  })
                }
                className={inputCls}
              >
                <option value="">
                  {t('crm.no_contact', { defaultValue: '- No contact -' })}
                </option>
                {(contactsQ.data?.items ?? []).map((c) => (
                  <option key={c.id} value={c.id}>
                    {contactLabel(c)}
                  </option>
                ))}
              </select>
              {contactsQ.data && <TruncationNotice page={contactsQ.data} className="mt-1" />}
            </WideModalField>
            <WideModalField
              label={t('crm.project', { defaultValue: 'Project' })}
            >
              <select
                value={dealForm.project_id}
                onChange={(e) =>
                  setDealForm({ ...dealForm, project_id: e.target.value })
                }
                className={inputCls}
              >
                <option value="">
                  {t('crm.no_project', { defaultValue: '- No project -' })}
                </option>
                {(projectsQ.data ?? []).map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              </select>
            </WideModalField>
          </WideModalSection>
        </>
      )}

      {kind === 'lead' && (
        <WideModalSection columns={2}>
          <WideModalField
            label={t('crm.contact_name', { defaultValue: 'Contact name' })}
            required
            span={2}
          >
            <input
              value={leadForm.contact_name}
              onChange={(e) =>
                setLeadForm({ ...leadForm, contact_name: e.target.value })
              }
              className={inputCls}
            />
          </WideModalField>
          <WideModalField label={t('crm.email', { defaultValue: 'Email' })}>
            <input
              type="email"
              value={leadForm.contact_email}
              onChange={(e) =>
                setLeadForm({ ...leadForm, contact_email: e.target.value })
              }
              className={inputCls}
            />
          </WideModalField>
          <WideModalField label={t('crm.phone', { defaultValue: 'Phone' })}>
            <input
              value={leadForm.contact_phone}
              onChange={(e) =>
                setLeadForm({ ...leadForm, contact_phone: e.target.value })
              }
              className={inputCls}
            />
          </WideModalField>
          <WideModalField
            label={t('crm.account', { defaultValue: 'Account' })}
          >
            <select
              value={leadForm.account_id}
              onChange={(e) =>
                setLeadForm({ ...leadForm, account_id: e.target.value })
              }
              className={inputCls}
            >
              <option value="">—</option>
              {accounts.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name}
                </option>
              ))}
            </select>
          </WideModalField>
          <WideModalField
            label={t('crm.source', { defaultValue: 'Source' })}
          >
            <select
              value={leadForm.source}
              onChange={(e) =>
                setLeadForm({
                  ...leadForm,
                  source: e.target.value as LeadSource,
                })
              }
              className={inputCls}
            >
              {LEAD_SOURCES.map((s) => (
                <option key={s} value={s}>
                  {s.replace(/_/g, ' ')}
                </option>
              ))}
            </select>
          </WideModalField>
        </WideModalSection>
      )}

      {kind === 'activity' && (
        <WideModalSection columns={2}>
          <WideModalField span={2}>
            <p className="flex items-start gap-1.5 text-xs text-content-tertiary">
              <Info size={13} className="mt-0.5 shrink-0" />
              {t('crm.activity_link_hint', {
                defaultValue:
                  'Link this activity to an account so it shows up on that account. To attach an activity to a specific deal, open the deal and log it from there.',
              })}
            </p>
          </WideModalField>
          <WideModalField label={t('crm.kind', { defaultValue: 'Kind' })}>
            <select
              value={actForm.kind}
              onChange={(e) =>
                setActForm({
                  ...actForm,
                  kind: e.target.value as ActivityKind,
                })
              }
              className={inputCls}
            >
              {ACTIVITY_KINDS.map((k) => (
                <option key={k} value={k}>
                  {k}
                </option>
              ))}
            </select>
          </WideModalField>
          <WideModalField label={t('crm.due', { defaultValue: 'Due' })}>
            <input
              type="date"
              value={actForm.due_at}
              onChange={(e) =>
                setActForm({ ...actForm, due_at: e.target.value })
              }
              className={inputCls}
            />
          </WideModalField>
          <WideModalField
            label={t('crm.link_account', {
              defaultValue: 'Link to account (optional)',
            })}
            span={2}
          >
            <select
              value={actForm.account_id}
              onChange={(e) =>
                setActForm({ ...actForm, account_id: e.target.value })
              }
              className={inputCls}
            >
              <option value="">
                {t('crm.no_account_link', {
                  defaultValue: '- Not linked -',
                })}
              </option>
              {accounts.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name}
                </option>
              ))}
            </select>
          </WideModalField>
          <WideModalField
            label={t('crm.subject', { defaultValue: 'Subject' })}
            span={2}
          >
            <input
              value={actForm.subject}
              onChange={(e) =>
                setActForm({ ...actForm, subject: e.target.value })
              }
              className={inputCls}
            />
          </WideModalField>
          <WideModalField
            label={t('crm.body', { defaultValue: 'Body' })}
            span={2}
          >
            <textarea
              value={actForm.body}
              onChange={(e) =>
                setActForm({ ...actForm, body: e.target.value })
              }
              rows={4}
              className={clsx(inputCls, 'h-auto py-2')}
            />
          </WideModalField>
        </WideModalSection>
      )}
    </WideModal>
  );
}
