// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { useState, useMemo, useCallback, useEffect, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  ShieldCheck,
  Play,
  XCircle,
  ChevronDown,
  ChevronRight,
  Download,
} from 'lucide-react';
import { Button, Card, EmptyState, Skeleton, Breadcrumb, DismissibleInfo, IntroRichText, ModuleGuideButton } from '@/shared/ui';
import { PageHeader } from '@/shared/ui/PageHeader';
import { validationGuide } from './validationGuide';
import { apiGet, apiPost, triggerDownload } from '@/shared/lib/api';
import { fetchProjectList } from '@/shared/lib/projectList';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { useToastStore } from '@/stores/useToastStore';
import { useAuthStore } from '@/stores/useAuthStore';
import {
  validationExportFilename,
  validationExportPath,
  type ValidationExportFormat,
} from './validationExport';
import { ruleSetLabel } from './ruleSetLabels';
import { EstimateAuditPanel } from './EstimateAuditPanel';
import { SummaryStrip, ValidationResults } from './ValidationResults';
import { ruleTitle } from './ruleTitles';
import type { FindingFilter, PositionRef } from './validationFindings';

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
  // Requested rule sets that resolved to zero implemented rules. These never
  // ran - rendered as a "not implemented" notice so the dashboard never lets
  // an unimplemented standard read as silently passed.
  unsupported_rule_sets?: string[];
  // How long the run took, or null when the report does not record it. A
  // stored report predating the field has no duration, and defaulting that to
  // zero printed "Duration: 0.0ms" as though the run had been timed. A stored
  // zero has the same problem for a different reason and no fix can reach it:
  // reports written before the timing clock was changed were measured with one
  // that stepped about every 15.6ms on Windows, so a run shorter than a step
  // was recorded as zero and stays zero when the report is reopened.
  duration_ms: number | null;
  results: ValidationResultItem[];
}

/* ── Backend wire shapes (validation module) ──────────────────────────── */

/** Single result item as returned by POST /v1/validation/run/. */
interface RunValidationResultItem {
  rule_id: string;
  status: string; // "pass" | "warning" | "error" | "info"
  message: string;
  element_ref: string | null;
  details: Record<string, unknown> | null;
  suggestion: string | null;
}

/** Response body of POST /v1/validation/run/. */
interface RunValidationResponse {
  report_id: string;
  status: string;
  score: number | null;
  total_rules: number;
  passed_count: number;
  warning_count: number;
  error_count: number;
  info_count: number;
  rule_sets: string[];
  supported_rule_sets?: string[];
  unsupported_rule_sets?: string[];
  duration_ms: number;
  results: RunValidationResultItem[];
}

/**
 * Stored result item embedded in a persisted ValidationReport. Richer than
 * the run-response item — it carries `rule_name`, `severity` and `passed`
 * because the server keeps the full engine output in `results`.
 */
interface StoredResultItem {
  rule_id: string;
  rule_name?: string;
  severity?: string;
  status?: string;
  passed?: boolean;
  message: string;
  element_ref?: string | null;
  details?: Record<string, unknown> | null;
  suggestion?: string | null;
}

/** Response body of GET /v1/validation/reports/{id} and the list endpoint. */
interface ValidationReportResponse {
  id: string;
  project_id: string;
  target_type: string;
  target_id: string;
  rule_set: string;
  status: string;
  score: string | null;
  total_rules: number;
  passed_count: number;
  error_count: number;
  warning_count: number;
  results: StoredResultItem[];
  created_at: string | null;
  metadata: {
    duration_ms?: number;
    rule_sets?: string[];
    unsupported_rule_sets?: string[];
  } | null;
}

/* ── Rule-set resolution ──────────────────────────────────────────────── */

/**
 * Resolve which rule sets a project validates against, from its
 * classification standard. `boq_quality` is universal and always applied;
 * the classification-specific sets are layered on top. This mirrors the
 * engine's registered rule sets and is the exact list sent to /run/.
 */
function resolveRuleSets(classificationStandard: string | undefined): string[] {
  const sets = ['boq_quality'];
  const std = (classificationStandard ?? '').trim().toLowerCase();
  switch (std) {
    case 'din276':
      sets.push('din276', 'gaeb');
      break;
    case 'nrm':
      sets.push('nrm');
      break;
    case 'masterformat':
      sets.push('masterformat');
      break;
    default:
      break;
  }
  return sets;
}

