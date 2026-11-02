// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, expect, it } from 'vitest';
import type { DetectCandidate, DiffChange, Issue } from './api';
import { bestCandidate, countByKind, hasBlockingIssue, pricedPercent } from './logic';

const cand = (key: string, confidence: number, item_count: number): DetectCandidate => ({
  profile_key: key, name: key, source: 'platform', confidence, reasons: [], item_count,
});

describe('owner schedule logic', () => {
  it('picks the most confident profile that reads items', () => {
    expect(bestCandidate([cand('a', 0.4, 10), cand('b', 0.9, 0), cand('c', 0.7, 5)])?.profile_key).toBe('c');
    expect(bestCandidate([cand('b', 0.9, 0)])).toBeNull();
  });
  it('flags only errors as blocking', () => {
    const issue = (severity: string): Issue => ({ severity, code: 'x', row: null, item_no: null, role: null });
    expect(hasBlockingIssue([issue('warning')])).toBe(false);
    expect(hasBlockingIssue([issue('warning'), issue('error')])).toBe(true);
  });
  it('counts addendum changes by kind', () => {
    const ch = (kind: DiffChange['kind']): DiffChange => ({ kind, item_no: '1', fields: [] });
    expect(countByKind([ch('added'), ch('added'), ch('removed')])).toEqual({
      added: 2, removed: 1, changed: 0, quantity_changed: 0,
    });
  });
  it('handles an empty schedule when computing progress', () => {
    expect(pricedPercent(0, 0)).toBe(0);
    expect(pricedPercent(1, 3)).toBe(33);
  });
});
