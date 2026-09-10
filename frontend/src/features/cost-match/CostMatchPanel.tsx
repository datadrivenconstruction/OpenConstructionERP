// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Cost Match — pricing a foreign bill against a cost base you trust.
 *
 * The module is a two-pass workflow and the screen is arranged as one. The
 * machine passes first and never applies anything: every line comes back
 * pending whatever tier it landed in. The person passes second, and that pass
 * is the only thing that turns a suggestion into a price the project uses.
 *
 * So the queue leads. `Review queue` holds exactly the lines where the matcher
 * is *not* claiming an answer, which is the backend's own predicate rather than
 * a filter invented here; `All lines` is the record, including the ones already
 * ruled on. A run whose queue is empty still has confirming left to do, and the
 * counts strip says so rather than showing an encouraging green nothing.
 *
 * Three things the layout is deliberate about.
 *
 * A ruled line renders what the ruling adopted, never what the row still
 * suggests. After an override those two disagree, and `suggested_code` is the
 * item the reviewer explicitly refused - so `adoptedItem` is the only source
 * for that block.
 *
 * Reason codes are matcher vocabulary and never reach the DOM. `explanation`
 * and `hint` are the same information already rendered in the reader's
 * language, which is why every read passes `locale`.
 *
 * Confidence is shown as the backend banded it. Re-thresholding it here against
 * the platform's shared confidence cutoffs would repaint rows the scorer had
 * already answered, which is why `confidenceBand` reads cost-match's own two
 * constants and `ConfidenceBadge`'s `score` prop is not used.
 */

import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  AlertTriangle,
  Check,
  ClipboardCopy,
  ClipboardPaste,
  FileSearch,
  Layers,
  Lock,
  ListChecks,
  Replace,
  Search,
  ShieldCheck,
  Trash2,
  Unlock,
  X,
} from 'lucide-react';

import { Badge } from '@/shared/ui/Badge';
import { Button } from '@/shared/ui/Button';
import { ConfirmDialog } from '@/shared/ui/ConfirmDialog';
import { EmptyState } from '@/shared/ui/EmptyState';
import { getErrorMessage } from '@/shared/lib/api';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { useToastStore } from '@/stores/useToastStore';

import {
  type CostBaseItem,
  type CostMatchValidationReport,
  type DecisionKind,
  type DecisionStateFilter,
  type MatchCandidate,
  type MatchResult,
  type MatchRun,
  type TierFilter,
  MAX_BATCH_LINES,
  createRun,
  decideResult,
  deleteRun,
  listCostBaseRegions,
  listReviewQueue,
  listRunResults,
  listRuns,
  searchCostBase,
  updateRun,
  validateRun,
} from './api';
import {
  type BadgeTone,
  type DecisionState,
  type MatchTier,
  DECISION_STATE_ORDER,
  TIER_ORDER,
  adoptedItem,
  canConfirm,
  confidenceBand,
  confidencePercent,
  currentDecision,
  decisionStateOf,
  decisionTone,
  overrideOptions,
  parseBillLines,
  resultTier,
  tallyResults,
  tierTone,
} from './costMatchStatus';

const PAGE_SIZE = 50;

/* ── Vocabulary rendered in the reader's language ──────────────────────── */

/** Translator function as `useTranslation` hands it over. */
type Translate = (key: string, options?: Record<string, unknown>) => string;

/**
 * The tier names, as plain functions of `t`.
 *
 * Plain rather than hooks because they are also needed inside a `.map()` that
 * builds the filter options, and a hook may not be called from a callback.
 */
function tierLabelMap(t: Translate): Record<MatchTier, string> {
  return {
    exact: t('cost_match.tier_exact', { defaultValue: 'Exact' }),
    high_confidence: t('cost_match.tier_high_confidence', { defaultValue: 'Confident' }),
    needs_review: t('cost_match.tier_needs_review', { defaultValue: 'Needs review' }),
    unmatched: t('cost_match.tier_unmatched', { defaultValue: 'Nothing found' }),
  };
}

function decisionLabelMap(t: Translate): Record<DecisionState, string> {
  return {
    pending: t('cost_match.state_pending', { defaultValue: 'Not ruled on' }),
    confirmed: t('cost_match.state_confirmed', { defaultValue: 'Confirmed' }),
    overridden: t('cost_match.state_overridden', { defaultValue: 'Overridden' }),
    rejected: t('cost_match.state_rejected', { defaultValue: 'Rejected' }),
  };
}

function toneVariant(tone: BadgeTone): 'neutral' | 'blue' | 'success' | 'warning' | 'error' {
  return tone;
}

/* ── Small pieces ──────────────────────────────────────────────────────── */

/**
 * A rate with its currency, or an explicit dash.
 *
 * Rates stay strings from the wire to here on purpose, so this formats rather
 * than converts: a base really can carry a row with no usable rate, and a
 * blank cell there reads as a rate of nothing.
 */
function Rate({ value, currency }: { value: string | null; currency: string }) {
  const { t } = useTranslation();
  if (value === null || value === '') {
    return (
      <span className="text-content-tertiary" title={t('cost_match.no_rate_hint', {
        defaultValue: 'This row of the base carries no usable rate.',
      })}>
        {t('cost_match.no_rate', { defaultValue: 'no rate' })}
      </span>
    );
  }
  return (
    <span className="tabular-nums">
      {value} {currency}
    </span>
  );
}

