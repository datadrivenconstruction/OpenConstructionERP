// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The register side of an expanded submittal: what the reviewer stamped and
 * what that means for ordering, the product and its dates, the revision
 * chain, and what the validation rules find.
 *
 * Every block is left out when it has nothing to say, so a submittal from
 * before the register columns existed expands to what it always showed.
 * The findings are fetched when the row is opened, not once per row of the
 * list, and only the rules that did not pass are listed.
 */
import type { ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import clsx from 'clsx';
import { AlertTriangle, Info, XCircle } from 'lucide-react';

import { CountryFlag, DateDisplay } from '@/shared/ui';
import { getCountry } from '@/shared/lib/countries';
import {
  fetchSubmittalFindings,
  type ReviewHistoryEntry,
  type Submittal,
  type SubmittalVocabulary,
  type ValidationSeverity,
} from './api';
import { ReviewCodeChip, outcomeHint, outcomeLabel } from './registerCells';
import { disciplineLabel, disciplineMark } from './registerView';

const blockTitleCls = 'text-xs text-content-tertiary mb-1 font-medium uppercase tracking-wide';

function Fact({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="text-2xs text-content-tertiary">{label}</dt>
      <dd className="text-sm text-content-primary break-words">{children}</dd>
    </div>
  );
}

/** The decision on the current revision, with the line that says what to do about it. */
function OutcomeBlock({ submittal }: { submittal: Submittal }) {
  const { t } = useTranslation();
  const outcome = submittal.review_outcome;
  if (!outcome) return null;
  const hint = outcomeHint(t, outcome);
  return (
    <div
      data-testid={`submittal-outcome-${submittal.id}`}
      className={clsx(
        'flex items-start gap-2 rounded-lg border p-3 text-xs',
        submittal.may_proceed
          ? 'border-emerald-200 bg-emerald-50 text-emerald-800 dark:border-emerald-800 dark:bg-emerald-950/20 dark:text-emerald-300'
          : 'border-orange-200 bg-orange-50 text-orange-800 dark:border-orange-800 dark:bg-orange-950/20 dark:text-orange-300',
      )}
    >
      <ReviewCodeChip code={submittal.review_code} outcome={outcome} className="mt-px shrink-0" />
      <div>
        <p>
          <span className="font-semibold">{outcomeLabel(t, outcome)}</span>
          {hint ? <> - {hint}</> : null}
        </p>
        {submittal.resubmit_for_record && (
          <p className="mt-1">
            {t('submittals.field_resubmit_for_record', {
              defaultValue: 'Corrected copy to be resubmitted for record',
            })}
          </p>
        )}
      </div>
    </div>
  );
}

/** The product and the dates, only the ones that are recorded. */
function ProcurementBlock({
  submittal,
  vocabulary,
}: {
  submittal: Submittal;
  vocabulary: SubmittalVocabulary | null;
}) {
  const { t } = useTranslation();
  const s = submittal;
  const supplier = s.supplier_name ?? s.supplier;
  const country = getCountry(s.country_of_origin);
  const lateDays = s.approval_late_days ?? 0;
  const overdueDays = s.review_overdue_days ?? 0;
  const drawings = s.linked_drawing_ids.length;

  const hasAny =
    s.discipline ||
    s.manufacturer ||
    s.model_reference ||
    s.country_of_origin ||
    supplier ||
    s.required_on_site_date ||
    s.long_lead ||
    s.lead_time_weeks !== null ||
    s.review_period_days !== null ||
    s.review_due_date ||
    s.approval_needed_by ||
    s.submit_by_date ||
    drawings > 0;
  if (!hasAny) return null;

  return (
    <div data-testid={`submittal-procurement-${s.id}`}>
      <p className={blockTitleCls}>{t('submittals.group_product', { defaultValue: 'Product and procurement' })}</p>
      <dl className="grid grid-cols-2 gap-x-4 gap-y-2 sm:grid-cols-3 lg:grid-cols-4">
        {s.discipline && (
          <Fact label={t('submittals.field_discipline', { defaultValue: 'Discipline' })}>
            {disciplineMark(vocabulary, s.discipline)} - {disciplineLabel(vocabulary, s.discipline)}
          </Fact>
        )}
        {s.manufacturer && (
          <Fact label={t('submittals.field_manufacturer', { defaultValue: 'Manufacturer / brand' })}>
            {s.manufacturer}
          </Fact>
        )}
        {s.model_reference && (
          <Fact label={t('submittals.field_model_reference', { defaultValue: 'Model / reference' })}>
            {s.model_reference}
          </Fact>
        )}
        {s.country_of_origin && (
          <Fact label={t('submittals.field_country_of_origin', { defaultValue: 'Country of origin' })}>
            <span className="inline-flex items-center gap-1.5">
              <CountryFlag code={s.country_of_origin} size={14} />
              {country?.name ?? s.country_of_origin}
            </span>
          </Fact>
        )}
        {supplier && (
          <Fact label={t('submittals.field_supplier', { defaultValue: 'Supplier' })}>{supplier}</Fact>
        )}
        {s.required_on_site_date && (
          <Fact label={t('submittals.field_required_on_site', { defaultValue: 'Required on site' })}>
            <DateDisplay value={s.required_on_site_date} className="text-sm" />
          </Fact>
        )}
        {(s.long_lead || s.lead_time_weeks !== null) && (
          <Fact label={t('submittals.field_lead_time_weeks', { defaultValue: 'Lead time (weeks)' })}>
            {s.lead_time_weeks === null ? (
              <span className="text-amber-700 dark:text-amber-400">
                {t('submittals.lead_time_missing', { defaultValue: 'Long-lead item, lead time not recorded' })}
              </span>
            ) : (
              s.lead_time_weeks
            )}
          </Fact>
        )}
        {s.approval_needed_by && (
          <Fact label={t('submittals.col_approval_needed_by', { defaultValue: 'Approval needed by' })}>
            <span className={clsx(lateDays > 0 && 'font-medium text-semantic-error')}>
              <DateDisplay value={s.approval_needed_by} className="text-sm" />
              {lateDays > 0 && (
                <> ({t('submittals.days_late', { defaultValue: '{{days}} d late', days: lateDays })})</>
              )}
            </span>
          </Fact>
        )}
        {s.submit_by_date && (
          <Fact label={t('submittals.label_submit_by', { defaultValue: 'Submit by' })}>
            <DateDisplay value={s.submit_by_date} className="text-sm" />
          </Fact>
        )}
        {s.review_period_days !== null && (
          <Fact label={t('submittals.field_review_period_days', { defaultValue: 'Review period (days)' })}>
            {s.review_period_days}
          </Fact>
        )}
        {s.review_due_date && (
          <Fact label={t('submittals.label_review_due', { defaultValue: 'Review due' })}>
            <span className={clsx(overdueDays > 0 && 'font-medium text-semantic-error')}>
              <DateDisplay value={s.review_due_date} className="text-sm" />
              {overdueDays > 0 && (
                <> ({t('submittals.days_overdue', { defaultValue: '{{days}} d overdue', days: overdueDays })})</>
              )}
            </span>
          </Fact>
        )}
        {s.date_returned && (
          <Fact label={t('submittals.label_returned', { defaultValue: 'Returned' })}>
            <DateDisplay value={s.date_returned} className="text-sm" />
          </Fact>
        )}
        {s.days_in_review !== null && (
          <Fact label={t('submittals.col_days_in_review', { defaultValue: 'Days in review' })}>
            {s.days_in_review}
          </Fact>
        )}
        {drawings > 0 && (
          <Fact label={t('submittals.field_linked_drawings', { defaultValue: 'Linked drawings' })}>{drawings}</Fact>
        )}
      </dl>
    </div>
  );
}

/**
 * The revisions this submittal has been through, oldest first, and which one
 * the current revision replaces.
 *
 * A finished review cycle is an entry of `review_history`. The current
 * revision gets a row of its own while it is still waiting for its answer,
 * so the chain always ends on what is in play now.
 */
function RevisionChain({ submittal }: { submittal: Submittal }) {
  const { t } = useTranslation();
  const history = submittal.review_history;
  if (history.length === 0) return null;

  const currentIsRecorded = history.some((entry) => entry.revision === submittal.revision);
  let replaced: ReviewHistoryEntry | undefined;
  for (const entry of history) {
    if (entry.revision === submittal.revision - 1) replaced = entry;
  }
  const th = 'px-2 py-1 text-left font-medium';
  const td = 'px-2 py-1 align-top';

  return (
    <div data-testid={`submittal-history-${submittal.id}`}>
      <p className={blockTitleCls}>{t('submittals.review_history', { defaultValue: 'Review history' })}</p>
      {replaced && (
        <p className="mb-1.5 text-xs text-content-secondary">
          {t('submittals.revision_replaces', {
            defaultValue: 'R{{current}} replaces R{{previous}}, which came back as {{code}} ({{outcome}}).',
            current: submittal.revision,
            previous: replaced.revision,
            code: replaced.code ?? '-',
            outcome: outcomeLabel(t, replaced.outcome),
          })}
        </p>
      )}
      <div className="overflow-x-auto rounded-lg border border-border-light">
        <table className="w-full min-w-[480px] text-xs">
          <thead className="bg-surface-secondary/40 text-2xs uppercase tracking-wide text-content-tertiary">
            <tr>
              <th className={th}>{t('submittals.col_rev', { defaultValue: 'Rev' })}</th>
              <th className={th}>{t('submittals.status_submitted', { defaultValue: 'Submitted' })}</th>
              <th className={th}>{t('submittals.label_returned', { defaultValue: 'Returned' })}</th>
              <th className={th}>{t('submittals.col_review_code', { defaultValue: 'Review code' })}</th>
              <th className={th}>{t('submittals.filter_outcome', { defaultValue: 'Review outcome' })}</th>
              <th className={th}>{t('submittals.label_review_notes', { defaultValue: 'Reviewer comments' })}</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border-light text-content-primary">
            {history.map((entry, index) => (
              <tr key={`${entry.revision}-${index}`}>
                <td className={clsx(td, 'font-mono tabular-nums')}>R{entry.revision}</td>
                <td className={td}>
                  <DateDisplay value={entry.date_submitted} className="text-xs" />
                </td>
                <td className={td}>
                  <DateDisplay value={entry.date_returned} className="text-xs" />
                </td>
                <td className={td}>
                  <ReviewCodeChip code={entry.code} outcome={entry.outcome} />
                </td>
                <td className={td}>
                  {outcomeLabel(t, entry.outcome)}
                  {entry.resubmit_for_record && (
                    <span className="block text-2xs text-content-tertiary">
                      {t('submittals.field_resubmit_for_record', {
                        defaultValue: 'Corrected copy to be resubmitted for record',
                      })}
                    </span>
                  )}
                </td>
                <td className={clsx(td, 'whitespace-pre-wrap text-content-secondary')}>{entry.notes ?? ''}</td>
              </tr>
            ))}
            {!currentIsRecorded && (
              <tr className="bg-surface-secondary/20">
                <td className={clsx(td, 'font-mono tabular-nums font-semibold')}>R{submittal.revision}</td>
                <td className={td}>
                  <DateDisplay value={submittal.date_submitted} className="text-xs" />
                </td>
                <td className={td} />
                <td className={td} />
                <td className={clsx(td, 'text-content-secondary')} colSpan={2}>
                  {t('submittals.revision_current', { defaultValue: 'Current revision, no decision yet' })}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

const FINDING_STYLE: Record<ValidationSeverity, string> = {
  error: 'border-red-200 bg-red-50 text-red-800 dark:border-red-800 dark:bg-red-950/20 dark:text-red-300',
  warning: 'border-amber-200 bg-amber-50 text-amber-800 dark:border-amber-800 dark:bg-amber-950/20 dark:text-amber-300',
  info: 'border-border-light bg-surface-secondary text-content-secondary',
};

function FindingIcon({ severity }: { severity: ValidationSeverity }) {
  if (severity === 'error') return <XCircle size={14} className="mt-0.5 shrink-0" aria-hidden />;
  if (severity === 'warning') return <AlertTriangle size={14} className="mt-0.5 shrink-0" aria-hidden />;
  return <Info size={14} className="mt-0.5 shrink-0" aria-hidden />;
}

/**
 * What the `submittal` rule set finds on this submittal. Advisory: the rules
 * report and never refuse, so the list sits above the actions, not in their way.
 */
function Findings({ submittal }: { submittal: Submittal }) {
  const { t } = useTranslation();
  // Keyed under ['submittals'] so an edit or a review refetches it with the list.
  const { data: findings = [] } = useQuery({
    queryKey: ['submittals', 'findings', submittal.id, submittal.updated_at],
    queryFn: () => fetchSubmittalFindings(submittal.id),
    retry: false,
  });
  if (findings.length === 0) return null;

  const severityLabel = (severity: ValidationSeverity): string => {
    if (severity === 'error') return t('submittals.finding_error', { defaultValue: 'Error' });
    if (severity === 'warning') return t('submittals.finding_warning', { defaultValue: 'Warning' });
    return t('submittals.finding_info', { defaultValue: 'Note' });
  };

  return (
    <div data-testid={`submittal-findings-${submittal.id}`}>
      <p className={blockTitleCls}>{t('submittals.findings_title', { defaultValue: 'Checks' })}</p>
      <ul className="space-y-1.5">
        {findings.map((finding, index) => (
          <li
            key={`${finding.rule_id}-${index}`}
            className={clsx('flex items-start gap-2 rounded-lg border p-2.5 text-xs', FINDING_STYLE[finding.severity])}
          >
            <FindingIcon severity={finding.severity} />
            <div>
              <p>
                <span className="font-semibold">{severityLabel(finding.severity)}:</span> {finding.message}
              </p>
              {finding.suggestion && <p className="mt-0.5 opacity-90">{finding.suggestion}</p>}
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function SubmittalRegisterDetail({
  submittal,
  vocabulary,
}: {
  submittal: Submittal;
  vocabulary: SubmittalVocabulary | null;
}) {
  return (
    <>
      <OutcomeBlock submittal={submittal} />
      <ProcurementBlock submittal={submittal} vocabulary={vocabulary} />
      <RevisionChain submittal={submittal} />
      <Findings submittal={submittal} />
    </>
  );
}
