/**
 * Coordination Hub Dashboard — top-level "Model Coordination" landing page.
 *
 * Unifies federations + clashes + smart views + rule packs + BCF activity
 * into one project-scoped view. Built as a thin composition over three
 * sub-components (KPI cards, trade matrix, timeline) so each can be
 * tested in isolation.
 *
 * Visual language: glass cards on a soft gradient backdrop with
 * per-block colour accents (rose / amber / emerald / sky) so the four
 * health signals are readable at a glance, not just a wall of numbers.
 *
 * Empty state: when no project is in the global project-context store
 * we render an EmptyState with a CTA back to the projects list rather
 * than showing zeros against an undefined id.
 */

import { useEffect, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import {
  RefreshCw,
  Radar,
  Layers,
  SlidersHorizontal,
  Eye,
  Sparkles,
  Activity,
  FolderOpen,
  Download,
} from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';

import { useToastStore } from '@/stores/useToastStore';

import { DateDisplay } from '@/shared/ui/DateDisplay';
import { BetaBanner, Breadcrumb, DismissibleInfo, EmptyState, IntroRichText, RecoveryCard } from '@/shared/ui';
import { PageHeader } from '@/shared/ui/PageHeader';
import { useActiveProjectProfile } from '@/features/projects/useProjectProfile';
import { projectsApi } from '@/features/projects/api';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { useAuthStore } from '@/stores/useAuthStore';
import {
  downloadCoordinationSnapshot,
  fetchCoordinationDashboard,
  fetchCoordinationThresholds,
  fetchCoordinationTimeline,
  fetchTradeMatrix,
} from './api';
import { CoordinationKPICards } from './CoordinationKPICards';
import { CoordinationTimeline } from './CoordinationTimeline';
import { CoordinationTradeMatrix } from './CoordinationTradeMatrix';
import {
  ThresholdAlertBanner,
  ThresholdEditorModal,
} from './CoordinationThresholds';

/** Roles that satisfy ``coordination.write`` (EDITOR and above, plus the
 *  EDITOR/ADMIN role aliases the backend permission registry maps). Used
 *  only to decide whether to OFFER the threshold editor — the PUT is still
 *  authoritatively gated server-side. */
const WRITE_ROLES = new Set([
  'admin',
  'manager',
  'editor',
  'estimator',
  'quantity_surveyor',
  'qs',
  'user',
  'superuser',
  'owner',
]);

/** Pull a numeric HTTP status off any thrown value (ApiError uses ``status``;
 *  other shapes occasionally surface ``response.status``). Returns
 *  ``undefined`` when the error isn't HTTP-shaped (e.g. an AbortError or a
 *  TypeError from a network failure) — callers treat that as "transient,
 *  show the generic Retry card". */
function statusOf(err: unknown): number | undefined {
  if (!err || typeof err !== 'object') return undefined;
  const e = err as { status?: unknown; response?: { status?: unknown } };
  if (typeof e.status === 'number') return e.status;
  if (e.response && typeof e.response.status === 'number') return e.response.status;
  return undefined;
}

/** Tiny presentational wrapper — gives any section the same glass
 *  treatment as the KPI row above. Two faint accent strokes (top
 *  gradient border + radial corner glow) keep panels visually
 *  consistent without re-implementing them per-component. */
function GlassPanel({
  testId,
  title,
  subtitle,
  icon,
  action,
  children,
}: {
  testId?: string;
  title: string;
  subtitle?: string;
  icon?: React.ReactNode;
  action?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <section
      data-testid={testId}
      className="relative overflow-hidden rounded-2xl border border-white/40 bg-white/60 backdrop-blur-xl shadow-lg shadow-slate-900/[0.04] dark:border-white/5 dark:bg-slate-900/40 dark:shadow-slate-950/30"
    >
      <div
        aria-hidden
        className="pointer-events-none absolute -top-20 -right-20 h-48 w-48 rounded-full bg-gradient-radial from-sky-500/15 to-transparent blur-3xl"
      />
      <div className="relative flex items-start justify-between gap-3 border-b border-white/40 px-5 py-4 dark:border-white/5">
        <div className="flex items-start gap-3">
          {icon ? (
            <div className="mt-0.5 flex h-8 w-8 items-center justify-center rounded-lg bg-slate-100 text-content-secondary dark:bg-slate-800">
              {icon}
            </div>
          ) : null}
          <div>
            <h2 className="text-sm font-semibold text-content-primary">
              {title}
            </h2>
            {subtitle ? (
              <p className="text-xs text-content-tertiary">{subtitle}</p>
            ) : null}
          </div>
        </div>
        {action}
      </div>
      <div className="relative p-5">{children}</div>
    </section>
  );
}

/** Inline project switcher rendered inside the empty / missing-project
 *  states so the user can jump to a live project without leaving the
 *  page (and without relying on the chrome switcher, which may still be
 *  showing a dead id). Fetches the project list lazily — only mounted
 *  on the empty branches — and writes the choice straight into the
 *  global project-context store, which re-enables the dashboard queries. */
function InlineProjectSwitcher({ excludeId }: { excludeId?: string | null }) {
  const { t } = useTranslation();
  const setActiveProject = useProjectContextStore((s) => s.setActiveProject);

  const { data: projects } = useQuery({
    queryKey: ['coordination-project-switcher'],
    queryFn: () => projectsApi.list(),
    staleTime: 60_000,
    retry: false,
  });

  const options = (projects ?? []).filter((p) => p.id !== excludeId);
  if (options.length === 0) return null;

  return (
    <select
      data-testid="coordination-inline-switcher"
      aria-label={t('coordination.switch_project_aria', {
        defaultValue: 'Switch to a different project',
      })}
      defaultValue=""
      onChange={(e) => {
        const next = options.find((p) => p.id === e.target.value);
        if (next) setActiveProject(next.id, next.name);
      }}
      className="inline-flex h-10 items-center justify-center rounded-md border border-border bg-surface px-3 text-sm font-medium text-content-primary transition-colors hover:border-oe-blue/40 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-400"
    >
      <option value="" disabled>
        {t('coordination.switch_project', {
          defaultValue: 'Switch project…',
        })}
      </option>
      {options.map((p) => (
        <option key={p.id} value={p.id}>
          {p.name}
        </option>
      ))}
    </select>
  );
}

/** Single quick-action tile inside the QuickActions row. */
function QuickActionTile({
  to,
  icon,
  label,
  description,
  navigate,
}: {
  to: string;
  icon: React.ReactNode;
  label: string;
  description: string;
  navigate: ReturnType<typeof useNavigate>;
}) {
  return (
    <button
      type="button"
      onClick={() => navigate(to)}
      className="group relative flex items-start gap-3 overflow-hidden rounded-xl border border-white/40 bg-white/40 px-3.5 py-3 text-left backdrop-blur-xl transition-all hover:-translate-y-0.5 hover:border-oe-blue/40 hover:bg-white/70 hover:shadow-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-400 dark:border-white/5 dark:bg-slate-900/40 dark:hover:bg-slate-800/60"
    >
      <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-oe-blue/10 text-oe-blue transition-colors group-hover:bg-oe-blue group-hover:text-white">
        {icon}
      </div>
      <div className="min-w-0">
        <div className="text-sm font-semibold text-content-primary">{label}</div>
        <div className="truncate text-xs text-content-tertiary">{description}</div>
      </div>
    </button>
  );
}

export function CoordinationHubPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { projectId } = useActiveProjectProfile();
  const clearProject = useProjectContextStore((s) => s.clearProject);
  const projectName = useProjectContextStore((s) => s.activeProjectName);

  const dashboardQuery = useQuery({
    queryKey: ['coordination-dashboard', projectId],
    queryFn: () => fetchCoordinationDashboard(projectId as string),
    enabled: !!projectId,
    staleTime: 30_000,
    retry: false,
  });

  const matrixQuery = useQuery({
    queryKey: ['coordination-trade-matrix', projectId],
    queryFn: () => fetchTradeMatrix(projectId as string),
    enabled: !!projectId,
    staleTime: 30_000,
    retry: false,
  });

  // Activity-window selector. The timeline endpoint already accepts
  // ``?days=N`` (1-365) but the UI previously pinned it to 30 with no
  // control. Lift it into state so the operator can widen / narrow the
  // lookback; the query key includes the window so React Query caches
  // each separately.
  const TIMELINE_WINDOWS = [7, 30, 90] as const;
  const [timelineDays, setTimelineDays] = useState<number>(30);
  const timelineQuery = useQuery({
    queryKey: ['coordination-timeline', projectId, timelineDays],
    queryFn: () => fetchCoordinationTimeline(projectId as string, timelineDays),
    enabled: !!projectId,
    staleTime: 30_000,
    retry: false,
  });

  // Configurable alert thresholds — feed the health banner above the KPI
  // cards and the editor modal. A failure here must never take the page
  // down: the banner degrades to a "loading thresholds" / open-clash hint
  // until the evaluation lands, so we don't fold this into ``hasError``.
  const thresholdsQuery = useQuery({
    queryKey: ['coordination-thresholds', projectId],
    queryFn: () => fetchCoordinationThresholds(projectId as string),
    enabled: !!projectId,
    staleTime: 30_000,
    retry: false,
  });

  const userRole = useAuthStore((s) => s.userRole);
  const canEditThresholds = !!userRole && WRITE_ROLES.has(userRole);
  const [thresholdEditorOpen, setThresholdEditorOpen] = useState(false);

  // CSV snapshot export - one attachable artefact for a coordination
  // meeting. Read-only so every authenticated member can pull it.
  const addToast = useToastStore((s) => s.addToast);
  const [exporting, setExporting] = useState(false);
  const handleExport = async () => {
    if (!projectId || exporting) return;
    setExporting(true);
    try {
      await downloadCoordinationSnapshot(projectId);
      addToast({
        type: 'success',
        title: t('coordination.export_started', {
          defaultValue: 'Coordination snapshot exported',
        }),
      });
    } catch {
      addToast({
        type: 'error',
        title: t('coordination.export_failed', {
          defaultValue: 'Could not export the coordination snapshot',
        }),
      });
    } finally {
      setExporting(false);
    }
  };

  // Stale-project detection. The user's `oe_active_project` localStorage
  // entry can outlive the project itself (deleted on the server, fresh
  // install with a different demo seed, multi-tenant switch, etc.). When
  // that happens every coordination endpoint returns 404 and the page
  // previously surfaced a generic "Couldn't load this" — leaving the
  // user stuck because the chrome project switcher still showed the
  // dead id. Detecting an all-404 fan-out lets us route them back to
  // /projects with a clear explanation + auto-clear the dead context.
  const allFour04 =
    !!projectId &&
    statusOf(dashboardQuery.error) === 404 &&
    statusOf(matrixQuery.error) === 404 &&
    statusOf(timelineQuery.error) === 404;

  // Auto-clear the stale id once we've confirmed it's gone server-side.
  // useEffect (not inline) so the store mutation never fires during
  // render — that would trip the "Cannot update during render" warning
  // and re-mount the page in a loop.
  useEffect(() => {
    if (allFour04) {
      clearProject();
    }
  }, [allFour04, clearProject]);

  if (!projectId) {
    return (
      <div data-testid="coordination-no-project" className="px-4 py-8">
        <EmptyState
          icon={<FolderOpen size={28} strokeWidth={1.5} />}
          title={t('requiresProject.title', {
            defaultValue: 'No project selected',
          })}
          description={t('coordination.no_project_desc', {
            defaultValue: 'Pick a project to see its coordination dashboard.',
          })}
          action={
            <div className="flex flex-wrap items-center justify-center gap-2">
              <InlineProjectSwitcher />
              <Link
                to="/projects"
                className="inline-flex h-10 items-center justify-center rounded-md bg-oe-blue px-4 text-sm font-medium text-white transition-colors hover:bg-oe-blue/90"
              >
                {t('requiresProject.cta', { defaultValue: 'Open Projects' })}
              </Link>
            </div>
          }
        />
      </div>
    );
  }

  if (allFour04) {
    return (
      <div data-testid="coordination-project-missing" className="px-4 py-8">
        <EmptyState
          icon={<FolderOpen size={28} strokeWidth={1.5} />}
          title={t('coordination.project_missing_title', {
            defaultValue: 'That project is no longer available',
          })}
          description={t('coordination.project_missing_desc', {
            defaultValue:
              'The previously selected project was removed or you no longer have access to it. Pick a different project to continue.',
          })}
          action={
            <div className="flex flex-wrap items-center justify-center gap-2">
              <InlineProjectSwitcher excludeId={projectId} />
              <Link
                to="/projects"
                className="inline-flex h-10 items-center justify-center rounded-md bg-oe-blue px-4 text-sm font-medium text-white transition-colors hover:bg-oe-blue/90"
              >
                {t('coordination.open_projects', { defaultValue: 'Open Projects' })}
              </Link>
            </div>
          }
        />
      </div>
    );
  }

  const handleRefresh = () => {
    dashboardQuery.refetch();
    matrixQuery.refetch();
    timelineQuery.refetch();
    thresholdsQuery.refetch();
  };

  // ``hasError`` keeps the legacy "every fan-out failed" full-page card
  // (matching the existing test contract). Partial failures fall through
  // to the per-panel branches below so a flaky timeline endpoint never
  // hides the KPI rollup the user came here for. Bumped to a transient-
  // error tone so a 401/403 (handled by RecoveryCard) still routes to
  // sign-in / request-access rather than a generic retry.
  const hasError =
    dashboardQuery.isError && matrixQuery.isError && timelineQuery.isError;

  return (
    <div
      data-testid="coordination-hub-page"
      className="relative min-h-full overflow-hidden"
    >
      <BetaBanner moduleKey="coordination-hub" className="mt-3" />
      {/* Page-level gradient backdrop. Layered so the glass cards
          above pick up a tint without us needing per-card gradients. */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 -z-10 bg-gradient-to-br from-sky-50 via-white to-emerald-50/40 dark:from-slate-950 dark:via-slate-900 dark:to-slate-950"
      />
      <div
        aria-hidden
        className="pointer-events-none absolute -top-40 -left-40 -z-10 h-96 w-96 rounded-full bg-gradient-radial from-sky-400/15 to-transparent blur-3xl"
      />
      <div
        aria-hidden
        className="pointer-events-none absolute -bottom-40 -right-40 -z-10 h-96 w-96 rounded-full bg-gradient-radial from-emerald-400/15 to-transparent blur-3xl"
      />

      <div className="space-y-5 px-4 py-5 lg:px-6 lg:py-6">
        <Breadcrumb
          items={[
            ...(projectName
              ? [{ label: projectName, to: `/projects/${projectId}` }]
              : []),
            { label: t('nav.coordination_hub', { defaultValue: 'Coordination Hub' }) },
          ]}
        />
        {/* Header */}
        <PageHeader
          srTitle={t('coordination.title', { defaultValue: 'Model Coordination' })}
          subtitle={t('coordination.subtitle', {
            defaultValue:
              'Federations, clashes, rule packs and BCF activity in one view.',
          })}
          actions={
            <>
              {dashboardQuery.data ? (
                <span
                  data-testid="coordination-as-of"
                  className="text-xs text-content-tertiary"
                >
                  {t('coordination.as_of', { defaultValue: 'As of' })}{' '}
                  <DateDisplay
                    value={dashboardQuery.data.as_of}
                    format="datetime"
                  />
                </span>
              ) : null}
              {canEditThresholds ? (
                <button
                  data-testid="coordination-configure-thresholds"
                  type="button"
                  onClick={() => setThresholdEditorOpen(true)}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-white/40 bg-white/50 px-3 py-1.5 text-xs font-medium text-content-secondary backdrop-blur transition hover:border-oe-blue/40 hover:bg-white/80 hover:text-content-primary focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-400 dark:border-white/5 dark:bg-slate-800/50 dark:hover:bg-slate-700/50"
                >
                  <SlidersHorizontal size={13} />
                  {t('coordination_hub.configure_thresholds', {
                    defaultValue: 'Thresholds',
                  })}
                </button>
              ) : null}
              <button
                data-testid="coordination-export"
                type="button"
                onClick={handleExport}
                disabled={exporting}
                className="inline-flex items-center gap-1.5 rounded-lg border border-white/40 bg-white/50 px-3 py-1.5 text-xs font-medium text-content-secondary backdrop-blur transition hover:border-oe-blue/40 hover:bg-white/80 hover:text-content-primary focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-400 disabled:cursor-not-allowed disabled:opacity-60 dark:border-white/5 dark:bg-slate-800/50 dark:hover:bg-slate-700/50"
              >
                <Download size={13} />
                {t('coordination.export_csv', { defaultValue: 'Export CSV' })}
              </button>
              <button
                data-testid="coordination-refresh"
                type="button"
                onClick={handleRefresh}
                className="inline-flex items-center gap-1.5 rounded-lg border border-white/40 bg-white/50 px-3 py-1.5 text-xs font-medium text-content-secondary backdrop-blur transition hover:border-oe-blue/40 hover:bg-white/80 hover:text-content-primary focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-400 dark:border-white/5 dark:bg-slate-800/50 dark:hover:bg-slate-700/50"
              >
                <RefreshCw size={13} />
                {t('coordination.refresh', { defaultValue: 'Refresh' })}
              </button>
            </>
          }
        />

        <DismissibleInfo
          storageKey="coordination"
          title={t('coordination.intro_title', {
            defaultValue: 'One health view across every federated model',
          })}
          more={
            t('coordination.intro_more', { defaultValue: '' })
              ? <IntroRichText text={t('coordination.intro_more')} />
              : undefined
          }
          links={[
            {
              label: t('nav.clash_detection', { defaultValue: 'Clash Detection' }),
              onClick: () => navigate('/clash'),
            },
            {
              label: t('nav.bim_federations', { defaultValue: 'BIM Federations' }),
              onClick: () => navigate('/bim/federations'),
            },
            {
              label: t('nav.bim_rules', { defaultValue: 'Rule Packs' }),
              onClick: () => navigate('/bim/rules'),
            },
          ]}
        >
          {t('coordination.intro_body', {
            defaultValue:
              'This dashboard rolls up your federated BIM models, clash results, rule-pack checks and BCF activity for the active project into a single status view. Use the quick actions to triage clashes, manage federations or run compliance rules, with every number traced back to the canonical model.',
          })}
        </DismissibleInfo>

        {hasError ? (
          <div data-testid="coordination-error">
            <RecoveryCard
              error={dashboardQuery.error ?? matrixQuery.error ?? timelineQuery.error}
              onRetry={handleRefresh}
            />
          </div>
        ) : (
          <>
            {dashboardQuery.isError ? (
              <div data-testid="coordination-kpi-error">
                <RecoveryCard
                  error={dashboardQuery.error}
                  onRetry={() => dashboardQuery.refetch()}
                />
              </div>
            ) : (
              <>
                <ThresholdAlertBanner
                  data={thresholdsQuery.data}
                  fallbackOpenClashes={
                    dashboardQuery.data?.clashes.open_count ?? 0
                  }
                />
                <CoordinationKPICards
                  data={dashboardQuery.data}
                  isLoading={dashboardQuery.isLoading}
                  projectId={projectId}
                  onNavigate={navigate}
                />
              </>
            )}

            {/* Quick actions — get-to-the-work shortcuts. Mirrors the
                "Skip the sales call" home-page CTA pattern but scoped
                to coordination workflows. */}
            <GlassPanel
              testId="coordination-quick-actions"
              icon={<Sparkles size={16} />}
              title={t('coordination.quick_actions_title', {
                defaultValue: 'Quick actions',
              })}
              subtitle={t('coordination.quick_actions_subtitle', {
                defaultValue: 'Jump straight to the next coordination task',
              })}
            >
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
                <QuickActionTile
                  navigate={navigate}
                  to="/clash"
                  icon={<Radar size={16} />}
                  label={t('coordination.qa_clash_label', {
                    defaultValue: 'Review clashes',
                  })}
                  description={t('coordination.qa_clash_desc', {
                    defaultValue: 'Triage, suppress, assign to disciplines',
                  })}
                />
                <QuickActionTile
                  navigate={navigate}
                  to="/bim/federations"
                  icon={<Layers size={16} />}
                  label={t('coordination.qa_federations_label', {
                    defaultValue: 'Federations',
                  })}
                  description={t('coordination.qa_federations_desc', {
                    defaultValue: 'Stitch BIM models, view by discipline',
                  })}
                />
                <QuickActionTile
                  navigate={navigate}
                  to="/bim/rules"
                  icon={<SlidersHorizontal size={16} />}
                  label={t('coordination.qa_rules_label', {
                    defaultValue: 'Rule packs',
                  })}
                  description={t('coordination.qa_rules_desc', {
                    defaultValue: 'LOD300 / LOD400 / COBie compliance',
                  })}
                />
                <QuickActionTile
                  navigate={navigate}
                  to="/bim"
                  icon={<Eye size={16} />}
                  label={t('coordination.qa_smart_views_label', {
                    defaultValue: 'Smart views',
                  })}
                  description={t('coordination.qa_smart_views_desc', {
                    defaultValue: 'Filter, color and isolate in 3D',
                  })}
                />
              </div>
            </GlassPanel>

            {/* Trade matrix — clash distribution across discipline pairs */}
            <GlassPanel
              testId="coordination-trade-matrix-panel"
              icon={<Radar size={16} />}
              title={t('coordination.trade_matrix_title', {
                defaultValue: 'Clashes by discipline pair',
              })}
              subtitle={t('coordination.trade_matrix_subtitle', {
                defaultValue:
                  'Click a cell to drill into the filtered clash list',
              })}
            >
              {matrixQuery.isError ? (
                <div data-testid="coordination-matrix-error">
                  <RecoveryCard
                    error={matrixQuery.error}
                    onRetry={() => matrixQuery.refetch()}
                  />
                </div>
              ) : (
                <CoordinationTradeMatrix
                  data={matrixQuery.data}
                  isLoading={matrixQuery.isLoading}
                  projectId={projectId}
                  embedded
                />
              )}
            </GlassPanel>

            {/* Recent activity timeline */}
            <GlassPanel
              testId="coordination-timeline-panel"
              icon={<Activity size={16} />}
              title={t('coordination.timeline_title_window', {
                defaultValue: 'Recent activity ({{days}} days)',
                days: timelineDays,
              })}
              subtitle={t('coordination.timeline_subtitle', {
                defaultValue:
                  'Clash runs, federations, rule pack checks and BCF topics',
              })}
              action={
                <div
                  role="group"
                  aria-label={t('coordination.timeline_window_aria', {
                    defaultValue: 'Activity lookback window',
                  })}
                  className="inline-flex overflow-hidden rounded-lg border border-border text-xs"
                >
                  {TIMELINE_WINDOWS.map((d) => (
                    <button
                      key={d}
                      type="button"
                      data-testid={`coordination-timeline-window-${d}`}
                      aria-pressed={timelineDays === d}
                      onClick={() => setTimelineDays(d)}
                      className={
                        timelineDays === d
                          ? 'bg-oe-blue px-3 py-1 font-medium text-white focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-400'
                          : 'bg-surface px-3 py-1 font-medium text-content-secondary transition-colors hover:bg-surface-secondary focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-400'
                      }
                    >
                      {t('coordination.timeline_window_days', {
                        defaultValue: '{{n}}d',
                        n: d,
                      })}
                    </button>
                  ))}
                </div>
              }
            >
              {timelineQuery.isError ? (
                <div data-testid="coordination-timeline-error">
                  <RecoveryCard
                    error={timelineQuery.error}
                    onRetry={() => timelineQuery.refetch()}
                  />
                </div>
              ) : (
                <CoordinationTimeline
                  data={timelineQuery.data}
                  isLoading={timelineQuery.isLoading}
                  embedded
                />
              )}
            </GlassPanel>
          </>
        )}
      </div>

      {/* Threshold editor — write-gated; mounted at page level so it
          overlays everything. Seeded from the live thresholds payload. */}
      {canEditThresholds ? (
        <ThresholdEditorModal
          open={thresholdEditorOpen}
          onClose={() => setThresholdEditorOpen(false)}
          projectId={projectId}
          rows={thresholdsQuery.data?.thresholds ?? []}
        />
      ) : null}
    </div>
  );
}
