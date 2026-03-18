import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  ShieldCheck,
  ChevronRight,
  ChevronDown,
  Play,
  AlertTriangle,
  CheckCircle2,
  XCircle,
  Info,
  ArrowLeft,
} from 'lucide-react';
import { Button, Card, Badge, EmptyState, Skeleton } from '@/shared/ui';
import { apiGet, apiPost } from '@/shared/lib/api';

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

interface ValidationResult {
  rule_id: string;
  status: 'pass' | 'warning' | 'error';
  message: string;
  element_ref: string;
  details: Record<string, unknown>;
}

interface ValidationReport {
  id: string;
  project_id: string;
  target_type: string;
  target_id: string;
  rule_set: string;
  status: 'passed' | 'warnings' | 'errors';
  score: number;
  results: ValidationResult[];
  created_at: string;
}

/* ── Sub-components ────────────────────────────────────────────────────── */

function TrafficLight({ status }: { status: 'passed' | 'warnings' | 'errors' }) {
  const colorMap = {
    passed: 'bg-semantic-success shadow-[0_0_24px_rgba(34,197,94,0.3)]',
    warnings: 'bg-semantic-warning shadow-[0_0_24px_rgba(234,179,8,0.3)]',
    errors: 'bg-semantic-error shadow-[0_0_24px_rgba(239,68,68,0.3)]',
  };

  return (
    <div className="flex items-center justify-center">
      <div className={`h-16 w-16 rounded-full ${colorMap[status]} transition-all duration-300`} />
    </div>
  );
}

function ScoreDisplay({ score }: { score: number }) {
  const pct = Math.round(score * 100);

  const colorClass =
    pct >= 80 ? 'text-[#15803d]' : pct >= 50 ? 'text-[#b45309]' : 'text-semantic-error';

  return (
    <div className="text-center">
      <span className={`text-4xl font-bold tabular-nums ${colorClass}`}>{pct}</span>
      <span className={`text-lg font-medium ${colorClass}`}>%</span>
    </div>
  );
}

function ResultCounters({ results }: { results: ValidationResult[] }) {
  const { t } = useTranslation();
  const passed = results.filter((r) => r.status === 'pass').length;
  const warnings = results.filter((r) => r.status === 'warning').length;
  const errors = results.filter((r) => r.status === 'error').length;

  return (
    <div className="flex items-center justify-center gap-6">
      <div className="flex items-center gap-2">
        <CheckCircle2 size={16} className="text-semantic-success" />
        <span className="text-sm font-medium text-content-primary">{passed}</span>
        <span className="text-sm text-content-secondary">{t('validation.passed')}</span>
      </div>
      <div className="flex items-center gap-2">
        <AlertTriangle size={16} className="text-semantic-warning" />
        <span className="text-sm font-medium text-content-primary">{warnings}</span>
        <span className="text-sm text-content-secondary">{t('validation.warnings')}</span>
      </div>
      <div className="flex items-center gap-2">
        <XCircle size={16} className="text-semantic-error" />
        <span className="text-sm font-medium text-content-primary">{errors}</span>
        <span className="text-sm text-content-secondary">{t('validation.errors')}</span>
      </div>
    </div>
  );
}

