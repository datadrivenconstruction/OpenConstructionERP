import { useState, useMemo, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { useParams, useNavigate, useSearchParams } from 'react-router-dom';
import { useQuery, useQueries, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  AlertTriangle,
  ShieldAlert,
  ClipboardList,
  HardHat,
  FileCheck,
  Wrench,
  Users,
  X,
  Plus,
  Search,
  ShieldCheck,
  Clock,
  CheckCircle2,
  Download,
  CheckCircle,
  PlayCircle,
  PauseCircle,
  XCircle,
  Send,
  Archive,
  ArrowUpCircle,
  ListChecks,
  Trash2,
  ExternalLink,
} from 'lucide-react';
import {
  Button,
  Card,
  Badge,
  EmptyState,
  Breadcrumb,
  RecoveryCard,
  SkeletonTable,
  IntroRichText,
} from '@/shared/ui';
import { RequiresProject } from '@/shared/auth/RequiresProject';
import { DateDisplay } from '@/shared/ui/DateDisplay';
import { PageHeader } from '@/shared/ui/PageHeader';
import { SectionIntro } from '@/features/validation';
import { normalizeListResponse } from '@/shared/lib/apiHelpers';
import { getErrorMessage } from '@/shared/lib/api';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { useToastStore } from '@/stores/useToastStore';
import { useTabKeyboardNav } from '@/shared/hooks/useTabKeyboardNav';
import {
  fetchInvestigations,
  fetchJSAs,
  fetchPermits,
  fetchToolboxTalks,
  fetchPPEIssues,
  fetchAudits,
  fetchCAPAs,
  getKpi,
  createInvestigation,
  createJSA,
  createPermit,
  createToolboxTalk,
  createPPEIssue,
  createAudit,
  createCAPA,
  daysUntil,
  downloadOsha300Csv,
  fetchCorrectiveActions,
  transitionCorrectiveAction,
  submitJSA,
  approveJSA,
  activateJSA,
  archiveJSA,
  approvePermit,
  activatePermit,
  suspendPermit,
  closePermit,
  cancelPermit,
  updatePermitPrerequisites,
  fetchAuditFindings,
  createAuditFinding,
  deleteAuditFinding,
  completeAudit,
  completeCAPA,
  escalateCAPA,
  cancelCAPA,
  setCAPAFiveWhys,
  verifyCAPAEffectiveness,
  fetchSafetyIncidents,
  type SafetyIncidentOption,
  type IncidentInvestigation,
  type JobSafetyAnalysis,
  type PermitToWork,
  type ToolboxTalk,
  type PPEIssue,
  type SafetyAudit,
  type CorrectiveAction,
  type PermitStatus,
  type CAPAStatus,
  type CATargetStatus,
  type CorrectiveActionRow,
  type HSEKpi,
  type AuditFinding,
  type AuditFindingCategory,
  type AuditFindingSeverity,
  type RootCauseCategory,
  type FiveWhyStep,
  type PermitPrerequisites,
} from './api';

const HSE_TAB_IDS = [
  'incidents', 'jsa', 'permits', 'toolbox', 'ppe', 'audits', 'capa',
] as const;
type HSETab = (typeof HSE_TAB_IDS)[number];

type BadgeVariant = 'neutral' | 'blue' | 'success' | 'warning' | 'error';

// Permit status colours — keyed to the real backend FSM states
// (requested → approved → active → suspended → closed/cancelled; expired).
const PERMIT_STATUS_COLORS: Record<PermitStatus, BadgeVariant> = {
  requested: 'warning',
  approved: 'blue',
  active: 'success',
  suspended: 'warning',
  closed: 'neutral',
  cancelled: 'neutral',
  expired: 'error',
};

// CAPA status colours — keyed to the real backend enum
// (open | in_progress | completed | overdue | cancelled).
const CAPA_STATUS_COLORS: Record<CAPAStatus, BadgeVariant> = {
  open: 'warning',
  in_progress: 'blue',
  completed: 'success',
  overdue: 'error',
  cancelled: 'neutral',
};

const inputCls =
  'h-10 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';
const textareaCls =
  'w-full rounded-lg border border-border bg-surface-primary px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue resize-none';

/* ── Shared safety-incident picker ──────────────────────────────────────
 * Replaces the raw-UUID field on the investigation / CAPA-source flows with a
 * real dropdown of the project's safety incidents (the Safety module is the
 * system of record). The selected id becomes the investigation's incident_ref
 * or the CAPA's source_ref, so the new record links back to what raised it.
 */
function useSafetyIncidents(projectId: string, enabled = true) {
  return useQuery({
    queryKey: ['hse-safety-incidents', projectId],
    queryFn: () => fetchSafetyIncidents(projectId),
    select: (d) => normalizeListResponse<SafetyIncidentOption>(d),
    enabled: enabled && !!projectId,
    staleTime: 30_000,
  });
}

/** Human-readable one-line label for a safety incident option. */
function incidentOptionLabel(it: SafetyIncidentOption): string {
  const head = it.incident_number || it.id.slice(0, 8);
  const type = (it.incident_type || '').replace(/_/g, ' ');
  const date = it.incident_date ? ` · ${it.incident_date}` : '';
  return `${head}${type ? ` · ${type}` : ''}${date}`;
}

function SafetyIncidentPicker({
  projectId,
  value,
  onChange,
  required,
  emptyHint,
}: {
  projectId: string;
  value: string;
  onChange: (id: string) => void;
  required?: boolean;
  emptyHint?: string;
}) {
  const { t } = useTranslation();
  const { data, isLoading, isError } = useSafetyIncidents(projectId);
  const incidents = data ?? [];

  if (isError) {
    // Fall back to a free-text id field so the flow never dead-ends if the
    // Safety endpoint is unavailable.
    return (
      <input
        className={inputCls}
        value={value}
        placeholder={t('hse_advanced.incident_ref_placeholder', {
          defaultValue: 'UUID of the linked safety incident',
        })}
        onChange={(e) => onChange(e.target.value)}
      />
    );
  }

  if (!isLoading && incidents.length === 0) {
    return (
      <p className="text-sm text-content-tertiary">
        {emptyHint ??
          t('hse_advanced.no_incidents_to_link', {
            defaultValue:
              'No safety incidents recorded for this project yet. Report one in the Safety module first.',
          })}
      </p>
    );
  }

  return (
    <select
      className={inputCls}
      value={value}
      disabled={isLoading}
      onChange={(e) => onChange(e.target.value)}
    >
      <option value="">
        {required
          ? t('hse_advanced.select_incident_required', {
              defaultValue: 'Select an incident…',
            })
          : t('hse_advanced.select_incident_none', { defaultValue: 'No linked incident' })}
      </option>
      {incidents.map((it) => (
        <option key={it.id} value={it.id}>
          {incidentOptionLabel(it)}
        </option>
      ))}
    </select>
  );
}

/* CAPA source types that point at a concrete record we can pick + deep-link.
 * "observation" has no first-class register here, so it carries no source_ref. */
const CAPA_SOURCE_TYPES = ['observation', 'audit', 'incident', 'jsa', 'permit'] as const;

/** Route a CAPA source (type + ref) to the page that owns it. */
function capaSourceLink(sourceType: string, sourceRef: string): string | null {
  if (!sourceRef) return null;
  switch (sourceType) {
    case 'incident':
      return '/safety?tab=incidents';
    case 'jsa':
      return '/hse-advanced?tab=jsa';
    case 'permit':
      return '/hse-advanced?tab=permits';
    case 'audit':
      return '/hse-advanced?tab=audits';
    default:
      return null;
  }
}

/**
 * Dependent source-ref picker: for incident/jsa/permit/audit it shows the
 * matching project register so the CAPA links back to a real record instead of
 * a pasted UUID. "observation" needs no ref.
 */
function CapaSourceRefPicker({
  projectId,
  sourceType,
  value,
  onChange,
}: {
  projectId: string;
  sourceType: string;
  value: string;
  onChange: (id: string) => void;
}) {
  const { t } = useTranslation();

  // Each source type fetches its own register; only the active one is enabled
  // so we never over-fetch. Hooks stay unconditional (rule-of-hooks safe).
  const jsaQ = useQuery({
    queryKey: ['hse-jsas', projectId],
    queryFn: () => fetchJSAs(projectId),
    select: (d) => normalizeListResponse<JobSafetyAnalysis>(d),
    enabled: sourceType === 'jsa' && !!projectId,
    staleTime: 30_000,
  });
  const permitQ = useQuery({
    queryKey: ['hse-permits', projectId],
    queryFn: () => fetchPermits(projectId),
    select: (d) => normalizeListResponse<PermitToWork>(d),
    enabled: sourceType === 'permit' && !!projectId,
    staleTime: 30_000,
  });
  const auditQ = useQuery({
    queryKey: ['hse-audits', projectId],
    queryFn: () => fetchAudits(projectId),
    select: (d) => normalizeListResponse<SafetyAudit>(d),
    enabled: sourceType === 'audit' && !!projectId,
    staleTime: 30_000,
  });

  if (sourceType === 'observation') {
    return (
      <p className="text-xs text-content-tertiary">
        {t('hse_advanced.capa_no_source_ref', {
          defaultValue: 'Observations are recorded in the Safety module - no record to link here.',
        })}
      </p>
    );
  }

  if (sourceType === 'incident') {
    return (
      <SafetyIncidentPicker
        projectId={projectId}
        value={value}
        onChange={onChange}
        emptyHint={t('hse_advanced.no_incidents_to_link', {
          defaultValue:
            'No safety incidents recorded for this project yet. Report one in the Safety module first.',
        })}
      />
    );
  }

  const options: { id: string; label: string }[] =
    sourceType === 'jsa'
      ? (jsaQ.data ?? []).map((j) => ({
          id: j.id,
          label: j.task_description.slice(0, 60) || j.id.slice(0, 8),
        }))
      : sourceType === 'permit'
        ? (permitQ.data ?? []).map((p) => ({
            id: p.id,
            label: `${p.permit_number || p.id.slice(0, 8)} · ${p.permit_type.replace(/_/g, ' ')}`,
          }))
        : (auditQ.data ?? []).map((a) => ({
            id: a.id,
            label: `${a.audit_type.replace(/_/g, ' ')} · ${a.conducted_at.slice(0, 10)}`,
          }));

  const isLoading = jsaQ.isLoading || permitQ.isLoading || auditQ.isLoading;

  if (!isLoading && options.length === 0) {
    return (
      <p className="text-xs text-content-tertiary">
        {t('hse_advanced.capa_no_source_records', {
          defaultValue: 'No matching records for this source type yet.',
        })}
      </p>
    );
  }

  return (
    <select className={inputCls} value={value} disabled={isLoading} onChange={(e) => onChange(e.target.value)}>
      <option value="">
        {t('hse_advanced.capa_select_source', { defaultValue: 'No linked record' })}
      </option>
      {options.map((o) => (
        <option key={o.id} value={o.id}>
          {o.label}
        </option>
      ))}
    </select>
  );
}

/* ── Main Page ─────────────────────────────────────────────────────────── */

export function HSEAdvancedPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { projectId: routeProjectId } = useParams<{ projectId?: string }>();
  const activeProjectId = useProjectContextStore((s) => s.activeProjectId);
  const projectName = useProjectContextStore((s) => s.activeProjectName);
  const projectId = routeProjectId || activeProjectId || '';

  // Deep-link support: Safety's "Investigate" row action lands here with
  // ?tab=incidents&action=investigate&incident_id=<id> so the investigation
  // modal opens pre-filled. The tab param also lets any sibling jump straight
  // to a section. We read it once on mount, sync the tab, then strip the
  // params (replace) so a refresh / back-nav does not re-trigger the action.
  const [searchParams, setSearchParams] = useSearchParams();
  const tabParam = searchParams.get('tab');
  const initialTab: HSETab = HSE_TAB_IDS.includes(tabParam as HSETab)
    ? (tabParam as HSETab)
    : 'incidents';

  const [tab, setTab] = useState<HSETab>(initialTab);
  const [incidentDeepLink, setIncidentDeepLink] = useState<string | null>(() =>
    searchParams.get('action') === 'investigate'
      ? searchParams.get('incident_id') ?? ''
      : null,
  );

  useEffect(() => {
    if (!searchParams.get('action') && !searchParams.get('tab')) return;
    const next = new URLSearchParams(searchParams);
    next.delete('tab');
    next.delete('action');
    next.delete('incident_id');
    setSearchParams(next, { replace: true });
    // Run once after mount — the captured initial state above drives behaviour.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const onTabKeyDown = useTabKeyboardNav<HSETab>({
    ids: HSE_TAB_IDS,
    activeId: tab,
    onChange: setTab,
    orientation: 'horizontal',
  });

  const tabs: { key: HSETab; label: string; icon: React.ReactNode }[] = [
    {
      key: 'incidents',
      label: t('hse_advanced.tab_incidents', { defaultValue: 'Incidents' }),
      icon: <ShieldAlert size={15} />,
    },
    {
      key: 'jsa',
      label: t('hse_advanced.tab_jsa', { defaultValue: 'JSAs' }),
      icon: <ClipboardList size={15} />,
    },
    {
      key: 'permits',
      label: t('hse_advanced.tab_permits', { defaultValue: 'Permits' }),
      icon: <FileCheck size={15} />,
    },
    {
      key: 'toolbox',
      label: t('hse_advanced.tab_toolbox', { defaultValue: 'Toolbox' }),
      icon: <Users size={15} />,
    },
    {
      key: 'ppe',
      label: t('hse_advanced.tab_ppe', { defaultValue: 'PPE' }),
      icon: <HardHat size={15} />,
    },
    {
      key: 'audits',
      label: t('hse_advanced.tab_audits', { defaultValue: 'Audits' }),
      icon: <ShieldCheck size={15} />,
    },
    {
      key: 'capa',
      label: t('hse_advanced.tab_capa', { defaultValue: 'CAPA' }),
      icon: <Wrench size={15} />,
    },
  ];

  return (
    <div className="space-y-5 animate-fade-in">
      <Breadcrumb
        items={[
          ...(projectName ? [{ label: projectName, to: `/projects/${projectId}` }] : []),
          { label: t('nav.hse_advanced', { defaultValue: 'HSE Advanced' }) },
        ]}
      />

      <PageHeader
        srTitle={t('hse_advanced.title', { defaultValue: 'HSE Advanced' })}
        subtitle={t('hse_advanced.subtitle', {
          defaultValue:
            'Investigate incidents, run JSAs, manage permits, deliver toolbox talks, issue PPE, audit the site and close CAPAs.',
        })}
        actions={projectId && <Osha300Download projectId={projectId} />}
      />

      <SectionIntro
        storageKey="hse_advanced"
        title={t('hse_advanced.intro_title', {
          defaultValue: 'Close out every safety finding, not just log it',
        })}
        more={
          <IntroRichText
            text={t('hse_advanced.intro_more', {
              defaultValue:
                'Logging a safety incident is the easy part. The hard part, and the part regulators and clients actually check, is showing that every finding was investigated, that high-risk tasks were planned before they started, that permits were properly issued, and that corrective actions were closed and stayed closed. This is the formal HSE workspace that carries a finding from "something happened" all the way to "fixed and verified", with the paper trail that an audit or an insurance claim needs.\n\n**You put in:**\n- Incident investigations opened from a Safety incident, using 5-Whys, fishbone, timeline or SWOT\n- Job Safety Analyses (JSA) that break a task into steps, name the hazards and list the controls\n- Permits to work (hot work, confined space and the like) with their prerequisites and work window\n- Toolbox talks, PPE issue records, site safety audits with findings, and corrective/preventive actions\n\n**You get out:**\n- A KPI strip across the top: open investigations, overdue CAPAs, active permits and days since the last lost-time incident\n- JSAs and permits driven through real approval states, so nothing goes active without the right sign-off\n- A CAPA register that tracks every action to completion and flags anything overdue\n- An OSHA 300 incident log you can export to CSV for the required five-year retention\n\n**How it works day to day:**\n1. When a Safety incident needs more than a log entry, open an investigation and work the root cause.\n2. Before high-risk work starts, raise a JSA and walk it from draft through review and approval to active.\n3. Issue the permit to work, confirm its prerequisites, and suspend or close it as conditions change.\n4. Record toolbox talks and PPE issues, and run audits that generate findings.\n5. Turn findings into CAPAs, assign and verify them, and watch the KPI strip drive the overdue count to zero.\n\nThis page is the formal counterpart to the day-to-day Safety module: incidents and observations are captured there, and the serious ones are escalated here for investigation and corrective action. The days-since-LTI figure is computed from the same safety data, so both views stay in agreement.',
            })}
          />
        }
        links={[
          {
            label: t('hse_advanced.intro_link_safety', { defaultValue: 'Safety' }),
            onClick: () => navigate('/safety'),
          },
        ]}
      >
        {t('hse_advanced.intro_body', {
          defaultValue:
            'This is the formal side of site safety: open a 5-Whys investigation off a Safety incident, run Job Safety Analyses and permits-to-work through their approval states, record toolbox talks and PPE issues, audit the site, and track corrective and preventive actions to close-out. Findings feed the KPI strip (open investigations, overdue CAPAs, active permits, days since LTI) and export to an OSHA 300 log.',
        })}
      </SectionIntro>

      {projectId && <HSEKpiStrip projectId={projectId} />}

      <RequiresProject
        emptyHint={t('hse_advanced.no_project_desc', {
          defaultValue:
            'Pick a project from the header to manage advanced HSE records: investigations, permits, audits and corrective actions.',
        })}
      >
        <div
          className="flex items-center gap-1 mb-5 border-b border-border-light overflow-x-auto"
          role="tablist"
          aria-label={t('hse_advanced.tabs_aria', {
            defaultValue: 'HSE advanced sections',
          })}
          onKeyDown={onTabKeyDown}
        >
          {tabs.map((tb) => {
            const isActive = tab === tb.key;
            return (
              <button
                key={tb.key}
                role="tab"
                id={`hse-tab-${tb.key}`}
                aria-selected={isActive}
                aria-controls={`hse-panel-${tb.key}`}
                tabIndex={isActive ? 0 : -1}
                onClick={() => setTab(tb.key)}
                className={`flex items-center gap-2 px-4 py-2.5 text-sm font-medium border-b-2 transition-all whitespace-nowrap ${
                  isActive
                    ? 'border-oe-blue text-oe-blue'
                    : 'border-transparent text-content-tertiary hover:text-content-primary hover:bg-surface-secondary'
                }`}
              >
                {tb.icon}
                {tb.label}
              </button>
            );
          })}
        </div>

        <div
          role="tabpanel"
          id={`hse-panel-${tab}`}
          aria-labelledby={`hse-tab-${tab}`}
        >
          {tab === 'incidents' && (
            <IncidentsTab
              projectId={projectId}
              initialInvestigateIncidentId={incidentDeepLink}
              onConsumeDeepLink={() => setIncidentDeepLink(null)}
            />
          )}
          {tab === 'jsa' && <JSATab projectId={projectId} />}
          {tab === 'permits' && <PermitsTab projectId={projectId} />}
          {tab === 'toolbox' && <ToolboxTab projectId={projectId} />}
          {tab === 'ppe' && <PPETab projectId={projectId} />}
          {tab === 'audits' && <AuditsTab projectId={projectId} />}
          {tab === 'capa' && <CAPATab projectId={projectId} />}
        </div>
      </RequiresProject>
    </div>
  );
}

/* ── Search Bar ──────────────────────────────────────────────────────── */

function SearchBar({
  value,
  onChange,
  placeholder,
  onCreate,
  createLabel,
}: {
  value: string;
  onChange: (v: string) => void;
  placeholder: string;
  onCreate: () => void;
  createLabel: string;
}) {
  return (
    <div className="p-4 border-b border-border-light flex items-center gap-3 flex-wrap">
      <div className="relative max-w-sm flex-1">
        <div className="pointer-events-none absolute inset-y-0 left-0 flex items-center pl-3 text-content-tertiary">
          <Search size={16} />
        </div>
        <input
          type="text"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder}
          aria-label={placeholder}
          className="h-10 w-full rounded-lg border border-border bg-surface-primary pl-10 pr-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue"
        />
      </div>
      <Button variant="primary" size="sm" icon={<Plus size={14} />} onClick={onCreate}>
        {createLabel}
      </Button>
    </div>
  );
}

