// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * One computation for every DWG takeoff number.
 *
 * Regressions covered:
 *  - a millimetre drawing showed `0.05 m` on the canvas and `54.85 m` in the
 *    annotation list for the same distance (the list ignored the units);
 *  - the Summary CSV said 3.210 m, the XLSX 3.36 m and the UI both, because
 *    the totals and the per-layer rows measured different entity sets (ARC
 *    length was only in one of them);
 *  - manual Distance/Area annotations were missing from the totals.
 */

import { describe, it, expect } from 'vitest';
import type { DwgAnnotation, DxfEntity } from '../../api';
import { quantifyByLayer } from '../auto-quantify';
import { aggregateEntities } from '../group-aggregation';
import { unitFactorToMetres } from '../measurement';
import {
  annotationRealValue,
  annotationTotals,
  quantifyTotals,
  scaleRawMeasurement,
} from '../takeoff-totals';

type Ann = Pick<DwgAnnotation, 'type' | 'measurement_value' | 'measurement_unit'>;

const MM = unitFactorToMetres('mm');

describe('annotationRealValue', () => {
  it('reads a raw millimetre distance as the canvas label does', () => {
    const ann: Ann = { type: 'distance', measurement_value: 54.85, measurement_unit: 'm' };
    const real = annotationRealValue(ann, MM);
    expect(real).toBeCloseTo(0.05485, 6);
    expect(real).toBe(scaleRawMeasurement(54.85, 'm', MM));
  });

  it('squares the scale for areas', () => {
    const ann: Ann = { type: 'area', measurement_value: 846_290, measurement_unit: 'm²' };
    expect(annotationRealValue(ann, MM)).toBeCloseTo(0.84629, 6);
    expect(annotationRealValue(ann, 50 * MM)).toBeCloseTo(0.84629 * 2500, 3);
  });

  it('leaves entity-derived and count values alone (already real)', () => {
    expect(annotationRealValue({ type: 'text_pin', measurement_value: 32.5, measurement_unit: 'm' }, MM)).toBe(32.5);
    expect(annotationRealValue({ type: 'count', measurement_value: 1, measurement_unit: 'nr' }, MM)).toBe(1);
  });

  it('uses a two-point calibration instead of the preset scale', () => {
    const ann: Ann = { type: 'distance', measurement_value: 200, measurement_unit: 'm' };
    expect(annotationRealValue(ann, MM, { unitsPerPixel: 5, unit: 'mm' })).toBeCloseTo(1, 9);
  });

  it('returns null for an annotation without a number', () => {
    expect(annotationRealValue({ type: 'distance', measurement_value: null, measurement_unit: 'm' } as Ann, 1)).toBeNull();
  });
});

describe('annotationTotals', () => {
  it('sums manual lengths and areas in real units and counts markers', () => {
    const anns: Ann[] = [
      { type: 'distance', measurement_value: 1000, measurement_unit: 'm' },
      { type: 'polyline', measurement_value: 500, measurement_unit: 'm' },
      { type: 'area', measurement_value: 2_000_000, measurement_unit: 'm²' },
      { type: 'count', measurement_value: 1, measurement_unit: 'nr' },
      { type: 'count', measurement_value: 1, measurement_unit: 'nr' },
      { type: 'text_pin', measurement_value: 99, measurement_unit: 'm' },
    ];
    const totals = annotationTotals(anns, MM);
    expect(totals.length).toBeCloseTo(1.5, 9);
    expect(totals.area).toBeCloseTo(2, 9);
    expect(totals.count).toBe(2);
  });
});

describe('drawing totals are one computation', () => {
  const entities: DxfEntity[] = [
    { id: 'l', type: 'LINE', layer: '0', color: '#fff', start: { x: 0, y: 0 }, end: { x: 2850, y: 0 } },
    // A quarter arc of radius 100 mm: the length the totals used to drop.
    { id: 'a', type: 'ARC', layer: '0', color: '#fff', start: { x: 0, y: 0 }, radius: 100, start_angle: 0, end_angle: Math.PI / 2 },
    {
      id: 'h',
      type: 'HATCH',
      layer: 'FILL',
      color: '#fff',
      vertices: [
        { x: 0, y: 0 },
        { x: 1000, y: 0 },
        { x: 1000, y: 1000 },
      ],
    },
    {
      id: 'r',
      type: 'LWPOLYLINE',
      layer: 'WALLS',
      color: '#fff',
      closed: true,
      vertices: [
        { x: 0, y: 0 },
        { x: 1000, y: 0 },
        { x: 1000, y: 1000 },
        { x: 0, y: 1000 },
      ],
    },
  ];

  it('the selection aggregate and the per-layer totals agree', () => {
    const rows = quantifyByLayer(entities, MM);
    const totals = quantifyTotals(rows);
    const agg = aggregateEntities(entities, MM);
    expect(totals.length).toBeCloseTo(2.85 + (Math.PI / 2) * 0.1, 3);
    expect(agg.length).toBeCloseTo(totals.length, 3);
    expect(agg.area).toBeCloseTo(totals.area, 3);
    expect(agg.perimeter).toBeCloseTo(totals.perimeter, 3);
    expect(totals.area).toBeCloseTo(1.5, 3);
    expect(totals.perimeter).toBeCloseTo(4, 3);
    expect(totals.count).toBe(4);
  });
});