/** Normalise an engine severity/status string to the UI severity union. */
function toSeverity(value: string | undefined): 'error' | 'warning' | 'info' {
  if (value === 'error') return 'error';
  if (value === 'info') return 'info';
  return 'warning';
}

/** Map a POST /v1/validation/run/ response into the page's report shape. */
function mapRunResponse(data: RunValidationResponse): ValidationReportData {
  return {
    id: data.report_id,
    status: data.status as ValidationReportData['status'],
    score: data.score ?? 0,
    counts: {
      total: data.total_rules,
      passed: data.passed_count,
      errors: data.error_count,
      warnings: data.warning_count,
      infos: data.info_count,
    },
    rule_sets: data.rule_sets,
    unsupported_rule_sets: data.unsupported_rule_sets,
    duration_ms: data.duration_ms,
    results: data.results.map((r) => {
      const passed = r.status === 'pass';
      return {
        rule_id: r.rule_id,
        rule_name: r.rule_id,
        severity: toSeverity(r.status),
        passed,
        message: r.message,
        element_ref: r.element_ref,
        suggestion: r.suggestion,
      };
    }),
  };
}

/** Map a persisted ValidationReport into the page's report shape. */
export function mapStoredReport(report: ValidationReportResponse): ValidationReportData {
  const results: ValidationResultItem[] = report.results.map((r) => {
    const passed = r.passed ?? r.status === 'pass';
    return {
      rule_id: r.rule_id,
      rule_name: r.rule_name ?? r.rule_id,
      severity: toSeverity(r.severity ?? r.status),
      passed,
      message: r.message,
      element_ref: r.element_ref ?? null,
      suggestion: r.suggestion ?? null,
    };
  });
  const infos = results.filter((r) => !r.passed && r.severity === 'info').length;
  return {
    id: report.id,
    status: report.status as ValidationReportData['status'],
    score: report.score !== null && report.score !== '' ? Number(report.score) : 0,
    counts: {
      total: report.total_rules,
      passed: report.passed_count,
      errors: report.error_count,
      warnings: report.warning_count,
      infos,
    },
    rule_sets: report.metadata?.rule_sets ?? (report.rule_set ? report.rule_set.split('+') : []),
    unsupported_rule_sets: report.metadata?.unsupported_rule_sets,
    duration_ms: report.metadata?.duration_ms ?? null,
    results,
  };
}

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

/* ── Rule-set human labels (chip primary text) ────────────────────────── */

/**
 * Short, human-readable name for a rule-set, shown as the primary chip text
 * so users never read the raw engine id (`boq_quality`, `din276`, …). The
 * engine id is rendered as muted secondary text next to it, and the full
 * sentence ({@link getRuleSetDescription}) stays as the hover/title tooltip.
 */
// Kept as a local alias so the call sites below read unchanged; the map itself
// now lives in ./ruleSetLabels so the chat renderer and the project settings
// pack list read the same names this page does.
const getRuleSetLabel = ruleSetLabel;

/* ── Rule-set descriptions (badge tooltips) ───────────────────────────── */

function getRuleSetDescription(
  ruleSet: string,
  t: (key: string, opts?: Record<string, unknown>) => string,
): string {
  const map: Record<string, string> = {
    boq_quality: t('validation.rs_boq_quality', {
      defaultValue: 'Universal BOQ hygiene: missing quantities/rates, duplicate ordinals, outlier rates.',
    }),
    din276: t('validation.rs_din276', {
      defaultValue: 'DIN 276 (DACH) cost-group structure & Kostengruppe completeness.',
    }),
    gaeb: t('validation.rs_gaeb', {
      defaultValue: 'GAEB tender format: LV structure & ordinal format checks.',
    }),
    nrm: t('validation.rs_nrm', {
      defaultValue: 'NRM 1/2 (UK) element compliance & measurement rules.',
    }),
    masterformat: t('validation.rs_masterformat', {
      defaultValue: 'MasterFormat (US) division structure & code format.',
    }),
    bim_compliance: t('validation.rs_bim', {
      defaultValue: 'CAD/BIM data: required properties, geometry validity, classification mapped.',
    }),
    project_completeness: t('validation.rs_completeness', {
      defaultValue: 'All trades covered, cost benchmarks, missing-scope detection.',
    }),
  };
  return map[ruleSet] ?? t('validation.rs_generic', {
    defaultValue: '{{name}} validation rules',
    name: ruleSet,
  });
}