function CountsStrip({ run }: { run: MatchRun }) {
  const { t } = useTranslation();
  const tierLabels = tierLabelMap(t);
  const decisionLabels = decisionLabelMap(t);
  const counts = run.counts;

  const cells: Array<{ label: string; value: number; tone: BadgeTone }> = [
    { label: tierLabels.exact, value: counts.exact, tone: 'success' },
    { label: tierLabels.high_confidence, value: counts.high_confidence, tone: 'blue' },
    { label: tierLabels.needs_review, value: counts.needs_review, tone: 'warning' },
    { label: tierLabels.unmatched, value: counts.unmatched, tone: 'neutral' },
  ];
  const rulings: Array<{ label: string; value: number; tone: BadgeTone }> = [
    { label: decisionLabels.pending, value: counts.pending, tone: 'warning' },
    { label: decisionLabels.confirmed, value: counts.confirmed, tone: 'success' },
    { label: decisionLabels.overridden, value: counts.overridden, tone: 'blue' },
    { label: decisionLabels.rejected, value: counts.rejected, tone: 'neutral' },
  ];

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="text-[11px] uppercase tracking-wide text-content-tertiary">
          {t('cost_match.counts_machine', { defaultValue: 'What the matcher found' })}
        </span>
        {cells.map((cell) => (
          <Badge key={cell.label} variant={toneVariant(cell.tone)} size="sm">
            {cell.label}: <span className="tabular-nums">{cell.value}</span>
          </Badge>
        ))}
      </div>
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="text-[11px] uppercase tracking-wide text-content-tertiary">
          {t('cost_match.counts_human', { defaultValue: 'What people ruled' })}
        </span>
        {rulings.map((cell) => (
          <Badge key={cell.label} variant={toneVariant(cell.tone)} size="sm">
            {cell.label}: <span className="tabular-nums">{cell.value}</span>
          </Badge>
        ))}
      </div>
      <p className="text-xs text-content-tertiary">
        {t('cost_match.counts_note', {
          defaultValue:
            'The queue is the lines the matcher is not claiming an answer for. Confident and exact lines are still proposals and still need confirming, so an empty queue is not an empty run.',
        })}
      </p>
    </div>
  );
}

/* ── Composing a run ───────────────────────────────────────────────────── */

interface ComposerProps {
  projectId: string;
  onClose: () => void;
  onCreated: (run: MatchRun) => void;
}

/**
 * Paste a bill, pin a base, submit.
 *
 * The paste is parsed here rather than server-side so the person sees what
 * their own separator did before anything is sent: how many lines it found,
 * how many quantities it could not read, and how many rows fall past the cap
 * the request itself cannot carry.
 */
