/**
 * Project Intelligence Page — AI-powered project completion analysis.
 *
 * Shows overall score ring, domain score bars, critical gaps,
 * achievements, AI recommendations, and action buttons.
 */

import { useState, useEffect, useCallback } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { apiGet, apiPost } from '@/shared/lib/api';
import { ScoreRing } from './ScoreRing';
import { DomainBar } from './DomainBar';
import { GapCard } from './GapCard';
import { AchievementCard } from './AchievementCard';
import { AIAdvisorPanel } from './AIAdvisorPanel';
import { DomainDetails } from './DomainDetails';
import {
  RefreshCw,
  BrainCircuit,
  ChevronDown,
  AlertTriangle,
  CheckCircle2,
} from 'lucide-react';

// Domain display config
const DOMAIN_CONFIG: Record<
  string,
  { label: string; color: string }
> = {
  boq: { label: 'BOQ', color: '#f0883e' },
  validation: { label: 'Validation', color: '#3fb950' },
  schedule: { label: 'Schedule', color: '#58a6ff' },
  cost_model: { label: 'Cost Model', color: '#bc8cff' },
  takeoff: { label: 'Takeoff', color: '#39d353' },
  risk: { label: 'Risk', color: '#ff7b72' },
  tendering: { label: 'Tendering', color: '#ffa657' },
  documents: { label: 'Documents', color: '#79c0ff' },
  reports: { label: 'Reports', color: '#56d364' },
};

// Grade color mapping
const GRADE_COLORS: Record<string, string> = {
  A: '#3fb950',
  B: '#8b949e',
  C: '#d29922',
  D: '#f85149',
  F: '#da3633',
};

