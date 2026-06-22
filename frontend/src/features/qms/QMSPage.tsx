import { useState, useMemo, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import clsx from 'clsx';
import {
  ClipboardCheck,
  ListChecks,
  AlertOctagon,
  Award,
  CheckCircle2,
  Search,
  Plus,
  X,
  Loader2,
  TrendingUp,
  Send,
  ArrowUpRight,
  FileCheck,
  Lock,
  Unlock,
  ShieldAlert,
  Download,
} from 'lucide-react';
import {
  Button,
  Card,
  Badge,
  EmptyState,
  Breadcrumb,
  RecoveryCard,
  SkeletonTable,
  WideModal,
  WideModalSection,
  WideModalField,
  IntroRichText,
  ModuleGuideButton,
} from '@/shared/ui';
import { RequiresProject } from '@/shared/auth/RequiresProject';
import { PageHeader } from '@/shared/ui/PageHeader';
import { MoneyDisplay } from '@/shared/ui/MoneyDisplay';
import { DateDisplay } from '@/shared/ui/DateDisplay';
import { SectionIntro } from '@/features/validation';
import { apiGet, getAuthToken, getErrorMessage, triggerDownload } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import {
  listITPPlans,
  listInspections,
  listNCRs,
  listPunchItems,
  listAudits,
  createITPPlan,
  activateITPPlan,
  createInspection,
  completeInspection,
  createNCR,
  addNCRAction,
  listNCRActions,
  verifyNCRAction,
  escalateNCRToVariation,
  closeNCR,
  createPunchItem,
  closePunchItem,
  createAudit,
  completeAudit,
  fetchCOPQ,
  listITPItems,
  signInspection,
  listInspectionSignatures,
  checkHoldPointStatus,
  releaseHoldPoint,
  linkITPItemToSpec,
  planComplianceCsvUrl,
  type ITPPlan,
  type ITPItem,
  type Inspection,
  type InspectionSignature,
  type NCR,
  type NCRAction,
  type NCRSeverity,
  type PunchItem,
  type PunchCategory,
  type Audit,
} from './api';
import { HoldPointDependencyTree } from './HoldPointDependencyTree';
import { AttachmentEvidenceGallery } from './AttachmentEvidenceGallery';
import { qmsGuide } from './qmsGuide';
import { listVariationOrders } from '@/features/variations/api';

type Tab = 'itp' | 'inspections' | 'ncrs' | 'punch' | 'audits';

interface ProjectLite {
  id: string;
  name: string;
}

const ITP_STATUS_VARIANT: Record<string, 'neutral' | 'blue' | 'success' | 'warning' | 'error'> = {
  draft: 'neutral',
  active: 'success',
  superseded: 'warning',
  closed: 'neutral',
};

const INSPECTION_VARIANT: Record<string, 'neutral' | 'blue' | 'success' | 'warning' | 'error'> = {
  scheduled: 'blue',
  in_progress: 'warning',
  passed: 'success',
  failed: 'error',
  conditional: 'warning',
};

const NCR_STATUS_VARIANT: Record<string, 'neutral' | 'blue' | 'success' | 'warning' | 'error'> = {
  open: 'error',
  action_pending: 'warning',
  verifying: 'blue',
  closed: 'success',
  cancelled: 'neutral',
};

const SEVERITY_VARIANT: Record<NCRSeverity, 'neutral' | 'blue' | 'success' | 'warning' | 'error'> = {
  minor: 'neutral',
  major: 'warning',
  critical: 'error',
};

const NCR_ACTION_VARIANT: Record<string, 'neutral' | 'blue' | 'success' | 'warning' | 'error'> = {
  assigned: 'warning',
  in_progress: 'blue',
  done: 'success',
};

const NCR_ACTION_LABEL: Record<string, string> = {
  assigned: 'Assigned',
  in_progress: 'In progress',
  done: 'Done',
};

const PUNCH_STATUS_VARIANT: Record<string, 'neutral' | 'blue' | 'success' | 'warning' | 'error'> = {
  open: 'error',
  assigned: 'warning',
  in_progress: 'warning',
  ready_for_inspection: 'blue',
  closed: 'success',
  rejected: 'neutral',
};

const AUDIT_STATUS_VARIANT: Record<string, 'neutral' | 'blue' | 'success' | 'warning' | 'error'> = {
  planned: 'blue',
  in_progress: 'warning',
  completed: 'success',
  closed: 'neutral',
};

const inputCls =
  'h-9 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';

export function QMSPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [tab, setTab] = useState<Tab>('itp');
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [categoryFilter, setCategoryFilter] = useState<PunchCategory | ''>('');
  const [createOpen, setCreateOpen] = useState(false);
  const [selectedNcrId, setSelectedNcrId] = useState<string | null>(null);
  const [selectedInspectionId, setSelectedInspectionId] = useState<string | null>(null);
  const [selectedPlanId, setSelectedPlanId] = useState<string | null>(null);
  // When raising an NCR straight from a failed inspection (CONN-64) we seed the
  // create modal's linked_inspection_id so the quality chain stays connected.
  const [ncrPrefillInspectionId, setNcrPrefillInspectionId] = useState<string | null>(null);
  const activeProjectId = useProjectContextStore((s) => s.activeProjectId);

  const { data: projects = [] } = useQuery({
    queryKey: ['projects'],
    queryFn: () => apiGet<ProjectLite[]>('/v1/projects/'),
    staleTime: 5 * 60_000,
  });

  const projectId = activeProjectId || projects[0]?.id || '';
  // Genuinely-selected project (shared context) — used for the breadcrumb
  // so the trail never shows a first-project guess.
  const breadcrumbProjectName =
    projects.find((p) => p.id === activeProjectId)?.name || '';

  const itpQ = useQuery({
    queryKey: ['qms', 'itp', projectId, statusFilter],
    queryFn: () => listITPPlans({ project_id: projectId, status: statusFilter || undefined, limit: 200 }),
    enabled: !!projectId && tab === 'itp',
  });
  const inspQ = useQuery({
    queryKey: ['qms', 'inspections', projectId, statusFilter],
    queryFn: () => listInspections({ project_id: projectId, status: statusFilter || undefined, limit: 200 }),
    enabled: !!projectId && tab === 'inspections',
  });
  const ncrQ = useQuery({
    queryKey: ['qms', 'ncrs', projectId, statusFilter],
    queryFn: () => listNCRs({ project_id: projectId, status: statusFilter || undefined, limit: 200 }),
    enabled: !!projectId && (tab === 'ncrs' || tab === 'inspections'),
  });
  const punchQ = useQuery({
    queryKey: ['qms', 'punch', projectId, statusFilter],
    queryFn: () => listPunchItems({ project_id: projectId, status: statusFilter || undefined, limit: 200 }),
    enabled: !!projectId && tab === 'punch',
  });
  const auditQ = useQuery({
    queryKey: ['qms', 'audits', projectId, statusFilter],
    queryFn: () => listAudits({ project_id: projectId, status: statusFilter || undefined, limit: 200 }),
    enabled: !!projectId && tab === 'audits',
  });
  const copqQ = useQuery({
    queryKey: ['qms', 'copq', projectId],
    queryFn: () => fetchCOPQ(projectId, ''),
    enabled: !!projectId && tab === 'ncrs',
  });

  const filteredItp = useMemo(
    () => filterByText(itpQ.data ?? [], search, (r) => `${r.name} ${r.work_type} ${r.wbs_ref ?? ''}`),
    [itpQ.data, search],
  );
  const filteredInsp = useMemo(
    () => filterByText(inspQ.data ?? [], search, (r) => `${r.location_ref ?? ''} ${r.notes ?? ''}`),
    [inspQ.data, search],
  );
  const filteredNcrs = useMemo(
    () => filterByText(ncrQ.data ?? [], search, (r) => `${r.title} ${r.description}`),
    [ncrQ.data, search],
  );
  const filteredPunch = useMemo(() => {
    const base = punchQ.data ?? [];
    const list = categoryFilter ? base.filter((p) => p.category === categoryFilter) : base;
    return filterByText(list, search, (r) => `${r.title} ${r.description ?? ''} ${r.room_ref ?? ''}`);
  }, [punchQ.data, search, categoryFilter]);
  const filteredAudits = useMemo(
    () => filterByText(auditQ.data ?? [], search, (r) => `${r.audit_type} ${r.audit_scope ?? ''} ${r.standard_ref ?? ''}`),
    [auditQ.data, search],
  );

  const isLoading =
    (tab === 'itp' && itpQ.isLoading) ||
    (tab === 'inspections' && inspQ.isLoading) ||
    (tab === 'ncrs' && ncrQ.isLoading) ||
    (tab === 'punch' && punchQ.isLoading) ||
    (tab === 'audits' && auditQ.isLoading);

  const activeQuery =
    tab === 'itp'
      ? itpQ
      : tab === 'inspections'
        ? inspQ
        : tab === 'ncrs'
          ? ncrQ
          : tab === 'punch'
            ? punchQ
            : auditQ;
  const loadError = activeQuery.isError ? activeQuery.error : null;

  return (
    <div className="space-y-5 animate-fade-in">
      <Breadcrumb
        items={[
          ...(activeProjectId && breadcrumbProjectName
            ? [{ label: breadcrumbProjectName, to: `/projects/${activeProjectId}` }]
            : []),
          { label: t('nav.qms', { defaultValue: 'Quality Management' }) },
        ]}
      />

      <PageHeader
        srTitle={t('nav.qms', { defaultValue: 'Quality Management' })}
        subtitle={t('qms.subtitle', {
          defaultValue: 'ITP plans, inspections, NCRs, punch list and audits in one place.',
        })}
        actions={
          <>
            <ModuleGuideButton content={qmsGuide} />
            <Button variant="primary" size="sm" icon={<Plus size={14} />} onClick={() => setCreateOpen(true)} disabled={!projectId}>
              {tabCreateLabel(tab, t)}
            </Button>
          </>
        }
      />

      <SectionIntro
        storageKey="qms"
        title={t('qms.intro_title', {
          defaultValue: 'One quality chain, not five silos',
        })}
        more={
          <IntroRichText
            text={t('qms.intro_more', {
              defaultValue:
                'On most jobs the quality records live in five different places: the ITP is a spreadsheet, inspections are on paper, NCRs are emailed around, the punch list is a separate app and the audit file sits with the QA manager. When the client asks for proof that a hold point was released before the pour, nobody can reconstruct the chain. This page keeps all five in one register so every check links back to the plan it came from and forward to the defect it raised.\n\n**You put in:**\n- Inspection and Test Plans (ITP) with their hold, witness and review points for each work package\n- Inspections booked against those control points, with pass, fail or conditional sign-offs\n- Non-conformance reports for work that fails, with a severity and any cost impact\n- Punch items for snags found on walkthroughs, and internal, external or supplier audits\n\n**You get out:**\n- A live status for every ITP plan and a hold-point dependency tree showing what is cleared to proceed\n- NCRs routed through corrective actions to close-out, with escalation to a Variation when there is a cost\n- A Cost of Poor Quality rollup that adds NCR cost, rework estimate and open punch count into one figure\n- An audit-ready compliance dossier you can export to CSV per ITP plan\n\n**How it works day to day:**\n1. Build the ITP for a work package and activate it so its hold and witness points become live gates.\n2. Schedule an inspection against a control point and record the result when the work is checked.\n3. If it fails, raise an NCR, assign corrective actions and verify them before you close it.\n4. Where the defect carries a cost, escalate the NCR to a Variation so the money trail stays attached.\n5. Track snags on the Punch List and run periodic Audits over the management system itself.\n\nThe tabs mirror the standalone modules, so the same records appear in Inspections, NCRs and the Punch List. Cost escalations land in Variations, and the COPQ figure feeds back into project cost reporting. Work the tabs left to right and the whole ISO 9001 chain stays connected.',
            })}
          />
        }
        links={[
          { label: t('inspections.title', { defaultValue: 'Inspections' }), onClick: () => navigate('/inspections') },
          { label: t('ncr.title', { defaultValue: 'NCRs' }), onClick: () => navigate('/ncr') },
          { label: t('nav.punchlist', { defaultValue: 'Punch List' }), onClick: () => navigate('/punchlist') },
        ]}
      >
        {t('qms.intro_body', {
          defaultValue:
            'Run the full ISO 9001 quality chain in one place: ITP plans define hold and witness points, Inspections sign them off, failed checks raise NCRs, NCRs with cost impact escalate to a Variation and feed the Cost of Poor Quality rollup, Punch items track close-out and Audits cover the management system. Pick a project, then work the tabs left to right.',
        })}
      </SectionIntro>

      <div className="border-b border-border-light">
        <nav className="flex gap-1 -mb-px overflow-x-auto">
          {tabsDef(t).map((it) => {
            const Icon = it.icon;
            return (
              <button
                key={it.id}
                type="button"
                onClick={() => {
                  setTab(it.id);
                  setStatusFilter('');
                  setSearch('');
                  setCategoryFilter('');
                }}
                className={clsx(
                  'flex items-center gap-2 px-4 py-2.5 text-sm font-medium border-b-2 transition-colors whitespace-nowrap',
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

      {tab === 'ncrs' && copqQ.data && (
        <Card padding="md">
          <div className="flex items-center justify-between flex-wrap gap-3">
            <div className="flex items-center gap-3">
              <span className="flex h-9 w-9 items-center justify-center rounded-full bg-semantic-error-bg text-semantic-error">
                <TrendingUp size={16} />
              </span>
              <div>
                <p className="text-xs uppercase tracking-wide text-content-tertiary">
                  {t('qms.copq', { defaultValue: 'Cost of Poor Quality' })}
                </p>
                <p className="text-lg font-semibold text-content-primary">
                  <MoneyDisplay
                    amount={Number(copqQ.data.copq_total) || 0}
                    currency={copqQ.data.currency || undefined}
                  />
                </p>
              </div>
            </div>
            <div className="grid grid-cols-3 gap-4 text-xs">
              <KvBlock
                label={t('qms.ncr_cost_total', { defaultValue: 'NCR cost' })}
                value={<MoneyDisplay amount={Number(copqQ.data.ncr_cost_total) || 0} currency={copqQ.data.currency || undefined} />}
              />
              <KvBlock
                label={t('qms.rework_cost', { defaultValue: 'Rework est.' })}
                value={<MoneyDisplay amount={Number(copqQ.data.rework_cost_estimate) || 0} currency={copqQ.data.currency || undefined} />}
              />
              <KvBlock
                label={t('qms.open_punch', { defaultValue: 'Open punch' })}
                value={copqQ.data.open_punch_count}
              />
            </div>
          </div>
        </Card>
      )}

      <div className="flex flex-wrap items-center gap-2">
        <div className="relative flex-1 min-w-[200px] max-w-md">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-content-tertiary" />
          <input
            type="text"
            placeholder={t('common.search', { defaultValue: 'Search…' })}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className={clsx(inputCls, 'pl-8')}
          />
        </div>
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          className={clsx(inputCls, 'max-w-[180px]')}
        >
          <option value="">{t('common.all_statuses', { defaultValue: 'All statuses' })}</option>
          {statusOptionsFor(tab).map((s) => (
            <option key={s} value={s}>
              {statusLabel(t, s)}
            </option>
          ))}
        </select>
        {tab === 'punch' && (
          <select
            value={categoryFilter}
            onChange={(e) => setCategoryFilter(e.target.value as PunchCategory | '')}
            className={clsx(inputCls, 'max-w-[180px]')}
          >
            <option value="">{t('qms.all_categories', { defaultValue: 'All categories' })}</option>
            {(['architectural', 'mechanical', 'electrical', 'finishes', 'structure'] as PunchCategory[]).map((c) => (
              <option key={c} value={c}>
                {categoryLabel(t, c)}
              </option>
            ))}
          </select>
        )}
      </div>

      <Card padding="none">
        {!projectId ? (
          <RequiresProject
            emptyHint={t('common.no_project_desc', { defaultValue: 'Create or select a project to view QMS data.' })}
          >{null}</RequiresProject>
        ) : isLoading ? (
          <div className="p-4">
            <SkeletonTable rows={8} columns={5} />
          </div>
        ) : loadError ? (
          <RecoveryCard error={loadError} onRetry={() => activeQuery.refetch()} />
        ) : tab === 'itp' ? (
          <ITPTable
            rows={filteredItp}
            onAction={() => setCreateOpen(true)}
            onSelect={(id) => setSelectedPlanId(id)}
          />
        ) : tab === 'inspections' ? (
          <InspectionTable
            rows={filteredInsp}
            onSelect={(id) => setSelectedInspectionId(id)}
            onAction={() => setCreateOpen(true)}
          />
        ) : tab === 'ncrs' ? (
          <NCRTable rows={filteredNcrs} onSelect={(id) => setSelectedNcrId(id)} onAction={() => setCreateOpen(true)} />
        ) : tab === 'punch' ? (
          <PunchTable rows={filteredPunch} onAction={() => setCreateOpen(true)} />
        ) : (
          <AuditTable rows={filteredAudits} onAction={() => setCreateOpen(true)} />
        )}
      </Card>

      {createOpen && (
        <CreateModal
          kind={tab}
          projectId={projectId}
          itpPlans={itpQ.data ?? []}
          inspections={inspQ.data ?? []}
          prefillInspectionId={ncrPrefillInspectionId}
          onClose={() => {
            setCreateOpen(false);
            setNcrPrefillInspectionId(null);
          }}
        />
      )}

      {selectedNcrId && (
        <NCRDrawer
          id={selectedNcrId}
          ncrs={ncrQ.data ?? []}
          onClose={() => setSelectedNcrId(null)}
        />
      )}

      {selectedInspectionId && (
        <InspectionDrawer
          id={selectedInspectionId}
          inspections={inspQ.data ?? []}
          onClose={() => setSelectedInspectionId(null)}
          onRaiseNcr={(inspectionId) => {
            setSelectedInspectionId(null);
            setNcrPrefillInspectionId(inspectionId);
            setTab('ncrs');
            setStatusFilter('');
            setSearch('');
            setCategoryFilter('');
            setCreateOpen(true);
          }}
        />
      )}

      {selectedPlanId && (
        <ITPPlanDrawer
          planId={selectedPlanId}
          plan={(itpQ.data ?? []).find((p) => p.id === selectedPlanId) ?? null}
          projectId={projectId}
          onClose={() => setSelectedPlanId(null)}
        />
      )}
    </div>
  );
}

function tabsDef(t: (k: string, opts?: Record<string, unknown>) => string) {
  return [
    { id: 'itp' as const, label: t('qms.tab_itp', { defaultValue: 'ITP Plans' }), icon: FileCheck },
    { id: 'inspections' as const, label: t('qms.tab_inspections', { defaultValue: 'Inspections' }), icon: ClipboardCheck },
    { id: 'ncrs' as const, label: t('qms.tab_ncrs', { defaultValue: 'NCRs' }), icon: AlertOctagon },
    { id: 'punch' as const, label: t('qms.tab_punch', { defaultValue: 'Punch List' }), icon: ListChecks },
    { id: 'audits' as const, label: t('qms.tab_audits', { defaultValue: 'Audits' }), icon: Award },
  ];
}

function tabCreateLabel(tab: Tab, t: (k: string, opts?: Record<string, unknown>) => string): string {
  switch (tab) {
    case 'itp':
      return t('qms.new_itp', { defaultValue: 'New ITP Plan' });
    case 'inspections':
      return t('qms.new_inspection', { defaultValue: 'Schedule Inspection' });
    case 'ncrs':
      return t('qms.new_ncr', { defaultValue: 'Raise NCR' });
    case 'punch':
      return t('qms.new_punch', { defaultValue: 'Add Punch Item' });
    case 'audits':
      return t('qms.new_audit', { defaultValue: 'Plan Audit' });
  }
}

function statusOptionsFor(tab: Tab): string[] {
  switch (tab) {
    case 'itp':
      return ['draft', 'active', 'superseded', 'closed'];
    case 'inspections':
      return ['scheduled', 'in_progress', 'passed', 'failed', 'conditional'];
    case 'ncrs':
      return ['open', 'action_pending', 'verifying', 'closed', 'cancelled'];
    case 'punch':
      return ['open', 'assigned', 'in_progress', 'ready_for_inspection', 'closed', 'rejected'];
    case 'audits':
      return ['planned', 'in_progress', 'completed', 'closed'];
  }
}

type Translate = ReturnType<typeof useTranslation>['t'];

// Human-readable English fallbacks for every QMS enum token. The actual
// translations are resolved through t('qms.status.<token>', …) so the
// i18n-sweep can localise them; these maps only provide the en defaultValue
// so we never render a raw snake_case identifier to the user.
const STATUS_LABEL_FALLBACK: Record<string, string> = {
  draft: 'Draft',
  active: 'Active',
  superseded: 'Superseded',
  closed: 'Closed',
  scheduled: 'Scheduled',
  in_progress: 'In progress',
  passed: 'Passed',
  failed: 'Failed',
  conditional: 'Conditional',
  open: 'Open',
  action_pending: 'Action pending',
  verifying: 'Verifying',
  cancelled: 'Cancelled',
  assigned: 'Assigned',
  ready_for_inspection: 'Ready for inspection',
  rejected: 'Rejected',
  planned: 'Planned',
  completed: 'Completed',
};

const SEVERITY_LABEL_FALLBACK: Record<string, string> = {
  minor: 'Minor',
  major: 'Major',
  critical: 'Critical',
  observation: 'Observation',
};

const CATEGORY_LABEL_FALLBACK: Record<string, string> = {
  architectural: 'Architectural',
  mechanical: 'Mechanical',
  electrical: 'Electrical',
  finishes: 'Finishes',
  structure: 'Structure',
};

/** Translate a QMS status token, falling back to a humanised English label. */
function statusLabel(t: Translate, status: string): string {
  return t(`qms.status.${status}`, {
    defaultValue: STATUS_LABEL_FALLBACK[status] ?? status,
  });
}

/** Translate a QMS severity token, falling back to a humanised English label. */
function severityLabel(t: Translate, severity: string): string {
  return t(`qms.severity_level.${severity}`, {
    defaultValue: SEVERITY_LABEL_FALLBACK[severity] ?? severity,
  });
}

/** Translate a punch-category token, falling back to a humanised English label. */
function categoryLabel(t: Translate, category: string): string {
  return t(`qms.category_label.${category}`, {
    defaultValue: CATEGORY_LABEL_FALLBACK[category] ?? category,
  });
}

const AUDIT_TYPE_LABEL_FALLBACK: Record<string, string> = {
  internal: 'Internal',
  external: 'External',
  supplier: 'Supplier',
};

/** Translate an audit-type token, falling back to a humanised English label. */
function auditTypeLabel(t: Translate, auditType: string): string {
  return t(`qms.audit_type_label.${auditType}`, {
    defaultValue: AUDIT_TYPE_LABEL_FALLBACK[auditType] ?? auditType,
  });
}

function filterByText<T>(rows: T[], search: string, getter: (r: T) => string): T[] {
  if (!search.trim()) return rows;
  const q = search.toLowerCase();
  return rows.filter((r) => getter(r).toLowerCase().includes(q));
}

function KvBlock({ label, value }: { label: React.ReactNode; value: React.ReactNode }) {
  return (
    <div>
      <p className="text-xs uppercase tracking-wide text-content-tertiary">{label}</p>
      <p className="mt-0.5 text-sm font-semibold text-content-primary">{value}</p>
    </div>
  );
}

/* ── Tables ────────────────────────────────────────────────────────────── */

function ITPTable({
  rows,
  onAction,
  onSelect,
}: {
  rows: ITPPlan[];
  onAction: () => void;
  onSelect: (id: string) => void;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const activate = useMutation({
    mutationFn: (id: string) => activateITPPlan(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['qms', 'itp'] });
      addToast({ type: 'success', title: t('qms.itp_activated', { defaultValue: 'ITP plan activated' }) });
    },
    onError: (e) => addToast({ type: 'error', title: getErrorMessage(e) }),
  });
  if (rows.length === 0) {
    return (
      <EmptyState
        icon={<FileCheck size={22} />}
        title={t('qms.empty_itp', { defaultValue: 'No ITP plans yet' })}
        description={t('qms.empty_itp_desc', {
          defaultValue: 'Inspection & Test Plans define quality gates for each work package.',
        })}
        action={{ label: t('qms.new_itp', { defaultValue: 'New ITP Plan' }), onClick: onAction }}
      />
    );
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead className="bg-surface-secondary text-content-tertiary text-xs uppercase tracking-wide">
          <tr>
            <th className="px-4 py-2.5 text-left">{t('qms.name', { defaultValue: 'Name' })}</th>
            <th className="px-4 py-2.5 text-left">{t('qms.work_type', { defaultValue: 'Work type' })}</th>
            <th className="px-4 py-2.5 text-left">{t('qms.wbs', { defaultValue: 'WBS' })}</th>
            <th className="px-4 py-2.5 text-left">{t('qms.version', { defaultValue: 'Ver' })}</th>
            <th className="px-4 py-2.5 text-left">{t('qms.status', { defaultValue: 'Status' })}</th>
            <th className="px-4 py-2.5 text-right">{t('qms.actions', { defaultValue: 'Actions' })}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr
              key={r.id}
              onClick={() => onSelect(r.id)}
              className="border-t border-border-light hover:bg-surface-secondary cursor-pointer"
            >
              <td className="px-4 py-2 font-medium text-content-primary">{r.name}</td>
              <td className="px-4 py-2 text-content-secondary">{r.work_type}</td>
              <td className="px-4 py-2 text-content-secondary text-xs">{r.wbs_ref || '—'}</td>
              <td className="px-4 py-2 text-content-secondary text-xs tabular-nums">v{r.version}</td>
              <td className="px-4 py-2">
                <Badge variant={ITP_STATUS_VARIANT[r.status] || 'neutral'} dot>
                  {statusLabel(t, r.status)}
                </Badge>
              </td>
              <td className="px-4 py-2 text-right">
                {r.status === 'draft' && (
                  <Button
                    variant="ghost"
                    size="sm"
                    loading={activate.isPending && activate.variables === r.id}
                    onClick={(e) => {
                      e.stopPropagation();
                      activate.mutate(r.id);
                    }}
                  >
                    {t('qms.activate', { defaultValue: 'Activate' })}
                  </Button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function InspectionTable({
  rows,
  onSelect,
  onAction,
}: {
  rows: Inspection[];
  onSelect: (id: string) => void;
  onAction: () => void;
}) {
  const { t } = useTranslation();
  if (rows.length === 0) {
    return (
      <EmptyState
        icon={<ClipboardCheck size={22} />}
        title={t('qms.empty_inspections', { defaultValue: 'No inspections scheduled' })}
        description={t('qms.empty_inspections_desc', {
          defaultValue: 'Schedule an inspection against an ITP control point to record hold/witness sign-offs.',
        })}
        action={{ label: t('qms.new_inspection', { defaultValue: 'Schedule Inspection' }), onClick: onAction }}
      />
    );
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead className="bg-surface-secondary text-content-tertiary text-xs uppercase tracking-wide">
          <tr>
            <th className="px-4 py-2.5 text-left">{t('qms.location', { defaultValue: 'Location' })}</th>
            <th className="px-4 py-2.5 text-left">{t('qms.scheduled_at', { defaultValue: 'Scheduled' })}</th>
            <th className="px-4 py-2.5 text-left">{t('qms.performed_at', { defaultValue: 'Performed' })}</th>
            <th className="px-4 py-2.5 text-left">{t('qms.status', { defaultValue: 'Status' })}</th>
            <th className="px-4 py-2.5 text-left">{t('qms.notes', { defaultValue: 'Notes' })}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr
              key={r.id}
              onClick={() => onSelect(r.id)}
              className="border-t border-border-light hover:bg-surface-secondary cursor-pointer"
            >
              <td className="px-4 py-2 font-medium text-content-primary">{r.location_ref || '—'}</td>
              <td className="px-4 py-2 text-xs text-content-secondary">
                {r.scheduled_at ? <DateDisplay value={r.scheduled_at} /> : '—'}
              </td>
              <td className="px-4 py-2 text-xs text-content-secondary">
                {r.performed_at ? <DateDisplay value={r.performed_at} /> : '—'}
              </td>
              <td className="px-4 py-2">
                <Badge variant={INSPECTION_VARIANT[r.status] || 'neutral'} dot>
                  {statusLabel(t, r.status)}
                </Badge>
              </td>
              <td className="px-4 py-2 text-content-secondary text-xs truncate max-w-[320px]">{r.notes || '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function NCRTable({
  rows,
  onSelect,
  onAction,
}: {
  rows: NCR[];
  onSelect: (id: string) => void;
  onAction: () => void;
}) {
  const { t } = useTranslation();
  if (rows.length === 0) {
    return (
      <EmptyState
        icon={<AlertOctagon size={22} />}
        title={t('qms.empty_ncrs', { defaultValue: 'No non-conformance reports' })}
        description={t('qms.empty_ncrs_desc', {
          defaultValue: 'NCRs capture defects with cost impact and feed the COPQ rollup.',
        })}
        action={{ label: t('qms.new_ncr', { defaultValue: 'Raise NCR' }), onClick: onAction }}
      />
    );
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead className="bg-surface-secondary text-content-tertiary text-xs uppercase tracking-wide">
          <tr>
            <th className="px-4 py-2.5 text-left">{t('qms.title_col', { defaultValue: 'Title' })}</th>
            <th className="px-4 py-2.5 text-left">{t('qms.severity', { defaultValue: 'Severity' })}</th>
            <th className="px-4 py-2.5 text-left">{t('qms.status', { defaultValue: 'Status' })}</th>
            <th className="px-4 py-2.5 text-left">{t('qms.raised_at', { defaultValue: 'Raised' })}</th>
            <th className="px-4 py-2.5 text-right">{t('qms.cost_impact', { defaultValue: 'Cost impact' })}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr
              key={r.id}
              onClick={() => onSelect(r.id)}
              className="border-t border-border-light hover:bg-surface-secondary cursor-pointer"
            >
              <td className="px-4 py-2 font-medium text-content-primary truncate max-w-[360px]">{r.title}</td>
              <td className="px-4 py-2">
                <Badge variant={SEVERITY_VARIANT[r.severity]}>{severityLabel(t, r.severity)}</Badge>
              </td>
              <td className="px-4 py-2">
                <Badge variant={NCR_STATUS_VARIANT[r.status] || 'neutral'} dot>
                  {statusLabel(t, r.status)}
                </Badge>
              </td>
              <td className="px-4 py-2 text-xs text-content-secondary">
                {r.raised_at ? <DateDisplay value={r.raised_at} /> : '—'}
              </td>
              <td className="px-4 py-2 text-right">
                {r.cost_impact_amount != null ? (
                  <MoneyDisplay
                    amount={Number(r.cost_impact_amount)}
                    currency={r.cost_impact_currency || undefined}
                  />
                ) : (
                  <span className="text-content-tertiary">—</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function PunchTable({ rows, onAction }: { rows: PunchItem[]; onAction: () => void }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const closeMut = useMutation({
    mutationFn: (id: string) => closePunchItem(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['qms', 'punch'] });
      addToast({ type: 'success', title: t('qms.punch_closed', { defaultValue: 'Punch item closed' }) });
    },
    onError: (e) => addToast({ type: 'error', title: getErrorMessage(e) }),
  });
  if (rows.length === 0) {
    return (
      <EmptyState
        icon={<ListChecks size={22} />}
        title={t('qms.empty_punch', { defaultValue: 'No punch items' })}
        description={t('qms.empty_punch_desc', {
          defaultValue: 'Snag items captured on walkthroughs land here for assignment and close-out.',
        })}
        action={{ label: t('qms.new_punch', { defaultValue: 'Add Punch Item' }), onClick: onAction }}
      />
    );
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead className="bg-surface-secondary text-content-tertiary text-xs uppercase tracking-wide">
          <tr>
            <th className="px-4 py-2.5 text-left">{t('qms.title_col', { defaultValue: 'Title' })}</th>
            <th className="px-4 py-2.5 text-left">{t('qms.category', { defaultValue: 'Category' })}</th>
            <th className="px-4 py-2.5 text-left">{t('qms.severity', { defaultValue: 'Severity' })}</th>
            <th className="px-4 py-2.5 text-left">{t('qms.status', { defaultValue: 'Status' })}</th>
            <th className="px-4 py-2.5 text-left">{t('qms.due_date', { defaultValue: 'Due' })}</th>
            <th className="px-4 py-2.5 text-right">{t('qms.actions', { defaultValue: 'Actions' })}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.id} className="border-t border-border-light hover:bg-surface-secondary">
              <td className="px-4 py-2 font-medium text-content-primary truncate max-w-[320px]">{r.title}</td>
              <td className="px-4 py-2 text-xs text-content-secondary">{r.category ? categoryLabel(t, r.category) : '—'}</td>
              <td className="px-4 py-2">
                <Badge variant={SEVERITY_VARIANT[r.severity]}>{severityLabel(t, r.severity)}</Badge>
              </td>
              <td className="px-4 py-2">
                <Badge variant={PUNCH_STATUS_VARIANT[r.status] || 'neutral'} dot>
                  {statusLabel(t, r.status)}
                </Badge>
              </td>
              <td className="px-4 py-2 text-xs text-content-secondary">
                {r.due_date ? <DateDisplay value={r.due_date} /> : '—'}
              </td>
              <td className="px-4 py-2 text-right">
                {r.status !== 'closed' && r.status !== 'rejected' && (
                  <Button
                    variant="ghost"
                    size="sm"
                    loading={closeMut.isPending && closeMut.variables === r.id}
                    onClick={() => closeMut.mutate(r.id)}
                  >
                    {t('qms.close', { defaultValue: 'Close' })}
                  </Button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function AuditTable({ rows, onAction }: { rows: Audit[]; onAction: () => void }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const completeMut = useMutation({
    mutationFn: ({ id, rating }: { id: string; rating?: number }) => completeAudit(id, rating),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['qms', 'audits'] });
      addToast({ type: 'success', title: t('qms.audit_completed', { defaultValue: 'Audit completed' }) });
    },
    onError: (e) => addToast({ type: 'error', title: getErrorMessage(e) }),
  });
  if (rows.length === 0) {
    return (
      <EmptyState
        icon={<Award size={22} />}
        title={t('qms.empty_audits', { defaultValue: 'No audits planned' })}
        description={t('qms.empty_audits_desc', {
          defaultValue: 'ISO 9001 internal, external and supplier audits with finding registers.',
        })}
        action={{ label: t('qms.new_audit', { defaultValue: 'Plan Audit' }), onClick: onAction }}
      />
    );
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead className="bg-surface-secondary text-content-tertiary text-xs uppercase tracking-wide">
          <tr>
            <th className="px-4 py-2.5 text-left">{t('qms.audit_type', { defaultValue: 'Type' })}</th>
            <th className="px-4 py-2.5 text-left">{t('qms.standard', { defaultValue: 'Standard' })}</th>
            <th className="px-4 py-2.5 text-left">{t('qms.planned_date', { defaultValue: 'Planned' })}</th>
            <th className="px-4 py-2.5 text-left">{t('qms.status', { defaultValue: 'Status' })}</th>
            <th className="px-4 py-2.5 text-left">{t('qms.rating', { defaultValue: 'Rating' })}</th>
            <th className="px-4 py-2.5 text-right">{t('qms.actions', { defaultValue: 'Actions' })}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.id} className="border-t border-border-light hover:bg-surface-secondary">
              <td className="px-4 py-2 font-medium text-content-primary">{auditTypeLabel(t, r.audit_type)}</td>
              <td className="px-4 py-2 text-content-secondary text-xs">{r.standard_ref || '—'}</td>
              <td className="px-4 py-2 text-xs text-content-secondary">
                {r.planned_date ? <DateDisplay value={r.planned_date} /> : '—'}
              </td>
              <td className="px-4 py-2">
                <Badge variant={AUDIT_STATUS_VARIANT[r.status] || 'neutral'} dot>
                  {statusLabel(t, r.status)}
                </Badge>
              </td>
              <td className="px-4 py-2 text-xs tabular-nums">
                {r.overall_rating != null ? `${r.overall_rating} / 5` : '—'}
              </td>
              <td className="px-4 py-2 text-right">
                {r.status === 'in_progress' && (
                  <Button
                    variant="ghost"
                    size="sm"
                    loading={completeMut.isPending && completeMut.variables?.id === r.id}
                    onClick={() => completeMut.mutate({ id: r.id })}
                  >
                    {t('qms.complete', { defaultValue: 'Complete' })}
                  </Button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Close a drawer when the user presses Escape (matches WideModal UX). */
function useEscapeToClose(onClose: () => void) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onClose]);
}

/* ── NCR Drawer ────────────────────────────────────────────────────────── */

function NCRDrawer({
  id,
  ncrs,
  onClose,
}: {
  id: string;
  ncrs: NCR[];
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const ncr = ncrs.find((n) => n.id === id);
  const [actionDesc, setActionDesc] = useState('');
  const [responsible, setResponsible] = useState('');
  const [variationId, setVariationId] = useState('');

  const actionsQ = useQuery({
    queryKey: ['qms', 'ncr-actions', id],
    queryFn: () => listNCRActions(id),
  });

  // Open variation orders the NCR can be escalated against. The QMS module
  // never fabricates a variation, so escalation is gated on a real VO id.
  const variationsQ = useQuery({
    queryKey: ['qms', 'ncr-variations', ncr?.project_id],
    queryFn: () => listVariationOrders({ project_id: ncr!.project_id }),
    enabled: !!ncr?.project_id,
  });

  const invalidateAll = () => {
    qc.invalidateQueries({ queryKey: ['qms', 'ncrs'] });
    qc.invalidateQueries({ queryKey: ['qms', 'ncr-actions', id] });
  };

  const addAction = useMutation({
    mutationFn: () =>
      addNCRAction(id, {
        description: actionDesc,
        responsible_user_id: responsible || undefined,
      }),
    onSuccess: () => {
      invalidateAll();
      addToast({ type: 'success', title: t('qms.action_added', { defaultValue: 'Action assigned' }) });
      setActionDesc('');
      setResponsible('');
    },
    onError: (e) => addToast({ type: 'error', title: getErrorMessage(e) }),
  });

  const verifyAction = useMutation({
    mutationFn: (actionId: string) => verifyNCRAction(id, actionId),
    onSuccess: () => {
      invalidateAll();
      addToast({ type: 'success', title: t('qms.action_verified', { defaultValue: 'Action verified' }) });
    },
    onError: (e) => addToast({ type: 'error', title: getErrorMessage(e) }),
  });

  const escalate = useMutation({
    mutationFn: () => escalateNCRToVariation(id, variationId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['qms', 'ncrs'] });
      addToast({ type: 'success', title: t('qms.ncr_escalated', { defaultValue: 'NCR escalated to variation' }) });
      onClose();
    },
    onError: (e) => addToast({ type: 'error', title: getErrorMessage(e) }),
  });

  const closeMut = useMutation({
    mutationFn: () => closeNCR(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['qms', 'ncrs'] });
      addToast({ type: 'success', title: t('qms.ncr_closed', { defaultValue: 'NCR closed' }) });
      onClose();
    },
    onError: (e) => addToast({ type: 'error', title: getErrorMessage(e) }),
  });

  useEscapeToClose(onClose);

  if (!ncr) return null;

  const actions = actionsQ.data ?? [];
  const canEscalate = ncr.status !== 'closed' && ncr.status !== 'cancelled';

  return (
    <div className="fixed inset-0 z-50 flex justify-end" onClick={onClose}>
      <div className="absolute inset-0 bg-black/30" />
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="qms-ncr-drawer-title"
        className="relative h-full w-full max-w-lg overflow-y-auto bg-surface-elevated shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="sticky top-0 z-10 flex items-center justify-between border-b border-border-light bg-surface-elevated px-5 py-3">
          <h2 id="qms-ncr-drawer-title" className="text-base font-semibold truncate">
            {ncr.title}
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
          <p className="text-sm text-content-secondary whitespace-pre-wrap">{ncr.description}</p>
          <div className="grid grid-cols-2 gap-3 text-sm">
            <Field label={t('qms.severity')} value={<Badge variant={SEVERITY_VARIANT[ncr.severity]}>{severityLabel(t, ncr.severity)}</Badge>} />
            <Field
              label={t('qms.status')}
              value={<Badge variant={NCR_STATUS_VARIANT[ncr.status] || 'neutral'} dot>{statusLabel(t, ncr.status)}</Badge>}
            />
            <Field
              label={t('qms.raised_at')}
              value={ncr.raised_at ? <DateDisplay value={ncr.raised_at} /> : '—'}
            />
            <Field
              label={t('qms.cost_impact')}
              value={
                ncr.cost_impact_amount != null ? (
                  <MoneyDisplay amount={Number(ncr.cost_impact_amount)} currency={ncr.cost_impact_currency || undefined} />
                ) : (
                  '—'
                )
              }
            />
            {ncr.root_cause && (
              <Field label={t('qms.root_cause', { defaultValue: 'Root cause' })} value={ncr.root_cause} />
            )}
            {ncr.linked_variation_id && (
              <Field label={t('qms.linked_variation', { defaultValue: 'Variation' })} value={ncr.linked_variation_id} />
            )}
          </div>

          <Card padding="sm">
            <p className="text-xs font-semibold uppercase tracking-wide text-content-secondary mb-2">
              {t('qms.corrective_actions', { defaultValue: 'Corrective actions' })}
            </p>
            {actionsQ.isLoading ? (
              <p className="text-xs text-content-tertiary">
                {t('common.loading', { defaultValue: 'Loading…' })}
              </p>
            ) : actions.length === 0 ? (
              <p className="text-xs text-content-tertiary">
                {t('qms.no_actions', { defaultValue: 'No corrective actions assigned yet.' })}
              </p>
            ) : (
              <ul className="space-y-2">
                {actions.map((a: NCRAction) => (
                  <li
                    key={a.id}
                    className="flex items-start justify-between gap-2 rounded-md border border-border-light p-2"
                  >
                    <div className="min-w-0">
                      <p className="text-sm text-content-primary break-words">{a.description}</p>
                      <div className="mt-1 flex items-center gap-2">
                        <Badge variant={NCR_ACTION_VARIANT[a.status] || 'neutral'} dot>
                          {t(`qms.action_status.${a.status}`, {
                            defaultValue: NCR_ACTION_LABEL[a.status] ?? a.status,
                          })}
                        </Badge>
                        {a.due_date && (
                          <span className="text-2xs text-content-tertiary">
                            <DateDisplay value={a.due_date} />
                          </span>
                        )}
                      </div>
                    </div>
                    {a.status !== 'done' && ncr.status !== 'closed' && ncr.status !== 'cancelled' && (
                      <Button
                        variant="secondary"
                        size="sm"
                        icon={<CheckCircle2 size={14} />}
                        loading={verifyAction.isPending && verifyAction.variables === a.id}
                        onClick={() => verifyAction.mutate(a.id)}
                      >
                        {t('qms.verify_action', { defaultValue: 'Verify' })}
                      </Button>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </Card>

          {ncr.status !== 'closed' && ncr.status !== 'cancelled' && (
            <Card padding="sm">
              <p className="text-xs font-semibold uppercase tracking-wide text-content-secondary mb-2">
                {t('qms.add_action', { defaultValue: 'Assign corrective action' })}
              </p>
              <div className="space-y-2">
                <textarea
                  value={actionDesc}
                  onChange={(e) => setActionDesc(e.target.value)}
                  placeholder={t('qms.action_desc', { defaultValue: 'Action description' })}
                  rows={2}
                  className={clsx(inputCls, 'h-auto py-2')}
                />
                <input
                  value={responsible}
                  onChange={(e) => setResponsible(e.target.value)}
                  placeholder={t('qms.responsible_user', {
                    defaultValue: 'Responsible (name or user ID - optional)',
                  })}
                  className={inputCls}
                />
                <Button
                  variant="primary"
                  icon={<Send size={14} />}
                  disabled={!actionDesc.trim()}
                  loading={addAction.isPending}
                  onClick={() => addAction.mutate()}
                >
                  {t('qms.assign', { defaultValue: 'Assign' })}
                </Button>
              </div>
            </Card>
          )}

          {canEscalate && (
            <Card padding="sm">
              <p className="text-xs font-semibold uppercase tracking-wide text-content-secondary mb-2">
                {t('qms.escalate_to_variation', { defaultValue: 'Escalate to Variation' })}
              </p>
              <div className="space-y-2">
                <select
                  value={variationId}
                  onChange={(e) => setVariationId(e.target.value)}
                  className={inputCls}
                >
                  <option value="">
                    {t('qms.select_variation', { defaultValue: 'Select a variation order…' })}
                  </option>
                  {(variationsQ.data ?? []).map((vo) => (
                    <option key={vo.id} value={vo.id}>
                      {vo.code} — {vo.title}
                    </option>
                  ))}
                </select>
                {(variationsQ.data ?? []).length === 0 && !variationsQ.isLoading && (
                  <p className="text-2xs text-content-tertiary">
                    {t('qms.no_variations', {
                      defaultValue: 'No variation orders exist for this project yet. Create one in Variations first.',
                    })}
                  </p>
                )}
                <Button
                  variant="primary"
                  icon={<ArrowUpRight size={14} />}
                  disabled={!variationId}
                  onClick={() => escalate.mutate()}
                  loading={escalate.isPending}
                >
                  {t('qms.escalate_to_variation', { defaultValue: 'Escalate to Variation' })}
                </Button>
              </div>
            </Card>
          )}

          {ncr.status === 'verifying' && (
            <div className="flex flex-wrap gap-2 pt-2">
              <Button
                variant="secondary"
                icon={<CheckCircle2 size={14} />}
                onClick={() => closeMut.mutate()}
                loading={closeMut.isPending}
              >
                {t('qms.close_ncr', { defaultValue: 'Close NCR' })}
              </Button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

/* ── ITP Plan Drawer (hold-point sequencing + spec linkage, item 12) ─────── */

/**
 * Download the ITP-plan compliance dossier (CSV) through an authed fetch.
 *
 * The endpoint is JWT-Bearer-only (qms.report.read), so a plain anchor would
 * navigate without the Authorization header and return 401. We fetch it with
 * the token, then hand the blob to triggerDownload. Exported for unit tests.
 */
export async function downloadPlanComplianceCsv(planId: string): Promise<void> {
  const token = getAuthToken();
  const response = await fetch(planComplianceCsvUrl(planId), {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!response.ok) {
    throw new Error(`Export failed (${response.status})`);
  }
  const blob = await response.blob();
  triggerDownload(blob, `itp_plan_${planId}_compliance.csv`);
}

function ITPPlanDrawer({
  planId,
  plan,
  projectId,
  onClose,
}: {
  planId: string;
  plan: ITPPlan | null;
  projectId: string;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const [editItemId, setEditItemId] = useState<string | null>(null);
  const [exportingCsv, setExportingCsv] = useState(false);

  const handleExportComplianceCsv = async () => {
    if (exportingCsv) return;
    setExportingCsv(true);
    try {
      await downloadPlanComplianceCsv(planId);
    } catch (err) {
      addToast({ type: 'error', title: getErrorMessage(err) });
    } finally {
      setExportingCsv(false);
    }
  };

  const itemsQ = useQuery({
    queryKey: ['qms', 'itp-items', planId],
    queryFn: () => listITPItems(planId),
  });
  // Inspections drive the dependency-tree traffic lights.
  const inspQ = useQuery({
    queryKey: ['qms', 'inspections', projectId, ''],
    queryFn: () => listInspections({ project_id: projectId, limit: 200 }),
    enabled: !!projectId,
  });

  useEscapeToClose(onClose);

  const items = itemsQ.data ?? [];

  return (
    <div className="fixed inset-0 z-50 flex justify-end" onClick={onClose}>
      <div className="absolute inset-0 bg-black/30" />
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="qms-plan-drawer-title"
        className="relative h-full w-full max-w-lg overflow-y-auto bg-surface-elevated shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="sticky top-0 z-10 flex items-center justify-between border-b border-border-light bg-surface-elevated px-5 py-3">
          <h2 id="qms-plan-drawer-title" className="text-base font-semibold">
            {plan?.name || t('qms.itp_plan', { defaultValue: 'ITP plan' })}
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
          <div className="flex items-center justify-between rounded-md border border-border-light bg-surface-secondary px-3 py-2">
            <span className="flex items-center gap-1.5 text-xs text-content-secondary">
              <FileCheck size={13} />
              {t('qms.compliance_dossier', {
                defaultValue: 'Audit-ready quality dossier',
              })}
            </span>
            <button
              type="button"
              onClick={handleExportComplianceCsv}
              disabled={exportingCsv}
              className="flex items-center gap-1 rounded border border-border-light px-2 py-1 text-2xs font-medium text-content-primary hover:bg-surface-tertiary disabled:opacity-50"
            >
              {exportingCsv ? <Loader2 size={12} className="animate-spin" /> : <Download size={12} />}
              {t('qms.export_compliance_csv', {
                defaultValue: 'Export compliance (CSV)',
              })}
            </button>
          </div>
          <div>
            <p className="mb-2 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-content-secondary">
              <Lock size={13} />
              {t('qms.hold_point_sequencing', { defaultValue: 'Hold point sequencing' })}
            </p>
            {itemsQ.isLoading ? (
              <div className="flex items-center gap-2 py-3 text-xs text-content-tertiary">
                <Loader2 size={14} className="animate-spin" />
                {t('common.loading', { defaultValue: 'Loading…' })}
              </div>
            ) : (
              <HoldPointDependencyTree items={items} inspections={inspQ.data ?? []} />
            )}
          </div>

          {items.length > 0 && (
            <div>
              <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-content-secondary">
                {t('qms.spec_linkage', { defaultValue: 'Spec linkage' })}
              </p>
              <ul className="space-y-1.5">
                {[...items]
                  .sort((a, b) => a.sequence - b.sequence)
                  .map((it) => (
                    <li key={it.id}>
                      <button
                        type="button"
                        onClick={() => setEditItemId(editItemId === it.id ? null : it.id)}
                        className="flex w-full items-center justify-between gap-2 rounded-md border border-border-light bg-surface-secondary px-2.5 py-1.5 text-left text-xs hover:bg-surface-tertiary"
                      >
                        <span className="truncate font-medium text-content-primary">
                          {it.sequence}. {it.control_point_name}
                        </span>
                        <span className="text-2xs text-content-tertiary">
                          {it.boq_position_id || it.csi_section_ref || it.spec_drawing_ref || it.bim_element_id
                            ? t('qms.linked', { defaultValue: 'Linked' })
                            : t('qms.not_linked', { defaultValue: 'Not linked' })}
                        </span>
                      </button>
                      {editItemId === it.id && (
                        <SpecLinkEditor
                          planId={planId}
                          item={it}
                          items={items}
                          onDone={() => setEditItemId(null)}
                        />
                      )}
                    </li>
                  ))}
              </ul>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function SpecLinkEditor({
  planId,
  item,
  items,
  onDone,
}: {
  planId: string;
  item: ITPItem;
  items: ITPItem[];
  onDone: () => void;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [csi, setCsi] = useState(item.csi_section_ref ?? '');
  const [drawing, setDrawing] = useState(item.spec_drawing_ref ?? '');
  const [bim, setBim] = useState(item.bim_element_id ?? '');
  const [predecessor, setPredecessor] = useState(item.predecessor_itp_item_id ?? '');

  const save = useMutation({
    mutationFn: () =>
      linkITPItemToSpec(planId, item.id, {
        csi_section_ref: csi.trim() || null,
        spec_drawing_ref: drawing.trim() || null,
        bim_element_id: bim.trim() || null,
        predecessor_itp_item_id: predecessor || null,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['qms', 'itp-items', planId] });
      addToast({ type: 'success', title: t('qms.spec_linked', { defaultValue: 'Control point linked' }) });
      onDone();
    },
    onError: (e) => addToast({ type: 'error', title: getErrorMessage(e) }),
  });

  // Predecessor candidates: any other item in the same plan.
  const candidates = items.filter((i) => i.id !== item.id);

  return (
    <div className="mt-1.5 space-y-2 rounded-md border border-border-light bg-surface-primary p-2.5">
      <input
        value={csi}
        onChange={(e) => setCsi(e.target.value)}
        placeholder={t('qms.csi_section', { defaultValue: 'CSI section (e.g. 03 30 00)' })}
        className={inputCls}
        aria-label={t('qms.csi_section', { defaultValue: 'CSI section' })}
      />
      <input
        value={drawing}
        onChange={(e) => setDrawing(e.target.value)}
        placeholder={t('qms.spec_drawing', { defaultValue: 'Drawing reference' })}
        className={inputCls}
        aria-label={t('qms.spec_drawing', { defaultValue: 'Drawing reference' })}
      />
      <input
        value={bim}
        onChange={(e) => setBim(e.target.value)}
        placeholder={t('qms.bim_element', { defaultValue: 'BIM element id' })}
        className={inputCls}
        aria-label={t('qms.bim_element', { defaultValue: 'BIM element id' })}
      />
      <select
        value={predecessor}
        onChange={(e) => setPredecessor(e.target.value)}
        className={inputCls}
        aria-label={t('qms.predecessor', { defaultValue: 'Predecessor hold point' })}
      >
        <option value="">
          {t('qms.no_predecessor', { defaultValue: 'No predecessor' })}
        </option>
        {candidates.map((c) => (
          <option key={c.id} value={c.id}>
            {c.sequence}. {c.control_point_name}
          </option>
        ))}
      </select>
      <div className="flex gap-2">
        <Button variant="primary" size="sm" loading={save.isPending} onClick={() => save.mutate()}>
          {t('common.save', { defaultValue: 'Save' })}
        </Button>
        <Button variant="ghost" size="sm" onClick={onDone}>
          {t('common.cancel', { defaultValue: 'Cancel' })}
        </Button>
      </div>
    </div>
  );
}

/* ── Inspection Drawer ─────────────────────────────────────────────────── */

function InspectionDrawer({
  id,
  inspections,
  onClose,
  onRaiseNcr,
}: {
  id: string;
  inspections: Inspection[];
  onClose: () => void;
  /** Raise an NCR pre-filled with this inspection as the linked source. */
  onRaiseNcr: (inspectionId: string) => void;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const insp = inspections.find((i) => i.id === id);
  const [result, setResult] = useState<'passed' | 'failed' | 'conditional'>('passed');
  const [notes, setNotes] = useState('');
  const [signRole, setSignRole] = useState<InspectionSignature['signer_role']>('inspector');

  const [releaseJustification, setReleaseJustification] = useState('');

  const sigsQ = useQuery({
    queryKey: ['qms', 'inspection-signatures', id],
    queryFn: () => listInspectionSignatures(id),
  });

  const holdQ = useQuery({
    queryKey: ['qms', 'hold-point-status', id],
    queryFn: () => checkHoldPointStatus(id),
  });

  const release = useMutation({
    mutationFn: () => releaseHoldPoint(id, { justification: releaseJustification.trim() }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['qms', 'hold-point-status', id] });
      qc.invalidateQueries({ queryKey: ['qms', 'inspections'] });
      addToast({
        type: 'success',
        title: t('qms.hold_point_released', { defaultValue: 'Hold point released' }),
      });
      setReleaseJustification('');
    },
    onError: (e) => addToast({ type: 'error', title: getErrorMessage(e) }),
  });

  const sign = useMutation({
    // signer_user_id is omitted on purpose: the backend signs as the
    // authenticated caller, so a normal user signs in one click without
    // hand-typing a UUID.
    mutationFn: () =>
      signInspection(id, {
        signer_role: signRole,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['qms', 'inspection-signatures', id] });
      addToast({ type: 'success', title: t('qms.signature_added', { defaultValue: 'Signature recorded' }) });
    },
    onError: (e) => addToast({ type: 'error', title: getErrorMessage(e) }),
  });

  const complete = useMutation({
    mutationFn: () => completeInspection(id, result, notes || undefined),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['qms', 'inspections'] });
      addToast({ type: 'success', title: t('qms.inspection_completed', { defaultValue: 'Inspection completed' }) });
      onClose();
    },
    onError: (e) => addToast({ type: 'error', title: getErrorMessage(e) }),
  });

  useEscapeToClose(onClose);

  if (!insp) return null;

  const photos = insp.photos_json ?? [];
  const sigData = sigsQ.data;
  const required = sigData?.required ?? 1;
  const collected = sigData?.collected ?? 0;
  const signaturesSatisfied = collected >= required;
  const isOpenStatus = insp.status === 'scheduled' || insp.status === 'in_progress';
  const SIGNER_ROLES: InspectionSignature['signer_role'][] = [
    'GC',
    'designer',
    'client',
    'subcontractor',
    'inspector',
    'other',
  ];

  return (
    <div className="fixed inset-0 z-50 flex justify-end" onClick={onClose}>
      <div className="absolute inset-0 bg-black/30" />
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="qms-insp-drawer-title"
        className="relative h-full w-full max-w-lg overflow-y-auto bg-surface-elevated shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="sticky top-0 z-10 flex items-center justify-between border-b border-border-light bg-surface-elevated px-5 py-3">
          <h2 id="qms-insp-drawer-title" className="text-base font-semibold">
            {insp.location_ref || t('qms.inspection', { defaultValue: 'Inspection' })}
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
          <div className="grid grid-cols-2 gap-3 text-sm">
            <Field label={t('qms.status')} value={<Badge variant={INSPECTION_VARIANT[insp.status] || 'neutral'} dot>{statusLabel(t, insp.status)}</Badge>} />
            <Field
              label={t('qms.scheduled_at')}
              value={insp.scheduled_at ? <DateDisplay value={insp.scheduled_at} /> : '—'}
            />
            <Field
              label={t('qms.performed_at')}
              value={insp.performed_at ? <DateDisplay value={insp.performed_at} /> : '—'}
            />
            <Field label={t('qms.drawing_ref', { defaultValue: 'Drawing' })} value={insp.drawing_ref || '—'} />
            {insp.notes && <Field label={t('qms.notes')} value={insp.notes} />}
          </div>

          {holdQ.data?.is_hold_point && (
            <div
              className={clsx(
                'flex items-start gap-2 rounded-lg border px-3 py-2 text-sm',
                holdQ.data.released
                  ? 'border-semantic-success/30 bg-semantic-success/10 text-semantic-success'
                  : holdQ.data.blocked
                    ? 'border-semantic-error/30 bg-semantic-error/10 text-semantic-error'
                    : 'border-semantic-warning/30 bg-semantic-warning/10 text-semantic-warning',
              )}
            >
              {holdQ.data.released ? (
                <Unlock size={15} className="mt-0.5 shrink-0" />
              ) : holdQ.data.blocked ? (
                <ShieldAlert size={15} className="mt-0.5 shrink-0" />
              ) : (
                <Lock size={15} className="mt-0.5 shrink-0" />
              )}
              <div>
                <p className="font-medium">
                  {holdQ.data.released
                    ? t('qms.hold_point_released_label', { defaultValue: 'Hold point released' })
                    : holdQ.data.blocked
                      ? t('qms.hold_point_blocked_label', { defaultValue: 'Hold point blocked' })
                      : t('qms.hold_point_label', { defaultValue: 'Hold point' })}
                </p>
                {holdQ.data.blocking_reason && (
                  <p className="text-xs opacity-90">{holdQ.data.blocking_reason}</p>
                )}
              </div>
            </div>
          )}

          {/* Failed (or conditional) inspection -> raise an NCR pre-filled with
              this inspection as the linked source (CONN-64). */}
          {(insp.status === 'failed' || insp.status === 'conditional') && (
            <Card padding="sm" className="border-semantic-error/30 bg-semantic-error/5">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="flex items-start gap-2">
                  <AlertOctagon size={15} className="mt-0.5 shrink-0 text-semantic-error" />
                  <p className="text-xs text-content-secondary">
                    {t('qms.inspection_failed_ncr_hint', {
                      defaultValue:
                        'This inspection did not pass. Raise an NCR so the defect is tracked to close-out.',
                    })}
                  </p>
                </div>
                <Button
                  variant="primary"
                  size="sm"
                  icon={<AlertOctagon size={14} />}
                  onClick={() => onRaiseNcr(id)}
                >
                  {t('qms.raise_ncr_from_inspection', { defaultValue: 'Raise NCR' })}
                </Button>
              </div>
            </Card>
          )}

          <Card padding="sm">
            <div className="flex items-center justify-between mb-2">
              <p className="text-xs font-semibold uppercase tracking-wide text-content-secondary">
                {t('qms.signatures', { defaultValue: 'Signatures' })}
              </p>
              <Badge variant={signaturesSatisfied ? 'success' : 'warning'}>
                {t('qms.signatures_collected', {
                  defaultValue: '{{collected}}/{{required}} collected',
                  collected,
                  required,
                })}
              </Badge>
            </div>
            <p className="text-xs text-content-tertiary mb-2">
              {t('qms.signatures_hint', {
                defaultValue: 'Sign-offs are captured per role (GC, designer, client, inspector).',
              })}
            </p>
            {(sigData?.signatures ?? []).length > 0 && (
              <ul className="mb-3 space-y-1.5">
                {(sigData?.signatures ?? []).map((s) => (
                  <li key={s.id} className="text-xs">
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-content-primary">
                        {t(`qms.signer_role.${s.signer_role}`, { defaultValue: s.signer_role })}
                      </span>
                      <span className="text-content-tertiary">
                        {s.signed_at ? <DateDisplay value={s.signed_at} /> : '—'}
                      </span>
                    </div>
                    {s.signer_ip && (
                      <p className="text-2xs text-content-tertiary">
                        {t('qms.signed_from', {
                          defaultValue: 'from {{ip}}',
                          ip: s.signer_ip,
                        })}
                      </p>
                    )}
                  </li>
                ))}
              </ul>
            )}
            {isOpenStatus && (
              <div className="space-y-2 border-t border-border-light pt-2">
                <label className="block text-2xs font-medium uppercase tracking-wide text-content-tertiary">
                  {t('qms.sign_as_role', { defaultValue: 'Sign as role' })}
                </label>
                <select
                  value={signRole}
                  onChange={(e) => setSignRole(e.target.value as InspectionSignature['signer_role'])}
                  className={inputCls}
                  aria-label={t('qms.sign_as_role', { defaultValue: 'Sign as role' })}
                >
                  {SIGNER_ROLES.map((r) => (
                    <option key={r} value={r}>
                      {t(`qms.signer_role.${r}`, { defaultValue: r })}
                    </option>
                  ))}
                </select>
                <p className="text-2xs text-content-tertiary">
                  {t('qms.sign_as_me_hint', {
                    defaultValue: 'You will sign this inspection as yourself in the selected role.',
                  })}
                </p>
                <Button
                  variant="secondary"
                  size="sm"
                  icon={<FileCheck size={14} />}
                  loading={sign.isPending}
                  onClick={() => sign.mutate()}
                >
                  {t('qms.sign_as_me', { defaultValue: 'Sign as me' })}
                </Button>
              </div>
            )}
          </Card>

          {photos.length > 0 && (
            <Card padding="sm">
              <p className="text-xs font-semibold uppercase tracking-wide text-content-secondary mb-2">
                {t('qms.photos', { defaultValue: 'Photos' })}
              </p>
              <div className="grid grid-cols-3 gap-2">
                {photos.map((p, idx) => {
                  const url = typeof p === 'object' && p && 'url' in p ? String((p as { url?: unknown }).url ?? '') : '';
                  return (
                    <div
                      key={idx}
                      className="aspect-square rounded-md bg-surface-secondary overflow-hidden flex items-center justify-center text-content-tertiary text-2xs"
                    >
                      {url ? (
                        <img
                          src={url}
                          alt={t('qms.inspection_photo', {
                            defaultValue: 'Inspection photo',
                          })}
                          className="h-full w-full object-cover"
                        />
                      ) : (
                        t('qms.photo', { defaultValue: 'Photo' })
                      )}
                    </div>
                  );
                })}
              </div>
            </Card>
          )}

          <AttachmentEvidenceGallery inspectionId={id} canEdit={isOpenStatus} />

          {holdQ.data?.is_hold_point && insp.status === 'passed' && !holdQ.data.released && (
            <Card padding="sm">
              <p className="mb-2 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-content-secondary">
                <Unlock size={13} />
                {t('qms.release_hold_point', { defaultValue: 'Release hold point' })}
              </p>
              <p className="mb-2 text-2xs text-content-tertiary">
                {t('qms.release_hint', {
                  defaultValue:
                    'Releasing this hold point unblocks dependent work. The release is recorded with your name and time.',
                })}
              </p>
              <textarea
                value={releaseJustification}
                onChange={(e) => setReleaseJustification(e.target.value)}
                placeholder={t('qms.release_justification', {
                  defaultValue: 'Justification (required)',
                })}
                rows={2}
                className={clsx(inputCls, 'h-auto py-2')}
                aria-label={t('qms.release_justification', { defaultValue: 'Justification (required)' })}
              />
              <Button
                variant="primary"
                size="sm"
                className="mt-2"
                icon={<Unlock size={14} />}
                disabled={!releaseJustification.trim()}
                loading={release.isPending}
                onClick={() => release.mutate()}
              >
                {t('qms.release', { defaultValue: 'Release' })}
              </Button>
            </Card>
          )}

          {(insp.status === 'scheduled' || insp.status === 'in_progress') && (
            <Card padding="sm">
              <p className="text-xs font-semibold uppercase tracking-wide text-content-secondary mb-2">
                {t('qms.complete_inspection', { defaultValue: 'Complete inspection' })}
              </p>
              <div className="space-y-2">
                <select
                  value={result}
                  onChange={(e) => setResult(e.target.value as 'passed' | 'failed' | 'conditional')}
                  className={inputCls}
                >
                  <option value="passed">{t('qms.result_passed', { defaultValue: 'Passed' })}</option>
                  <option value="failed">{t('qms.result_failed', { defaultValue: 'Failed' })}</option>
                  <option value="conditional">{t('qms.result_conditional', { defaultValue: 'Conditional' })}</option>
                </select>
                <textarea
                  value={notes}
                  onChange={(e) => setNotes(e.target.value)}
                  placeholder={t('qms.notes_placeholder', { defaultValue: 'Notes (optional)' })}
                  rows={2}
                  className={clsx(inputCls, 'h-auto py-2')}
                />
                {!signaturesSatisfied && (
                  <p className="text-2xs text-semantic-warning">
                    {t('qms.signatures_required_hint', {
                      defaultValue: 'Collect {{required}} signature(s) before completing.',
                      required,
                    })}
                  </p>
                )}
                <Button
                  variant="primary"
                  icon={<CheckCircle2 size={14} />}
                  disabled={!signaturesSatisfied}
                  onClick={() => complete.mutate()}
                  loading={complete.isPending}
                >
                  {t('qms.complete', { defaultValue: 'Complete' })}
                </Button>
              </div>
            </Card>
          )}
        </div>
      </div>
    </div>
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

/* ── Create modal ──────────────────────────────────────────────────────── */

function CreateModal({
  kind,
  projectId,
  itpPlans,
  inspections,
  prefillInspectionId,
  onClose,
}: {
  kind: Tab;
  projectId: string;
  itpPlans: ITPPlan[];
  inspections: Inspection[];
  /** When set, seeds the NCR form's linked inspection (CONN-64). */
  prefillInspectionId?: string | null;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [busy, setBusy] = useState(false);

  const [itpForm, setItpForm] = useState({ name: '', work_type: '', wbs_ref: '' });
  const [inspForm, setInspForm] = useState({
    itp_item_id: '',
    location_ref: '',
    scheduled_at: '',
    notes: '',
  });
  // ITP plan picked first; its control-point items are loaded on demand so
  // the inspection's itp_item_id is a real item id (FK to oe_qms_itp_item),
  // never a plan id.
  const [selectedPlanId, setSelectedPlanId] = useState('');
  const itpItemsQ = useQuery({
    queryKey: ['qms', 'itp-items', selectedPlanId],
    queryFn: () => listITPItems(selectedPlanId),
    enabled: kind === 'inspections' && !!selectedPlanId,
  });
  const [ncrForm, setNcrForm] = useState({
    title: '',
    description: '',
    severity: 'minor' as NCRSeverity,
    cost_impact_amount: '',
    cost_impact_currency: '',
    linked_inspection_id: prefillInspectionId ?? '',
  });
  const [punchForm, setPunchForm] = useState({
    title: '',
    description: '',
    room_ref: '',
    severity: 'minor' as NCRSeverity,
    category: '' as PunchCategory | '',
    due_date: '',
  });
  const [auditForm, setAuditForm] = useState({
    audit_type: 'internal' as 'internal' | 'external' | 'supplier',
    standard_ref: 'ISO 9001',
    planned_date: '',
    audit_scope: '',
  });

  const submit = async () => {
    setBusy(true);
    try {
      if (kind === 'itp') {
        if (!itpForm.name.trim() || !itpForm.work_type.trim()) throw new Error('Name and work type required');
        await createITPPlan({
          project_id: projectId,
          name: itpForm.name,
          work_type: itpForm.work_type,
          wbs_ref: itpForm.wbs_ref || undefined,
        });
        addToast({ type: 'success', title: t('qms.itp_created', { defaultValue: 'ITP plan created' }) });
        qc.invalidateQueries({ queryKey: ['qms', 'itp'] });
      } else if (kind === 'inspections') {
        await createInspection({
          project_id: projectId,
          itp_item_id: inspForm.itp_item_id || undefined,
          location_ref: inspForm.location_ref || undefined,
          scheduled_at: inspForm.scheduled_at || undefined,
          notes: inspForm.notes || undefined,
        });
        addToast({ type: 'success', title: t('qms.inspection_scheduled', { defaultValue: 'Inspection scheduled' }) });
        qc.invalidateQueries({ queryKey: ['qms', 'inspections'] });
      } else if (kind === 'ncrs') {
        if (!ncrForm.title.trim() || !ncrForm.description.trim()) throw new Error('Title and description required');
        await createNCR({
          project_id: projectId,
          title: ncrForm.title,
          description: ncrForm.description,
          severity: ncrForm.severity,
          cost_impact_amount: ncrForm.cost_impact_amount ? Number(ncrForm.cost_impact_amount) : undefined,
          cost_impact_currency: ncrForm.cost_impact_currency || undefined,
          linked_inspection_id: ncrForm.linked_inspection_id || undefined,
        });
        addToast({ type: 'success', title: t('qms.ncr_created', { defaultValue: 'NCR raised' }) });
        qc.invalidateQueries({ queryKey: ['qms', 'ncrs'] });
      } else if (kind === 'punch') {
        if (!punchForm.title.trim()) throw new Error('Title required');
        await createPunchItem({
          project_id: projectId,
          title: punchForm.title,
          description: punchForm.description || undefined,
          room_ref: punchForm.room_ref || undefined,
          severity: punchForm.severity,
          category: punchForm.category || undefined,
          due_date: punchForm.due_date || undefined,
        });
        addToast({ type: 'success', title: t('qms.punch_created', { defaultValue: 'Punch item added' }) });
        qc.invalidateQueries({ queryKey: ['qms', 'punch'] });
      } else if (kind === 'audits') {
        await createAudit({
          project_id: projectId,
          audit_type: auditForm.audit_type,
          standard_ref: auditForm.standard_ref || undefined,
          planned_date: auditForm.planned_date || undefined,
          audit_scope: auditForm.audit_scope || undefined,
        });
        addToast({ type: 'success', title: t('qms.audit_created', { defaultValue: 'Audit planned' }) });
        qc.invalidateQueries({ queryKey: ['qms', 'audits'] });
      }
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
      busy={busy}
      size="xl"
      title={tabCreateLabel(kind, t)}
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={busy}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button variant="primary" onClick={submit} loading={busy} icon={busy ? <Loader2 size={14} /> : <Plus size={14} />}>
            {t('common.create', { defaultValue: 'Create' })}
          </Button>
        </>
      }
    >
      {kind === 'itp' && (
        <WideModalSection columns={2}>
          <WideModalField label={t('qms.name', { defaultValue: 'Name' })} required span={2}>
            <input value={itpForm.name} onChange={(e) => setItpForm({ ...itpForm, name: e.target.value })} className={inputCls} />
          </WideModalField>
          <WideModalField label={t('qms.work_type', { defaultValue: 'Work type' })} required>
            <input
              value={itpForm.work_type}
              onChange={(e) => setItpForm({ ...itpForm, work_type: e.target.value })}
              className={inputCls}
              placeholder="concrete / mep / finishes / …"
            />
          </WideModalField>
          <WideModalField label={t('qms.wbs', { defaultValue: 'WBS ref' })}>
            <input value={itpForm.wbs_ref} onChange={(e) => setItpForm({ ...itpForm, wbs_ref: e.target.value })} className={inputCls} />
          </WideModalField>
        </WideModalSection>
      )}

      {kind === 'inspections' && (
        <WideModalSection columns={2}>
          <WideModalField
            label={t('qms.itp_plan', { defaultValue: 'ITP plan (optional)' })}
          >
            <select
              value={selectedPlanId}
              onChange={(e) => {
                setSelectedPlanId(e.target.value);
                // Reset the item whenever the plan changes so we never
                // submit an item id from a different plan.
                setInspForm({ ...inspForm, itp_item_id: '' });
              }}
              className={inputCls}
            >
              <option value="">—</option>
              {itpPlans.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          </WideModalField>
          <WideModalField
            label={t('qms.itp_item', { defaultValue: 'ITP control point (optional)' })}
          >
            <select
              value={inspForm.itp_item_id}
              onChange={(e) => setInspForm({ ...inspForm, itp_item_id: e.target.value })}
              className={inputCls}
              disabled={!selectedPlanId || itpItemsQ.isLoading}
            >
              <option value="">
                {!selectedPlanId
                  ? t('qms.itp_pick_plan_first', { defaultValue: 'Pick a plan first' })
                  : itpItemsQ.isLoading
                    ? t('common.loading', { defaultValue: 'Loading…' })
                    : '—'}
              </option>
              {(itpItemsQ.data ?? []).map((it: ITPItem) => (
                <option key={it.id} value={it.id}>
                  {it.sequence}. {it.control_point_name}
                  {it.signatories_required > 1
                    ? ` (${it.signatories_required}×)`
                    : ''}
                </option>
              ))}
            </select>
          </WideModalField>
          <WideModalField label={t('qms.location', { defaultValue: 'Location' })}>
            <input
              value={inspForm.location_ref}
              onChange={(e) => setInspForm({ ...inspForm, location_ref: e.target.value })}
              className={inputCls}
            />
          </WideModalField>
          <WideModalField label={t('qms.scheduled_at', { defaultValue: 'Scheduled at' })}>
            <input
              type="datetime-local"
              value={inspForm.scheduled_at}
              onChange={(e) => setInspForm({ ...inspForm, scheduled_at: e.target.value })}
              className={inputCls}
            />
          </WideModalField>
          <WideModalField label={t('qms.notes', { defaultValue: 'Notes' })} span={2}>
            <textarea
              value={inspForm.notes}
              onChange={(e) => setInspForm({ ...inspForm, notes: e.target.value })}
              rows={2}
              className={clsx(inputCls, 'h-auto py-2')}
            />
          </WideModalField>
        </WideModalSection>
      )}

      {kind === 'ncrs' && (
        <WideModalSection columns={2}>
          <WideModalField label={t('qms.title_col', { defaultValue: 'Title' })} required span={2}>
            <input value={ncrForm.title} onChange={(e) => setNcrForm({ ...ncrForm, title: e.target.value })} className={inputCls} />
          </WideModalField>
          <WideModalField label={t('qms.description', { defaultValue: 'Description' })} required span={2}>
            <textarea
              value={ncrForm.description}
              onChange={(e) => setNcrForm({ ...ncrForm, description: e.target.value })}
              rows={3}
              className={clsx(inputCls, 'h-auto py-2')}
            />
          </WideModalField>
          <WideModalField label={t('qms.severity', { defaultValue: 'Severity' })}>
            <select
              value={ncrForm.severity}
              onChange={(e) => setNcrForm({ ...ncrForm, severity: e.target.value as NCRSeverity })}
              className={inputCls}
            >
              {(['minor', 'major', 'critical'] as NCRSeverity[]).map((s) => (
                <option key={s} value={s}>
                  {severityLabel(t, s)}
                </option>
              ))}
            </select>
          </WideModalField>
          <WideModalField label={t('qms.linked_inspection', { defaultValue: 'Linked inspection' })}>
            <select
              value={ncrForm.linked_inspection_id}
              onChange={(e) => setNcrForm({ ...ncrForm, linked_inspection_id: e.target.value })}
              className={inputCls}
            >
              <option value="">—</option>
              {inspections.map((i) => (
                <option key={i.id} value={i.id}>
                  {i.location_ref || i.id.slice(0, 8)}
                </option>
              ))}
            </select>
          </WideModalField>
          <WideModalField label={t('qms.cost_impact', { defaultValue: 'Cost impact' })}>
            <input
              type="number"
              value={ncrForm.cost_impact_amount}
              onChange={(e) => setNcrForm({ ...ncrForm, cost_impact_amount: e.target.value })}
              className={inputCls}
            />
          </WideModalField>
          <WideModalField label={t('common.currency', { defaultValue: 'Currency' })}>
            <input
              value={ncrForm.cost_impact_currency}
              onChange={(e) => setNcrForm({ ...ncrForm, cost_impact_currency: e.target.value })}
              className={inputCls}
              maxLength={3}
            />
          </WideModalField>
        </WideModalSection>
      )}

      {kind === 'punch' && (
        <WideModalSection columns={2}>
          <WideModalField label={t('qms.title_col', { defaultValue: 'Title' })} required span={2}>
            <input
              value={punchForm.title}
              onChange={(e) => setPunchForm({ ...punchForm, title: e.target.value })}
              className={inputCls}
            />
          </WideModalField>
          <WideModalField label={t('qms.description', { defaultValue: 'Description' })} span={2}>
            <textarea
              value={punchForm.description}
              onChange={(e) => setPunchForm({ ...punchForm, description: e.target.value })}
              rows={2}
              className={clsx(inputCls, 'h-auto py-2')}
            />
          </WideModalField>
          <WideModalField label={t('qms.room', { defaultValue: 'Room / area' })}>
            <input
              value={punchForm.room_ref}
              onChange={(e) => setPunchForm({ ...punchForm, room_ref: e.target.value })}
              className={inputCls}
            />
          </WideModalField>
          <WideModalField label={t('qms.category')}>
            <select
              value={punchForm.category}
              onChange={(e) =>
                setPunchForm({ ...punchForm, category: e.target.value as PunchCategory | '' })
              }
              className={inputCls}
            >
              <option value="">—</option>
              {(['architectural', 'mechanical', 'electrical', 'finishes', 'structure'] as PunchCategory[]).map((c) => (
                <option key={c} value={c}>
                  {categoryLabel(t, c)}
                </option>
              ))}
            </select>
          </WideModalField>
          <WideModalField label={t('qms.severity')}>
            <select
              value={punchForm.severity}
              onChange={(e) => setPunchForm({ ...punchForm, severity: e.target.value as NCRSeverity })}
              className={inputCls}
            >
              {(['minor', 'major', 'critical'] as NCRSeverity[]).map((s) => (
                <option key={s} value={s}>
                  {severityLabel(t, s)}
                </option>
              ))}
            </select>
          </WideModalField>
          <WideModalField label={t('qms.due_date')}>
            <input
              type="date"
              value={punchForm.due_date}
              onChange={(e) => setPunchForm({ ...punchForm, due_date: e.target.value })}
              className={inputCls}
            />
          </WideModalField>
        </WideModalSection>
      )}

      {kind === 'audits' && (
        <WideModalSection columns={2}>
          <WideModalField label={t('qms.audit_type')}>
            <select
              value={auditForm.audit_type}
              onChange={(e) =>
                setAuditForm({ ...auditForm, audit_type: e.target.value as 'internal' | 'external' | 'supplier' })
              }
              className={inputCls}
            >
              <option value="internal">{auditTypeLabel(t, 'internal')}</option>
              <option value="external">{auditTypeLabel(t, 'external')}</option>
              <option value="supplier">{auditTypeLabel(t, 'supplier')}</option>
            </select>
          </WideModalField>
          <WideModalField label={t('qms.standard', { defaultValue: 'Standard' })}>
            <input
              value={auditForm.standard_ref}
              onChange={(e) => setAuditForm({ ...auditForm, standard_ref: e.target.value })}
              className={inputCls}
            />
          </WideModalField>
          <WideModalField label={t('qms.planned_date', { defaultValue: 'Planned date' })} span={2}>
            <input
              type="date"
              value={auditForm.planned_date}
              onChange={(e) => setAuditForm({ ...auditForm, planned_date: e.target.value })}
              className={inputCls}
            />
          </WideModalField>
          <WideModalField label={t('qms.audit_scope', { defaultValue: 'Scope' })} span={2}>
            <textarea
              value={auditForm.audit_scope}
              onChange={(e) => setAuditForm({ ...auditForm, audit_scope: e.target.value })}
              rows={2}
              className={clsx(inputCls, 'h-auto py-2')}
            />
          </WideModalField>
        </WideModalSection>
      )}
    </WideModal>
  );
}
