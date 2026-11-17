// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { afterEach, describe, expect, it } from 'vitest';
import { usePreferencesStore } from '@/stores/usePreferencesStore';
import { fmtDecimal, fmtRate, fmtStepPercent } from './format';

const initial = usePreferencesStore.getState().numberLocale;

describe('sealed figures follow the reader number locale', () => {
  afterEach(() => usePreferencesStore.setState({ numberLocale: initial }));

  it('writes German separators and keeps the sealed digits', () => {
    usePreferencesStore.setState({ numberLocale: 'de-DE' });
    expect(fmtRate('36.16')).toBe('36,16');
    expect(fmtDecimal('0.45')).toBe('0,45');
    expect(fmtDecimal('0.025')).toBe('0,025');
    expect(fmtDecimal('1250')).toBe('1.250');
    expect(fmtStepPercent('9.5')).toMatch(/^9,5\s%$/);
  });

  it('writes English separators and leaves blanks blank', () => {
    usePreferencesStore.setState({ numberLocale: 'en-US' });
    expect(fmtRate('12033.28')).toBe('12,033.28');
    expect(fmtStepPercent('11')).toBe('11%');
    expect(fmtDecimal(null)).toBe('');
    expect(fmtRate('')).toBe('');
  });
});
