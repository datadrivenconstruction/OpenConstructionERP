// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Estimation Dashboard (RFC 25, formerly Project Intelligence).
 *
 * Layout (top to bottom):
 *   1. Header + KPI strip (ProjectKPIHero)
 *   2. Gaps column + Analytics grid (ProjectAnalyticsGrid)
 *   3. Domain detail tabs — reduced to 4 (BOQ / Cost / Schedule / Risk)
 *   4. Cost Intelligence Advisor (existing AIAdvisorPanel)
 *
 * The URL (/project-intelligence) is unchanged so existing bookmarks
 * keep working.
 */

import { useState, useEffect, useCallback } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { useAuthStore } from '@/stores/useAuthStore';
import { useToastStore } from '@/stores/useToastStore';
import { apiGet, apiPost } from '@/shared/lib/api';
import { isModuleLoaded, _resetModuleProbeCache } from '@/shared/lib/moduleProbe';
import { formatElapsed } from '@/shared/lib/duration';
import { Breadcrumb, DismissibleInfo, ModuleGuideButton } from '@/shared/ui';
import { PageHeader } from '@/shared/ui/PageHeader';
import { project_intelligenceGuide } from './project_intelligenceGuide';
import { ScoreRing } from './ScoreRing';
import { GapCard } from './GapCard';
import { AIAdvisorPanel } from './AIAdvisorPanel';
import { DomainDetails } from './DomainDetails';
import { ProjectKPIHero } from './components/ProjectKPIHero';
import { ProjectAnalyticsGrid } from './components/ProjectAnalyticsGrid';
import { ForecastPanel } from './components/ForecastPanel';
import { ForecastInsightsPanel } from './components/ForecastInsightsPanel';
import {
  RefreshCw,
  BrainCircuit,
  ChevronDown,
  AlertTriangle,
  CheckCircle2,
  PowerOff,
  Power,
  Settings2,
  FileText,
  TrendingUp,
} from 'lucide-react';
import { fmtFixed } from '@/shared/lib/formatters';

/** Dynamic state object from backend — each domain key (boq, validation, etc.)
 *  maps to an object with heterogeneous metric fields. */
type DomainStateValue = string | number | boolean | string[] | null | undefined;
type DomainStateMap = Record<string, Record<string, DomainStateValue>>;
interface SummaryState {
  project_name?: string;
  [key: string]: Record<string, DomainStateValue> | string | undefined;
}

interface Summary {
  state: SummaryState;
  score: {
    overall: number;
    overall_grade: string;
    domain_scores: Record<string, number>;
    critical_gaps: CriticalGap[];
    achievements: Achievement[];
  };
}

interface CriticalGap {
  id: string;
  domain: string;
  severity: string;
  title: string;
  description: string;
  impact: string;
  action_id: string | null;
  affected_count: number | null;
}

interface Achievement {
  domain: string;
  title: string;
  description: string;
}

interface ActionDef {
  id: string;
  label: string;
  description: string;
  icon: string;
  requires_confirmation: boolean;
  confirmation_message: string;
  navigate_to: string | null;
  has_backend_action: boolean;
}

interface AnomalyRow {
  position_id: string;
  type: 'outlier' | 'jump' | 'format';
  severity: 'info' | 'warning' | 'error';
  detail: string;
}

interface LineItemRow {
  position_id: string;
  description: string;
  total_cost: number;
  share_of_total: number;
}

// Reduced set of detail tabs per RFC 25 §3.
const RFC25_DETAIL_DOMAINS = ['boq', 'cost_model', 'schedule', 'risk'];

const GRADE_COLORS: Record<string, string> = {
  A: '#3fb950',
  B: '#8b949e',
  C: '#d29922',
  D: '#f85149',
  F: '#da3633',
};

