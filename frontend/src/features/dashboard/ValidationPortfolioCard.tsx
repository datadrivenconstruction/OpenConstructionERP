// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * ValidationPortfolioCard - the latest validation status of every estimate
 * in every project the reader can open, worst first.
 *
 * Validation results used to be visible only inside each BOQ editor, so a
 * head of estimating had to open every estimate to find the failing ones.
 * This card answers "where do I look first" in one read: each project shows
 * its worst estimate state, the error and warning counts of the latest
 * reports, which rule sets ran and when, and every estimate links straight to
 * its report on the validation page.
 *
 * It deliberately answers for the whole workspace, not the project picked in
 * the top bar: a cross-project view scoped to one project would be the BOQ
 * editor's own panel again. The selected project is marked instead.
 *
 * An estimate nobody validated reads "Not validated", never "Passed". The
 * backend decides that and the order; this component only renders it.
 *
 * Unlike the delivery cards this one never self-hides: loading, error and
 * empty each render their own state, so a failed read cannot pass for an
 * empty workspace.
 */

import { useState } from 'react';
import type { ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import clsx from 'clsx';
import { ArrowRight, ChevronDown, ChevronUp } from 'lucide-react';
import { Card, CardContent, CardHeader, ErrorState, InfoHint, Skeleton } from '@/shared/ui';
import { fmtDate } from '@/shared/lib/formatters';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { getNumberLocale } from '@/stores/usePreferencesStore';
import { ruleSetLabel } from '@/features/validation/ruleSetLabels';
import { KpiStrip } from './KpiStrip';
import {
  VALIDATION_PORTFOLIO_QUERY_KEY,
  estimateValidationHref,
  fetchValidationPortfolio,
  projectEstimatesHref,
  ranButCheckedNothing,
  type PortfolioEstimate,
  type PortfolioProject,
  type PortfolioState,
} from './validationPortfolio';

/** Estimates shown per project before "Show all". */
const ESTIMATES_PREVIEW = 3;

const STATE_TONE: Record<PortfolioState, { pill: string; dot: string }> = {
  errors: {
    pill: 'bg-rose-50 text-rose-700 ring-rose-200 dark:bg-rose-950/40 dark:text-rose-300 dark:ring-rose-900',
    dot: 'bg-rose-500',
  },
  warnings: {
    pill: 'bg-amber-50 text-amber-700 ring-amber-200 dark:bg-amber-950/40 dark:text-amber-300 dark:ring-amber-900',
    dot: 'bg-amber-500',
  },
  not_validated: {
    pill: 'bg-surface-secondary text-content-secondary ring-border-light',
    dot: 'bg-content-quaternary',
  },
  info: {
    pill: 'bg-sky-50 text-sky-700 ring-sky-200 dark:bg-sky-950/40 dark:text-sky-300 dark:ring-sky-900',
    dot: 'bg-sky-500',
  },
  passed: {
    pill: 'bg-emerald-50 text-emerald-700 ring-emerald-200 dark:bg-emerald-950/40 dark:text-emerald-300 dark:ring-emerald-900',
    dot: 'bg-emerald-500',
  },
};

/** A state this build does not know (a newer server) reads as not validated, never as a pass. */
function toneFor(state: PortfolioState): { pill: string; dot: string } {
  return (STATE_TONE as Partial<Record<string, { pill: string; dot: string }>>)[state] ?? STATE_TONE.not_validated;
}

function formatCount(value: number): string {
  // Read on each call: the header language switcher does not reload the chunk.
  return value.toLocaleString(getNumberLocale(), { maximumFractionDigits: 0 });
}

type T = ReturnType<typeof useTranslation>['t'];

function stateLabel(state: PortfolioState, t: T): string {
  switch (state) {
    case 'errors':
      return t('dashboard.validation_portfolio.state_errors', { defaultValue: 'Errors' });
    case 'warnings':
      return t('dashboard.validation_portfolio.state_warnings', { defaultValue: 'Warnings' });
    case 'info':
      return t('dashboard.validation_portfolio.state_info', { defaultValue: 'Notes only' });
    case 'passed':
      return t('dashboard.validation_portfolio.state_passed', { defaultValue: 'Passed' });
    default:
      return t('dashboard.validation_portfolio.state_not_validated', { defaultValue: 'Not validated' });
  }
}

function StatePill({ state }: { state: PortfolioState }) {
  const { t } = useTranslation();
  return (
    <span
      className={clsx(
        'inline-flex shrink-0 items-center gap-1.5 rounded-full px-2 py-0.5 text-2xs font-semibold ring-1 ring-inset',
        toneFor(state).pill,
      )}
      data-state={state}
    >
      <span aria-hidden="true" className={clsx('h-1.5 w-1.5 rounded-full', toneFor(state).dot)} />
      {stateLabel(state, t)}
    </span>
  );
}

/** "2 errors · 5 warnings", or nothing when both are zero. */
function findingCounts(errors: number, warnings: number, t: T): string {
  const parts: string[] = [];
  if (errors > 0) {
    parts.push(
      t('dashboard.validation_portfolio.errors_count', {
        count: errors,
        defaultValue: '{{count}} error',
        defaultValue_one: '{{count}} error',
        defaultValue_other: '{{count}} errors',
      }),
    );
  }
  if (warnings > 0) {
    parts.push(
      t('dashboard.validation_portfolio.warnings_count', {
        count: warnings,
        defaultValue: '{{count}} warning',
        defaultValue_one: '{{count}} warning',
        defaultValue_other: '{{count}} warnings',
      }),
    );
  }
  return parts.join(' · ');
}

function EstimateRow({ projectId, estimate }: { projectId: string; estimate: PortfolioEstimate }) {
  const { t } = useTranslation();
  const counts = findingCounts(estimate.error_count, estimate.warning_count, t);
  const ruleSets = estimate.rule_sets.map((rs) => ruleSetLabel(rs, t)).join(' · ');
  let detail: string;
  if (estimate.report_id === null) {
    // "No report on record", not "never validated": a check run by someone
    // who may not create validation reports is not stored, and neither was
    // any run from the BOQ editor before it started storing them.
    detail = t('dashboard.validation_portfolio.no_report', { defaultValue: 'No validation report on record' });
  } else if (ranButCheckedNothing(estimate)) {
    detail = t('dashboard.validation_portfolio.checked_nothing', {
      defaultValue: 'Last run checked no rules',
    });
  } else {
    detail = counts || t('dashboard.validation_portfolio.no_findings', { defaultValue: 'No findings' });
  }

  return (
    <li>
      <Link
        to={estimateValidationHref(projectId, estimate)}
        className="group flex items-center gap-2 rounded-md px-2 py-1.5 text-xs hover:bg-surface-secondary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/40"
        aria-label={t('dashboard.validation_portfolio.open_estimate', {
          name: estimate.boq_name,
          defaultValue: 'Open the validation of {{name}}',
        })}
      >
        <span
          aria-hidden="true"
          className={clsx('h-2 w-2 shrink-0 rounded-full', toneFor(estimate.state).dot)}
        />
        <span className="min-w-0 flex-1">
          <span className="block truncate font-medium text-content-primary">{estimate.boq_name}</span>
          <span className="block truncate text-content-tertiary">
            {stateLabel(estimate.state, t)} · {detail}
            {ruleSets ? ` · ${ruleSets}` : ''}
          </span>
        </span>
        {estimate.validated_at && (
          <span className="hidden shrink-0 tabular-nums text-content-tertiary sm:inline">
            {fmtDate(estimate.validated_at)}
          </span>
        )}
        <ArrowRight
          size={12}
          aria-hidden="true"
          className="shrink-0 text-content-quaternary group-hover:text-oe-blue"
        />
      </Link>
    </li>
  );
}

function ProjectBlock({ project, isActive }: { project: PortfolioProject; isActive: boolean }) {
  const { t } = useTranslation();
  const [expanded, setExpanded] = useState(false);
  const counts = findingCounts(project.error_count, project.warning_count, t);
  const shown = expanded ? project.estimates : project.estimates.slice(0, ESTIMATES_PREVIEW);

  return (
    <li
      className={clsx(
        'rounded-lg border px-3 py-2.5',
        isActive ? 'border-oe-blue/40 bg-oe-blue/5' : 'border-border-light',
      )}
      data-testid="validation-portfolio-project"
      data-project-id={project.project_id}
    >
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <StatePill state={project.state} />
        <span className="min-w-0 flex-1 truncate text-sm font-semibold text-content-primary">
          {project.project_name}
        </span>
        {isActive && (
          <span className="shrink-0 text-2xs font-medium text-oe-blue">
            {t('dashboard.validation_portfolio.selected', { defaultValue: 'Selected project' })}
          </span>
        )}
      </div>
      <p className="mt-1 text-xs text-content-tertiary">
        {project.estimate_count === 0
          ? t('dashboard.validation_portfolio.no_estimates', { defaultValue: 'No estimates yet' })
          : t('dashboard.validation_portfolio.validated_of', {
              // The plural follows the raw total; the shown numbers are
              // formatted in the reader's locale.
              count: project.estimate_count,
              validated: formatCount(project.validated_count),
              total: formatCount(project.estimate_count),
              defaultValue: '{{validated}} of {{total}} estimate validated',
              defaultValue_one: '{{validated}} of {{total}} estimate validated',
              defaultValue_other: '{{validated}} of {{total}} estimates validated',
            })}
        {counts ? ` · ${counts}` : ''}
        {project.last_validated_at
          ? ` · ${t('dashboard.validation_portfolio.last_checked', {
              date: fmtDate(project.last_validated_at),
              defaultValue: 'last checked {{date}}',
            })}`
          : ''}
      </p>

      {project.estimate_count === 0 ? (
        <Link
          to={projectEstimatesHref(project.project_id)}
          className="mt-1.5 inline-flex items-center gap-1 text-xs font-medium text-oe-blue hover:underline"
        >
          {t('dashboard.validation_portfolio.open_estimates', { defaultValue: 'Open estimates' })}
          <ArrowRight size={12} aria-hidden="true" />
        </Link>
      ) : (
        <ul className="mt-1.5 space-y-0.5">
          {shown.map((estimate) => (
            <EstimateRow key={estimate.boq_id} projectId={project.project_id} estimate={estimate} />
          ))}
        </ul>
      )}

      {project.estimates.length > ESTIMATES_PREVIEW && (
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          aria-expanded={expanded}
          className="mt-1 inline-flex items-center gap-1 px-2 text-xs font-medium text-oe-blue hover:underline"
        >
          {expanded ? (
            <>
              {t('dashboard.validation_portfolio.show_fewer', { defaultValue: 'Show fewer' })}
              <ChevronUp size={12} aria-hidden="true" />
            </>
          ) : (
            <>
              {t('dashboard.validation_portfolio.show_all', {
                count: project.estimates.length,
                defaultValue: 'Show {{count}} estimate',
                defaultValue_one: 'Show {{count}} estimate',
                defaultValue_other: 'Show all {{count}} estimates',
              })}
              <ChevronDown size={12} aria-hidden="true" />
            </>
          )}
        </button>
      )}
    </li>
  );
}

function LoadingRows() {
  return (
    <div className="space-y-2" aria-busy="true" data-testid="validation-portfolio-loading">
      <Skeleton height={56} />
      <Skeleton height={48} />
      <Skeleton height={48} />
    </div>
  );
}

export function ValidationPortfolioCard() {
  const { t } = useTranslation();
  const activeProjectId = useProjectContextStore((s) => s.activeProjectId);
  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: VALIDATION_PORTFOLIO_QUERY_KEY,
    queryFn: fetchValidationPortfolio,
    staleTime: 60 * 1000,
  });

  const projects = data && Array.isArray(data.projects) ? data.projects : null;
  const summary = data?.summary;

  let body: ReactNode;
  if (isError) {
    body = (
      <ErrorState
        compact
        title={t('dashboard.validation_portfolio.error', {
          defaultValue: 'Validation status could not be loaded.',
        })}
        hint={t('dashboard.validation_portfolio.error_hint', {
          defaultValue: 'This is not the same as no reports. Try again in a moment.',
        })}
        onRetry={() => void refetch()}
      />
    );
  } else if (isLoading || projects === null) {
    body = <LoadingRows />;
  } else if (projects.length === 0) {
    body = (
      <p className="rounded-lg border border-dashed border-border-light px-3 py-4 text-center text-sm text-content-secondary">
        {t('dashboard.validation_portfolio.empty', {
          defaultValue:
            'No projects to show yet. Once a project has an estimate, its validation status appears here.',
        })}
      </p>
    );
  } else {
    body = (
      <>
        {summary && (
          <KpiStrip
            className="mb-3"
            stats={[
              {
                label: t('dashboard.validation_portfolio.kpi_errors', { defaultValue: 'Projects with errors' }),
                value: formatCount(summary.errors),
                tone: summary.errors > 0 ? 'text-rose-600' : 'text-content-secondary',
              },
              {
                label: t('dashboard.validation_portfolio.kpi_warnings', {
                  defaultValue: 'Projects with warnings',
                }),
                value: formatCount(summary.warnings),
                tone: summary.warnings > 0 ? 'text-amber-600' : 'text-content-secondary',
              },
              {
                label: t('dashboard.validation_portfolio.kpi_not_validated', {
                  defaultValue: 'Not fully validated',
                }),
                value: formatCount(summary.not_validated),
                tone: 'text-content-secondary',
              },
              {
                label: t('dashboard.validation_portfolio.kpi_clean', {
                  defaultValue: 'No errors or warnings',
                }),
                value: formatCount(summary.passed + summary.info),
                tone: 'text-emerald-600',
              },
            ]}
          />
        )}
        <ul className="max-h-[28rem] space-y-2 overflow-y-auto pr-1" data-testid="validation-portfolio-list">
          {projects.map((project) => (
            <ProjectBlock
              key={project.project_id}
              project={project}
              isActive={project.project_id === activeProjectId}
            />
          ))}
        </ul>
      </>
    );
  }

  return (
    <Card className="h-full">
      <CardHeader
        title={t('dashboard.validation_portfolio.title', { defaultValue: 'Validation across projects' })}
        subtitle={t('dashboard.validation_portfolio.subtitle', {
          defaultValue: 'Latest check of every estimate in all your projects, worst first',
        })}
        action={
          <Link to="/validation" className="text-xs text-oe-blue hover:underline">
            {t('dashboard.validation_portfolio.open_validation', { defaultValue: 'Open validation' })}
          </Link>
        }
      />
      <CardContent>
        {body}
        <InfoHint
          className="mt-3"
          text={t('dashboard.validation_portfolio.help', {
            defaultValue:
              'Each estimate shows the verdict of its stored validation reports; nothing is re-run here. A narrower check, such as the one-click estimate audit, does not clear findings from rule sets it did not run again, so those stay until a run of the same scope clears them. Checks from the BOQ editor are stored when you may create validation reports. A project takes the state of its worst estimate, so one unchecked estimate keeps a project at "Not validated" even if the others passed. This card covers every project you can open, not only the one selected at the top.',
          })}
        />
      </CardContent>
    </Card>
  );
}

export default ValidationPortfolioCard;
