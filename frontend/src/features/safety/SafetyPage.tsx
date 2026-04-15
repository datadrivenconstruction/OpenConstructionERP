import { useState, useMemo, useEffect, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { useParams, useNavigate } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import clsx from 'clsx';
import { normalizeListResponse } from '@/shared/lib/apiHelpers';
import {
  ShieldAlert,
  Eye,
  Search,
  HardHat,
  Download,
  Loader2,
  Plus,
  X,
  ClipboardCheck,
  ListChecks,
  Heart,
  AlertTriangle,
  Home,
  Leaf,
  Flame,
  ThumbsUp,
  UserX,
  AlertOctagon,
} from 'lucide-react';
import {
  Button,
  Card,
  Badge,
  EmptyState,
  Breadcrumb,
  SkeletonTable,
} from '@/shared/ui';
import { DateDisplay } from '@/shared/ui/DateDisplay';
import { apiGet, apiPost, triggerDownload } from '@/shared/lib/api';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { useAuthStore } from '@/stores/useAuthStore';
import { useToastStore } from '@/stores/useToastStore';

/* ── Types ─────────────────────────────────────────────────────────────── */

interface Incident {
  id: string;
  project_id: string;
  incident_number: string;
  date: string;
  type: string;
  severity: string;
  description: string;
  treatment: string;
  days_lost: number;
  status: string;
  reported_by: string;
  created_at: string;
  updated_at: string;
}

interface Observation {
  id: string;
  project_id: string;
  observation_number: string;
  date: string;
  type: string;
  severity: number;
  risk_score: number;
  description: string;
  location: string;
  status: string;
  reported_by: string;
  corrective_action: string;
  created_at: string;
  updated_at: string;
}

/* ── Constants ────────────────────────────────────────────────────────── */

type SafetyTab = 'incidents' | 'observations';

const INCIDENT_TYPE_COLORS: Record<
  string,
  'neutral' | 'blue' | 'success' | 'warning' | 'error'
> = {
  near_miss: 'warning',
  first_aid: 'blue',
  medical: 'error',
  lost_time: 'error',
  fatality: 'error',
  property_damage: 'warning',
  environmental: 'blue',
};

const INCIDENT_SEVERITY_COLORS: Record<
  string,
  'neutral' | 'blue' | 'success' | 'warning' | 'error'
> = {
  minor: 'neutral',
  moderate: 'warning',
  major: 'error',
  critical: 'error',
};

const INCIDENT_STATUS_COLORS: Record<
  string,
  'neutral' | 'blue' | 'success' | 'warning' | 'error'
> = {
  reported: 'blue',
  investigating: 'warning',
  resolved: 'success',
  closed: 'neutral',
};

const OBS_TYPE_COLORS: Record<
  string,
  'neutral' | 'blue' | 'success' | 'warning' | 'error'
> = {
  unsafe_act: 'error',
  unsafe_condition: 'warning',
  positive: 'success',
  environmental: 'blue',
  housekeeping: 'neutral',
};

const OBS_STATUS_COLORS: Record<
  string,
  'neutral' | 'blue' | 'success' | 'warning' | 'error'
> = {
  open: 'warning',
  in_progress: 'blue',
  resolved: 'success',
  closed: 'neutral',
};

/* ── Card Config for Create Modals ────────────────────────────────────── */

function getIncidentTypeCards(t: (key: string, opts?: Record<string, unknown>) => string): Record<
  string,
  { icon: React.ElementType; color: string; description: string }
> {
  return {
    injury: {
      icon: Heart,
      color:
        'text-red-600 bg-red-50 border-red-200 dark:text-red-400 dark:bg-red-950/30 dark:border-red-800',
      description: t('safety.incident_type_injury', { defaultValue: 'Worker injury' }),
    },
    near_miss: {
      icon: AlertTriangle,
      color:
        'text-amber-600 bg-amber-50 border-amber-200 dark:text-amber-400 dark:bg-amber-950/30 dark:border-amber-800',
      description: t('safety.incident_type_near_miss', { defaultValue: 'Close call' }),
    },
    property_damage: {
      icon: Home,
      color:
        'text-orange-600 bg-orange-50 border-orange-200 dark:text-orange-400 dark:bg-orange-950/30 dark:border-orange-800',
      description: t('safety.incident_type_property_damage', { defaultValue: 'Equipment/structure damage' }),
    },
    environmental: {
      icon: Leaf,
      color:
        'text-green-600 bg-green-50 border-green-200 dark:text-green-400 dark:bg-green-950/30 dark:border-green-800',
      description: t('safety.incident_type_environmental', { defaultValue: 'Spill or emission' }),
    },
    fire: {
      icon: Flame,
      color:
        'text-rose-600 bg-rose-50 border-rose-200 dark:text-rose-400 dark:bg-rose-950/30 dark:border-rose-800',
      description: t('safety.incident_type_fire', { defaultValue: 'Fire or explosion' }),
    },
  };
}

const INCIDENT_TYPES_LIST = ['injury', 'near_miss', 'property_damage', 'environmental', 'fire'];

function getTreatmentOptions(t: (key: string, opts?: Record<string, unknown>) => string) {
  return [
    { value: '', label: t('safety.treatment_none', { defaultValue: 'None' }) },
    { value: 'first_aid', label: t('safety.treatment_first_aid', { defaultValue: 'First Aid' }) },
    { value: 'medical', label: t('safety.treatment_medical', { defaultValue: 'Medical' }) },
    { value: 'hospital', label: t('safety.treatment_hospital', { defaultValue: 'Hospital' }) },
  ] as const;
}

function getObsTypeCards(t: (key: string, opts?: Record<string, unknown>) => string): Record<
  string,
  { icon: React.ElementType; color: string; description: string }
> {
  return {
    positive: {
      icon: ThumbsUp,
      color:
        'text-green-600 bg-green-50 border-green-200 dark:text-green-400 dark:bg-green-950/30 dark:border-green-800',
      description: t('safety.obs_type_positive', { defaultValue: 'Good safety practice observed' }),
    },
    unsafe_act: {
      icon: UserX,
      color:
        'text-red-600 bg-red-50 border-red-200 dark:text-red-400 dark:bg-red-950/30 dark:border-red-800',
      description: t('safety.obs_type_unsafe_act', { defaultValue: 'Person doing something unsafe' }),
    },
    unsafe_condition: {
      icon: AlertOctagon,
      color:
        'text-orange-600 bg-orange-50 border-orange-200 dark:text-orange-400 dark:bg-orange-950/30 dark:border-orange-800',
      description: t('safety.obs_type_unsafe_condition', { defaultValue: 'Hazardous condition found' }),
    },
    near_miss: {
      icon: AlertTriangle,
      color:
        'text-amber-600 bg-amber-50 border-amber-200 dark:text-amber-400 dark:bg-amber-950/30 dark:border-amber-800',
      description: t('safety.obs_type_near_miss', { defaultValue: 'Almost happened' }),
    },
  };
}

const OBS_TYPES_LIST = ['positive', 'unsafe_act', 'unsafe_condition', 'near_miss'];

/* ── Helpers ──────────────────────────────────────────────────────────── */

function riskScoreColor(score: number): string {
  if (score <= 5) return 'bg-green-100 text-green-800 dark:bg-green-900/40 dark:text-green-300';
  if (score <= 10) return 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900/40 dark:text-yellow-300';
  if (score <= 15) return 'bg-orange-100 text-orange-800 dark:bg-orange-900/40 dark:text-orange-300';
  return 'bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-300';
}

function riskScoreLabel(score: number, t: (key: string, opts?: Record<string, unknown>) => string): string {
  if (score <= 5) return t('safety.risk_low', { defaultValue: 'Low' });
  if (score <= 10) return t('safety.risk_medium', { defaultValue: 'Medium' });
  if (score <= 15) return t('safety.risk_high', { defaultValue: 'High' });
  return t('safety.risk_critical', { defaultValue: 'Critical' });
}

function SeverityDots({ level, max = 5 }: { level: number; max?: number }) {
  return (
    <div className="flex items-center gap-0.5">
      {Array.from({ length: max }).map((_, i) => (
        <span
          key={i}
          className={`inline-block h-2 w-2 rounded-full ${
            i < level
              ? level >= 4
                ? 'bg-red-500'
                : level >= 3
                  ? 'bg-orange-400'
                  : level >= 2
                    ? 'bg-yellow-400'
                    : 'bg-green-400'
              : 'bg-surface-tertiary'
          }`}
        />
      ))}
    </div>
  );
}

/* ── Export helpers ───────────────────────────────────────────────────── */

async function downloadExcelExport(url: string, fallbackFilename: string): Promise<void> {
  const token = useAuthStore.getState().accessToken;
  const headers: Record<string, string> = { Accept: 'application/octet-stream' };
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  const response = await fetch(`/api${url}`, { method: 'GET', headers });
  if (!response.ok) {
    let detail = 'Export failed';
    try {
      const body = await response.json();
      detail = body.detail || detail;
    } catch {
      // ignore parse error
    }
    throw new Error(detail);
  }

  const blob = await response.blob();
  const disposition = response.headers.get('Content-Disposition');
  const filename = disposition?.match(/filename="?(.+)"?/)?.[1] || fallbackFilename;
  triggerDownload(blob, filename);
}

/* ── Quality Ecosystem Summary ────────────────────────────────────────── */

interface SafetyStats {
  total_incidents: number;
  incidents_by_status?: Record<string, number>;
}

interface PunchSummaryData {
  total: number;
  by_status: Record<string, number>;
}

function QualityDashboardSummary({ projectId }: { projectId: string }) {
  const { t } = useTranslation();

  const { data: safetyStats } = useQuery({
    queryKey: ['safety-stats', projectId],
    queryFn: () => apiGet<SafetyStats>(`/v1/safety/stats/?project_id=${projectId}`),
    enabled: !!projectId,
  });

  const { data: inspections } = useQuery({
    queryKey: ['inspections-summary', projectId],
    queryFn: () =>
      apiGet<{ status: string }[]>(`/v1/inspections/?project_id=${projectId}`),
    select: (d): { status: string }[] => normalizeListResponse(d),
    enabled: !!projectId,
  });

  const { data: ncrs } = useQuery({
    queryKey: ['ncrs-summary', projectId],
    queryFn: () =>
      apiGet<{ status: string }[]>(`/v1/ncr/?project_id=${projectId}`),
    select: (d): { status: string }[] => normalizeListResponse(d),
    enabled: !!projectId,
  });

  const { data: punchSummary } = useQuery({
    queryKey: ['punch-summary', projectId],
    queryFn: () => apiGet<PunchSummaryData>(`/v1/punchlist/summary/?project_id=${projectId}`),
    enabled: !!projectId,
  });

  const openIncidents = safetyStats
    ? (safetyStats.incidents_by_status?.['reported'] ?? 0) +
      (safetyStats.incidents_by_status?.['investigating'] ?? 0)
    : 0;

  const pendingInspections = inspections
    ? inspections.filter((i) => i.status === 'scheduled' || i.status === 'in_progress').length
    : 0;

  const openNCRs = ncrs
    ? ncrs.filter((n) => n.status === 'open' || n.status === 'under_review' || n.status === 'corrective_action').length
    : 0;

  const openDefects = punchSummary
    ? (punchSummary.by_status?.['open'] ?? 0) +
      (punchSummary.by_status?.['in_progress'] ?? 0)
    : 0;

  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6">
      <Card padding="none">
        <div className="p-3">
          <div className="text-2xs text-content-tertiary uppercase">
            {t('safety.dash_open_incidents', { defaultValue: 'Open Incidents' })}
          </div>
          <div className="text-xl font-bold text-content-primary">{openIncidents}</div>
        </div>
      </Card>
      <Card padding="none">
        <div className="p-3">
          <div className="text-2xs text-content-tertiary uppercase">
            {t('safety.dash_pending_inspections', { defaultValue: 'Pending Inspections' })}
          </div>
          <div className="text-xl font-bold text-content-primary">{pendingInspections}</div>
        </div>
      </Card>
      <Card padding="none">
        <div className="p-3">
          <div className="text-2xs text-content-tertiary uppercase">
            {t('safety.dash_open_ncrs', { defaultValue: 'Open NCRs' })}
          </div>
          <div className="text-xl font-bold text-content-primary">{openNCRs}</div>
        </div>
      </Card>
      <Card padding="none">
        <div className="p-3">
          <div className="text-2xs text-content-tertiary uppercase">
            {t('safety.dash_open_defects', { defaultValue: 'Open Defects' })}
          </div>
          <div className="text-xl font-bold text-content-primary">{openDefects}</div>
        </div>
      </Card>
    </div>
  );
}

