// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * <TimesheetLineRow> - one labour or plant line on a timesheet.
 *
 * Editable while the timesheet is a draft (text / number fields commit on
 * blur, selects and the daywork toggle commit immediately); read-only once
 * the sheet is submitted or beyond. The parent remounts the row after every
 * server change (via a key on line.updated_at) so local state never drifts.
 */

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import clsx from 'clsx';
import { Trash2, HardHat, Wrench } from 'lucide-react';
import { Toggle } from '@/shared/ui/Toggle';
import { CostCodeAssist } from './CostCodeAssist';
import {
  formatHours,
  instantFromTime,
  timeOfDay,
  type EmployerKind,
  type FieldTimesheetLine,
  type LineUpdatePayload,
} from './api';

export interface PickOption {
  id: string;
  label: string;
}

const fieldCls =
  'h-8 w-full rounded-lg border border-border-light bg-surface-primary px-2.5 text-sm text-content-primary disabled:opacity-60';

export interface TimesheetLineRowProps {
  line: FieldTimesheetLine;
  editable: boolean;
  projectId: string;
  labour: PickOption[];
  plant: PickOption[];
  variations: PickOption[];
  /** Subcontractors, for a line whose worker is employed by one. */
  employers?: PickOption[];
  /** Show the clock-time and employer fields (the sheet records working time). */
  workingTime?: boolean;
  /** The sheet's day, which is what a typed clock time is a time on. */
  timesheetDate?: string;
  onUpdate: (lineId: string, payload: LineUpdatePayload) => void;
  onDelete: (lineId: string) => void;
  busy?: boolean;
}

