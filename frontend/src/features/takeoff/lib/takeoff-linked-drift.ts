// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Has the bill fallen behind the drawing? A linked measurement wrote its
 * reported quantity into a bill position once. When the measurement is
 * changed afterwards (redrawn, a wall height or an opening added), nothing
 * re-pushes it, on purpose: the position may have been edited by hand since.
 * This compares the two so the takeoff can ASK ("bill 27.51 m2, measured
 * 68.40 m2, update the bill?") and a person decides.
 *
 * Pure and React-free so it unit-tests on its own.
 */

import { convertBetween } from '@/shared/lib/unitConversion';
import type { Measurement } from './takeoff-types';
import { reportedMagnitude } from './takeoff-quantity';
import { canonicalReportedUnit } from './takeoff-create-position';

/** The fields of a bill position the comparison reads. */
export interface LinkedPositionLike {
  id: string;
  quantity: number | string | null | undefined;
  unit?: string | null;
  metadata?: Record<string, unknown> | null;
}

export interface LinkedQuantityDrift<P extends LinkedPositionLike> {
  position: P;
  /** Quantity the bill holds now, in the position's unit. */
  billQuantity: number;
  /** The measurement's reported quantity restated in the position's unit. */
  measuredQuantity: number;
  /** The position's unit, or the measurement's when the position has none. */
  unit: string;
}

const round4 = (v: number): number => Math.round(v * 1e4) / 1e4;

/**
 * The difference between a linked measurement and its bill position, or
 * `null` when there is nothing to propose: not linked, the position is not
 * among `positions`, the units cannot be converted, the figures agree to the
 * bill's 4 decimals, or the position is fed by more than one measurement (a
 * one-row update would then overwrite the others' share). `measurements`
 * only holds the open drawing, so the position's own stamp
 * (`metadata.pdf_measurement_id`, written by every link path that knows the
 * measurement) must also name this row: a position last written from another
 * drawing is not this row's to update.
 */
export function linkedQuantityDrift<P extends LinkedPositionLike>(
  m: Measurement,
  positions: readonly P[],
  measurements: readonly Pick<Measurement, 'linkedPositionId'>[],
): LinkedQuantityDrift<P> | null {
  const positionId = m.linkedPositionId;
  if (!positionId || m.isDeduction || m.suggested) return null;
  if (measurements.filter((x) => x.linkedPositionId === positionId).length > 1) return null;
  const position = positions.find((p) => p.id === positionId);
  if (!position) return null;
  const stamp = position.metadata?.pdf_measurement_id;
  if (stamp != null && stamp !== '' && String(stamp) !== m.serverId && String(stamp) !== m.id) return null;
  const billQuantity = Number(position.quantity);
  if (!Number.isFinite(billQuantity)) return null;
  const metricUnit = canonicalReportedUnit(m);
  const positionUnit = (position.unit ?? '').trim();
  const measured = positionUnit
    ? convertBetween(reportedMagnitude(m), metricUnit, positionUnit)
    : reportedMagnitude(m);
  if (measured === null || !Number.isFinite(measured)) return null;
  const measuredQuantity = round4(measured);
  if (measuredQuantity === round4(billQuantity)) return null;
  return { position, billQuantity, measuredQuantity, unit: positionUnit || metricUnit };
}
