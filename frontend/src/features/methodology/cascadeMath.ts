// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Pure, client-side preview of the markup cascade.
//
// This faithfully mirrors the backend engine in
// backend/app/modules/methodology/cascade.py so the editor can show a live
// "what would this total be" preview WITHOUT a backend round-trip on every
// keystroke. The authoritative computation is always the backend POST
// /api/v1/methodology/compute (used when a methodology is saved / applied to a
// real BOQ); this is a faithful estimate for the editor only.
//
// Behaviour parity with the backend:
//   * Each leaf base is rounded to `decimals` places (ROUND_HALF_UP) up front.
//   * A composite is the sum of its member leaf bases, rounded.
//   * direct_total = sum of all leaf bases.
//   * Each step's base_amount = sum of its resolved tokens (leaf base,
//     composite, or an EARLIER step's rounded amount), rounded; then for a
//     percentage step amount = round(base_amount * rate / 100), and for a fixed
//     step amount = round(step.amount).
//   * A step may only reference earlier steps; forward / self references are
//     errors. Unknown tokens, duplicate keys and base/composite/step name
//     collisions are errors.
//   * markup_total = sum of step amounts; grand_total = direct_total +
//     markup_total.
//
// JS has no Decimal, so we round at every step exactly where the backend does.
// For the editor's preview (sample resource totals) this matches the backend to
// the rounding unit; it is not a substitute for the server's exact Decimal math
// on persisted money.

import { toNum } from './api';
import type { MarkupStep } from './types';

/** A resolved cascade step, mirroring the backend StepResult. */
export interface PreviewStepResult {
  key: string;
  label: string;
  category: string;
  kind: 'percentage' | 'fixed';
  /** Rate actually applied (0 for fixed steps). */
  rate: number;
  /** Sum of the step's base tokens that the rate applied to. */
  baseAmount: number;
  /** The rounded step result. */
  amount: number;
  /** direct_total plus all step amounts up to and including this step. */
  runningTotal: number;
}

/** The full preview result, mirroring the backend CascadeResult. */
export interface PreviewResult {
  bases: Record<string, number>;
  composites: Record<string, number>;
  steps: PreviewStepResult[];
  directTotal: number;
  markupTotal: number;
  grandTotal: number;
}

/** Raised when a cascade preview cannot be computed (mirrors CascadeError). */
export class CascadePreviewError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'CascadePreviewError';
  }
}

/** Round half-up to `decimals` places. Mirrors Decimal ROUND_HALF_UP. */
export function roundTo(value: number, decimals: number): number {
  if (!Number.isFinite(value)) return 0;
  if (decimals < 0) {
    throw new CascadePreviewError(`decimals must be non-negative, got ${decimals}`);
  }
  const factor = Math.pow(10, decimals);
  // Nudge by a tiny epsilon (scaled to magnitude) so values that are exactly
  // .5 in decimal but land just below in binary float (e.g. 2.675) still round
  // half-up, matching Decimal's behaviour on the inputs a preview sees.
  const scaled = value * factor;
  const eps = Math.sign(scaled) * 1e-9 * Math.max(1, Math.abs(scaled));
  return Math.round(scaled + eps) / factor;
}

/**
 * Compute a cascade preview.
 *
 * @param params.bases        Leaf base token -> amount (already resolved from
 *                            resource totals via the methodology base_mapping).
 * @param params.composites   Composite name -> member leaf base tokens.
 * @param params.steps        Ordered markup steps.
 * @param params.decimals     Rounding precision (default 2).
 */
