// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, it, expect } from 'vitest';
import { unitGlyph, localizedUnitCode } from './unitLabels';

describe('unitGlyph', () => {
  it('maps canonical area/volume tokens to superscript glyphs', () => {
    expect(unitGlyph('m2')).toBe('m²');
    expect(unitGlyph('m3')).toBe('m³');
  });

  it('passes unknown tokens through unchanged', () => {
    expect(unitGlyph('psch')).toBe('psch');
    expect(unitGlyph('')).toBe('');
  });
});

describe('localizedUnitCode', () => {
  it('renders superscript glyphs regardless of locale', () => {
    expect(localizedUnitCode('m2', 'en')).toBe('m²');
    expect(localizedUnitCode('m3', 'de')).toBe('m³');
  });

  it('shows the German trade code psch for lump-sum tokens under de', () => {
    expect(localizedUnitCode('lsum', 'de')).toBe('psch');
    expect(localizedUnitCode('ls', 'de')).toBe('psch');
    expect(localizedUnitCode('lump_sum', 'de')).toBe('psch');
    expect(localizedUnitCode('LSUM', 'de-AT')).toBe('psch');
  });

  it('keeps the canonical token outside German', () => {
    expect(localizedUnitCode('lsum', 'en')).toBe('lsum');
    expect(localizedUnitCode('lsum', 'fr')).toBe('lsum');
  });

  // Audit case-2 K-14: a raw "pcs" next to German labels reads as
  // untranslated UI; the app's own German strings promise "Stk".
  it('shows the German trade code Stk for piece tokens under de', () => {
    expect(localizedUnitCode('pcs', 'de')).toBe('Stk');
    expect(localizedUnitCode('ea', 'de')).toBe('Stk');
    expect(localizedUnitCode('pcs', 'en')).toBe('pcs');
  });

  // P-56: Croatian trade spellings. The server stores the running metre m'
  // as the canonical "lm"; it has to read back as m', not "l.m".
  it('shows the Croatian trade codes under hr', () => {
    expect(localizedUnitCode('lm', 'hr')).toBe("m'");
    expect(localizedUnitCode('lsum', 'hr')).toBe('pauš.');
    expect(localizedUnitCode('pcs', 'hr')).toBe('kom');
    expect(localizedUnitCode('m2', 'hr')).toBe('m²');
    expect(localizedUnitCode('lm', 'en')).toBe('l.m');
  });

  it('localizes the unit part of compound trade units (DACH cost bases)', () => {
    expect(localizedUnitCode('100 m2', 'de')).toBe('100 m²');
    expect(localizedUnitCode('100 m3', 'de')).toBe('100 m³');
    expect(localizedUnitCode('10 lsum', 'de')).toBe('10 psch');
  });

  it('never modifies unknown tokens', () => {
    expect(localizedUnitCode('Stk', 'de')).toBe('Stk');
    expect(localizedUnitCode('', 'de')).toBe('');
  });
});
