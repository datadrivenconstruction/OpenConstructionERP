// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Rule results as the validation endpoints return them, and the pure helpers
 * that turn them into traffic lights and translatable sentences.
 */

export interface RuleResult {
  rule_id: string;
  passed: boolean;
  severity: string;
  message: string;
  element_ref?: string | null;
  details?: Record<string, unknown> | null;
}

export type TrafficLight = 'red' | 'amber' | 'blue' | 'green';

/** Passed is green; a failure is red (error), amber (warning) or blue (anything softer). */
export function ruleLight(r: Pick<RuleResult, 'passed' | 'severity'>): TrafficLight {
  if (r.passed) return 'green';
  const s = (r.severity || '').toLowerCase();
  if (s === 'error' || s === 'critical') return 'red';
  if (s === 'warning') return 'amber';
  return 'blue';
}

/** Translation key and interpolation params carried by a rule result, if any. */
export function ruleMessage(r: RuleResult): { key: string | null; params: Record<string, string> } {
  const details = r.details ?? {};
  const key = typeof details.message_key === 'string' && details.message_key ? details.message_key : null;
  const params: Record<string, string> = {};
  for (const [k, v] of Object.entries(details)) {
    if (k !== 'message_key' && v !== null && v !== undefined) params[k] = String(v);
  }
  return { key, params };
}

export interface RuleTally {
  red: number;
  amber: number;
  blue: number;
  green: number;
}

export function tallyRules(results: readonly RuleResult[]): RuleTally {
  const tally: RuleTally = { red: 0, amber: 0, blue: 0, green: 0 };
  for (const r of results) tally[ruleLight(r)] += 1;
  return tally;
}

const LIGHT_ORDER: Record<TrafficLight, number> = { red: 0, amber: 1, blue: 2, green: 3 };

/** Failures first, worst first; passed results are left to the caller. */
export function failedRules(results: readonly RuleResult[]): RuleResult[] {
  return results
    .filter((r) => !r.passed)
    .sort((a, b) => LIGHT_ORDER[ruleLight(a)] - LIGHT_ORDER[ruleLight(b)]);
}
