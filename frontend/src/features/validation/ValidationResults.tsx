// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The result half of the validation page: a compact summary strip, the filter,
// and the findings grouped by rule. An estimator opens a report to see what is
// wrong, so the list starts on the problems, one heading per rule with what to
// do, and every finding names the BOQ position it is about instead of an id.
import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import {
  AlertOctagon,
  AlertTriangle,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  ExternalLink,
  Info,
  Search,
  Wand2,
  XCircle,
} from 'lucide-react';
import { Badge, Button, Card } from '@/shared/ui';
import { fmtFixed, fmtList } from '@/shared/lib/formatters';
import { ruleTitle } from './ruleTitles';
import {
  countFindings,
  groupFindings,
  resolveScope,
  shortDescription,
  type FindingFilter,
  type FindingGroup,
  type FindingLike,
  type FindingScope,
  type PositionRef,
} from './validationFindings';

/** Above this many findings in view, the search box is offered. */
const SEARCH_THRESHOLD = 20;
/** Findings rendered per group before "Show all" (passes can run to hundreds). */
const GROUP_PAGE = 50;
/** With this many findings or fewer in view, groups open expanded. */
const AUTO_EXPAND_LIMIT = 20;

export interface ReportSummary {
  score: number;
  counts: { total: number; passed: number; errors: number; warnings: number; infos: number };
  rule_sets: string[];
  unsupported_rule_sets?: string[];
  duration_ms: number | null;
}

type Tone = FindingGroup['tone'];

function toneIcon(tone: Tone, size = 16) {
  if (tone === 'passed') return <CheckCircle2 size={size} className="shrink-0 text-semantic-success" />;
  if (tone === 'error') return <XCircle size={size} className="shrink-0 text-semantic-error" />;
  if (tone === 'info') return <Info size={size} className="shrink-0 text-blue-500" />;
  return <AlertTriangle size={size} className="shrink-0 text-semantic-warning" />;
}

function toneBadge(tone: Tone): 'success' | 'error' | 'warning' | 'blue' {
  if (tone === 'passed') return 'success';
  if (tone === 'error') return 'error';
  if (tone === 'info') return 'blue';
  return 'warning';
}

function useToneLabel() {
  const { t } = useTranslation();
  return (tone: Tone) =>
    tone === 'passed'
      ? t('validation.status_passed', 'Passed')
      : tone === 'error'
        ? t('validation.status_error', 'Error')
        : tone === 'info'
          ? t('validation.status_info', 'Info')
          : t('validation.status_warning', 'Warning');
}

/* ── Summary strip ─────────────────────────────────────────────────────── */

function scoreColor(pct: number, errors: number, warnings: number): string {
  if (errors > 0 || pct < 60) return 'text-semantic-error';
  if (warnings > 0 || pct < 80) return 'text-semantic-warning';
  if (pct < 95) return 'text-oe-blue';
  return 'text-semantic-success';
}

/**
 * Score, errors, warnings, passes and checks on one line. Each count is also a
 * shortcut to its filter. The score is not a pass rate: a blocking error caps
 * it (see `compute_quality_score`), so when that cap produced the number the
 * strip says so rather than leaving two numbers that seem to disagree.
 */
