// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The small marks of the submittal register: the reviewer's code, the
 * discipline, the review clock, the approval deadline and the long-lead flag.
 *
 * Each one prints a value the server sent. Days in review, days overdue and
 * days past the approval deadline are measured by the server against the
 * contract's review period and the item's lead time; nothing here subtracts
 * two dates, so the screen and the printed register cannot disagree.
 */
import { useTranslation } from 'react-i18next';
import clsx from 'clsx';
import { AlertTriangle, ArrowDown, ArrowUp, Hourglass, Truck } from 'lucide-react';

import { Badge, DateDisplay } from '@/shared/ui';
import type { Submittal, SubmittalVocabulary } from './api';
import { DaysInCourtBadge } from './DaysInCourtBadge';
import { disciplineLabel, disciplineMark, humaniseCode, type RegisterSort } from './registerView';

type Translate = ReturnType<typeof useTranslation>['t'];

/**
 * A review outcome as a word. The four decisions are also workflow statuses,
 * so they read with the same words as the status badge on the row.
 */
export function outcomeLabel(t: Translate, outcome: string): string {
  switch (outcome) {
    case 'approved':
      return t('submittals.status_approved', { defaultValue: 'Approved' });
    case 'approved_as_noted':
      return t('submittals.status_approved_as_noted', { defaultValue: 'Approved as Noted' });
    case 'revise_and_resubmit':
      return t('submittals.status_revise_and_resubmit', { defaultValue: 'Revise & Resubmit' });
    case 'rejected':
      return t('submittals.status_rejected', { defaultValue: 'Rejected' });
    default:
      return humaniseCode(outcome);
  }
}

/**
 * What an outcome means for buying the item, in one line. `null` for a code
 * outside the four decisions: there is nothing true to say about it.
 */
export function outcomeHint(t: Translate, outcome: string): string | null {
  switch (outcome) {
    case 'approved':
      return t('submittals.outcome_hint_approved', {
        defaultValue: 'Released: order and install as submitted.',
      });
    case 'approved_as_noted':
      return t('submittals.outcome_hint_approved_as_noted', {
        defaultValue: "Released: order and install, with the reviewer's notes taken into account.",
      });
    case 'revise_and_resubmit':
      return t('submittals.outcome_hint_revise_and_resubmit', {
        defaultValue: 'Not released: do not order. Correct it and send in a new revision.',
      });
    case 'rejected':
      return t('submittals.outcome_hint_rejected', {
        defaultValue: 'Not released: do not order. A different proposal is needed.',
      });
    default:
      return null;
  }
}

const OUTCOME_TONE: Record<string, string> = {
  approved: 'bg-emerald-100 text-emerald-800 border-emerald-300 dark:bg-emerald-900/30 dark:text-emerald-300 dark:border-emerald-800',
  approved_as_noted: 'bg-amber-100 text-amber-800 border-amber-300 dark:bg-amber-900/30 dark:text-amber-300 dark:border-amber-800',
  revise_and_resubmit: 'bg-orange-100 text-orange-800 border-orange-300 dark:bg-orange-900/30 dark:text-orange-300 dark:border-orange-800',
  rejected: 'bg-red-100 text-red-800 border-red-300 dark:bg-red-900/30 dark:text-red-300 dark:border-red-800',
};
const NEUTRAL_TONE = 'bg-surface-secondary text-content-secondary border-border';

/**
 * The mark the reviewer stamped, coloured by the decision it stands for.
 *
 * The colour follows the outcome, not the letter: a project whose reviewer
 * stamps "2" for approved as noted still gets the amber chip. The tooltip
 * spells out the decision and what it means for ordering.
 */