export function ProjectIntelligencePage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const addToast = useToastStore((s) => s.addToast);
  const [searchParams] = useSearchParams();
  const projectId = useProjectContextStore((s) => s.activeProjectId);
  const userRole = useAuthStore((s) => s.userRole);
  const isAdmin = userRole === 'admin';
  const paramProjectId = searchParams.get('project_id');
  const activeProjectId = paramProjectId || projectId;

  const [summary, setSummary] = useState<Summary | null>(null);
  const [actions, setActions] = useState<ActionDef[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [moduleDisabled, setModuleDisabled] = useState(false);
  const [enabling, setEnabling] = useState(false);
  const [enableError, setEnableError] = useState<string | null>(null);
  const [lastRefresh, setLastRefresh] = useState<Date | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [role, setRole] = useState<string>('estimator');
  const [expandedGap, setExpandedGap] = useState<string | null>(null);
  const [showAllGaps, setShowAllGaps] = useState(false);
  const [selectedDomain, setSelectedDomain] = useState<string | null>('boq');
  // Active predictive-forecast alert count, reported up from ForecastPanel.
  // Drives the banner above the KPI hero and the Forecasts section badge.
  const [forecastAlertCount, setForecastAlertCount] = useState(0);

  const scrollToForecasts = useCallback(() => {
    document
      .getElementById('pi-forecasts')
      ?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }, []);

  // Anomaly + line-item data used to enrich the Critical Gaps card with $ impact.
  const [anomalies, setAnomalies] = useState<AnomalyRow[]>([]);
  const [lineItems, setLineItems] = useState<LineItemRow[]>([]);

  // Fetch summary data
  const fetchData = useCallback(
    async (refresh = false) => {
      if (!activeProjectId) return;
      // The module is optional. When disabled the dashboard shows the
      // "module disabled" empty state instead of 404-logging once per
      // load.
      if (!(await isModuleLoaded('oe_project_intelligence'))) {
        setLoading(false);
        setModuleDisabled(true);
        return;
      }
      setModuleDisabled(false);
      try {
        if (refresh) setRefreshing(true);
        else setLoading(true);
        setError(null);

        const data = await apiGet<Summary>(
          `/v1/project_intelligence/summary/?project_id=${activeProjectId}${refresh ? '&refresh=true' : ''}`,
        );
        setSummary(data);
        setLastRefresh(new Date());

        // Fetch available actions
        try {
          const actData = await apiGet<ActionDef[]>(
            `/v1/project_intelligence/actions/?project_id=${activeProjectId}`,
          );
          setActions(actData);
        } catch { /* actions are optional */ }

        // Enrich critical gaps with $ impact from the anomalies + line-items
        // endpoints. Both are optional — failure just hides the enrichment.
        try {
          const [an, li] = await Promise.all([
            apiGet<AnomalyRow[]>(`/v1/boq/anomalies/?project_id=${activeProjectId}`),
            apiGet<LineItemRow[]>(
              `/v1/boq/line-items/?project_id=${activeProjectId}&group=cost&top_n=20`,
            ),
          ]);
          setAnomalies(an);
          setLineItems(li);
        } catch {
          setAnomalies([]);
          setLineItems([]);
        }
      } catch (err: unknown) {
        setError(
          err instanceof Error ? err.message : 'Failed to load the dashboard',
        );
      } finally {
        setLoading(false);
        setRefreshing(false);
      }
    },
    [activeProjectId],
  );

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  // Enable the disabled module via the existing /v1/modules/{name}/enable
  // endpoint, then refresh the probe cache and re-fetch the dashboard.
  // Admin-only — non-admins see a Modules-page link instead.
  const handleEnableModule = useCallback(async () => {
    setEnableError(null);
    setEnabling(true);
    try {
      await apiPost('/v1/modules/oe_project_intelligence/enable');
      _resetModuleProbeCache();
      setModuleDisabled(false);
      await fetchData();
    } catch (err: unknown) {
      setEnableError(
        err instanceof Error
          ? err.message
          : t('project_intelligence.enable_failed', {
              defaultValue: 'Could not enable the module',
            }),
      );
    } finally {
      setEnabling(false);
    }
  }, [fetchData, t]);

  // Execute action
  const handleAction = useCallback(
    async (actionId: string) => {
      if (!activeProjectId) return;
      try {
        const result = await apiPost<{
          status: string;
          message: string;
          redirect_url?: string;
        }>(
          `/v1/project_intelligence/actions/${actionId}/?project_id=${activeProjectId}`,
        );
        if (result.redirect_url) {
          // Prefer SPA navigation for in-app paths so the dashboard state
          // (and the rest of the app shell) is not blown away by a full
          // page reload. Only fall back to a hard redirect for absolute
          // URLs (external links).
          if (result.redirect_url.startsWith('/')) {
            navigate(result.redirect_url);
          } else {
            window.location.href = result.redirect_url;
          }
        } else {
          if (result.message) {
            addToast({
              type: result.status === 'error' ? 'error' : 'success',
              title: t('project_intelligence.action_done', {
                defaultValue: 'Action complete',
              }),
              message: result.message,
            });
          }
          fetchData(true);
        }
      } catch (err: unknown) {
        // Previously swallowed — a failed fix-it action looked like the
        // button did nothing. Surface it so the user can react.
        addToast({
          type: 'error',
          title: t('project_intelligence.action_failed', {
            defaultValue: 'Could not complete the action',
          }),
          message: err instanceof Error ? err.message : '',
        });
      }
    },
    [activeProjectId, fetchData, navigate, addToast, t],
  );

  if (!activeProjectId) {
    return (
      <div className="flex flex-col items-center justify-center py-16 px-6 text-center space-y-4 animate-fade-in">
        <div className="w-14 h-14 rounded-2xl bg-oe-blue/10 flex items-center justify-center">
          <BrainCircuit size={28} className="text-oe-blue" />
        </div>
        <h2 className="text-lg font-semibold text-content-primary">
          {t('project_intelligence.page_title_v191', {
            defaultValue: 'Estimation Dashboard',
          })}
        </h2>
        <p className="text-sm text-content-secondary max-w-xl mx-auto leading-relaxed">
          {t('project_intelligence.v191_select_prompt', {
            defaultValue:
              'Select a project from the header to see its cost variance, anomalies, and bid analytics.',
          })}
        </p>
        <div className="flex items-center justify-center gap-3 pt-1">
          <Link
            to="/projects"
            className="inline-flex items-center gap-2 px-4 py-2 text-sm font-medium bg-oe-blue text-white rounded-lg shadow-sm hover:bg-oe-blue-dark transition-colors"
          >
            <FileText size={14} />
            {t('project_intelligence.v191_open_projects', {
              defaultValue: 'Open Projects',
            })}
          </Link>
          <Link
            to="/ai-estimate"
            className="inline-flex items-center gap-2 px-4 py-2 text-sm font-medium border border-border-light rounded-lg hover:bg-surface-secondary transition-colors text-content-secondary"
          >
            <BrainCircuit size={14} />
            {t('project_intelligence.v191_try_estimate', {
              defaultValue: 'Try AI Estimate',
            })}
          </Link>
        </div>
      </div>
    );
  }

  if (loading) {
    return (
      <div className="w-full py-16">
        <div className="text-center space-y-3 animate-pulse">
          <BrainCircuit size={48} className="mx-auto text-oe-blue" />
          <p className="text-sm text-content-secondary">
            {t('project_intelligence.analyzing', {
              defaultValue: 'Analyzing project...',
            })}
          </p>
        </div>
      </div>
    );
  }

  if (moduleDisabled) {
    return (
      <div className="w-full py-12 px-6">
        <div className="max-w-xl mx-auto rounded-2xl border border-border-light bg-surface-elevated shadow-sm p-8 text-center space-y-5">
          <div className="w-14 h-14 rounded-2xl bg-amber-50 dark:bg-amber-950/30 flex items-center justify-center mx-auto">
            <PowerOff size={26} className="text-amber-500" />
          </div>
          <div className="space-y-2">
            <h2 className="text-lg font-semibold text-content-primary">
              {t('project_intelligence.module_disabled_title', {
                defaultValue: 'Project Intelligence is turned off',
              })}
            </h2>
            <p className="text-sm text-content-secondary leading-relaxed">
              {t('project_intelligence.module_disabled_body', {
                defaultValue:
                  'This dashboard runs against the optional Project Intelligence module. It is currently disabled on this server, so the AI advisor, gap detector and analytics grid have nothing to query.',
              })}
            </p>
          </div>

          {enableError && (
            <div className="rounded-lg border border-red-200 dark:border-red-900/40 bg-red-50 dark:bg-red-950/20 px-3 py-2 text-xs text-red-700 dark:text-red-300 text-left">
              {enableError}
            </div>
          )}

          <div className="flex items-center justify-center gap-2 pt-1">
            {isAdmin ? (
              <button
                onClick={handleEnableModule}
                disabled={enabling}
                className="inline-flex items-center gap-2 px-4 py-2 text-sm font-medium bg-oe-blue text-white rounded-lg shadow-sm hover:bg-oe-blue-dark transition-colors disabled:opacity-50"
              >
                <Power size={14} className={enabling ? 'animate-pulse' : ''} />
                {enabling
                  ? t('project_intelligence.enabling', { defaultValue: 'Enabling…' })
                  : t('project_intelligence.enable_module', {
                      defaultValue: 'Enable module',
                    })}
              </button>
            ) : (
              <p className="text-xs text-content-tertiary">
                {t('project_intelligence.module_disabled_ask_admin', {
                  defaultValue: 'Ask an admin to enable this module to continue.',
                })}
              </p>
            )}
            <Link
              to="/modules"
              className="inline-flex items-center gap-2 px-4 py-2 text-sm font-medium border border-border-light rounded-lg hover:bg-surface-secondary transition-colors text-content-secondary"
            >
              <Settings2 size={14} />
              {t('project_intelligence.open_modules_page', {
                defaultValue: 'Open Modules page',
              })}
            </Link>
          </div>

          <p className="text-2xs text-content-quaternary pt-1">
            {t('project_intelligence.module_disabled_footnote', {
              defaultValue:
                'No data is collected while the module is off. Enabling is reversible from the Modules page.',
            })}
          </p>
        </div>
      </div>
    );
  }

  if (error) {
    const isAuth =
      error.includes('401') ||
      error.includes('auth') ||
      error.includes('Unauthorized');
    return (
      <div className="w-full py-12">
        <div className="text-center space-y-4">
          <div className="w-14 h-14 rounded-2xl bg-amber-50 dark:bg-amber-950/30 flex items-center justify-center mx-auto">
            <AlertTriangle size={28} className="text-amber-500" />
          </div>
          <h2 className="text-lg font-semibold text-content-primary">
            {isAuth
              ? t('project_intelligence.auth_error', {
                  defaultValue: 'Session expired',
                })
              : t('project_intelligence.load_error', {
                  defaultValue: 'Could not load analysis',
                })}
          </h2>
          <p className="text-sm text-content-secondary max-w-md mx-auto">
            {isAuth
              ? t('project_intelligence.auth_hint', {
                  defaultValue:
                    'Please refresh the page or sign in again to continue.',
                })
              : error}
          </p>
          <div className="flex items-center justify-center gap-3 pt-2">
            <button
              onClick={() => fetchData()}
              className="px-4 py-2 text-sm bg-oe-blue text-white rounded-lg hover:bg-oe-blue-dark transition-colors"
            >
              {t('common.retry', { defaultValue: 'Retry' })}
            </button>
            {isAuth && (
              <button
                onClick={() => window.location.reload()}
                className="px-4 py-2 text-sm border border-border rounded-lg hover:bg-surface-secondary transition-colors"
              >
                {t('common.refresh_page', { defaultValue: 'Refresh Page' })}
              </button>
            )}
          </div>
        </div>
      </div>
    );
  }

  if (!summary) return null;

  const { score, state } = summary;
  const gradeColor = GRADE_COLORS[score.overall_grade] || '#8b949e';

  // Enrich the Critical Gaps card with $ impact derived from anomalies + line items.
  const missingPriceCount = anomalies.filter(
    (a) => a.type === 'format' && a.detail.includes('unit_rate'),
  ).length;
  const totalBoqValue = lineItems.reduce((acc, li) => acc + (li.total_cost || 0), 0);
  const avgLineValue =
    lineItems.length > 0 ? totalBoqValue / lineItems.length : 0;
  const costUncertainty = missingPriceCount * avgLineValue;
  const dollarImpact =
    missingPriceCount > 0
      ? t('project_intelligence.gaps.dollar_impact', {
          defaultValue:
            '{{count}} items missing prices → ~{{amount}} cost uncertainty',
          count: missingPriceCount,
          amount:
            costUncertainty >= 1_000_000
              ? `$${fmtFixed(costUncertainty / 1_000_000, 1)}M`
              : costUncertainty >= 1_000
              ? `$${fmtFixed(costUncertainty / 1_000, 0)}k`
              : `$${fmtFixed(costUncertainty, 0)}`,
        })
      : null;

  const displayGaps = showAllGaps
    ? score.critical_gaps
    : score.critical_gaps.slice(0, 5);
  const hasMoreGaps = !showAllGaps && score.critical_gaps.length > 5;

  return (
    <div className="space-y-5 animate-fade-in">
      {/* Canonical top block (MODULE_STYLE_GUIDE): breadcrumb with depth,
          PageHeader (subtitle + actions, module name lives in the top bar),
          then the standard DismissibleInfo card. */}
      <Breadcrumb
        items={[
          ...(activeProjectId
            ? [
                {
                  label:
                    state.project_name ||
                    t('project_intelligence.unnamed', {
                      defaultValue: 'Unnamed Project',
                    }),
                  to: `/projects/${activeProjectId}`,
                },
              ]
            : []),
          {
            label: t('nav.estimation_dashboard', {
              defaultValue: 'Project Intelligence',
            }),
          },
        ]}
      />
      <PageHeader
        srTitle={t('project_intelligence.page_title_v191', {
          defaultValue: 'Estimation Dashboard',
        })}
        subtitle={t('project_intelligence.v191_header_desc', {
          defaultValue:
            'Cost variance, anomalies, bid analytics - refreshed every 60s.',
        })}
        actions={
          <>
            <ModuleGuideButton content={project_intelligenceGuide} />
            <select
              value={role}
              onChange={(e) => setRole(e.target.value)}
              className="h-9 text-xs bg-surface-secondary border border-border-light rounded-md px-2 text-content-secondary focus:outline-none focus:ring-1 focus:ring-oe-blue"
              aria-label={t('project_intelligence.role', {
                defaultValue: 'View as role',
              })}
            >
              <option value="estimator">
                {t('project_intelligence.role_estimator', {
                  defaultValue: 'Estimator',
                })}
              </option>
              <option value="manager">
                {t('project_intelligence.role_manager', {
                  defaultValue: 'Manager',
                })}
              </option>
              <option value="explorer">
                {t('project_intelligence.role_explorer', {
                  defaultValue: 'Explorer',
                })}
              </option>
            </select>
            <button
              data-testid="pi-refresh-button"
              onClick={() => fetchData(true)}
              disabled={refreshing}
              className="flex h-9 items-center gap-1.5 rounded-md px-2 text-xs text-content-secondary hover:text-content-primary transition-colors disabled:opacity-50"
              title={t('project_intelligence.refresh', {
                defaultValue: 'Refresh analysis',
              })}
            >
              <RefreshCw size={14} className={refreshing ? 'animate-spin' : ''} />
              {/* #174: this used to stop at hours, so an analysis left open
                  overnight reported "18h ago" and one from last week "172h
                  ago". The shared formatter climbs to days and months. */}
              {lastRefresh && (
                <span>{formatElapsed(t, lastRefresh, { suffix: true })}</span>
              )}
            </button>
          </>
        }
      />

      <DismissibleInfo
        storageKey="project-intelligence"
        title={t('project_intelligence.intro_title', {
          defaultValue: 'What this dashboard tells you',
        })}
        links={[
          {
            label: t('project_intelligence.intro_link_boq', {
              defaultValue: 'BOQ editor',
            }),
            onClick: () => navigate('/boq'),
          },
          {
            label: t('project_intelligence.intro_link_validation', {
              defaultValue: 'Validation',
            }),
            onClick: () => navigate('/validation'),
          },
        ]}
      >
        {t('project_intelligence.intro_body', {
          defaultValue:
            'It reads your live BOQ, cost model, schedule and risk register and grades how ready this estimate is to go out (BOQ 40%, Cost Model 30%, Validation 20%, Risk 10%). Critical Gaps are the fastest ways to raise that grade - each one links straight to the screen that fixes it. The advisor at the bottom answers project-specific questions.',
        })}
      </DismissibleInfo>

      {/* Predictive forecast alert banner — only shown when the forecast
          engine has flagged one or more active alerts for this project. */}
      {forecastAlertCount > 0 && (
        <div
          className="rounded-xl border border-rose-300/60 dark:border-rose-900/50 bg-rose-50/70 dark:bg-rose-950/20 p-3 flex items-center gap-3"
          data-testid="pi-forecast-alert-banner"
        >
          <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-rose-500/10">
            <AlertTriangle size={16} className="text-rose-500" />
          </div>
          <div className="flex-1 min-w-0">
            <p className="text-xs font-semibold text-content-primary">
              {t('project_intelligence.forecast.banner_title', {
                defaultValue: '{{count}} active forecast alert',
                defaultValue_plural: '{{count}} active forecast alerts',
                count: forecastAlertCount,
              })}
            </p>
            <p className="text-2xs text-content-secondary">
              {t('project_intelligence.forecast.banner_body', {
                defaultValue:
                  'The predictive EVM forecast has breached a cost/schedule threshold. Review and acknowledge below.',
              })}
            </p>
          </div>
          <button
            onClick={scrollToForecasts}
            className="shrink-0 inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium bg-rose-500 text-white rounded-lg hover:bg-rose-600 transition-colors"
          >
            <TrendingUp size={13} />
            {t('project_intelligence.forecast.banner_cta', {
              defaultValue: 'View forecast',
            })}
          </button>
        </div>
      )}

      {/* Section 1 — KPI hero */}
      <ProjectKPIHero projectId={activeProjectId} />

      {/* Section 2 — Readiness + Critical gaps (side-by-side, equal height) */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-4">
        {/* Readiness ring card (compact, fixed width) */}
        <div className="lg:col-span-3 bg-white dark:bg-gray-800/60 rounded-xl border border-border-light shadow-sm p-4 flex flex-col">
          <h3 className="text-xs font-semibold text-content-primary mb-2">
            {t('project_intelligence.readiness_title', {
              defaultValue: 'Estimation readiness',
            })}
          </h3>
          <div
            className="flex-1 flex items-center justify-center"
            title={t('project_intelligence.score_tooltip_v191', {
              defaultValue:
                'Score weighting (RFC 25): BOQ 40%, Cost Model 30%, Validation 20%, Risk 10%.',
            })}
          >
            <ScoreRing
              score={score.overall}
              grade={score.overall_grade}
              gradeColor={gradeColor}
              size={140}
              strokeWidth={9}
            />
          </div>
        </div>

        {/* Critical gaps card — fills remaining width */}
        <div className="lg:col-span-9 bg-white dark:bg-gray-800/60 rounded-xl border border-border-light shadow-sm p-4 flex flex-col">
          {score.critical_gaps.length > 0 ? (
            <>
              <h3 className="text-sm font-semibold text-content-primary flex items-center gap-2 mb-2">
                <AlertTriangle size={15} className="text-red-400" />
                {t('project_intelligence.critical_gaps', {
                  defaultValue: 'Critical Gaps',
                })}
                <span className="text-xs text-content-tertiary font-normal ml-auto">
                  {score.critical_gaps.length}
                </span>
              </h3>
              {dollarImpact && (
                <p
                  className="text-xs text-amber-600 dark:text-amber-400 mb-2"
                  data-testid="pi-dollar-impact"
                >
                  {dollarImpact}
                </p>
              )}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                {displayGaps.map((gap) => (
                  <GapCard
                    key={gap.id}
                    gap={gap}
                    isExpanded={expandedGap === gap.id}
                    onToggle={() =>
                      setExpandedGap(expandedGap === gap.id ? null : gap.id)
                    }
                    onAction={
                      gap.action_id ? () => handleAction(gap.action_id!) : undefined
                    }
                    actionLabel={actions.find((a) => a.id === gap.action_id)?.label}
                  />
                ))}
              </div>
              {hasMoreGaps && (
                <button
                  onClick={() => setShowAllGaps(true)}
                  className="mt-2 w-full text-xs text-content-tertiary hover:text-content-secondary py-1.5 flex items-center justify-center gap-1 transition-colors"
                >
                  <ChevronDown size={12} />
                  {t('project_intelligence.show_more_gaps', {
                    defaultValue: '{{count}} more',
                    count: score.critical_gaps.length - 5,
                  })}
                </button>
              )}
            </>
          ) : (
            <div className="flex-1 flex flex-col items-center justify-center text-center">
              <CheckCircle2 size={28} className="text-green-400 mb-2" />
              <p className="text-sm font-medium text-content-primary">
                {t('project_intelligence.no_gaps_title', {
                  defaultValue: 'No critical gaps',
                })}
              </p>
              <p className="text-2xs text-content-tertiary mt-1 max-w-md">
                {t('project_intelligence.no_gaps_desc', {
                  defaultValue:
                    'Your project has no critical issues. Keep refining to tighten variance.',
                })}
              </p>
            </div>
          )}
        </div>
      </div>

      {/* Section 2b — Analytics grid (full width) */}
      <ProjectAnalyticsGrid projectId={activeProjectId} />

      {/* Section 2c — Predictive EVM forecast + alerts (TOP-30 #19) */}
      <div id="pi-forecasts" className="scroll-mt-20">
        <div className="rounded-xl border border-border-light bg-white dark:bg-gray-800/60 shadow-sm p-4">
          <div className="flex items-center gap-2 mb-3">
            <TrendingUp size={16} className="text-oe-blue" />
            <h2 className="text-sm font-semibold text-content-primary">
              {t('project_intelligence.forecast.section_title', {
                defaultValue: 'Predictive Forecast',
              })}
            </h2>
            {forecastAlertCount > 0 && (
              <span className="inline-flex items-center justify-center min-w-[18px] h-[18px] px-1.5 rounded-full bg-rose-500 text-white text-2xs font-semibold">
                {forecastAlertCount}
              </span>
            )}
            <span className="ml-auto text-2xs text-content-tertiary">
              {t('project_intelligence.forecast.section_hint', {
                defaultValue: 'EAC / ETC forecast with threshold alerts',
              })}
            </span>
          </div>
          <ForecastPanel
            projectId={activeProjectId}
            onAlertCountChange={setForecastAlertCount}
          />
        </div>
      </div>

      {/* Section 2d — Live predictive cost + schedule + risk analytics (#19) */}
      <div>
        <div className="rounded-xl border border-border-light bg-white dark:bg-gray-800/60 shadow-sm p-4">
          <div className="flex items-center gap-2 mb-3">
            <TrendingUp size={16} className="text-oe-blue" />
            <h2 className="text-sm font-semibold text-content-primary">
              {t('project_intelligence.insights.section_title', {
                defaultValue: 'Predictive Risk Analytics',
              })}
            </h2>
            <span className="ml-auto text-2xs text-content-tertiary">
              {t('project_intelligence.insights.section_hint', {
                defaultValue: 'CPI/SPI/EAC, finish-variance and cost-overrun risk',
              })}
            </span>
          </div>
          <ForecastInsightsPanel projectId={activeProjectId} />
        </div>
      </div>

      {/* Section 3 — Domain detail tabs (reduced to 4) */}
      <div>
        <DomainDetails
          state={state as DomainStateMap}
          scores={score.domain_scores}
          selectedDomain={selectedDomain}
          onSelectDomain={setSelectedDomain}
          onAction={handleAction}
          actions={actions}
          allowedDomains={RFC25_DETAIL_DOMAINS}
        />
      </div>

      {/* Section 4 — Cost Intelligence Advisor */}
      <div className="pb-2">
        <AIAdvisorPanel
          projectId={activeProjectId}
          role={role}
          projectName={state.project_name ?? ''}
          score={score}
        />
      </div>
    </div>
  );
}

