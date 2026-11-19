// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, expect, it } from 'vitest';
import { parseBook, parseStations } from './CalcPage';

describe('parseStations', () => {
  it('reads DMS as one token or three, with the leg distance last', () => {
    expect(parseStations('A 108-12-30 120.50\nB 108 12 30 98.2', 'dms')).toEqual([
      { station_id: 'A', angle: '108-12-30', distance_m: 120.5 },
      { station_id: 'B', angle: '108 12 30', distance_m: 98.2 },
    ]);
  });

  it('reads gon with an optional distance and refuses a bad distance', () => {
    expect(parseStations('A 120.1234 50\nB 80.5', 'gon')).toEqual([
      { station_id: 'A', angle: '120.1234', distance_m: 50 },
      { station_id: 'B', angle: '80.5', distance_m: null },
    ]);
    expect(parseStations('A 120 x\nB 80', 'gon')).toBeNull();
  });
});

describe('parseBook', () => {
  it('reads the level book rows with dashes for readings not taken', () => {
    expect(parseBook('BM1 1.234 - - 0\nTP1 2.100 - 0.987 60')).toEqual([
      { station: 'BM1', bs: 1.234, is: null, fs: null, distance_m: 0 },
      { station: 'TP1', bs: 2.1, is: null, fs: 0.987, distance_m: 60 },
    ]);
    expect(parseBook('BM1 abc')).toBeNull();
  });
});
