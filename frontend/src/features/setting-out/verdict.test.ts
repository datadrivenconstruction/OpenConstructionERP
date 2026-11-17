// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, expect, it } from 'vitest';
import { fmtMm, instantDelta, parseDecimal } from './verdict';

const C03 = { e: 389060, n: 5819030, z: 34.3 };

describe('instantDelta', () => {
  it('matches the DOMAIN worked example: 15 mm against 10 mm fails', () => {
    const r = instantDelta(C03, { e: 389060.012, n: 5819029.991, z: 34.302 }, 10, 10);
    expect(r).toEqual({ d_mm: 15, dz_mm: 2, verdict: 'fail' });
  });

  it('passes C-04 at 5 mm with dZ -2', () => {
    const r = instantDelta({ e: 389080, n: 5819030, z: 34.3 }, { e: 389080.004, n: 5819029.997, z: 34.298 }, 10, 10);
    expect(r).toEqual({ d_mm: 5, dz_mm: -2, verdict: 'pass' });
  });

  it('passes exactly at the tolerance and fails on height alone', () => {
    expect(instantDelta(C03, { e: 389060.006, n: 5819030.008, z: null }, 10, 10).verdict).toBe('pass');
    expect(instantDelta(C03, { e: 389060, n: 5819030, z: 34.315 }, 10, 10).verdict).toBe('fail');
  });

  it('gives no verdict without a tolerance profile', () => {
    expect(instantDelta(C03, { e: 389060.1, n: 5819030, z: null }, null, null).verdict).toBe('no_tolerance');
  });
});

describe('parseDecimal and fmtMm', () => {
  it('reads a decimal comma and refuses junk', () => {
    expect(parseDecimal(' 5819029,997 ')).toBe(5819029.997);
    expect(parseDecimal('')).toBeNull();
    expect(parseDecimal('12a')).toBeNull();
  });

  it('prints whole millimetres without a decimal', () => {
    expect(fmtMm(5)).toBe('5');
    expect(fmtMm(4.56)).toBe('4.6');
    expect(fmtMm(null)).toBe('');
  });
});
