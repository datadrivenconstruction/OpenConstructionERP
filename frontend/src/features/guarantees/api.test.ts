// DDC-CWICR-OE: DataDrivenConstruction​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The lifecycle rules the guarantees UI mirrors client-side. The transition
 * table and the delete rule are enforced by the backend as well; if the two
 * drift, a button appears that the server then refuses.
 */

import { describe, it, expect } from 'vitest';
import {
  ALLOWED_TRANSITIONS,
  GUARANTEE_STATUSES,
  alertBandClass,
  barWidth,
  compactBody,
  isDeletable,
  transitionNeeds,
  utilisationPercent,
} from './api';

describe('ALLOWED_TRANSITIONS', () => {
  it('covers every status and leaves released and called final', () => {
    expect(Object.keys(ALLOWED_TRANSITIONS).sort()).toEqual([...GUARANTEE_STATUSES].sort());
    expect(ALLOWED_TRANSITIONS.released).toEqual([]);
    expect(ALLOWED_TRANSITIONS.called).toEqual([]);
  });

  it('lets an expired guarantee only be extended', () => {
    expect(ALLOWED_TRANSITIONS.expired).toEqual(['extended']);
  });

  it('moves draft and requested forward to issued', () => {
    expect(ALLOWED_TRANSITIONS.draft).toEqual(['requested', 'issued']);
    expect(ALLOWED_TRANSITIONS.requested).toEqual(['draft', 'issued']);
  });
});

describe('transitionNeeds', () => {
  it('asks for an expiry on extend and an amount on reduce', () => {
    expect(transitionNeeds('extended')).toBe('expiry');
    expect(transitionNeeds('reduced')).toBe('amount');
    expect(transitionNeeds('released')).toBeNull();
  });
});

describe('isDeletable', () => {
  it('allows only draft and requested', () => {
    expect(GUARANTEE_STATUSES.filter(isDeletable)).toEqual(['draft', 'requested']);
  });
});

describe('utilisationPercent', () => {
  it('returns null for a line without a limit', () => {
    expect(utilisationPercent({ utilisation_pct: null })).toBeNull();
  });
  it('parses strings and numbers', () => {
    expect(utilisationPercent({ utilisation_pct: '42.5' })).toBe(42.5);
    expect(utilisationPercent({ utilisation_pct: 120 })).toBe(120);
  });
});

describe('barWidth', () => {
  it('scales against the largest amount and clamps', () => {
    expect(barWidth('50', 200)).toBe(25);
    expect(barWidth('500', 200)).toBe(100);
    expect(barWidth('abc', 200)).toBe(0);
    expect(barWidth('10', 0)).toBe(0);
  });
});

describe('alertBandClass', () => {
  it('uses three distinct colours for the three bands', () => {
    const set = new Set([alertBandClass(14), alertBandClass(30), alertBandClass(60), alertBandClass(null)]);
    expect(set.size).toBe(4);
  });
});

describe('compactBody', () => {
  it('drops empty strings and undefined but keeps false and zero', () => {
    expect(compactBody({ a: '', b: undefined, c: false, d: 0, e: 'x' })).toEqual({ c: false, d: 0, e: 'x' });
  });
});