/* ── Main Page ────────────────────────────────────────────────────────── */

const inputCls =
  'h-10 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';
const textareaCls =
  'w-full rounded-lg border border-border bg-surface-primary px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue resize-none';

export function SafetyPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { projectId: routeProjectId } = useParams<{ projectId?: string }>();
  const activeProjectId = useProjectContextStore((s) => s.activeProjectId);
  const projectId = routeProjectId || activeProjectId || '';
  const projectName = useProjectContextStore((s) => s.activeProjectName);

  const [activeTab, setActiveTab] = useState<SafetyTab>('incidents');

  const tabs: { key: SafetyTab; label: string; icon: React.ReactNode }[] = [
    {
      key: 'incidents',
      label: t('safety.incidents', { defaultValue: 'Incidents' }),
      icon: <ShieldAlert size={15} />,
    },
    {
      key: 'observations',
      label: t('safety.observations', { defaultValue: 'Observations' }),
      icon: <Eye size={15} />,
    },
  ];

  return (
    <div className="w-full animate-fade-in">
      <Breadcrumb
        items={[
          { label: t('nav.dashboard', 'Dashboard'), to: '/' },
          ...(projectName
            ? [{ label: projectName, to: `/projects/${projectId}` }]
            : []),
          { label: t('safety.title', { defaultValue: 'Safety' }) },
        ]}
        className="mb-4"
      />

      {/* Header */}
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-content-primary">
          {t('safety.title', { defaultValue: 'Safety' })}
        </h1>
        <p className="mt-1 text-sm text-content-secondary">
          {t('safety.subtitle', {
            defaultValue: 'Report incidents, record observations, and monitor site safety compliance',
          })}
        </p>
      </div>

      {/* Cross-module links */}
      <div className="flex flex-wrap gap-1.5 mb-4">
        <Button variant="ghost" size="sm" className="text-xs" onClick={() => navigate('/inspections')}>
          <ClipboardCheck size={13} className="me-1" />
          {t('safety.link_inspections', { defaultValue: 'Inspections' })}
        </Button>
        <Button variant="ghost" size="sm" className="text-xs" onClick={() => navigate('/punchlist')}>
          <ListChecks size={13} className="me-1" />
          {t('safety.link_punchlist', { defaultValue: 'Punch List' })}
        </Button>
      </div>

      {/* Quality Ecosystem Summary */}
      {projectId && <QualityDashboardSummary projectId={projectId} />}

      {/* No-project warning */}
      {!projectId && (
        <div className="mb-4 flex items-center gap-3 rounded-lg border border-amber-200 bg-amber-50 dark:bg-amber-950/20 dark:border-amber-800 px-4 py-3">
          <AlertTriangle size={18} className="text-amber-600 shrink-0" />
          <div>
            <p className="text-sm font-medium text-amber-800 dark:text-amber-300">{t('common.no_project_selected', { defaultValue: 'No project selected' })}</p>
            <p className="text-xs text-amber-600 dark:text-amber-400">{t('common.select_project_hint', { defaultValue: 'Select a project from the header to view and manage items.' })}</p>
          </div>
        </div>
      )}

      {projectId ? (
        <>
          {/* Tab Bar */}
          <div className="flex items-center gap-1 mb-6 border-b border-border-light">
            {tabs.map((tab) => (
              <button
                key={tab.key}
                onClick={() => setActiveTab(tab.key)}
                className={`
                  flex items-center gap-2 px-4 py-2.5 text-sm font-medium border-b-2 transition-all
                  ${
                    activeTab === tab.key
                      ? 'border-oe-blue text-oe-blue'
                      : 'border-transparent text-content-tertiary hover:text-content-primary hover:bg-surface-secondary'
                  }
                `}
              >
                {tab.icon}
                {tab.label}
              </button>
            ))}
          </div>

          {/* Tab Content */}
          {activeTab === 'incidents' && (
            <IncidentsTab projectId={projectId} />
          )}
          {activeTab === 'observations' && (
            <ObservationsTab projectId={projectId} />
          )}
        </>
      ) : (
        <EmptyState
          icon={<HardHat size={28} strokeWidth={1.5} />}
          title={t('safety.no_project', {
            defaultValue: 'No project selected',
          })}
          description={t('safety.select_project', {
            defaultValue:
              'Select a project from the header to report incidents, record safety observations, and track compliance.',
          })}
        />
      )}
    </div>
  );
}