/**
 * How many decimals to print for a run duration in milliseconds.
 *
 * The backend rounds a measured duration to two decimals, so the smallest
 * non-zero value it can put on the wire is 0.01ms. Printing that with one
 * decimal produces "0.0ms", the very text an untimed run produces, so a short
 * duration is shown with the digits the wire actually carries. Past 10ms the
 * second decimal is noise and one reads better.
 *
 * This is not a way to hide a zero. Durations used to be measured with a clock
 * that steps about every 15.6ms on Windows, so any run that finished inside one
 * step differenced to exactly zero and nine of twenty five stored reports read
 * "0.0ms". The clock was replaced, not the display: a zero is now rare and it
 * means something, either a report measured before the fix or a run genuinely
 * below five microseconds, and either way it is printed as it is.
 */
export function durationDecimals(ms: number): number {
  return Math.abs(ms) < 10 ? 2 : 1;
}

/**
 * Rule-set chip: the human label, with the full sentence as the title tooltip.
 *
 * It used to print the engine id beside the label as muted secondary text,
 * which had the effect of showing `boq_quality` next to a clean `MasterFormat`
 * on the same row: the id was hidden only when it happened to match its own
 * label, so the tidiest names were the ones that stayed tidy. An estimator has
 * no use for the identifier in either case, and the tooltip already carries
 * what the set actually checks.
 */