function BillComposer({ projectId, onClose, onCreated }: ComposerProps) {
  const { t, i18n } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const queryClient = useQueryClient();

  const [name, setName] = useState('');
  const [sourceLabel, setSourceLabel] = useState('');
  const [text, setText] = useState('');
  const [costSource, setCostSource] = useState('');
  const [region, setRegion] = useState('');
  const [sourceLocale, setSourceLocale] = useState(i18n.language.split('-')[0]);

  const regionsQuery = useQuery({
    queryKey: ['cost-match', 'regions'],
    queryFn: listCostBaseRegions,
    staleTime: 5 * 60 * 1000,
  });

  const parsed = useMemo(() => parseBillLines(text, MAX_BATCH_LINES), [text]);

  const createMutation = useMutation({
    mutationFn: () =>
      createRun({
        project_id: projectId,
        name: name.trim() || undefined,
        source_label: sourceLabel.trim() || undefined,
        source_locale: sourceLocale || undefined,
        cost_source: costSource || undefined,
        region: region || null,
        lines: parsed.lines,
      }),
    onSuccess: (run) => {
      queryClient.invalidateQueries({ queryKey: ['cost-match', 'runs', projectId] });
      addToast({
        type: 'success',
        title: t('cost_match.run_created', { defaultValue: 'The bill was matched' }),
        message: t('cost_match.run_created_detail', {
          defaultValue: '{{count}} of {{total}} lines still need a person.',
          count: run.counts.queue_length,
          total: run.counts.total,
        }),
      });
      onCreated(run);
    },
    onError: (err) =>
      addToast({
        type: 'error',
        title: t('cost_match.run_create_failed', { defaultValue: 'The bill could not be matched' }),
        message: getErrorMessage(err),
      }),
  });

  const empty = parsed.lines.length === 0;

  return (
    <div className="rounded-lg border border-border bg-surface-primary p-4 space-y-3">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-medium text-content-primary">
            {t('cost_match.composer_title', { defaultValue: 'Match a bill' })}
          </h3>
          <p className="mt-0.5 text-xs text-content-tertiary">
            {t('cost_match.composer_intro', {
              defaultValue:
                'Paste the lines as they came. Columns separated by a tab, a semicolon or a pipe are read as description, unit, quantity and the sender’s own reference; a column pasted on its own is all description.',
            })}
          </p>
        </div>
        <Button variant="ghost" size="sm" icon={<X size={14} />} onClick={onClose}>
          {t('common.cancel', { defaultValue: 'Cancel' })}
        </Button>
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
        <label className="block">
          <span className="text-xs text-content-secondary">
            {t('cost_match.field_name', { defaultValue: 'Name this run' })}
          </span>
          <input
            className="mt-1 w-full rounded-md border border-border bg-surface-primary px-2 py-1.5 text-sm"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder={t('cost_match.field_name_placeholder', {
              defaultValue: 'Groundworks quote, revision B',
            })}
          />
        </label>
        <label className="block">
          <span className="text-xs text-content-secondary">
            {t('cost_match.field_source_label', { defaultValue: 'Where the bill came from' })}
          </span>
          <input
            className="mt-1 w-full rounded-md border border-border bg-surface-primary px-2 py-1.5 text-sm"
            value={sourceLabel}
            onChange={(e) => setSourceLabel(e.target.value)}
            placeholder={t('cost_match.field_source_label_placeholder', {
              defaultValue: 'The subcontractor or the document',
            })}
          />
        </label>
        <label className="block">
          <span className="text-xs text-content-secondary">
            {t('cost_match.field_cost_source', { defaultValue: 'Which cost base' })}
          </span>
          <input
            className="mt-1 w-full rounded-md border border-border bg-surface-primary px-2 py-1.5 text-sm"
            value={costSource}
            onChange={(e) => setCostSource(e.target.value)}
            placeholder={t('cost_match.field_cost_source_placeholder', {
              defaultValue: 'the platform default',
            })}
          />
          <span className="mt-0.5 block text-[11px] text-content-tertiary">
            {t('cost_match.field_cost_source_hint', {
              defaultValue:
                'The base is pinned to the run together with the region, so a line ruled on today cannot later refer to a catalogue that has moved on.',
            })}
          </span>
        </label>
        <label className="block">
          <span className="text-xs text-content-secondary">
            {t('cost_match.field_region', { defaultValue: 'Cost base region' })}
          </span>
          <select
            className="mt-1 w-full rounded-md border border-border bg-surface-primary px-2 py-1.5 text-sm"
            value={region}
            onChange={(e) => setRegion(e.target.value)}
          >
            <option value="">
              {t('cost_match.region_any', { defaultValue: 'Every region loaded' })}
            </option>
            {(regionsQuery.data ?? []).map((code) => (
              <option key={code} value={code}>
                {code}
              </option>
            ))}
          </select>
        </label>
        <label className="block">
          <span className="text-xs text-content-secondary">
            {t('cost_match.field_source_locale', { defaultValue: 'Language of the bill' })}
          </span>
          <input
            className="mt-1 w-full rounded-md border border-border bg-surface-primary px-2 py-1.5 text-sm"
            value={sourceLocale}
            onChange={(e) => setSourceLocale(e.target.value)}
          />
          <span className="mt-0.5 block text-[11px] text-content-tertiary">
            {t('cost_match.field_source_locale_hint', {
              defaultValue:
                'The language the descriptions are written in, which decides how they are scored. Not the language you are reading in.',
            })}
          </span>
        </label>
      </div>

      <label className="block">
        <span className="text-xs text-content-secondary">
          {t('cost_match.field_lines', { defaultValue: 'The bill' })}
        </span>
        <textarea
          className="mt-1 h-40 w-full rounded-md border border-border bg-surface-primary px-2 py-1.5 font-mono text-xs"
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder={t('cost_match.field_lines_placeholder', {
            defaultValue: 'Excavate to reduced level\tm3\t120\tA.01',
          })}
        />
      </label>

      <div className="flex flex-wrap items-center gap-2 text-xs">
        <Badge variant="neutral" size="sm">
          {t('cost_match.parsed_lines', {
            defaultValue: '{{count}} lines read',
            count: parsed.lines.length,
          })}
        </Badge>
        {parsed.unreadableQuantity > 0 && (
          <Badge variant="warning" size="sm">
            {t('cost_match.parsed_unreadable', {
              defaultValue: '{{count}} quantities could not be read',
              count: parsed.unreadableQuantity,
            })}
          </Badge>
        )}
        {parsed.overflow > 0 && (
          <Badge variant="error" size="sm">
            {t('cost_match.parsed_overflow', {
              defaultValue: '{{count}} lines past the limit of {{max}} and not sent',
              count: parsed.overflow,
              max: MAX_BATCH_LINES,
            })}
          </Badge>
        )}
      </div>
      {parsed.unreadableQuantity > 0 && (
        <p className="text-xs text-content-tertiary">
          {t('cost_match.parsed_unreadable_note', {
            defaultValue:
              'Those lines are kept and matched on their description. Only the quantity is dropped, because the batch is refused whole if one figure is not a quantity the schema accepts.',
          })}
        </p>
      )}

      <div className="flex justify-end gap-2">
        <Button
          variant="primary"
          size="sm"
          disabled={empty}
          loading={createMutation.isPending}
          icon={<Layers size={14} />}
          onClick={() => createMutation.mutate()}
        >
          {t('cost_match.submit_run', { defaultValue: 'Match these lines' })}
        </Button>
      </div>
    </div>
  );
}

/* ── Overriding onto an item the reviewer picks ────────────────────────── */

interface OverrideProps {
  run: MatchRun;
  result: MatchResult;
  onCancel: () => void;
  onPick: (item: { id: string; code: string; description: string }, note: string) => void;
  pending: boolean;
}

/**
 * Pick the item this line is really priced against.
 *
 * The runners-up come first because they are already scored against this line,
 * and the search is scoped to the run's own pinned base: the decision endpoint
 * accepts an active item of that exact base and answers 404 for anything else,
 * so offering a wider search would offer targets that cannot be chosen.
 */
