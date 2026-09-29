// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
//
// Pure helpers for the progress-rigor panel (T3.2). Kept out of the .tsx so
// they can be unit-tested without a DOM. The authoritative math lives in the
// backend engine (progress_math.py); the client-side step roll-up here only
// drives the live footer preview and must agree with the server (weighted
// average; plain mean when total weight is 0; milestone-below-100 caps the
// roll-up below complete).

import { toNum } from '@/shared/lib/money';
import type {
  ActivityProgressState,
  EvmWarningKey,
  PercentCompleteType,
  TypedActivityView,
  TypedProgressBody,
  TypedProgressResponse,
} from './api';
import { fmtPercent } from '@/shared/lib/formatters';

/** The panel's view of an activity, built from a typed-progress response. */
export function viewFromTyped(res: TypedProgressResponse): TypedActivityView {
  return {
    percent_complete_type: res.percent_complete_type,
    progress_pct: res.percent_complete,
    remaining_duration: res.remaining_duration,
    status: res.status,
    forecast_finish: res.forecast_finish,
    installed_units: res.installed_units,
    budgeted_units: res.budgeted_units,
    suspended_at: res.suspended_at,
    suspend_reason: res.suspend_reason,
  };
}

/**
 * Merge a suspend / resume / calendar answer into the view. That answer carries
 * no unit quantities, so they are kept; the forecast finish is dropped because
 * suspending or resuming moves it and the answer does not say where to.
 */
export function mergeProgressState(view: TypedActivityView, state: ActivityProgressState): TypedActivityView {
  return {
    ...view,
    percent_complete_type: state.percent_complete_type,
    progress_pct: state.progress_pct,
    remaining_duration: state.remaining_duration,
    status: state.status,
    forecast_finish: null,
    suspended_at: state.suspended_at,
    suspend_reason: state.suspend_reason,
  };
}

/**
 * The typed-progress body for a units save. A blank input is left out rather
 * than sent as 0: the server keeps the stored quantity for an omitted field,
 * while a 0 would overwrite it.
 */
export function unitsProgressBody(installed: string, budgeted: string): TypedProgressBody {
  const body: TypedProgressBody = { percent_complete_type: 'units' };
  if (String(installed).trim() !== '') body.installed_units = toNum(installed);
  if (String(budgeted).trim() !== '') body.budgeted_units = toNum(budgeted);
  return body;
}

export interface StepLike {
  weight: string | number;
  percent_complete: string | number;
  is_milestone?: boolean;
}

/** Sum of step weights. */
export function totalWeight(steps: StepLike[]): number {
  return steps.reduce((sum, s) => sum + toNum(s.weight), 0);
}

/**
 * Client mirror of the server step roll-up. Returns a 0..100 percent.
 *
 * - no steps -> 0
 * - total weight 0 -> plain mean of the step percents
 * - otherwise -> weighted average
 * - any milestone step below 100 caps the result at 99.999
 */
export function rollupSteps(steps: StepLike[]): number {
  if (!steps.length) return 0;
  const tw = totalWeight(steps);
  let rolled: number;
  if (tw === 0) {
    rolled = steps.reduce((sum, s) => sum + toNum(s.percent_complete), 0) / steps.length;
  } else {
    rolled = steps.reduce((sum, s) => sum + toNum(s.weight) * toNum(s.percent_complete), 0) / tw;
  }
  const hasOpenMilestone = steps.some((s) => s.is_milestone && toNum(s.percent_complete) < 100);
  if (hasOpenMilestone && rolled > 99.999) rolled = 99.999;
  return Math.min(100, Math.max(0, rolled));
}

/** PV as a percent of BAC, or '-' when BAC is zero/unknown. */
export function pvPercentOfBac(pv: string | number | null | undefined, bac: string | number | null | undefined): string {
  const p = toNum(pv);
  const b = toNum(bac);
  if (!b) return '-';
  return fmtPercent((p / b) * 100);
}

/** i18n default-value text for each deterministic EVM-distortion warning key. */
export const EVM_WARNING_DEFAULTS: Record<EvmWarningKey, string> = {
  units_type_without_budgeted_units:
    'Units type with no budgeted quantity - % cannot be derived from quantity.',
  duration_type_on_nonlinear_cost:
    'Duration type on front/back-loaded cost - earning by time will misstate EV.',
  physical_manual_pct_is_subjective:
    'Manual physical % with no steps - the percent is subjective and unverified.',
  all_steps_zero_weight: 'All steps have zero weight - the roll-up degrades to a plain average.',
};

/** The three percent-complete types in canonical (UI) order. */
export const PERCENT_TYPES: readonly PercentCompleteType[] = ['duration', 'units', 'physical'];