function RuleSetChip({ ruleSet, tone }: { ruleSet: string; tone: 'blue' | 'neutral' }) {
  const { t } = useTranslation();
  const label = getRuleSetLabel(ruleSet, t);
  const toneClasses =
    tone === 'blue'
      ? 'border-oe-blue/30 bg-oe-blue-subtle text-oe-blue'
      : 'border-border-light bg-surface-secondary text-content-secondary';
  return (
    <span
      title={getRuleSetDescription(ruleSet, t)}
      className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-medium ${toneClasses}`}
    >
      {label}
    </span>
  );
}

function SelectDropdown({
  id,
  label,
  value,
  onChange,
  options,
  placeholder,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
  options: { value: string; label: string }[];
  placeholder: string;
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={id} className="text-sm font-medium text-content-primary">{label}</label>
      <select
        id={id}
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
  const [searchParams, setSearchParams] = useSearchParams();
  const { activeProjectId, activeBOQId, setActiveProject, setActiveBOQ } =
    useProjectContextStore();
  const addToast = useToastStore((s) => s.addToast);

  // Honor a ?project= deep link (e.g. from the BOQ editor Validate button)
  // by adopting it into the global project context on mount.
  const projectParam = searchParams.get('project');
  const boqIdParam = searchParams.get('boq_id');

  const selectedProjectId = activeProjectId ?? '';
  // BOQ selection is remembered per project via the shared project context
  // (useProjectContextStore.activeBOQId). Seed from an explicit ?boq_id= deep
  // link first, then the remembered context, so a returning user lands on the
  // same BOQ they last validated without re-picking it.
  const [selectedBoqId, setSelectedBoqId] = useState(boqIdParam ?? activeBOQId ?? '');
  // Problems first: the passes stay one click away under their own filter.
  const [filter, setFilter] = useState<FindingFilter>('problems');
  // The long explainer is open by default only while there is no report; once
  // a report is on screen it folds into a one-line toggle above the results.
  const [introOpen, setIntroOpen] = useState(false);

  // Fetch projects
  const { data: projects, isLoading: projectsLoading } = useQuery({
    queryKey: ['projects'],
    queryFn: () => fetchProjectList<Project[]>(),
    staleTime: 5 * 60_000,
  });

  // Fetch BOQs for selected project
  const { data: boqs, isLoading: boqsLoading } = useQuery({
    queryKey: ['boqs', selectedProjectId],
    queryFn: () => apiGet<BOQ[]>(`/v1/boq/boqs/?project_id=${selectedProjectId}`),
    enabled: !!selectedProjectId,
  });

  // Adopt a ?project= deep link (carried by cross-module links such as the
  // BOQ editor Validate button) into the global project context, so the page
  // resolves to the same project the link came from rather than the last one
  // the user happened to have active.
  useEffect(() => {
    if (!projectParam || projectParam === selectedProjectId) return;
    const name = projects?.find((p) => p.id === projectParam)?.name ?? '';
    setActiveProject(projectParam, name);
  }, [projectParam, selectedProjectId, projects, setActiveProject]);

  const selectedProject = useMemo(
    () => projects?.find((p) => p.id === selectedProjectId),
    [projects, selectedProjectId],
  );

  // Remember the picked BOQ in the shared project context so it survives
  // navigation and reload (mirrors how the project itself is remembered).
  useEffect(() => {
    if (selectedBoqId && selectedBoqId !== activeBOQId) {
      setActiveBOQ(selectedBoqId);
    }
  }, [selectedBoqId, activeBOQId, setActiveBOQ]);

  // Rule sets the engine will apply to this project — derived from its
  // classification standard. Shown as chips and sent verbatim to /run/.
  const resolvedRuleSets = useMemo(
    () => resolveRuleSets(selectedProject?.classification_standard),
    [selectedProject],
  );

  // Validation report state (from a run, or restored from the latest
  // persisted report for the selected BOQ).
  const [report, setReport] = useState<ValidationReportData | null>(null);

  const reportIdParam = searchParams.get('report');

  // Auto-select the project's most recent BOQ (the list is created_at desc,
  // so boqs[0] is newest) when nothing is chosen yet and there is no report to
  // restore — cutting a returning user's clicks-to-result. We wait for the
  // restore query (below) to settle so a report's BOQ wins over this fallback.
  // Restore a persisted report so landing on the page shows the last
  // traffic-light state instead of an empty prompt. Resolution order:
  //   1. an explicit ?report= id (deep link from a notification),
  //   2. the newest report for the currently-selected BOQ,
  //   3. (no BOQ chosen yet) the project's most recent report of any BOQ —
  //      this lets a returning user land straight on their last result, and
  //      the alignment effect below selects that report's BOQ.
  // The list endpoint returns reports newest-first (created_at desc), so the
  // first matching entry is always the latest.
  const { data: restoredReport, isSuccess: restoreSettled } = useQuery({
    queryKey: ['validation', 'latest', selectedProjectId, selectedBoqId, reportIdParam],
    queryFn: async (): Promise<ValidationReportResponse | null> => {
      if (reportIdParam) {
        return apiGet<ValidationReportResponse>(`/v1/validation/reports/${reportIdParam}`);
      }
      const reports = await apiGet<ValidationReportResponse[]>(
        `/v1/validation/reports/?project_id=${selectedProjectId}&target_type=boq`,
      );
      if (selectedBoqId) {
        return reports.find((r) => r.target_id === selectedBoqId) ?? null;
      }
      // No BOQ picked yet: surface the project's most recent report.
      return reports[0] ?? null;
    },
    // Fire whenever a project is known (auto-restore the latest report) or on
    // an explicit ?report= deep link even before a project is resolved.
    enabled: !!selectedProjectId || !!reportIdParam,
    staleTime: 30_000,
  });

  // Alignment: when a restored report arrives (either via a ?report= deep link
  // or as the project's most recent report picked when no BOQ was chosen yet),
  // point the project/BOQ selectors at it so the dropdowns, rule chips and the
  // hydrate effect below all resolve to the report being viewed.
  useEffect(() => {
    if (!restoredReport) return;
    if (restoredReport.project_id && restoredReport.project_id !== selectedProjectId) {
      const name = projects?.find((p) => p.id === restoredReport.project_id)?.name ?? '';
      setActiveProject(restoredReport.project_id, name);
    }
    if (restoredReport.target_id && restoredReport.target_id !== selectedBoqId) {
      setSelectedBoqId(restoredReport.target_id);
    }
  }, [restoredReport, selectedProjectId, selectedBoqId, projects, setActiveProject]);

  // Hydrate the page report from a restored persisted report (only when the
  // user has not just produced a fresher one via a run). When no BOQ is yet
  // selected we still hydrate the project's most recent report; the alignment
  // effect above brings the BOQ selection into sync a render later.
  useEffect(() => {
    if (!restoredReport) return;
    if (selectedBoqId && !reportIdParam && restoredReport.target_id !== selectedBoqId) return;
    setReport((prev) => {
      if (prev && prev.id === restoredReport.id) return prev;
      return mapStoredReport(restoredReport);
    });
  }, [restoredReport, selectedBoqId, reportIdParam]);

  // Fallback BOQ auto-select: once the restore query has settled with no
  // report to align a BOQ, pick the project's most recent BOQ so the page is
  // one click (Run) from a result rather than forcing a manual BOQ pick.
  useEffect(() => {
    if (selectedBoqId || !boqs) return;
    if (!restoreSettled || restoredReport) return;
    // noUncheckedIndexedAccess: a length guard does not narrow boqs[0].
    const first = boqs[0];
    if (first) setSelectedBoqId(first.id);
  }, [selectedBoqId, boqs, restoreSettled, restoredReport]);

  // Run validation mutation — persists a server-side ValidationReport via
  // the validation module (RBAC: validation.create) instead of the
  // throwaway BOQ-side validate endpoint.
  const runValidation = useMutation({
    mutationFn: () =>
      apiPost<RunValidationResponse, { project_id: string; boq_id: string; rule_sets: string[] }>(
        '/v1/validation/run/',
        {
          project_id: selectedProjectId,
          boq_id: selectedBoqId,
          rule_sets: resolvedRuleSets,
        },
      ),
    onSuccess: (data) => {
      setReport(mapRunResponse(data));
      setFilter('problems');
      // Persist the report id in the URL so re-entry restores this result.
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          next.set('report', data.report_id);
          return next;
        },
        { replace: true },
      );
      queryClient.invalidateQueries({ queryKey: ['validation'] });
    },
    onError: (err: Error) => {
      addToast({ type: 'error', title: t('validation.run_failed', { defaultValue: 'Validation failed' }), message: err.message });
    },
  });

  // The project is chosen globally (top-bar switcher → useProjectContextStore),
  // not from an in-page picker. When it changes, drop the BOQ selection and any
  // restored report so the auto-restore re-resolves for the new project.
  const prevProjectRef = useRef(selectedProjectId);
  useEffect(() => {
    if (prevProjectRef.current === selectedProjectId) return;
    prevProjectRef.current = selectedProjectId;
    // Keep an explicit ?boq_id= deep link; otherwise reset to the new project.
    if (boqIdParam) return;
    setSelectedBoqId('');
    setReport(null);
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        next.delete('report');
        return next;
      },
      { replace: true },
    );
  }, [selectedProjectId, boqIdParam, setSearchParams]);

  const handleBoqChange = useCallback(
    (boqId: string) => {
      setSelectedBoqId(boqId);
      setActiveBOQ(boqId || null);
      setReport(null);
      // Drop any stale ?report= / ?boq_id= so the latest-report restore can
      // re-resolve for the newly selected BOQ.
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          next.delete('report');
          next.delete('boq_id');
          return next;
        },
        { replace: true },
      );
    },
    [setSearchParams, setActiveBOQ],
  );

  // Positions of the validated BOQ, so a finding names its position (ordinal
  // and description) instead of the id the engine stores in element_ref.
  const reportHasRefs = useMemo(
    () => !!report && report.results.some((r) => r.element_ref),
    [report],
  );
  const { data: boqPositions } = useQuery({
    queryKey: ['validation', 'boq-positions', selectedBoqId],
    queryFn: () =>
      apiGet<{ positions: { id: string; ordinal: string; description: string }[] }>(
        `/v1/boq/boqs/${selectedBoqId}`,
      ),
    enabled: !!selectedBoqId && reportHasRefs,
    staleTime: 60_000,
  });
  const positionsById = useMemo(() => {
    if (!boqPositions) return null;
    const map = new Map<string, PositionRef>();
    for (const p of boqPositions.positions ?? []) {
      map.set(p.id, { ordinal: p.ordinal ?? '', description: p.description ?? '' });
    }
    return map;
  }, [boqPositions]);
  const boqNamesById = useMemo(
    () => new Map((boqs ?? []).map((b) => [b.id, b.name] as const)),
    [boqs],
  );
  const ruleDescriptions = useMemo(() => getRuleDescriptions(t), [t]);
  const ruleHint = useCallback(
    (ruleId: string) => ruleDescriptions[ruleId] ?? null,
    [ruleDescriptions],
  );

  const [pdfPending, setPdfPending] = useState(false);

  const handleExportPdf = useCallback(async () => {
    if (!selectedBoqId || pdfPending) return;
    setPdfPending(true);
    try {
      const token = useAuthStore.getState().accessToken;
      const response = await fetch(`/api/v1/boq/boqs/${selectedBoqId}/export/pdf/`, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      if (!response.ok) throw new Error(`Export failed: ${response.status}`);
      const blob = await response.blob();
      triggerDownload(blob, `boq_${selectedBoqId.slice(0, 8)}.pdf`);
    } catch (err) {
      addToast({
        type: 'error',
        title: t('validation.export_failed', { defaultValue: 'Export failed' }),
        message: err instanceof Error ? err.message : undefined,
      });
    } finally {
      setPdfPending(false);
    }
  }, [selectedBoqId, pdfPending, addToast, t]);

  // Validation findings are persisted server-side as a ValidationReport
  // (see /v1/validation/run/). Export is served by the validation module
  // (GET /v1/validation/reports/{id}/export.csv|.xlsx): the backend is the
  // single place that neutralises spreadsheet formula injection in every
  // cell, so we download the server-rendered file rather than rebuilding it
  // (and its escaping) in the browser.
  const [exportPending, setExportPending] = useState<ValidationExportFormat | null>(null);

  const handleExport = useCallback(
    async (format: ValidationExportFormat) => {
      if (!report || exportPending) return;
      setExportPending(format);
      try {
        const token = useAuthStore.getState().accessToken;
        const response = await fetch(validationExportPath(report.id, format), {
          headers: token ? { Authorization: `Bearer ${token}` } : {},
        });
        if (!response.ok) throw new Error(`Export failed: ${response.status}`);
        const blob = await response.blob();
        triggerDownload(
          blob,
          validationExportFilename(format, { boqId: selectedBoqId, reportId: report.id }),
        );
        addToast({
          type: 'success',
          title: t('validation.findings_exported', { defaultValue: 'Findings exported' }),
        });
      } catch (err) {
        addToast({
          type: 'error',
          title: t('validation.export_failed', { defaultValue: 'Export failed' }),
          message: err instanceof Error ? err.message : undefined,
        });
      } finally {
        setExportPending(null);
      }
    },
    [report, exportPending, selectedBoqId, addToast, t],
  );

  // Raise an NCR from a failing validation finding. Deep-links to the NCR
  // module with the finding pre-filled (title, description, location and a
  // source marker). The NCR page consumes these ?create= params; until it
  // lands, the link still opens the NCR register scoped to the project.
  const handleRaiseNcr = useCallback(
    (result: ValidationResultItem) => {
      const params = new URLSearchParams({ create: '1', source: 'validation' });
      if (selectedProjectId) params.set('project', selectedProjectId);
      params.set(
        'title',
        t('validation.ncr_title_prefill', {
          defaultValue: 'Validation: {{rule}}',
          rule: ruleTitle(result.rule_id, result.rule_name, t),
        }),
      );
      const descParts = [result.message];
      if (result.element_ref) {
        descParts.push(
          t('validation.ncr_element_line', {
            defaultValue: 'BOQ element: {{ref}}',
            ref: result.element_ref,
          }),
        );
      }
      descParts.push(
        t('validation.ncr_rule_line', {
          defaultValue: 'Failed rule: {{rule}}',
          rule: result.rule_id,
        }),
      );
      params.set('description', descParts.join('\n'));
      if (result.element_ref) params.set('element_ref', result.element_ref);
      navigate(`/ncr?${params.toString()}`);
    },
    [selectedProjectId, navigate, t],
  );

  const introLinks = [
    {
      label: t('validation.intro_link_boq', { defaultValue: 'Open BOQ editor' }),
      onClick: () => navigate('/boq'),
    },
    {
      label: t('validation.intro_link_bim', { defaultValue: 'BIM / canonical model' }),
      onClick: () => navigate('/bim'),
    },
  ];

  const boqOptions = (boqs || []).map((b) => ({
    value: b.id,
    label: b.name,
  }));

  return (
    <div className="space-y-5 animate-fade-in">
      <Breadcrumb items={[
        ...(selectedProject ? [{ label: selectedProject.name, to: `/projects/${selectedProject.id}` }] : []),
        { label: t('validation.title', 'Validation') },
      ]} />

      {/* Header row — the module name lives in the top app bar; only a one-line
          subtitle here per the module style guide (no in-page H1, no project
          picker; the project comes from the global top-bar context). */}
      <PageHeader
        srTitle={t('validation.title', 'Validation')}
        subtitle={t(
          'validation.subtitle',
          'Check a Bill of Quantities against the rule sets configured for the project.',
        )}
        actions={<ModuleGuideButton content={validationGuide} />}
      />

      {/* The explainer is for a first visit. Once a report is on screen it
          folds into one line, so the results start near the top. */}
      {!report && (
        <DismissibleInfo
          storageKey="validation"
          title={t('validation.intro_title', {
            defaultValue: 'How validation fits the workflow',
          })}
          more={
            t('validation.intro_more', { defaultValue: '' })
              ? <IntroRichText text={t('validation.intro_more', { defaultValue: '' })} />
              : undefined
          }
          links={introLinks}
        >
          {t('validation.intro_body', {
            defaultValue:
              'Validation is a first-class step in the Import → Validate → Enrich → Estimate pipeline. It checks a Bill of Quantities (and its linked canonical/BIM elements) against the rule sets configured for the project - these are derived automatically from the project’s region and classification standard (DIN 276, GAEB, NRM, MasterFormat, boq_quality, …). Each finding links back to the exact BOQ position so you can fix it at the source.',
          })}
        </DismissibleInfo>
      )}

      {/* No active project — the project is chosen globally in the top bar, so
          guide the user there instead of duplicating a picker. */}
      {!selectedProjectId && !projectsLoading && (
        <EmptyState
          icon={<ShieldCheck size={28} strokeWidth={1.5} />}
          title={t('validation.no_project_title', { defaultValue: 'Select a project to validate' })}
          description={t('validation.no_project_description', {
            defaultValue:
              'Pick a project from the switcher in the top bar, then choose one of its Bills of Quantities to check.',
          })}
          action={{
            label: t('validation.go_to_projects', { defaultValue: 'Browse projects' }),
            onClick: () => navigate('/projects'),
          }}
        />
      )}

      {/* Selector bar — BOQ picker + Run. The project is global (top bar). */}
      {selectedProjectId && (
        <Card>
          <div className="flex flex-col gap-4 sm:flex-row sm:items-end">
            <div className="flex-1">
              {boqsLoading ? (
                <Skeleton height={40} className="w-full" rounded="md" />
              ) : (
                <SelectDropdown
                  id="validation-boq-select"
                  label={t('validation.select_boq', 'Bill of Quantities')}
                  value={selectedBoqId}
                  onChange={handleBoqChange}
                  options={boqOptions}
                  placeholder={
                    boqOptions.length > 0
                      ? t('validation.select_boq_placeholder', 'Choose a BOQ...')
                      : t('validation.no_boqs_for_project', { defaultValue: 'This project has no BOQs yet' })
                  }
                />
              )}
            </div>
            <div className="shrink-0">
              <span title={!selectedBoqId ? t('validation.select_boq_first', { defaultValue: 'Select a BOQ first' }) : undefined}>
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

          {/* Resolved rule sets — shown before running so the user knows
              exactly which checks will be applied to this project. Once a
              report exists the summary strip names the sets it ran. */}
          {!report && (
          <div className="mt-4 flex flex-wrap items-center gap-1.5 border-t border-border-light pt-3">
            <span className="text-xs text-content-tertiary">
              {t('validation.will_check_with', { defaultValue: 'Will check with' })}:
            </span>
            {resolvedRuleSets.map((rs) => (
              <RuleSetChip key={rs} ruleSet={rs} tone="blue" />
            ))}
            <span className="text-xs text-content-tertiary">
              {t('validation.rule_sets_from_standard', {
                defaultValue: 'derived from the project’s classification standard',
              })}
            </span>
          </div>
          )}
        </Card>
      )}

      {/* One-click estimate audit - grouped findings + per-finding apply-fix
          + re-run score delta. Independent of the rule-set report above. */}
      {selectedProjectId && !report && (
        <EstimateAuditPanel projectId={selectedProjectId} boqId={selectedBoqId} />
      )}

      {/* No report yet (project active) — honest empty state once a project is
          selected but no report has been run or restored. */}
      {selectedProjectId && !report && !runValidation.isPending && (
        <EmptyState
          icon={<ShieldCheck size={28} strokeWidth={1.5} />}
          title={t('validation.empty_title', 'No validation report yet')}
          description={t(
            'validation.empty_description',
            'Choose a BOQ and click "Run Validation" to check its data quality.',
          )}
        />
      )}

      {/* Loading state */}
      {runValidation.isPending && (
        <div className="space-y-4">
          <Skeleton height={72} className="w-full" rounded="lg" />
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
        <div className="space-y-4 animate-fade-in">
          {/* Explainer folded to one line while a report is on screen. */}
          <div>
            <button
              type="button"
              onClick={() => setIntroOpen((v) => !v)}
              aria-expanded={introOpen}
              className="inline-flex items-center gap-1 text-xs font-medium text-content-secondary transition-colors hover:text-content-primary"
            >
              {introOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
              {t('validation.intro_toggle', { defaultValue: 'How validation works' })}
            </button>
            {introOpen && (
              <div className="mt-2 rounded-xl border border-border-light bg-surface-secondary/40 px-4 py-3 text-sm leading-relaxed text-content-secondary animate-fade-in">
                {t('validation.intro_body', {
                  defaultValue:
                    'Validation is a first-class step in the Import → Validate → Enrich → Estimate pipeline. It checks a Bill of Quantities (and its linked canonical/BIM elements) against the rule sets configured for the project - these are derived automatically from the project’s region and classification standard (DIN 276, GAEB, NRM, MasterFormat, boq_quality, …). Each finding links back to the exact BOQ position so you can fix it at the source.',
                })}
                <div className="mt-2 flex flex-wrap gap-3">
                  {introLinks.map((link) => (
                    <button
                      key={link.label}
                      type="button"
                      onClick={link.onClick}
                      className="text-xs font-medium text-oe-blue hover:underline"
                    >
                      {link.label}
                    </button>
                  ))}
                </div>
              </div>
            )}
          </div>

          <SummaryStrip
            report={report}
            filter={filter}
            onFilterChange={setFilter}
            ruleSetLabel={(rs) => getRuleSetLabel(rs, t)}
            durationDecimals={durationDecimals}
          />

          <ValidationResults
            findings={report.results}
            totalChecks={report.counts.total}
            filter={filter}
            onFilterChange={setFilter}
            positions={positionsById}
            boqs={boqNamesById}
            boqId={selectedBoqId || undefined}
            ruleHint={ruleHint}
            onRaiseNcr={handleRaiseNcr}
          />

          {/* Action buttons */}
          <div className="flex flex-wrap items-center gap-3 border-t border-border-light pt-6">
            <Button
              variant="secondary"
              size="md"
              icon={<Download size={16} />}
              onClick={() => handleExport('xlsx')}
              loading={exportPending === 'xlsx'}
              disabled={exportPending !== null}
            >
              {exportPending === 'xlsx'
                ? t('validation.export_pending', { defaultValue: 'Preparing export…' })
                : t('validation.export_xlsx', { defaultValue: 'Export Findings (XLSX)' })}
            </Button>
            <Button
              variant="secondary"
              size="md"
              icon={<Download size={16} />}
              onClick={() => handleExport('csv')}
              loading={exportPending === 'csv'}
              disabled={exportPending !== null}
            >
              {exportPending === 'csv'
                ? t('validation.export_pending', { defaultValue: 'Preparing export…' })
                : t('validation.export_csv', { defaultValue: 'Export Findings (CSV)' })}
            </Button>
            <Button
              variant="ghost"
              size="md"
              icon={<Download size={16} />}
              onClick={handleExportPdf}
              loading={pdfPending}
              disabled={pdfPending}
            >
              {pdfPending
                ? t('validation.export_boq_pdf_pending', { defaultValue: 'Preparing BOQ PDF…' })
                : t('validation.export_priced_boq_pdf', { defaultValue: 'Export priced BOQ (PDF)' })}
            </Button>
          </div>

          {/* The one-click estimate audit is a separate tool; with a report
              on screen it sits below the findings instead of above them. */}
          {selectedProjectId && (
            <EstimateAuditPanel projectId={selectedProjectId} boqId={selectedBoqId} />
          )}
        </div>
      )}
    </div>
  );
}
