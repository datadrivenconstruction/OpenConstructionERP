import { useState, useMemo, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  ShieldCheck,
  Play,
  AlertTriangle,
  CheckCircle2,
  XCircle,
  Info,
  ChevronDown,
  ChevronRight,
  Download,
  Wand2,
  Filter,
  ExternalLink,
} from 'lucide-react';
import { Button, Card, Badge, EmptyState, Skeleton, Breadcrumb } from '@/shared/ui';
import { apiGet, apiPost, triggerDownload } from '@/shared/lib/api';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { useToastStore } from '@/stores/useToastStore';
import { useAuthStore } from '@/stores/useAuthStore';

/* ── Types ─────────────────────────────────────────────────────────────── */

interface Project {
  id: string;
  name: string;
  description: string;
  classification_standard: string;
}

interface BOQ {
  id: string;
  project_id: string;
  name: string;
  description: string;
  status: string;
}

interface ValidationResultItem {
  rule_id: string;
  rule_name: string;
  severity: 'error' | 'warning' | 'info';
  passed: boolean;
  message: string;
  element_ref: string | null;
  suggestion: string | null;
}

interface ValidationReportData {
  id: string;
  status: 'passed' | 'warnings' | 'errors' | 'skipped';
  score: number;
  counts: {
    total: number;
    passed: number;
    errors: number;
    warnings: number;
    infos: number;
  };
  rule_sets: string[];
  duration_ms: number;
  results: ValidationResultItem[];
}

type FilterMode = 'all' | 'errors' | 'warnings' | 'info' | 'passed';

/* ── Rule descriptions for tooltips ───────────────────────────────────── */

function getRuleDescriptions(t: (key: string, opts?: Record<string, unknown>) => string): Record<string, string> {
  return {
    'boq_quality.position_has_quantity': t('validation.rule_position_has_quantity', { defaultValue: 'Checks that every BOQ position has a quantity greater than zero.' }),
    'boq_quality.position_has_unit_rate': t('validation.rule_position_has_unit_rate', { defaultValue: 'Checks that every position has a unit rate assigned.' }),
    'boq_quality.position_has_description': t('validation.rule_position_has_description', { defaultValue: 'Checks that every position has a meaningful description.' }),
    'boq_quality.no_duplicate_ordinals': t('validation.rule_no_duplicate_ordinals', { defaultValue: 'Ensures all ordinal numbers within the BOQ are unique.' }),
    'boq_quality.unit_rate_in_range': t('validation.rule_unit_rate_in_range', { defaultValue: 'Flags unit rates that deviate more than 5x from median.' }),
    'din276.cost_group_required': t('validation.rule_cost_group_required', { defaultValue: 'Ensures every position has a DIN 276 Kostengruppe assigned.' }),
    'din276.valid_cost_group': t('validation.rule_valid_cost_group', { defaultValue: 'Validates that DIN 276 codes are proper 3-digit codes.' }),
    'gaeb.ordinal_format': t('validation.rule_ordinal_format', { defaultValue: 'Checks ordinal numbers follow GAEB LV format XX.XX.XXXX.' }),
  };
}

/* ── Helpers ───────────────────────────────────────────────────────────── */

function getScoreLabel(pct: number, t: (key: string, fallback: string) => string): string {
  if (pct >= 95) return t('validation.score_excellent', 'Excellent');
  if (pct >= 80) return t('validation.score_good', 'Good');
  if (pct >= 60) return t('validation.score_needs_review', 'Needs Review');
  return t('validation.score_poor', 'Poor');
}

function getScoreColor(pct: number): string {
  if (pct >= 95) return 'text-semantic-success';
  if (pct >= 80) return 'text-oe-blue';
  if (pct >= 60) return 'text-semantic-warning';
  return 'text-semantic-error';
}

function getScoreRingColor(pct: number): string {
  if (pct >= 95) return 'stroke-semantic-success';
  if (pct >= 80) return 'stroke-oe-blue';
  if (pct >= 60) return 'stroke-semantic-warning';
  return 'stroke-semantic-error';
}

/* ── Sub-components ────────────────────────────────────────────────────── */

