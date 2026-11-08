// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
// Sensor unit conversion, calibration warnings, strike reason, ranges and sparklines.
import { describe, expect, it } from 'vitest';
import { calibrationWarnings, parseCalibrationRows } from './calibration';
import { hoursRange, sparkPath, strikeNeedsReason } from './sensorData';
import { decimalsFor, displayUnit, toDisplay, unitKeyOf } from './units';

describe('toDisplay', () => {
  it('keeps SI for metric projects', () => {
    expect(toDisplay(20, 'degC', 'metric')).toEqual({ value: 20, unit: 'degC' });
  });
  it('converts for imperial projects and stores nothing', () => {
    expect(toDisplay(20, 'degC', 'imperial')).toEqual({ value: 68, unit: 'degF' });
    expect(toDisplay(1000, 'degC_h', 'imperial').value).toBeCloseTo(1800);
    expect(toDisplay(15, 'mpa', 'imperial').value).toBeCloseTo(2175.6, 1);
    expect(toDisplay(12.7, 'mm_s', 'imperial').value).toBeCloseTo(0.5);
    expect(toDisplay(70, 'dba', 'imperial')).toEqual({ value: 70, unit: 'dba' });
    expect(displayUnit('mpa', 'imperial')).toBe('psi');
    expect(decimalsFor('in_s')).toBe(3);
  });
  it('maps stored unit strings, old and new spellings', () => {
    expect(unitKeyOf('degC')).toBe('degC');
    expect(unitKeyOf('°C')).toBe('degC');
    expect(unitKeyOf('ug/m3')).toBe('ugm3');
    expect(unitKeyOf('µg/m³')).toBe('ugm3');
    expect(unitKeyOf('furlong')).toBeNull();
  });
});

describe('calibration', () => {
  it('drops blank and invalid rows', () => {
    expect(
      parseCalibrationRows([
        { index: '500', mpa: '8.2' },
        { index: '', mpa: '9' },
        { index: '-1', mpa: '3' },
      ]),
    ).toEqual([{ maturity_index: 500, strength_mpa: '8.2' }]);
  });
  it('warns under 4 cubes or R² 0.9', () => {
    expect(calibrationWarnings(0, null)).toEqual([]);
    expect(calibrationWarnings(3, 0.98)).toEqual(['few_points']);
    expect(calibrationWarnings(5, 0.8)).toEqual(['low_r2']);
    expect(calibrationWarnings(5, 0.95)).toEqual([]);
  });
});

describe('strike and projection helpers', () => {
  it('asks for a reason below target or without an estimate', () => {
    expect(strikeNeedsReason(12.4, '15')).toBe(true);
    expect(strikeNeedsReason(null, '15')).toBe(true);
    expect(strikeNeedsReason(15.2, '15')).toBe(false);
  });
  it('rounds the hours range outward', () => {
    expect(hoursRange([10.2, 13.7])).toEqual([10, 14]);
    expect(hoursRange(null)).toBeNull();
  });
  it('draws a sparkline with gaps and a limit line', () => {
    const { path, limitY } = sparkPath([50, null, 60, 70], 55, 30, 20);
    expect(path).toBe('M0,20 M20,10 L30,0');
    expect(limitY).toBe(15);
    expect(sparkPath([null, null], 5).path).toBe('');
  });
});
