// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, expect, it } from 'vitest';
import { buildLinework, lineworkProblems, parseCode, type CodeEntry, type CodedPoint } from './linework';
import { runLiveChecks } from './liveChecks';
import { arcThrough, offsetPath, ringArea, angleAt, ringSelfIntersections } from './geometry';

const lib: CodeEntry[] = [
  { code: 'EP', label: 'Edge of pavement', symbol: 'kerb', line: 'open', smooth: false, layer: 'linework', colour: 'kerb' },
  { code: 'FN', label: 'Fence', symbol: 'post', line: 'open', smooth: false, layer: 'linework', colour: 'fence' },
  { code: 'BLD', label: 'Building', symbol: 'spot', line: 'closed', smooth: false, layer: 'linework', colour: 'building' },
  { code: 'TR', label: 'Tree', symbol: 'tree', line: 'none', smooth: false, layer: 'points', colour: 'tree' },
];
const p = (id: string, e: number, n: number, code: string, line: number): CodedPoint => ({ id, e, n, code, sourceLine: line });

describe('parseCode', () => {
  it.each([
    ['EP1', 'EP', '1', null],
    ['EP2 ST', 'EP', '2', 'ST'],
    ['EP2ST', 'EP', '2', 'ST'],
    ['BLD1 CL', 'BLD', '1', 'CL'],
    ['FN END', 'FN', '1', 'END'],
    ['TR', 'TR', '1', null],
  ])('%s', (raw, base, string, control) => {
    const r = parseCode(raw, lib);
    expect([r.entry?.code, r.string, r.control]).toEqual([base, string, control]);
  });

  it('an unknown code has no entry', () => {
    expect(parseCode('XYZ3', lib).entry).toBeNull();
  });
});

describe('buildLinework', () => {
  it('joins strings in field order and closes closed codes', () => {
    const pts = [
      p('1', 0, 0, 'EP1', 1),
      p('2', 0, 10, 'EP2', 2),
      p('3', 10, 0, 'EP1', 3),
      p('4', 10, 10, 'EP2', 4),
      p('5', 20, 0, 'EP1', 5),
      p('6', 50, 50, 'TR', 6),
      p('7', 0, 20, 'BLD1', 7),
      p('8', 5, 20, 'BLD1', 8),
      p('9', 5, 25, 'BLD1', 9),
    ];
    const lines = buildLinework(pts, lib);
    const ep1 = lines.find((l) => l.properties.string === 'EP1')!;
    expect(ep1.geometry).toEqual({ type: 'LineString', coordinates: [[0, 0], [10, 0], [20, 0]] });
    expect(lines.find((l) => l.properties.string === 'EP2')!.properties.points).toEqual(['2', '4']);
    expect(lines.find((l) => l.properties.string === 'BLD1')!.geometry.type).toBe('Polygon');
    expect(lines).toHaveLength(3);
  });

  it('ST starts a new part, CL closes and END ends', () => {
    const pts = [p('1', 0, 0, 'FN1', 1), p('2', 1, 0, 'FN1', 2), p('3', 5, 5, 'FN1 ST', 3), p('4', 6, 5, 'FN1', 4), p('5', 6, 6, 'FN1 CL', 5)];
    const lines = buildLinework(pts, lib);
    expect(lines).toHaveLength(2);
    expect(lines[0]!.geometry.type).toBe('LineString');
    expect(lines[1]!.geometry.type).toBe('Polygon');
  });

  it('reports strings that cannot draw and unknown codes', () => {
    const pts = [p('1', 0, 0, 'EP7', 1), p('2', 0, 0, 'BLD2', 2), p('3', 1, 0, 'BLD2', 3), p('4', 3, 3, 'ZZ', 4)];
    expect(lineworkProblems(pts, lib).map((x) => x.key).sort()).toEqual(['BLD2', 'EP7']);
    const findings = runLiveChecks({ features: [], codes: lib, points: pts });
    expect(findings.map((f) => f.ruleId).sort()).toEqual(['SRV-140', 'SRV-141', 'SRV-141']);
  });
});

describe('geometry used by the tools', () => {
  it('arc through three points stays on the circle', () => {
    const arc = arcThrough([10, 0], [0, 10], [-10, 0]);
    for (const q of arc) expect(Math.hypot(q[0], q[1])).toBeCloseTo(10, 9);
    expect(arc[0]).toEqual([10, 0]);
    expect(arc[arc.length - 1]).toEqual([-10, 0]);
    // It goes over the top (through N = 10), not under.
    expect(Math.max(...arc.map((q) => q[1]))).toBeCloseTo(10, 2);
  });

  it('offset to the right of travel', () => {
    expect(offsetPath([[0, 0], [10, 0]], 2)).toEqual([[0, -2], [10, -2]]);
  });

  it('area, angle and self-intersection', () => {
    expect(ringArea([[0, 0], [10, 0], [10, 10], [0, 10]])).toBe(100);
    expect(angleAt([0, 10], [0, 0], [10, 0])).toBeCloseTo(90, 9);
    expect(ringSelfIntersections([[0, 0], [10, 10], [10, 0], [0, 10]])).toHaveLength(1);
  });
});
