// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Client checks that run on every edit, for immediacy. They mirror server
 * rules; the server result on save is the record. Packages add their own
 * checks (`registerLiveCheck`), e.g. P2's parcel ring checks.
 */

import type { GridXY, PlanFeature } from '../types';
import { ringSelfIntersections } from './geometry';
import { parseCode, lineworkProblems, type CodeEntry, type CodedPoint } from './linework';

export interface LiveFinding {
  ruleId: string;
  severity: 'error' | 'warning' | 'info';
  featureId?: string;
  messageKey: string;
  defaultMessage: string;
  params?: Record<string, string | number>;
  /** Where to mark it on the plan (a red X for a crossing). */
  at?: GridXY;
}

export interface LiveCheckInput {
  features: readonly PlanFeature[];
  codes: readonly CodeEntry[];
  points: readonly CodedPoint[];
}

export type LiveCheck = (input: LiveCheckInput) => LiveFinding[];

const registry = new Map<string, LiveCheck>();

/** Add a check under a stable name; returns the unregister function. */
export function registerLiveCheck(name: string, check: LiveCheck): () => void {
  registry.set(name, check);
  return () => {
    if (registry.get(name) === check) registry.delete(name);
  };
}

/** Rings of sketch features: closed and not crossing themselves. */
export const ringCheck: LiveCheck = ({ features }) => {
  const out: LiveFinding[] = [];
  for (const f of features) {
    if (f.geometry.type !== 'Polygon') continue;
    const ring = f.geometry.coordinates[0] ?? [];
    if (ring.length < 3) {
      out.push({ ruleId: 'SRV-142', severity: 'warning', featureId: f.id, messageKey: 'plan.check.ring_open', defaultMessage: 'The ring needs at least three vertices' });
      continue;
    }
    for (const at of ringSelfIntersections(ring)) {
      out.push({ ruleId: 'SRV-143', severity: 'error', featureId: f.id, at, messageKey: 'plan.check.ring_crosses', defaultMessage: 'The ring crosses itself' });
    }
  }
  return out;
};

/** Point codes missing from the library, and strings that cannot draw. */
export const codeCheck: LiveCheck = ({ codes, points }) => {
  if (codes.length === 0) return [];
  const out: LiveFinding[] = [];
  const unknown = new Map<string, number>();
  for (const p of points) {
    if (!p.code) continue;
    const parsed = parseCode(p.code, codes);
    if (!parsed.entry) unknown.set(parsed.base || p.code, (unknown.get(parsed.base || p.code) ?? 0) + 1);
  }
  for (const [code, count] of unknown) {
    out.push({ ruleId: 'SRV-140', severity: 'info', messageKey: 'plan.check.code_unknown', defaultMessage: 'Code {{code}} is not in the code library ({{count}} points)', params: { code, count } });
  }
  for (const p of lineworkProblems(points, codes)) {
    out.push({
      ruleId: 'SRV-141',
      severity: 'warning',
      messageKey: p.closed ? 'plan.check.string_short_closed' : 'plan.check.string_short',
      defaultMessage: p.closed ? 'String {{key}} is closed but has only {{count}} points' : 'String {{key}} has a single point',
      params: { key: p.key, count: p.count },
    });
  }
  return out;
};

registerLiveCheck('core.ring', ringCheck);
registerLiveCheck('core.codes', codeCheck);

export function runLiveChecks(input: LiveCheckInput): LiveFinding[] {
  const out: LiveFinding[] = [];
  for (const check of registry.values()) out.push(...check(input));
  return out;
}
