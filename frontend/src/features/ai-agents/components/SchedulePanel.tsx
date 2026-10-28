// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
// Schedule panel for the custom-agent builder (Item 29).
//
// Lets a non-technical user put an agent on a recurring schedule without ever
// writing a cron string: pick a frequency (daily / weekly / monthly) and a time
// and we synthesise the 5-field POSIX cron. A power user can still flip to "raw
// cron" and type one directly. The agent then runs automatically at those UTC
// times; a scheduled run is a normal run and never auto-applies its output.
import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Clock, AlertCircle } from 'lucide-react';
import clsx from 'clsx';

// ── Cron synthesis / parsing (the simple subset the UI builds) ───────────────

type Frequency = 'daily' | 'weekly' | 'monthly' | 'custom';

const WEEKDAYS: { value: number; labelKey: string; defaultLabel: string }[] = [
  { value: 1, labelKey: 'agents.schedule.mon', defaultLabel: 'Monday' },
  { value: 2, labelKey: 'agents.schedule.tue', defaultLabel: 'Tuesday' },
  { value: 3, labelKey: 'agents.schedule.wed', defaultLabel: 'Wednesday' },
  { value: 4, labelKey: 'agents.schedule.thu', defaultLabel: 'Thursday' },
  { value: 5, labelKey: 'agents.schedule.fri', defaultLabel: 'Friday' },
  { value: 6, labelKey: 'agents.schedule.sat', defaultLabel: 'Saturday' },
  { value: 0, labelKey: 'agents.schedule.sun', defaultLabel: 'Sunday' },
];

/** Build a 5-field cron from the structured picker state. */
function buildCron(freq: Frequency, hour: number, minute: number, dow: number, dom: number): string {
  const m = String(minute);
  const h = String(hour);
  switch (freq) {
    case 'daily':
      return `${m} ${h} * * *`;
    case 'weekly':
      return `${m} ${h} * * ${dow}`;
    case 'monthly':
      return `${m} ${h} ${dom} * *`;
    default:
      return '';
  }
}

interface ParsedCron {
  freq: Frequency;
  hour: number;
  minute: number;
  dow: number;
  dom: number;
}

/** Best-effort parse of a cron back into picker state (falls back to custom). */
function parseCron(expr: string): ParsedCron {
  const fields = expr.trim().split(/\s+/);
  const fallback: ParsedCron = { freq: 'custom', hour: 9, minute: 0, dow: 1, dom: 1 };
  if (fields.length !== 5) return fallback;
  const [m, h, dom, month, dow] = fields as [string, string, string, string, string];
  const minute = Number(m);
  const hour = Number(h);
  if (!Number.isInteger(minute) || !Number.isInteger(hour) || month !== '*') return fallback;
  if (dom === '*' && dow === '*') return { freq: 'daily', hour, minute, dow: 1, dom: 1 };
  if (dom === '*' && /^[0-6]$/.test(dow)) {
    return { freq: 'weekly', hour, minute, dow: Number(dow), dom: 1 };
  }
  if (dow === '*' && /^([1-9]|[12]\d|3[01])$/.test(dom)) {
    return { freq: 'monthly', hour, minute, dow: 1, dom: Number(dom) };
  }
  return fallback;
}

function pad2(n: number): string {
  return String(n).padStart(2, '0');
}

interface SchedulePanelProps {
  /** Current cron expression (null = no schedule). */
  cron: string | null;
  enabled: boolean;
  /** The instruction a scheduled run is fired with (blank = generic default). */
  scheduleInput: string;
  /** Next run, ISO-8601 UTC (from the server). Shown read-only when present. */
  nextRunAt: string | null;
  onChange: (next: { cron: string | null; enabled: boolean; scheduleInput: string }) => void;
}

