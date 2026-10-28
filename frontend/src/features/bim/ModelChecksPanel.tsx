// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * ModelChecksPanel - surfaces the automated model-checking engine on the Model
 * Review page.
 *
 * The rule engine already lives on the backend; this panel is the first place
 * a reviewer can actually run it. "Run checks" calls
 * POST /validation/check-bim-model for the active model and renders:
 *
 *   - a traffic-light summary (passed / warnings / errors / info counts + an
 *     overall status and quality score),
 *   - the maturity scorecard facets from GET /validation/bim-scorecard/{id},
 *   - a findings list grouped by severity (errors first). Each finding can be
 *     focused in the 3D viewer (reusing the page's selection mechanism) and
 *     turned into a tracked BCF issue via the exact same capture flow the
 *     Issues dock uses (`useBcfCapture`), pre-filled from the finding.
 *
 * The panel owns no viewer internals: focusing an element goes through the
 * `onFocusElement` callback the page provides, and the capture bridge is
 * injected, so this component stays decoupled from the 3D scene.
 */

import { useMemo } from 'react';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import {
  AlertTriangle,
  CheckCircle2,
  Crosshair,
  Gauge,
  Info,
  ListChecks,
  Lock,
  Play,
  Plus,
  XCircle,
} from 'lucide-react';
import clsx from 'clsx';

import { Badge, Button, Card, EmptyState, SkeletonText } from '@/shared/ui';
import { ApiError } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import { useBcfCapture, type BcfViewerBridge } from '@/features/bcf';

import {
  checkBimModel,
  fetchBimScorecard,
  type BIMCheckReport,
  type BIMCheckResultItem,
  type BIMScorecardFacet,
} from './modelChecksApi';

/* ── Severity + grade presentation helpers ─────────────────────────────── */

type Severity = 'error' | 'warning' | 'info';

/** Normalise any backend severity/status string to the UI severity union. */
function toSeverity(value: string | undefined): Severity {
  if (value === 'error') return 'error';
  if (value === 'info') return 'info';
  return 'warning';
}

const SEVERITY_ORDER: Record<Severity, number> = { error: 0, warning: 1, info: 2 };

/** Map an overall report status to a Badge variant + human label. */
function statusMeta(
  status: string,
  t: (key: string, opts?: Record<string, unknown>) => string,
): { variant: 'success' | 'warning' | 'error' | 'neutral'; label: string } {
  switch (status) {
    case 'passed':
      return { variant: 'success', label: t('bim.checks_status_passed', { defaultValue: 'Passed' }) };
    case 'errors':
      return { variant: 'error', label: t('bim.checks_status_errors', { defaultValue: 'Errors' }) };
    case 'warnings':
      return { variant: 'warning', label: t('bim.checks_status_warnings', { defaultValue: 'Warnings' }) };
    case 'info':
      return { variant: 'warning', label: t('bim.checks_status_info', { defaultValue: 'Info' }) };
    default:
      return { variant: 'neutral', label: t('bim.checks_status_skipped', { defaultValue: 'Not checked' }) };
  }
}

/** Letter grade -> Badge variant (A/B green, C amber, D/F red, else neutral). */
function gradeVariant(grade: string): 'success' | 'warning' | 'error' | 'neutral' {
  const g = grade.trim().toUpperCase();
  if (g === 'A' || g === 'B') return 'success';
  if (g === 'C') return 'warning';
  if (g === 'D' || g === 'F') return 'error';
  return 'neutral';
}

/** Parse a decimal-string / number score to a whole percent, or null. */
function toPercent(value: string | number | null | undefined): number | null {
  if (value === null || value === undefined || value === '') return null;
  const n = Number(value);
  return Number.isFinite(n) ? Math.round(n * 100) : null;
}

/** True for the synthetic "results truncated" sentinel row. */
function isTruncationRow(r: BIMCheckResultItem): boolean {
  return r.rule_id === '_truncated';
}

/* ── Traffic-light summary ─────────────────────────────────────────────── */

function CheckSummary({ report }: { report: BIMCheckReport }) {
  const { t } = useTranslation();
  const meta = statusMeta(report.status, t);
  const scorePct = toPercent(report.score);
  const infoCount = report.metadata?.info_count ?? 0;

  const stats: { key: string; icon: typeof CheckCircle2; color: string; label: string; value: number }[] = [
    {
      key: 'passed',
      icon: CheckCircle2,
      color: 'text-semantic-success',
      label: t('bim.checks_passed', { defaultValue: 'Passed' }),
      value: report.passed_count,
    },
    {
      key: 'errors',
      icon: XCircle,
      color: 'text-semantic-error',
      label: t('bim.checks_errors', { defaultValue: 'Errors' }),
      value: report.error_count,
    },
    {
      key: 'warnings',
      icon: AlertTriangle,
      color: 'text-semantic-warning',
      label: t('bim.checks_warnings', { defaultValue: 'Warnings' }),
      value: report.warning_count,
    },
    {
      key: 'info',
      icon: Info,
      color: 'text-oe-blue',
      label: t('bim.checks_info', { defaultValue: 'Info' }),
      value: infoCount,
    },
  ];

  return (
    <Card padding="sm">
      <div className="mb-3 flex items-center justify-between gap-2">
        <span className="text-xs font-semibold uppercase tracking-wider text-content-tertiary">
          {t('bim.checks_summary', { defaultValue: 'Check summary' })}
        </span>
        <Badge variant={meta.variant} size="sm" dot>
          {meta.label}
        </Badge>
      </div>

      <div className="grid grid-cols-2 gap-2">
        {stats.map((s) => (
          <div
            key={s.key}
            className="flex items-center gap-2 rounded-lg border border-border-light bg-surface-primary px-2.5 py-2"
          >
            <s.icon size={15} className={clsx('shrink-0', s.color)} />
            <span className="text-xs text-content-secondary">{s.label}</span>
            <span className={clsx('ms-auto text-sm font-semibold tabular-nums', s.color)}>{s.value}</span>
          </div>
        ))}
      </div>

      <div className="mt-3 flex items-center justify-between border-t border-border-light pt-2.5 text-xs text-content-tertiary">
        <span>
          {t('bim.checks_total', {
            defaultValue: '{{count}} checks run',
            count: report.total_rules,
          })}
        </span>
        {scorePct !== null && (
          <span className="font-medium text-content-secondary tabular-nums">
            {t('bim.checks_score', { defaultValue: 'Score' })}: {scorePct}%
          </span>
        )}
      </div>
    </Card>
  );
}

/* ── Maturity scorecard ────────────────────────────────────────────────── */

function FacetRow({ facet }: { facet: BIMScorecardFacet }) {
  const { t } = useTranslation();
  const pct = toPercent(facet.score);
  return (
    <div className="flex items-start gap-2 py-2">
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-1.5">
          <span className="truncate text-xs font-medium text-content-primary">{facet.name}</span>
          {facet.applicable ? (
            <Badge variant={gradeVariant(facet.grade)} size="sm">
              {facet.grade}
              {pct !== null && <span className="ms-1 font-normal tabular-nums">{pct}%</span>}
            </Badge>
          ) : (
            <Badge variant="neutral" size="sm">
              {t('bim.checks_facet_na', { defaultValue: 'N/A' })}
            </Badge>
          )}
        </div>
        <p className="mt-0.5 text-2xs leading-relaxed text-content-tertiary">{facet.summary}</p>
      </div>
    </div>
  );
}

function ScorecardCard({
  facets,
  overallGrade,
  overallScore,
  trendDirection,
  trendDelta,
}: {
  facets: BIMScorecardFacet[];
  overallGrade: string;
  overallScore: number | null;
  trendDirection?: string;
  trendDelta?: number | null;
}) {
  const { t } = useTranslation();
  const pct = toPercent(overallScore);

  const trendLabel = useMemo(() => {
    if (!trendDirection || trendDirection === 'insufficient') return null;
    const deltaPts = trendDelta != null ? Math.round(trendDelta * 100) : null;
    const sign = deltaPts != null && deltaPts > 0 ? '+' : '';
    switch (trendDirection) {
      case 'improving':
        return t('bim.checks_trend_improving', {
          defaultValue: 'Improving ({{delta}} pts vs first run)',
          delta: `${sign}${deltaPts ?? 0}`,
        });
      case 'regressing':
        return t('bim.checks_trend_regressing', {
          defaultValue: 'Regressing ({{delta}} pts vs first run)',
          delta: `${sign}${deltaPts ?? 0}`,
        });
      default:
        return t('bim.checks_trend_flat', { defaultValue: 'Steady vs first run' });
    }
  }, [trendDirection, trendDelta, t]);

  return (
    <Card padding="sm">
      <div className="mb-2 flex items-center justify-between gap-2">
        <span className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wider text-content-tertiary">
          <Gauge size={13} className="text-content-tertiary" />
          {t('bim.checks_scorecard', { defaultValue: 'Model maturity' })}
        </span>
        <span className="flex items-center gap-1.5">
          {pct !== null && (
            <span className="text-xs font-medium text-content-secondary tabular-nums">{pct}%</span>
          )}
          <Badge variant={gradeVariant(overallGrade)} size="sm">
            {overallGrade}
          </Badge>
        </span>
      </div>

      <div className="divide-y divide-border-light">
        {facets.map((f) => (
          <FacetRow key={f.facet_id} facet={f} />
        ))}
      </div>

      {trendLabel && (
        <p className="mt-2 border-t border-border-light pt-2 text-2xs text-content-tertiary">{trendLabel}</p>
      )}
    </Card>
  );
}

/* ── Finding row ───────────────────────────────────────────────────────── */

function severityIcon(sev: Severity) {
  if (sev === 'error') return <XCircle size={15} className="mt-0.5 shrink-0 text-semantic-error" />;
  if (sev === 'info') return <Info size={15} className="mt-0.5 shrink-0 text-oe-blue" />;
  return <AlertTriangle size={15} className="mt-0.5 shrink-0 text-semantic-warning" />;
}

function FindingRow({
  finding,
  canFocus,
  onFocus,
  onCreateIssue,
  creating,
}: {
  finding: BIMCheckResultItem;
  canFocus: boolean;
  onFocus: () => void;
  onCreateIssue: () => void;
  creating: boolean;
}) {
  const { t } = useTranslation();
  const sev = toSeverity(finding.severity);
  const hasElement = Boolean(finding.element_id);
  const focusable = canFocus && hasElement;

  return (
    <div
      className={clsx(
        'rounded-lg border border-border-light bg-surface-primary transition-colors',
        focusable && 'cursor-pointer hover:bg-surface-secondary/50',
      )}
      role={focusable ? 'button' : undefined}
      tabIndex={focusable ? 0 : undefined}
      onClick={focusable ? onFocus : undefined}
      onKeyDown={
        focusable
          ? (e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                onFocus();
              }
            }
          : undefined
      }
    >
      <div className="flex items-start gap-2 px-3 py-2">
        {severityIcon(sev)}
        <div className="min-w-0 flex-1">
          <p className="text-xs font-medium text-content-primary">{finding.rule_name || finding.rule_id}</p>
          <p className="mt-0.5 text-2xs leading-relaxed text-content-secondary">{finding.message}</p>
          {(finding.element_name || finding.element_id) && (
            <p className="mt-1 truncate font-mono text-2xs text-content-tertiary" title={finding.element_id ?? undefined}>
              {finding.element_name
                ? `${finding.element_name}${finding.element_type ? ` · ${finding.element_type}` : ''}`
                : `${(finding.element_id ?? '').slice(0, 8)}…`}
            </p>
          )}
        </div>
      </div>

      {canFocus && (
        <div className="flex items-center gap-1.5 border-t border-border-light px-3 py-1.5">
          {focusable && (
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                onFocus();
              }}
              className="inline-flex items-center gap-1 rounded-md px-1.5 py-1 text-2xs font-medium text-content-secondary transition-colors hover:bg-oe-blue-subtle/40 hover:text-oe-blue"
              title={t('bim.checks_locate', { defaultValue: 'Show in model' })}
            >
              <Crosshair size={12} />
              {t('bim.checks_locate', { defaultValue: 'Show in model' })}
            </button>
          )}
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              onCreateIssue();
            }}
            disabled={creating}
            className="inline-flex items-center gap-1 rounded-md px-1.5 py-1 text-2xs font-medium text-content-secondary transition-colors hover:bg-oe-blue-subtle/40 hover:text-oe-blue disabled:cursor-not-allowed disabled:opacity-50"
            title={t('bim.checks_create_issue', { defaultValue: 'Create issue' })}
          >
            <Plus size={12} />
            {creating
              ? t('bim.checks_creating_issue', { defaultValue: 'Creating…' })
              : t('bim.checks_create_issue', { defaultValue: 'Create issue' })}
          </button>
        </div>
      )}
    </div>
  );
}

