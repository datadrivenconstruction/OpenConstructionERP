import { useState, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation } from '@tanstack/react-query';
import {
  ShieldAlert,
  Eye,
  Search,
  HardHat,
  Download,
  Loader2,
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
import { apiGet, triggerDownload } from '@/shared/lib/api';
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

export function SafetyPage() {
  const { t } = useTranslation();
  const projectId = useProjectContextStore((s) => s.activeProjectId);
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
  const [search, setSearch] = useState('');
  const addToast = useToastStore((s) => s.addToast);

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
    <Card padding="none">
      {/* Search + Export */}
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
            {filtered.map((inc) => (
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
  );
}

/* ── Observations Tab ─────────────────────────────────────────────────── */

function ObservationsTab({ projectId }: { projectId: string }) {
  const { t } = useTranslation();
  const [search, setSearch] = useState('');
  const addToast = useToastStore((s) => s.addToast);

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
    <Card padding="none">
      {/* Search + Export */}
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
            {filtered.map((obs) => (
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
  );
}