export function SummaryStrip({
  report,
  filter,
  onFilterChange,
  ruleSetLabel,
  durationDecimals,
}: {
  report: ReportSummary;
  filter: FindingFilter;
  onFilterChange: (f: FindingFilter) => void;
  ruleSetLabel: (ruleSet: string) => string;
  durationDecimals: (ms: number) => number;
}) {
  const { t } = useTranslation();
  const pct = Math.round(report.score * 100);
  const { errors, warnings, passed, total } = report.counts;

  const tile = (
    key: FindingFilter | null,
    label: string,
    value: number | string,
    color: string,
    icon: React.ReactNode,
  ) => {
    const active = key !== null && filter === key;
    const body = (
      <>
        <span className="flex items-center gap-1.5 text-xs text-content-secondary">
          {icon}
          {label}
        </span>
        <span className={`text-xl font-semibold tabular-nums ${color}`}>{value}</span>
      </>
    );
    if (key === null) {
      return <div className="flex min-w-[6.5rem] flex-col gap-0.5 px-3 py-2">{body}</div>;
    }
    return (
      <button
        type="button"
        onClick={() => onFilterChange(key)}
        aria-pressed={active}
        className={`flex min-w-[6.5rem] flex-col gap-0.5 rounded-lg px-3 py-2 text-left transition-colors duration-fast ${
          active ? 'bg-surface-secondary ring-1 ring-border' : 'hover:bg-surface-secondary/60'
        }`}
      >
        {body}
      </button>
    );
  };

  return (
    <Card padding="none" className="px-2 py-2">
      <div className="flex flex-wrap items-stretch gap-1">
        <div
          className="flex min-w-[6.5rem] flex-col gap-0.5 px-3 py-2"
          title={errors > 0 ? t('validation.score_capped', { defaultValue: 'Capped by blocking errors, not a pass rate' }) : undefined}
        >
          <span className="text-xs text-content-secondary">
            {t('validation.quality_score', { defaultValue: 'Quality score' })}
          </span>
          <span className={`text-xl font-semibold tabular-nums ${scoreColor(pct, errors, warnings)}`}>{pct}%</span>
        </div>
        {tile('errors', t('validation.errors', 'Errors'), errors, errors > 0 ? 'text-semantic-error' : 'text-content-primary', <XCircle size={12} className="text-semantic-error" />)}
        {tile('warnings', t('validation.warnings', 'Warnings'), warnings, warnings > 0 ? 'text-semantic-warning' : 'text-content-primary', <AlertTriangle size={12} className="text-semantic-warning" />)}
        {tile('passed', t('validation.passed', 'Passed'), passed, 'text-semantic-success', <CheckCircle2 size={12} className="text-semantic-success" />)}
        {tile(null, t('validation.checks_label', { defaultValue: 'Checks' }), total, 'text-content-primary', null)}
        <div className="ml-auto flex min-w-0 flex-col justify-center gap-1 px-3 py-2 text-xs text-content-tertiary">
          <span className="flex flex-wrap items-center gap-1">
            <span>{t('validation.rule_sets', 'Rule sets')}:</span>
            <span className="text-content-secondary">
              {report.rule_sets.length > 0
                ? fmtList(report.rule_sets.map(ruleSetLabel))
                : t('validation.no_rule_sets', { defaultValue: 'none configured for this project' })}
            </span>
          </span>
          {report.duration_ms !== null && (
            <span className="tabular-nums">
              {t('validation.duration_ms', {
                defaultValue: 'Duration: {{ms}}ms',
                ms: fmtFixed(report.duration_ms, durationDecimals(report.duration_ms)),
              })}
            </span>
          )}
        </div>
      </div>
      {errors > 0 && (
        <p className="px-3 pb-1 text-xs text-content-tertiary">
          {t('validation.score_capped', { defaultValue: 'Capped by blocking errors, not a pass rate' })}
        </p>
      )}
      {report.unsupported_rule_sets && report.unsupported_rule_sets.length > 0 && (
        <p
          className="px-3 pb-1 text-xs text-amber-700 dark:text-amber-300"
          title={t('validation.unsupported_rule_sets_hint', {
            defaultValue:
              'No validation rules are implemented for this rule set, so it was not run. It is reported as not implemented rather than passed.',
          })}
        >
          {t('validation.unsupported_rule_sets', { defaultValue: 'Not implemented (did not run):' })}{' '}
          {fmtList(report.unsupported_rule_sets.map(ruleSetLabel))}
        </p>
      )}
    </Card>
  );
}

/* ── Filter bar ────────────────────────────────────────────────────────── */

function FilterBar({
  filter,
  onFilterChange,
  counts,
}: {
  filter: FindingFilter;
  onFilterChange: (f: FindingFilter) => void;
  counts: Record<FindingFilter, number>;
}) {
  const { t } = useTranslation();
  const options: { value: FindingFilter; label: string }[] = [
    { value: 'problems', label: t('validation.filter_problems', { defaultValue: 'Problems' }) },
    { value: 'errors', label: t('validation.filter_errors', 'Errors') },
    { value: 'warnings', label: t('validation.filter_warnings', 'Warnings') },
    ...(counts.info > 0 ? [{ value: 'info' as const, label: t('validation.filter_info', 'Info') }] : []),
    { value: 'passed', label: t('validation.filter_passed', 'Passed') },
    { value: 'all', label: t('validation.filter_all', 'All') },
  ];
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {options.map((opt) => (
        <button
          key={opt.value}
          type="button"
          onClick={() => onFilterChange(opt.value)}
          aria-pressed={filter === opt.value}
          className={`inline-flex items-center gap-1 rounded-lg px-2.5 py-1.5 text-xs font-medium transition-all duration-fast ${
            filter === opt.value
              ? 'bg-oe-blue text-content-inverse shadow-xs'
              : 'bg-surface-secondary text-content-secondary hover:bg-surface-tertiary'
          }`}
        >
          {opt.label}
          <span className={`tabular-nums ${filter === opt.value ? 'text-content-inverse/70' : 'text-content-tertiary'}`}>
            {counts[opt.value]}
          </span>
        </button>
      ))}
    </div>
  );
}

