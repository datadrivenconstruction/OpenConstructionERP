// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Keyboard input of a vertex: bearing + distance, relative offsets, absolute
 * coordinates, or polar from a station with a backsight (the field-book form).
 * Coordinates follow the axis convention, angles the angle unit and direction
 * format, distances the linear unit; a ground distance becomes grid by the CSF.
 */

import { INPUT_MODES, type GridXY, type InputMode, type PrecisionContext, type PrecisionFields, type PrecisionResult } from '../types';
import { azimuthOf, normalizeAzimuth, parseAngle, parseDirection } from '../units/angles';
import { fromDisplayOrder, groundToGrid, parseDistance } from '../units/linear';
import { polarPoint } from './geometry';

const fail = (field: string, errorKey: string, defaultError: string): PrecisionResult => ({ ok: false, field, errorKey, defaultError });

export function emptyFields(mode: InputMode): PrecisionFields {
  switch (mode) {
    case 'brg_dist':
      return { mode, bearing: '', distance: '' };
    case 'delta':
      return { mode, first: '', second: '' };
    case 'abs':
      return { mode, first: '', second: '', z: '' };
    case 'polar':
      return { mode, station: '', backsight: '', angle: '', distance: '' };
  }
}

/** Field names of a mode in Tab order. */
export function fieldOrder(mode: InputMode): string[] {
  return Object.keys(emptyFields(mode)).filter((k) => k !== 'mode');
}

export function nextMode(mode: InputMode): InputMode {
  return INPUT_MODES[(INPUT_MODES.indexOf(mode) + 1) % INPUT_MODES.length]!;
}

function gridDistance(text: string, ctx: PrecisionContext, field: string): number | PrecisionResult {
  const d = parseDistance(text, ctx.conventions);
  if (d == null) return fail(field, 'plan.input.bad_distance', 'Not a distance');
  if (d <= 0) return fail(field, 'plan.input.distance_positive', 'The distance must be above zero');
  return ctx.conventions.distanceInput === 'ground' ? groundToGrid(d, ctx.csf) : d;
}

function signedLength(text: string, ctx: PrecisionContext, field: string): number | PrecisionResult {
  const d = parseDistance(text, ctx.conventions);
  if (d == null) return fail(field, 'plan.input.bad_number', 'Not a number');
  return ctx.conventions.distanceInput === 'ground' ? groundToGrid(d, ctx.csf) : d;
}

/** The grid point the fields describe, or which field is wrong and why. */
export function parsePrecision(fields: PrecisionFields, ctx: PrecisionContext): PrecisionResult {
  const conv = ctx.conventions;
  switch (fields.mode) {
    case 'brg_dist': {
      if (!ctx.last) return fail('bearing', 'plan.input.needs_start', 'Place the first vertex first');
      const az = parseDirection(fields.bearing, conv);
      if (az == null) return fail('bearing', 'plan.input.bad_bearing', 'Not a bearing');
      const d = gridDistance(fields.distance, ctx, 'distance');
      if (typeof d !== 'number') return d;
      return { ok: true, point: polarPoint(ctx.last, az, d) };
    }
    case 'delta': {
      if (!ctx.last) return fail('first', 'plan.input.needs_start', 'Place the first vertex first');
      const a = signedLength(fields.first, ctx, 'first');
      if (typeof a !== 'number') return a;
      const b = signedLength(fields.second, ctx, 'second');
      if (typeof b !== 'number') return b;
      const [de, dn] = fromDisplayOrder(a, b, conv.axis);
      return { ok: true, point: [ctx.last[0] + de, ctx.last[1] + dn] };
    }
    case 'abs': {
      const a = parseDistance(fields.first, conv);
      if (a == null) return fail('first', 'plan.input.bad_number', 'Not a number');
      const b = parseDistance(fields.second, conv);
      if (b == null) return fail('second', 'plan.input.bad_number', 'Not a number');
      const [e, n] = fromDisplayOrder(a, b, conv.axis);
      const zText = fields.z?.trim();
      if (zText) {
        const z = parseDistance(zText, conv);
        if (z == null) return fail('z', 'plan.input.bad_number', 'Not a number');
        return { ok: true, point: [e, n], z };
      }
      return { ok: true, point: [e, n] };
    }
    case 'polar': {
      const st = ctx.lookup(fields.station.trim());
      if (!st) return fail('station', 'plan.input.unknown_point', 'No point with this id');
      const bs = ctx.lookup(fields.backsight.trim());
      if (!bs) return fail('backsight', 'plan.input.unknown_point', 'No point with this id');
      const angle = parseAngle(fields.angle, conv.angleUnit);
      if (angle == null) return fail('angle', 'plan.input.bad_angle', 'Not an angle');
      const d = gridDistance(fields.distance, ctx, 'distance');
      if (typeof d !== 'number') return d;
      // Angle turned clockwise from the backsight, as read on the instrument.
      const az = normalizeAzimuth(azimuthOf(st, bs) + angle);
      return { ok: true, point: polarPoint(st as GridXY, az, d) };
    }
  }
}