function OverridePicker({ run, result, onCancel, onPick, pending }: OverrideProps) {
  const { t, i18n } = useTranslation();
  const [query, setQuery] = useState('');
  const [note, setNote] = useState('');
  const [submitted, setSubmitted] = useState('');

  const alternatives = useMemo(() => overrideOptions(result), [result]);

  const searchQuery = useQuery({
    queryKey: ['cost-match', 'base-search', run.id, submitted, i18n.language],
    queryFn: () =>
      searchCostBase({
        q: submitted,
        costSource: run.cost_source,
        region: run.region,
        catalogId: run.catalog_id,
        locale: i18n.language,
      }),
    enabled: submitted.trim().length > 1,
  });

  const rows: Array<{ id: string; code: string; description: string; unit: string; rate: string | null; currency: string; scored?: MatchCandidate }> = [];
  for (const candidate of alternatives) {
    if (!candidate.cost_item_id) continue;
    rows.push({
      id: candidate.cost_item_id,
      code: candidate.code,
      description: candidate.description,
      unit: candidate.unit,
      rate: candidate.rate,
      currency: candidate.currency,
      scored: candidate,
    });
  }
  const seen = new Set(rows.map((r) => r.id));
  for (const item of searchQuery.data?.items ?? ([] as CostBaseItem[])) {
    if (seen.has(item.id)) continue;
    rows.push({
      id: item.id,
      code: item.code,
      description: item.description,
      unit: item.unit,
      rate: item.rate === null || item.rate === undefined ? null : String(item.rate),
      currency: item.currency ?? '',
    });
  }

  return (
    <div className="mt-2 rounded-md border border-oe-blue/40 bg-oe-blue-subtle/30 p-3 space-y-2">
      <div className="flex items-center justify-between">
        <span className="text-xs font-medium text-content-primary">
          {t('cost_match.override_title', { defaultValue: 'Price this line against' })}
        </span>
        <Button variant="ghost" size="sm" onClick={onCancel}>
          {t('common.cancel', { defaultValue: 'Cancel' })}
        </Button>
      </div>

      <form
        className="flex gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          setSubmitted(query);
        }}
      >
        <input
          className="flex-1 rounded-md border border-border bg-surface-primary px-2 py-1.5 text-sm"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder={t('cost_match.override_search_placeholder', {
            defaultValue: 'Search the base this run is pinned to',
          })}
        />
        <Button type="submit" variant="secondary" size="sm" icon={<Search size={14} />}>
          {t('common.search', { defaultValue: 'Search' })}
        </Button>
      </form>

      <label className="block">
        <span className="text-xs text-content-secondary">
          {t('cost_match.override_note', { defaultValue: 'Why (kept with the ruling)' })}
        </span>
        <input
          className="mt-1 w-full rounded-md border border-border bg-surface-primary px-2 py-1.5 text-sm"
          value={note}
          onChange={(e) => setNote(e.target.value)}
        />
      </label>

      {rows.length === 0 ? (
        <p className="text-xs text-content-tertiary">
          {submitted.trim().length > 1
            ? t('cost_match.override_no_hits', {
                defaultValue: 'Nothing in this base matched that. Try fewer words.',
              })
            : t('cost_match.override_prompt', {
                defaultValue:
                  'The matcher offered no runner-up for this line. Search the base for the item it should be priced against.',
              })}
        </p>
      ) : (
        <ul className="max-h-64 space-y-1 overflow-y-auto">
          {rows.map((row) => (
            <li key={row.id}>
              <button
                type="button"
                disabled={pending}
                onClick={() => onPick({ id: row.id, code: row.code, description: row.description }, note)}
                className="w-full rounded-md border border-border bg-surface-primary px-2 py-1.5 text-left text-xs hover:bg-surface-secondary disabled:opacity-50"
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="font-mono text-content-secondary">{row.code}</span>
                  <span className="flex items-center gap-2">
                    {row.scored && (
                      <Badge variant={toneVariant(confidenceBand(row.scored.confidence) === 'high' ? 'blue' : 'neutral')} size="sm">
                        {t('cost_match.candidate_score', {
                          defaultValue: 'scored {{percent}}%',
                          percent: confidencePercent(row.scored.confidence),
                        })}
                      </Badge>
                    )}
                    <Rate value={row.rate} currency={row.currency} />
                  </span>
                </div>
                <div className="text-content-primary">{row.description}</div>
                {row.unit && <div className="text-content-tertiary">{row.unit}</div>}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/* ── One line ──────────────────────────────────────────────────────────── */

interface ResultRowProps {
  run: MatchRun;
  result: MatchResult;
  onDecide: (result: MatchResult, kind: DecisionKind, costItemId: string | null, note: string) => void;
  pendingId: string | null;
  locked: boolean;
}

function ResultRow({ run, result, onDecide, pendingId, locked }: ResultRowProps) {
  const { t } = useTranslation();
  const tierLabels = tierLabelMap(t);
  const decisionLabels = decisionLabelMap(t);
  const [overriding, setOverriding] = useState(false);

  const tier = resultTier(result);
  const state = decisionStateOf(result);
  const adopted = adoptedItem(result);
  const ruling = currentDecision(result);
  const busy = pendingId === result.id;

  return (
    <li className="rounded-lg border border-border bg-surface-primary p-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="text-[11px] tabular-nums text-content-tertiary">
              {result.line_no}
            </span>
            <span className="truncate text-sm text-content-primary">
              {result.source_description || (
                <span className="text-content-tertiary">
                  {t('cost_match.blank_description', { defaultValue: 'blank line in the bill' })}
                </span>
              )}
            </span>
          </div>
          <div className="mt-0.5 flex flex-wrap items-center gap-2 text-xs text-content-tertiary">
            {result.source_quantity && (
              <span className="tabular-nums">
                {result.source_quantity} {result.source_unit}
              </span>
            )}
            {!result.source_quantity && result.source_unit && <span>{result.source_unit}</span>}
            {result.source_ref && <span className="font-mono">{result.source_ref}</span>}
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          <Badge variant={toneVariant(tierTone(tier))} size="sm">
            {tierLabels[tier]}
          </Badge>
          {tier !== 'unmatched' && (
            <Badge variant="neutral" size="sm">
              {t('cost_match.confidence_percent', {
                defaultValue: '{{percent}}%',
                percent: confidencePercent(result.confidence),
              })}
            </Badge>
          )}
          <Badge variant={toneVariant(decisionTone(state))} size="sm">
            {decisionLabels[state]}
          </Badge>
        </div>
      </div>

      {result.tie && (
        <p className="mt-1.5 flex items-start gap-1 text-xs text-[#b45309]">
          <AlertTriangle size={12} className="mt-0.5 shrink-0" />
          {t('cost_match.tie_note', {
            defaultValue:
              'A second item scored exactly the same. The winner was picked by input order, which is not a judgement about which one is right.',
          })}
        </p>
      )}

      {/* What the machine proposed, or why it proposed nothing. */}
      {result.suggested_cost_item_id ? (
        <div className="mt-2 rounded-md bg-surface-secondary p-2">
          <div className="flex items-center justify-between gap-2 text-xs">
            <span className="font-mono text-content-secondary">{result.suggested_code}</span>
            <Rate value={result.suggested_rate} currency={result.suggested_currency} />
          </div>
          <div className="text-sm text-content-primary">{result.suggested_description}</div>
          {result.suggested_unit && (
            <div className="text-xs text-content-tertiary">{result.suggested_unit}</div>
          )}
          {result.explanation && (
            <p className="mt-1 text-xs text-content-tertiary">{result.explanation}</p>
          )}
        </div>
      ) : (
        <p className="mt-2 text-xs text-content-tertiary">
          {result.hint ||
            t('cost_match.no_candidate', {
              defaultValue: 'Nothing in this base was close enough to offer.',
            })}
        </p>
      )}

      {/* What the project actually took. Never the suggestion once ruled. */}
      {adopted && (
        <div className="mt-2 rounded-md border border-semantic-success/40 bg-semantic-success-bg/40 p-2">
          <div className="flex items-center justify-between gap-2 text-xs">
            <span className="flex items-center gap-1 font-medium text-content-primary">
              <Check size={12} />
              {t('cost_match.adopted_title', { defaultValue: 'Priced against' })}
            </span>
            <Rate value={adopted.rate} currency={adopted.currency} />
          </div>
          <div className="mt-0.5 text-xs">
            <span className="font-mono text-content-secondary">{adopted.code}</span>{' '}
            <span className="text-content-primary">{adopted.description}</span>
          </div>
        </div>
      )}
      {state === 'rejected' && (
        <p className="mt-2 text-xs text-content-tertiary">
          {t('cost_match.rejected_note', {
            defaultValue: 'Ruled that nothing in this base fits this line.',
          })}
        </p>
      )}
      {ruling?.note && (
        <p className="mt-1 text-xs italic text-content-tertiary">{ruling.note}</p>
      )}

      {/* The human pass. */}
      {!locked && (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {canConfirm(result) && (
            <Button
              variant="secondary"
              size="sm"
              disabled={busy}
              icon={<Check size={13} />}
              onClick={() => onDecide(result, 'confirmed', null, '')}
            >
              {t('cost_match.action_confirm', { defaultValue: 'Confirm' })}
            </Button>
          )}
          <Button
            variant="secondary"
            size="sm"
            disabled={busy}
            icon={<Replace size={13} />}
            onClick={() => setOverriding((open) => !open)}
          >
            {t('cost_match.action_override', { defaultValue: 'Price against something else' })}
          </Button>
          <Button
            variant="ghost"
            size="sm"
            disabled={busy}
            icon={<X size={13} />}
            onClick={() => onDecide(result, 'rejected', null, '')}
          >
            {t('cost_match.action_reject', { defaultValue: 'Nothing here fits' })}
          </Button>
        </div>
      )}

      {overriding && !locked && (
        <OverridePicker
          run={run}
          result={result}
          pending={busy}
          onCancel={() => setOverriding(false)}
          onPick={(item, note) => {
            onDecide(result, 'overridden', item.id, note);
            setOverriding(false);
          }}
        />
      )}
    </li>
  );
}

/* ── The panel ─────────────────────────────────────────────────────────── */

export function CostMatchPanel() {
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const activeProjectId = useProjectContextStore((s) => s.activeProjectId);
  const tierLabels = tierLabelMap(t);
  const decisionLabels = decisionLabelMap(t);

  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [composing, setComposing] = useState(false);
  const [tab, setTab] = useState<'queue' | 'all'>('queue');
  const [tierFilter, setTierFilter] = useState<TierFilter | ''>('');
  const [stateFilter, setStateFilter] = useState<DecisionStateFilter | ''>('');
  const [decidingId, setDecidingId] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [report, setReport] = useState<CostMatchValidationReport | null>(null);
  const [batchProgress, setBatchProgress] = useState<{ done: number; total: number } | null>(null);

  const runsQuery = useQuery({
    queryKey: ['cost-match', 'runs', activeProjectId],
    queryFn: () => listRuns({ projectId: activeProjectId as string, limit: 50 }),
    enabled: !!activeProjectId,
  });

  const runs = runsQuery.data ?? [];
  const selectedRun = runs.find((run) => run.id === selectedRunId) ?? runs[0] ?? null;
  const runId = selectedRun?.id ?? null;
  const locked = selectedRun?.status === 'closed';

  const resultsQuery = useQuery({
    queryKey: ['cost-match', 'results', runId, tab, tierFilter, stateFilter, i18n.language],
    queryFn: () =>
      tab === 'queue'
        ? listReviewQueue(runId as string, { locale: i18n.language, limit: PAGE_SIZE })
        : listRunResults(runId as string, {
            tier: tierFilter || undefined,
            decisionState: stateFilter || undefined,
            locale: i18n.language,
            limit: PAGE_SIZE,
          }),
    enabled: !!runId,
  });

  const results = useMemo(() => resultsQuery.data?.items ?? [], [resultsQuery.data]);
  const shownTally = useMemo(() => tallyResults(results), [results]);

  const decideMutation = useMutation({
    mutationFn: (args: { result: MatchResult; kind: DecisionKind; costItemId: string | null; note: string }) =>
      decideResult(args.result.id, {
        decision: args.kind,
        cost_item_id: args.kind === 'overridden' ? args.costItemId : null,
        note: args.note.trim() || null,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['cost-match', 'results'] });
      queryClient.invalidateQueries({ queryKey: ['cost-match', 'runs', activeProjectId] });
    },
    onError: (err) =>
      addToast({
        type: 'error',
        title: t('cost_match.decision_failed', { defaultValue: 'The ruling was not recorded' }),
        message: getErrorMessage(err),
      }),
    onSettled: () => setDecidingId(null),
  });

  const validateMutation = useMutation({
    mutationFn: () => validateRun(runId as string, i18n.language),
    onSuccess: (data) => setReport(data),
    onError: (err) =>
      addToast({
        type: 'error',
        title: t('cost_match.validate_failed', { defaultValue: 'The run could not be checked' }),
        message: getErrorMessage(err),
      }),
  });

  const lockMutation = useMutation({
    mutationFn: (status: 'matched' | 'closed') => updateRun(runId as string, { status }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['cost-match', 'runs', activeProjectId] }),
    onError: (err) =>
      addToast({
        type: 'error',
        title: t('cost_match.lock_failed', { defaultValue: 'The run was not changed' }),
        message: getErrorMessage(err),
      }),
  });

  const deleteMutation = useMutation({
    mutationFn: () => deleteRun(runId as string),
    onSuccess: () => {
      setSelectedRunId(null);
      setConfirmDelete(false);
      queryClient.invalidateQueries({ queryKey: ['cost-match', 'runs', activeProjectId] });
    },
    onError: (err) => {
      setConfirmDelete(false);
      addToast({
        type: 'error',
        title: t('cost_match.delete_failed', { defaultValue: 'The run was not deleted' }),
        message: getErrorMessage(err),
      });
    },
  });

  const handleDecide = (
    result: MatchResult,
    kind: DecisionKind,
    costItemId: string | null,
    note: string,
  ) => {
    setDecidingId(result.id);
    decideMutation.mutate({ result, kind, costItemId, note });
  };

  const confirmableResults = useMemo(
    () => results.filter((r) => canConfirm(r) && decisionStateOf(r) === 'pending'),
    [results],
  );

  const batchConfirm = useMutation({
    mutationFn: async () => {
      const targets = confirmableResults;
      setBatchProgress({ done: 0, total: targets.length });
      for (let i = 0; i < targets.length; i++) {
        const target = targets[i];
        if (target) {
          await decideResult(target.id, { decision: 'confirmed' });
          setBatchProgress({ done: i + 1, total: targets.length });
        }
      }
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['cost-match', 'results'] });
      queryClient.invalidateQueries({ queryKey: ['cost-match', 'runs', activeProjectId] });
      addToast({
        type: 'success',
        title: t('cost_match.batch_confirmed', { defaultValue: 'Batch confirmed' }),
        message: t('cost_match.batch_confirmed_detail', {
          defaultValue: '{{count}} lines confirmed in one pass.',
          count: confirmableResults.length,
        }),
      });
    },
    onError: (err) =>
      addToast({
        type: 'error',
        title: t('cost_match.batch_failed', { defaultValue: 'Some confirmations did not go through' }),
        message: getErrorMessage(err),
      }),
    onSettled: () => setBatchProgress(null),
  });

  /* Every hook is above this line; the guards start here. */

  if (!activeProjectId) {
    return (
      <EmptyState
        icon={<Layers size={28} />}
        title={t('cost_match.no_project', { defaultValue: 'Pick a project first' })}
        description={t('cost_match.no_project_hint', {
          defaultValue:
            'A run is matched against one project’s cost base and belongs to that project.',
        })}
      />
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-base font-medium text-content-primary">
          {t('cost_match.runs_title', { defaultValue: 'Matched bills' })}
        </h2>
        {!composing && (
          <Button
            variant="primary"
            size="sm"
            icon={<ClipboardPaste size={14} />}
            onClick={() => setComposing(true)}
          >
            {t('cost_match.new_run', { defaultValue: 'Match a bill' })}
          </Button>
        )}
      </div>

      {composing && (
        <BillComposer
          projectId={activeProjectId}
          onClose={() => setComposing(false)}
          onCreated={(run) => {
            setComposing(false);
            setSelectedRunId(run.id);
            setTab('queue');
          }}
        />
      )}

      {runsQuery.isLoading && (
        <p className="text-sm text-content-tertiary">
          {t('common.loading', { defaultValue: 'Loading...' })}
        </p>
      )}

      {!runsQuery.isLoading && runs.length === 0 && !composing && (
        <EmptyState
          icon={<Layers size={28} />}
          title={t('cost_match.empty_title', { defaultValue: 'No bill has been matched yet' })}
          description={t('cost_match.empty_description', {
            defaultValue:
              'Paste a subcontractor’s bill and it is scored line by line against your cost base. Nothing is applied: every line waits for a person.',
          })}
          action={{
            label: t('cost_match.new_run', { defaultValue: 'Match a bill' }),
            onClick: () => setComposing(true),
          }}
        />
      )}

      {runs.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {runs.map((run) => (
            <button
              key={run.id}
              type="button"
              onClick={() => {
                setSelectedRunId(run.id);
                setReport(null);
              }}
              className={
                'rounded-md border px-2.5 py-1.5 text-left text-xs ' +
                (run.id === runId
                  ? 'border-oe-blue bg-oe-blue-subtle text-oe-blue-text'
                  : 'border-border bg-surface-primary text-content-secondary hover:bg-surface-secondary')
              }
            >
              <span className="block font-medium">{run.name}</span>
              <span className="block text-content-tertiary">
                {t('cost_match.run_summary', {
                  defaultValue: '{{queue}} of {{total}} still need a person',
                  queue: run.counts.queue_length,
                  total: run.counts.total,
                })}
              </span>
            </button>
          ))}
        </div>
      )}

      {selectedRun && (
        <div className="space-y-3 rounded-lg border border-border bg-surface-primary p-4">
          <div className="flex flex-wrap items-start justify-between gap-2">
            <div>
              <h3 className="text-sm font-medium text-content-primary">{selectedRun.name}</h3>
              <p className="mt-0.5 text-xs text-content-tertiary">
                {t('cost_match.run_base', {
                  defaultValue: 'Matched against {{source}}{{region}} in {{locale}}',
                  source: selectedRun.cost_source,
                  region: selectedRun.region ? `, ${selectedRun.region}` : '',
                  locale: selectedRun.source_locale,
                })}
              </p>
              {selectedRun.source_label && (
                <p className="text-xs text-content-tertiary">{selectedRun.source_label}</p>
              )}
            </div>
            <div className="flex flex-wrap gap-1.5">
              <Button
                variant="secondary"
                size="sm"
                icon={<ShieldCheck size={13} />}
                loading={validateMutation.isPending}
                onClick={() => validateMutation.mutate()}
              >
                {t('cost_match.action_validate', { defaultValue: 'Check this run' })}
              </Button>
              <Button
                variant="secondary"
                size="sm"
                icon={locked ? <Unlock size={13} /> : <Lock size={13} />}
                loading={lockMutation.isPending}
                onClick={() => lockMutation.mutate(locked ? 'matched' : 'closed')}
              >
                {locked
                  ? t('cost_match.action_reopen', { defaultValue: 'Re-open for review' })
                  : t('cost_match.action_close', { defaultValue: 'Close review' })}
              </Button>
              <Button
                variant="ghost"
                size="sm"
                icon={<Trash2 size={13} />}
                onClick={() => setConfirmDelete(true)}
              >
                {t('common.delete', { defaultValue: 'Delete' })}
              </Button>
            </div>
          </div>

          {locked && (
            <p className="flex items-center gap-1.5 rounded-md bg-surface-secondary px-2 py-1.5 text-xs text-content-secondary">
              <Lock size={12} />
              {t('cost_match.closed_note', {
                defaultValue:
                  'This run is closed and takes no further rulings. Re-open it to change one.',
              })}
            </p>
          )}

          <CountsStrip run={selectedRun} />

          {confirmableResults.length > 0 && !locked && (
            <div className="flex items-center gap-2">
              <Button
                variant="secondary"
                size="sm"
                icon={<ListChecks size={13} />}
                loading={batchConfirm.isPending}
                onClick={() => batchConfirm.mutate()}
              >
                {batchProgress
                  ? t('cost_match.batch_progress', {
                      defaultValue: 'Confirming {{done}} / {{total}}...',
                      done: batchProgress.done,
                      total: batchProgress.total,
                    })
                  : t('cost_match.batch_confirm', {
                      defaultValue: 'Confirm all {{count}} suggested on this page',
                      count: confirmableResults.length,
                    })}
              </Button>
            </div>
          )}

          {report && (
            <div className="rounded-md border border-border bg-surface-secondary p-3">
              <div className="flex items-center justify-between">
                <span className="flex items-center gap-1.5 text-xs font-medium text-content-primary">
                  <ShieldCheck size={13} />
                  {t('cost_match.report_title', { defaultValue: 'What the check found' })}
                </span>
                <Button variant="ghost" size="sm" onClick={() => setReport(null)}>
                  {t('common.close', { defaultValue: 'Close' })}
                </Button>
              </div>
              <div className="mt-1.5 flex flex-wrap gap-1.5">
                <Badge variant="error" size="sm">
                  {t('cost_match.report_errors', {
                    defaultValue: '{{count}} errors',
                    count: report.error_count,
                  })}
                </Badge>
                <Badge variant="warning" size="sm">
                  {t('cost_match.report_warnings', {
                    defaultValue: '{{count}} warnings',
                    count: report.warning_count,
                  })}
                </Badge>
                <Badge variant="success" size="sm">
                  {t('cost_match.report_passed', {
                    defaultValue: '{{count}} passed',
                    count: report.passed_count,
                  })}
                </Badge>
              </div>
              {report.findings.length > 0 && (
                <ul className="mt-2 space-y-1">
                  {report.findings.slice(0, 20).map((finding, index) => (
                    <li key={`${finding.rule_id}-${index}`} className="text-xs">
                      <span className="font-mono text-content-tertiary">{finding.rule_id}</span>{' '}
                      <span className="text-content-primary">{finding.message}</span>
                      {finding.suggestion && (
                        <span className="block text-content-tertiary">{finding.suggestion}</span>
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}

          {/* Tabs. The queue is the work; all lines is the record. */}
          <div className="flex gap-1 border-b border-border">
            <button
              type="button"
              onClick={() => setTab('queue')}
              className={
                'flex items-center gap-1.5 px-3 py-1.5 text-xs ' +
                (tab === 'queue'
                  ? 'border-b-2 border-oe-blue text-oe-blue-text'
                  : 'text-content-secondary hover:text-content-primary')
              }
            >
              <ListChecks size={13} />
              {t('cost_match.tab_queue', { defaultValue: 'Waiting for a person' })}
              <span className="tabular-nums">({selectedRun.counts.queue_length})</span>
            </button>
            <button
              type="button"
              onClick={() => setTab('all')}
              className={
                'flex items-center gap-1.5 px-3 py-1.5 text-xs ' +
                (tab === 'all'
                  ? 'border-b-2 border-oe-blue text-oe-blue-text'
                  : 'text-content-secondary hover:text-content-primary')
              }
            >
              <FileSearch size={13} />
              {t('cost_match.tab_all', { defaultValue: 'Every line' })}
              <span className="tabular-nums">({selectedRun.counts.total})</span>
            </button>
          </div>

          {tab === 'all' && (
            <div className="flex flex-wrap gap-2">
              <select
                className="rounded-md border border-border bg-surface-primary px-2 py-1 text-xs"
                value={tierFilter}
                onChange={(e) => setTierFilter(e.target.value as TierFilter | '')}
              >
                <option value="">
                  {t('cost_match.filter_tier_any', { defaultValue: 'Any tier' })}
                </option>
                {TIER_ORDER.map((tier) => (
                  <option key={tier} value={tier}>
                    {tierLabels[tier]}
                  </option>
                ))}
              </select>
              <select
                className="rounded-md border border-border bg-surface-primary px-2 py-1 text-xs"
                value={stateFilter}
                onChange={(e) => setStateFilter(e.target.value as DecisionStateFilter | '')}
              >
                <option value="">
                  {t('cost_match.filter_state_any', { defaultValue: 'Any ruling' })}
                </option>
                {DECISION_STATE_ORDER.map((state) => (
                  <option key={state} value={state}>
                    {decisionLabels[state]}
                  </option>
                ))}
              </select>
            </div>
          )}

          {results.length > 0 && (
            <div className="flex justify-end">
              <Button
                variant="ghost"
                size="sm"
                icon={<ClipboardCopy size={13} />}
                onClick={() => {
                  const header = ['Line', 'Description', 'Qty', 'Unit', 'Ref', 'Tier', 'Status', 'Matched code', 'Matched rate', 'Currency'].join('\t');
                  const rows = results.map((r) => {
                    const adopted2 = adoptedItem(r);
                    return [
                      r.line_no,
                      r.source_description || '',
                      r.source_quantity || '',
                      r.source_unit || '',
                      r.source_ref || '',
                      resultTier(r),
                      decisionStateOf(r),
                      adopted2?.code || r.suggested_code || '',
                      adopted2?.rate || r.suggested_rate || '',
                      adopted2?.currency || r.suggested_currency || '',
                    ].join('\t');
                  });
                  navigator.clipboard.writeText([header, ...rows].join('\n'));
                  addToast({
                    type: 'success',
                    title: t('cost_match.copied', { defaultValue: 'Copied to clipboard' }),
                    message: t('cost_match.copied_detail', {
                      defaultValue: '{{count}} lines ready to paste into a spreadsheet.',
                      count: results.length,
                    }),
                  });
                }}
              >
                {t('cost_match.copy_results', { defaultValue: 'Copy to clipboard' })}
              </Button>
            </div>
          )}

          {resultsQuery.isLoading && (
            <p className="text-sm text-content-tertiary">
              {t('common.loading', { defaultValue: 'Loading...' })}
            </p>
          )}

          {!resultsQuery.isLoading && results.length === 0 && (
            <p className="rounded-md bg-surface-secondary px-3 py-4 text-center text-xs text-content-tertiary">
              {tab === 'queue'
                ? t('cost_match.queue_clear', {
                    defaultValue:
                      'Nothing here is waiting on a person. Confident and exact lines are under "Every line" and still need confirming.',
                  })
                : t('cost_match.no_lines_match', {
                    defaultValue: 'No line in this run matches that filter.',
                  })}
            </p>
          )}

          {results.length > 0 && (
            <>
              <ul className="space-y-2">
                {results.map((result) => (
                  <ResultRow
                    key={result.id}
                    run={selectedRun}
                    result={result}
                    onDecide={handleDecide}
                    pendingId={decidingId}
                    locked={locked}
                  />
                ))}
              </ul>
              <p className="text-xs text-content-tertiary">
                {t('cost_match.page_note', {
                  defaultValue:
                    'Showing {{shown}} of {{total}}, {{queue}} of them still waiting on a person.',
                  shown: results.length,
                  total: resultsQuery.data?.total ?? results.length,
                  queue: shownTally.queueLength,
                })}
              </p>
            </>
          )}
        </div>
      )}

      <ConfirmDialog
        open={confirmDelete}
        onCancel={() => setConfirmDelete(false)}
        onConfirm={() => deleteMutation.mutate()}
        title={t('cost_match.delete_title', { defaultValue: 'Delete this run?' })}
        message={t('cost_match.delete_message', {
          defaultValue:
            'The matched lines go with it, and so does every ruling anybody made on them. That history is not kept anywhere else.',
        })}
        confirmLabel={t('common.delete', { defaultValue: 'Delete' })}
        variant="danger"
      />
    </div>
  );
}

