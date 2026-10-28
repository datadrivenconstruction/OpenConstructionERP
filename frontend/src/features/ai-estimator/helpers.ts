// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Shared presentation helpers for the AI Estimate Builder. Score-band
// thresholds live ONLY here so the per-group match card, the run list and
// the assembly review never drift apart (the 4-file drift the dossier
// warns about).
import type { ConfidenceBand, GroupStatus, RunStatus, ValidationStatus } from './api';
import { DEFAULT_THRESHOLDS, type ScoreThresholds } from './meta';


/** Tailwind classes for a score badge (matches AICostFinderPanel).
 *
 *  The green / amber / gray cutoffs are server-driven (GET /meta -
 *  `score_thresholds`); pass the active thresholds from `useScoreThresholds()`
 *  so the bands never drift from the backend's confidence bands. Defaults to
 *  the contract values when called without thresholds. */
export function scoreColor(
  score: number | null | undefined,
  thresholds: ScoreThresholds = DEFAULT_THRESHOLDS,
): string {
  if (score == null) return 'bg-gray-100 text-gray-500 dark:bg-gray-800 dark:text-gray-400';
  if (score >= thresholds.high)
    return 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400';
  if (score >= thresholds.low)
    return 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400';
  return 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400';
}

/** Tailwind border classes for a candidate / group card by score. */
export function scoreBorder(
  score: number | null | undefined,
  thresholds: ScoreThresholds = DEFAULT_THRESHOLDS,
): string {
  if (score == null) return 'border-border-light';
  if (score >= thresholds.high) return 'border-green-200 dark:border-green-800';
  if (score >= thresholds.low) return 'border-amber-200 dark:border-amber-800';
  return 'border-border-light';
}

/** Parse a measurement value that may arrive as a JSON number or a
 *  Decimal-precision string into a finite number. Returns 0 for null /
 *  empty / unparseable input so display and arithmetic never produce NaN. */
export function toNum(value: number | string | null | undefined): number {
  if (value == null || value === '') return 0;
  const n = typeof value === 'number' ? value : Number(value);
  return Number.isFinite(n) ? n : 0;
}

/** Human percent for a [0,1] score, or an em-dash-free placeholder. */
export function scorePercent(score: number | null | undefined): string {
  if (score == null) return '-';
  return `${Math.round(score * 100)}%`;
}

/** Pill classes for a group status chip. */
export function groupStatusChip(status: GroupStatus): string {
  switch (status) {
    case 'confirmed':
    case 'applied':
      return 'bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-200';
    case 'suggested':
      return 'bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-200';
    case 'overridden':
      return 'bg-indigo-100 text-indigo-800 dark:bg-indigo-900/40 dark:text-indigo-200';
    case 'needs_human':
      return 'bg-rose-100 text-rose-800 dark:bg-rose-900/40 dark:text-rose-200';
    case 'skipped':
    case 'tbd':
      return 'bg-slate-100 text-slate-500 dark:bg-slate-800 dark:text-slate-400';
    default:
      return 'bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300';
  }
}

/** Pill classes for a run status chip. */
export function runStatusChip(status: RunStatus): string {
  switch (status) {
    case 'applied':
      return 'bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-200';
    case 'failed':
      return 'bg-rose-100 text-rose-800 dark:bg-rose-900/40 dark:text-rose-200';
    case 'cancelled':
      return 'bg-slate-100 text-slate-500 dark:bg-slate-800 dark:text-slate-400';
    case 'review':
      return 'bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-200';
    default:
      return 'bg-oe-blue/10 text-oe-blue';
  }
}

/** Traffic-light tone for a validation report status. */
export function validationTone(
  status: ValidationStatus | null | undefined,
): { dot: string; label: string; ring: string } {
  switch (status) {
    case 'passed':
      return { dot: 'bg-emerald-500', label: 'text-emerald-700 dark:text-emerald-300', ring: 'ring-emerald-500/30' };
    case 'warnings':
      return { dot: 'bg-amber-500', label: 'text-amber-700 dark:text-amber-300', ring: 'ring-amber-500/30' };
    case 'errors':
      return { dot: 'bg-rose-500', label: 'text-rose-700 dark:text-rose-300', ring: 'ring-rose-500/30' };
    default:
      return { dot: 'bg-slate-400', label: 'text-content-secondary', ring: 'ring-slate-400/30' };
  }
}

/** Confidence band -> short tone classes. */
export function bandTone(band: ConfidenceBand): string {
  switch (band) {
    case 'high':
      return 'text-emerald-600 dark:text-emerald-400';
    case 'medium':
      return 'text-amber-600 dark:text-amber-400';
    case 'low':
      return 'text-rose-600 dark:text-rose-400';
    default:
      return 'text-content-tertiary';
  }
}

/** Format a Decimal-as-string money value with its ISO currency. Falls
 *  back to a plain "value CUR" string when Intl rejects the code. Never
 *  blends currencies - the caller passes one currency per number. */
export function fmtMoneyStr(
  value: string | null | undefined,
  currency: string | null | undefined,
  locale?: string,
): string {
  if (value == null || value === '') return '-';
  const n = Number(value);
  if (Number.isNaN(n)) return `${value} ${currency ?? ''}`.trim();
  try {
    return new Intl.NumberFormat(locale, {
      style: currency ? 'currency' : 'decimal',
      currency: currency || undefined,
      maximumFractionDigits: 2,
    }).format(n);
  } catch {
    return `${n.toFixed(2)} ${currency ?? ''}`.trim();
  }
}

/** Resource-type -> short badge classes (labor/material/equipment/...). */
export function resourceTypeBadge(type: string): string {
  switch (type.toLowerCase()) {
    case 'labor':
      return 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300';
    case 'material':
      return 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-300';
    case 'equipment':
    case 'operator':
      return 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300';
    case 'electricity':
      return 'bg-violet-100 text-violet-700 dark:bg-violet-900/30 dark:text-violet-300';
    default:
      return 'bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300';
  }
}