/* ── Finding row ───────────────────────────────────────────────────────── */

function ScopeLabel({ scope, boqId }: { scope: FindingScope; boqId: string | undefined }) {
  const { t } = useTranslation();
  switch (scope.kind) {
    case 'position':
      return (
        <span className="flex min-w-0 items-baseline gap-2">
          <span className="shrink-0 font-mono text-xs font-semibold text-content-primary">
            {scope.position.ordinal || '?'}
          </span>
          <span className="truncate text-sm text-content-primary" title={scope.position.description}>
            {shortDescription(scope.position.description)}
          </span>
        </span>
      );
    case 'boq':
      return (
        <span className="truncate text-sm font-medium text-content-primary">
          {scope.boqId === boqId || !scope.name
            ? t('validation.scope_whole_boq', { defaultValue: 'Whole BOQ' })
            : scope.name}
        </span>
      );
    case 'loading':
      return (
        <span className="text-xs text-content-tertiary">
          {t('validation.position_loading', { defaultValue: 'Loading position' })}
        </span>
      );
    case 'missing':
      return (
        <span className="text-xs text-content-tertiary">
          {t('validation.position_not_found', { defaultValue: 'Position no longer in this BOQ' })}
        </span>
      );
    default:
      return (
        <span className="text-sm font-medium text-content-primary">
          {t('validation.scope_project', { defaultValue: 'Project' })}
        </span>
      );
  }
}

function FindingRow<T extends FindingLike>({
  finding,
  scope,
  boqId,
  showSuggestion,
  onRaiseNcr,
}: {
  finding: T;
  scope: FindingScope;
  boqId: string | undefined;
  showSuggestion: boolean;
  onRaiseNcr?: (finding: T) => void;
}) {
  const { t } = useTranslation();
  const link =
    scope.kind === 'position' && boqId
      ? `/boq/${boqId}?highlight=${scope.positionId}`
      : scope.kind === 'boq'
        ? `/boq/${scope.boqId}`
        : null;

  return (
    <li className="flex flex-col gap-1 px-4 py-2.5 sm:flex-row sm:items-start sm:gap-4">
      <div className="min-w-0 flex-1">
        <ScopeLabel scope={scope} boqId={boqId} />
        <p className="mt-0.5 text-sm text-content-secondary">{finding.message}</p>
        {showSuggestion && finding.suggestion && (
          <p className="mt-1 flex items-start gap-1.5 text-xs text-oe-blue">
            <Wand2 size={12} className="mt-0.5 shrink-0" />
            {finding.suggestion}
          </p>
        )}
      </div>
      <div className="flex shrink-0 items-center gap-2">
        {link && (
          <Link
            to={link}
            className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs font-medium text-oe-blue hover:bg-oe-blue-subtle"
          >
            {t('validation.open_in_boq', { defaultValue: 'Open in BOQ' })}
            <ExternalLink size={11} />
          </Link>
        )}
        {!finding.passed && finding.severity === 'error' && onRaiseNcr && (
          <Button
            variant="ghost"
            size="sm"
            icon={<AlertOctagon size={13} />}
            onClick={() => onRaiseNcr(finding)}
          >
            {t('validation.raise_ncr', { defaultValue: 'Raise NCR' })}
          </Button>
        )}
      </div>
    </li>
  );
}

/* ── Rule group ────────────────────────────────────────────────────────── */

