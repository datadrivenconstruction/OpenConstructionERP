// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
// Pure helpers behind the Project Catalogue page, on the worked example: a
// 185.00 wall rate priced at 172.50 locally, then the database moves to 190.00.
import { describe, it, expect } from 'vitest';

import { formatDeviation, needsDecision, statusVariant } from './api';

describe('statusVariant', () => {
  it('colours every status the API can return', () => {
    expect(statusVariant('in_sync')).toBe('success');
    expect(statusVariant('overridden')).toBe('blue');
    expect(statusVariant('source_changed')).toBe('warning');
    expect(statusVariant('source_missing')).toBe('error');
    expect(statusVariant('manual')).toBe('neutral');
  });
});

describe('needsDecision', () => {
  it('asks for a decision only when the source moved', () => {
    expect(needsDecision({ status: 'source_changed' })).toBe(true);
    expect(needsDecision({ status: 'overridden' })).toBe(false);
    expect(needsDecision({ status: 'source_missing' })).toBe(false);
  });
});

describe('formatDeviation', () => {
  it('signs the distance from the source rate', () => {
    expect(formatDeviation('-6.8')).toBe('-6.8 %');
    expect(formatDeviation('832.4')).toBe('+832.4 %');
  });

  it('shows nothing without a source or without a difference', () => {
    expect(formatDeviation(null)).toBe('');
    expect(formatDeviation('0.0')).toBe('');
    expect(formatDeviation('')).toBe('');
  });
});