/* ── Findings list (grouped by severity) ───────────────────────────────── */

function FindingsList({
  report,
  canFocus,
  onFocus,
  onCreateIssue,
  creatingFinding,
}: {
  report: BIMCheckReport;
  canFocus: boolean;
  onFocus: (finding: BIMCheckResultItem) => void;
  onCreateIssue: (finding: BIMCheckResultItem) => void;
  /** The finding whose "create issue" is in flight (reference-compared). */
  creatingFinding: BIMCheckResultItem | null;
}) {
  const { t } = useTranslation();

  // Bucket findings by severity, dropping the synthetic truncation sentinel.
  const groups = useMemo(() => {
    const buckets: Record<Severity, BIMCheckResultItem[]> = { error: [], warning: [], info: [] };
    for (const r of report.results) {
      if (isTruncationRow(r)) continue;
      buckets[toSeverity(r.severity)].push(r);
    }
    return buckets;
  }, [report.results]);

  const total = groups.error.length + groups.warning.length + groups.info.length;
  const truncated = report.metadata?.truncated === true || report.results.some(isTruncationRow);

  // Everything passed - a clean bill of health for a model that WAS checked.
  if (total === 0 && report.total_rules > 0) {
    return (
      <div className="flex items-center gap-2 rounded-xl bg-semantic-success-bg px-4 py-3">
        <CheckCircle2 size={18} className="shrink-0 text-semantic-success" />
        <p className="text-xs font-medium text-semantic-success">
          {t('bim.checks_all_passed', { defaultValue: 'Every automated check passed.' })}
        </p>
      </div>
    );
  }

  if (total === 0) return null;

  // Errors first, then warnings, then info - each its own labelled group.
  const sectionDefs: { sev: Severity; label: string }[] = [
    { sev: 'error', label: t('bim.checks_errors', { defaultValue: 'Errors' }) },
    { sev: 'warning', label: t('bim.checks_warnings', { defaultValue: 'Warnings' }) },
    { sev: 'info', label: t('bim.checks_info', { defaultValue: 'Info' }) },
  ];
  const sections = sectionDefs.sort((a, b) => SEVERITY_ORDER[a.sev] - SEVERITY_ORDER[b.sev]);

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <span className="text-xs font-semibold uppercase tracking-wider text-content-tertiary">
          {t('bim.checks_findings', { defaultValue: 'Findings' })}
        </span>
        <span className="text-2xs text-content-tertiary tabular-nums">{total}</span>
      </div>

      {sections.map(({ sev, label }) => {
        const items = groups[sev];
        if (items.length === 0) return null;
        return (
          <div key={sev} className="space-y-2">
            <div className="flex items-center gap-1.5">
              {severityIcon(sev)}
              <span className="text-2xs font-semibold uppercase tracking-wider text-content-tertiary">
                {label}
              </span>
              <span className="text-2xs text-content-quaternary tabular-nums">{items.length}</span>
            </div>
            {items.map((finding, idx) => {
              const key = `${finding.rule_id}::${finding.element_id ?? idx}`;
              return (
                <FindingRow
                  key={key}
                  finding={finding}
                  canFocus={canFocus}
                  onFocus={() => onFocus(finding)}
                  onCreateIssue={() => onCreateIssue(finding)}
                  creating={creatingFinding === finding}
                />
              );
            })}
          </div>
        );
      })}

      {truncated && (
        <p className="px-1 py-1 text-2xs italic text-content-tertiary">
          {t('bim.checks_truncated', {
            defaultValue: 'Only the first findings are shown - narrow the model or re-run to see the rest.',
          })}
        </p>
      )}
    </div>
  );
}