export function ReviewCodeChip({
  code,
  outcome,
  className,
}: {
  code: string | null;
  outcome: string | null;
  className?: string;
}) {
  const { t } = useTranslation();
  if (!code) return null;
  const label = outcome ? outcomeLabel(t, outcome) : '';
  const hint = outcome ? outcomeHint(t, outcome) : null;
  const title = [label, hint].filter(Boolean).join('. ');
  return (
    <span
      title={title || undefined}
      aria-label={t('submittals.review_code_aria', {
        defaultValue: 'Review code {{code}}: {{outcome}}',
        code,
        outcome: label,
      })}
      className={clsx(
        'inline-flex h-5 min-w-5 items-center justify-center rounded border px-1 text-2xs font-bold tabular-nums',
        (outcome && OUTCOME_TONE[outcome]) || NEUTRAL_TONE,
        className,
      )}
    >
      {code}
    </span>
  );
}

/** The discipline as its short mark, with the full word in the tooltip. */
export function DisciplineBadge({
  discipline,
  vocabulary,
}: {
  discipline: string | null;
  vocabulary: SubmittalVocabulary | null;
}) {
  if (!discipline) return null;
  return (
    <span
      title={disciplineLabel(vocabulary, discipline)}
      className="inline-flex h-5 items-center rounded bg-surface-secondary px-1.5 text-2xs font-semibold text-content-secondary"
    >
      {disciplineMark(vocabulary, discipline)}
    </span>
  );
}

/**
 * How long the current revision has been with the reviewer, and whether that
 * is past the contract's review period.
 *
 * A row with a review period reads from the server's two figures and turns
 * red only when the server says the period has run out. A row without one
 * (every row from before the period could be recorded) keeps the badge the
 * register always showed, fed the server's day count when there is one.
 */
export function ReviewClock({ submittal }: { submittal: Submittal }) {
  const { t } = useTranslation();
  const days = submittal.days_in_review;
  const over = submittal.review_overdue_days;

  if (over === null || days === null) {
    return <DaysInCourtBadge dateSubmitted={submittal.date_submitted} status={submittal.status} days={days} />;
  }

  const late = over > 0;
  const title = late
    ? t('submittals.review_clock_overdue', {
        defaultValue: '{{days}} d in review, {{over}} d past the review period',
        days,
        over,
      })
    : t('submittals.review_clock', { defaultValue: '{{days}} d in review, inside the review period', days });
  return (
    <span title={title} data-testid={`review-clock-${submittal.id}`}>
      <Badge variant={late ? 'error' : 'neutral'} size="sm">
        <Hourglass size={10} className="me-1 inline-block" aria-hidden />
        {t('submittals.days_short', { defaultValue: '{{days}} d', days })}
        {late && (
          <span className="ms-1 font-bold">
            +{over}
          </span>
        )}
        <span className="sr-only">{title}</span>
      </Badge>
    </span>
  );
}

/**
 * The last day an approval still lets the item arrive when the site needs it
 * (required on site less the lead time), and how far past it the item is.
 *
 * A long-lead item with no such date gets a warning mark instead of an empty
 * cell: the deadline cannot be worked out, which is not the same as there
 * being none.
 */
export function ApprovalNeededBy({ submittal }: { submittal: Submittal }) {
  const { t } = useTranslation();
  const lateDays = submittal.approval_late_days ?? 0;

  if (!submittal.approval_needed_by) {
    if (!submittal.long_lead || submittal.may_proceed) return null;
    const reason = t('submittals.needed_by_unknown', {
      defaultValue:
        'Long-lead item without a lead time or a required-on-site date: the date its approval is needed by cannot be worked out.',
    });
    return (
      <span title={reason} className="inline-flex text-amber-600 dark:text-amber-400">
        <AlertTriangle size={13} aria-hidden />
        <span className="sr-only">{reason}</span>
      </span>
    );
  }

  return (
    <>
      <DateDisplay
        value={submittal.approval_needed_by}
        className={clsx('text-xs', lateDays > 0 ? 'font-medium text-semantic-error' : 'text-content-tertiary')}
      />
      {lateDays > 0 && (
        <Badge variant="error" size="sm">
          {t('submittals.days_late', { defaultValue: '{{days}} d late', days: lateDays })}
        </Badge>
      )}
    </>
  );
}

