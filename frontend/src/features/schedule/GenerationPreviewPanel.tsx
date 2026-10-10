// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { AlertTriangle, Info } from 'lucide-react';
import type { TFunction } from 'i18next';
import { fmtDate } from '@/shared/lib/formatters';
import type { GenerationNote, GenerationPreview } from './api';
import { isParallelCrewsWarning } from './generateWindow';

/** Estimate types that describe a budget rather than a bill to build from. */
const BUDGET_ESTIMATE_TYPES = new Set(['budget', 'conceptual', 'order_of_magnitude', 'rom', 'preliminary']);

/** Whether at least half the positions a bill schedules are lump sums, as in a control budget. */
export function isMostlyLumpSums(preview: Pick<GenerationPreview, 'lump_sum_positions' | 'positions_scheduled'>): boolean {
  return preview.positions_scheduled > 0 && preview.lump_sum_positions * 2 >= preview.positions_scheduled;
}

/** Whether a BOQ was saved as a budget-level estimate (a control budget, a cost plan). */
export function isBudgetEstimate(estimateType: string | null | undefined): boolean {
  return !!estimateType && BUDGET_ESTIMATE_TYPES.has(estimateType.toLowerCase());
}

/**
 * The sentence for positions given several crews side by side, because one
 * crew of the assumed size could not finish them in the window. Shown in the
 * preview and after generating, so a duration shorter than one crew could
 * manage always comes with its reason.
 */
export function parallelCrewsText(
  t: TFunction,
  w: { positions: number; workers: number; most_crews: number },
): string {
  return t('schedule.warning_parallel_crews', {
    defaultValue:
      'Positions given parallel crews: {{positions}}. One crew of {{workers}} could not finish them in the window, so up to {{crews}} crews work each of them side by side. Their labour hours are unchanged, only their durations are shorter.',
    positions: w.positions,
    workers: w.workers,
    crews: w.most_crews,
  });
}

// How many notes are listed before "Show all".
const NOTES_SHOWN = 30;

function noteText(t: TFunction, note: GenerationNote): string {
  const days = note.days ?? 0;
  switch (note.note) {
    case 'estimated_from_unit': {
      const b = note.basis;
      if (!b) return t('schedule.preview_note_unit_plain', { defaultValue: '{{count}} working days, estimated from its unit.', count: days });
      const main = t('schedule.preview_note_unit', {
        defaultValue:
          '{{count}} working days: about {{hours}} hours at {{rate}} h per {{unit}}, for a gang of {{gang}} working {{hoursPerDay}} h a day.',
        count: days,
        hours: Math.round(b.hours),
        rate: b.rate,
        unit: b.unit,
        gang: b.gang,
        hoursPerDay: b.hours_per_day,
      });
      if (!b.capped_by_price || b.hours_from_unit == null) return main;
      return `${main} ${t('schedule.preview_note_capped', {
        defaultValue: 'The unit alone gave {{hours}} hours, more than its price allows, so it was held to about three times its share of the bill.',
        hours: Math.round(b.hours_from_unit),
      })}`;
    }
    case 'cost_share':
      return t('schedule.preview_note_cost_share', {
        defaultValue: '{{count}} working days, from its share of the bill\'s cost (a lump sum has no quantity to go by).',
        count: days,
      });
    case 'default_duration':
      return t('schedule.preview_note_default', {
        defaultValue: '{{count}} working days, a default: no labour, quantity or price to go by.',
        count: days,
      });
    case 'spans_works':
      return t('schedule.preview_note_spans_works', {
        defaultValue:
          'Runs for the whole works, {{count}} working days: a lump sum outside every section, such as site costs or safety.',
        count: days,
      });
    case 'skipped_zero_qty':
      return t('schedule.preview_note_zero_qty', { defaultValue: 'Left out: no quantity, so nothing to build.' });
    case 'empty_section_dropped':
      return t('schedule.preview_note_empty_section', { defaultValue: 'Left out: a section with no positions.' });
    case 'blank_row_dropped':
      return t('schedule.preview_note_blank_row', { defaultValue: 'Left out: a blank row.' });
    default:
      return '';
  }
}

