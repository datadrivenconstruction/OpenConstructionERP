// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Form logic for "Create new position" in the takeoff link-to-bill picker:
 * which sections the position can go into, the default section, the unit the
 * position is stated in and the quantity preview the estimator confirms.
 *
 * The server creates the position and computes its quantity
 * (`POST /v1/takeoff/measurements/{id}/create-boq-position/`); the preview
 * here uses the same fold (`effectiveQuantity` / `effectiveUnit`) so what the
 * picker shows is what lands in the bill.
 *
 * Pure and React-free so it unit-tests on its own.
 */

import type { MeasurementSystem } from '@/stores/usePreferencesStore';
import { convertUnit } from '@/shared/lib/unitConversion';
import type { Measurement } from './takeoff-types';
import { effectiveUnit, reportedMagnitude } from './takeoff-quantity';

/** The fields of a BOQ position the section picker reads. */
export interface PositionLike {
  id: string;
  ordinal: string;
  description?: string | null;
  unit?: string | null;
  parent_id?: string | null;
  sort_order?: number;
}

export interface SectionOption {
  id: string;
  label: string;
}

/** A section is a position without a unit (the BOQ's `isSection` rule). */
function isSectionRow(p: PositionLike): boolean {
  const unit = (p.unit ?? '').trim().toLowerCase();
  return unit === '' || unit === 'section';
}

/** Sections of a bill in bill order, labelled "ordinal description". */
export function sectionOptions(positions: readonly PositionLike[]): SectionOption[] {
  return positions
    .filter(isSectionRow)
    .slice()
    .sort((a, b) =>
      (a.sort_order ?? 0) !== (b.sort_order ?? 0)
        ? (a.sort_order ?? 0) - (b.sort_order ?? 0)
        : (a.ordinal ?? '').localeCompare(b.ordinal ?? '', undefined, { numeric: true }),
    )
    .map((p) => ({
      id: p.id,
      label: [p.ordinal, (p.description ?? '').trim()].filter(Boolean).join(' '),
    }));
}

/**
 * Default section for a new position: the last section of the bill, the same
 * place the BOQ editor's "Add position" puts a line when nothing is selected.
 * Empty string (top level) when the bill has no sections.
 */
export function defaultSectionId(positions: readonly PositionLike[]): string {
  const sections = sectionOptions(positions);
  return sections.length > 0 ? sections[sections.length - 1]!.id : '';
}

/** Canonical metric unit code of a reported quantity (`m²` -> `m2`). */
export function canonicalReportedUnit(m: Measurement): string {
  const unit = effectiveUnit(m) || '';
  return unit.replace('²', '2').replace('³', '3');
}

/**
 * Unit the new position is stated in: the canonical metric unit, or its
 * imperial counterpart (`m2` -> `ft2`) for a reader working in imperial, so
 * an imperial bill is priced per square foot. Units with no imperial
 * counterpart (pcs) stay as they are.
 */
export function positionUnitFor(m: Measurement, system: MeasurementSystem): string {
  const metric = canonicalReportedUnit(m);
  if (system !== 'imperial' || !metric) return metric;
  return convertUnit(0, metric, 'imperial').unit || metric;
}

/** Quantity preview in the position's unit, rounded to 4 decimals like the bill. */
export function positionQuantityFor(m: Measurement, system: MeasurementSystem): number {
  const metric = reportedMagnitude(m);
  const value =
    system === 'imperial' ? convertUnit(metric, canonicalReportedUnit(m), 'imperial').value : metric;
  return Math.round(value * 1e4) / 1e4;
}