function ScoreCircle({ score }: { score: number }) {
  const { t } = useTranslation();
  const pct = Math.round(score * 100);
  const radius = 54;
  const circumference = 2 * Math.PI * radius;
  const dashOffset = circumference - (pct / 100) * circumference;

  return (
    <div className="flex flex-col items-center gap-2">
      <div className="relative h-36 w-36">
        <svg className="h-36 w-36 -rotate-90" viewBox="0 0 120 120" role="img" aria-label={`${t('validation.quality_score', { defaultValue: 'Quality score' })}: ${pct}%`}>
          <circle
            cx="60"
            cy="60"
            r={radius}
            fill="none"
            stroke="currentColor"
            strokeWidth="8"
            className="text-surface-secondary"
          />
          <circle
            cx="60"
            cy="60"
            r={radius}
            fill="none"
            strokeWidth="8"
            strokeLinecap="round"
            className={`${getScoreRingColor(pct)} transition-all duration-700 ease-out`}
            style={{
              strokeDasharray: circumference,
              strokeDashoffset: dashOffset,
            }}
          />
        </svg>
        <div className="absolute inset-0 flex flex-col items-center justify-center">
          <span className={`text-3xl font-bold tabular-nums ${getScoreColor(pct)}`}>
            {pct}
          </span>
          <span className={`text-sm font-medium ${getScoreColor(pct)}`}>%</span>
        </div>
      </div>
      <span className={`text-sm font-semibold ${getScoreColor(pct)}`}>
        {getScoreLabel(pct, t)}
      </span>
    </div>
  );
}

function SummaryCard({ report }: { report: ValidationReportData }) {
  const { t } = useTranslation();

  return (
    <Card>
      <div className="space-y-3">
        <h3 className="text-sm font-semibold text-content-primary">
          {t('validation.summary', 'Summary')}
        </h3>
        <div className="space-y-2">
          <div className="flex items-center justify-between text-sm">
            <span className="text-content-secondary">
              {t('validation.rules_checked', 'Rules checked')}
            </span>
            <span className="font-medium text-content-primary tabular-nums">
              {report.counts.total}
            </span>
          </div>
          <div className="flex items-center justify-between text-sm">
            <span className="flex items-center gap-2 text-content-secondary">
              <CheckCircle2 size={14} className="text-semantic-success" />
              {t('validation.passed', 'Passed')}
            </span>
            <span className="font-medium text-semantic-success tabular-nums">
              {report.counts.passed}
            </span>
          </div>
          <div className="flex items-center justify-between text-sm">
            <span className="flex items-center gap-2 text-content-secondary">
              <AlertTriangle size={14} className="text-semantic-warning" />
              {t('validation.warnings', 'Warnings')}
            </span>
            <span className="font-medium text-semantic-warning tabular-nums">
              {report.counts.warnings}
            </span>
          </div>
          <div className="flex items-center justify-between text-sm">
            <span className="flex items-center gap-2 text-content-secondary">
              <XCircle size={14} className="text-semantic-error" />
              {t('validation.errors', 'Errors')}
            </span>
            <span className="font-medium text-semantic-error tabular-nums">
              {report.counts.errors}
            </span>
          </div>
        </div>
        <div className="border-t border-border-light pt-3">
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="text-xs text-content-tertiary">
              {t('validation.rule_sets', 'Rule sets')}:
            </span>
            {report.rule_sets.map((rs) => (
              <Badge key={rs} variant="neutral" size="sm">
                {rs}
              </Badge>
            ))}
          </div>
          <p className="mt-1.5 text-xs text-content-tertiary tabular-nums">
            {t('validation.duration', 'Duration')}: {report.duration_ms.toFixed(1)}ms
          </p>
        </div>
      </div>
    </Card>
  );
}