/* ── Panel ─────────────────────────────────────────────────────────────── */

export interface ModelChecksPanelProps {
  projectId: string;
  /** Active model id, or null when none is selected. */
  modelId: string | null;
  /** Stable capture bridge from the page. Its getters tolerate a null scene,
   *  so it is always defined; interaction is gated on `viewerReady`. */
  bridge: BcfViewerBridge;
  /** True once the 3D scene has mounted (focus + capture become meaningful). */
  viewerReady: boolean;
  /** Select (and optionally frame) an element in the viewer by its BIMElement
   *  id. Returns true when the element resolved to a mesh in the loaded model. */
  onFocusElement: (elementId: string, opts?: { zoom?: boolean }) => boolean;
  className?: string;
}

export function ModelChecksPanel({
  projectId,
  modelId,
  bridge,
  viewerReady,
  onFocusElement,
  className,
}: ModelChecksPanelProps) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const { raiseIssue } = useBcfCapture(projectId, bridge);

  // Run the per-element rule engine. Keyed by the model from the parent, so
  // the mutation state is scoped to the active model (no manual reset needed).
  const runMut = useMutation({
    mutationFn: (id: string) => checkBimModel(id),
    onSuccess: () => {
      // Refresh the scorecard so its trend reflects the run we just persisted.
      if (modelId) qc.invalidateQueries({ queryKey: ['bim-scorecard', modelId] });
    },
  });
  const report = runMut.data ?? null;
  const forbidden = runMut.error instanceof ApiError && runMut.error.status === 403;

  // Maturity scorecard - read-only, fetched once checks have been run so the
  // facets + trend appear alongside the report rather than eagerly loading the
  // whole element set just by opening the panel.
  const scorecardQuery = useQuery({
    queryKey: ['bim-scorecard', modelId],
    queryFn: () => fetchBimScorecard(modelId!),
    enabled: Boolean(modelId) && runMut.isSuccess,
    staleTime: 30_000,
  });

  // Turn a finding into a tracked BCF issue, reusing the Issues dock's capture
  // mechanism (`useBcfCapture`). We first select the finding's element so the
  // captured viewpoint links + highlights it, then create a topic pre-filled
  // from the finding. The dock lists topics under this same query key, so the
  // new issue appears there once we invalidate it.
  const createIssueMut = useMutation({
    mutationFn: async (finding: BIMCheckResultItem) => {
      if (finding.element_id) onFocusElement(finding.element_id, { zoom: false });
      const priority =
        toSeverity(finding.severity) === 'error'
          ? 'High'
          : toSeverity(finding.severity) === 'warning'
            ? 'Normal'
            : 'Low';
      const descParts = [finding.message];
      const elementLabel = finding.element_name || finding.element_id;
      if (elementLabel) {
        descParts.push(
          t('bim.checks_issue_element_line', { defaultValue: 'Element: {{ref}}', ref: elementLabel }),
        );
      }
      descParts.push(
        t('bim.checks_issue_rule_line', { defaultValue: 'Failed check: {{rule}}', rule: finding.rule_id }),
      );
      return raiseIssue({
        title: finding.rule_name || finding.rule_id,
        description: descParts.join('\n'),
        priority,
        labels: ['model-check'],
        bimModelId: modelId,
        topicStatus: 'Open',
      });
    },
    onSuccess: (result) => {
      qc.invalidateQueries({ queryKey: ['bcf', 'topics', projectId] });
      addToast({
        type: result.viewpointFailed ? 'warning' : 'success',
        title: result.viewpointFailed
          ? t('bim.checks_issue_created_no_view', { defaultValue: 'Issue created (view not saved)' })
          : t('bim.checks_issue_created', { defaultValue: 'Issue created from finding' }),
      });
    },
    onError: (err: Error) =>
      addToast({
        type: 'error',
        title: t('bim.checks_issue_failed', { defaultValue: 'Could not create issue' }),
        message: err.message,
      }),
  });
  const creatingFinding =
    createIssueMut.isPending && createIssueMut.variables ? createIssueMut.variables : null;

  const handleFocus = (finding: BIMCheckResultItem) => {
    if (!finding.element_id) return;
    const located = onFocusElement(finding.element_id, { zoom: true });
    if (!located) {
      addToast({
        type: 'info',
        title: t('bim.checks_element_not_in_view', {
          defaultValue: 'That element is not in the current 3D view.',
        }),
      });
    }
  };

  // Element-count hint from the report metadata, once a run has happened.
  const elementCount = report?.metadata?.element_count ?? null;

  return (
    <div className={clsx('flex h-full min-h-0 flex-col', className)}>
      {/* Header: title + run action */}
      <div className="flex items-center gap-2 border-b border-border-light px-4 py-2.5">
        <ListChecks size={16} className="shrink-0 text-oe-blue" />
        <h3 className="text-sm font-semibold text-content-primary">
          {t('bim.checks_title', { defaultValue: 'Checks' })}
        </h3>
        <div className="flex-1" />
        <Button
          variant="primary"
          size="sm"
          icon={<Play size={14} />}
          loading={runMut.isPending}
          disabled={!modelId || runMut.isPending}
          onClick={() => modelId && runMut.mutate(modelId)}
        >
          {report
            ? t('bim.checks_rerun', { defaultValue: 'Re-run' })
            : t('bim.checks_run', { defaultValue: 'Run checks' })}
        </Button>
      </div>

      {/* Body */}
      <div className="flex-1 overflow-y-auto p-4">
        {!modelId ? (
          <EmptyState
            icon={<ListChecks size={22} strokeWidth={1.5} />}
            title={t('bim.checks_no_model_title', { defaultValue: 'No model selected' })}
            description={t('bim.checks_no_model_desc', {
              defaultValue: 'Pick a model above to run the automated checks against it.',
            })}
          />
        ) : forbidden ? (
          <EmptyState
            icon={<Lock size={22} strokeWidth={1.5} />}
            title={t('bim.checks_forbidden_title', { defaultValue: 'Permission needed' })}
            description={t('bim.checks_forbidden_desc', {
              defaultValue: 'You lack permission to run model checks. Ask a project admin for validation access.',
            })}
          />
        ) : runMut.isPending ? (
          <div className="space-y-3">
            <Card padding="sm">
              <SkeletonText lines={3} />
            </Card>
            <Card padding="sm">
              <SkeletonText lines={4} />
            </Card>
          </div>
        ) : runMut.isError ? (
          <Card className="border-semantic-error/30 bg-semantic-error-bg" padding="sm">
            <div className="flex items-start gap-2">
              <XCircle size={18} className="mt-0.5 shrink-0 text-semantic-error" />
              <div className="min-w-0">
                <p className="text-sm font-medium text-semantic-error">
                  {t('bim.checks_run_failed', { defaultValue: 'Checks could not run' })}
                </p>
                <p className="mt-0.5 break-words text-xs text-content-secondary">
                  {runMut.error instanceof Error
                    ? runMut.error.message
                    : t('bim.checks_run_failed_desc', {
                        defaultValue: 'Something went wrong. Please try again.',
                      })}
                </p>
                <div className="mt-2">
                  <Button variant="secondary" size="sm" onClick={() => modelId && runMut.mutate(modelId)}>
                    {t('bim.checks_retry', { defaultValue: 'Try again' })}
                  </Button>
                </div>
              </div>
            </div>
          </Card>
        ) : !report ? (
          <EmptyState
            icon={<ListChecks size={22} strokeWidth={1.5} />}
            title={t('bim.checks_empty_title', { defaultValue: 'No checks run yet' })}
            description={t('bim.checks_empty_desc', {
              defaultValue:
                'Run the automated checks to score the model and list every element that needs attention.',
            })}
            action={{
              label: t('bim.checks_run', { defaultValue: 'Run checks' }),
              onClick: () => modelId && runMut.mutate(modelId),
            }}
          />
        ) : elementCount === 0 ? (
          <EmptyState
            icon={<ListChecks size={22} strokeWidth={1.5} />}
            title={t('bim.checks_no_elements_title', { defaultValue: 'Nothing to check' })}
            description={t('bim.checks_no_elements_desc', {
              defaultValue: 'This model has no elements, so there is nothing for the checks to inspect.',
            })}
          />
        ) : (
          <div className="space-y-4">
            <CheckSummary report={report} />

            {/* Maturity scorecard - loads just after the run. */}
            {scorecardQuery.isLoading ? (
              <Card padding="sm">
                <SkeletonText lines={4} />
              </Card>
            ) : scorecardQuery.data ? (
              <ScorecardCard
                facets={scorecardQuery.data.scorecard.facets}
                overallGrade={scorecardQuery.data.scorecard.overall_grade}
                overallScore={scorecardQuery.data.scorecard.overall_score}
                trendDirection={scorecardQuery.data.trend?.direction}
                trendDelta={scorecardQuery.data.trend?.delta}
              />
            ) : null}

            {/* No rule matched any element (has elements, but 0 checks). */}
            {report.total_rules === 0 && (
              <p className="rounded-lg border border-border-light bg-surface-secondary/40 px-3 py-2 text-2xs text-content-tertiary">
                {t('bim.checks_none_applied', {
                  defaultValue: "No automated checks applied to this model's elements.",
                })}
              </p>
            )}

            <FindingsList
              report={report}
              canFocus={viewerReady}
              onFocus={handleFocus}
              onCreateIssue={(finding) => createIssueMut.mutate(finding)}
              creatingFinding={creatingFinding}
            />
          </div>
        )}
      </div>
    </div>
  );
}

export default ModelChecksPanel;