/**
 * What a generation from a BOQ would write, before anything is written.
 *
 * Counts first ("86 activities, 12 estimated, 3 left out"), then when the plan
 * ends against the end date asked for, then one line per position whose
 * duration is an estimate or that is left out, with the numbers behind it.
 */
export function GenerationPreviewPanel({ preview }: { preview: GenerationPreview }) {
  const { t } = useTranslation();
  const [showAll, setShowAll] = useState(false);
  const notes = showAll ? preview.notes : preview.notes.slice(0, NOTES_SHOWN);
  const late = preview.requested_end != null && preview.planned_end > preview.requested_end;

  return (
    <div className="space-y-3 rounded-lg border border-border bg-surface-secondary/40 p-3" data-testid="generation-preview">
      <p className="text-sm font-medium text-content-primary">
        {t('schedule.preview_counts', {
          defaultValue: '{{count}} activities: {{positions}} positions in {{sections}} sections, a start and a completion milestone.',
          count: preview.activity_count,
          positions: preview.positions_scheduled,
          sections: preview.summary_count,
        })}{' '}
        {t('schedule.preview_estimated', {
          defaultValue: '{{count}} durations are estimates.',
          count: preview.estimated_count,
        })}{' '}
        {preview.skipped_count > 0 &&
          t('schedule.preview_skipped', { defaultValue: '{{count}} rows left out.', count: preview.skipped_count })}
      </p>
      <p className={`flex items-start gap-2 text-sm ${late ? 'text-semantic-warning' : 'text-content-secondary'}`}>
        {late && <AlertTriangle size={14} className="mt-0.5 shrink-0" />}
        {preview.requested_end == null
          ? t('schedule.preview_dates_open', {
              defaultValue: 'Starts {{start}}, ends {{end}}. No end date was given, so the plan takes as long as the work needs.',
              start: fmtDate(preview.planned_start),
              end: fmtDate(preview.planned_end),
            })
          : late
            ? t('schedule.preview_dates_late', {
                defaultValue: 'Starts {{start}}, ends {{end}}: after the end date you asked for, {{requested}}.',
                start: fmtDate(preview.planned_start),
                end: fmtDate(preview.planned_end),
                requested: fmtDate(preview.requested_end),
              })
            : t('schedule.preview_dates_fit', {
                defaultValue: 'Starts {{start}}, ends {{end}}, inside the end date you asked for, {{requested}}.',
                start: fmtDate(preview.planned_start),
                end: fmtDate(preview.planned_end),
                requested: fmtDate(preview.requested_end),
              })}
      </p>
      <p className="text-xs text-content-tertiary">
        {t('schedule.preview_crews', {
          defaultValue: 'Up to {{count}} crews work side by side in each section.',
          count: preview.crews,
        })}
        {preview.workers_per_position != null &&
          (preview.positions_without_workers ?? 0) > 0 &&
          ` ${
            // Not fitting at the estimates while the plan as a whole fits means
            // the durations were shortened: the line after this one says how far.
            preview.workers_assumed &&
            preview.fitted_window?.fits === false &&
            !preview.fitted_window.default &&
            preview.fits
              ? t('schedule.preview_workers_most_shortened', {
                  defaultValue:
                    'Assumed: {{count}} workers per position where the bill gives no crew ({{positions}} positions), the most the plan assumes. Even with them the work fits your end date only with shorter durations.',
                  count: preview.workers_per_position,
                  positions: preview.positions_without_workers,
                })
              : preview.workers_assumed && preview.fitted_window?.fits === false
              ? t(
                  preview.fitted_window.default
                    ? 'schedule.preview_workers_most_default'
                    : 'schedule.preview_workers_most',
                  {
                    defaultValue: preview.fitted_window.default
                      ? 'Assumed: {{count}} workers per position where the bill gives no crew ({{positions}} positions), the most the plan assumes. Even so the work runs past a default window of {{days}} days. Check the labour hours in the bill, or enter an end date and more workers.'
                      : 'Assumed: {{count}} workers per position where the bill gives no crew ({{positions}} positions), the most the plan assumes. Even so the work does not fit your end date. Check the labour hours in the bill, or move the end date.',
                    count: preview.workers_per_position,
                    positions: preview.positions_without_workers,
                    days: preview.fitted_window.days,
                  },
                )
              : preview.workers_assumed && preview.fitted_window?.default
              ? t('schedule.preview_workers_assumed_default', {
                  defaultValue:
                    'Assumed: at least {{count}} workers per position where the bill gives no crew ({{positions}} positions), the fewest that fit a default window of {{days}} days, to {{end}}. No end date was given; enter one to fit the plan to your own.',
                  count: preview.workers_per_position,
                  positions: preview.positions_without_workers,
                  days: preview.fitted_window.days,
                  end: fmtDate(preview.fitted_window.end),
                })
              : preview.workers_assumed
              ? t('schedule.preview_workers_assumed', {
                  defaultValue:
                    'Assumed: at least {{count}} workers per position where the bill gives no crew ({{positions}} positions), the fewest that fit your end date.',
                  count: preview.workers_per_position,
                  positions: preview.positions_without_workers,
                })
              : t('schedule.preview_workers_set', {
                  defaultValue:
                    'At least {{count}} workers per position where the bill gives no crew ({{positions}} positions), as you set it.',
                  count: preview.workers_per_position,
                  positions: preview.positions_without_workers,
                })
          }`}
        {preview.compressed_pct != null &&
          !preview.fits &&
          ` ${t('schedule.preview_shortened_to_floor', {
            defaultValue: 'Every duration is already cut to half of its estimate, the shortest a plan is squeezed to.',
          })}`}
        {preview.compressed_pct != null &&
          preview.fits &&
          ` ${t('schedule.warning_durations_shortened', {
            defaultValue:
              'To fit the dates you asked for, every duration was shortened to {{percent}}% of its estimate. Check that the crews can keep that pace.',
            percent: preview.compressed_pct,
          })}`}
        {preview.warnings
          .filter(isParallelCrewsWarning)
          .map((w) => ` ${parallelCrewsText(t, w)}`)
          .join('')}
      </p>
      {isBudgetEstimate(preview.boq_estimate_type) ? (
        <p className="flex items-start gap-2 text-xs text-semantic-warning">
          <Info size={14} className="mt-0.5 shrink-0" />
          {t('schedule.preview_budget_bill', {
            defaultValue:
              'This bill is saved as a budget estimate. Its lump sums become one bar each, so the plan is only as detailed as the budget. A detailed bill gives a plan you can build to.',
          })}
        </p>
      ) : (
        isMostlyLumpSums(preview) && (
          <p className="flex items-start gap-2 text-xs text-semantic-warning">
            <Info size={14} className="mt-0.5 shrink-0" />
            {t('schedule.preview_lump_sum_bill', {
              defaultValue:
                '{{count}} of its {{total}} positions are lump sums. Each becomes one bar, so the plan is only as detailed as that, as with a budget. A bill with quantities gives a plan you can build to.',
              count: preview.lump_sum_positions,
              total: preview.positions_scheduled,
            })}
          </p>
        )
      )}
      {preview.notes.length > 0 && (
        <div>
          <p className="mb-1 text-xs font-medium text-content-secondary">
            {t('schedule.preview_notes_title', { defaultValue: 'Estimated or left out' })}
          </p>
          <ul className="max-h-56 space-y-1 overflow-y-auto text-xs" data-testid="generation-preview-notes">
            {notes.map((note) => (
              <li key={`${note.position_id}-${note.note}`} className="text-content-secondary">
                <span className="font-mono text-content-tertiary">{note.ordinal}</span>{' '}
                <span className="text-content-primary">{note.description}</span>
                {': '}
                {noteText(t, note)}
              </li>
            ))}
          </ul>
          {!showAll && preview.notes.length > NOTES_SHOWN && (
            <button
              type="button"
              onClick={() => setShowAll(true)}
              className="mt-1 text-xs font-medium text-oe-blue hover:underline"
            >
              {t('schedule.preview_notes_show_all', { defaultValue: 'Show all {{count}}', count: preview.notes.length })}
            </button>
          )}
        </div>
      )}
    </div>
  );
}