export function SchedulePanel({
  cron,
  enabled,
  scheduleInput,
  nextRunAt,
  onChange,
}: SchedulePanelProps): JSX.Element {
  const { t } = useTranslation();

  const initial = useMemo(() => (cron ? parseCron(cron) : null), [cron]);
  const [on, setOn] = useState<boolean>(!!cron && enabled);
  const [freq, setFreq] = useState<Frequency>(initial?.freq ?? 'daily');
  const [hour, setHour] = useState<number>(initial?.hour ?? 9);
  const [minute, setMinute] = useState<number>(initial?.minute ?? 0);
  const [dow, setDow] = useState<number>(initial?.dow ?? 1);
  const [dom, setDom] = useState<number>(initial?.dom ?? 1);
  const [rawCron, setRawCron] = useState<string>(cron ?? '');
  const [input, setInput] = useState<string>(scheduleInput ?? '');

  // Re-seed when the source cron changes (e.g. opening edit on a new agent).
  useEffect(() => {
    const p = cron ? parseCron(cron) : null;
    setOn(!!cron && enabled);
    setFreq(p?.freq ?? 'daily');
    setHour(p?.hour ?? 9);
    setMinute(p?.minute ?? 0);
    setDow(p?.dow ?? 1);
    setDom(p?.dom ?? 1);
    setRawCron(cron ?? '');
    setInput(scheduleInput ?? '');
  }, [cron, enabled, scheduleInput]);

  // Recompute the effective cron whenever any control changes and bubble up.
  const effectiveCron = useMemo(() => {
    if (!on) return null;
    if (freq === 'custom') return rawCron.trim() || null;
    return buildCron(freq, hour, minute, dow, dom);
  }, [on, freq, hour, minute, dow, dom, rawCron]);

  useEffect(() => {
    onChange({ cron: effectiveCron, enabled: on, scheduleInput: input });
    // onChange identity is stable from the parent (useCallback) — exclude it to
    // avoid a feedback loop.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [effectiveCron, on, input]);

  const inputClass = clsx(
    'rounded-lg border border-border-light bg-surface-primary px-2.5 py-1.5',
    'text-sm text-content-primary',
    'focus:border-oe-blue focus:outline-none focus:ring-2 focus:ring-oe-blue/20',
  );

  const summary = useMemo(() => {
    if (!on || !effectiveCron) return null;
    const time = `${pad2(hour)}:${pad2(minute)}`;
    switch (freq) {
      case 'daily':
        return t('agents.schedule.summary_daily', {
          defaultValue: 'Runs every day at {{time}} UTC',
          time,
        });
      case 'weekly': {
        const day = WEEKDAYS.find((d) => d.value === dow);
        return t('agents.schedule.summary_weekly', {
          defaultValue: 'Runs every {{day}} at {{time}} UTC',
          day: day ? t(day.labelKey, { defaultValue: day.defaultLabel }) : '',
          time,
        });
      }
      case 'monthly':
        return t('agents.schedule.summary_monthly', {
          defaultValue: 'Runs on day {{dom}} of each month at {{time}} UTC',
          dom,
          time,
        });
      default:
        return t('agents.schedule.summary_custom', {
          defaultValue: 'Runs on schedule: {{cron}} (UTC)',
          cron: effectiveCron,
        });
    }
  }, [on, effectiveCron, freq, hour, minute, dow, dom, t]);

  return (
    <div className="space-y-3">
      {/* Enable toggle */}
      <label className="flex cursor-pointer items-center gap-2.5">
        <input
          type="checkbox"
          checked={on}
          onChange={(e) => setOn(e.target.checked)}
          className="h-4 w-4 rounded border-border text-oe-blue focus:ring-oe-blue/30"
        />
        <span className="flex items-center gap-1.5 text-sm font-medium text-content-secondary">
          <Clock className="h-4 w-4 text-oe-blue" aria-hidden="true" />
          {t('agents.schedule.enable', { defaultValue: 'Run this agent automatically on a schedule' })}
        </span>
      </label>

      {on && (
        <div className="space-y-3 rounded-xl border border-border-light bg-surface-secondary/40 p-3">
          {/* Frequency */}
          <div className="flex flex-wrap items-center gap-1.5">
            {(['daily', 'weekly', 'monthly', 'custom'] as Frequency[]).map((f) => (
              <button
                key={f}
                type="button"
                onClick={() => setFreq(f)}
                aria-pressed={freq === f}
                className={clsx(
                  'rounded-full border px-3 py-1.5 text-xs font-medium transition-all',
                  freq === f
                    ? 'border-oe-blue/20 bg-oe-blue/10 text-oe-blue'
                    : 'border-transparent bg-surface-secondary text-content-secondary hover:bg-surface-tertiary',
                )}
              >
                {t(`agents.schedule.freq_${f}`, {
                  defaultValue:
                    f === 'daily'
                      ? 'Daily'
                      : f === 'weekly'
                        ? 'Weekly'
                        : f === 'monthly'
                          ? 'Monthly'
                          : 'Custom cron',
                })}
              </button>
            ))}
          </div>

          {freq !== 'custom' ? (
            <div className="flex flex-wrap items-end gap-3">
              {/* Time */}
              <div>
                <span className="mb-1 block text-2xs font-medium uppercase tracking-wide text-content-tertiary">
                  {t('agents.schedule.time', { defaultValue: 'Time (UTC)' })}
                </span>
                <div className="flex items-center gap-1">
                  <select
                    value={hour}
                    onChange={(e) => setHour(Number(e.target.value))}
                    aria-label={t('agents.schedule.hour', { defaultValue: 'Hour' })}
                    className={inputClass}
                  >
                    {Array.from({ length: 24 }, (_, i) => (
                      <option key={i} value={i}>
                        {pad2(i)}
                      </option>
                    ))}
                  </select>
                  <span className="text-content-tertiary">:</span>
                  <select
                    value={minute}
                    onChange={(e) => setMinute(Number(e.target.value))}
                    aria-label={t('agents.schedule.minute', { defaultValue: 'Minute' })}
                    className={inputClass}
                  >
                    {[0, 15, 30, 45].map((mm) => (
                      <option key={mm} value={mm}>
                        {pad2(mm)}
                      </option>
                    ))}
                  </select>
                </div>
              </div>

              {freq === 'weekly' && (
                <div>
                  <span className="mb-1 block text-2xs font-medium uppercase tracking-wide text-content-tertiary">
                    {t('agents.schedule.day', { defaultValue: 'Day of week' })}
                  </span>
                  <select
                    value={dow}
                    onChange={(e) => setDow(Number(e.target.value))}
                    className={inputClass}
                  >
                    {WEEKDAYS.map((d) => (
                      <option key={d.value} value={d.value}>
                        {t(d.labelKey, { defaultValue: d.defaultLabel })}
                      </option>
                    ))}
                  </select>
                </div>
              )}

              {freq === 'monthly' && (
                <div>
                  <span className="mb-1 block text-2xs font-medium uppercase tracking-wide text-content-tertiary">
                    {t('agents.schedule.dom', { defaultValue: 'Day of month' })}
                  </span>
                  <select
                    value={dom}
                    onChange={(e) => setDom(Number(e.target.value))}
                    className={inputClass}
                  >
                    {Array.from({ length: 28 }, (_, i) => i + 1).map((d) => (
                      <option key={d} value={d}>
                        {d}
                      </option>
                    ))}
                  </select>
                </div>
              )}
            </div>
          ) : (
            <div>
              <label
                htmlFor="ca-raw-cron"
                className="mb-1 block text-2xs font-medium uppercase tracking-wide text-content-tertiary"
              >
                {t('agents.schedule.raw_cron', { defaultValue: 'Cron expression (5 fields, UTC)' })}
              </label>
              <input
                id="ca-raw-cron"
                type="text"
                value={rawCron}
                onChange={(e) => setRawCron(e.target.value)}
                placeholder="0 9 * * 1-5"
                className={clsx(inputClass, 'w-full font-mono')}
              />
            </div>
          )}

          {/* Scheduled instruction */}
          <div>
            <label
              htmlFor="ca-schedule-input"
              className="mb-1 block text-2xs font-medium uppercase tracking-wide text-content-tertiary"
            >
              {t('agents.schedule.input_label', { defaultValue: 'What should it do on each run? (optional)' })}
            </label>
            <textarea
              id="ca-schedule-input"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              rows={2}
              maxLength={2000}
              placeholder={t('agents.schedule.input_placeholder', {
                defaultValue: 'e.g. Summarise yesterday’s site progress and flag any blockers.',
              })}
              className={clsx(inputClass, 'w-full')}
            />
          </div>

          {/* Summary + next run */}
          {summary && (
            <p className="text-xs text-content-secondary">{summary}</p>
          )}
          {nextRunAt && (
            <p className="text-2xs text-content-tertiary">
              {t('agents.schedule.next_run', { defaultValue: 'Next run' })}: {nextRunAt} UTC
            </p>
          )}

          <div className="flex items-start gap-1.5 rounded-md bg-semantic-info-bg/60 px-2.5 py-1.5 text-2xs text-content-secondary">
            <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-semantic-info" aria-hidden="true" />
            <span>
              {t('agents.schedule.review_note', {
                defaultValue:
                  'Scheduled runs are saved like any run for you to review - nothing is applied automatically.',
              })}
            </span>
          </div>
        </div>
      )}
    </div>
  );
}

export default SchedulePanel;
