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

const API_BASE = '/api/v1/project_intelligence';

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

        const res = await fetch(
          `${API_BASE}/summary/?project_id=${activeProjectId}${refresh ? '&refresh=true' : ''}`,
          {
            headers: {
              Authorization: `Bearer ${localStorage.getItem('oe_token') || ''}`,
            },
          }
        );
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data: Summary = await res.json();
        setSummary(data);
        setLastRefresh(new Date());

        // Fetch available actions
        const actRes = await fetch(
          `${API_BASE}/actions/?project_id=${activeProjectId}`,
          {
            headers: {
              Authorization: `Bearer ${localStorage.getItem('oe_token') || ''}`,
            },
          }
        );
        if (actRes.ok) {
          setActions(await actRes.json());
        }
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
        const res = await fetch(
          `${API_BASE}/actions/${actionId}/?project_id=${activeProjectId}`,
          {
            method: 'POST',
            headers: {
              Authorization: `Bearer ${localStorage.getItem('oe_token') || ''}`,
              'Content-Type': 'application/json',
            },
          }
        );
        const result = await res.json();
        if (result.redirect_url) {
          window.location.href = result.redirect_url;
        } else {
          // Re-fetch data after action
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
      <div className="flex items-center justify-center h-full">
        <div className="text-center space-y-3">
          <BrainCircuit size={48} className="mx-auto text-content-tertiary" />
          <h2 className="text-lg font-semibold text-content-primary">
            {t('project_intelligence.no_project', { defaultValue: 'No project selected' })}
          </h2>
          <p className="text-sm text-content-secondary max-w-md">
            {t('project_intelligence.select_project', {
              defaultValue:
                'Select a project from the Projects page to view its intelligence analysis.',
            })}
          </p>
        </div>
      </div>
    );
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="text-center space-y-3 animate-pulse">
          <BrainCircuit size={48} className="mx-auto text-content-tertiary" />
          <p className="text-sm text-content-secondary">
            {t('project_intelligence.analyzing', { defaultValue: 'Analyzing project...' })}
          </p>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="text-center space-y-3">
          <AlertTriangle size={48} className="mx-auto text-yellow-500" />
          <p className="text-sm text-content-secondary">{error}</p>
          <button
            onClick={() => fetchData()}
            className="px-4 py-2 text-sm bg-oe-blue text-white rounded-lg hover:bg-oe-blue-dark transition-colors"
          >
            {t('common.retry', { defaultValue: 'Retry' })}
          </button>
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
              </h1>
              <p className="text-xs text-content-tertiary">
                {state.project_name || t('project_intelligence.unnamed', { defaultValue: 'Unnamed Project' })}
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
            {/* Score ring card */}
            <div className="bg-surface-secondary rounded-xl border border-border-light p-5">
              <div className="flex justify-center mb-5">
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

            {/* Critical gaps */}
            {score.critical_gaps.length > 0 && (
              <div className="bg-surface-secondary rounded-xl border border-border-light p-5">
                <h3 className="text-sm font-semibold text-content-primary mb-3 flex items-center gap-2">
                  <AlertTriangle size={15} className="text-red-400" />
                  {t('project_intelligence.critical_gaps', {
                    defaultValue: 'Critical Gaps',
                  })}
                  <span className="text-xs text-content-tertiary font-normal ml-auto">
                    {score.critical_gaps.length}
                  </span>
                </h3>
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

            {/* Achievements */}
            {score.achievements.length > 0 && (
              <div className="bg-surface-secondary rounded-xl border border-border-light p-5">
                <h3 className="text-sm font-semibold text-content-primary mb-3 flex items-center gap-2">
                  <CheckCircle2 size={15} className="text-green-400" />
                  {t('project_intelligence.achievements', {
                    defaultValue: 'Achievements',
                  })}
                </h3>
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

            {/* Domain details */}
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
