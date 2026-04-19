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
import { useSearchParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { apiGet, apiPost } from '@/shared/lib/api';
import { ScoreRing } from './ScoreRing';
import { GapCard } from './GapCard';
import { AIAdvisorPanel } from './AIAdvisorPanel';
import { DomainDetails } from './DomainDetails';
import { ProjectKPIHero } from './components/ProjectKPIHero';
import { ProjectAnalyticsGrid } from './components/ProjectAnalyticsGrid';
import {
  RefreshCw,
  BrainCircuit,
  ChevronDown,
  AlertTriangle,
  CheckCircle2,
} from 'lucide-react';

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
  const [searchParams] = useSearchParams();
  const projectId = useProjectContextStore((s) => s.activeProjectId);
  const paramProjectId = searchParams.get('project_id');
  const activeProjectId = paramProjectId || projectId;

  const [summary, setSummary] = useState<Summary | null>(null);
  const [actions, setActions] = useState<ActionDef[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastRefresh, setLastRefresh] = useState<Date | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [role, setRole] = useState<string>('estimator');
  const [expandedGap, setExpandedGap] = useState<string | null>(null);
  const [showAllGaps, setShowAllGaps] = useState(false);
  const [selectedDomain, setSelectedDomain] = useState<string | null>('boq');

  // Anomaly + line-item data used to enrich the Critical Gaps card with $ impact.
  const [anomalies, setAnomalies] = useState<AnomalyRow[]>([]);
  const [lineItems, setLineItems] = useState<LineItemRow[]>([]);

  // Fetch summary data
  const fetchData = useCallback(
    async (refresh = false) => {
      if (!activeProjectId) return;
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
          window.location.href = result.redirect_url;
        } else {
          fetchData(true);
        }
      } catch {
        // Silently handle
      }
    },
    [activeProjectId, fetchData],
  );

  if (!activeProjectId) {
    return (
      <div className="max-w-3xl mx-auto py-12 px-6 text-center space-y-4">
        <div className="w-14 h-14 rounded-2xl bg-oe-blue/10 flex items-center justify-center mx-auto">
          <BrainCircuit size={28} className="text-oe-blue" />
        </div>
        <h2 className="text-lg font-bold text-content-primary">
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
          <h2 className="text-lg font-bold text-content-primary">
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
              ? `$${(costUncertainty / 1_000_000).toFixed(1)}M`
              : costUncertainty >= 1_000
              ? `$${(costUncertainty / 1_000).toFixed(0)}k`
              : `$${costUncertainty.toFixed(0)}`,
        })
      : null;

  const displayGaps = showAllGaps
    ? score.critical_gaps
    : score.critical_gaps.slice(0, 5);
  const hasMoreGaps = !showAllGaps && score.critical_gaps.length > 5;

  return (
    <div className="h-full overflow-y-auto">
      {/* Header */}
      <div className="sticky top-0 z-10 bg-surface-primary/95 backdrop-blur-sm border-b border-border-light py-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <BrainCircuit size={20} className="text-oe-blue" />
            <div>
              <h1 className="text-base font-semibold text-content-primary">
                {t('project_intelligence.page_title_v191', {
                  defaultValue: 'Estimation Dashboard',
                })}
                <span className="ml-2 text-xs font-normal text-content-tertiary">
                  —{' '}
                  {state.project_name ||
                    t('project_intelligence.unnamed', {
                      defaultValue: 'Unnamed Project',
                    })}
                </span>
              </h1>
              <p className="text-xs text-content-quaternary">
                {t('project_intelligence.v191_header_desc', {
                  defaultValue:
                    'Cost variance, anomalies, bid analytics — refreshed every 60s.',
                })}
              </p>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <select
              value={role}
              onChange={(e) => setRole(e.target.value)}
              className="text-xs bg-surface-secondary border border-border-light rounded-md px-2 py-1.5 text-content-secondary focus:outline-none focus:ring-1 focus:ring-oe-blue"
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
              className="flex items-center gap-1.5 text-xs text-content-secondary hover:text-content-primary transition-colors disabled:opacity-50"
              title={t('project_intelligence.refresh', {
                defaultValue: 'Refresh analysis',
              })}
            >
              <RefreshCw size={14} className={refreshing ? 'animate-spin' : ''} />
              {lastRefresh && <span>{formatAgo(lastRefresh)}</span>}
            </button>
          </div>
        </div>
      </div>

      {/* Section 1 — KPI hero */}
      <div className="py-4">
        <ProjectKPIHero projectId={activeProjectId} />
      </div>

      {/* Section 2 — Readiness + Critical gaps (side-by-side, equal height) */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-4 pb-4">
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
      <div className="pb-4">
        <ProjectAnalyticsGrid projectId={activeProjectId} />
      </div>

      {/* Section 3 — Domain detail tabs (reduced to 4) */}
      <div className="pb-4">
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
      <div className="pb-6">
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

/** Format relative time, e.g. "2m ago". */
function formatAgo(date: Date): string {
  const seconds = Math.floor((Date.now() - date.getTime()) / 1000);
  if (seconds < 60) return 'just now';
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  return `${hours}h ago`;
}