function ResultRow({
  result,
  expanded,
  onToggle,
  boqId,
  onNavigateToPosition,
}: {
  result: ValidationResultItem;
  expanded: boolean;
  onToggle: () => void;
  boqId?: string;
  onNavigateToPosition?: (boqId: string, positionId: string) => void;
}) {
  const { t } = useTranslation();

  const statusIcon = result.passed ? (
    <CheckCircle2 size={16} className="shrink-0 text-semantic-success" />
  ) : result.severity === 'error' ? (
    <XCircle size={16} className="shrink-0 text-semantic-error" />
  ) : (
    <AlertTriangle size={16} className="shrink-0 text-semantic-warning" />
  );

  const statusBadgeVariant = result.passed
    ? 'success'
    : result.severity === 'error'
      ? 'error'
      : 'warning';

  const statusLabel = result.passed
    ? t('validation.status_passed', 'Passed')
    : result.severity === 'error'
      ? t('validation.status_error', 'Error')
      : t('validation.status_warning', 'Warning');

  const tooltip = getRuleDescriptions(t)[result.rule_id] || '';

  return (
    <div
      className={`rounded-xl border transition-all duration-fast ${
        expanded
          ? 'border-border bg-surface-primary shadow-xs'
          : 'border-border-light bg-surface-primary hover:bg-surface-secondary/50'
      }`}
    >
      <button
        onClick={onToggle}
        className="flex w-full items-center gap-3 px-4 py-3 text-left"
        title={tooltip}
      >
        {statusIcon}
        <div className="min-w-0 flex-1">
          <span className="text-sm font-medium text-content-primary">
            {result.rule_name}
          </span>
        </div>
        {result.element_ref && (
          <span className="hidden text-xs font-mono text-content-tertiary sm:inline-block">
            {result.element_ref.substring(0, 8)}
          </span>
        )}
        <Badge variant={statusBadgeVariant as 'success' | 'error' | 'warning'} size="sm">
          {statusLabel}
        </Badge>
        <span className="shrink-0 text-content-tertiary">
          {expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        </span>
      </button>

      {expanded && (
        <div className="border-t border-border-light px-4 py-3 animate-fade-in">
          <p className="text-sm text-content-secondary">{result.message}</p>
          {result.suggestion && (
            <div className="mt-2 flex items-start gap-2 rounded-lg bg-oe-blue-subtle px-3 py-2">
              <Wand2 size={14} className="mt-0.5 shrink-0 text-oe-blue" />
              <p className="text-xs text-oe-blue">
                {t('validation.suggestion', 'Suggestion')}: {result.suggestion}
              </p>
            </div>
          )}
          {result.element_ref && (
            <p className="mt-2 flex items-center gap-1.5 text-xs text-content-tertiary">
              <Info size={12} />
              {t('validation.element_ref', 'Element')}:{' '}
              {boqId && onNavigateToPosition ? (
                <button
                  onClick={(e) => { e.stopPropagation(); onNavigateToPosition(boqId, result.element_ref!); }}
                  className="inline-flex items-center gap-1 text-oe-blue hover:underline font-mono"
                >
                  {result.element_ref.substring(0, 8)}...
                  <ExternalLink size={10} />
                </button>
              ) : (
                <span className="font-mono">{result.element_ref}</span>
              )}
            </p>
          )}
          {tooltip && (
            <p className="mt-1 text-xs text-content-tertiary italic">{tooltip}</p>
          )}
        </div>
      )}
    </div>
  );
}

function FilterBar({
  filter,
  onFilterChange,
  counts,
}: {
  filter: FilterMode;
  onFilterChange: (f: FilterMode) => void;
  counts: { all: number; errors: number; warnings: number; infos: number; passed: number };
}) {
  const { t } = useTranslation();

  const options: { value: FilterMode; label: string; count: number }[] = [
    { value: 'all', label: t('validation.filter_all', 'All'), count: counts.all },
    { value: 'errors', label: t('validation.filter_errors', 'Errors'), count: counts.errors },
    { value: 'warnings', label: t('validation.filter_warnings', 'Warnings'), count: counts.warnings },
    { value: 'info', label: t('validation.filter_info', 'Info'), count: counts.infos },
    { value: 'passed', label: t('validation.filter_passed', 'Passed'), count: counts.passed },
  ];

  return (
    <div className="flex items-center gap-1.5">
      <Filter size={14} className="text-content-tertiary" />
      {options.map((opt) => (
        <button
          key={opt.value}
          onClick={() => onFilterChange(opt.value)}
          aria-pressed={filter === opt.value}
          className={`inline-flex items-center gap-1 rounded-lg px-2.5 py-1.5 text-xs font-medium transition-all duration-fast ${
            filter === opt.value
              ? 'bg-oe-blue text-content-inverse shadow-xs'
              : 'bg-surface-secondary text-content-secondary hover:bg-surface-tertiary'
          }`}
        >
          {opt.label}
          <span
            className={`tabular-nums ${
              filter === opt.value ? 'text-content-inverse/70' : 'text-content-tertiary'
            }`}
          >
            {opt.count}
          </span>
        </button>
      ))}
    </div>
  );
}

function SelectDropdown({
  label,
  value,
  onChange,
  options,
  placeholder,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  options: { value: string; label: string }[];
  placeholder: string;
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <label className="text-sm font-medium text-content-primary">{label}</label>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className={`h-10 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm transition-all duration-normal ease-oe focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue hover:border-content-tertiary ${
          !value ? 'text-content-tertiary' : 'text-content-primary'
        }`}
      >
        <option value="">{placeholder}</option>
        {options.map((opt) => (
          <option key={opt.value} value={opt.value}>
            {opt.label}
          </option>
        ))}
      </select>
    </div>
  );
}

/* ── Main Page ─────────────────────────────────────────────────────────── */

export function ValidationPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { activeProjectId, setActiveProject } = useProjectContextStore();
  const addToast = useToastStore((s) => s.addToast);

  const selectedProjectId = activeProjectId ?? '';
  const [selectedBoqId, setSelectedBoqId] = useState('');
  const [filter, setFilter] = useState<FilterMode>('all');
  const [expandedResults, setExpandedResults] = useState<Set<number>>(new Set());

  // Fetch projects
  const { data: projects, isLoading: projectsLoading } = useQuery({
    queryKey: ['projects'],
    queryFn: () => apiGet<Project[]>('/v1/projects/'),
    staleTime: 5 * 60_000,
  });

  // Fetch BOQs for selected project
  const { data: boqs, isLoading: boqsLoading } = useQuery({
    queryKey: ['boqs', selectedProjectId],
    queryFn: () => apiGet<BOQ[]>(`/v1/boq/boqs/?project_id=${selectedProjectId}`),
    enabled: !!selectedProjectId,
  });

  // Validation report state (stored from mutation result)
  const [report, setReport] = useState<ValidationReportData | null>(null);

  // Run validation mutation
  const runValidation = useMutation({
    mutationFn: () =>
      apiPost<ValidationReportData>(`/v1/boq/boqs/${selectedBoqId}/validate/`),
    onSuccess: (data) => {
      setReport(data);
      setFilter('all');
      setExpandedResults(new Set());
      queryClient.invalidateQueries({ queryKey: ['validation', selectedBoqId] });
    },
    onError: (err: Error) => {
      addToast({ type: 'error', title: t('validation.run_failed', { defaultValue: 'Validation failed' }), message: err.message });
    },
  });

  // Reset BOQ selection when project changes
  const handleProjectChange = useCallback(
    (projectId: string) => {
      const name = projects?.find((p) => p.id === projectId)?.name ?? '';
      if (projectId) {
        setActiveProject(projectId, name);
      } else {
        useProjectContextStore.getState().clearProject();
      }
      setSelectedBoqId('');
      setReport(null);
    },
    [projects, setActiveProject],
  );

  const handleBoqChange = useCallback((boqId: string) => {
    setSelectedBoqId(boqId);
    setReport(null);
  }, []);

  // Filter results
  const filteredResults = useMemo(() => {
    if (!report) return [];
    let results: ValidationResultItem[];
    switch (filter) {
      case 'errors':
        results = report.results.filter((r) => !r.passed && r.severity === 'error');
        break;
      case 'warnings':
        results = report.results.filter((r) => !r.passed && r.severity === 'warning');
        break;
      case 'info':
        results = report.results.filter((r) => !r.passed && r.severity === 'info');
        break;
      case 'passed':
        results = report.results.filter((r) => r.passed);
        break;
      default:
        results = [...report.results];
    }
    // Sort: errors first, then warnings, then info, then passed
    const severityOrder: Record<string, number> = { error: 0, warning: 1, info: 2 };
    return results.sort((a, b) => {
      if (a.passed !== b.passed) return a.passed ? 1 : -1;
      return (severityOrder[a.severity] ?? 3) - (severityOrder[b.severity] ?? 3);
    });
  }, [report, filter]);

  const filterCounts = useMemo(() => {
    if (!report) return { all: 0, errors: 0, warnings: 0, infos: 0, passed: 0 };
    return {
      all: report.results.length,
      errors: report.results.filter((r) => !r.passed && r.severity === 'error').length,
      warnings: report.results.filter((r) => !r.passed && r.severity === 'warning').length,
      infos: report.results.filter((r) => !r.passed && r.severity === 'info').length,
      passed: report.results.filter((r) => r.passed).length,
    };
  }, [report]);

  const toggleResult = useCallback((idx: number) => {
    setExpandedResults((prev) => {
      const next = new Set(prev);
      if (next.has(idx)) {
        next.delete(idx);
      } else {
        next.add(idx);
      }
      return next;
    });
  }, []);

  const handleExportPdf = useCallback(async () => {
    if (!selectedBoqId) return;
    try {
      const token = useAuthStore.getState().accessToken;
      const response = await fetch(`/api/v1/boq/boqs/${selectedBoqId}/export/pdf/`, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      if (!response.ok) throw new Error(`Export failed: ${response.status}`);
      const blob = await response.blob();
      triggerDownload(blob, `validation_report.pdf`);
    } catch (err) {
      addToast({
        type: 'error',
        title: t('validation.export_failed', { defaultValue: 'Export failed' }),
        message: err instanceof Error ? err.message : undefined,
      });
    }
  }, [selectedBoqId, addToast, t]);

  const projectOptions = (projects || []).map((p) => ({
    value: p.id,
    label: p.name,
  }));

  const boqOptions = (boqs || []).map((b) => ({
    value: b.id,
    label: b.name,
  }));

  return (
    <div className="w-full animate-fade-in">
      <Breadcrumb items={[
        { label: t('nav.dashboard', 'Dashboard'), to: '/' },
        { label: t('validation.title', 'Validation Dashboard') },
      ]} className="mb-4" />

      {/* Header */}
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-content-primary">
          {t('validation.title', 'Validation Dashboard')}
        </h1>
        <p className="mt-1 text-sm text-content-secondary">
          {t(
            'validation.subtitle',
            'Select a project and BOQ to validate against configured rule sets',
          )}
        </p>
      </div>

      {/* Selector bar */}
      <Card className="mb-6">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-end">
          <div className="flex-1">
            {projectsLoading ? (
              <Skeleton height={40} className="w-full" rounded="md" />
            ) : (
              <SelectDropdown
                label={t('validation.select_project', 'Project')}
                value={selectedProjectId}
                onChange={handleProjectChange}
                options={projectOptions}
                placeholder={t('validation.select_project_placeholder', 'Choose a project...')}
              />
            )}
          </div>
          <div className="flex-1">
            {boqsLoading ? (
              <Skeleton height={40} className="w-full" rounded="md" />
            ) : (
              <SelectDropdown
                label={t('validation.select_boq', 'Bill of Quantities')}
                value={selectedBoqId}
                onChange={handleBoqChange}
                options={boqOptions}
                placeholder={
                  selectedProjectId
                    ? t('validation.select_boq_placeholder', 'Choose a BOQ...')
                    : t('validation.select_project_first', 'Select a project first')
                }
              />
            )}
          </div>
          <div className="shrink-0">
            <span title={!selectedBoqId ? t('validation.select_boq_first', { defaultValue: 'Select a project and BOQ first' }) : undefined}>
              <Button
                variant="primary"
                size="md"
                icon={<Play size={16} />}
                loading={runValidation.isPending}
                disabled={!selectedBoqId}
                onClick={() => runValidation.mutate()}
              >
                {t('validation.run', 'Run Validation')}
              </Button>
            </span>
          </div>
        </div>
      </Card>

      {/* No selection state */}
      {!report && !runValidation.isPending && (
        <EmptyState
          icon={<ShieldCheck size={28} strokeWidth={1.5} />}
          title={t('validation.empty_title', 'No validation report yet')}
          description={t(
            'validation.empty_description',
            'Select a project and BOQ, then click "Run Validation" to check data quality.',
          )}
        />
      )}

      {/* Loading state */}
      {runValidation.isPending && (
        <div className="space-y-4">
          <div className="flex gap-6">
            <Skeleton width={160} height={200} rounded="lg" />
            <Skeleton height={200} className="flex-1" rounded="lg" />
          </div>
          <Skeleton height={48} className="w-full" rounded="lg" />
          {[1, 2, 3, 4].map((i) => (
            <Skeleton key={i} height={56} className="w-full" rounded="lg" />
          ))}
        </div>
      )}

      {/* Error state */}
      {runValidation.isError && (
        <Card className="border-semantic-error/30 bg-semantic-error-bg">
          <div className="flex items-center gap-3">
            <XCircle size={20} className="text-semantic-error" />
            <div>
              <p className="text-sm font-medium text-semantic-error">
                {t('validation.error_title', 'Validation failed')}
              </p>
              <p className="mt-0.5 text-xs text-content-secondary">
                {runValidation.error instanceof Error
                  ? runValidation.error.message
                  : t(
                      'validation.error_description',
                      'Could not run validation. Check that the BOQ has positions and try again.',
                    )}
              </p>
            </div>
          </div>
        </Card>
      )}

      {/* Report */}
      {report && !runValidation.isPending && (
        <div className="space-y-6 animate-fade-in">
          {/* Score + Summary row */}
          <div className="grid gap-6 md:grid-cols-[200px_1fr]">
            {/* Score circle card */}
            <Card className="flex items-center justify-center">
              <ScoreCircle score={report.score} />
            </Card>

            {/* Summary card */}
            <SummaryCard report={report} />
          </div>

          {/* Filter + Results */}
          <div>
            <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
              <h2 className="text-lg font-semibold text-content-primary">
                {t('validation.results_title', 'Results')}
              </h2>
              <div className="flex items-center gap-3">
                <div className="flex items-center gap-1.5">
                  <button
                    onClick={() => setExpandedResults(new Set(filteredResults.map((_, i) => i)))}
                    className="text-xs font-medium text-content-secondary hover:text-content-primary transition-colors"
                  >
                    {t('validation.expand_all', { defaultValue: 'Expand All' })}
                  </button>
                  <span className="text-content-quaternary">|</span>
                  <button
                    onClick={() => setExpandedResults(new Set())}
                    className="text-xs font-medium text-content-secondary hover:text-content-primary transition-colors"
                  >
                    {t('validation.collapse_all', { defaultValue: 'Collapse All' })}
                  </button>
                </div>
                <FilterBar
                  filter={filter}
                  onFilterChange={setFilter}
                  counts={filterCounts}
                />
              </div>
            </div>

            {/* All passed banner */}
            {report.counts.errors === 0 && report.counts.warnings === 0 && (
              <div className="mb-4 flex items-center gap-3 rounded-xl bg-semantic-success-bg px-5 py-4">
                <CheckCircle2 size={20} className="shrink-0 text-semantic-success" />
                <p className="text-sm font-medium text-semantic-success">
                  {t(
                    'validation.all_passed',
                    'All validation rules passed successfully!',
                  )}
                </p>
              </div>
            )}

            {/* Results list */}
            <div className="space-y-2">
              {filteredResults.length === 0 && (
                <p className="py-8 text-center text-sm text-content-tertiary">
                  {t('validation.no_results_for_filter', 'No results match this filter.')}
                </p>
              )}
              {filteredResults.map((result, idx) => (
                <ResultRow
                  key={`${result.rule_id}-${idx}`}
                  result={result}
                  expanded={expandedResults.has(idx)}
                  onToggle={() => toggleResult(idx)}
                  boqId={selectedBoqId || undefined}
                  onNavigateToPosition={(bId, posId) => navigate(`/boq/${bId}?highlight=${posId}`)}
                />
              ))}
            </div>
          </div>

          {/* Action buttons */}
          <div className="flex items-center gap-3 border-t border-border-light pt-6">
            <Button
              variant="secondary"
              size="md"
              icon={<Download size={16} />}
              onClick={handleExportPdf}
            >
              {t('validation.export_pdf', 'Export Report PDF')}
            </Button>
            {(report.counts.warnings > 0 || report.counts.errors > 0) && (
              <Button
                variant="ghost"
                size="md"
                icon={<Wand2 size={16} />}
                onClick={() => setFilter('warnings')}
              >
                {t('validation.show_issues', 'Show All Issues')}
              </Button>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
