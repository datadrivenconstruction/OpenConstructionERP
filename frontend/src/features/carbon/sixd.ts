// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Pure helpers for the 6D (BIM auto-enrich) carbon flow. No React, no i18next
// here: each label helper returns a stable key + English default so the
// component resolves it through t(key, { defaultValue }). Kept side-effect free
// so it can be unit-tested without a DOM.

import type { AutoEnrichBimResult, EmbodiedSource } from './api';
import { fmtFixed } from '@/shared/lib/formatters';

/** Subset of the design-system Badge variants the source pill uses. Narrower
 *  than Badge's full union on purpose, and assignable to it. */
export type SourcePillVariant = 'neutral' | 'blue';

/** Plain-number summary of an auto-enrich pass, ready for display. */
export interface EnrichSummary {
  /** Elements matched to a factor (created, or creatable in a dry run). */
  created: number;
  /** Elements skipped because no material carbon factor matched. */
  skippedNoMatch: number;
  /** Elements skipped because they carried no usable quantity. */
  skippedNoQuantity: number;
  /** Elements skipped because this inventory already has an auto-enriched
   *  entry linked to them (idempotency - re-running never double-counts). */
  skippedExisting: number;
  /** All skipped elements (no-match + no-quantity + already-linked). */
  totalSkipped: number;
  /** Every element the pass looked at. */
  totalConsidered: number;
  /** True when there is at least one proposal worth confirming. */
  hasProposals: boolean;
}

/** A non-negative integer view of a possibly-missing counter. */
function count(value: number | null | undefined): number {
  if (typeof value !== 'number' || !Number.isFinite(value) || value < 0) return 0;
  return Math.floor(value);
}

/**
 * Fold an {@link AutoEnrichBimResult} into display counters. Tolerates a
 * partial / malformed payload (missing counters become 0) so the preview UI
 * never renders NaN.
 */
export function summarizeEnrich(result: AutoEnrichBimResult | null | undefined): EnrichSummary {
  // The matched/creatable count is the number of proposals the pass returned.
  // A dry-run preview reports created=0 (nothing persisted yet) while still
  // returning every proposal in `entries`, so count the proposals directly and
  // fall back to the persisted counter only when `entries` is absent.
  const created = Array.isArray(result?.entries)
    ? result.entries.length
    : count(result?.created);
  const skippedNoMatch = count(result?.skipped_no_match);
  const skippedNoQuantity = count(result?.skipped_no_quantity);
  const skippedExisting = count(result?.skipped_existing);
  const totalSkipped = skippedNoMatch + skippedNoQuantity + skippedExisting;
  return {
    created,
    skippedNoMatch,
    skippedNoQuantity,
    skippedExisting,
    totalSkipped,
    totalConsidered: created + totalSkipped,
    hasProposals: created > 0,
  };
}

/** A label resolvable through i18next: stable key plus its English default. */
export interface SourceLabelDescriptor {
  key: string;
  defaultValue: string;
}

/**
 * Map an embodied-entry source to a short pill label. An absent / unknown
 * source is treated as manual, matching the backend's legacy-row behaviour.
 */
export function sourceLabel(source: EmbodiedSource | null | undefined): SourceLabelDescriptor {
  switch (source) {
    case 'auto_enriched':
      return { key: 'carbon.sixd.source_auto', defaultValue: 'Auto from BIM' };
    case 'boq_derived':
      return { key: 'carbon.sixd.source_boq', defaultValue: 'From BOQ' };
    case 'manual':
    default:
      return { key: 'carbon.sixd.source_manual', defaultValue: 'Manual' };
  }
}

/** Badge colour for a source pill. Auto-from-BIM stands out (blue); the
 *  others are quiet neutrals so the list stays calm. */
export function sourcePillVariant(source: EmbodiedSource | null | undefined): SourcePillVariant {
  return source === 'auto_enriched' ? 'blue' : 'neutral';
}

/* --- 6D Phase 2: whole-life helpers (carbon + cost) --- */

/** Non-negative float view of a possibly-missing / string numeric value. Kept
 *  separate from {@link count} (which floors to an integer counter). */
export function toNumber(value: number | string | null | undefined): number {
  if (value === null || value === undefined) return 0;
  if (typeof value === 'number') return Number.isFinite(value) ? value : 0;
  const n = parseFloat(value);
  return Number.isFinite(n) ? n : 0;
}

/** Human kgCO2e with a magnitude unit (kg / t / kt). Mirrors the inventory
 *  drawer so the whole-life tab reads the same. */
export function formatCarbonKg(kg: number): string {
  const abs = Math.abs(kg);
  if (abs >= 1_000_000) return `${fmtFixed(kg / 1_000_000, 2)} kt`;
  if (abs >= 1_000) return `${fmtFixed(kg / 1_000, 2)} t`;
  return `${fmtFixed(kg, 0)} kg`;
}

/** Traffic-light band for a coverage percentage (0..100).
 *  - `none`: nothing linked (0% or absent) -> red.
 *  - `partial`: some but under the good threshold -> amber.
 *  - `good`: at or above the threshold -> green. */
export type CoverageTone = 'good' | 'partial' | 'none';

/** At/above this percentage a coverage row is considered well covered. */
export const COVERAGE_GOOD_MIN = 80;

export function coverageTone(pct: number | null | undefined): CoverageTone {
  if (typeof pct !== 'number' || !Number.isFinite(pct) || pct <= 0) return 'none';
  if (pct >= COVERAGE_GOOD_MIN) return 'good';
  return 'partial';
}

/** True only for a draft line, i.e. one that still needs a human accept /
 *  reject. Confirmed (or any other) status never shows the accept control. */
export function isDraftStatus(status: string | null | undefined): boolean {
  return status === 'draft';
}

/** Loose shape shared by the operational-carbon and whole-life-cost compute
 *  responses. Only the counters the preview UI reads are declared; the two
 *  skip fields differ per endpoint so both are optional. */
export interface ComputeCounters {
  created?: number | null;
  skipped_existing?: number | null;
  skipped_no_energy?: number | null;
  skipped_no_cost?: number | null;
  entries?: unknown[] | null;
}

/** Plain-number summary of a compute pass, ready for display. */
export interface ComputeSummary {
  /** Lines proposed (dry run) or persisted (real run). */
  created: number;
  /** Every skipped element (no signal + already computed). */
  skipped: number;
  /** Everything the pass looked at. */
  total: number;
  /** True when there is at least one line worth saving. */
  hasProposals: boolean;
}

/**
 * Fold an operational-carbon or whole-life-cost compute result into display
 * counters. Like {@link summarizeEnrich}, a dry-run reports `created=0` while
 * still returning every proposal in `entries`, so count `entries` first and
 * fall back to the persisted counter only when `entries` is absent.
 */
export function summarizeCompute(result: ComputeCounters | null | undefined): ComputeSummary {
  const created = Array.isArray(result?.entries) ? result.entries.length : count(result?.created);
  const skipped =
    count(result?.skipped_existing) +
    count(result?.skipped_no_energy) +
    count(result?.skipped_no_cost);
  return {
    created,
    skipped,
    total: created + skipped,
    hasProposals: created > 0,
  };
}