/* ── Incidents Tab ────────────────────────────────────────────────────── */

function IncidentsTab({ projectId }: { projectId: string }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [search, setSearch] = useState('');
  const addToast = useToastStore((s) => s.addToast);
  const [showCreate, setShowCreate] = useState(false);
  const [incidentForm, setIncidentForm] = useState({
    incident_date: new Date().toISOString().slice(0, 10),
    incident_type: 'near_miss' as string,
    description: '',
    severity: 'minor' as string,
    treatment_type: '' as string,
    location: '',
    days_lost: 0,
  });
  const [incidentErrors, setIncidentErrors] = useState<Record<string, string>>({});
  const incidentDateRef = useRef<HTMLInputElement>(null);

  // Auto-focus incident date when modal opens
  useEffect(() => {
    if (showCreate && incidentDateRef.current) {
      setTimeout(() => incidentDateRef.current?.focus(), 100);
    }
  }, [showCreate]);

  const canSubmitIncident = !!incidentForm.incident_date && incidentForm.description.trim().length > 0;

  const validateIncident = (): boolean => {
    const e: Record<string, string> = {};
    if (!incidentForm.incident_date) e.incident_date = t('validation.required', { defaultValue: 'This field is required' });
    if (!incidentForm.description.trim()) e.description = t('validation.required', { defaultValue: 'This field is required' });
    setIncidentErrors(e);
    return Object.keys(e).length === 0;
  };

  // Escape key handler for inline modal
  useEffect(() => {
    if (!showCreate) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setShowCreate(false);
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [showCreate]);

  const createMut = useMutation({
    mutationFn: (data: typeof incidentForm) =>
      apiPost('/v1/safety/incidents/', {
        project_id: projectId,
        incident_date: data.incident_date,
        incident_type: data.incident_type,
        description: data.description,
        severity: data.severity,
        treatment_type: data.treatment_type || undefined,
        location: data.location || undefined,
        days_lost: data.days_lost || 0,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['safety-incidents', projectId] });
      setShowCreate(false);
      setIncidentForm({
        incident_date: new Date().toISOString().slice(0, 10),
        incident_type: 'near_miss',
        description: '',
        severity: 'minor',
        treatment_type: '',
        location: '',
        days_lost: 0,
      });
      addToast({ type: 'success', title: t('safety.incident_created', { defaultValue: 'Incident reported successfully' }) });
    },
    onError: (e: Error) =>
      addToast({ type: 'error', title: t('safety.incident_create_failed', { defaultValue: 'Failed to report incident' }), message: e.message }),
  });

  const exportMut = useMutation({
    mutationFn: () =>
      downloadExcelExport(
        `/v1/safety/incidents/export?project_id=${projectId}`,
        'safety_incidents.xlsx',
      ),
    onSuccess: () =>
      addToast({
        type: 'success',
        title: t('safety.export_success', { defaultValue: 'Safety data exported successfully' }),
      }),
    onError: (e: Error) =>
      addToast({
        type: 'error',
        title: t('safety.export_failed', { defaultValue: 'Failed to export safety data' }),
        message: e.message,
      }),
  });

  const { data: incidents, isLoading } = useQuery({
    queryKey: ['safety-incidents', projectId],
    queryFn: () =>
      apiGet<Incident[]>(
        `/v1/safety/incidents?project_id=${projectId}`,
      ),
    select: (d): Incident[] => normalizeListResponse(d),
  });

  const filtered = useMemo(() => {
    if (!incidents) return [];
    if (!search) return incidents;
    const q = search.toLowerCase();
    return incidents.filter(
      (inc) =>
        inc.incident_number.toLowerCase().includes(q) ||
        inc.description.toLowerCase().includes(q) ||
        inc.type.toLowerCase().includes(q),
    );
  }, [incidents, search]);

  if (isLoading) return <SkeletonTable rows={5} columns={7} />;

  const isEmpty = !incidents || incidents.length === 0;

  return (
    <>
    {isEmpty ? (
      <EmptyState
        icon={<ShieldAlert size={28} strokeWidth={1.5} />}
        title={t('safety.no_incidents', {
          defaultValue: 'No incidents reported',
        })}
        description={t('safety.no_incidents_desc', {
          defaultValue: 'Report workplace incidents to track injuries, near misses, and property damage. All records are logged for compliance reporting.',
        })}
        action={{
          label: t('safety.report_incident', { defaultValue: 'Report Incident' }),
          onClick: () => setShowCreate(true),
        }}
      />
    ) : (
    <Card padding="none">
      {/* Search + Export + New */}
      <div className="p-4 border-b border-border-light flex items-center gap-3">
        <div className="relative max-w-sm flex-1">
          <div className="pointer-events-none absolute inset-y-0 left-0 flex items-center pl-3 text-content-tertiary">
            <Search size={16} />
          </div>
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder={t('safety.search_incidents', {
              defaultValue: 'Search incidents...',
            })}
            className="h-10 w-full rounded-lg border border-border bg-surface-primary pl-10 pr-3 text-sm text-content-primary placeholder:text-content-tertiary focus:outline-none focus:ring-2 focus:ring-oe-blue focus:border-transparent"
          />
        </div>
        <Button
          variant="secondary"
          size="sm"
          icon={
            exportMut.isPending ? (
              <Loader2 size={14} className="animate-spin" />
            ) : (
              <Download size={14} />
            )
          }
          onClick={() => exportMut.mutate()}
          disabled={exportMut.isPending}
        >
          {t('common.export_excel', { defaultValue: 'Export Excel' })}
        </Button>
        <Button
          variant="primary"
          size="sm"
          icon={<Plus size={14} />}
          onClick={() => setShowCreate(true)}
        >
          {t('safety.report_incident_btn', { defaultValue: 'Report Incident' })}
        </Button>
      </div>

      {/* Desktop table */}
      <div className="hidden md:block overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border-light bg-surface-secondary/50">
              <th className="px-4 py-3 text-left font-medium text-content-tertiary">
                {t('safety.incident_number', { defaultValue: 'Incident #' })}
              </th>
              <th className="px-4 py-3 text-left font-medium text-content-tertiary">
                {t('safety.date', { defaultValue: 'Date' })}
              </th>
              <th className="px-4 py-3 text-center font-medium text-content-tertiary">
                {t('safety.type', { defaultValue: 'Type' })}
              </th>
              <th className="px-4 py-3 text-center font-medium text-content-tertiary">
                {t('safety.severity', { defaultValue: 'Severity' })}
              </th>
              <th className="px-4 py-3 text-left font-medium text-content-tertiary">
                {t('safety.treatment', { defaultValue: 'Treatment' })}
              </th>
              <th className="px-4 py-3 text-center font-medium text-content-tertiary">
                {t('safety.days_lost', { defaultValue: 'Days Lost' })}
              </th>
              <th className="px-4 py-3 text-center font-medium text-content-tertiary">
                {t('common.status', { defaultValue: 'Status' })}
              </th>
            </tr>
          </thead>
          <tbody>
            {filtered.length === 0 ? (
              <tr>
                <td colSpan={7} className="px-4 py-8 text-center text-sm text-content-tertiary">
                  {t('safety.no_incidents_match', { defaultValue: 'No matching incidents' })}
                </td>
              </tr>
            ) : filtered.map((inc) => (
              <tr
                key={inc.id}
                className="border-b border-border-light hover:bg-surface-secondary/30 transition-colors"
              >
                <td className="px-4 py-3 font-mono text-xs text-content-primary">
                  {inc.incident_number}
                </td>
                <td className="px-4 py-3 text-content-secondary">
                  <DateDisplay value={inc.date} />
                </td>
                <td className="px-4 py-3 text-center">
                  <Badge
                    variant={INCIDENT_TYPE_COLORS[inc.type] ?? 'neutral'}
                    size="sm"
                  >
                    {t(`safety.type_${inc.type}`, {
                      defaultValue: inc.type.replace(/_/g, ' '),
                    })}
                  </Badge>
                </td>
                <td className="px-4 py-3 text-center">
                  <Badge
                    variant={INCIDENT_SEVERITY_COLORS[inc.severity] ?? 'neutral'}
                    size="sm"
                  >
                    {t(`safety.severity_${inc.severity}`, {
                      defaultValue: inc.severity,
                    })}
                  </Badge>
                </td>
                <td className="px-4 py-3 text-content-secondary text-xs">
                  {inc.treatment || '\u2014'}
                </td>
                <td className="px-4 py-3 text-center tabular-nums">
                  {inc.days_lost > 0 ? (
                    <span className="font-medium text-semantic-error">
                      {inc.days_lost}
                    </span>
                  ) : (
                    <span className="text-content-tertiary">0</span>
                  )}
                </td>
                <td className="px-4 py-3 text-center">
                  <Badge
                    variant={INCIDENT_STATUS_COLORS[inc.status] ?? 'neutral'}
                    size="sm"
                  >
                    {t(`safety.status_${inc.status}`, {
                      defaultValue: inc.status,
                    })}
                  </Badge>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Mobile card view */}
      <div className="md:hidden p-4 space-y-3">
        {filtered.length === 0 ? (
          <p className="text-center text-sm text-content-tertiary py-4">
            {t('safety.no_incidents_match', { defaultValue: 'No matching incidents' })}
          </p>
        ) : filtered.map((inc) => (
          <Card key={inc.id} className="p-4">
            <div className="flex items-center justify-between mb-2">
              <div>
                <span className="text-xs font-mono text-content-tertiary">{inc.incident_number}</span>
                <span className="ml-2 text-xs text-content-secondary"><DateDisplay value={inc.date} /></span>
              </div>
              <Badge variant={INCIDENT_STATUS_COLORS[inc.status] ?? 'neutral'} size="sm">
                {t(`safety.status_${inc.status}`, { defaultValue: inc.status })}
              </Badge>
            </div>
            <p className="text-sm text-content-primary line-clamp-2 mb-2">{inc.description}</p>
            <div className="flex items-center gap-2 flex-wrap">
              <Badge variant={INCIDENT_TYPE_COLORS[inc.type] ?? 'neutral'} size="sm">
                {t(`safety.type_${inc.type}`, { defaultValue: inc.type.replace(/_/g, ' ') })}
              </Badge>
              <Badge variant={INCIDENT_SEVERITY_COLORS[inc.severity] ?? 'neutral'} size="sm">
                {t(`safety.severity_${inc.severity}`, { defaultValue: inc.severity })}
              </Badge>
              {inc.days_lost > 0 && (
                <span className="text-xs font-medium text-semantic-error">{inc.days_lost} {t('safety.days_lost', { defaultValue: 'days lost' })}</span>
              )}
            </div>
          </Card>
        ))}
      </div>
    </Card>
    )}

    {/* New Incident Modal */}
    {showCreate && (
      <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm animate-fade-in">
        <div className="w-full max-w-2xl bg-surface-elevated rounded-xl shadow-xl border border-border animate-card-in mx-4 max-h-[90vh] overflow-y-auto" role="dialog" aria-label={t('safety.new_incident', { defaultValue: 'New Incident' })}>
          <div className="flex items-center justify-between px-6 py-4 border-b border-border-light">
            <h2 className="text-lg font-semibold text-content-primary">
              {t('safety.new_incident', { defaultValue: 'New Incident' })}
            </h2>
            <button
              onClick={() => setShowCreate(false)}
              aria-label={t('common.close', { defaultValue: 'Close' })}
              className="flex h-8 w-8 items-center justify-center rounded-lg text-content-tertiary hover:bg-surface-secondary hover:text-content-primary transition-colors"
            >
              <X size={18} />
            </button>
          </div>
          <div className="px-6 py-4 space-y-5">
            {/* ── Incident Type Cards ── */}
            <div>
              <label className="block text-sm font-medium text-content-primary mb-2">
                {t('safety.type', { defaultValue: 'Incident Type' })}
              </label>
              <div className="grid grid-cols-3 sm:grid-cols-5 gap-2">
                {INCIDENT_TYPES_LIST.map((tp) => {
                  const cfg = getIncidentTypeCards(t)[tp]!;
                  const TypeIcon = cfg.icon;
                  const selected = incidentForm.incident_type === tp;
                  return (
                    <button
                      key={tp}
                      type="button"
                      onClick={() => setIncidentForm((f) => ({ ...f, incident_type: tp }))}
                      className={clsx(
                        'flex flex-col items-center gap-1.5 rounded-lg border-2 px-2 py-2.5 text-center transition-all',
                        selected
                          ? cfg.color + ' ring-2 ring-oe-blue/30'
                          : 'border-border bg-surface-primary text-content-tertiary hover:border-border-light hover:bg-surface-secondary',
                      )}
                    >
                      <TypeIcon size={18} />
                      <span className="text-2xs font-medium leading-tight">
                        {t(`safety.type_${tp}`, {
                          defaultValue: tp.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase()),
                        })}
                      </span>
                    </button>
                  );
                })}
              </div>
              <p className="mt-1.5 text-xs text-content-quaternary">
                {t(`safety.type_${incidentForm.incident_type}_desc`, {
                  defaultValue: getIncidentTypeCards(t)[incidentForm.incident_type]?.description || '',
                })}
              </p>
            </div>

            {/* ── Incident Details Section ── */}
            <div className="flex items-center gap-2 pt-2 pb-1">
              <ShieldAlert size={14} className="text-content-tertiary" />
              <span className="text-xs font-semibold uppercase tracking-wider text-content-tertiary">
                {t('safety.section_incident_details', { defaultValue: 'Incident Details' })}
              </span>
              <div className="flex-1 h-px bg-border-light" />
            </div>

            {/* Date */}
            <div>
              <label className="block text-sm font-medium text-content-primary mb-1.5">
                {t('safety.date', { defaultValue: 'Date' })} <span className="text-semantic-error">*</span>
              </label>
              <input
                ref={incidentDateRef}
                type="date"
                value={incidentForm.incident_date}
                onChange={(e) => {
                  setIncidentForm((f) => ({ ...f, incident_date: e.target.value }));
                  if (incidentErrors.incident_date) setIncidentErrors((prev) => { const next = { ...prev }; delete next.incident_date; return next; });
                }}
                className={clsx(inputCls, incidentErrors.incident_date && 'border-semantic-error focus:ring-red-300 focus:border-semantic-error')}
              />
              {incidentErrors.incident_date && <p className="mt-1 text-xs text-semantic-error">{incidentErrors.incident_date}</p>}
            </div>

            {/* Description */}
            <div>
              <label className="block text-sm font-medium text-content-primary mb-1.5">
                {t('tasks.field_description', { defaultValue: 'Description' })} <span className="text-semantic-error">*</span>
              </label>
              <textarea
                value={incidentForm.description}
                onChange={(e) => {
                  setIncidentForm((f) => ({ ...f, description: e.target.value }));
                  if (incidentErrors.description) setIncidentErrors((prev) => { const next = { ...prev }; delete next.description; return next; });
                }}
                rows={3}
                className={clsx(textareaCls, incidentErrors.description && 'border-semantic-error focus:ring-red-300 focus:border-semantic-error')}
                placeholder={t('safety.incident_desc_placeholder', { defaultValue: 'Describe what happened...' })}
              />
              {incidentErrors.description && <p className="mt-1 text-xs text-semantic-error">{incidentErrors.description}</p>}
            </div>

            {/* Location */}
            <div>
              <label className="block text-sm font-medium text-content-primary mb-1.5">
                {t('safety.location', { defaultValue: 'Location' })}
              </label>
              <input
                value={incidentForm.location}
                onChange={(e) => setIncidentForm((f) => ({ ...f, location: e.target.value }))}
                className={inputCls}
                placeholder={t('safety.location_placeholder', { defaultValue: 'e.g. Building A, Level 3' })}
              />
            </div>

            {/* ── Impact Section ── */}
            <div className="flex items-center gap-2 pt-2 pb-1">
              <Heart size={14} className="text-content-tertiary" />
              <span className="text-xs font-semibold uppercase tracking-wider text-content-tertiary">
                {t('safety.section_impact', { defaultValue: 'Impact' })}
              </span>
              <div className="flex-1 h-px bg-border-light" />
            </div>

            {/* Treatment Type - Visual Toggle */}
            <div>
              <label className="block text-sm font-medium text-content-primary mb-2">
                {t('safety.treatment', { defaultValue: 'Treatment Type' })}
              </label>
              <div className="grid grid-cols-4 gap-2">
                {getTreatmentOptions(t).map((opt) => {
                  const selected = incidentForm.treatment_type === opt.value;
                  return (
                    <button
                      key={opt.value}
                      type="button"
                      onClick={() => setIncidentForm((f) => ({ ...f, treatment_type: opt.value }))}
                      className={clsx(
                        'flex items-center justify-center gap-1.5 rounded-lg border-2 px-3 py-2.5 transition-all text-center',
                        selected
                          ? opt.value === 'hospital'
                            ? 'text-red-600 bg-red-50 border-red-200 ring-2 ring-red-300 dark:text-red-400 dark:bg-red-950/30 dark:border-red-800'
                            : opt.value === 'medical'
                              ? 'text-orange-600 bg-orange-50 border-orange-200 ring-2 ring-orange-300 dark:text-orange-400 dark:bg-orange-950/30 dark:border-orange-800'
                              : opt.value === 'first_aid'
                                ? 'text-amber-600 bg-amber-50 border-amber-200 ring-2 ring-amber-300 dark:text-amber-400 dark:bg-amber-950/30 dark:border-amber-800'
                                : 'text-gray-600 bg-gray-50 border-gray-200 ring-2 ring-gray-300 dark:text-gray-400 dark:bg-gray-800/50 dark:border-gray-700'
                          : 'border-border bg-surface-primary text-content-tertiary hover:border-border-light hover:bg-surface-secondary',
                      )}
                    >
                      <span className="text-xs font-semibold">
                        {t(`safety.treatment_${opt.value || 'none'}`, { defaultValue: opt.label })}
                      </span>
                    </button>
                  );
                })}
              </div>
            </div>

            {/* Days Lost - only show if treatment is Medical or Hospital */}
            {(incidentForm.treatment_type === 'medical' || incidentForm.treatment_type === 'hospital') && (
              <div className="animate-fade-in">
                <label className="block text-sm font-medium text-content-primary mb-1.5">
                  {t('safety.days_lost', { defaultValue: 'Days Lost' })}
                </label>
                <input
                  type="number"
                  min="0"
                  value={incidentForm.days_lost || ''}
                  onChange={(e) => setIncidentForm((f) => ({ ...f, days_lost: Number(e.target.value) || 0 }))}
                  className={inputCls + ' max-w-[120px]'}
                  placeholder="0"
                />
                <p className="mt-1 text-xs text-content-quaternary">
                  {t('safety.days_lost_hint', { defaultValue: 'Number of working days lost due to the incident' })}
                </p>
              </div>
            )}
          </div>
          <div className="flex items-center justify-end gap-3 px-6 py-4 border-t border-border-light">
            <Button variant="ghost" onClick={() => setShowCreate(false)} disabled={createMut.isPending}>
              {t('common.cancel', { defaultValue: 'Cancel' })}
            </Button>
            <Button
              variant="primary"
              onClick={() => {
                if (!validateIncident()) return;
                createMut.mutate(incidentForm);
              }}
              disabled={createMut.isPending || !canSubmitIncident}
            >
              {createMut.isPending ? (
                <Loader2 size={16} className="animate-spin mr-1.5" />
              ) : (
                <Plus size={16} className="mr-1.5" />
              )}
              <span>{t('safety.report_incident', { defaultValue: 'Report Incident' })}</span>
            </Button>
          </div>
        </div>
      </div>
    )}
    </>
  );
}

/* ── Observations Tab ─────────────────────────────────────────────────── */

function ObservationsTab({ projectId }: { projectId: string }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [search, setSearch] = useState('');
  const addToast = useToastStore((s) => s.addToast);
  const [showCreate, setShowCreate] = useState(false);
  const [obsForm, setObsForm] = useState({
    observation_type: 'unsafe_condition' as string,
    description: '',
    location: '',
    severity: 3,
    likelihood: 3,
  });
  const [obsErrors, setObsErrors] = useState<Record<string, string>>({});

  const canSubmitObs = obsForm.description.trim().length > 0;

  const validateObs = (): boolean => {
    const e: Record<string, string> = {};
    if (!obsForm.description.trim()) e.description = t('validation.required', { defaultValue: 'This field is required' });
    setObsErrors(e);
    return Object.keys(e).length === 0;
  };

  // Escape key handler for inline modal
  useEffect(() => {
    if (!showCreate) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setShowCreate(false);
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [showCreate]);

  const computedRisk = obsForm.severity * obsForm.likelihood;

  const createObsMut = useMutation({
    mutationFn: (data: typeof obsForm) =>
      apiPost('/v1/safety/observations/', {
        project_id: projectId,
        observation_type: data.observation_type,
        description: data.description,
        location: data.location || undefined,
        severity: data.severity,
        likelihood: data.likelihood,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['safety-observations', projectId] });
      setShowCreate(false);
      setObsForm({ observation_type: 'unsafe_condition', description: '', location: '', severity: 3, likelihood: 3 });
      addToast({ type: 'success', title: t('safety.observation_created', { defaultValue: 'Safety observation recorded successfully' }) });
    },
    onError: (e: Error) =>
      addToast({ type: 'error', title: t('safety.observation_create_failed', { defaultValue: 'Failed to record observation' }), message: e.message }),
  });

  const exportMut = useMutation({
    mutationFn: () =>
      downloadExcelExport(
        `/v1/safety/observations/export?project_id=${projectId}`,
        'safety_observations.xlsx',
      ),
    onSuccess: () =>
      addToast({
        type: 'success',
        title: t('safety.obs_export_success', { defaultValue: 'Observations exported successfully' }),
      }),
    onError: (e: Error) =>
      addToast({
        type: 'error',
        title: t('safety.obs_export_failed', { defaultValue: 'Failed to export observations' }),
        message: e.message,
      }),
  });

  const { data: observations, isLoading } = useQuery({
    queryKey: ['safety-observations', projectId],
    queryFn: () =>
      apiGet<Observation[]>(
        `/v1/safety/observations?project_id=${projectId}`,
      ),
    select: (d): Observation[] => normalizeListResponse(d),
  });

  const filtered = useMemo(() => {
    if (!observations) return [];
    if (!search) return observations;
    const q = search.toLowerCase();
    return observations.filter(
      (obs) =>
        obs.observation_number.toLowerCase().includes(q) ||
        obs.description.toLowerCase().includes(q) ||
        obs.type.toLowerCase().includes(q),
    );
  }, [observations, search]);

  if (isLoading) return <SkeletonTable rows={5} columns={6} />;

  const isEmpty = !observations || observations.length === 0;

  return (
    <>
    {isEmpty ? (
      <EmptyState
        icon={<Eye size={28} strokeWidth={1.5} />}
        title={t('safety.no_observations', {
          defaultValue: 'No observations yet',
        })}
        description={t('safety.no_observations_desc', {
          defaultValue: 'Record safety observations to identify hazards, track unsafe conditions, and reinforce positive safety behavior on site.',
        })}
        action={{
          label: t('safety.report_observation_btn', { defaultValue: 'Report Observation' }),
          onClick: () => setShowCreate(true),
        }}
      />
    ) : (
    <Card padding="none">
      {/* Search + Export + New */}
      <div className="p-4 border-b border-border-light flex items-center gap-3">
        <div className="relative max-w-sm flex-1">
          <div className="pointer-events-none absolute inset-y-0 left-0 flex items-center pl-3 text-content-tertiary">
            <Search size={16} />
          </div>
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder={t('safety.search_observations', {
              defaultValue: 'Search observations...',
            })}
            className="h-10 w-full rounded-lg border border-border bg-surface-primary pl-10 pr-3 text-sm text-content-primary placeholder:text-content-tertiary focus:outline-none focus:ring-2 focus:ring-oe-blue focus:border-transparent"
          />
        </div>
        <Button
          variant="secondary"
          size="sm"
          icon={
            exportMut.isPending ? (
              <Loader2 size={14} className="animate-spin" />
            ) : (
              <Download size={14} />
            )
          }
          onClick={() => exportMut.mutate()}
          disabled={exportMut.isPending}
        >
          {t('common.export_excel', { defaultValue: 'Export Excel' })}
        </Button>
        <Button
          variant="primary"
          size="sm"
          icon={<Plus size={14} />}
          onClick={() => setShowCreate(true)}
        >
          {t('safety.report_observation_btn', { defaultValue: 'Report Observation' })}
        </Button>
      </div>

      {/* Desktop table */}
      <div className="hidden md:block overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border-light bg-surface-secondary/50">
              <th className="px-4 py-3 text-left font-medium text-content-tertiary">
                {t('safety.observation_number', { defaultValue: 'Observation #' })}
              </th>
              <th className="px-4 py-3 text-left font-medium text-content-tertiary">
                {t('safety.date', { defaultValue: 'Date' })}
              </th>
              <th className="px-4 py-3 text-center font-medium text-content-tertiary">
                {t('safety.type', { defaultValue: 'Type' })}
              </th>
              <th className="px-4 py-3 text-center font-medium text-content-tertiary">
                {t('safety.severity', { defaultValue: 'Severity' })}
              </th>
              <th className="px-4 py-3 text-center font-medium text-content-tertiary">
                {t('safety.risk_score', { defaultValue: 'Risk Score' })}
              </th>
              <th className="px-4 py-3 text-center font-medium text-content-tertiary">
                {t('common.status', { defaultValue: 'Status' })}
              </th>
            </tr>
          </thead>
          <tbody>
            {filtered.length === 0 ? (
              <tr>
                <td colSpan={6} className="px-4 py-8 text-center text-sm text-content-tertiary">
                  {t('safety.no_observations_match', { defaultValue: 'No matching observations' })}
                </td>
              </tr>
            ) : filtered.map((obs) => (
              <tr
                key={obs.id}
                className="border-b border-border-light hover:bg-surface-secondary/30 transition-colors"
              >
                <td className="px-4 py-3 font-mono text-xs text-content-primary">
                  {obs.observation_number}
                </td>
                <td className="px-4 py-3 text-content-secondary">
                  <DateDisplay value={obs.date} />
                </td>
                <td className="px-4 py-3 text-center">
                  <Badge
                    variant={OBS_TYPE_COLORS[obs.type] ?? 'neutral'}
                    size="sm"
                  >
                    {t(`safety.obs_type_${obs.type}`, {
                      defaultValue: obs.type.replace(/_/g, ' '),
                    })}
                  </Badge>
                </td>
                <td className="px-4 py-3">
                  <div className="flex justify-center">
                    <SeverityDots level={obs.severity} />
                  </div>
                </td>
                <td className="px-4 py-3 text-center">
                  <span
                    className={`inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-semibold ${riskScoreColor(obs.risk_score)}`}
                  >
                    {obs.risk_score}
                    <span className="text-2xs font-normal opacity-80">
                      {riskScoreLabel(obs.risk_score, t)}
                    </span>
                  </span>
                </td>
                <td className="px-4 py-3 text-center">
                  <Badge
                    variant={OBS_STATUS_COLORS[obs.status] ?? 'neutral'}
                    size="sm"
                  >
                    {t(`safety.obs_status_${obs.status}`, {
                      defaultValue: obs.status.replace(/_/g, ' '),
                    })}
                  </Badge>
                  {obs.risk_score > 15 && (
                    <div className="text-2xs text-red-600 mt-1">
                      {t('safety.high_risk_hint', { defaultValue: 'High risk \u2014 consider scheduling an inspection' })}
                      <Button variant="ghost" size="sm" className="text-2xs ml-1" onClick={(e) => { e.stopPropagation(); navigate('/inspections'); }}>
                        {t('safety.create_inspection_link', { defaultValue: 'Create Inspection \u2192' })}
                      </Button>
                    </div>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Mobile card view */}
      <div className="md:hidden p-4 space-y-3">
        {filtered.length === 0 ? (
          <p className="text-center text-sm text-content-tertiary py-4">
            {t('safety.no_observations_match', { defaultValue: 'No matching observations' })}
          </p>
        ) : filtered.map((obs) => (
          <Card key={obs.id} className="p-4">
            <div className="flex items-center justify-between mb-2">
              <div>
                <span className="text-xs font-mono text-content-tertiary">{obs.observation_number}</span>
                <span className="ml-2 text-xs text-content-secondary"><DateDisplay value={obs.date} /></span>
              </div>
              <Badge variant={OBS_STATUS_COLORS[obs.status] ?? 'neutral'} size="sm">
                {t(`safety.obs_status_${obs.status}`, { defaultValue: obs.status.replace(/_/g, ' ') })}
              </Badge>
            </div>
            <p className="text-sm text-content-primary line-clamp-2 mb-2">{obs.description}</p>
            <div className="flex items-center gap-2 flex-wrap">
              <Badge variant={OBS_TYPE_COLORS[obs.type] ?? 'neutral'} size="sm">
                {t(`safety.obs_type_${obs.type}`, { defaultValue: obs.type.replace(/_/g, ' ') })}
              </Badge>
              <SeverityDots level={obs.severity} />
              <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-semibold ${riskScoreColor(obs.risk_score)}`}>
                {obs.risk_score} {riskScoreLabel(obs.risk_score, t)}
              </span>
            </div>
            {obs.risk_score > 15 && (
              <div className="text-2xs text-red-600 mt-2">
                {t('safety.high_risk_hint', { defaultValue: 'High risk \u2014 consider scheduling an inspection' })}
                <Button variant="ghost" size="sm" className="text-2xs ml-1" onClick={() => navigate('/inspections')}>
                  {t('safety.create_inspection_link', { defaultValue: 'Create Inspection \u2192' })}
                </Button>
              </div>
            )}
          </Card>
        ))}
      </div>
    </Card>
    )}

    {/* New Observation Modal */}
    {showCreate && (
      <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm animate-fade-in">
        <div className="w-full max-w-2xl bg-surface-elevated rounded-xl shadow-xl border border-border animate-card-in mx-4 max-h-[90vh] overflow-y-auto" role="dialog" aria-label={t('safety.new_observation', { defaultValue: 'New Observation' })}>
          <div className="flex items-center justify-between px-6 py-4 border-b border-border-light">
            <h2 className="text-lg font-semibold text-content-primary">
              {t('safety.new_observation', { defaultValue: 'New Observation' })}
            </h2>
            <button
              onClick={() => setShowCreate(false)}
              aria-label={t('common.close', { defaultValue: 'Close' })}
              className="flex h-8 w-8 items-center justify-center rounded-lg text-content-tertiary hover:bg-surface-secondary hover:text-content-primary transition-colors"
            >
              <X size={18} />
            </button>
          </div>
          <div className="px-6 py-4 space-y-5">
            {/* ── Observation Type Cards ── */}
            <div>
              <label className="block text-sm font-medium text-content-primary mb-2">
                {t('safety.type', { defaultValue: 'Observation Type' })}
              </label>
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                {OBS_TYPES_LIST.map((tp) => {
                  const cfg = getObsTypeCards(t)[tp]!;
                  const TypeIcon = cfg.icon;
                  const selected = obsForm.observation_type === tp;
                  return (
                    <button
                      key={tp}
                      type="button"
                      onClick={() => setObsForm((f) => ({ ...f, observation_type: tp }))}
                      className={clsx(
                        'flex flex-col items-center gap-1.5 rounded-lg border-2 px-2 py-2.5 text-center transition-all',
                        selected
                          ? cfg.color + ' ring-2 ring-oe-blue/30'
                          : 'border-border bg-surface-primary text-content-tertiary hover:border-border-light hover:bg-surface-secondary',
                      )}
                    >
                      <TypeIcon size={18} />
                      <span className="text-2xs font-medium leading-tight">
                        {t(`safety.obs_type_${tp}`, {
                          defaultValue: tp.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase()),
                        })}
                      </span>
                    </button>
                  );
                })}
              </div>
              <p className="mt-1.5 text-xs text-content-quaternary">
                {t(`safety.obs_type_${obsForm.observation_type}_desc`, {
                  defaultValue: getObsTypeCards(t)[obsForm.observation_type]?.description || '',
                })}
              </p>
            </div>

            {/* Description */}
            <div>
              <label className="block text-sm font-medium text-content-primary mb-1.5">
                {t('tasks.field_description', { defaultValue: 'Description' })} <span className="text-semantic-error">*</span>
              </label>
              <textarea
                value={obsForm.description}
                onChange={(e) => {
                  setObsForm((f) => ({ ...f, description: e.target.value }));
                  if (obsErrors.description) setObsErrors((prev) => { const next = { ...prev }; delete next.description; return next; });
                }}
                rows={3}
                className={clsx(textareaCls, obsErrors.description && 'border-semantic-error focus:ring-red-300 focus:border-semantic-error')}
                placeholder={t('safety.obs_desc_placeholder', { defaultValue: 'Describe the observation...' })}
              />
              {obsErrors.description && <p className="mt-1 text-xs text-semantic-error">{obsErrors.description}</p>}
            </div>

            {/* Location */}
            <div>
              <label className="block text-sm font-medium text-content-primary mb-1.5">
                {t('safety.location', { defaultValue: 'Location' })}
              </label>
              <input
                value={obsForm.location}
                onChange={(e) => setObsForm((f) => ({ ...f, location: e.target.value }))}
                className={inputCls}
                placeholder={t('safety.location_placeholder', { defaultValue: 'e.g. Building A, Level 3' })}
              />
            </div>

            {/* ── Severity Visual 1-5 Scale ── */}
            <div>
              <label className="block text-sm font-medium text-content-primary mb-2">
                {t('safety.severity', { defaultValue: 'Severity' })}
              </label>
              <div className="flex items-center gap-2">
                <div className="flex items-center gap-1.5">
                  {[1, 2, 3, 4, 5].map((v) => (
                    <button
                      key={v}
                      type="button"
                      onClick={() => setObsForm((f) => ({ ...f, severity: v }))}
                      className="p-0.5 transition-transform hover:scale-110"
                      aria-label={`${t('safety.severity', { defaultValue: 'Severity' })} ${v}`}
                    >
                      <span
                        className={clsx(
                          'inline-block h-5 w-5 rounded-full transition-colors',
                          v <= obsForm.severity
                            ? obsForm.severity >= 4
                              ? 'bg-red-500'
                              : obsForm.severity >= 3
                                ? 'bg-orange-400'
                                : obsForm.severity >= 2
                                  ? 'bg-yellow-400'
                                  : 'bg-green-400'
                            : 'bg-surface-tertiary',
                        )}
                      />
                    </button>
                  ))}
                </div>
                <span className="text-sm font-medium text-content-secondary ml-2">
                  {obsForm.severity}/5
                </span>
              </div>
            </div>

            {/* ── Likelihood Visual 1-5 Scale ── */}
            <div>
              <label className="block text-sm font-medium text-content-primary mb-2">
                {t('safety.likelihood', { defaultValue: 'Likelihood' })}
              </label>
              <div className="flex items-center gap-2">
                <div className="flex items-center gap-1.5">
                  {[1, 2, 3, 4, 5].map((v) => (
                    <button
                      key={v}
                      type="button"
                      onClick={() => setObsForm((f) => ({ ...f, likelihood: v }))}
                      className="p-0.5 transition-transform hover:scale-110"
                      aria-label={`${t('safety.likelihood', { defaultValue: 'Likelihood' })} ${v}`}
                    >
                      <span
                        className={clsx(
                          'inline-block h-5 w-5 rounded-full transition-colors',
                          v <= obsForm.likelihood
                            ? obsForm.likelihood >= 4
                              ? 'bg-red-500'
                              : obsForm.likelihood >= 3
                                ? 'bg-orange-400'
                                : obsForm.likelihood >= 2
                                  ? 'bg-yellow-400'
                                  : 'bg-green-400'
                            : 'bg-surface-tertiary',
                        )}
                      />
                    </button>
                  ))}
                </div>
                <span className="text-sm font-medium text-content-secondary ml-2">
                  {obsForm.likelihood}/5
                </span>
              </div>
            </div>

            {/* Computed risk score */}
            <div className="rounded-lg bg-surface-secondary p-3">
              <div className="flex items-center justify-between">
                <span className="text-sm font-medium text-content-secondary">
                  {t('safety.risk_score', { defaultValue: 'Risk Score' })}
                </span>
                <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-sm font-semibold ${riskScoreColor(computedRisk)}`}>
                  {computedRisk}
                  <span className="text-xs font-normal opacity-80">
                    {riskScoreLabel(computedRisk, t)}
                  </span>
                </span>
              </div>
              <p className="text-xs text-content-quaternary mt-1">
                {t('safety.risk_formula', { defaultValue: 'Severity x Likelihood = {{score}}', score: computedRisk })}
              </p>
            </div>
          </div>
          <div className="flex items-center justify-end gap-3 px-6 py-4 border-t border-border-light">
            <Button variant="ghost" onClick={() => setShowCreate(false)} disabled={createObsMut.isPending}>
              {t('common.cancel', { defaultValue: 'Cancel' })}
            </Button>
            <Button
              variant="primary"
              onClick={() => {
                if (!validateObs()) return;
                createObsMut.mutate(obsForm);
              }}
              disabled={createObsMut.isPending || !canSubmitObs}
            >
              {createObsMut.isPending ? (
                <Loader2 size={16} className="animate-spin mr-1.5" />
              ) : (
                <Plus size={16} className="mr-1.5" />
              )}
              <span>{t('safety.record_observation', { defaultValue: 'Record Observation' })}</span>
            </Button>
          </div>
        </div>
      </div>
    )}
    </>
  );
}