function RuleGroup<T extends FindingLike>({
  group,
  expanded,
  onToggle,
  scopeOf,
  boqId,
  hint,
  onRaiseNcr,
}: {
  group: FindingGroup<T>;
  expanded: boolean;
  onToggle: () => void;
  scopeOf: (finding: T) => FindingScope;
  boqId: string | undefined;
  hint: string | null;
  onRaiseNcr?: (finding: T) => void;
}) {
  const { t } = useTranslation();
  const toneLabel = useToneLabel();
  const [showAll, setShowAll] = useState(false);
  const visible = showAll ? group.findings : group.findings.slice(0, GROUP_PAGE);
  const panelId = `validation-group-${group.ruleId.replace(/[^a-zA-Z0-9_-]/g, '-')}`;

  return (
    <div className="rounded-xl border border-border-light bg-surface-primary">
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={expanded}
        aria-controls={panelId}
        className="flex w-full items-start gap-3 px-4 py-3 text-left hover:bg-surface-secondary/50"
      >
        <span className="mt-0.5">{toneIcon(group.tone)}</span>
        <span className="min-w-0 flex-1">
          <span className="block text-sm font-semibold text-content-primary">{group.ruleName}</span>
          {hint && group.tone !== 'passed' && (
            <span className="mt-0.5 block text-xs text-content-secondary">
              {group.commonSuggestion && (
                <>
                  <span className="font-medium text-oe-blue">{t('validation.what_to_do', { defaultValue: 'What to do' })}:</span>{' '}
                </>
              )}
              {hint}
            </span>
          )}
        </span>
        <Badge variant={toneBadge(group.tone) as 'success' | 'error' | 'warning'} size="sm">
          {toneLabel(group.tone)}
        </Badge>
        <span className="min-w-[2rem] text-right text-sm font-semibold tabular-nums text-content-primary">
          {group.findings.length}
        </span>
        <span className="mt-0.5 shrink-0 text-content-tertiary">
          {expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        </span>
      </button>
      {expanded && (
        <div id={panelId} className="border-t border-border-light">
          <ul className="divide-y divide-border-light">
            {visible.map(({ index, finding }) => (
              <FindingRow
                key={index}
                finding={finding}
                scope={scopeOf(finding)}
                boqId={boqId}
                showSuggestion={!group.commonSuggestion}
                onRaiseNcr={onRaiseNcr}
              />
            ))}
          </ul>
          {!showAll && group.findings.length > GROUP_PAGE && (
            <div className="border-t border-border-light px-4 py-2">
              <button
                type="button"
                onClick={() => setShowAll(true)}
                className="text-xs font-medium text-oe-blue hover:underline"
              >
                {t('validation.show_all_findings', { defaultValue: 'Show all {{total}}', total: group.findings.length })}
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/* ── Results ───────────────────────────────────────────────────────────── */

export function ValidationResults<T extends FindingLike>({
  findings,
  totalChecks,
  filter,
  onFilterChange,
  positions,
  boqs,
  boqId,
  ruleHint,
  onRaiseNcr,
}: {
  findings: readonly T[];
  totalChecks: number;
  filter: FindingFilter;
  onFilterChange: (f: FindingFilter) => void;
  /** Positions of the validated BOQ by id, or null while they load. */
  positions: ReadonlyMap<string, PositionRef> | null;
  /** Names of the project's BOQs by id (a project rule may point at a bill). */
  boqs: ReadonlyMap<string, string>;
  boqId: string | undefined;
  /** A one-line description of the rule, used when its findings share no suggestion. */
  ruleHint: (ruleId: string) => string | null;
  onRaiseNcr?: (finding: T) => void;
}) {
  const { t } = useTranslation();
  const [search, setSearch] = useState('');
  const [toggled, setToggled] = useState<Record<string, boolean>>({});

  const counts = useMemo(() => countFindings(findings), [findings]);
  const titleOf = useMemo(() => {
    const cache = new Map<string, string>();
    return (f: T) => {
      let title = cache.get(f.rule_id);
      if (title === undefined) {
        title = ruleTitle(f.rule_id, f.rule_name, t);
        cache.set(f.rule_id, title);
      }
      return title;
    };
  }, [t]);
  const scopeOf = (f: T) => resolveScope(f.element_ref, positions, boqs);

  const inView = counts[filter];
  const searchActive = inView > SEARCH_THRESHOLD && search.trim() !== '';
  const groups = useMemo(
    () =>
      groupFindings(findings, filter, {
        title: titleOf,
        search: searchActive ? search : '',
        position: (f) => (f.element_ref ? positions?.get(f.element_ref) : undefined),
      }),
    [findings, filter, titleOf, searchActive, search, positions],
  );
  const shown = groups.reduce((n, g) => n + g.findings.length, 0);
  const defaultOpen = searchActive || shown <= AUTO_EXPAND_LIMIT || groups.length === 1;
  const isOpen = (ruleId: string) => toggled[`${filter}:${ruleId}`] ?? defaultOpen;
  const setAll = (open: boolean) =>
    setToggled((prev) => {
      const next = { ...prev };
      for (const g of groups) next[`${filter}:${g.ruleId}`] = open;
      return next;
    });

  const noProblems = counts.problems === 0 && counts.all > 0;

  return (
    <div className="space-y-3">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <h2 className="text-lg font-semibold text-content-primary">{t('validation.results_title', 'Results')}</h2>
        <FilterBar filter={filter} onFilterChange={onFilterChange} counts={counts} />
      </div>

      {(inView > SEARCH_THRESHOLD || groups.length > 1) && (
        <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
          {inView > SEARCH_THRESHOLD && (
            <label className="relative flex-1">
              <span className="sr-only">{t('validation.search_label', { defaultValue: 'Search findings' })}</span>
              <Search size={14} className="pointer-events-none absolute start-3 top-1/2 -translate-y-1/2 text-content-tertiary" />
              <input
                type="search"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder={t('validation.search_placeholder', { defaultValue: 'Search position or text' })}
                className="h-9 w-full rounded-lg border border-border bg-surface-primary ps-8 pe-3 text-sm text-content-primary placeholder:text-content-tertiary focus:border-oe-blue focus:outline-none focus:ring-2 focus:ring-oe-blue/30"
              />
            </label>
          )}
          {groups.length > 1 && (
            <div className="flex items-center gap-1.5 sm:ml-auto">
              <button
                type="button"
                onClick={() => setAll(true)}
                className="text-xs font-medium text-content-secondary transition-colors hover:text-content-primary"
              >
                {t('validation.expand_all', { defaultValue: 'Expand All' })}
              </button>
              <span className="text-content-quaternary">|</span>
              <button
                type="button"
                onClick={() => setAll(false)}
                className="text-xs font-medium text-content-secondary transition-colors hover:text-content-primary"
              >
                {t('validation.collapse_all', { defaultValue: 'Collapse All' })}
              </button>
            </div>
          )}
        </div>
      )}

      {noProblems && filter === 'problems' ? (
        <div className="flex flex-col items-start gap-3 rounded-xl bg-semantic-success-bg px-5 py-4 sm:flex-row sm:items-center">
          <CheckCircle2 size={22} className="shrink-0 text-semantic-success" />
          <div className="min-w-0 flex-1">
            <p className="text-sm font-semibold text-semantic-success">
              {t('validation.no_problems_title', { defaultValue: 'No problems found' })}
            </p>
            <p className="mt-0.5 text-sm text-content-secondary">
              {t('validation.no_problems_body', {
                defaultValue: 'All {{total}} checks passed. Nothing in this BOQ needs your attention.',
                total: totalChecks,
              })}
            </p>
          </div>
          {counts.passed > 0 && (
            <Button variant="secondary" size="sm" onClick={() => onFilterChange('passed')}>
              {t('validation.show_passed_checks', { defaultValue: 'Show passed checks' })} ({counts.passed})
            </Button>
          )}
        </div>
      ) : groups.length === 0 ? (
        <p className="py-8 text-center text-sm text-content-tertiary">
          {searchActive
            ? t('validation.search_no_match', { defaultValue: 'No findings match your search.' })
            : t('validation.no_results_for_filter', 'No results match this filter.')}
        </p>
      ) : (
        <div className="space-y-2">
          {groups.map((group) => (
            <RuleGroup
              key={`${filter}:${group.ruleId}`}
              group={group}
              expanded={isOpen(group.ruleId)}
              onToggle={() =>
                setToggled((prev) => ({ ...prev, [`${filter}:${group.ruleId}`]: !isOpen(group.ruleId) }))
              }
              scopeOf={scopeOf}
              boqId={boqId}
              hint={group.commonSuggestion ?? ruleHint(group.ruleId)}
              onRaiseNcr={onRaiseNcr}
            />
          ))}
        </div>
      )}
    </div>
  );
}