/* ── Filter Chips ────────────────────────────────────────────────────── */

function FilterChips<T extends string>({
  value,
  options,
  onChange,
}: {
  value: T;
  options: { value: T; label: string; count?: number }[];
  onChange: (v: T) => void;
}) {
  return (
    <div className="flex items-center gap-2 flex-wrap">
      {options.map((opt) => (
        <button
          key={opt.value}
          type="button"
          onClick={() => onChange(opt.value)}
          className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-medium transition-colors ${
            value === opt.value
              ? 'border-oe-blue bg-oe-blue-subtle text-oe-blue-text'
              : 'border-border bg-surface-primary text-content-secondary hover:bg-surface-secondary'
          }`}
        >
          <span>{opt.label}</span>
          {opt.count !== undefined && (
            <span className="text-2xs text-content-tertiary">{opt.count}</span>
          )}
        </button>
      ))}
    </div>
  );
}

/* ── OSHA Form 300 CSV download ─────────────────────────────────────── */

/**
 * Renders the year selector + download button that triggers an OSHA 300
 * incident-log CSV export. Surfaces high in the page header so it is one
 * click away from any tab — matches Procore / Sphera placement.
 */
function Osha300Download({ projectId }: { projectId: string }) {
  const { t } = useTranslation();
  const currentYear = new Date().getFullYear();
  const [year, setYear] = useState(currentYear);
  const addToast = useToastStore((s) => s.addToast);

  // Six-year window — OSHA 1904.33 requires five years of retention; we
  // give one extra leading year so mid-January exports of the prior year
  // are always available.
  const years = useMemo(() => {
    const out: number[] = [];
    for (let y = currentYear; y >= currentYear - 5; y -= 1) {
      out.push(y);
    }
    return out;
  }, [currentYear]);

  return (
    <div className="flex items-center gap-2 shrink-0">
      <label
        htmlFor="osha-300-year"
        className="text-xs font-medium text-content-tertiary"
      >
        {t('hse.advanced.osha_year_label', { defaultValue: 'Year' })}
      </label>
      <select
        id="osha-300-year"
        value={year}
        onChange={(e) => setYear(Number.parseInt(e.target.value, 10))}
        className="h-9 rounded-lg border border-border bg-surface-primary px-2 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue"
        aria-label={t('hse.advanced.osha_year_label', { defaultValue: 'Year' })}
      >
        {years.map((y) => (
          <option key={y} value={y}>
            {y}
          </option>
        ))}
      </select>
      <Button
        variant="secondary"
        size="sm"
        icon={<Download size={14} />}
        onClick={() => {
          try {
            downloadOsha300Csv(projectId, year);
            addToast({
              type: 'success',
              title: t('hse.advanced.osha_download_started', {
                defaultValue: 'OSHA 300 CSV download started',
              }),
            });
          } catch (err) {
            addToast({
              type: 'error',
              title: t('hse.advanced.osha_download_failed', {
                defaultValue: 'Could not start OSHA 300 download',
              }),
              message: getErrorMessage(err),
            });
          }
        }}
      >
        {t('hse.advanced.download_osha_300', {
          defaultValue: 'Download OSHA 300 (CSV)',
        })}
      </Button>
    </div>
  );
}

/* ── HSE KPI Strip ────────────────────────────────────────────────────── */

/**
 * Top-of-page KPI strip — four mini-cards giving HSE managers instant
 * site-health context before they pick a tab. All counts come from the
 * existing module endpoints; no new backend needed. ``useQueries``
 * deliberately runs the fetches in parallel — hook-rule-safe per the
 * v4.5.0 propdev decision (memory: useQueries for hook safety).
 *
 *  - Open Investigations: status != completed/abandoned (backend statuses are
 *                         in_progress | completed | abandoned)
 *  - Overdue CAPAs:       target_date < today AND not completed/cancelled
 *  - Active Permits:      status === 'active'
 *  - Days Since LTI:      read straight off the KPI endpoint's
 *                         days_without_lti (computed server-side from the
 *                         safety module's lost-time incidents). The
 *                         investigation record no longer carries
 *                         severity/incident_date, so we no longer try to
 *                         re-derive this on the client.
 *
 * Severity-tinted backgrounds drive at-a-glance reading:
 *  - red       when overdue CAPAs > 0 or days-since-LTI < 7
 *  - amber     when days-since-LTI < 30
 *  - emerald   when ≥ 30 days
 *  - neutral   when no data
 */
function HSEKpiStrip({ projectId }: { projectId: string }) {
  const { t } = useTranslation();
  const results = useQueries({
    queries: [
      {
        queryKey: ['hse-kpi-investigations', projectId],
        queryFn: () => fetchInvestigations(projectId),
        select: (d: unknown) => normalizeListResponse<IncidentInvestigation>(d as IncidentInvestigation[] | { items: IncidentInvestigation[] } | null | undefined),
        staleTime: 30_000,
      },
      {
        queryKey: ['hse-kpi-capas', projectId],
        queryFn: () => fetchCAPAs(projectId),
        select: (d: unknown) => normalizeListResponse<CorrectiveAction>(d as CorrectiveAction[] | { items: CorrectiveAction[] } | null | undefined),
        staleTime: 30_000,
      },
      {
        queryKey: ['hse-kpi-permits', projectId],
        queryFn: () => fetchPermits(projectId),
        select: (d: unknown) => normalizeListResponse<PermitToWork>(d as PermitToWork[] | { items: PermitToWork[] } | null | undefined),
        staleTime: 30_000,
      },
      {
        queryKey: ['hse-kpi-summary', projectId],
        queryFn: () => getKpi(projectId),
        staleTime: 30_000,
      },
    ],
  });

  const [invQ, capaQ, permQ, kpiQ] = results;
  const isLoading = results.some((r) => r.isLoading);
  // The list queries gate the strip; a KPI-summary failure only blanks the
  // LTI card (days-since-LTI shows "No record") rather than hiding the strip.
  const isError = invQ.isError || capaQ.isError || permQ.isError;

  const stats = useMemo(() => {
    const investigations = (invQ.data ?? []) as IncidentInvestigation[];
    const capas = (capaQ.data ?? []) as CorrectiveAction[];
    const permits = (permQ.data ?? []) as PermitToWork[];
    const kpi = kpiQ.data as HSEKpi | undefined;

    // Investigation statuses are in_progress | completed | abandoned — both
    // completed and abandoned count as closed.
    const openInvestigations = investigations.filter(
      (it) => it.status !== 'completed' && it.status !== 'abandoned',
    ).length;

    const today = new Date();
    today.setHours(0, 0, 0, 0);
    const overdueCapas = capas.filter((c) => {
      if (c.status === 'completed' || c.status === 'cancelled') {
        return false;
      }
      // Backend CAPA field is target_date (not due_date).
      if (!c.target_date) return false;
      const due = new Date(c.target_date);
      if (Number.isNaN(due.getTime())) return false;
      due.setHours(0, 0, 0, 0);
      return due.getTime() < today.getTime();
    }).length;

    const activePermits = permits.filter((p) => p.status === 'active').length;

    // Days-since-LTI comes from the server-computed KPI; null when no LTI.
    const daysSinceLti: number | null = kpi?.days_without_lti ?? null;

    return { openInvestigations, overdueCapas, activePermits, daysSinceLti };
  }, [invQ.data, capaQ.data, permQ.data, kpiQ.data]);

  if (isError) {
    // Don't block the page on KPI failure — just hide the strip silently
    // and let the user fall back to the tabs.
    return null;
  }

  const ltiTone: KpiTone =
    stats.daysSinceLti === null
      ? 'neutral'
      : stats.daysSinceLti < 7
        ? 'error'
        : stats.daysSinceLti < 30
          ? 'warning'
          : 'success';

  const capaTone: KpiTone = stats.overdueCapas === 0 ? 'success' : 'error';

  return (
    <div
      className="grid grid-cols-2 md:grid-cols-4 gap-3"
      data-testid="hse-kpi-strip"
      aria-label={t('hse_advanced.kpi_aria', { defaultValue: 'HSE key indicators' })}
    >
      <KpiCard
        label={t('hse_advanced.kpi_open_investigations', {
          defaultValue: 'Open investigations',
        })}
        value={isLoading ? '—' : stats.openInvestigations}
        icon={<ShieldAlert size={16} />}
        tone={stats.openInvestigations > 0 ? 'warning' : 'neutral'}
        testId="hse-kpi-open-investigations"
      />
      <KpiCard
        label={t('hse_advanced.kpi_overdue_capas', { defaultValue: 'Overdue CAPAs' })}
        value={isLoading ? '—' : stats.overdueCapas}
        icon={<Wrench size={16} />}
        tone={capaTone}
        testId="hse-kpi-overdue-capas"
      />
      <KpiCard
        label={t('hse_advanced.kpi_active_permits', { defaultValue: 'Active permits' })}
        value={isLoading ? '—' : stats.activePermits}
        icon={<FileCheck size={16} />}
        tone={stats.activePermits > 0 ? 'blue' : 'neutral'}
        testId="hse-kpi-active-permits"
      />
      <KpiCard
        label={t('hse_advanced.kpi_days_since_lti', {
          defaultValue: 'Days since LTI',
        })}
        value={
          isLoading
            ? '—'
            : stats.daysSinceLti === null
              ? t('hse_advanced.kpi_no_lti', { defaultValue: 'No record' })
              : stats.daysSinceLti
        }
        icon={<Clock size={16} />}
        tone={ltiTone}
        testId="hse-kpi-days-since-lti"
      />
    </div>
  );
}

type KpiTone = 'success' | 'warning' | 'error' | 'blue' | 'neutral';

function KpiCard({
  label,
  value,
  icon,
  tone,
  testId,
}: {
  label: string;
  value: number | string;
  icon: React.ReactNode;
  tone: KpiTone;
  testId: string;
}) {
  // Soft tints — match the project's badge palette so the cards never
  // overpower the table data they sit above.
  const toneCls: Record<KpiTone, string> = {
    success: 'border-semantic-success/30 bg-semantic-success/5 text-semantic-success',
    warning: 'border-amber-500/30 bg-amber-50 text-amber-700',
    error: 'border-semantic-error/30 bg-semantic-error/5 text-semantic-error',
    blue: 'border-oe-blue/30 bg-oe-blue-subtle text-oe-blue-text',
    neutral: 'border-border bg-surface-secondary text-content-tertiary',
  };
  return (
    <div
      className={`rounded-xl border px-4 py-3 transition-colors ${toneCls[tone]}`}
      data-testid={testId}
    >
      <div className="flex items-center justify-between">
        <span className="text-xs font-medium opacity-80">{label}</span>
        <span className="opacity-70">{icon}</span>
      </div>
      <div className="mt-1 text-lg font-semibold tabular-nums">{value}</div>
    </div>
  );
}

/* ── Modal Shell ─────────────────────────────────────────────────────── */

function ModalShell({
  title,
  onClose,
  children,
  footer,
  size = 'max-w-2xl',
}: {
  title: string;
  onClose: () => void;
  children: React.ReactNode;
  footer: React.ReactNode;
  size?: string;
}) {
  const { t } = useTranslation();

  // Escape-to-close — standard accessible-dialog behaviour.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onClose]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-lg animate-fade-in"
      onClick={onClose}
    >
      <div
        className={`w-full ${size} bg-surface-elevated rounded-xl shadow-xl border border-border animate-card-in mx-4 max-h-[90vh] overflow-y-auto`}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-6 py-4 border-b border-border-light">
          <h2 className="text-lg font-semibold text-content-primary">{title}</h2>
          <button
            onClick={onClose}
            aria-label={t('common.close', { defaultValue: 'Close' })}
            className="flex h-8 w-8 items-center justify-center rounded-lg text-content-tertiary hover:bg-surface-secondary hover:text-content-primary transition-colors"
          >
            <X size={18} />
          </button>
        </div>
        <div className="px-6 py-4 space-y-4">{children}</div>
        <div className="flex items-center justify-end gap-3 px-6 py-4 border-t border-border-light">
          {footer}
        </div>
      </div>
    </div>
  );
}

/* ── Incidents Tab ───────────────────────────────────────────────────── */

function IncidentsTab({
  projectId,
  initialInvestigateIncidentId,
  onConsumeDeepLink,
}: {
  projectId: string;
  /** When set (from a Safety "Investigate" deep-link), open the create modal
   *  pre-filled with this incident id. null means no deep-link. */
  initialInvestigateIncidentId?: string | null;
  onConsumeDeepLink?: () => void;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [search, setSearch] = useState('');
  const [showCreate, setShowCreate] = useState(false);
  const [detail, setDetail] = useState<IncidentInvestigation | null>(null);
  // InvestigationCreate requires incident_ref (UUID of the linked safety
  // incident) + started_at; method/findings are optional with defaults.
  const [form, setForm] = useState({
    incident_ref: '',
    started_at: new Date().toISOString().slice(0, 10),
    method: '5_whys' as IncidentInvestigation['method'],
    findings: '',
  });

  // Honour a one-shot deep link from Safety: open the modal pre-filled, then
  // tell the parent to drop the captured id so it fires only once.
  useEffect(() => {
    if (initialInvestigateIncidentId == null) return;
    setForm((f) => ({ ...f, incident_ref: initialInvestigateIncidentId }));
    setShowCreate(true);
    onConsumeDeepLink?.();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialInvestigateIncidentId]);

  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ['hse-investigations', projectId],
    queryFn: () => fetchInvestigations(projectId),
    select: (d) => normalizeListResponse<IncidentInvestigation>(d),
  });

  const createMut = useMutation({
    mutationFn: () =>
      createInvestigation({
        incident_ref: form.incident_ref.trim(),
        // The date input gives YYYY-MM-DD; widen to an ISO datetime the
        // backend's started_at: datetime accepts.
        started_at: new Date(form.started_at).toISOString(),
        method: form.method,
        findings: form.findings || undefined,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['hse-investigations', projectId] });
      setShowCreate(false);
      setForm({
        incident_ref: '',
        started_at: new Date().toISOString().slice(0, 10),
        method: '5_whys',
        findings: '',
      });
      addToast({
        type: 'success',
        title: t('hse_advanced.investigation_created', {
          defaultValue: 'Investigation opened',
        }),
      });
    },
    onError: (e) =>
      addToast({
        type: 'error',
        title: t('hse_advanced.investigation_failed', {
          defaultValue: 'Failed to open investigation',
        }),
        message: getErrorMessage(e),
      }),
  });

  const filtered = useMemo(() => {
    if (!data) return [];
    if (!search) return data;
    const q = search.toLowerCase();
    return data.filter(
      (it) =>
        it.incident_ref.toLowerCase().includes(q) ||
        it.findings.toLowerCase().includes(q),
    );
  }, [data, search]);

  if (isLoading) return <SkeletonTable rows={5} columns={6} />;

  if (isError) {
    return (
      <Card className="py-12">
        <RecoveryCard error={error} onRetry={() => refetch()} />
      </Card>
    );
  }

  if (!data || data.length === 0) {
    return (
      <EmptyState
        icon={<ShieldAlert size={28} strokeWidth={1.5} />}
        title={t('hse_advanced.no_investigations', {
          defaultValue: 'No investigations yet',
        })}
        description={t('hse_advanced.no_investigations_desc', {
          defaultValue:
            'Open a formal investigation when an incident requires 5-Whys analysis, root-cause review, and corrective actions.',
        })}
        action={{
          label: t('hse_advanced.open_investigation', { defaultValue: 'Open Investigation' }),
          onClick: () => setShowCreate(true),
        }}
      />
    );
  }

  return (
    <>
      <Card padding="none">
        <SearchBar
          value={search}
          onChange={setSearch}
          placeholder={t('hse_advanced.search_investigations', {
            defaultValue: 'Search investigations...',
          })}
          onCreate={() => setShowCreate(true)}
          createLabel={t('hse_advanced.open_investigation', {
            defaultValue: 'Open Investigation',
          })}
        />
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border-light bg-surface-secondary/50">
                <th className="px-4 py-3 text-left font-medium text-content-tertiary">
                  {t('hse_advanced.incident_ref', { defaultValue: 'Incident ref' })}
                </th>
                <th className="px-4 py-3 text-left font-medium text-content-tertiary">
                  {t('hse_advanced.method', { defaultValue: 'Method' })}
                </th>
                <th className="px-4 py-3 text-left font-medium text-content-tertiary">
                  {t('hse_advanced.started_at', { defaultValue: 'Started' })}
                </th>
                <th className="px-4 py-3 text-center font-medium text-content-tertiary">
                  {t('common.status', { defaultValue: 'Status' })}
                </th>
                <th className="px-4 py-3 text-left font-medium text-content-tertiary">
                  {t('hse_advanced.lead', { defaultValue: 'Lead' })}
                </th>
              </tr>
            </thead>
            <tbody>
              {filtered.length === 0 ? (
                <tr>
                  <td colSpan={5} className="px-4 py-8 text-center text-sm text-content-tertiary">
                    {t('hse_advanced.no_matches', { defaultValue: 'No matches' })}
                  </td>
                </tr>
              ) : (
                filtered.map((it) => (
                  <tr
                    key={it.id}
                    className="border-b border-border-light hover:bg-surface-secondary/30 cursor-pointer transition-colors"
                    onClick={() => setDetail(it)}
                  >
                    <td className="px-4 py-3 font-mono text-xs text-content-primary">
                      {it.incident_ref}
                    </td>
                    <td className="px-4 py-3 text-content-secondary">
                      {t(`hse_advanced.method_${it.method}`, {
                        defaultValue: it.method.replace(/_/g, ' '),
                      })}
                    </td>
                    <td className="px-4 py-3 text-content-secondary">
                      <DateDisplay value={it.started_at} />
                    </td>
                    <td className="px-4 py-3 text-center">
                      <Badge
                        variant={it.status === 'completed' ? 'success' : 'blue'}
                        size="sm"
                      >
                        {t(`hse_advanced.invest_status_${it.status}`, {
                          defaultValue: it.status.replace(/_/g, ' '),
                        })}
                      </Badge>
                    </td>
                    <td className="px-4 py-3 text-content-secondary text-xs font-mono">
                      {it.investigation_lead ?? '—'}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </Card>

      {showCreate && (
        <ModalShell
          title={t('hse_advanced.open_investigation', { defaultValue: 'Open Investigation' })}
          onClose={() => setShowCreate(false)}
          footer={
            <>
              <Button variant="ghost" onClick={() => setShowCreate(false)}>
                {t('common.cancel', { defaultValue: 'Cancel' })}
              </Button>
              <Button
                variant="primary"
                disabled={!form.incident_ref.trim() || createMut.isPending}
                onClick={() => createMut.mutate()}
              >
                {t('common.create', { defaultValue: 'Create' })}
              </Button>
            </>
          }
        >
          <div>
            <label className="block text-sm font-medium text-content-primary mb-1.5">
              {t('hse_advanced.incident_ref', { defaultValue: 'Linked safety incident' })}{' '}
              <span className="text-semantic-error">*</span>
            </label>
            <SafetyIncidentPicker
              projectId={projectId}
              value={form.incident_ref}
              required
              onChange={(id) => setForm((f) => ({ ...f, incident_ref: id }))}
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-content-primary mb-1.5">
              {t('hse_advanced.started_at', { defaultValue: 'Started' })}
            </label>
            <input
              type="date"
              className={inputCls}
              value={form.started_at}
              onChange={(e) => setForm((f) => ({ ...f, started_at: e.target.value }))}
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-content-primary mb-1.5">
              {t('hse_advanced.method', { defaultValue: 'Method' })}
            </label>
            <select
              className={inputCls}
              value={form.method}
              onChange={(e) =>
                setForm((f) => ({
                  ...f,
                  method: e.target.value as IncidentInvestigation['method'],
                }))
              }
            >
              <option value="5_whys">
                {t('hse_advanced.method_5_whys', { defaultValue: '5 Whys' })}
              </option>
              <option value="fishbone">
                {t('hse_advanced.method_fishbone', { defaultValue: 'Fishbone' })}
              </option>
              <option value="timeline">
                {t('hse_advanced.method_timeline', { defaultValue: 'Timeline' })}
              </option>
              <option value="swot">
                {t('hse_advanced.method_swot', { defaultValue: 'SWOT' })}
              </option>
            </select>
          </div>
          <div>
            <label className="block text-sm font-medium text-content-primary mb-1.5">
              {t('hse_advanced.findings', { defaultValue: 'Findings' })}
            </label>
            <textarea
              rows={3}
              className={textareaCls}
              value={form.findings}
              onChange={(e) => setForm((f) => ({ ...f, findings: e.target.value }))}
            />
          </div>
        </ModalShell>
      )}

      {detail && <IncidentDetailDrawer item={detail} onClose={() => setDetail(null)} />}
    </>
  );
}

/* ── Incident Detail Drawer ──────────────────────────────────────────── */

function IncidentDetailDrawer({
  item,
  onClose,
}: {
  item: IncidentInvestigation;
  onClose: () => void;
}) {
  const { t } = useTranslation();

  return (
    <ModalShell
      title={`${t('hse_advanced.investigation', { defaultValue: 'Investigation' })} - ${item.incident_ref}`}
      onClose={onClose}
      size="max-w-3xl"
      footer={
        <Button variant="ghost" onClick={onClose}>
          {t('common.close', { defaultValue: 'Close' })}
        </Button>
      }
    >
      <div className="grid grid-cols-2 gap-3 text-sm">
        <div>
          <div className="text-xs text-content-tertiary uppercase">
            {t('hse_advanced.method', { defaultValue: 'Method' })}
          </div>
          <div className="text-content-primary">
            {t(`hse_advanced.method_${item.method}`, {
              defaultValue: item.method.replace(/_/g, ' '),
            })}
          </div>
        </div>
        <div>
          <div className="text-xs text-content-tertiary uppercase">
            {t('common.status', { defaultValue: 'Status' })}
          </div>
          <Badge variant={item.status === 'completed' ? 'success' : 'blue'} size="sm">
            {t(`hse_advanced.invest_status_${item.status}`, {
              defaultValue: item.status.replace(/_/g, ' '),
            })}
          </Badge>
        </div>
        <div>
          <div className="text-xs text-content-tertiary uppercase">
            {t('hse_advanced.started_at', { defaultValue: 'Started' })}
          </div>
          <div className="text-content-secondary">
            <DateDisplay value={item.started_at} />
          </div>
        </div>
        <div>
          <div className="text-xs text-content-tertiary uppercase">
            {t('hse_advanced.completed_at', { defaultValue: 'Completed' })}
          </div>
          <div className="text-content-secondary">
            {item.completed_at ? (
              <DateDisplay value={item.completed_at} />
            ) : (
              t('common.not_set', { defaultValue: 'Not set' })
            )}
          </div>
        </div>
      </div>

      <div>
        <div className="text-xs font-semibold uppercase tracking-wider text-content-tertiary mb-1">
          {t('hse_advanced.investigation_lead', { defaultValue: 'Investigation lead' })}
        </div>
        <p className="text-sm text-content-secondary font-mono">
          {item.investigation_lead || t('common.not_set', { defaultValue: 'Not set' })}
        </p>
      </div>

      <div>
        <div className="text-xs font-semibold uppercase tracking-wider text-content-tertiary mb-1">
          {t('hse_advanced.findings', { defaultValue: 'Findings' })}
        </div>
        <p className="text-sm text-content-secondary whitespace-pre-wrap">
          {item.findings || t('hse_advanced.no_findings', { defaultValue: 'No findings recorded.' })}
        </p>
      </div>

      <div>
        <div className="text-xs font-semibold uppercase tracking-wider text-content-tertiary mb-1">
          {t('hse_advanced.recommendations', { defaultValue: 'Recommendations' })}
        </div>
        <p className="text-sm text-content-secondary whitespace-pre-wrap">
          {item.recommendations ||
            t('hse_advanced.no_recommendations', { defaultValue: 'No recommendations recorded.' })}
        </p>
      </div>

      {item.report_url && (
        <div>
          <div className="text-xs font-semibold uppercase tracking-wider text-content-tertiary mb-1">
            {t('hse_advanced.report', { defaultValue: 'Report' })}
          </div>
          <a
            href={item.report_url}
            target="_blank"
            rel="noopener noreferrer"
            className="text-sm text-oe-blue-text underline break-all"
          >
            {item.report_url}
          </a>
        </div>
      )}
    </ModalShell>
  );
}

/* ── JSA Tab ─────────────────────────────────────────────────────────── */

function JSATab({ projectId }: { projectId: string }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [search, setSearch] = useState('');
  const [showCreate, setShowCreate] = useState(false);
  const [detail, setDetail] = useState<JobSafetyAnalysis | null>(null);
  // JSACreate requires project_id + task_description + work_date.
  const [form, setForm] = useState({
    task_description: '',
    work_date: new Date().toISOString().slice(0, 10),
    location: '',
  });

  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ['hse-jsas', projectId],
    queryFn: () => fetchJSAs(projectId),
    select: (d) => normalizeListResponse<JobSafetyAnalysis>(d),
  });

  const createMut = useMutation({
    mutationFn: () =>
      createJSA({
        project_id: projectId,
        task_description: form.task_description,
        work_date: form.work_date,
        location: form.location || undefined,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['hse-jsas', projectId] });
      setShowCreate(false);
      setForm({
        task_description: '',
        work_date: new Date().toISOString().slice(0, 10),
        location: '',
      });
      addToast({
        type: 'success',
        title: t('hse_advanced.jsa_created', { defaultValue: 'JSA created' }),
      });
    },
    onError: (e) =>
      addToast({
        type: 'error',
        title: t('hse_advanced.jsa_failed', { defaultValue: 'Failed to create JSA' }),
        message: getErrorMessage(e),
      }),
  });

  const filtered = useMemo(() => {
    if (!data) return [];
    if (!search) return data;
    const q = search.toLowerCase();
    return data.filter((it) => it.task_description.toLowerCase().includes(q));
  }, [data, search]);

  if (isLoading) return <SkeletonTable rows={5} columns={5} />;
  if (isError) {
    return (
      <Card className="py-12">
        <RecoveryCard error={error} onRetry={() => refetch()} />
      </Card>
    );
  }
  if (!data || data.length === 0) {
    return (
      <EmptyState
        icon={<ClipboardList size={28} strokeWidth={1.5} />}
        title={t('hse_advanced.no_jsas', { defaultValue: 'No JSAs yet' })}
        description={t('hse_advanced.no_jsas_desc', {
          defaultValue:
            'A Job Safety Analysis breaks a task into steps, identifies hazards per step, and lists controls. Create one before high-risk work begins.',
        })}
        action={{
          label: t('hse_advanced.new_jsa', { defaultValue: 'New JSA' }),
          onClick: () => setShowCreate(true),
        }}
      />
    );
  }

  return (
    <>
      <Card padding="none">
        <SearchBar
          value={search}
          onChange={setSearch}
          placeholder={t('hse_advanced.search_jsas', { defaultValue: 'Search JSAs...' })}
          onCreate={() => setShowCreate(true)}
          createLabel={t('hse_advanced.new_jsa', { defaultValue: 'New JSA' })}
        />
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border-light bg-surface-secondary/50">
                <th className="px-4 py-3 text-left font-medium text-content-tertiary">
                  {t('hse_advanced.task_description', { defaultValue: 'Task' })}
                </th>
                <th className="px-4 py-3 text-left font-medium text-content-tertiary">
                  {t('hse_advanced.location', { defaultValue: 'Location' })}
                </th>
                <th className="px-4 py-3 text-left font-medium text-content-tertiary">
                  {t('hse_advanced.work_date', { defaultValue: 'Work date' })}
                </th>
                <th className="px-4 py-3 text-center font-medium text-content-tertiary">
                  {t('hse_advanced.risk_score', { defaultValue: 'Risk' })}
                </th>
                <th className="px-4 py-3 text-center font-medium text-content-tertiary">
                  {t('common.status', { defaultValue: 'Status' })}
                </th>
              </tr>
            </thead>
            <tbody>
              {filtered.length === 0 ? (
                <tr>
                  <td colSpan={5} className="px-4 py-8 text-center text-sm text-content-tertiary">
                    {t('hse_advanced.no_matches', { defaultValue: 'No matches' })}
                  </td>
                </tr>
              ) : (
                filtered.map((it) => (
                  <tr
                    key={it.id}
                    className="border-b border-border-light hover:bg-surface-secondary/30 cursor-pointer transition-colors"
                    onClick={() => setDetail(it)}
                  >
                    <td className="px-4 py-3 text-content-primary max-w-[24rem] truncate">
                      {it.task_description}
                    </td>
                    <td className="px-4 py-3 text-content-secondary">{it.location ?? '—'}</td>
                    <td className="px-4 py-3 text-content-secondary">
                      <DateDisplay value={it.work_date} />
                    </td>
                    <td className="px-4 py-3 text-center tabular-nums">{it.risk_score}</td>
                    <td className="px-4 py-3 text-center">
                      <Badge
                        variant={it.status === 'approved' || it.status === 'active' ? 'success' : 'blue'}
                        size="sm"
                      >
                        {t(`hse_advanced.jsa_status_${it.status}`, {
                          defaultValue: it.status.replace(/_/g, ' '),
                        })}
                      </Badge>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </Card>

      {showCreate && (
        <ModalShell
          title={t('hse_advanced.new_jsa', { defaultValue: 'New JSA' })}
          onClose={() => setShowCreate(false)}
          footer={
            <>
              <Button variant="ghost" onClick={() => setShowCreate(false)}>
                {t('common.cancel', { defaultValue: 'Cancel' })}
              </Button>
              <Button
                variant="primary"
                disabled={!form.task_description.trim() || createMut.isPending}
                onClick={() => createMut.mutate()}
              >
                {t('common.create', { defaultValue: 'Create' })}
              </Button>
            </>
          }
        >
          <div>
            <label className="block text-sm font-medium text-content-primary mb-1.5">
              {t('hse_advanced.task_description', { defaultValue: 'Task description' })}{' '}
              <span className="text-semantic-error">*</span>
            </label>
            <textarea
              rows={3}
              className={textareaCls}
              value={form.task_description}
              onChange={(e) => setForm((f) => ({ ...f, task_description: e.target.value }))}
            />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-sm font-medium text-content-primary mb-1.5">
                {t('hse_advanced.work_date', { defaultValue: 'Work date' })}
              </label>
              <input
                type="date"
                className={inputCls}
                value={form.work_date}
                onChange={(e) => setForm((f) => ({ ...f, work_date: e.target.value }))}
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-content-primary mb-1.5">
                {t('hse_advanced.location', { defaultValue: 'Location' })}
              </label>
              <input
                className={inputCls}
                value={form.location}
                onChange={(e) => setForm((f) => ({ ...f, location: e.target.value }))}
              />
            </div>
          </div>
        </ModalShell>
      )}

      {detail && (
        <JSADetailDrawer
          item={detail}
          projectId={projectId}
          onClose={() => setDetail(null)}
        />
      )}
    </>
  );
}

/* ── JSA Detail Drawer (lifecycle FSM) ───────────────────────────────── */

// JSA FSM (service.py allowed_jsa_transitions):
// draft → under_review (submit) → approved (approve) → active (activate) → archived.
type JSAAction = 'submit' | 'approve' | 'activate' | 'archive';

function jsaActionsFor(status: string): JSAAction[] {
  switch (status) {
    case 'draft':
      return ['submit', 'archive'];
    case 'under_review':
      return ['approve', 'archive'];
    case 'approved':
      return ['activate', 'archive'];
    case 'active':
      return ['archive'];
    default:
      return [];
  }
}

function JSADetailDrawer({
  item,
  projectId,
  onClose,
}: {
  item: JobSafetyAnalysis;
  projectId: string;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);

  const actionMut = useMutation({
    mutationFn: (action: JSAAction) => {
      switch (action) {
        case 'submit':
          return submitJSA(item.id);
        case 'approve':
          return approveJSA(item.id);
        case 'activate':
          return activateJSA(item.id);
        case 'archive':
          return archiveJSA(item.id);
      }
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['hse-jsas', projectId] });
      addToast({
        type: 'success',
        title: t('hse_advanced.jsa_advanced', { defaultValue: 'JSA updated' }),
      });
      onClose();
    },
    onError: (e) =>
      addToast({
        type: 'error',
        title: t('hse_advanced.jsa_advance_failed', { defaultValue: 'Could not update JSA' }),
        message: getErrorMessage(e),
      }),
  });

  const actions = jsaActionsFor(item.status);
  const actionMeta: Record<
    JSAAction,
    { label: string; icon: React.ReactNode; variant: 'primary' | 'secondary' | 'ghost' }
  > = {
    submit: {
      label: t('hse_advanced.jsa_submit', { defaultValue: 'Submit for review' }),
      icon: <Send size={14} />,
      variant: 'primary',
    },
    approve: {
      label: t('hse_advanced.jsa_approve', { defaultValue: 'Approve' }),
      icon: <CheckCircle size={14} />,
      variant: 'primary',
    },
    activate: {
      label: t('hse_advanced.jsa_activate', { defaultValue: 'Activate' }),
      icon: <PlayCircle size={14} />,
      variant: 'primary',
    },
    archive: {
      label: t('hse_advanced.jsa_archive', { defaultValue: 'Archive' }),
      icon: <Archive size={14} />,
      variant: 'ghost',
    },
  };

  return (
    <ModalShell
      title={`${t('hse_advanced.jsa', { defaultValue: 'JSA' })} - ${item.task_description.slice(0, 60)}`}
      onClose={onClose}
      size="max-w-3xl"
      footer={
        <div className="flex flex-1 items-center justify-between gap-3 flex-wrap">
          <span className="text-xs text-content-tertiary">
            {actions.length === 0
              ? t('hse_advanced.jsa_terminal', {
                  defaultValue: 'This JSA is archived - no further actions.',
                })
              : t('hse_advanced.jsa_fsm_hint', {
                  defaultValue: 'Lifecycle: draft → review → approved → active → archived.',
                })}
          </span>
          <div className="flex items-center gap-2 flex-wrap">
            {actions.map((a) => (
              <Button
                key={a}
                variant={actionMeta[a].variant}
                size="sm"
                icon={actionMeta[a].icon}
                disabled={actionMut.isPending}
                onClick={() => actionMut.mutate(a)}
              >
                {actionMeta[a].label}
              </Button>
            ))}
            <Button variant="ghost" size="sm" onClick={onClose}>
              {t('common.close', { defaultValue: 'Close' })}
            </Button>
          </div>
        </div>
      }
    >
      <div className="grid grid-cols-2 gap-3 text-sm">
        <div>
          <div className="text-xs text-content-tertiary uppercase">
            {t('common.status', { defaultValue: 'Status' })}
          </div>
          <Badge
            variant={item.status === 'approved' || item.status === 'active' ? 'success' : 'blue'}
            size="sm"
          >
            {t(`hse_advanced.jsa_status_${item.status}`, {
              defaultValue: item.status.replace(/_/g, ' '),
            })}
          </Badge>
        </div>
        <div>
          <div className="text-xs text-content-tertiary uppercase">
            {t('hse_advanced.risk_score', { defaultValue: 'Risk score' })}
          </div>
          <div className="text-content-primary font-semibold tabular-nums">{item.risk_score}</div>
        </div>
        <div>
          <div className="text-xs text-content-tertiary uppercase">
            {t('hse_advanced.work_date', { defaultValue: 'Work date' })}
          </div>
          <div className="text-content-secondary">
            <DateDisplay value={item.work_date} />
          </div>
        </div>
        <div>
          <div className="text-xs text-content-tertiary uppercase">
            {t('hse_advanced.location', { defaultValue: 'Location' })}
          </div>
          <div className="text-content-secondary">{item.location ?? '—'}</div>
        </div>
      </div>

      <div>
        <div className="text-xs font-semibold uppercase tracking-wider text-content-tertiary mb-1">
          {t('hse_advanced.task_description', { defaultValue: 'Task' })}
        </div>
        <p className="text-sm text-content-secondary whitespace-pre-wrap">
          {item.task_description}
        </p>
      </div>

      <div>
        <div className="text-xs font-semibold uppercase tracking-wider text-content-tertiary mb-1">
          {t('hse_advanced.hazards', { defaultValue: 'Hazards & controls' })}
        </div>
        {item.hazards && item.hazards.length > 0 ? (
          <ul className="text-sm space-y-1.5">
            {item.hazards.map((h, i) => (
              <li
                key={i}
                className="rounded-md border border-border-light bg-surface-secondary/40 px-3 py-2"
              >
                <div className="text-content-primary">
                  {h.step ? `${h.step}: ` : ''}
                  {h.hazard ?? '—'}
                </div>
                {h.controls && (
                  <div className="text-xs text-content-tertiary mt-0.5">
                    {t('hse_advanced.controls', { defaultValue: 'Controls' })}: {h.controls}
                  </div>
                )}
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-content-tertiary">
            {t('hse_advanced.no_hazards', { defaultValue: 'No hazards recorded yet.' })}
          </p>
        )}
      </div>

      <div>
        <div className="text-xs font-semibold uppercase tracking-wider text-content-tertiary mb-1">
          {t('hse_advanced.required_ppe', { defaultValue: 'Required PPE' })}
        </div>
        {item.required_ppe && item.required_ppe.length > 0 ? (
          <div className="flex flex-wrap gap-1.5">
            {item.required_ppe.map((p, i) => (
              <Badge key={i} variant="neutral" size="sm">
                {p.replace(/_/g, ' ')}
              </Badge>
            ))}
          </div>
        ) : (
          <p className="text-sm text-content-tertiary">
            {t('hse_advanced.no_ppe_listed', { defaultValue: 'None listed.' })}
          </p>
        )}
      </div>
    </ModalShell>
  );
}

/* ── Permits Tab ─────────────────────────────────────────────────────── */

function PermitsTab({ projectId }: { projectId: string }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [search, setSearch] = useState('');
  const [showCreate, setShowCreate] = useState(false);
  const [detail, setDetail] = useState<PermitToWork | null>(null);
  const [filter, setFilter] = useState<'all' | 'requested' | 'active' | 'expired'>('all');
  // Default work window: start now, end in 8h — supervisors adjust before issue.
  const nowLocal = new Date().toISOString().slice(0, 16);
  const [form, setForm] = useState({
    permit_number: '',
    permit_type: 'hot_work',
    description: '',
    work_start: nowLocal,
    work_end: nowLocal,
  });

  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ['hse-permits', projectId],
    queryFn: () => fetchPermits(projectId),
    select: (d) => normalizeListResponse<PermitToWork>(d),
  });

  const createMut = useMutation({
    mutationFn: () =>
      createPermit({
        project_id: projectId,
        permit_number: form.permit_number.trim(),
        permit_type: form.permit_type,
        description: form.description,
        // datetime-local gives YYYY-MM-DDTHH:mm; ISO-widen for the backend.
        work_start: new Date(form.work_start).toISOString(),
        work_end: new Date(form.work_end).toISOString(),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['hse-permits', projectId] });
      setShowCreate(false);
      const reset = new Date().toISOString().slice(0, 16);
      setForm({
        permit_number: '',
        permit_type: 'hot_work',
        description: '',
        work_start: reset,
        work_end: reset,
      });
      addToast({
        type: 'success',
        title: t('hse_advanced.permit_created', { defaultValue: 'Permit issued' }),
      });
    },
    onError: (e) =>
      addToast({
        type: 'error',
        title: t('hse_advanced.permit_failed', { defaultValue: 'Failed to create permit' }),
        message: getErrorMessage(e),
      }),
  });

  const counts = useMemo(() => {
    const c = { all: data?.length ?? 0, requested: 0, active: 0, expired: 0 };
    if (!data) return c;
    for (const p of data) {
      if (p.status === 'requested') c.requested++;
      else if (p.status === 'active') c.active++;
      else if (p.status === 'expired') c.expired++;
    }
    return c;
  }, [data]);

  const filtered = useMemo(() => {
    if (!data) return [];
    let rows = data;
    if (filter === 'requested') rows = rows.filter((p) => p.status === 'requested');
    else if (filter === 'active') rows = rows.filter((p) => p.status === 'active');
    else if (filter === 'expired') rows = rows.filter((p) => p.status === 'expired');
    if (!search) return rows;
    const q = search.toLowerCase();
    return rows.filter(
      (p) =>
        p.description.toLowerCase().includes(q) ||
        p.permit_number.toLowerCase().includes(q),
    );
  }, [data, search, filter]);

  if (isLoading) return <SkeletonTable rows={5} columns={6} />;
  if (isError) {
    return (
      <Card className="py-12">
        <RecoveryCard error={error} onRetry={() => refetch()} />
      </Card>
    );
  }
  if (!data || data.length === 0) {
    return (
      <EmptyState
        icon={<FileCheck size={28} strokeWidth={1.5} />}
        title={t('hse_advanced.no_permits', { defaultValue: 'No permits yet' })}
        description={t('hse_advanced.no_permits_desc', {
          defaultValue:
            'Issue a Permit to Work to authorise hot work, confined-space entry, work-at-height and other high-risk tasks. Each permit tracks scope, hazards, controls and signatures.',
        })}
        action={{
          label: t('hse_advanced.new_permit', { defaultValue: 'Issue Permit' }),
          onClick: () => setShowCreate(true),
        }}
      />
    );
  }

  return (
    <>
      <div className="mb-4">
        <FilterChips<'all' | 'requested' | 'active' | 'expired'>
          value={filter}
          onChange={setFilter}
          options={[
            {
              value: 'all',
              label: t('hse_advanced.filter_all', { defaultValue: 'All' }),
              count: counts.all,
            },
            {
              value: 'requested',
              label: t('hse_advanced.filter_requested', { defaultValue: 'Requested' }),
              count: counts.requested,
            },
            {
              value: 'active',
              label: t('hse_advanced.filter_active', { defaultValue: 'Active' }),
              count: counts.active,
            },
            {
              value: 'expired',
              label: t('hse_advanced.filter_expired', { defaultValue: 'Expired' }),
              count: counts.expired,
            },
          ]}
        />
      </div>

      <Card padding="none">
        <SearchBar
          value={search}
          onChange={setSearch}
          placeholder={t('hse_advanced.search_permits', { defaultValue: 'Search permits...' })}
          onCreate={() => setShowCreate(true)}
          createLabel={t('hse_advanced.new_permit', { defaultValue: 'Issue Permit' })}
        />
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border-light bg-surface-secondary/50">
                <th className="px-4 py-3 text-left font-medium text-content-tertiary">
                  {t('common.number', { defaultValue: '#' })}
                </th>
                <th className="px-4 py-3 text-left font-medium text-content-tertiary">
                  {t('common.description', { defaultValue: 'Description' })}
                </th>
                <th className="px-4 py-3 text-left font-medium text-content-tertiary">
                  {t('hse_advanced.permit_type', { defaultValue: 'Type' })}
                </th>
                <th className="px-4 py-3 text-center font-medium text-content-tertiary">
                  {t('common.status', { defaultValue: 'Status' })}
                </th>
                <th className="px-4 py-3 text-left font-medium text-content-tertiary">
                  {t('hse_advanced.work_end', { defaultValue: 'Work end' })}
                </th>
                <th className="px-4 py-3 text-center font-medium text-content-tertiary">
                  {t('hse_advanced.countdown', { defaultValue: 'Countdown' })}
                </th>
              </tr>
            </thead>
            <tbody>
              {filtered.length === 0 ? (
                <tr>
                  <td colSpan={6} className="px-4 py-8 text-center text-sm text-content-tertiary">
                    {t('hse_advanced.no_matches', { defaultValue: 'No matches' })}
                  </td>
                </tr>
              ) : (
                filtered.map((p) => {
                  // Countdown is driven off the permit's work_end window
                  // (there is no separate expiry field on the backend).
                  const days = daysUntil(p.work_end);
                  return (
                    <tr
                      key={p.id}
                      className="border-b border-border-light hover:bg-surface-secondary/30 cursor-pointer"
                      onClick={() => setDetail(p)}
                    >
                      <td className="px-4 py-3 font-mono text-xs">{p.permit_number}</td>
                      <td className="px-4 py-3 text-content-primary max-w-[20rem] truncate">
                        {p.description || '—'}
                      </td>
                      <td className="px-4 py-3 text-content-secondary text-xs">
                        {p.permit_type.replace(/_/g, ' ')}
                      </td>
                      <td className="px-4 py-3 text-center">
                        <Badge variant={PERMIT_STATUS_COLORS[p.status] ?? 'neutral'} size="sm">
                          {t(`hse_advanced.permit_status_${p.status}`, {
                            defaultValue: p.status,
                          })}
                        </Badge>
                      </td>
                      <td className="px-4 py-3 text-content-secondary">
                        {p.work_end ? <DateDisplay value={p.work_end} /> : '—'}
                      </td>
                      <td className="px-4 py-3 text-center tabular-nums">
                        {days === null ? (
                          <span className="text-content-tertiary">—</span>
                        ) : days < 0 ? (
                          <span className="text-semantic-error font-medium">
                            {t('hse_advanced.expired_days_ago', {
                              defaultValue: '{{n}}d ago',
                              n: Math.abs(days),
                            })}
                          </span>
                        ) : days <= 1 ? (
                          <span className="text-semantic-error font-medium">
                            {t('hse_advanced.expires_today', { defaultValue: 'today' })}
                          </span>
                        ) : (
                          <span
                            className={
                              days <= 3
                                ? 'text-amber-600 font-medium'
                                : 'text-content-secondary'
                            }
                          >
                            {t('hse_advanced.in_days', { defaultValue: 'in {{n}}d', n: days })}
                          </span>
                        )}
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </Card>

      {showCreate && (
        <ModalShell
          title={t('hse_advanced.new_permit', { defaultValue: 'Issue Permit' })}
          onClose={() => setShowCreate(false)}
          footer={
            <>
              <Button variant="ghost" onClick={() => setShowCreate(false)}>
                {t('common.cancel', { defaultValue: 'Cancel' })}
              </Button>
              <Button
                variant="primary"
                disabled={!form.permit_number.trim() || createMut.isPending}
                onClick={() => createMut.mutate()}
              >
                {t('common.issue', { defaultValue: 'Issue' })}
              </Button>
            </>
          }
        >
          <div>
            <label className="block text-sm font-medium text-content-primary mb-1.5">
              {t('hse_advanced.permit_number', { defaultValue: 'Permit number' })}{' '}
              <span className="text-semantic-error">*</span>
            </label>
            <input
              className={inputCls}
              value={form.permit_number}
              onChange={(e) => setForm((f) => ({ ...f, permit_number: e.target.value }))}
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-content-primary mb-1.5">
              {t('hse_advanced.permit_type', { defaultValue: 'Type' })}
            </label>
            <select
              className={inputCls}
              value={form.permit_type}
              onChange={(e) => setForm((f) => ({ ...f, permit_type: e.target.value }))}
            >
              <option value="hot_work">
                {t('hse_advanced.permit_type_hot_work', { defaultValue: 'Hot work' })}
              </option>
              <option value="confined_space">
                {t('hse_advanced.permit_type_confined_space', {
                  defaultValue: 'Confined space',
                })}
              </option>
              <option value="work_at_height">
                {t('hse_advanced.permit_type_work_at_height', {
                  defaultValue: 'Work at height',
                })}
              </option>
              <option value="excavation">
                {t('hse_advanced.permit_type_excavation', { defaultValue: 'Excavation' })}
              </option>
              <option value="electrical">
                {t('hse_advanced.permit_type_electrical', { defaultValue: 'Electrical' })}
              </option>
              <option value="lifting">
                {t('hse_advanced.permit_type_lifting', { defaultValue: 'Lifting / crane' })}
              </option>
            </select>
          </div>
          <div>
            <label className="block text-sm font-medium text-content-primary mb-1.5">
              {t('common.description', { defaultValue: 'Description' })}
            </label>
            <textarea
              rows={3}
              className={textareaCls}
              value={form.description}
              onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
            />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-sm font-medium text-content-primary mb-1.5">
                {t('hse_advanced.work_start', { defaultValue: 'Work start' })}
              </label>
              <input
                type="datetime-local"
                className={inputCls}
                value={form.work_start}
                onChange={(e) => setForm((f) => ({ ...f, work_start: e.target.value }))}
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-content-primary mb-1.5">
                {t('hse_advanced.work_end', { defaultValue: 'Work end' })}
              </label>
              <input
                type="datetime-local"
                className={inputCls}
                value={form.work_end}
                onChange={(e) => setForm((f) => ({ ...f, work_end: e.target.value }))}
              />
            </div>
          </div>
        </ModalShell>
      )}

      {detail && (
        <PermitDetailDrawer
          item={detail}
          projectId={projectId}
          onClose={() => setDetail(null)}
        />
      )}
    </>
  );
}

/* ── Permit Detail Drawer ────────────────────────────────────────────── */

// Permit FSM (service.py allowed_permit_transitions):
// requested → approved → active → suspended/closed/cancelled; suspended → active.
type PermitAction = 'approve' | 'activate' | 'suspend' | 'close' | 'cancel';

function permitActionsFor(status: PermitStatus): PermitAction[] {
  switch (status) {
    case 'requested':
      return ['approve', 'cancel'];
    case 'approved':
      return ['activate', 'cancel'];
    case 'active':
      return ['suspend', 'close', 'cancel'];
    case 'suspended':
      return ['activate', 'close', 'cancel'];
    default:
      return [];
  }
}

function PermitDetailDrawer({
  item,
  projectId,
  onClose,
}: {
  item: PermitToWork;
  projectId: string;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [closing, setClosing] = useState(false);
  const [closureNotes, setClosureNotes] = useState('');
  // Countdown is driven off the permit's work_end window (no expiry field).
  const days = daysUntil(item.work_end);

  const invalidate = () =>
    qc.invalidateQueries({ queryKey: ['hse-permits', projectId] });

  const actionMut = useMutation({
    mutationFn: (action: PermitAction) => {
      switch (action) {
        case 'approve':
          return approvePermit(item.id);
        case 'activate':
          return activatePermit(item.id);
        case 'suspend':
          return suspendPermit(item.id);
        case 'close':
          return closePermit(item.id, {
            closure_checklist_passed: true,
            closure_notes: closureNotes.trim(),
          });
        case 'cancel':
          return cancelPermit(item.id);
      }
    },
    onSuccess: () => {
      invalidate();
      addToast({
        type: 'success',
        title: t('hse_advanced.permit_advanced', { defaultValue: 'Permit updated' }),
      });
      onClose();
    },
    onError: (e) =>
      addToast({
        type: 'error',
        title: t('hse_advanced.permit_advance_failed', {
          defaultValue: 'Could not update permit',
        }),
        message: getErrorMessage(e),
      }),
  });

  const actions = permitActionsFor(item.status);
  const actionMeta: Record<
    PermitAction,
    { label: string; icon: React.ReactNode; variant: 'primary' | 'secondary' | 'ghost' }
  > = {
    approve: {
      label: t('hse_advanced.permit_approve', { defaultValue: 'Approve' }),
      icon: <CheckCircle size={14} />,
      variant: 'primary',
    },
    activate: {
      label: t('hse_advanced.permit_activate', { defaultValue: 'Activate' }),
      icon: <PlayCircle size={14} />,
      variant: 'primary',
    },
    suspend: {
      label: t('hse_advanced.permit_suspend', { defaultValue: 'Suspend' }),
      icon: <PauseCircle size={14} />,
      variant: 'secondary',
    },
    close: {
      label: t('hse_advanced.permit_close', { defaultValue: 'Close' }),
      icon: <CheckCircle2 size={14} />,
      variant: 'secondary',
    },
    cancel: {
      label: t('hse_advanced.permit_cancel', { defaultValue: 'Cancel permit' }),
      icon: <XCircle size={14} />,
      variant: 'ghost',
    },
  };

  return (
    <ModalShell
      title={`${item.permit_number} - ${item.permit_type.replace(/_/g, ' ')}`}
      onClose={onClose}
      size="max-w-2xl"
      footer={
        <div className="flex flex-1 items-center justify-between gap-3 flex-wrap">
          <span className="text-xs text-content-tertiary">
            {actions.length === 0
              ? t('hse_advanced.permit_terminal', {
                  defaultValue: 'No further actions for this permit.',
                })
              : t('hse_advanced.permit_fsm_hint', {
                  defaultValue: 'Approve, then activate when prerequisites are met.',
                })}
          </span>
          <div className="flex items-center gap-2 flex-wrap">
            {actions.map((a) => (
              <Button
                key={a}
                variant={actionMeta[a].variant}
                size="sm"
                icon={actionMeta[a].icon}
                disabled={actionMut.isPending}
                onClick={() => {
                  if (a === 'close') {
                    setClosing(true);
                  } else {
                    actionMut.mutate(a);
                  }
                }}
              >
                {actionMeta[a].label}
              </Button>
            ))}
            <Button variant="ghost" size="sm" onClick={onClose}>
              {t('common.close', { defaultValue: 'Close' })}
            </Button>
          </div>
        </div>
      }
    >
      <div className="grid grid-cols-2 gap-3 text-sm">
        <div>
          <div className="text-xs text-content-tertiary uppercase">
            {t('hse_advanced.permit_type', { defaultValue: 'Type' })}
          </div>
          <div className="text-content-primary">{item.permit_type.replace(/_/g, ' ')}</div>
        </div>
        <div>
          <div className="text-xs text-content-tertiary uppercase">
            {t('common.status', { defaultValue: 'Status' })}
          </div>
          <Badge variant={PERMIT_STATUS_COLORS[item.status] ?? 'neutral'} size="sm">
            {t(`hse_advanced.permit_status_${item.status}`, { defaultValue: item.status })}
          </Badge>
        </div>
      </div>

      <div>
        <div className="text-xs font-semibold uppercase tracking-wider text-content-tertiary mb-1">
          {t('common.description', { defaultValue: 'Description' })}
        </div>
        <p className="text-sm text-content-secondary whitespace-pre-wrap">
          {item.description || t('common.not_set', { defaultValue: 'Not set' })}
        </p>
      </div>

      <div className="grid grid-cols-2 gap-4">
        <div>
          <div className="text-xs font-semibold uppercase tracking-wider text-content-tertiary mb-1">
            {t('hse_advanced.work_start', { defaultValue: 'Work start' })}
          </div>
          <p className="text-sm text-content-secondary">
            <DateDisplay value={item.work_start} />
          </p>
        </div>
        <div>
          <div className="text-xs font-semibold uppercase tracking-wider text-content-tertiary mb-1">
            {t('hse_advanced.work_end', { defaultValue: 'Work end' })}
          </div>
          <p className="text-sm text-content-secondary">
            <DateDisplay value={item.work_end} />
          </p>
        </div>
      </div>

      <PermitPrereqChecklist
        item={item}
        projectId={projectId}
        editable={item.status === 'requested' || item.status === 'approved'}
      />

      <div>
        <div className="text-xs font-semibold uppercase tracking-wider text-content-tertiary mb-1">
          {t('hse_advanced.conditions', { defaultValue: 'Conditions' })}
        </div>
        <p className="text-sm text-content-secondary whitespace-pre-wrap">
          {item.conditions || t('hse_advanced.no_conditions', { defaultValue: 'None recorded' })}
        </p>
      </div>

      <div className="rounded-lg bg-surface-secondary p-3">
        <div className="flex items-center justify-between text-sm">
          <span className="flex items-center gap-1.5 text-content-secondary">
            <Clock size={14} />
            {t('hse_advanced.countdown', { defaultValue: 'Expiry countdown' })}
          </span>
          <span
            className={
              days !== null && days < 0
                ? 'text-semantic-error font-semibold'
                : days !== null && days <= 3
                  ? 'text-amber-600 font-semibold'
                  : 'text-content-primary font-medium'
            }
          >
            {days === null
              ? t('common.not_set', { defaultValue: 'Not set' })
              : days < 0
                ? t('hse_advanced.expired_days_ago', {
                    defaultValue: '{{n}}d ago',
                    n: Math.abs(days),
                  })
                : t('hse_advanced.in_days', { defaultValue: 'in {{n}}d', n: days })}
          </span>
        </div>
      </div>

      {closing && (
        <ModalShell
          title={t('hse_advanced.permit_close_title', { defaultValue: 'Close permit' })}
          onClose={() => setClosing(false)}
          size="max-w-lg"
          footer={
            <>
              <Button variant="ghost" onClick={() => setClosing(false)}>
                {t('common.cancel', { defaultValue: 'Cancel' })}
              </Button>
              <Button
                variant="primary"
                icon={<CheckCircle2 size={14} />}
                disabled={actionMut.isPending}
                onClick={() => actionMut.mutate('close')}
              >
                {t('hse_advanced.permit_close', { defaultValue: 'Close' })}
              </Button>
            </>
          }
        >
          <p className="text-sm text-content-secondary">
            {t('hse_advanced.permit_close_help', {
              defaultValue:
                'Closing confirms the work is complete and the area was made safe. The closure is recorded in the audit trail.',
            })}
          </p>
          <div>
            <label className="block text-sm font-medium text-content-primary mb-1.5">
              {t('hse_advanced.closure_notes', { defaultValue: 'Closure notes' })}
            </label>
            <textarea
              rows={3}
              className={textareaCls}
              value={closureNotes}
              onChange={(e) => setClosureNotes(e.target.value)}
              placeholder={t('hse_advanced.closure_notes_placeholder', {
                defaultValue: 'Area cleared, fire watch stood down, tools removed…',
              })}
            />
          </div>
        </ModalShell>
      )}
    </ModalShell>
  );
}

/**
 * Pre-activation safety prerequisites for a Permit-to-Work.
 *
 * The backend stores 5 booleans (jsa_approved, supervisor_present,
 * fire_watch_assigned, extinguisher_present, atmospheric_test_passed)
 * that gate the requested → active FSM transition.
 *
 * While the permit is still requested or approved the supervisor can tick
 * the gates off here (PATCH /permits/{id}/prerequisites). Once the permit is
 * active/closed the list is read-only and doubles as the historical
 * "everything was checked" record so the audit trail is preserved.
 */
const PERMIT_PREREQ_FIELDS: {
  key: string;
  field: keyof PermitPrerequisites;
  prop: keyof PermitToWork;
  labelKey: string;
  labelDefault: string;
}[] = [
  {
    key: 'jsa',
    field: 'prereq_jsa_approved',
    prop: 'prereq_jsa_approved',
    labelKey: 'hse_advanced.prereq_jsa',
    labelDefault: 'JSA approved',
  },
  {
    key: 'supervisor',
    field: 'prereq_supervisor_present',
    prop: 'prereq_supervisor_present',
    labelKey: 'hse_advanced.prereq_supervisor',
    labelDefault: 'Supervisor present',
  },
  {
    key: 'fire_watch',
    field: 'prereq_fire_watch_assigned',
    prop: 'prereq_fire_watch_assigned',
    labelKey: 'hse_advanced.prereq_fire_watch',
    labelDefault: 'Fire watch assigned',
  },
  {
    key: 'extinguisher',
    field: 'prereq_extinguisher_present',
    prop: 'prereq_extinguisher_present',
    labelKey: 'hse_advanced.prereq_extinguisher',
    labelDefault: 'Extinguisher on hand',
  },
  {
    key: 'atmospheric',
    field: 'prereq_atmospheric_test_passed',
    prop: 'prereq_atmospheric_test_passed',
    labelKey: 'hse_advanced.prereq_atmospheric',
    labelDefault: 'Atmospheric test passed',
  },
];

function PermitPrereqChecklist({
  item,
  projectId,
  editable,
}: {
  item: PermitToWork;
  projectId: string;
  editable: boolean;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);

  const patchMut = useMutation({
    mutationFn: (body: PermitPrerequisites) => updatePermitPrerequisites(item.id, body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['hse-permits', projectId] });
    },
    onError: (e) =>
      addToast({
        type: 'error',
        title: t('hse_advanced.prereq_update_failed', {
          defaultValue: 'Could not update prerequisite',
        }),
        message: getErrorMessage(e),
      }),
  });

  const items = PERMIT_PREREQ_FIELDS.map((f) => ({
    ...f,
    label: t(f.labelKey, { defaultValue: f.labelDefault }),
    checked: item[f.prop] === true,
  }));
  const passed = items.filter((i) => i.checked).length;

  return (
    <div data-testid="permit-prereq-checklist">
      <div className="flex items-center justify-between text-xs font-semibold uppercase tracking-wider text-content-tertiary mb-1">
        <span>
          {t('hse_advanced.prereq_title', {
            defaultValue: 'Pre-activation checks',
          })}
        </span>
        <span className="text-content-tertiary tabular-nums">
          {passed}/{items.length}
        </span>
      </div>
      {editable && (
        <p className="text-2xs text-content-tertiary mb-1.5">
          {t('hse_advanced.prereq_editable_hint', {
            defaultValue: 'Tick each gate as it is verified - all must pass before activation.',
          })}
        </p>
      )}
      <ul className="text-sm space-y-1">
        {items.map((row) =>
          editable ? (
            <li key={row.key} data-testid={`permit-prereq-${row.key}`}>
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  className="h-4 w-4 rounded border-border text-oe-blue focus:ring-oe-blue/30"
                  checked={row.checked}
                  disabled={patchMut.isPending}
                  onChange={(e) =>
                    patchMut.mutate({ [row.field]: e.target.checked } as PermitPrerequisites)
                  }
                />
                <span
                  className={row.checked ? 'text-content-secondary' : 'text-content-tertiary'}
                >
                  {row.label}
                </span>
              </label>
            </li>
          ) : (
            <li
              key={row.key}
              className="flex items-center gap-2"
              data-testid={`permit-prereq-${row.key}`}
            >
              <CheckCircle2
                size={14}
                className={
                  row.checked ? 'text-semantic-success' : 'text-content-tertiary opacity-40'
                }
                aria-hidden
              />
              <span
                className={
                  row.checked ? 'text-content-secondary' : 'text-content-tertiary line-through'
                }
              >
                {row.label}
              </span>
            </li>
          ),
        )}
      </ul>
    </div>
  );
}

/* ── Toolbox Tab ─────────────────────────────────────────────────────── */

function ToolboxTab({ projectId }: { projectId: string }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [search, setSearch] = useState('');
  const [showCreate, setShowCreate] = useState(false);
  // ToolboxTalkCreate requires project_id + topic_code + topic_title + conducted_at.
  const [form, setForm] = useState({
    topic_code: '',
    topic_title: '',
    conducted_at: new Date().toISOString().slice(0, 10),
    notes: '',
  });

  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ['hse-toolbox', projectId],
    queryFn: () => fetchToolboxTalks(projectId),
    select: (d) => normalizeListResponse<ToolboxTalk>(d),
  });

  const createMut = useMutation({
    mutationFn: () =>
      createToolboxTalk({
        project_id: projectId,
        topic_code: form.topic_code.trim(),
        topic_title: form.topic_title.trim(),
        // date input → ISO datetime for conducted_at: datetime.
        conducted_at: new Date(form.conducted_at).toISOString(),
        notes: form.notes || undefined,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['hse-toolbox', projectId] });
      setShowCreate(false);
      setForm({
        topic_code: '',
        topic_title: '',
        conducted_at: new Date().toISOString().slice(0, 10),
        notes: '',
      });
      addToast({
        type: 'success',
        title: t('hse_advanced.toolbox_created', { defaultValue: 'Toolbox talk logged' }),
      });
    },
    onError: (e) =>
      addToast({
        type: 'error',
        title: t('hse_advanced.toolbox_failed', { defaultValue: 'Failed to log talk' }),
        message: getErrorMessage(e),
      }),
  });

  const filtered = useMemo(() => {
    if (!data) return [];
    if (!search) return data;
    const q = search.toLowerCase();
    return data.filter(
      (it) =>
        it.topic_title.toLowerCase().includes(q) ||
        it.topic_code.toLowerCase().includes(q),
    );
  }, [data, search]);

  if (isLoading) return <SkeletonTable rows={5} columns={5} />;
  if (isError) {
    return (
      <Card className="py-12">
        <RecoveryCard error={error} onRetry={() => refetch()} />
      </Card>
    );
  }
  if (!data || data.length === 0) {
    return (
      <EmptyState
        icon={<Users size={28} strokeWidth={1.5} />}
        title={t('hse_advanced.no_toolbox', { defaultValue: 'No toolbox talks yet' })}
        description={t('hse_advanced.no_toolbox_desc', {
          defaultValue:
            'Log daily toolbox talks with topic, presenter and attendance. Each talk is a record that workers were briefed before high-risk activities.',
        })}
        action={{
          label: t('hse_advanced.new_toolbox', { defaultValue: 'Log Talk' }),
          onClick: () => setShowCreate(true),
        }}
      />
    );
  }

  return (
    <>
      <Card padding="none">
        <SearchBar
          value={search}
          onChange={setSearch}
          placeholder={t('hse_advanced.search_toolbox', { defaultValue: 'Search talks...' })}
          onCreate={() => setShowCreate(true)}
          createLabel={t('hse_advanced.new_toolbox', { defaultValue: 'Log Talk' })}
        />
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border-light bg-surface-secondary/50">
                <th className="px-4 py-3 text-left font-medium text-content-tertiary">
                  {t('hse_advanced.topic_code', { defaultValue: 'Code' })}
                </th>
                <th className="px-4 py-3 text-left font-medium text-content-tertiary">
                  {t('hse_advanced.topic', { defaultValue: 'Topic' })}
                </th>
                <th className="px-4 py-3 text-left font-medium text-content-tertiary">
                  {t('hse_advanced.conducted_at', { defaultValue: 'Conducted' })}
                </th>
                <th className="px-4 py-3 text-center font-medium text-content-tertiary">
                  {t('hse_advanced.attendance', { defaultValue: 'Attendance' })}
                </th>
              </tr>
            </thead>
            <tbody>
              {filtered.length === 0 ? (
                <tr>
                  <td colSpan={4} className="px-4 py-8 text-center text-sm text-content-tertiary">
                    {t('hse_advanced.no_matches', { defaultValue: 'No matches' })}
                  </td>
                </tr>
              ) : (
                filtered.map((it) => (
                  <tr key={it.id} className="border-b border-border-light hover:bg-surface-secondary/30">
                    <td className="px-4 py-3 font-mono text-xs">{it.topic_code}</td>
                    <td className="px-4 py-3 text-content-primary">{it.topic_title}</td>
                    <td className="px-4 py-3 text-content-secondary">
                      <DateDisplay value={it.conducted_at} />
                    </td>
                    <td className="px-4 py-3 text-center">
                      <Badge variant="blue" size="sm">
                        {it.attendance_count}
                      </Badge>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </Card>

      {showCreate && (
        <ModalShell
          title={t('hse_advanced.new_toolbox', { defaultValue: 'Log Toolbox Talk' })}
          onClose={() => setShowCreate(false)}
          footer={
            <>
              <Button variant="ghost" onClick={() => setShowCreate(false)}>
                {t('common.cancel', { defaultValue: 'Cancel' })}
              </Button>
              <Button
                variant="primary"
                disabled={
                  !form.topic_code.trim() || !form.topic_title.trim() || createMut.isPending
                }
                onClick={() => createMut.mutate()}
              >
                {t('common.save', { defaultValue: 'Save' })}
              </Button>
            </>
          }
        >
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-sm font-medium text-content-primary mb-1.5">
                {t('hse_advanced.topic_code', { defaultValue: 'Topic code' })}{' '}
                <span className="text-semantic-error">*</span>
              </label>
              <input
                className={inputCls}
                value={form.topic_code}
                onChange={(e) => setForm((f) => ({ ...f, topic_code: e.target.value }))}
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-content-primary mb-1.5">
                {t('hse_advanced.conducted_at', { defaultValue: 'Conducted at' })}
              </label>
              <input
                type="date"
                className={inputCls}
                value={form.conducted_at}
                onChange={(e) => setForm((f) => ({ ...f, conducted_at: e.target.value }))}
              />
            </div>
          </div>
          <div>
            <label className="block text-sm font-medium text-content-primary mb-1.5">
              {t('hse_advanced.topic_title', { defaultValue: 'Topic title' })}{' '}
              <span className="text-semantic-error">*</span>
            </label>
            <input
              className={inputCls}
              value={form.topic_title}
              onChange={(e) => setForm((f) => ({ ...f, topic_title: e.target.value }))}
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-content-primary mb-1.5">
              {t('common.notes', { defaultValue: 'Notes' })}
            </label>
            <textarea
              rows={3}
              className={textareaCls}
              value={form.notes}
              onChange={(e) => setForm((f) => ({ ...f, notes: e.target.value }))}
            />
          </div>
        </ModalShell>
      )}
    </>
  );
}

/* ── PPE Tab ─────────────────────────────────────────────────────────── */

function PPETab({ projectId }: { projectId: string }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [search, setSearch] = useState('');
  const [showCreate, setShowCreate] = useState(false);
  const [detail, setDetail] = useState<PPEIssue | null>(null);
  const [filter, setFilter] = useState<'all' | 'issued' | 'expiring'>('all');
  // PPEIssueCreate requires ppe_type + issued_at; recipient_name is optional.
  // There is no project_id/quantity/return_by on the backend.
  const [form, setForm] = useState({
    ppe_type: 'hard_hat',
    recipient_name: '',
    issued_at: new Date().toISOString().slice(0, 10),
    valid_until: '',
  });

  // The PPE list is org-wide (the backend route takes no project_id). We keep
  // projectId in the query key so the cache resets when the user switches
  // projects, but the request itself is unscoped.
  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ['hse-ppe', projectId],
    queryFn: () => fetchPPEIssues(),
    select: (d) => normalizeListResponse<PPEIssue>(d),
  });

  const createMut = useMutation({
    mutationFn: () =>
      createPPEIssue({
        ppe_type: form.ppe_type,
        recipient_name: form.recipient_name || undefined,
        // date input → ISO datetime for issued_at: datetime.
        issued_at: new Date(form.issued_at).toISOString(),
        // valid_until is a plain date on the backend.
        valid_until: form.valid_until || undefined,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['hse-ppe', projectId] });
      setShowCreate(false);
      setForm({
        ppe_type: 'hard_hat',
        recipient_name: '',
        issued_at: new Date().toISOString().slice(0, 10),
        valid_until: '',
      });
      addToast({
        type: 'success',
        title: t('hse_advanced.ppe_created', { defaultValue: 'PPE issued' }),
      });
    },
    onError: (e) =>
      addToast({
        type: 'error',
        title: t('hse_advanced.ppe_failed', { defaultValue: 'Failed to issue PPE' }),
        message: getErrorMessage(e),
      }),
  });

  const counts = useMemo(() => {
    const c = { all: data?.length ?? 0, issued: 0, expiring: 0 };
    if (!data) return c;
    for (const it of data) {
      if (!it.returned_at) c.issued++;
      const d = daysUntil(it.valid_until);
      if (d !== null && d >= 0 && d <= 30) c.expiring++;
    }
    return c;
  }, [data]);

  const filtered = useMemo(() => {
    if (!data) return [];
    let rows = data;
    if (filter === 'issued') rows = rows.filter((p) => !p.returned_at);
    else if (filter === 'expiring')
      rows = rows.filter((p) => {
        const d = daysUntil(p.valid_until);
        return d !== null && d >= 0 && d <= 30;
      });
    if (!search) return rows;
    const q = search.toLowerCase();
    return rows.filter(
      (p) =>
        (p.recipient_name ?? '').toLowerCase().includes(q) ||
        p.ppe_type.toLowerCase().includes(q),
    );
  }, [data, search, filter]);

  if (isLoading) return <SkeletonTable rows={5} columns={6} />;
  if (isError) {
    return (
      <Card className="py-12">
        <RecoveryCard error={error} onRetry={() => refetch()} />
      </Card>
    );
  }
  if (!data || data.length === 0) {
    return (
      <EmptyState
        icon={<HardHat size={28} strokeWidth={1.5} />}
        title={t('hse_advanced.no_ppe', { defaultValue: 'No PPE issued yet' })}
        description={t('hse_advanced.no_ppe_desc', {
          defaultValue:
            'Log PPE issued to workers - hard hats, harnesses, respirators, hearing protection. Tracks expiry, return-by dates and inventory.',
        })}
        action={{
          label: t('hse_advanced.new_ppe', { defaultValue: 'Issue PPE' }),
          onClick: () => setShowCreate(true),
        }}
      />
    );
  }

  return (
    <>
      <div className="mb-4">
        <FilterChips<'all' | 'issued' | 'expiring'>
          value={filter}
          onChange={setFilter}
          options={[
            {
              value: 'all',
              label: t('hse_advanced.filter_all', { defaultValue: 'All' }),
              count: counts.all,
            },
            {
              value: 'issued',
              label: t('hse_advanced.filter_issued', { defaultValue: 'Issued' }),
              count: counts.issued,
            },
            {
              value: 'expiring',
              label: t('hse_advanced.filter_expiring', { defaultValue: 'Expiring 30d' }),
              count: counts.expiring,
            },
          ]}
        />
      </div>

      <Card padding="none">
        <SearchBar
          value={search}
          onChange={setSearch}
          placeholder={t('hse_advanced.search_ppe', { defaultValue: 'Search PPE...' })}
          onCreate={() => setShowCreate(true)}
          createLabel={t('hse_advanced.new_ppe', { defaultValue: 'Issue PPE' })}
        />
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border-light bg-surface-secondary/50">
                <th className="px-4 py-3 text-left font-medium text-content-tertiary">
                  {t('hse_advanced.item', { defaultValue: 'Item' })}
                </th>
                <th className="px-4 py-3 text-left font-medium text-content-tertiary">
                  {t('hse_advanced.issued_to', { defaultValue: 'Issued to' })}
                </th>
                <th className="px-4 py-3 text-left font-medium text-content-tertiary">
                  {t('hse_advanced.issued_at', { defaultValue: 'Issued at' })}
                </th>
                <th className="px-4 py-3 text-center font-medium text-content-tertiary">
                  {t('common.status', { defaultValue: 'Status' })}
                </th>
                <th className="px-4 py-3 text-center font-medium text-content-tertiary">
                  {t('hse_advanced.valid_until', { defaultValue: 'Valid until' })}
                </th>
              </tr>
            </thead>
            <tbody>
              {filtered.length === 0 ? (
                <tr>
                  <td colSpan={5} className="px-4 py-8 text-center text-sm text-content-tertiary">
                    {t('hse_advanced.no_matches', { defaultValue: 'No matches' })}
                  </td>
                </tr>
              ) : (
                filtered.map((p) => {
                  const d = daysUntil(p.valid_until);
                  const flag = d !== null && d >= 0 && d <= 30;
                  return (
                    <tr
                      key={p.id}
                      className="border-b border-border-light hover:bg-surface-secondary/30 cursor-pointer"
                      onClick={() => setDetail(p)}
                    >
                      <td className="px-4 py-3 text-content-primary">
                        {p.ppe_type.replace(/_/g, ' ')}
                      </td>
                      <td className="px-4 py-3 text-content-secondary">
                        {p.recipient_name ?? '—'}
                      </td>
                      <td className="px-4 py-3 text-content-secondary">
                        <DateDisplay value={p.issued_at} />
                      </td>
                      <td className="px-4 py-3 text-center">
                        <Badge variant={p.returned_at ? 'neutral' : 'success'} size="sm">
                          {t(`hse_advanced.ppe_status_${p.status}`, {
                            defaultValue: p.status.replace(/_/g, ' '),
                          })}
                        </Badge>
                      </td>
                      <td className="px-4 py-3 text-center">
                        {p.valid_until ? (
                          <span
                            className={
                              flag
                                ? 'text-amber-600 font-medium text-xs'
                                : 'text-content-secondary text-xs'
                            }
                          >
                            <DateDisplay value={p.valid_until} />
                            {flag && (
                              <AlertTriangle
                                size={12}
                                className="inline ml-1 text-amber-600"
                              />
                            )}
                          </span>
                        ) : (
                          <span className="text-content-tertiary">—</span>
                        )}
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </Card>

      {showCreate && (
        <ModalShell
          title={t('hse_advanced.new_ppe', { defaultValue: 'Issue PPE' })}
          onClose={() => setShowCreate(false)}
          footer={
            <>
              <Button variant="ghost" onClick={() => setShowCreate(false)}>
                {t('common.cancel', { defaultValue: 'Cancel' })}
              </Button>
              <Button
                variant="primary"
                disabled={createMut.isPending}
                onClick={() => createMut.mutate()}
              >
                {t('common.issue', { defaultValue: 'Issue' })}
              </Button>
            </>
          }
        >
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-sm font-medium text-content-primary mb-1.5">
                {t('hse_advanced.ppe_type', { defaultValue: 'PPE type' })}
              </label>
              <select
                className={inputCls}
                value={form.ppe_type}
                onChange={(e) => setForm((f) => ({ ...f, ppe_type: e.target.value }))}
              >
                <option value="hard_hat">
                  {t('hse_advanced.ppe_hard_hat', { defaultValue: 'Hard hat' })}
                </option>
                <option value="safety_boots">
                  {t('hse_advanced.ppe_safety_boots', { defaultValue: 'Safety boots' })}
                </option>
                <option value="gloves">
                  {t('hse_advanced.ppe_gloves', { defaultValue: 'Gloves' })}
                </option>
                <option value="hi_vis">
                  {t('hse_advanced.ppe_hi_vis', { defaultValue: 'Hi-vis vest' })}
                </option>
                <option value="harness">
                  {t('hse_advanced.ppe_harness', { defaultValue: 'Fall harness' })}
                </option>
                <option value="respirator">
                  {t('hse_advanced.ppe_respirator', { defaultValue: 'Respirator' })}
                </option>
                <option value="glasses">
                  {t('hse_advanced.ppe_glasses', { defaultValue: 'Safety glasses' })}
                </option>
                <option value="other">
                  {t('hse_advanced.ppe_other', { defaultValue: 'Other' })}
                </option>
              </select>
            </div>
            <div>
              <label className="block text-sm font-medium text-content-primary mb-1.5">
                {t('hse_advanced.issued_at', { defaultValue: 'Issued at' })}
              </label>
              <input
                type="date"
                className={inputCls}
                value={form.issued_at}
                onChange={(e) => setForm((f) => ({ ...f, issued_at: e.target.value }))}
              />
            </div>
          </div>
          <div>
            <label className="block text-sm font-medium text-content-primary mb-1.5">
              {t('hse_advanced.issued_to', { defaultValue: 'Issued to' })}
            </label>
            <input
              className={inputCls}
              value={form.recipient_name}
              onChange={(e) => setForm((f) => ({ ...f, recipient_name: e.target.value }))}
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-content-primary mb-1.5">
              {t('hse_advanced.valid_until', { defaultValue: 'Valid until' })}
            </label>
            <input
              type="date"
              className={inputCls}
              value={form.valid_until}
              onChange={(e) => setForm((f) => ({ ...f, valid_until: e.target.value }))}
            />
          </div>
        </ModalShell>
      )}

      {detail && <PPEDetailDrawer item={detail} onClose={() => setDetail(null)} />}
    </>
  );
}

/* ── PPE Detail Drawer ───────────────────────────────────────────────── */

function PPEDetailDrawer({ item, onClose }: { item: PPEIssue; onClose: () => void }) {
  const { t } = useTranslation();
  const expiryDays = daysUntil(item.valid_until);

  return (
    <ModalShell
      title={`${item.ppe_type.replace(/_/g, ' ')}${
        item.recipient_name ? ` - ${item.recipient_name}` : ''
      }`}
      onClose={onClose}
      size="max-w-xl"
      footer={
        <Button variant="ghost" onClick={onClose}>
          {t('common.close', { defaultValue: 'Close' })}
        </Button>
      }
    >
      <div className="grid grid-cols-2 gap-3 text-sm">
        <div>
          <div className="text-xs text-content-tertiary uppercase">
            {t('hse_advanced.issued_to', { defaultValue: 'Issued to' })}
          </div>
          <div className="text-content-primary font-medium">{item.recipient_name ?? '—'}</div>
        </div>
        <div>
          <div className="text-xs text-content-tertiary uppercase">
            {t('common.status', { defaultValue: 'Status' })}
          </div>
          <Badge variant={item.returned_at ? 'neutral' : 'success'} size="sm">
            {t(`hse_advanced.ppe_status_${item.status}`, {
              defaultValue: item.status.replace(/_/g, ' '),
            })}
          </Badge>
        </div>
        <div>
          <div className="text-xs text-content-tertiary uppercase">
            {t('hse_advanced.issued_at', { defaultValue: 'Issued at' })}
          </div>
          <div className="text-content-secondary">
            <DateDisplay value={item.issued_at} />
          </div>
        </div>
        <div>
          <div className="text-xs text-content-tertiary uppercase">
            {t('hse_advanced.returned_at', { defaultValue: 'Returned at' })}
          </div>
          <div className="text-content-secondary">
            {item.returned_at ? <DateDisplay value={item.returned_at} /> : '—'}
          </div>
        </div>
        {item.size && (
          <div>
            <div className="text-xs text-content-tertiary uppercase">
              {t('hse_advanced.size', { defaultValue: 'Size' })}
            </div>
            <div className="text-content-secondary">{item.size}</div>
          </div>
        )}
        {item.serial && (
          <div>
            <div className="text-xs text-content-tertiary uppercase">
              {t('hse_advanced.serial', { defaultValue: 'Serial' })}
            </div>
            <div className="text-content-secondary font-mono text-xs">{item.serial}</div>
          </div>
        )}
      </div>

      {item.valid_until && (
        <div className="rounded-lg bg-surface-secondary p-3 text-sm flex items-center justify-between">
          <span className="flex items-center gap-1.5 text-content-secondary">
            <Clock size={14} />
            {t('hse_advanced.valid_until', { defaultValue: 'Valid until' })}
          </span>
          <span
            className={
              expiryDays !== null && expiryDays < 0
                ? 'text-semantic-error font-semibold'
                : expiryDays !== null && expiryDays <= 30
                  ? 'text-amber-600 font-semibold'
                  : 'text-content-primary'
            }
          >
            <DateDisplay value={item.valid_until} />
            {expiryDays !== null &&
              ` - ${
                expiryDays < 0
                  ? t('hse_advanced.expired_days_ago', {
                      defaultValue: '{{n}}d ago',
                      n: Math.abs(expiryDays),
                    })
                  : t('hse_advanced.in_days', { defaultValue: 'in {{n}}d', n: expiryDays })
              }`}
          </span>
        </div>
      )}
    </ModalShell>
  );
}

/* ── Audits Tab ──────────────────────────────────────────────────────── */

function AuditsTab({ projectId }: { projectId: string }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [search, setSearch] = useState('');
  const [showCreate, setShowCreate] = useState(false);
  const [detail, setDetail] = useState<SafetyAudit | null>(null);
  // AuditCreate requires project_id + audit_type + conducted_at.
  const [form, setForm] = useState({
    audit_type: 'internal',
    conducted_at: new Date().toISOString().slice(0, 10),
    summary: '',
  });

  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ['hse-audits', projectId],
    queryFn: () => fetchAudits(projectId),
    select: (d) => normalizeListResponse<SafetyAudit>(d),
  });

  const createMut = useMutation({
    mutationFn: () =>
      createAudit({
        project_id: projectId,
        audit_type: form.audit_type,
        // date input → ISO datetime for conducted_at: datetime.
        conducted_at: new Date(form.conducted_at).toISOString(),
        summary: form.summary || undefined,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['hse-audits', projectId] });
      setShowCreate(false);
      setForm({
        audit_type: 'internal',
        conducted_at: new Date().toISOString().slice(0, 10),
        summary: '',
      });
      addToast({
        type: 'success',
        title: t('hse_advanced.audit_created', { defaultValue: 'Audit scheduled' }),
      });
    },
    onError: (e) =>
      addToast({
        type: 'error',
        title: t('hse_advanced.audit_failed', { defaultValue: 'Failed to schedule audit' }),
        message: getErrorMessage(e),
      }),
  });

  const filtered = useMemo(() => {
    if (!data) return [];
    if (!search) return data;
    const q = search.toLowerCase();
    return data.filter(
      (it) =>
        it.audit_type.toLowerCase().includes(q) ||
        it.summary.toLowerCase().includes(q),
    );
  }, [data, search]);

  if (isLoading) return <SkeletonTable rows={5} columns={6} />;
  if (isError) {
    return (
      <Card className="py-12">
        <RecoveryCard error={error} onRetry={() => refetch()} />
      </Card>
    );
  }
  if (!data || data.length === 0) {
    return (
      <EmptyState
        icon={<ShieldCheck size={28} strokeWidth={1.5} />}
        title={t('hse_advanced.no_audits', { defaultValue: 'No safety audits yet' })}
        description={t('hse_advanced.no_audits_desc', {
          defaultValue:
            'Plan recurring safety audits and walk-throughs. Findings can be converted into CAPA actions with assigned owners and due dates.',
        })}
        action={{
          label: t('hse_advanced.new_audit', { defaultValue: 'Schedule Audit' }),
          onClick: () => setShowCreate(true),
        }}
      />
    );
  }

  return (
    <>
      <Card padding="none">
        <SearchBar
          value={search}
          onChange={setSearch}
          placeholder={t('hse_advanced.search_audits', { defaultValue: 'Search audits...' })}
          onCreate={() => setShowCreate(true)}
          createLabel={t('hse_advanced.new_audit', { defaultValue: 'Schedule Audit' })}
        />
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border-light bg-surface-secondary/50">
                <th className="px-4 py-3 text-left font-medium text-content-tertiary">
                  {t('hse_advanced.audit_type', { defaultValue: 'Type' })}
                </th>
                <th className="px-4 py-3 text-left font-medium text-content-tertiary">
                  {t('hse_advanced.conducted_at', { defaultValue: 'Conducted' })}
                </th>
                <th className="px-4 py-3 text-left font-medium text-content-tertiary">
                  {t('hse_advanced.summary', { defaultValue: 'Summary' })}
                </th>
                <th className="px-4 py-3 text-center font-medium text-content-tertiary">
                  {t('common.status', { defaultValue: 'Status' })}
                </th>
                <th className="px-4 py-3 text-center font-medium text-content-tertiary">
                  {t('hse_advanced.score', { defaultValue: 'Score' })}
                </th>
              </tr>
            </thead>
            <tbody>
              {filtered.length === 0 ? (
                <tr>
                  <td colSpan={5} className="px-4 py-8 text-center text-sm text-content-tertiary">
                    {t('hse_advanced.no_matches', { defaultValue: 'No matches' })}
                  </td>
                </tr>
              ) : (
                filtered.map((it) => {
                  // score_total / max_score are Decimal serialized as STRING —
                  // Number()-wrap before computing the percentage.
                  const total = it.score_total == null ? null : Number(it.score_total);
                  const max = it.max_score == null ? null : Number(it.max_score);
                  const pct =
                    total !== null && max !== null && max > 0
                      ? Math.round((total / max) * 100)
                      : null;
                  return (
                    <tr
                      key={it.id}
                      className="border-b border-border-light hover:bg-surface-secondary/30 cursor-pointer transition-colors"
                      onClick={() => setDetail(it)}
                    >
                      <td className="px-4 py-3 text-content-primary">
                        {t(`hse_advanced.audit_type_${it.audit_type}`, {
                          defaultValue: it.audit_type.replace(/_/g, ' '),
                        })}
                      </td>
                      <td className="px-4 py-3 text-content-secondary">
                        <DateDisplay value={it.conducted_at} />
                      </td>
                      <td className="px-4 py-3 text-content-secondary max-w-[20rem] truncate">
                        {it.summary || '—'}
                      </td>
                      <td className="px-4 py-3 text-center">
                        <Badge
                          variant={it.status === 'completed' ? 'success' : 'blue'}
                          size="sm"
                        >
                          {t(`hse_advanced.audit_status_${it.status}`, {
                            defaultValue: it.status.replace(/_/g, ' '),
                          })}
                        </Badge>
                      </td>
                      <td className="px-4 py-3 text-center tabular-nums">
                        {pct === null ? '—' : `${pct}%`}
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </Card>

      {showCreate && (
        <ModalShell
          title={t('hse_advanced.new_audit', { defaultValue: 'Schedule Audit' })}
          onClose={() => setShowCreate(false)}
          footer={
            <>
              <Button variant="ghost" onClick={() => setShowCreate(false)}>
                {t('common.cancel', { defaultValue: 'Cancel' })}
              </Button>
              <Button
                variant="primary"
                disabled={createMut.isPending}
                onClick={() => createMut.mutate()}
              >
                {t('common.schedule', { defaultValue: 'Schedule' })}
              </Button>
            </>
          }
        >
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-sm font-medium text-content-primary mb-1.5">
                {t('hse_advanced.audit_type', { defaultValue: 'Type' })}
              </label>
              <select
                className={inputCls}
                value={form.audit_type}
                onChange={(e) => setForm((f) => ({ ...f, audit_type: e.target.value }))}
              >
                <option value="internal">
                  {t('hse_advanced.audit_type_internal', { defaultValue: 'Internal' })}
                </option>
                <option value="external">
                  {t('hse_advanced.audit_type_external', { defaultValue: 'External' })}
                </option>
                <option value="regulatory">
                  {t('hse_advanced.audit_type_regulatory', { defaultValue: 'Regulatory' })}
                </option>
                <option value="site_walk">
                  {t('hse_advanced.audit_type_site_walk', { defaultValue: 'Site walk' })}
                </option>
              </select>
            </div>
            <div>
              <label className="block text-sm font-medium text-content-primary mb-1.5">
                {t('hse_advanced.conducted_at', { defaultValue: 'Conducted at' })}
              </label>
              <input
                type="date"
                className={inputCls}
                value={form.conducted_at}
                onChange={(e) => setForm((f) => ({ ...f, conducted_at: e.target.value }))}
              />
            </div>
          </div>
          <div>
            <label className="block text-sm font-medium text-content-primary mb-1.5">
              {t('hse_advanced.summary', { defaultValue: 'Summary' })}
            </label>
            <textarea
              rows={3}
              className={textareaCls}
              value={form.summary}
              onChange={(e) => setForm((f) => ({ ...f, summary: e.target.value }))}
            />
          </div>
        </ModalShell>
      )}

      {detail && (
        <AuditDetailDrawer
          item={detail}
          projectId={projectId}
          onClose={() => setDetail(null)}
        />
      )}
    </>
  );
}

/* ── Audit Detail Drawer (findings + complete) ───────────────────────── */

const FINDING_SEVERITY_COLORS: Record<AuditFindingSeverity, BadgeVariant> = {
  low: 'neutral',
  med: 'warning',
  high: 'warning',
  critical: 'error',
};

function AuditDetailDrawer({
  item,
  projectId,
  onClose,
}: {
  item: SafetyAudit;
  projectId: string;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [showAddFinding, setShowAddFinding] = useState(false);
  // When set, opens the shared Create CAPA dialog seeded from this finding,
  // with the source locked to the originating audit (source_type=audit,
  // source_ref=audit.id). The finding description becomes the CAPA title.
  const [capaFromFinding, setCapaFromFinding] = useState<AuditFinding | null>(null);
  const [findingForm, setFindingForm] = useState<{
    item_description: string;
    category: AuditFindingCategory;
    severity: AuditFindingSeverity;
    is_passed: boolean;
  }>({
    item_description: '',
    category: 'other',
    severity: 'low',
    is_passed: true,
  });

  const isCompleted = item.status === 'completed';

  const findingsQ = useQuery({
    queryKey: ['hse-audit-findings', item.id],
    queryFn: () => fetchAuditFindings(item.id),
    select: (d) => normalizeListResponse<AuditFinding>(d),
  });

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ['hse-audit-findings', item.id] });
    qc.invalidateQueries({ queryKey: ['hse-audits', projectId] });
  };

  const addFindingMut = useMutation({
    mutationFn: () =>
      createAuditFinding(item.id, {
        item_description: findingForm.item_description.trim(),
        category: findingForm.category,
        severity: findingForm.severity,
        is_passed: findingForm.is_passed,
      }),
    onSuccess: () => {
      invalidate();
      setShowAddFinding(false);
      setFindingForm({
        item_description: '',
        category: 'other',
        severity: 'low',
        is_passed: true,
      });
      addToast({
        type: 'success',
        title: t('hse_advanced.finding_added', { defaultValue: 'Finding recorded' }),
      });
    },
    onError: (e) =>
      addToast({
        type: 'error',
        title: t('hse_advanced.finding_failed', { defaultValue: 'Could not record finding' }),
        message: getErrorMessage(e),
      }),
  });

  const deleteFindingMut = useMutation({
    mutationFn: (findingId: string) => deleteAuditFinding(findingId),
    onSuccess: () => invalidate(),
    onError: (e) =>
      addToast({
        type: 'error',
        title: t('hse_advanced.finding_delete_failed', {
          defaultValue: 'Could not delete finding',
        }),
        message: getErrorMessage(e),
      }),
  });

  const completeMut = useMutation({
    mutationFn: () => completeAudit(item.id),
    onSuccess: () => {
      invalidate();
      addToast({
        type: 'success',
        title: t('hse_advanced.audit_completed', { defaultValue: 'Audit completed' }),
      });
      onClose();
    },
    onError: (e) =>
      addToast({
        type: 'error',
        title: t('hse_advanced.audit_complete_failed', {
          defaultValue: 'Could not complete audit',
        }),
        message: getErrorMessage(e),
      }),
  });

  const findings = findingsQ.data ?? [];
  const total = item.score_total == null ? null : Number(item.score_total);
  const max = item.max_score == null ? null : Number(item.max_score);
  const pct = total !== null && max !== null && max > 0 ? Math.round((total / max) * 100) : null;

  const categories: AuditFindingCategory[] = [
    'PPE',
    'permit',
    'housekeeping',
    'electrical',
    'fire',
    'environmental',
    'other',
  ];
  const severities: AuditFindingSeverity[] = ['low', 'med', 'high', 'critical'];

  return (
    <ModalShell
      title={`${t(`hse_advanced.audit_type_${item.audit_type}`, {
        defaultValue: item.audit_type.replace(/_/g, ' '),
      })} - ${t('hse_advanced.tab_audits', { defaultValue: 'Audit' })}`}
      onClose={onClose}
      size="max-w-3xl"
      footer={
        <div className="flex flex-1 items-center justify-between gap-3 flex-wrap">
          <span className="text-xs text-content-tertiary">
            {isCompleted
              ? t('hse_advanced.audit_done_hint', {
                  defaultValue: 'Audit completed - score is locked from the recorded findings.',
                })
              : t('hse_advanced.audit_open_hint', {
                  defaultValue: 'Record each finding, then complete the audit to lock the score.',
                })}
          </span>
          <div className="flex items-center gap-2 flex-wrap">
            {!isCompleted && (
              <Button
                variant="primary"
                size="sm"
                icon={<CheckCircle size={14} />}
                disabled={completeMut.isPending}
                onClick={() => completeMut.mutate()}
              >
                {t('hse_advanced.complete_audit', { defaultValue: 'Complete audit' })}
              </Button>
            )}
            <Button variant="ghost" size="sm" onClick={onClose}>
              {t('common.close', { defaultValue: 'Close' })}
            </Button>
          </div>
        </div>
      }
    >
      <div className="grid grid-cols-3 gap-3 text-sm">
        <div>
          <div className="text-xs text-content-tertiary uppercase">
            {t('common.status', { defaultValue: 'Status' })}
          </div>
          <Badge variant={isCompleted ? 'success' : 'blue'} size="sm">
            {t(`hse_advanced.audit_status_${item.status}`, {
              defaultValue: item.status.replace(/_/g, ' '),
            })}
          </Badge>
        </div>
        <div>
          <div className="text-xs text-content-tertiary uppercase">
            {t('hse_advanced.conducted_at', { defaultValue: 'Conducted' })}
          </div>
          <div className="text-content-secondary">
            <DateDisplay value={item.conducted_at} />
          </div>
        </div>
        <div>
          <div className="text-xs text-content-tertiary uppercase">
            {t('hse_advanced.score', { defaultValue: 'Score' })}
          </div>
          <div className="text-content-primary font-semibold tabular-nums">
            {pct === null ? '—' : `${pct}%`}
          </div>
        </div>
      </div>

      {item.summary && (
        <div>
          <div className="text-xs font-semibold uppercase tracking-wider text-content-tertiary mb-1">
            {t('hse_advanced.summary', { defaultValue: 'Summary' })}
          </div>
          <p className="text-sm text-content-secondary whitespace-pre-wrap">{item.summary}</p>
        </div>
      )}

      <div>
        <div className="flex items-center justify-between mb-2">
          <div className="text-xs font-semibold uppercase tracking-wider text-content-tertiary">
            {t('hse_advanced.findings', { defaultValue: 'Findings' })}
          </div>
          {!isCompleted && (
            <Button
              variant="secondary"
              size="sm"
              icon={<Plus size={14} />}
              onClick={() => setShowAddFinding(true)}
            >
              {t('hse_advanced.add_finding', { defaultValue: 'Add finding' })}
            </Button>
          )}
        </div>
        {findingsQ.isLoading ? (
          <SkeletonTable rows={3} columns={3} />
        ) : findings.length === 0 ? (
          <p className="text-sm text-content-tertiary py-4 text-center">
            {t('hse_advanced.no_findings_yet', {
              defaultValue: 'No findings recorded. Add findings to score this audit.',
            })}
          </p>
        ) : (
          <ul className="space-y-1.5">
            {findings.map((f) => (
              <li
                key={f.id}
                className="flex items-start gap-2 rounded-md border border-border-light bg-surface-secondary/40 px-3 py-2"
              >
                {f.is_passed ? (
                  <CheckCircle2 size={15} className="text-semantic-success mt-0.5 shrink-0" />
                ) : (
                  <XCircle size={15} className="text-semantic-error mt-0.5 shrink-0" />
                )}
                <div className="flex-1 min-w-0">
                  <div className="text-sm text-content-primary">{f.item_description}</div>
                  <div className="flex items-center gap-1.5 mt-1 flex-wrap">
                    <Badge variant="neutral" size="sm">
                      {t(`hse_advanced.finding_cat_${f.category}`, {
                        defaultValue: f.category,
                      })}
                    </Badge>
                    <Badge variant={FINDING_SEVERITY_COLORS[f.severity]} size="sm">
                      {t(`hse_advanced.finding_sev_${f.severity}`, { defaultValue: f.severity })}
                    </Badge>
                    {f.corrective_action_ref ? (
                      <Badge variant="success" size="sm">
                        {t('hse_advanced.finding_has_capa', { defaultValue: 'CAPA raised' })}
                      </Badge>
                    ) : (
                      <button
                        type="button"
                        onClick={() => setCapaFromFinding(f)}
                        className="inline-flex items-center gap-1 text-xs text-oe-blue-text hover:underline"
                      >
                        <Wrench size={12} />
                        {t('hse_advanced.create_capa_from_finding', {
                          defaultValue: 'Create CAPA',
                        })}
                      </button>
                    )}
                  </div>
                </div>
                {!isCompleted && (
                  <button
                    type="button"
                    aria-label={t('common.delete', { defaultValue: 'Delete' })}
                    disabled={deleteFindingMut.isPending}
                    onClick={() => deleteFindingMut.mutate(f.id)}
                    className="text-content-tertiary hover:text-semantic-error transition-colors shrink-0"
                  >
                    <Trash2 size={14} />
                  </button>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>

      {capaFromFinding && (
        <CreateCAPADialog
          projectId={projectId}
          lockSource
          initial={{
            source_type: 'audit',
            source_ref: item.id,
            title: capaFromFinding.item_description.slice(0, 200),
            description: t('hse_advanced.capa_from_finding_desc', {
              defaultValue: 'Corrective action for audit finding: {{finding}}',
              finding: capaFromFinding.item_description,
            }),
          }}
          onClose={() => setCapaFromFinding(null)}
        />
      )}

      {showAddFinding && (
        <ModalShell
          title={t('hse_advanced.add_finding', { defaultValue: 'Add finding' })}
          onClose={() => setShowAddFinding(false)}
          size="max-w-lg"
          footer={
            <>
              <Button variant="ghost" onClick={() => setShowAddFinding(false)}>
                {t('common.cancel', { defaultValue: 'Cancel' })}
              </Button>
              <Button
                variant="primary"
                disabled={!findingForm.item_description.trim() || addFindingMut.isPending}
                onClick={() => addFindingMut.mutate()}
              >
                {t('common.add', { defaultValue: 'Add' })}
              </Button>
            </>
          }
        >
          <div>
            <label className="block text-sm font-medium text-content-primary mb-1.5">
              {t('hse_advanced.finding_description', { defaultValue: 'Finding' })}{' '}
              <span className="text-semantic-error">*</span>
            </label>
            <textarea
              rows={3}
              className={textareaCls}
              value={findingForm.item_description}
              onChange={(e) =>
                setFindingForm((f) => ({ ...f, item_description: e.target.value }))
              }
            />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-sm font-medium text-content-primary mb-1.5">
                {t('hse_advanced.finding_category', { defaultValue: 'Category' })}
              </label>
              <select
                className={inputCls}
                value={findingForm.category}
                onChange={(e) =>
                  setFindingForm((f) => ({
                    ...f,
                    category: e.target.value as AuditFindingCategory,
                  }))
                }
              >
                {categories.map((c) => (
                  <option key={c} value={c}>
                    {t(`hse_advanced.finding_cat_${c}`, { defaultValue: c })}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="block text-sm font-medium text-content-primary mb-1.5">
                {t('hse_advanced.finding_severity', { defaultValue: 'Severity' })}
              </label>
              <select
                className={inputCls}
                value={findingForm.severity}
                onChange={(e) =>
                  setFindingForm((f) => ({
                    ...f,
                    severity: e.target.value as AuditFindingSeverity,
                  }))
                }
              >
                {severities.map((s) => (
                  <option key={s} value={s}>
                    {t(`hse_advanced.finding_sev_${s}`, { defaultValue: s })}
                  </option>
                ))}
              </select>
            </div>
          </div>
          <label className="flex items-center gap-2 cursor-pointer text-sm">
            <input
              type="checkbox"
              className="h-4 w-4 rounded border-border text-oe-blue focus:ring-oe-blue/30"
              checked={findingForm.is_passed}
              onChange={(e) => setFindingForm((f) => ({ ...f, is_passed: e.target.checked }))}
            />
            <span className="text-content-secondary">
              {t('hse_advanced.finding_passed', {
                defaultValue: 'Item passed (uncheck for a failed / non-conforming item)',
              })}
            </span>
          </label>
        </ModalShell>
      )}
    </ModalShell>
  );
}

/* ── CAPA Tab ────────────────────────────────────────────────────────── */

function CAPATab({ projectId }: { projectId: string }) {
  const { t } = useTranslation();
  const [subTab, setSubTab] = useState<'capa' | 'corrective_actions'>('capa');
  return (
    <>
      <div className="flex items-center gap-1 mb-4" role="tablist">
        <button
          role="tab"
          aria-selected={subTab === 'capa'}
          onClick={() => setSubTab('capa')}
          className={`px-3 py-1.5 text-xs font-medium rounded-md transition-colors ${
            subTab === 'capa'
              ? 'bg-oe-blue-subtle text-oe-blue-text'
              : 'text-content-tertiary hover:bg-surface-secondary'
          }`}
        >
          {t('hse.advanced.subtab_capa', { defaultValue: 'CAPAs' })}
        </button>
        <button
          role="tab"
          aria-selected={subTab === 'corrective_actions'}
          onClick={() => setSubTab('corrective_actions')}
          className={`px-3 py-1.5 text-xs font-medium rounded-md transition-colors ${
            subTab === 'corrective_actions'
              ? 'bg-oe-blue-subtle text-oe-blue-text'
              : 'text-content-tertiary hover:bg-surface-secondary'
          }`}
        >
          {t('hse.advanced.subtab_corrective_actions', {
            defaultValue: 'Corrective actions (FSM)',
          })}
        </button>
      </div>
      {subTab === 'capa' ? (
        <CAPALegacyTab projectId={projectId} />
      ) : (
        <CorrectiveActionsFSMTab projectId={projectId} />
      )}
    </>
  );
}

function CAPALegacyTab({ projectId }: { projectId: string }) {
  const { t } = useTranslation();
  const [search, setSearch] = useState('');
  const [showCreate, setShowCreate] = useState(false);
  const [detail, setDetail] = useState<CorrectiveAction | null>(null);
  const [filter, setFilter] = useState<'all' | 'open' | 'closed'>('open');

  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ['hse-capa', projectId],
    queryFn: () => fetchCAPAs(projectId),
    select: (d) => normalizeListResponse<CorrectiveAction>(d),
  });

  // CAPA status enum: open | in_progress | completed | overdue | cancelled.
  // "Closed" buckets the terminal states (completed | cancelled).
  const isCapaClosed = (status: CAPAStatus) =>
    status === 'completed' || status === 'cancelled';

  const counts = useMemo(() => {
    const c = { all: data?.length ?? 0, open: 0, closed: 0 };
    if (!data) return c;
    for (const it of data) {
      if (isCapaClosed(it.status)) c.closed++;
      else c.open++;
    }
    return c;
  }, [data]);

  const filtered = useMemo(() => {
    if (!data) return [];
    let rows = data;
    if (filter === 'open') rows = rows.filter((it) => !isCapaClosed(it.status));
    else if (filter === 'closed') rows = rows.filter((it) => isCapaClosed(it.status));
    if (!search) return rows;
    const q = search.toLowerCase();
    return rows.filter((it) => it.title.toLowerCase().includes(q));
  }, [data, search, filter]);

  if (isLoading) return <SkeletonTable rows={5} columns={6} />;
  if (isError) {
    return (
      <Card className="py-12">
        <RecoveryCard error={error} onRetry={() => refetch()} />
      </Card>
    );
  }
  if (!data || data.length === 0) {
    return (
      <EmptyState
        icon={<Wrench size={28} strokeWidth={1.5} />}
        title={t('hse_advanced.no_capa', { defaultValue: 'No corrective actions yet' })}
        description={t('hse_advanced.no_capa_desc', {
          defaultValue:
            'Corrective and Preventive Actions track what was done to fix an issue and prevent recurrence. They link back to a safety incident, JSA, permit, audit or observation.',
        })}
        action={{
          label: t('hse_advanced.new_capa', { defaultValue: 'New CAPA' }),
          onClick: () => setShowCreate(true),
        }}
      />
    );
  }

  return (
    <>
      <div className="mb-4">
        <FilterChips<'all' | 'open' | 'closed'>
          value={filter}
          onChange={setFilter}
          options={[
            {
              value: 'open',
              label: t('hse_advanced.filter_open', { defaultValue: 'Open' }),
              count: counts.open,
            },
            {
              value: 'closed',
              label: t('hse_advanced.filter_closed', { defaultValue: 'Closed' }),
              count: counts.closed,
            },
            {
              value: 'all',
              label: t('hse_advanced.filter_all', { defaultValue: 'All' }),
              count: counts.all,
            },
          ]}
        />
      </div>

      <Card padding="none">
        <SearchBar
          value={search}
          onChange={setSearch}
          placeholder={t('hse_advanced.search_capa', { defaultValue: 'Search CAPAs...' })}
          onCreate={() => setShowCreate(true)}
          createLabel={t('hse_advanced.new_capa', { defaultValue: 'New CAPA' })}
        />
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border-light bg-surface-secondary/50">
                <th className="px-4 py-3 text-left font-medium text-content-tertiary">
                  {t('hse_advanced.source_type', { defaultValue: 'Source' })}
                </th>
                <th className="px-4 py-3 text-left font-medium text-content-tertiary">
                  {t('common.title', { defaultValue: 'Title' })}
                </th>
                <th className="px-4 py-3 text-left font-medium text-content-tertiary">
                  {t('hse_advanced.owner', { defaultValue: 'Owner' })}
                </th>
                <th className="px-4 py-3 text-left font-medium text-content-tertiary">
                  {t('hse_advanced.target_date', { defaultValue: 'Target' })}
                </th>
                <th className="px-4 py-3 text-center font-medium text-content-tertiary">
                  {t('common.status', { defaultValue: 'Status' })}
                </th>
                <th className="px-4 py-3 text-center font-medium text-content-tertiary">
                  {t('hse_advanced.countdown', { defaultValue: 'Countdown' })}
                </th>
              </tr>
            </thead>
            <tbody>
              {filtered.length === 0 ? (
                <tr>
                  <td colSpan={6} className="px-4 py-8 text-center text-sm text-content-tertiary">
                    {t('hse_advanced.no_matches', { defaultValue: 'No matches' })}
                  </td>
                </tr>
              ) : (
                filtered.map((it) => {
                  // Countdown is driven off the CAPA's target_date.
                  const days = daysUntil(it.target_date);
                  const isClosed = isCapaClosed(it.status);
                  return (
                    <tr
                      key={it.id}
                      className="border-b border-border-light hover:bg-surface-secondary/30 cursor-pointer transition-colors"
                      onClick={() => setDetail(it)}
                    >
                      <td className="px-4 py-3 text-content-secondary text-xs">
                        {t(`hse_advanced.source_type_${it.source_type}`, {
                          defaultValue: it.source_type.replace(/_/g, ' '),
                        })}
                      </td>
                      <td className="px-4 py-3 text-content-primary">{it.title}</td>
                      <td className="px-4 py-3 text-content-secondary text-xs font-mono">
                        {it.owner_user_id ?? '—'}
                      </td>
                      <td className="px-4 py-3 text-content-secondary">
                        {it.target_date ? <DateDisplay value={it.target_date} /> : '—'}
                      </td>
                      <td className="px-4 py-3 text-center">
                        <Badge variant={CAPA_STATUS_COLORS[it.status] ?? 'neutral'} size="sm">
                          {t(`hse_advanced.capa_status_${it.status}`, {
                            defaultValue: it.status.replace(/_/g, ' '),
                          })}
                        </Badge>
                      </td>
                      <td className="px-4 py-3 text-center tabular-nums text-xs">
                        {isClosed || days === null ? (
                          <span className="text-content-tertiary">—</span>
                        ) : days < 0 ? (
                          <span className="text-semantic-error font-medium">
                            {t('hse_advanced.overdue_days', {
                              defaultValue: '{{n}}d overdue',
                              n: Math.abs(days),
                            })}
                          </span>
                        ) : (
                          <span
                            className={
                              days <= 3 ? 'text-amber-600 font-medium' : 'text-content-secondary'
                            }
                          >
                            {t('hse_advanced.in_days', { defaultValue: 'in {{n}}d', n: days })}
                          </span>
                        )}
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </Card>

      {showCreate && (
        <CreateCAPADialog projectId={projectId} onClose={() => setShowCreate(false)} />
      )}

      {detail && (
        <CAPADetailDrawer
          item={detail}
          projectId={projectId}
          onClose={() => setDetail(null)}
        />
      )}
    </>
  );
}

/* ── Create CAPA dialog (shared) ─────────────────────────────────────────
 * Used by the CAPA tab's "New CAPA" button (full source picker) and by the
 * audit "Create CAPA" finding shortcut (source locked to the originating
 * audit). Centralising the create form means source_ref wiring lives in one
 * place. The backend source_type enum is incident|jsa|permit|audit|observation;
 * source_ref is the optional UUID of that record.
 */
function CreateCAPADialog({
  projectId,
  initial,
  lockSource = false,
  onClose,
  onCreated,
}: {
  projectId: string;
  initial?: {
    source_type?: string;
    source_ref?: string;
    title?: string;
    description?: string;
  };
  /** When true the source_type/source_ref come pre-set and are not editable
   *  (e.g. opened from an audit finding). */
  lockSource?: boolean;
  onClose: () => void;
  onCreated?: () => void;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);

  const [form, setForm] = useState({
    source_type: initial?.source_type ?? 'observation',
    source_ref: initial?.source_ref ?? '',
    title: initial?.title ?? '',
    description: initial?.description ?? '',
    target_date: new Date().toISOString().slice(0, 10),
  });

  const createMut = useMutation({
    mutationFn: () =>
      createCAPA({
        project_id: projectId,
        source_type: form.source_type,
        // "observation" carries no ref; everything else passes the picked id
        // (or undefined when the user left it blank).
        source_ref:
          form.source_type === 'observation' || !form.source_ref ? undefined : form.source_ref,
        title: form.title,
        description: form.description || undefined,
        target_date: form.target_date,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['hse-capa', projectId] });
      addToast({
        type: 'success',
        title: t('hse_advanced.capa_created', { defaultValue: 'CAPA created' }),
      });
      onCreated?.();
      onClose();
    },
    onError: (e) =>
      addToast({
        type: 'error',
        title: t('hse_advanced.capa_failed', { defaultValue: 'Failed to create CAPA' }),
        message: getErrorMessage(e),
      }),
  });

  return (
    <ModalShell
      title={t('hse_advanced.new_capa', { defaultValue: 'New CAPA' })}
      onClose={onClose}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button
            variant="primary"
            disabled={!form.title.trim() || !form.description.trim() || createMut.isPending}
            onClick={() => createMut.mutate()}
          >
            {t('common.create', { defaultValue: 'Create' })}
          </Button>
        </>
      }
    >
      <div>
        <label className="block text-sm font-medium text-content-primary mb-1.5">
          {t('common.title', { defaultValue: 'Title' })}{' '}
          <span className="text-semantic-error">*</span>
        </label>
        <input
          className={inputCls}
          value={form.title}
          onChange={(e) => setForm((f) => ({ ...f, title: e.target.value }))}
        />
      </div>
      <div>
        <label className="block text-sm font-medium text-content-primary mb-1.5">
          {t('common.description', { defaultValue: 'Description' })}{' '}
          <span className="text-semantic-error">*</span>
        </label>
        <textarea
          rows={3}
          className={textareaCls}
          value={form.description}
          onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
        />
      </div>
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="block text-sm font-medium text-content-primary mb-1.5">
            {t('hse_advanced.source_type', { defaultValue: 'Source' })}
          </label>
          <select
            className={inputCls}
            value={form.source_type}
            disabled={lockSource}
            onChange={(e) =>
              // Switching source type clears any previously picked ref.
              setForm((f) => ({ ...f, source_type: e.target.value, source_ref: '' }))
            }
          >
            {/* source_type must match the backend enum
                ^(incident|jsa|permit|audit|observation)$. */}
            {CAPA_SOURCE_TYPES.map((s) => (
              <option key={s} value={s}>
                {t(`hse_advanced.source_type_${s}`, {
                  defaultValue: s.charAt(0).toUpperCase() + s.slice(1),
                })}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="block text-sm font-medium text-content-primary mb-1.5">
            {t('hse_advanced.target_date', { defaultValue: 'Target date' })}
          </label>
          <input
            type="date"
            className={inputCls}
            value={form.target_date}
            onChange={(e) => setForm((f) => ({ ...f, target_date: e.target.value }))}
          />
        </div>
      </div>
      <div>
        <label className="block text-sm font-medium text-content-primary mb-1.5">
          {t('hse_advanced.source_record', { defaultValue: 'Linked source record' })}
        </label>
        {lockSource ? (
          <p className="text-sm text-content-secondary">
            {t('hse_advanced.capa_source_locked', {
              defaultValue: 'Linked to the originating audit.',
            })}
          </p>
        ) : (
          <CapaSourceRefPicker
            projectId={projectId}
            sourceType={form.source_type}
            value={form.source_ref}
            onChange={(id) => setForm((f) => ({ ...f, source_ref: id }))}
          />
        )}
      </div>
    </ModalShell>
  );
}

/* ── CAPA Detail Drawer (lifecycle + 5-Whys + effectiveness) ─────────── */

const ROOT_CAUSE_CATEGORIES: RootCauseCategory[] = [
  'manpower',
  'method',
  'material',
  'machine',
  'environment',
  'management',
  'other',
];

function CAPADetailDrawer({
  item,
  projectId,
  onClose,
}: {
  item: CorrectiveAction;
  projectId: string;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);

  // Sub-modals: complete (verification notes), 5-whys editor, effectiveness.
  const [completing, setCompleting] = useState(false);
  const [verificationNotes, setVerificationNotes] = useState('');
  const [editingWhys, setEditingWhys] = useState(false);
  const [verifyingEff, setVerifyingEff] = useState(false);

  const [whys, setWhys] = useState<FiveWhyStep[]>(() =>
    (item.five_whys ?? []).map((w) => ({
      why: String((w as Record<string, unknown>).why ?? ''),
      answer: String((w as Record<string, unknown>).answer ?? ''),
    })),
  );
  const [rootCause, setRootCause] = useState<RootCauseCategory | ''>(
    (item.root_cause_category as RootCauseCategory | undefined) ?? '',
  );
  const [effForm, setEffForm] = useState({ effective: true, notes: '' });

  const invalidate = () => qc.invalidateQueries({ queryKey: ['hse-capa', projectId] });
  const isClosed = item.status === 'completed' || item.status === 'cancelled';

  const completeMut = useMutation({
    mutationFn: () => completeCAPA(item.id, verificationNotes.trim()),
    onSuccess: () => {
      invalidate();
      addToast({
        type: 'success',
        title: t('hse_advanced.capa_completed', { defaultValue: 'CAPA completed' }),
      });
      onClose();
    },
    onError: (e) =>
      addToast({
        type: 'error',
        title: t('hse_advanced.capa_action_failed', { defaultValue: 'Could not update CAPA' }),
        message: getErrorMessage(e),
      }),
  });

  const escalateMut = useMutation({
    mutationFn: () => escalateCAPA(item.id),
    onSuccess: () => {
      invalidate();
      addToast({
        type: 'success',
        title: t('hse_advanced.capa_escalated', { defaultValue: 'CAPA escalated' }),
      });
      onClose();
    },
    onError: (e) =>
      addToast({
        type: 'error',
        title: t('hse_advanced.capa_action_failed', { defaultValue: 'Could not update CAPA' }),
        message: getErrorMessage(e),
      }),
  });

  const cancelMut = useMutation({
    mutationFn: () => cancelCAPA(item.id),
    onSuccess: () => {
      invalidate();
      addToast({
        type: 'success',
        title: t('hse_advanced.capa_cancelled', { defaultValue: 'CAPA cancelled' }),
      });
      onClose();
    },
    onError: (e) =>
      addToast({
        type: 'error',
        title: t('hse_advanced.capa_action_failed', { defaultValue: 'Could not update CAPA' }),
        message: getErrorMessage(e),
      }),
  });

  const whysMut = useMutation({
    mutationFn: () =>
      setCAPAFiveWhys(item.id, {
        steps: whys.filter((w) => w.why.trim() && w.answer.trim()),
        root_cause_category: rootCause || null,
      }),
    onSuccess: () => {
      invalidate();
      setEditingWhys(false);
      addToast({
        type: 'success',
        title: t('hse_advanced.whys_saved', { defaultValue: '5-Whys saved' }),
      });
    },
    onError: (e) =>
      addToast({
        type: 'error',
        title: t('hse_advanced.whys_failed', { defaultValue: 'Could not save 5-Whys' }),
        message: getErrorMessage(e),
      }),
  });

  const effMut = useMutation({
    mutationFn: () =>
      verifyCAPAEffectiveness(item.id, {
        effective: effForm.effective,
        notes: effForm.notes.trim(),
      }),
    onSuccess: () => {
      invalidate();
      setVerifyingEff(false);
      addToast({
        type: 'success',
        title: t('hse_advanced.effectiveness_saved', {
          defaultValue: 'Effectiveness verified',
        }),
      });
      onClose();
    },
    onError: (e) =>
      addToast({
        type: 'error',
        title: t('hse_advanced.effectiveness_failed', {
          defaultValue: 'Could not verify effectiveness',
        }),
        message: getErrorMessage(e),
      }),
  });

  return (
    <ModalShell
      title={`${t('hse_advanced.tab_capa', { defaultValue: 'CAPA' })} - ${item.title.slice(0, 60)}`}
      onClose={onClose}
      size="max-w-3xl"
      footer={
        <div className="flex flex-1 items-center justify-end gap-2 flex-wrap">
          {!isClosed && (
            <>
              <Button
                variant="secondary"
                size="sm"
                icon={<ArrowUpCircle size={14} />}
                disabled={escalateMut.isPending}
                onClick={() => escalateMut.mutate()}
              >
                {t('hse_advanced.capa_escalate', { defaultValue: 'Escalate' })}
              </Button>
              <Button
                variant="ghost"
                size="sm"
                icon={<XCircle size={14} />}
                disabled={cancelMut.isPending}
                onClick={() => cancelMut.mutate()}
              >
                {t('hse_advanced.capa_cancel', { defaultValue: 'Cancel CAPA' })}
              </Button>
              <Button
                variant="primary"
                size="sm"
                icon={<CheckCircle size={14} />}
                onClick={() => setCompleting(true)}
              >
                {t('hse_advanced.capa_complete', { defaultValue: 'Complete' })}
              </Button>
            </>
          )}
          {item.status === 'completed' && (
            <Button
              variant="secondary"
              size="sm"
              icon={<ListChecks size={14} />}
              onClick={() => setVerifyingEff(true)}
            >
              {t('hse_advanced.verify_effectiveness', {
                defaultValue: 'Verify effectiveness',
              })}
            </Button>
          )}
          <Button variant="ghost" size="sm" onClick={onClose}>
            {t('common.close', { defaultValue: 'Close' })}
          </Button>
        </div>
      }
    >
      <div className="grid grid-cols-2 gap-3 text-sm">
        <div>
          <div className="text-xs text-content-tertiary uppercase">
            {t('common.status', { defaultValue: 'Status' })}
          </div>
          <Badge variant={CAPA_STATUS_COLORS[item.status] ?? 'neutral'} size="sm">
            {t(`hse_advanced.capa_status_${item.status}`, {
              defaultValue: item.status.replace(/_/g, ' '),
            })}
          </Badge>
        </div>
        <div>
          <div className="text-xs text-content-tertiary uppercase">
            {t('hse_advanced.target_date', { defaultValue: 'Target' })}
          </div>
          <div className="text-content-secondary">
            {item.target_date ? <DateDisplay value={item.target_date} /> : '—'}
          </div>
        </div>
        <div>
          <div className="text-xs text-content-tertiary uppercase">
            {t('hse_advanced.source_type', { defaultValue: 'Source' })}
          </div>
          <div className="text-content-secondary flex items-center gap-2 flex-wrap">
            <span>
              {t(`hse_advanced.source_type_${item.source_type}`, {
                defaultValue: item.source_type.replace(/_/g, ' '),
              })}
            </span>
            {item.source_ref && capaSourceLink(item.source_type, item.source_ref) && (
              <button
                type="button"
                onClick={() => {
                  const to = capaSourceLink(item.source_type, item.source_ref!);
                  if (to) navigate(to);
                }}
                className="inline-flex items-center gap-1 text-xs text-oe-blue-text hover:underline"
              >
                <ExternalLink size={12} />
                {t('hse_advanced.view_source', { defaultValue: 'View source' })}
              </button>
            )}
          </div>
        </div>
        <div>
          <div className="text-xs text-content-tertiary uppercase">
            {t('hse_advanced.root_cause', { defaultValue: 'Root cause' })}
          </div>
          <div className="text-content-secondary">
            {item.root_cause_category
              ? t(`hse_advanced.root_cause_${item.root_cause_category}`, {
                  defaultValue: item.root_cause_category,
                })
              : '—'}
          </div>
        </div>
      </div>

      {item.description && (
        <div>
          <div className="text-xs font-semibold uppercase tracking-wider text-content-tertiary mb-1">
            {t('common.description', { defaultValue: 'Description' })}
          </div>
          <p className="text-sm text-content-secondary whitespace-pre-wrap">
            {item.description}
          </p>
        </div>
      )}

      {/* 5-Whys root-cause chain */}
      <div>
        <div className="flex items-center justify-between mb-1">
          <div className="text-xs font-semibold uppercase tracking-wider text-content-tertiary">
            {t('hse_advanced.five_whys', { defaultValue: '5-Whys root cause' })}
          </div>
          {!isClosed && (
            <Button variant="ghost" size="sm" onClick={() => setEditingWhys(true)}>
              {t('hse_advanced.edit_whys', { defaultValue: 'Edit 5-Whys' })}
            </Button>
          )}
        </div>
        {item.five_whys && item.five_whys.length > 0 ? (
          <ol className="text-sm space-y-1 list-decimal list-inside">
            {item.five_whys.map((w, i) => {
              const rec = w as Record<string, unknown>;
              return (
                <li key={i} className="text-content-secondary">
                  <span className="text-content-primary">{String(rec.why ?? '')}</span>
                  {' → '}
                  {String(rec.answer ?? '')}
                </li>
              );
            })}
          </ol>
        ) : (
          <p className="text-sm text-content-tertiary">
            {t('hse_advanced.no_whys', { defaultValue: 'No root-cause chain recorded yet.' })}
          </p>
        )}
      </div>

      {item.verification_notes && (
        <div>
          <div className="text-xs font-semibold uppercase tracking-wider text-content-tertiary mb-1">
            {t('hse_advanced.verification_notes', { defaultValue: 'Verification notes' })}
          </div>
          <p className="text-sm text-content-secondary whitespace-pre-wrap">
            {item.verification_notes}
          </p>
        </div>
      )}

      {item.effectiveness_verified_at && (
        <div className="rounded-lg bg-semantic-success/5 border border-semantic-success/30 p-3 text-sm text-semantic-success flex items-center gap-2">
          <ListChecks size={15} />
          {t('hse_advanced.effectiveness_done', {
            defaultValue: 'Effectiveness verified',
          })}{' '}
          (<DateDisplay value={item.effectiveness_verified_at} />)
        </div>
      )}

      {/* Complete (verification notes) sub-modal */}
      {completing && (
        <ModalShell
          title={t('hse_advanced.capa_complete', { defaultValue: 'Complete CAPA' })}
          onClose={() => setCompleting(false)}
          size="max-w-lg"
          footer={
            <>
              <Button variant="ghost" onClick={() => setCompleting(false)}>
                {t('common.cancel', { defaultValue: 'Cancel' })}
              </Button>
              <Button
                variant="primary"
                icon={<CheckCircle size={14} />}
                disabled={completeMut.isPending}
                onClick={() => completeMut.mutate()}
              >
                {t('hse_advanced.capa_complete', { defaultValue: 'Complete' })}
              </Button>
            </>
          }
        >
          <p className="text-sm text-content-secondary">
            {t('hse_advanced.capa_complete_help', {
              defaultValue:
                'Record what was done to close this action. Notes become part of the CAPA audit trail.',
            })}
          </p>
          <div>
            <label className="block text-sm font-medium text-content-primary mb-1.5">
              {t('hse_advanced.verification_notes', { defaultValue: 'Verification notes' })}
            </label>
            <textarea
              rows={4}
              className={textareaCls}
              value={verificationNotes}
              onChange={(e) => setVerificationNotes(e.target.value)}
            />
          </div>
        </ModalShell>
      )}

      {/* 5-Whys editor sub-modal */}
      {editingWhys && (
        <ModalShell
          title={t('hse_advanced.five_whys', { defaultValue: '5-Whys root cause' })}
          onClose={() => setEditingWhys(false)}
          size="max-w-2xl"
          footer={
            <>
              <Button variant="ghost" onClick={() => setEditingWhys(false)}>
                {t('common.cancel', { defaultValue: 'Cancel' })}
              </Button>
              <Button
                variant="primary"
                disabled={whysMut.isPending}
                onClick={() => whysMut.mutate()}
              >
                {t('common.save', { defaultValue: 'Save' })}
              </Button>
            </>
          }
        >
          <p className="text-sm text-content-secondary">
            {t('hse_advanced.five_whys_help', {
              defaultValue:
                'Ask "why" repeatedly to reach the true root cause. Each row is a why and its answer.',
            })}
          </p>
          <div className="space-y-2">
            {whys.map((w, i) => (
              <div key={i} className="grid grid-cols-[1fr,1fr,auto] gap-2 items-start">
                <input
                  className={inputCls}
                  placeholder={t('hse_advanced.why_n', { defaultValue: 'Why #{{n}}?', n: i + 1 })}
                  value={w.why}
                  onChange={(e) =>
                    setWhys((arr) =>
                      arr.map((row, j) => (j === i ? { ...row, why: e.target.value } : row)),
                    )
                  }
                />
                <input
                  className={inputCls}
                  placeholder={t('hse_advanced.because', { defaultValue: 'Because…' })}
                  value={w.answer}
                  onChange={(e) =>
                    setWhys((arr) =>
                      arr.map((row, j) =>
                        j === i ? { ...row, answer: e.target.value } : row,
                      ),
                    )
                  }
                />
                <button
                  type="button"
                  aria-label={t('common.delete', { defaultValue: 'Delete' })}
                  onClick={() => setWhys((arr) => arr.filter((_, j) => j !== i))}
                  className="h-10 px-2 text-content-tertiary hover:text-semantic-error"
                >
                  <Trash2 size={15} />
                </button>
              </div>
            ))}
          </div>
          <Button
            variant="ghost"
            size="sm"
            icon={<Plus size={14} />}
            onClick={() => setWhys((arr) => [...arr, { why: '', answer: '' }])}
          >
            {t('hse_advanced.add_why', { defaultValue: 'Add why' })}
          </Button>
          <div>
            <label className="block text-sm font-medium text-content-primary mb-1.5">
              {t('hse_advanced.root_cause_category', { defaultValue: 'Root-cause category' })}
            </label>
            <select
              className={inputCls}
              value={rootCause}
              onChange={(e) => setRootCause(e.target.value as RootCauseCategory | '')}
            >
              <option value="">
                {t('hse_advanced.root_cause_none', { defaultValue: 'Not categorised' })}
              </option>
              {ROOT_CAUSE_CATEGORIES.map((c) => (
                <option key={c} value={c}>
                  {t(`hse_advanced.root_cause_${c}`, { defaultValue: c })}
                </option>
              ))}
            </select>
          </div>
        </ModalShell>
      )}

      {/* Effectiveness verification sub-modal (ISO 9001 §10.2.1) */}
      {verifyingEff && (
        <ModalShell
          title={t('hse_advanced.verify_effectiveness', {
            defaultValue: 'Verify effectiveness',
          })}
          onClose={() => setVerifyingEff(false)}
          size="max-w-lg"
          footer={
            <>
              <Button variant="ghost" onClick={() => setVerifyingEff(false)}>
                {t('common.cancel', { defaultValue: 'Cancel' })}
              </Button>
              <Button
                variant="primary"
                icon={<ListChecks size={14} />}
                disabled={effMut.isPending}
                onClick={() => effMut.mutate()}
              >
                {t('common.save', { defaultValue: 'Save' })}
              </Button>
            </>
          }
        >
          <p className="text-sm text-content-secondary">
            {t('hse_advanced.effectiveness_help', {
              defaultValue:
                'Confirm the corrective action actually prevented recurrence (ISO 9001 §10.2.1 follow-up).',
            })}
          </p>
          <label className="flex items-center gap-2 cursor-pointer text-sm">
            <input
              type="checkbox"
              className="h-4 w-4 rounded border-border text-oe-blue focus:ring-oe-blue/30"
              checked={effForm.effective}
              onChange={(e) => setEffForm((f) => ({ ...f, effective: e.target.checked }))}
            />
            <span className="text-content-secondary">
              {t('hse_advanced.was_effective', {
                defaultValue: 'The action was effective (uncheck if it was not)',
              })}
            </span>
          </label>
          <div>
            <label className="block text-sm font-medium text-content-primary mb-1.5">
              {t('common.notes', { defaultValue: 'Notes' })}
            </label>
            <textarea
              rows={3}
              className={textareaCls}
              value={effForm.notes}
              onChange={(e) => setEffForm((f) => ({ ...f, notes: e.target.value }))}
            />
          </div>
        </ModalShell>
      )}
    </ModalShell>
  );
}

/* ── Corrective Actions (slim FSM) sub-tab ─────────────────────────── */

/** Map FSM state to the visible-text label so the dropdown is i18n-aware. */
function fsmLabel(t: ReturnType<typeof useTranslation>['t'], s: CATargetStatus): string {
  switch (s) {
    case 'pending':
      return t('hse.advanced.ca_status_pending', { defaultValue: 'Pending' });
    case 'in_progress':
      return t('hse.advanced.ca_status_in_progress', { defaultValue: 'In progress' });
    case 'verified':
      return t('hse.advanced.ca_status_verified', { defaultValue: 'Verified' });
    case 'closed':
      return t('hse.advanced.ca_status_closed', { defaultValue: 'Closed' });
  }
}

const FSM_NEXT: Record<CATargetStatus, CATargetStatus | null> = {
  pending: 'in_progress',
  in_progress: 'verified',
  verified: 'closed',
  closed: null,
};

const FSM_BADGE: Record<CATargetStatus, BadgeVariant> = {
  pending: 'warning',
  in_progress: 'blue',
  verified: 'success',
  closed: 'neutral',
};

function CorrectiveActionsFSMTab({ projectId }: { projectId: string }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const addToast = useToastStore((s) => s.addToast);
  // When advancing to 'verified' we capture verification notes first so the
  // audit trail (verified_at/verified_by + verification_notes) is complete.
  const [verifyTarget, setVerifyTarget] = useState<CorrectiveActionRow | null>(null);
  const [verifyNotes, setVerifyNotes] = useState('');

  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ['hse-corrective-actions', projectId],
    queryFn: () => fetchCorrectiveActions({ projectId }),
    select: (d) => normalizeListResponse<CorrectiveActionRow>(d),
  });

  const transitionMut = useMutation({
    mutationFn: (args: { caId: string; to: CATargetStatus; notes?: string }) =>
      transitionCorrectiveAction(args.caId, {
        to_status: args.to,
        verification_notes: args.notes,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['hse-corrective-actions', projectId] });
      setVerifyTarget(null);
      setVerifyNotes('');
      addToast({
        type: 'success',
        title: t('hse.advanced.ca_transition_ok', {
          defaultValue: 'Corrective action advanced',
        }),
      });
    },
    onError: (e) =>
      addToast({
        type: 'error',
        title: t('hse.advanced.ca_transition_failed', {
          defaultValue: 'Could not advance corrective action',
        }),
        message: getErrorMessage(e),
      }),
  });

  // Advancing to 'verified' opens the notes modal; every other step is direct.
  const advance = (row: CorrectiveActionRow, to: CATargetStatus) => {
    if (to === 'verified') {
      setVerifyNotes('');
      setVerifyTarget(row);
    } else {
      transitionMut.mutate({ caId: row.id, to });
    }
  };

  if (isLoading) return <SkeletonTable rows={4} columns={5} />;
  if (isError) {
    return (
      <Card className="py-12">
        <RecoveryCard error={error} onRetry={() => refetch()} />
      </Card>
    );
  }
  if (!data || data.length === 0) {
    return (
      <EmptyState
        icon={<CheckCircle2 size={28} strokeWidth={1.5} />}
        title={t('hse.advanced.no_corrective_actions', {
          defaultValue: 'No corrective actions yet',
        })}
        description={t('hse.advanced.no_corrective_actions_desc', {
          defaultValue:
            'Slim corrective actions are opened off a safety incident and walk a strict pending → in_progress → verified → closed lifecycle. Open an incident in the Safety module and assign a corrective action to populate this list.',
        })}
        action={{
          label: t('hse.advanced.go_to_safety', { defaultValue: 'Go to Safety incidents' }),
          onClick: () => navigate('/safety'),
        }}
      />
    );
  }

  return (
    <>
    <Card padding="none">
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border-light bg-surface-secondary/50">
              <th className="px-4 py-3 text-left font-medium text-content-tertiary">
                {t('hse.advanced.ca_col_description', { defaultValue: 'Description' })}
              </th>
              <th className="px-4 py-3 text-left font-medium text-content-tertiary">
                {t('hse.advanced.ca_col_due', { defaultValue: 'Due' })}
              </th>
              <th className="px-4 py-3 text-center font-medium text-content-tertiary">
                {t('common.status', { defaultValue: 'Status' })}
              </th>
              <th className="px-4 py-3 text-left font-medium text-content-tertiary">
                {t('hse.advanced.ca_col_verified_at', { defaultValue: 'Verified at' })}
              </th>
              <th className="px-4 py-3 text-center font-medium text-content-tertiary">
                {t('hse.advanced.ca_col_advance', { defaultValue: 'Advance' })}
              </th>
            </tr>
          </thead>
          <tbody>
            {data.map((row) => {
              const next = FSM_NEXT[row.status];
              return (
                <tr
                  key={row.id}
                  className="border-b border-border-light hover:bg-surface-secondary/30"
                >
                  <td className="px-4 py-3 text-content-primary max-w-[28rem] truncate">
                    {row.description}
                  </td>
                  <td className="px-4 py-3 text-content-secondary">
                    {row.due_date ? <DateDisplay value={row.due_date} /> : '—'}
                  </td>
                  <td className="px-4 py-3 text-center">
                    <Badge variant={FSM_BADGE[row.status]} size="sm">
                      {fsmLabel(t, row.status)}
                    </Badge>
                  </td>
                  <td className="px-4 py-3 text-content-secondary">
                    {row.verified_at ? <DateDisplay value={row.verified_at} /> : '—'}
                  </td>
                  <td className="px-4 py-3 text-center">
                    {next ? (
                      <select
                        aria-label={t('hse.advanced.ca_col_advance', {
                          defaultValue: 'Advance',
                        })}
                        value=""
                        disabled={transitionMut.isPending}
                        onChange={(e) => {
                          const to = e.target.value as CATargetStatus;
                          if (!to) return;
                          advance(row, to);
                        }}
                        className="h-8 rounded-md border border-border bg-surface-primary px-2 text-xs focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue"
                      >
                        <option value="">
                          {t('hse.advanced.ca_choose_next', {
                            defaultValue: 'Advance to…',
                          })}
                        </option>
                        <option value={next}>{fsmLabel(t, next)}</option>
                      </select>
                    ) : (
                      <span className="text-xs text-content-tertiary">
                        {t('hse.advanced.ca_terminal', { defaultValue: 'Closed' })}
                      </span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </Card>

    {verifyTarget && (
      <ModalShell
        title={t('hse.advanced.ca_verify_title', { defaultValue: 'Verify corrective action' })}
        onClose={() => setVerifyTarget(null)}
        size="max-w-lg"
        footer={
          <>
            <Button variant="ghost" onClick={() => setVerifyTarget(null)}>
              {t('common.cancel', { defaultValue: 'Cancel' })}
            </Button>
            <Button
              variant="primary"
              icon={<CheckCircle size={14} />}
              disabled={transitionMut.isPending}
              onClick={() =>
                transitionMut.mutate({
                  caId: verifyTarget.id,
                  to: 'verified',
                  notes: verifyNotes.trim() || undefined,
                })
              }
            >
              {t('hse.advanced.ca_status_verified', { defaultValue: 'Verified' })}
            </Button>
          </>
        }
      >
        <p className="text-sm text-content-secondary">
          {t('hse.advanced.ca_verify_help', {
            defaultValue:
              'Verifying records that you checked the action was carried out. Add a short note describing what you confirmed.',
          })}
        </p>
        <div>
          <label className="block text-sm font-medium text-content-primary mb-1.5">
            {t('hse_advanced.verification_notes', { defaultValue: 'Verification notes' })}
          </label>
          <textarea
            rows={3}
            className={textareaCls}
            value={verifyNotes}
            onChange={(e) => setVerifyNotes(e.target.value)}
            placeholder={t('hse.advanced.ca_verify_placeholder', {
              defaultValue: 'Checked on site, photos attached, sign-off received…',
            })}
          />
        </div>
      </ModalShell>
    )}
    </>
  );
}
