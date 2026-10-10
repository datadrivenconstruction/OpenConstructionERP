// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The strip above the submittal register: the counts of the summary route,
 * each one a way into the rows behind it.
 *
 * It answers the three things a document controller opens the register for:
 * what is with the reviewer and how much of it is past the review period,
 * what came back and was not released, and which long-lead items are running
 * out of time. Every number is the server's, counted over the whole project
 * as of today, so pressing a card always opens that exact cut on its own:
 * the other filters are cleared first, otherwise the list under it could be
 * shorter than the number that was pressed.
 */
import { useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import clsx from 'clsx';
import { CircleHelp } from 'lucide-react';

import type { SubmittalRegisterSummary as Summary, SubmittalVocabulary } from './api';
import { OutcomeLegend, ReviewCodeChip, outcomeHint, outcomeLabel } from './registerCells';
import {
  NO_FILTERS,
  disciplineLabel,
  disciplineMark,
  hasActiveFilter,
  sameFilters,
  type RegisterFilters,
} from './registerView';

const cardCls =
  'rounded-xl border bg-surface-elevated/90 p-4 shadow-xs transition-shadow duration-normal ease-oe hover:shadow-sm animate-card-in';
const chipCls =
  'inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/40';

function Card({
  testId,
  label,
  value,
  tone,
  active,
  onPress,
  children,
}: {
  testId: string;
  label: string;
  value: ReactNode;
  tone: string;
  active: boolean;
  onPress: () => void;
  children?: ReactNode;
}) {
  return (
    <div className={clsx(cardCls, active ? 'border-oe-blue ring-1 ring-oe-blue/40' : 'border-border-light')}>
      <button
        type="button"
        data-testid={testId}
        aria-pressed={active}
        onClick={onPress}
        className="block w-full text-start focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/40 rounded"
      >
        <span className="block text-2xs font-medium text-content-tertiary uppercase tracking-wide">{label}</span>
        <span className={clsx('block text-lg font-semibold mt-1 tabular-nums', tone)}>{value}</span>
      </button>
      {children}
    </div>
  );
}

export function SubmittalRegisterSummary({
  summary,
  vocabulary,
  filters,
  onFilters,
}: {
  summary: Summary;
  vocabulary: SubmittalVocabulary | null;
  filters: RegisterFilters;
  onFilters: (next: RegisterFilters) => void;
}) {
  const { t } = useTranslation();
  const [legendOpen, setLegendOpen] = useState(false);

  /** Open one cut on its own, or go back to the whole register when it is already open. */
  const shortcut = (cut: Partial<RegisterFilters>) => {
    const next = { ...NO_FILTERS, ...cut };
    return {
      active: sameFilters(filters, next),
      press: () => onFilters(sameFilters(filters, next) ? NO_FILTERS : next),
    };
  };

  const awaiting = shortcut({ awaiting: true });
  const overdue = shortcut({ reviewOverdue: true });
  const longLead = shortcut({ longLead: true });
  const late = shortcut({ approvalLate: true });
  const disciplines = summary.by_discipline.filter((row) => row.code !== '');
  const noDiscipline = summary.by_discipline.find((row) => row.code === '')?.count ?? 0;

  return (
    <div className="space-y-3" data-testid="submittals-summary">
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <Card
          testId="submittals-stat-total"
          label={t('submittals.stat_total', { defaultValue: 'Total' })}
          value={summary.total}
          tone="text-content-primary"
          active={!hasActiveFilter(filters)}
          onPress={() => onFilters(NO_FILTERS)}
        />

        <Card
          testId="submittals-stat-awaiting"
          label={t('submittals.stat_awaiting_review', { defaultValue: 'Awaiting review' })}
          value={summary.awaiting_review}
          tone={summary.awaiting_review > 0 ? 'text-amber-500' : 'text-content-primary'}
          active={awaiting.active}
          onPress={awaiting.press}
        >
          <div className="mt-1 space-y-0.5 text-2xs">
            <button
              type="button"
              data-testid="submittals-stat-review-overdue"
              aria-pressed={overdue.active}
              onClick={overdue.press}
              className={clsx(
                'block text-start hover:underline',
                summary.review_overdue > 0 ? 'font-semibold text-semantic-error' : 'text-content-tertiary',
                overdue.active && 'underline',
              )}
            >
              {t('submittals.stat_review_overdue', {
                defaultValue: '{{n}} past the review period',
                n: summary.review_overdue,
              })}
            </button>
            {summary.review_period_unknown > 0 && (
              <p className="text-content-tertiary">
                {t('submittals.stat_review_period_unknown', {
                  defaultValue: '{{n}} with no review period recorded',
                  n: summary.review_period_unknown,
                })}
              </p>
            )}
          </div>
        </Card>

        <Card
          testId="submittals-stat-long-lead"
          label={t('submittals.stat_long_lead_awaiting', { defaultValue: 'Long lead awaiting approval' })}
          value={summary.long_lead_awaiting_approval}
          tone={summary.long_lead_awaiting_approval > 0 ? 'text-amber-500' : 'text-content-primary'}
          active={longLead.active}
          onPress={longLead.press}
        >
          <div className="mt-1 space-y-0.5 text-2xs text-content-tertiary">
            <p>
              {t('submittals.stat_long_lead_of', {
                defaultValue: 'of {{n}} long-lead items; opens them all',
                n: summary.long_lead,
              })}
            </p>
            {summary.long_lead_without_lead_time > 0 && (
              <p className="font-medium text-amber-700 dark:text-amber-400">
                {t('submittals.stat_long_lead_no_lead_time', {
                  defaultValue: '{{n}} with no approval deadline: lead time or site date missing',
                  n: summary.long_lead_without_lead_time,
                })}
              </p>
            )}
          </div>
        </Card>

        <Card
          testId="submittals-stat-approval-late"
          label={t('submittals.stat_approval_late', { defaultValue: 'Approval late' })}
          value={summary.approval_late}
          tone={summary.approval_late > 0 ? 'text-semantic-error' : 'text-content-primary'}
          active={late.active}
          onPress={late.press}
        >
          <p className="mt-1 text-2xs text-content-tertiary">
            {t('submittals.stat_approval_late_hint', {
              defaultValue: 'Not approved, and past required on site less lead time',
            })}
          </p>
        </Card>
      </div>

      {/* Outcome chips: what came back, by the reviewer's code. */}
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-2xs font-medium uppercase tracking-wide text-content-tertiary">
          {t('submittals.filter_outcome', { defaultValue: 'Review outcome' })}
        </span>
        {summary.by_outcome.map((row) => {
          const cut = shortcut({ outcome: row.code });
          const hint = outcomeHint(t, row.code);
          return (
            <button
              key={row.code}
              type="button"
              data-testid={`submittals-outcome-${row.code}`}
              aria-pressed={cut.active}
              title={hint ?? undefined}
              onClick={cut.press}
              className={clsx(
                chipCls,
                cut.active
                  ? 'border-oe-blue bg-oe-blue-subtle text-oe-blue-text'
                  : 'border-border-light bg-surface-primary text-content-secondary hover:bg-surface-secondary',
              )}
            >
              <ReviewCodeChip code={row.review_code} outcome={row.code} />
              <span>{outcomeLabel(t, row.code)}</span>
              <span className="font-semibold tabular-nums text-content-primary">{row.count}</span>
            </button>
          );
        })}
        <button
          type="button"
          data-testid="submittals-legend-toggle"
          aria-expanded={legendOpen}
          onClick={() => setLegendOpen((open) => !open)}
          className="inline-flex items-center gap-1 text-xs font-medium text-oe-blue-text hover:underline"
        >
          <CircleHelp size={13} aria-hidden />
          {t('submittals.outcome_legend_toggle', { defaultValue: 'What the codes mean' })}
        </button>
      </div>
      {legendOpen && <OutcomeLegend vocabulary={vocabulary} />}

      {/* Discipline chips, only once a project files anything under a discipline. */}
      {disciplines.length > 0 && (
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-2xs font-medium uppercase tracking-wide text-content-tertiary">
            {t('submittals.field_discipline', { defaultValue: 'Discipline' })}
          </span>
          {disciplines.map((row) => {
            const cut = shortcut({ discipline: row.code });
            return (
              <button
                key={row.code}
                type="button"
                data-testid={`submittals-discipline-${row.code}`}
                aria-pressed={cut.active}
                title={disciplineLabel(vocabulary, row.code)}
                onClick={cut.press}
                className={clsx(
                  chipCls,
                  cut.active
                    ? 'border-oe-blue bg-oe-blue-subtle text-oe-blue-text'
                    : 'border-border-light bg-surface-primary text-content-secondary hover:bg-surface-secondary',
                )}
              >
                <span className="font-semibold">{disciplineMark(vocabulary, row.code)}</span>
                <span>{disciplineLabel(vocabulary, row.code)}</span>
                <span className="font-semibold tabular-nums text-content-primary">{row.count}</span>
              </button>
            );
          })}
          {noDiscipline > 0 && (
            <span className="text-xs text-content-tertiary">
              {t('submittals.discipline_none_count', {
                defaultValue: 'No discipline: {{n}}',
                n: noDiscipline,
              })}
            </span>
          )}
        </div>
      )}
    </div>
  );
}
