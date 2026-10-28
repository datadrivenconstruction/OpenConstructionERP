// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Shared label helpers for the Last Planner / CPM (schedule-advanced)
// feature. Every status / type field arrives raw snake_case on the wire
// (in_planning, cannot_clear, at_risk, ...). Tables, badges and <select>
// options must show a localised, humanised label ("In planning", "Cannot
// clear", "At risk") rather than the verbatim enum value.
//
// i18n: each helper reads ``schedule_advanced.<ns>.<value>`` via
// t(key, { defaultValue }). Following the module convention (see
// scheduleAdvancedGuide.ts) the inline English defaults are the single
// source of truth - these keys are NOT added to en.ts; the /i18n-sweep
// workflow translates them into the other locales.

import type { TFunction } from 'i18next';

/** Humanise a raw snake_case value: ``cannot_clear`` -> ``Cannot clear``.
 *  Used as the fallback for any enum value without an explicit English
 *  default so a new backend status never leaks as raw snake_case. */
function prettify(value: string): string {
  const spaced = value.replace(/_/g, ' ').trim();
  if (!spaced) return value;
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

function label(
  t: TFunction,
  ns: string,
  value: string,
  englishByValue: Record<string, string>,
): string {
  return t(`schedule_advanced.${ns}.${value}`, {
    defaultValue: englishByValue[value] ?? prettify(value),
  });
}

const MASTER_STATUS_EN: Record<string, string> = {
  active: 'Active',
  archived: 'Archived',
};

const LOOKAHEAD_STATUS_EN: Record<string, string> = {
  draft: 'Draft',
  reviewed: 'Reviewed',
  published: 'Published',
};

const WEEKLY_STATUS_EN: Record<string, string> = {
  draft: 'Draft',
  committed: 'Committed',
  in_progress: 'In progress',
  closed: 'Closed',
};

const COMMITMENT_STATUS_EN: Record<string, string> = {
  planned: 'Planned',
  committed: 'Committed',
  in_progress: 'In progress',
  completed: 'Completed',
  at_risk: 'At risk',
  missed: 'Missed',
};

const CONSTRAINT_STATUS_EN: Record<string, string> = {
  open: 'Open',
  in_progress: 'In progress',
  cleared: 'Cleared',
  escalated: 'Escalated',
  cannot_clear: 'Cannot clear',
};

const CONSTRAINT_TYPE_EN: Record<string, string> = {
  info: 'Information',
  material: 'Material',
  labor: 'Labour',
  equipment: 'Equipment',
  permit: 'Permit',
  predecessor: 'Predecessor',
  weather: 'Weather',
  other: 'Other',
};

const BASELINE_STATUS_EN: Record<string, string> = {
  active: 'Active',
  superseded: 'Superseded',
  archived: 'Archived',
};

const TASK_STATUS_EN: Record<string, string> = {
  draft: 'Draft',
  open: 'Open',
  in_progress: 'In progress',
  completed: 'Completed',
};

export const masterStatusLabel = (t: TFunction, v: string): string =>
  label(t, 'master_status', v, MASTER_STATUS_EN);

export const lookAheadStatusLabel = (t: TFunction, v: string): string =>
  label(t, 'lookahead_status', v, LOOKAHEAD_STATUS_EN);

export const weeklyStatusLabel = (t: TFunction, v: string): string =>
  label(t, 'weekly_status', v, WEEKLY_STATUS_EN);

export const commitmentStatusLabel = (t: TFunction, v: string): string =>
  label(t, 'commitment_status', v, COMMITMENT_STATUS_EN);

export const constraintStatusLabel = (t: TFunction, v: string): string =>
  label(t, 'constraint_status', v, CONSTRAINT_STATUS_EN);

export const constraintTypeLabel = (t: TFunction, v: string): string =>
  label(t, 'constraint_type', v, CONSTRAINT_TYPE_EN);

export const baselineStatusLabel = (t: TFunction, v: string): string =>
  label(t, 'baseline_status', v, BASELINE_STATUS_EN);

export const taskStatusLabel = (t: TFunction, v: string): string =>
  label(t, 'task_status', v, TASK_STATUS_EN);