/** The long-lead flag beside a title, with the lead time when it is recorded. */
export function LongLeadMark({ submittal }: { submittal: Submittal }) {
  const { t } = useTranslation();
  if (!submittal.long_lead) return null;
  const title =
    submittal.lead_time_weeks === null
      ? t('submittals.long_lead_title', { defaultValue: 'Long-lead item' })
      : t('submittals.long_lead_weeks', {
          defaultValue: 'Long-lead item, {{weeks}} wk lead time',
          weeks: submittal.lead_time_weeks,
        });
  return (
    <span title={title} className="inline-flex shrink-0 text-amber-600 dark:text-amber-400">
      <Truck size={13} aria-hidden />
      <span className="sr-only">{title}</span>
    </span>
  );
}

/**
 * What each review code means for ordering, one line per code.
 *
 * The letters are the ones the vocabulary serves as defaults. A reviewer may
 * stamp other marks, which is why the legend is keyed by the decision and
 * says so underneath.
 */
export function OutcomeLegend({ vocabulary }: { vocabulary: SubmittalVocabulary | null }) {
  const { t } = useTranslation();
  const outcomes = vocabulary?.outcomes ?? [];
  if (outcomes.length === 0) return null;
  return (
    <div data-testid="submittals-outcome-legend" className="rounded-lg border border-border-light bg-surface-secondary/40 p-3">
      <ul className="space-y-1.5">
        {outcomes.map((entry) => (
          <li key={entry.code} className="flex items-start gap-2 text-xs">
            <ReviewCodeChip code={entry.short_code ?? entry.code} outcome={entry.code} className="mt-px shrink-0" />
            <span className="text-content-secondary">
              <span className="font-medium text-content-primary">{outcomeLabel(t, entry.code)}</span>
              {outcomeHint(t, entry.code) ? <> - {outcomeHint(t, entry.code)}</> : null}
            </span>
          </li>
        ))}
      </ul>
      <p className="mt-2 text-2xs text-content-tertiary">
        {t('submittals.outcome_legend_note', {
          defaultValue:
            'The letters are the default marks. When a reviewer stamps another mark, the register shows it as stamped, in the colour of the decision.',
        })}
      </p>
    </div>
  );
}

/**
 * A column heading that orders the list when the server can order by it.
 *
 * Pressing it goes ascending, then descending, then back to the register's
 * own order. A column the server does not list as sortable is a plain
 * heading.
 */
export function SortableHeader({
  label,
  field,
  sortable,
  sort,
  onSort,
  className,
}: {
  label: string;
  field: string;
  sortable: boolean;
  sort: RegisterSort | null;
  onSort: (next: RegisterSort | null) => void;
  className?: string;
}) {
  const { t } = useTranslation();
  if (!sortable) return <span className={className}>{label}</span>;
  const order = sort?.field === field ? sort.order : null;
  const next: RegisterSort | null =
    order === null ? { field, order: 'asc' } : order === 'asc' ? { field, order: 'desc' } : null;
  return (
    <span className={className}>
      <button
        type="button"
        data-testid={`submittals-sort-${field}`}
        aria-label={t('submittals.sort_by', { defaultValue: 'Sort by {{column}}', column: label })}
        aria-pressed={order !== null}
        onClick={() => onSort(next)}
        className={clsx(
          'inline-flex max-w-full items-center gap-0.5 uppercase tracking-wider hover:text-content-primary',
          order !== null && 'text-content-primary',
        )}
      >
        <span className="truncate">{label}</span>
        {order === 'asc' && <ArrowUp size={11} aria-hidden />}
        {order === 'desc' && <ArrowDown size={11} aria-hidden />}
      </button>
    </span>
  );
}
