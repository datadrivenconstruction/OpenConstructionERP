// Design module (ERP side of the design editor link).
/** Schedule delta of a revision (ddc-schedule-impact/1), as the server computes it with the ERP's CPM. */

export interface RateSource {
  title: string;
  publisher: string;
  country: string;
  url: string;
  page: string;
  published: string;
  retrieved: string;
  quote: string;
}

export interface ScheduleRow {
  rule: string;
  label: string;
  /** Empty for a whole-building activity. */
  storey: string;
  activity_id: string | null;
  new_activity: boolean;
  current_days: number | null;
  model_days_now: number | null;
  model_days_new: number;
  new_days: number;
  delta_days: number;
  override: boolean;
  override_days: number | null;
  flags: string[];
  quantity: string;
  unit: string;
  provenance: { worked?: string; source?: RateSource; crew?: number; crew_source?: string } & Record<string, unknown>;
}

export interface ScheduleImpact {
  schema: 'ddc-schedule-impact/1';
  revision_id: string;
  /** False when the project has no design schedule: there is nothing to compare. */
  schedule: boolean;
  schedule_id?: string;
  start?: string;
  rows?: ScheduleRow[];
  totals?: {
    current_finish: string | null;
    after_finish: string | null;
    current_days: number;
    after_days: number;
    delta_days: number;
    activities_added: number;
    overrides_kept: number;
  };
  rate_missing?: { rule: string; label: string; unit: string; missing: string; quantity: string }[];
  not_scheduled?: { rule: string; label: string; reason: string }[];
  complete?: boolean;
}

/** Rows a person should see: a new activity, a changed duration, a kept override, or work that left the model. */
export function changedRows(rows: ScheduleRow[]): ScheduleRow[] {
  return rows.filter((r) => r.new_activity || r.delta_days !== 0 || r.override || r.flags.includes('no_match'));
}

/** A day count with its sign: +3, -2, 0. */
export function signedDays(n: number): string {
  return n > 0 ? `+${n}` : String(n);
}

/** An ISO date in the page language; the raw value when it is not a date. */
export function day(value: string | null | undefined, locale?: string): string {
  if (!value) return '—';
  const d = new Date(`${value.slice(0, 10)}T00:00:00Z`);
  return Number.isNaN(d.getTime()) ? value : d.toLocaleDateString(locale, { timeZone: 'UTC' });
}