function ResultsList({ results }: { results: ValidationResult[] }) {
  const { t } = useTranslation();
  const issues = results.filter((r) => r.status !== 'pass');

  if (issues.length === 0) {
    return (
      <div className="flex items-center gap-3 rounded-xl bg-semantic-success-bg px-5 py-4">
        <CheckCircle2 size={20} className="shrink-0 text-semantic-success" />
        <p className="text-sm font-medium text-[#15803d]">
          {t('validation.all_passed', 'All validation rules passed successfully')}
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {issues.map((result, idx) => {
        const isError = result.status === 'error';
        return (
          <div
            key={`${result.rule_id}-${idx}`}
            className="flex items-start gap-3 rounded-xl border border-border-light bg-surface-primary px-4 py-3 transition-colors hover:bg-surface-secondary/50"
          >
            {isError ? (
              <XCircle size={16} className="mt-0.5 shrink-0 text-semantic-error" />
            ) : (
              <AlertTriangle size={16} className="mt-0.5 shrink-0 text-semantic-warning" />
            )}
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2">
                <Badge variant={isError ? 'error' : 'warning'} size="sm">
                  {isError
                    ? t('validation.errors', 'Error')
                    : t('validation.warnings', 'Warning')}
                </Badge>
                <span className="truncate text-xs font-mono text-content-tertiary">
                  {result.rule_id}
                </span>
              </div>
              <p className="mt-1 text-sm text-content-primary">{result.message}</p>
              {result.element_ref && (
                <p className="mt-1 flex items-center gap-1.5 text-xs text-content-secondary">
                  <Info size={12} />
                  {t('validation.position', 'Position')}: {result.element_ref}
                </p>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}

/* ── BOQ Validation Card ───────────────────────────────────────────────── */

function BOQValidationCard({ boq }: { boq: BOQ }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [expanded, setExpanded] = useState(false);

  const {
    data: report,
    isLoading: reportLoading,
  } = useQuery({
    queryKey: ['validation', boq.id],
    queryFn: () => apiGet<ValidationReport>(`/v1/boq/boqs/${boq.id}/validation`),
    enabled: expanded,
    retry: false,
  });

  const runValidation = useMutation({
    mutationFn: () => apiPost<ValidationReport>(`/v1/boq/boqs/${boq.id}/validate`),
    onSuccess: (result) => {
      queryClient.setQueryData(['validation', boq.id], result);
      setExpanded(true);
    },
  });

  return (
    <Card padding="none" className="overflow-hidden">
      {/* BOQ Header Row */}
      <div className="flex items-center gap-3 px-5 py-4">
        <button
          onClick={() => setExpanded((prev) => !prev)}
          className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-content-tertiary transition-colors hover:bg-surface-secondary hover:text-content-primary"
        >
          {expanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
        </button>

        <div className="min-w-0 flex-1">
          <h3 className="text-sm font-semibold text-content-primary truncate">{boq.name}</h3>
          {boq.description && (
            <p className="mt-0.5 text-xs text-content-secondary truncate">{boq.description}</p>
          )}
        </div>

        <Badge variant={boq.status === 'final' ? 'success' : 'blue'} size="sm">
          {boq.status}
        </Badge>

        <Button
          variant="secondary"
          size="sm"
          icon={<Play size={14} />}
          loading={runValidation.isPending}
          onClick={() => runValidation.mutate()}
        >
          {t('validation.run', 'Run Validation')}
        </Button>
      </div>

      {/* Expanded Validation Report */}
      {expanded && (
        <div className="border-t border-border-light bg-surface-secondary/30 px-5 py-6">
          {reportLoading ? (
            <div className="space-y-4">
              <div className="flex items-center justify-center gap-6">
                <Skeleton width={64} height={64} rounded="full" />
                <Skeleton width={100} height={48} />
              </div>
              <Skeleton height={14} className="w-2/3 mx-auto" />
              <Skeleton height={14} className="w-1/2 mx-auto" />
            </div>
          ) : report ? (
            <div className="space-y-6">
              {/* Traffic Light + Score */}
              <div className="flex items-center justify-center gap-8">
                <TrafficLight status={report.status} />
                <div>
                  <ScoreDisplay score={report.score} />
                  <p className="mt-1 text-center text-xs text-content-tertiary">
                    {t('validation.score')}
                  </p>
                </div>
              </div>

              {/* Counters */}
              <ResultCounters results={report.results} />

              {/* Rule set info */}
              <div className="flex items-center justify-center gap-2">
                <span className="text-xs text-content-tertiary">
                  {t('validation.rule_set', 'Rule set')}:
                </span>
                <Badge variant="neutral" size="sm">
                  {report.rule_set}
                </Badge>
                <span className="text-xs text-content-tertiary">
                  {new Date(report.created_at).toLocaleString()}
                </span>
              </div>

              {/* Results List */}
              <ResultsList results={report.results} />
            </div>
          ) : (
            <div className="py-6 text-center">
              <p className="text-sm text-content-secondary">
                {t(
                  'validation.no_report',
                  'No validation report yet. Click "Run Validation" to check this BOQ.',
                )}
              </p>
            </div>
          )}
        </div>
      )}
    </Card>
  );
}

/* ── Main Page ─────────────────────────────────────────────────────────── */

export function ValidationPage() {
  const { t } = useTranslation();
  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(null);

  const { data: projects, isLoading } = useQuery({
    queryKey: ['projects'],
    queryFn: () => apiGet<Project[]>('/v1/projects/'),
  });

  const selectedProject = selectedProjectId
    ? projects?.find((p) => p.id === selectedProjectId)
    : null;

  // Single-project detail view
  if (selectedProject) {
    return (
      <div className="max-w-content mx-auto animate-fade-in">
        <button
          onClick={() => setSelectedProjectId(null)}
          className="mb-4 flex items-center gap-1.5 text-sm text-content-secondary hover:text-content-primary transition-colors"
        >
          <ArrowLeft size={14} />
          {t('validation.back_to_projects', 'Back to projects')}
        </button>

        <div className="mb-6">
          <h1 className="text-2xl font-bold text-content-primary">{selectedProject.name}</h1>
          <p className="mt-1 text-sm text-content-secondary">
            {t('validation.project_validation', 'Validation dashboard for this project')}
          </p>
        </div>

        <ProjectAccordionExpanded project={selectedProject} />
      </div>
    );
  }

  // Project list view
  return (
    <div className="max-w-content mx-auto animate-fade-in">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-content-primary">{t('validation.title')}</h1>
        <p className="mt-1 text-sm text-content-secondary">
          {t(
            'validation.subtitle',
            'Select a project to validate its BOQs against configured rule sets',
          )}
        </p>
      </div>

      {isLoading ? (
        <div className="space-y-4">
          {[1, 2, 3].map((i) => (
            <Skeleton key={i} height={72} className="w-full" rounded="lg" />
          ))}
        </div>
      ) : !projects || projects.length === 0 ? (
        <EmptyState
          icon={<ShieldCheck size={24} strokeWidth={1.5} />}
          title={t('validation.no_projects', 'No projects to validate')}
          description={t(
            'validation.no_projects_hint',
            'Create a project and add BOQ positions first',
          )}
        />
      ) : (
        <div className="space-y-3">
          {projects.map((project) => (
            <Card
              key={project.id}
              hoverable
              padding="none"
              className="cursor-pointer"
              onClick={() => setSelectedProjectId(project.id)}
            >
              <div className="flex items-center gap-3 px-5 py-4">
                <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-oe-blue-subtle text-oe-blue font-bold">
                  {project.name.charAt(0).toUpperCase()}
                </div>
                <div className="min-w-0 flex-1">
                  <h2 className="text-sm font-semibold text-content-primary truncate">
                    {project.name}
                  </h2>
                  {project.description && (
                    <p className="mt-0.5 text-xs text-content-secondary truncate">
                      {project.description}
                    </p>
                  )}
                </div>
                <Badge variant="blue" size="sm">
                  {project.classification_standard}
                </Badge>
                <ChevronRight size={16} className="shrink-0 text-content-tertiary" />
              </div>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}

/* ── Expanded Project (used in detail view) ────────────────────────────── */

function ProjectAccordionExpanded({ project }: { project: Project }) {
  const { t } = useTranslation();

  const { data: boqs, isLoading: boqsLoading } = useQuery({
    queryKey: ['boqs', project.id],
    queryFn: () => apiGet<BOQ[]>(`/v1/boq/boqs/?project_id=${project.id}`),
  });

  if (boqsLoading) {
    return (
      <div className="space-y-3">
        {[1, 2].map((i) => (
          <Skeleton key={i} height={64} className="w-full" rounded="lg" />
        ))}
      </div>
    );
  }

  if (!boqs || boqs.length === 0) {
    return (
      <EmptyState
        icon={<ShieldCheck size={24} strokeWidth={1.5} />}
        title={t('validation.no_boqs', 'No BOQs in this project')}
        description={t(
          'validation.no_boqs_hint',
          'Add BOQ positions to run validation checks',
        )}
      />
    );
  }

  return (
    <div className="space-y-3">
      {boqs.map((boq) => (
        <BOQValidationCard key={boq.id} boq={boq} />
      ))}
    </div>
  );
}