export function computeCascadePreview(params: {
  bases: Record<string, number>;
  composites: Record<string, string[]>;
  steps: MarkupStep[];
  decimals?: number;
}): PreviewResult {
  const decimals = params.decimals ?? 2;

  // Resolve + round leaf bases up front.
  const resolvedBases: Record<string, number> = {};
  for (const [name, raw] of Object.entries(params.bases)) {
    resolvedBases[name] = roundTo(toNum(raw), decimals);
  }

  // Validate + resolve composites against the leaf bases.
  const resolvedComposites: Record<string, number> = {};
  for (const [compName, members] of Object.entries(params.composites)) {
    if (compName in resolvedBases) {
      throw new CascadePreviewError(
        `composite '${compName}' collides with a leaf base of the same name`,
      );
    }
    let total = 0;
    for (const member of members) {
      if (!(member in resolvedBases)) {
        throw new CascadePreviewError(
          `composite '${compName}' references unknown leaf base '${member}'`,
        );
      }
      total += resolvedBases[member] ?? 0;
    }
    resolvedComposites[compName] = roundTo(total, decimals);
  }

  const directTotal = roundTo(
    Object.values(resolvedBases).reduce((a, b) => a + b, 0),
    decimals,
  );

  const seenStepKeys = new Set<string>();
  const stepAmounts: Record<string, number> = {};
  const stepResults: PreviewStepResult[] = [];
  let runningTotal = directTotal;
  let markupTotal = 0;

  const stepKeyByIndex = params.steps.map((s) => s.key);

  params.steps.forEach((step, index) => {
    if (step.kind !== 'percentage' && step.kind !== 'fixed') {
      throw new CascadePreviewError(
        `step '${step.key}' has unknown kind '${step.kind}'`,
      );
    }
    if (seenStepKeys.has(step.key)) {
      throw new CascadePreviewError(`duplicate step key '${step.key}'`);
    }
    if (step.key in resolvedBases || step.key in resolvedComposites) {
      throw new CascadePreviewError(
        `step key '${step.key}' collides with a base or composite name`,
      );
    }

    let baseAmount = 0;
    for (const token of step.base) {
      if (token in resolvedBases) {
        baseAmount += resolvedBases[token] ?? 0;
      } else if (token in resolvedComposites) {
        baseAmount += resolvedComposites[token] ?? 0;
      } else if (token in stepAmounts) {
        baseAmount += stepAmounts[token] ?? 0;
      } else if (token === step.key) {
        throw new CascadePreviewError(
          `step '${step.key}' references itself in its base`,
        );
      } else if (stepKeyByIndex.indexOf(token, index) >= 0) {
        throw new CascadePreviewError(
          `step '${step.key}' forward-references step '${token}' ` +
            `(a step may only reference earlier steps)`,
        );
      } else {
        throw new CascadePreviewError(
          `step '${step.key}' references unknown token '${token}' ` +
            `(not a base, composite, or earlier step)`,
        );
      }
    }

    baseAmount = roundTo(baseAmount, decimals);

    let amount: number;
    let appliedRate: number;
    if (step.kind === 'percentage') {
      amount = roundTo((baseAmount * toNum(step.rate)) / 100, decimals);
      appliedRate = toNum(step.rate);
    } else {
      amount = roundTo(toNum(step.amount), decimals);
      appliedRate = 0;
    }

    seenStepKeys.add(step.key);
    stepAmounts[step.key] = amount;
    markupTotal += amount;
    runningTotal += amount;

    stepResults.push({
      key: step.key,
      label: step.label,
      category: step.category,
      kind: step.kind,
      rate: appliedRate,
      baseAmount,
      amount,
      runningTotal,
    });
  });

  markupTotal = roundTo(markupTotal, decimals);
  const grandTotal = roundTo(directTotal + markupTotal, decimals);

  return {
    bases: resolvedBases,
    composites: resolvedComposites,
    steps: stepResults,
    directTotal,
    markupTotal,
    grandTotal,
  };
}

/**
 * Resolve cascade leaf-base amounts from a methodology base_mapping and a
 * per-resource-type totals map. Mirrors backend bases.resolve_bases: each base
 * token's amount is the sum of resource_totals over its mapped resource types;
 * a mapped resource type absent from the totals contributes 0.
 *
 * When base_mapping is empty (a bare flat template), the backend falls back to
 * a single "direct" base equal to the sum of all resource totals; this mirrors
 * that so the preview is correct for the international default too.
 */
export function resolveBasesFromResourceTotals(
  baseMapping: Record<string, string[]>,
  resourceTotals: Record<string, number>,
): Record<string, number> {
  const keys = Object.keys(baseMapping);
  if (keys.length === 0) {
    const total = Object.values(resourceTotals).reduce((a, b) => a + toNum(b), 0);
    return { direct: total };
  }
  const out: Record<string, number> = {};
  for (const [token, types] of Object.entries(baseMapping)) {
    let total = 0;
    for (const t of types) total += toNum(resourceTotals[t]);
    out[token] = total;
  }
  return out;
}

const DEFAULT_SAMPLE_TYPES = ['labor', 'material', 'machinery', 'equipment', 'subcontractor'];

/** Resource types the sample inputs offer: exactly those the base mapping
 *  consumes, so a field never counts for nothing. */
export function sampleResourceTypes(baseMapping: Record<string, string[]>): string[] {
  const seen = new Set<string>();
  for (const types of Object.values(baseMapping)) for (const t of types) seen.add(t);
  return seen.size > 0 ? [...seen] : DEFAULT_SAMPLE_TYPES;
}
