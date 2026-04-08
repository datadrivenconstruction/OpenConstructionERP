import { useState, useMemo, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { useParams } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import clsx from 'clsx';
import {
  ShieldAlert,
  Eye,
  Search,
  HardHat,
  Download,
  Loader2,
  Plus,
  X,
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

/* ── Main Page ────────────────────────────────────────────────────────── */

const inputCls =
  'h-10 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';
const textareaCls =
  'w-full rounded-lg border border-border bg-surface-primary px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue resize-none';

export function SafetyPage() {
  const { t } = useTranslation();
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
    <div className="max-w-content mx-auto animate-fade-in">
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
            defaultValue: 'Incident tracking and safety observations',
          })}
        </p>
      </div>

      {/* No-project warning */}
      {!projectId && (
        <div className="mb-6 rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800 dark:border-amber-800 dark:bg-amber-950/30 dark:text-amber-300">
          {t('common.select_project_first', { defaultValue: 'Please select a project to continue.' })}
        </div>
      )}

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
      {!projectId ? (
        <EmptyState
          icon={<HardHat size={24} strokeWidth={1.5} />}
          title={t('safety.no_project', {
            defaultValue: 'No project selected',
          })}
          description={t('safety.select_project', {
            defaultValue:
              'Open a project first to view its safety data',
          })}
        />
      ) : (
        <>
          {activeTab === 'incidents' && (
            <IncidentsTab projectId={projectId} />
          )}
          {activeTab === 'observations' && (
            <ObservationsTab projectId={projectId} />
          )}
        </>
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
  });

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
      apiPost('/v1/safety/incidents', {
        project_id: projectId,
        incident_date: data.incident_date,
        incident_type: data.incident_type,
        description: data.description,
        treatment_type: data.treatment_type || undefined,
        location: data.location || undefined,
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
      });
      addToast({ type: 'success', title: t('safety.incident_created', { defaultValue: 'Incident reported' }) });
    },
    onError: (e: Error) =>
      addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: e.message }),
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
        title: t('safety.export_success', { defaultValue: 'Export complete' }),
      }),
    onError: (e: Error) =>
      addToast({
        type: 'error',
        title: t('common.error', { defaultValue: 'Error' }),
        message: e.message,
      }),
  });

  const { data: incidents, isLoading } = useQuery({
    queryKey: ['safety-incidents', projectId],
    queryFn: () =>
      apiGet<Incident[]>(
        `/v1/safety/incidents?project_id=${projectId}`,
      ),
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

  if (!incidents || incidents.length === 0) {
    return (
      <EmptyState
        icon={<ShieldAlert size={24} strokeWidth={1.5} />}
        title={t('safety.no_incidents', {
          defaultValue: 'No incidents reported',
        })}
        description={t('safety.no_incidents_desc', {
          defaultValue: 'Incidents will appear here when reported',
        })}
      />
    );
  }

  return (
    <>
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
          {t('safety.new_incident', { defaultValue: 'New Incident' })}
        </Button>
      </div>

      {/* Table */}
      <div className="overflow-x-auto">
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
    </Card>

    {/* New Incident Modal */}
    {showCreate && (
      <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm animate-fade-in">
        <div className="w-full max-w-lg bg-surface-elevated rounded-xl shadow-xl border border-border animate-card-in mx-4 max-h-[90vh] overflow-y-auto" role="dialog" aria-label={t('safety.new_incident', { defaultValue: 'New Incident' })}>
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
          <div className="px-6 py-4 space-y-4">
            {/* Date */}
            <div>
              <label className="block text-sm font-medium text-content-secondary mb-1">
                {t('safety.date', { defaultValue: 'Date' })} <span className="text-semantic-error">*</span>
              </label>
              <input
                type="date"
                value={incidentForm.incident_date}
                onChange={(e) => setIncidentForm((f) => ({ ...f, incident_date: e.target.value }))}
                className={inputCls}
              />
            </div>
            {/* Type */}
            <div>
              <label className="block text-sm font-medium text-content-secondary mb-2">
                {t('safety.type', { defaultValue: 'Type' })} <span className="text-semantic-error">*</span>
              </label>
              <div className="flex flex-wrap gap-2">
                {['near_miss', 'injury', 'property_damage', 'environmental', 'fire'].map((tp) => (
                  <button
                    key={tp}
                    onClick={() => setIncidentForm((f) => ({ ...f, incident_type: tp }))}
                    className={clsx(
                      'rounded-lg px-3 py-1.5 text-sm font-medium transition-colors border',
                      incidentForm.incident_type === tp
                        ? 'bg-oe-blue-subtle text-oe-blue border-oe-blue/30'
                        : 'border-border text-content-tertiary hover:text-content-secondary',
                    )}
                  >
                    {t(`safety.type_${tp}`, { defaultValue: tp.replace(/_/g, ' ') })}
                  </button>
                ))}
              </div>
            </div>
            {/* Description */}
            <div>
              <label className="block text-sm font-medium text-content-secondary mb-1">
                {t('tasks.field_description', { defaultValue: 'Description' })} <span className="text-semantic-error">*</span>
              </label>
              <textarea
                value={incidentForm.description}
                onChange={(e) => setIncidentForm((f) => ({ ...f, description: e.target.value }))}
                rows={3}
                className={textareaCls}
                placeholder={t('safety.incident_desc_placeholder', { defaultValue: 'Describe what happened...' })}
              />
            </div>
            {/* Location */}
            <div>
              <label className="block text-sm font-medium text-content-secondary mb-1">
                {t('safety.location', { defaultValue: 'Location' })}
              </label>
              <input
                value={incidentForm.location}
                onChange={(e) => setIncidentForm((f) => ({ ...f, location: e.target.value }))}
                className={inputCls}
                placeholder={t('safety.location_placeholder', { defaultValue: 'e.g. Building A, Level 3' })}
              />
            </div>
            {/* Treatment */}
            <div>
              <label className="block text-sm font-medium text-content-secondary mb-1">
                {t('safety.treatment', { defaultValue: 'Treatment' })}
              </label>
              <select
                value={incidentForm.treatment_type}
                onChange={(e) => setIncidentForm((f) => ({ ...f, treatment_type: e.target.value }))}
                className={inputCls}
              >
                <option value="">{t('common.none', { defaultValue: 'None' })}</option>
                <option value="first_aid">{t('safety.treatment_first_aid', { defaultValue: 'First Aid' })}</option>
                <option value="medical">{t('safety.treatment_medical', { defaultValue: 'Medical' })}</option>
                <option value="hospital">{t('safety.treatment_hospital', { defaultValue: 'Hospital' })}</option>
                <option value="fatality">{t('safety.treatment_fatality', { defaultValue: 'Fatality' })}</option>
              </select>
            </div>
          </div>
          <div className="flex items-center justify-end gap-3 px-6 py-4 border-t border-border-light">
            <Button variant="ghost" onClick={() => setShowCreate(false)} disabled={createMut.isPending}>
              {t('common.cancel', { defaultValue: 'Cancel' })}
            </Button>
            <Button
              variant="primary"
              onClick={() => createMut.mutate(incidentForm)}
              disabled={createMut.isPending || !incidentForm.description.trim() || !incidentForm.incident_date}
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
      apiPost('/v1/safety/observations', {
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
      addToast({ type: 'success', title: t('safety.observation_created', { defaultValue: 'Observation recorded' }) });
    },
    onError: (e: Error) =>
      addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: e.message }),
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
        title: t('safety.export_success', { defaultValue: 'Export complete' }),
      }),
    onError: (e: Error) =>
      addToast({
        type: 'error',
        title: t('common.error', { defaultValue: 'Error' }),
        message: e.message,
      }),
  });

  const { data: observations, isLoading } = useQuery({
    queryKey: ['safety-observations', projectId],
    queryFn: () =>
      apiGet<Observation[]>(
        `/v1/safety/observations?project_id=${projectId}`,
      ),
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

  if (!observations || observations.length === 0) {
    return (
      <EmptyState
        icon={<Eye size={24} strokeWidth={1.5} />}
        title={t('safety.no_observations', {
          defaultValue: 'No observations yet',
        })}
        description={t('safety.no_observations_desc', {
          defaultValue: 'Safety observations will appear here when recorded',
        })}
      />
    );
  }

  return (
    <>
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
          {t('safety.new_observation', { defaultValue: 'New Observation' })}
        </Button>
      </div>

      {/* Table */}
      <div className="overflow-x-auto">
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
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>

    {/* New Observation Modal */}
    {showCreate && (
      <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm animate-fade-in">
        <div className="w-full max-w-lg bg-surface-elevated rounded-xl shadow-xl border border-border animate-card-in mx-4 max-h-[90vh] overflow-y-auto" role="dialog" aria-label={t('safety.new_observation', { defaultValue: 'New Observation' })}>
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
          <div className="px-6 py-4 space-y-4">
            {/* Type */}
            <div>
              <label className="block text-sm font-medium text-content-secondary mb-2">
                {t('safety.type', { defaultValue: 'Type' })} <span className="text-semantic-error">*</span>
              </label>
              <div className="flex flex-wrap gap-2">
                {['unsafe_act', 'unsafe_condition', 'positive', 'near_miss'].map((tp) => (
                  <button
                    key={tp}
                    onClick={() => setObsForm((f) => ({ ...f, observation_type: tp }))}
                    className={clsx(
                      'rounded-lg px-3 py-1.5 text-sm font-medium transition-colors border',
                      obsForm.observation_type === tp
                        ? 'bg-oe-blue-subtle text-oe-blue border-oe-blue/30'
                        : 'border-border text-content-tertiary hover:text-content-secondary',
                    )}
                  >
                    {t(`safety.obs_type_${tp}`, { defaultValue: tp.replace(/_/g, ' ') })}
                  </button>
                ))}
              </div>
            </div>
            {/* Description */}
            <div>
              <label className="block text-sm font-medium text-content-secondary mb-1">
                {t('tasks.field_description', { defaultValue: 'Description' })} <span className="text-semantic-error">*</span>
              </label>
              <textarea
                value={obsForm.description}
                onChange={(e) => setObsForm((f) => ({ ...f, description: e.target.value }))}
                rows={3}
                className={textareaCls}
                placeholder={t('safety.obs_desc_placeholder', { defaultValue: 'Describe the observation...' })}
              />
            </div>
            {/* Location */}
            <div>
              <label className="block text-sm font-medium text-content-secondary mb-1">
                {t('safety.location', { defaultValue: 'Location' })}
              </label>
              <input
                value={obsForm.location}
                onChange={(e) => setObsForm((f) => ({ ...f, location: e.target.value }))}
                className={inputCls}
                placeholder={t('safety.location_placeholder', { defaultValue: 'e.g. Building A, Level 3' })}
              />
            </div>
            {/* Severity + Likelihood */}
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-sm font-medium text-content-secondary mb-1">
                  {t('safety.severity', { defaultValue: 'Severity' })} (1-5)
                </label>
                <select
                  value={obsForm.severity}
                  onChange={(e) => setObsForm((f) => ({ ...f, severity: Number(e.target.value) }))}
                  className={inputCls}
                >
                  {[1, 2, 3, 4, 5].map((v) => (
                    <option key={v} value={v}>{v}</option>
                  ))}
                </select>
              </div>
              <div>
                <label className="block text-sm font-medium text-content-secondary mb-1">
                  {t('safety.likelihood', { defaultValue: 'Likelihood' })} (1-5)
                </label>
                <select
                  value={obsForm.likelihood}
                  onChange={(e) => setObsForm((f) => ({ ...f, likelihood: Number(e.target.value) }))}
                  className={inputCls}
                >
                  {[1, 2, 3, 4, 5].map((v) => (
                    <option key={v} value={v}>{v}</option>
                  ))}
                </select>
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
              onClick={() => createObsMut.mutate(obsForm)}
              disabled={createObsMut.isPending || !obsForm.description.trim()}
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