interface Summary {
  state: any;
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
  const [selectedDomain, setSelectedDomain] = useState<string | null>(null);

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
      } catch (err: any) {
        setError(err.message || 'Failed to load project intelligence');
      } finally {
        setLoading(false);
        setRefreshing(false);
      }
    },
    [activeProjectId]
  );

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  // Execute action
  const handleAction = useCallback(
    async (actionId: string) => {
      if (!activeProjectId) return;
      try {
        const result = await apiPost<{ status: string; message: string; redirect_url?: string }>(
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
    [activeProjectId, fetchData]
  );

  if (!activeProjectId) {
    return (
      <div className="max-w-3xl mx-auto py-12 px-6">
        {/* Hero */}
        <div className="text-center space-y-4 mb-10">
          <div className="w-16 h-16 rounded-2xl bg-oe-blue/10 flex items-center justify-center mx-auto">
            <BrainCircuit size={32} className="text-oe-blue" />
          </div>
          <h2 className="text-xl font-bold text-content-primary">
            {t('project_intelligence.title', { defaultValue: 'Project Intelligence' })}
          </h2>
          <p className="text-sm text-content-secondary max-w-xl mx-auto leading-relaxed">
            {t('project_intelligence.hero_description', {
              defaultValue:
                'Project Intelligence analyzes your project across 9 weighted domains and generates a completeness score from 0 to 100 (grades A through F). It identifies critical gaps that need attention and provides actionable recommendations to improve project quality.',
            })}
          </p>
        </div>

        {/* How it works — step by step */}
        <div className="bg-surface-secondary rounded-xl border border-border-light p-6 mb-6">
          <h3 className="text-sm font-semibold text-content-primary mb-4">
            {t('project_intelligence.how_it_works', { defaultValue: 'How it works' })}
          </h3>
          <div className="grid grid-cols-1 sm:grid-cols-4 gap-4">
            {[
              {
                step: '1',
                title: t('project_intelligence.step1_title', { defaultValue: 'Select a project' }),
                desc: t('project_intelligence.step1_desc', {
                  defaultValue: 'Choose an active project from the header dropdown to begin analysis.',
                }),
              },
              {
                step: '2',
                title: t('project_intelligence.step2_title', { defaultValue: 'View completeness score' }),
                desc: t('project_intelligence.step2_desc', {
                  defaultValue: 'See your overall score (0-100) and per-domain breakdown across BOQ, Validation, Cost Model, and 6 more.',
                }),
              },
              {
                step: '3',
                title: t('project_intelligence.step3_title', { defaultValue: 'Fix gaps' }),
                desc: t('project_intelligence.step3_desc', {
                  defaultValue: 'Review critical gaps sorted by severity. Each gap includes a description, impact, and a one-click fix action.',
                }),
              },
              {
                step: '4',
                title: t('project_intelligence.step4_title', { defaultValue: 'Get AI recommendations' }),
                desc: t('project_intelligence.step4_desc', {
                  defaultValue: 'Connect an AI provider in Settings to receive personalized, role-specific advice and chat with the advisor.',
                }),
              },
            ].map((item) => (
              <div key={item.step} className="text-center sm:text-left">
                <div className="w-8 h-8 rounded-full bg-oe-blue/10 text-oe-blue text-sm font-bold flex items-center justify-center mx-auto sm:mx-0 mb-2">
                  {item.step}
                </div>
                <div className="text-xs font-medium text-content-primary mb-1">{item.title}</div>
                <div className="text-2xs text-content-tertiary leading-relaxed">{item.desc}</div>
              </div>
            ))}
          </div>
        </div>

        {/* Domains overview */}
        <div className="bg-surface-secondary rounded-xl border border-border-light p-6 mb-6">
          <h3 className="text-sm font-semibold text-content-primary mb-1">
            {t('project_intelligence.domains_title', { defaultValue: '9 analysis domains' })}
          </h3>
          <p className="text-2xs text-content-tertiary mb-4">
            {t('project_intelligence.domains_desc', {
              defaultValue:
                'Each domain is weighted by importance. BOQ and Validation carry the most weight; Reports and Documents the least.',
            })}
          </p>
          <div className="grid grid-cols-3 gap-2 text-xs">
            {[
              { label: 'BOQ', weight: '30%', color: '#f0883e' },
              { label: 'Validation', weight: '20%', color: '#3fb950' },
              { label: 'Schedule', weight: '15%', color: '#58a6ff' },
              { label: 'Cost Model', weight: '10%', color: '#bc8cff' },
              { label: 'Takeoff', weight: '8%', color: '#39d353' },
              { label: 'Risk', weight: '7%', color: '#ff7b72' },
              { label: 'Tendering', weight: '5%', color: '#ffa657' },
              { label: 'Documents', weight: '3%', color: '#79c0ff' },
              { label: 'Reports', weight: '2%', color: '#56d364' },
            ].map((d) => (
              <div
                key={d.label}
                className="flex items-center gap-2 rounded-md bg-surface-tertiary px-3 py-2"
              >
                <div className="w-2 h-2 rounded-full shrink-0" style={{ backgroundColor: d.color }} />
                <span className="text-content-secondary">{d.label}</span>
                <span className="ml-auto text-content-quaternary tabular-nums">{d.weight}</span>
              </div>
            ))}
          </div>
        </div>

        {/* Call to action */}
        <div className="flex items-center justify-center gap-2 py-4">
          <AlertTriangle size={16} className="text-amber-500" />
          <span className="text-sm text-amber-700 dark:text-amber-400">
            {t('project_intelligence.select_project', {
              defaultValue: 'Select a project from the header to start analysis',
            })}
          </span>
        </div>
      </div>
    );
  }

  if (loading) {
    return (
      <div className="max-w-content mx-auto py-16">
        <div className="text-center space-y-3 animate-pulse">
          <BrainCircuit size={48} className="mx-auto text-oe-blue" />
          <p className="text-sm text-content-secondary">
            {t('project_intelligence.analyzing', { defaultValue: 'Analyzing project across 9 domains...' })}
          </p>
        </div>
      </div>
    );
  }

  if (error) {
    const isAuth = error.includes('401') || error.includes('auth') || error.includes('Unauthorized');
    return (
      <div className="max-w-content mx-auto py-12">
        <div className="text-center space-y-4">
          <div className="w-14 h-14 rounded-2xl bg-amber-50 dark:bg-amber-950/30 flex items-center justify-center mx-auto">
            <AlertTriangle size={28} className="text-amber-500" />
          </div>
          <h2 className="text-lg font-bold text-content-primary">
            {isAuth
              ? t('project_intelligence.auth_error', { defaultValue: 'Session expired' })
              : t('project_intelligence.load_error', { defaultValue: 'Could not load analysis' })}
          </h2>
          <p className="text-sm text-content-secondary max-w-md mx-auto">
            {isAuth
              ? t('project_intelligence.auth_hint', { defaultValue: 'Please refresh the page or sign in again to continue.' })
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

  const displayGaps = showAllGaps ? score.critical_gaps : score.critical_gaps.slice(0, 5);
  const hasMoreGaps = !showAllGaps && score.critical_gaps.length > 5;

  // Domain scores sorted by weight importance
  const domainOrder = [
    'boq',
    'validation',
    'schedule',
    'cost_model',
    'takeoff',
    'risk',
    'tendering',
    'documents',
    'reports',
  ];

  return (
    <div className="h-full overflow-y-auto">
      {/* Header */}
      <div className="sticky top-0 z-10 bg-surface-primary/95 backdrop-blur-sm border-b border-border-light px-6 py-3">
        <div className="flex items-center justify-between max-w-7xl mx-auto">
          <div className="flex items-center gap-3">
            <BrainCircuit size={20} className="text-oe-blue" />
            <div>
              <h1 className="text-base font-semibold text-content-primary">
                {t('project_intelligence.title', { defaultValue: 'Project Intelligence' })}
                <span className="ml-2 text-xs font-normal text-content-tertiary">
                  — {state.project_name || t('project_intelligence.unnamed', { defaultValue: 'Unnamed Project' })}
                </span>
              </h1>
              <p className="text-xs text-content-quaternary">
                {t('project_intelligence.header_desc', {
                  defaultValue: 'AI analysis of 9 domains: BOQ, Validation, Schedule, Cost Model, Takeoff, Risk, Tendering, Documents, Reports',
                })}
              </p>
            </div>
          </div>
          <div className="flex items-center gap-3">
            {/* Role selector */}
            <select
              value={role}
              onChange={(e) => setRole(e.target.value)}
              className="text-xs bg-surface-secondary border border-border-light rounded-md px-2 py-1.5 text-content-secondary focus:outline-none focus:ring-1 focus:ring-oe-blue"
              aria-label={t('project_intelligence.role', { defaultValue: 'View as role' })}
            >
              <option value="estimator">
                {t('project_intelligence.role_estimator', { defaultValue: 'Estimator' })}
              </option>
              <option value="manager">
                {t('project_intelligence.role_manager', { defaultValue: 'Manager' })}
              </option>
              <option value="explorer">
                {t('project_intelligence.role_explorer', { defaultValue: 'Explorer' })}
              </option>
            </select>

            {/* Refresh */}
            <button
              onClick={() => fetchData(true)}
              disabled={refreshing}
              className="flex items-center gap-1.5 text-xs text-content-secondary hover:text-content-primary transition-colors disabled:opacity-50"
              title={t('project_intelligence.refresh', { defaultValue: 'Refresh analysis' })}
            >
              <RefreshCw size={14} className={refreshing ? 'animate-spin' : ''} />
              {lastRefresh && (
                <span>{_formatAgo(lastRefresh)}</span>
              )}
            </button>
          </div>
        </div>
      </div>

      {/* Main content — two column layout */}
      <div className="max-w-7xl mx-auto px-6 py-6">
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
          {/* Left column — Score + Gaps + Achievements */}
          <div className="lg:col-span-4 space-y-5">
            {/* Completeness Score section */}
            <div className="bg-surface-secondary rounded-xl border border-border-light p-5">
              <div className="mb-4">
                <h3 className="text-sm font-semibold text-content-primary">
                  {t('project_intelligence.completeness_score', {
                    defaultValue: 'Completeness Score',
                  })}
                </h3>
                <p className="text-2xs text-content-tertiary mt-0.5 leading-relaxed">
                  {t('project_intelligence.completeness_score_desc', {
                    defaultValue:
                      'How complete is your project across 9 weighted domains. BOQ (30%) and Validation (20%) carry the most weight.',
                  })}
                </p>
              </div>
              <div className="flex justify-center mb-5" title={t('project_intelligence.score_tooltip', { defaultValue: 'Score is calculated from 9 domains weighted by importance: BOQ 30%, Validation 20%, Schedule 15%, Cost Model 10%, Takeoff 8%, Risk 7%, Tendering 5%, Documents 3%, Reports 2%' })}>
                <ScoreRing
                  score={score.overall}
                  grade={score.overall_grade}
                  gradeColor={gradeColor}
                  size={160}
                  strokeWidth={10}
                />
              </div>

              {/* Domain bars */}
              <div className="space-y-2">
                {domainOrder.map((domain) => {
                  const dscore = score.domain_scores[domain] ?? 0;
                  const config = DOMAIN_CONFIG[domain];
                  if (!config) return null;
                  return (
                    <DomainBar
                      key={domain}
                      label={config.label}
                      score={dscore}
                      color={config.color}
                      onClick={() =>
                        setSelectedDomain(selectedDomain === domain ? null : domain)
                      }
                      isSelected={selectedDomain === domain}
                    />
                  );
                })}
              </div>
            </div>

            {/* Critical gaps section */}
            {score.critical_gaps.length > 0 && (
              <div className="bg-surface-secondary rounded-xl border border-border-light p-5">
                <div className="mb-3">
                  <h3 className="text-sm font-semibold text-content-primary flex items-center gap-2">
                    <AlertTriangle size={15} className="text-red-400" />
                    {t('project_intelligence.critical_gaps', {
                      defaultValue: 'Critical Gaps',
                    })}
                    <span className="text-xs text-content-tertiary font-normal ml-auto">
                      {score.critical_gaps.length}
                    </span>
                  </h3>
                  <p className="text-2xs text-content-tertiary mt-0.5 leading-relaxed">
                    {t('project_intelligence.critical_gaps_desc', {
                      defaultValue:
                        'Issues that need attention, sorted by severity. Expand each gap to see its impact and available fix actions.',
                    })}
                  </p>
                </div>
                <div className="space-y-2">
                  {displayGaps.map((gap) => (
                    <GapCard
                      key={gap.id}
                      gap={gap}
                      isExpanded={expandedGap === gap.id}
                      onToggle={() =>
                        setExpandedGap(expandedGap === gap.id ? null : gap.id)
                      }
                      onAction={gap.action_id ? () => handleAction(gap.action_id!) : undefined}
                      actionLabel={
                        actions.find((a) => a.id === gap.action_id)?.label
                      }
                    />
                  ))}
                  {hasMoreGaps && (
                    <button
                      onClick={() => setShowAllGaps(true)}
                      className="w-full text-xs text-content-tertiary hover:text-content-secondary py-1.5 flex items-center justify-center gap-1 transition-colors"
                    >
                      <ChevronDown size={12} />
                      {t('project_intelligence.show_more_gaps', {
                        defaultValue: '{{count}} more',
                        count: score.critical_gaps.length - 5,
                      })}
                    </button>
                  )}
                </div>
              </div>
            )}

            {/* No gaps — all clear */}
            {score.critical_gaps.length === 0 && (
              <div className="bg-surface-secondary rounded-xl border border-border-light p-5 text-center">
                <CheckCircle2 size={24} className="mx-auto text-green-400 mb-2" />
                <p className="text-sm font-medium text-content-primary">
                  {t('project_intelligence.no_gaps_title', {
                    defaultValue: 'No critical gaps',
                  })}
                </p>
                <p className="text-2xs text-content-tertiary mt-1">
                  {t('project_intelligence.no_gaps_desc', {
                    defaultValue:
                      'Your project has no critical issues. Keep adding data to improve your score further.',
                  })}
                </p>
              </div>
            )}

            {/* Achievements section */}
            {score.achievements.length > 0 && (
              <div className="bg-surface-secondary rounded-xl border border-border-light p-5">
                <div className="mb-3">
                  <h3 className="text-sm font-semibold text-content-primary flex items-center gap-2">
                    <CheckCircle2 size={15} className="text-green-400" />
                    {t('project_intelligence.achievements', {
                      defaultValue: 'Achievements',
                    })}
                  </h3>
                  <p className="text-2xs text-content-tertiary mt-0.5 leading-relaxed">
                    {t('project_intelligence.achievements_desc', {
                      defaultValue:
                        'What you have done well. These are milestones your project has already reached.',
                    })}
                  </p>
                </div>
                <div className="space-y-1.5">
                  {score.achievements.map((ach, i) => (
                    <AchievementCard key={i} achievement={ach} />
                  ))}
                </div>
              </div>
            )}
          </div>

          {/* Right column — AI Advisor + Domain Details */}
          <div className="lg:col-span-8 space-y-5">
            {/* AI Advisor */}
            <AIAdvisorPanel
              projectId={activeProjectId}
              role={role}
              projectName={state.project_name}
              score={score}
            />

            {/* Domain Analysis section */}
            <div>
              <div className="mb-2 px-1">
                <h3 className="text-sm font-semibold text-content-primary">
                  {t('project_intelligence.domain_analysis', {
                    defaultValue: 'Domain Analysis',
                  })}
                </h3>
                <p className="text-2xs text-content-tertiary mt-0.5">
                  {t('project_intelligence.domain_analysis_desc', {
                    defaultValue:
                      'Click a domain tab to see detailed metrics, status indicators, and available actions for each area.',
                  })}
                </p>
              </div>
              <DomainDetails
                state={state}
                scores={score.domain_scores}
                selectedDomain={selectedDomain}
                onSelectDomain={setSelectedDomain}
                onAction={handleAction}
                actions={actions}
              />
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

/** Format relative time, e.g. "2m ago". */
function _formatAgo(date: Date): string {
  const seconds = Math.floor((Date.now() - date.getTime()) / 1000);
  if (seconds < 60) return 'just now';
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  return `${hours}h ago`;
}