export function TimesheetLineRow({
  line,
  editable,
  projectId,
  labour,
  plant,
  variations,
  employers = [],
  workingTime = false,
  timesheetDate = '',
  onUpdate,
  onDelete,
  busy,
}: TimesheetLineRowProps) {
  const { t } = useTranslation();
  const [hours, setHours] = useState(formatHours(line.hours));
  const [costCode, setCostCode] = useState(line.cost_code);
  const [wbs, setWbs] = useState(line.wbs ?? '');
  const [note, setNote] = useState(line.note ?? '');
  const [startTime, setStartTime] = useState(timeOfDay(line.started_at));
  const [endTime, setEndTime] = useState(timeOfDay(line.ended_at));
  const [breakMinutes, setBreakMinutes] = useState(
    line.break_minutes == null ? '' : String(line.break_minutes),
  );

  const isLabour = line.kind === 'labour';
  const options = isLabour ? labour : plant;
  const currentId = isLabour ? line.resource_id : line.equipment_id;
  const hasCurrent = currentId != null && options.some((o) => o.id === currentId);

  const commit = (payload: LineUpdatePayload) => {
    if (!editable) return;
    onUpdate(line.id, payload);
  };

  /**
   * Send the clock times as a pair, because that is what the server accepts:
   * a line records both or neither, so a half-typed pair waits here rather than
   * going up to be refused. The times are moments, not wall-clock readings, so
   * the sheet's day and the reader's own timezone turn them into one.
   */
  const commitTimes = (nextStart: string, nextEnd: string, nextBreak: string) => {
    if (!editable) return;
    if (!!nextStart !== !!nextEnd) return;
    const startISO = nextStart ? instantFromTime(timesheetDate, nextStart) : null;
    const minutes = nextBreak.trim() === '' ? null : Number(nextBreak);
    commit({
      started_at: startISO,
      ended_at: nextEnd ? instantFromTime(timesheetDate, nextEnd, startISO) : null,
      break_minutes: minutes != null && Number.isFinite(minutes) ? Math.max(0, minutes) : null,
    });
  };

  return (
    <div className="rounded-lg border border-border-light bg-surface-primary p-2.5">
      <div className="grid grid-cols-2 gap-2 lg:grid-cols-12 lg:items-end">
      {/* Kind */}
      <div className="col-span-2 flex items-center gap-1.5 lg:col-span-1">
        {isLabour ? (
          <HardHat size={15} className="text-oe-blue" />
        ) : (
          <Wrench size={15} className="text-content-secondary" />
        )}
        <span className="text-2xs font-medium uppercase tracking-wide text-content-tertiary">
          {isLabour
            ? t('field_time.kind_labour', { defaultValue: 'Labour' })
            : t('field_time.kind_plant', { defaultValue: 'Plant' })}
        </span>
      </div>

      {/* Who / what */}
      <label className="col-span-2 lg:col-span-3">
        <span className="mb-1 block text-2xs font-medium text-content-tertiary">
          {isLabour
            ? t('field_time.worker', { defaultValue: 'Worker / crew' })
            : t('field_time.machine', { defaultValue: 'Machine' })}
        </span>
        <select
          value={currentId ?? ''}
          disabled={!editable}
          className={fieldCls}
          onChange={(e) =>
            commit(isLabour ? { resource_id: e.target.value } : { equipment_id: e.target.value })
          }
        >
          {!hasCurrent && (
            <option value={currentId ?? ''}>
              {t('field_time.unknown_pick', { defaultValue: 'Unknown' })}
            </option>
          )}
          {options.map((o) => (
            <option key={o.id} value={o.id}>
              {o.label}
            </option>
          ))}
        </select>
      </label>

      {/* Hours. Read-only once the line has clock times: the figure is derived
          from them on every write, so an edit here would be undone silently. */}
      <label className="lg:col-span-1">
        <span className="mb-1 block text-2xs font-medium text-content-tertiary">
          {t('field_time.hours', { defaultValue: 'Hours' })}
        </span>
        <input
          type="number"
          min="0"
          step="0.25"
          value={hours}
          disabled={!editable || line.hours_derived}
          title={
            line.hours_derived
              ? t('field_time.working_time.hours_derived', {
                  defaultValue: 'Worked out from the start, the end and the break.',
                })
              : undefined
          }
          className={clsx(fieldCls, 'tabular-nums')}
          onChange={(e) => setHours(e.target.value)}
          onBlur={() => {
            const next = hours.trim() === '' ? '0' : hours.trim();
            if (next !== formatHours(line.hours)) commit({ hours: next });
          }}
        />
      </label>

      {/* Cost code + assist */}
      <div className="col-span-2 lg:col-span-3">
        <span className="mb-1 block text-2xs font-medium text-content-tertiary">
          {t('field_time.cost_code', { defaultValue: 'Cost code' })}
        </span>
        <div className="flex items-center gap-1.5">
          <input
            value={costCode}
            disabled={!editable}
            className={fieldCls}
            placeholder={t('field_time.cost_code_placeholder', { defaultValue: 'e.g. 03.30' })}
            onChange={(e) => setCostCode(e.target.value)}
            onBlur={() => {
              if (costCode !== line.cost_code) commit({ cost_code: costCode });
            }}
          />
          {editable && (
            <CostCodeAssist
              projectId={projectId}
              defaultText={note || undefined}
              disabled={busy}
              onApply={(code) => {
                setCostCode(code);
                commit({ cost_code: code });
              }}
            />
          )}
        </div>
      </div>

      {/* WBS */}
      <label className="lg:col-span-1">
        <span className="mb-1 block text-2xs font-medium text-content-tertiary">
          {t('field_time.wbs', { defaultValue: 'WBS' })}
        </span>
        <input
          value={wbs}
          disabled={!editable}
          className={fieldCls}
          onChange={(e) => setWbs(e.target.value)}
          onBlur={() => {
            const next = wbs.trim();
            if (next !== (line.wbs ?? '')) commit({ wbs: next || null });
          }}
        />
      </label>

      {/* Daywork + variation */}
      <div className="col-span-2 lg:col-span-2">
        <span className="mb-1 block text-2xs font-medium text-content-tertiary">
          {t('field_time.daywork', { defaultValue: 'Daywork' })}
        </span>
        <div className="flex h-8 items-center">
          <Toggle
            checked={line.is_daywork}
            disabled={!editable}
            size="sm"
            onChange={(next) => commit({ is_daywork: next })}
            label={
              line.is_daywork
                ? t('common.yes', { defaultValue: 'Yes' })
                : t('common.no', { defaultValue: 'No' })
            }
          />
        </div>
        {line.is_daywork && (
          <select
            value={line.variation_id ?? ''}
            disabled={!editable}
            className={clsx(fieldCls, 'mt-1.5')}
            onChange={(e) => commit({ variation_id: e.target.value || null })}
          >
            <option value="">
              {t('field_time.variation_none', { defaultValue: 'No variation' })}
            </option>
            {variations.map((v) => (
              <option key={v.id} value={v.id}>
                {v.label}
              </option>
            ))}
          </select>
        )}
      </div>

      {/* Delete */}
      <div className="flex justify-end lg:col-span-1">
        {editable && (
          <button
            type="button"
            disabled={busy}
            onClick={() => onDelete(line.id)}
            aria-label={t('field_time.delete_line', { defaultValue: 'Delete line' })}
            className="inline-flex h-8 w-8 items-center justify-center rounded-lg text-content-tertiary hover:bg-semantic-error-bg hover:text-semantic-error disabled:opacity-40"
          >
            <Trash2 size={15} />
          </button>
        )}
      </div>
      </div>

      {/* Clock times and the employer, on labour lines of a sheet that records
          working time. A machine has no working time and no employer, so a
          plant line never grows these fields. */}
      {workingTime && isLabour && (
        <div className="mt-2 grid grid-cols-2 gap-2 border-t border-border-light pt-2 lg:grid-cols-12 lg:items-end">
          <label className="lg:col-span-2">
            <span className="mb-1 block text-2xs font-medium text-content-tertiary">
              {t('field_time.working_time.start', { defaultValue: 'Start' })}
            </span>
            <input
              type="time"
              value={startTime}
              disabled={!editable}
              className={clsx(fieldCls, 'tabular-nums')}
              onChange={(e) => setStartTime(e.target.value)}
              onBlur={() => commitTimes(startTime, endTime, breakMinutes)}
            />
          </label>
          <label className="lg:col-span-2">
            <span className="mb-1 block text-2xs font-medium text-content-tertiary">
              {t('field_time.working_time.end', { defaultValue: 'End' })}
            </span>
            <input
              type="time"
              value={endTime}
              disabled={!editable}
              className={clsx(fieldCls, 'tabular-nums')}
              onChange={(e) => setEndTime(e.target.value)}
              onBlur={() => commitTimes(startTime, endTime, breakMinutes)}
            />
          </label>
          <label className="lg:col-span-2">
            <span className="mb-1 block text-2xs font-medium text-content-tertiary">
              {t('field_time.working_time.break_minutes', { defaultValue: 'Break (min)' })}
            </span>
            <input
              type="number"
              min="0"
              step="5"
              value={breakMinutes}
              disabled={!editable}
              className={clsx(fieldCls, 'tabular-nums')}
              onChange={(e) => setBreakMinutes(e.target.value)}
              onBlur={() => commitTimes(startTime, endTime, breakMinutes)}
            />
          </label>
          <label className="lg:col-span-3">
            <span className="mb-1 block text-2xs font-medium text-content-tertiary">
              {t('field_time.working_time.employer', { defaultValue: 'Employer' })}
            </span>
            <select
              value={line.employer_kind ?? ''}
              disabled={!editable}
              className={fieldCls}
              onChange={(e) => {
                const kind = (e.target.value || null) as EmployerKind | null;
                commit({
                  employer_kind: kind,
                  // Own staff cannot also name a subcontractor, and clearing
                  // the employer clears whichever firm was named with it.
                  employer_subcontractor_id:
                    kind === 'subcontractor' ? line.employer_subcontractor_id : null,
                });
              }}
            >
              <option value="">
                {t('field_time.working_time.employer_unstated', { defaultValue: 'Not stated' })}
              </option>
              <option value="own">
                {t('field_time.working_time.employer_own', { defaultValue: 'Own staff' })}
              </option>
              <option value="subcontractor">
                {t('field_time.working_time.employer_sub', { defaultValue: 'Subcontractor' })}
              </option>
            </select>
          </label>
          {line.employer_kind === 'subcontractor' && (
            <label className="col-span-2 lg:col-span-3">
              <span className="mb-1 block text-2xs font-medium text-content-tertiary">
                {t('field_time.working_time.which_subcontractor', { defaultValue: 'Which firm' })}
              </span>
              <select
                value={line.employer_subcontractor_id ?? ''}
                disabled={!editable}
                className={fieldCls}
                onChange={(e) => commit({ employer_subcontractor_id: e.target.value || null })}
              >
                <option value="">
                  {t('field_time.working_time.employer_unnamed', {
                    defaultValue: 'Subcontractor, not named',
                  })}
                </option>
                {employers.map((o) => (
                  <option key={o.id} value={o.id}>
                    {o.label}
                  </option>
                ))}
              </select>
            </label>
          )}
        </div>
      )}

      {/* Note (full width) */}
      {editable ? (
        <label className="mt-2 block">
          <span className="mb-1 block text-2xs font-medium text-content-tertiary">
            {t('field_time.note', { defaultValue: 'Note' })}
          </span>
          <input
            value={note}
            className={fieldCls}
            placeholder={t('field_time.line_note_placeholder', {
              defaultValue: 'What was done (optional)',
            })}
            onChange={(e) => setNote(e.target.value)}
            onBlur={() => {
              const next = note.trim();
              if (next !== (line.note ?? '')) commit({ note: next || null });
            }}
          />
        </label>
      ) : (
        line.note && (
          <p className="mt-2 text-xs text-content-secondary">
            <span className="text-content-tertiary">
              {t('field_time.note', { defaultValue: 'Note' })}:
            </span>{' '}
            {line.note}
          </p>
        )
      )}
    </div>
  );
}
