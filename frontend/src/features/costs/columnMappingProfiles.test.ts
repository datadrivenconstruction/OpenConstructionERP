// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { beforeEach, describe, expect, it } from 'vitest';
import { headerFingerprint, loadColumnProfile, saveColumnProfile } from './columnMappingProfiles';

const HEADERS = ['Tariffa', 'Descrizione', 'U.M.', 'Prezzo €', 'Note'];

beforeEach(() => localStorage.clear());

describe('remembered column mappings', () => {
  it('brings a mapping back for the same headers, whatever their case, spacing or accents', () => {
    saveColumnProfile(HEADERS, { code: 'Tariffa', description: 'Descrizione', unit: 'U.M.', rate: 'Prezzo €', currency: '' });
    expect(loadColumnProfile(HEADERS)).toEqual({
      code: 'Tariffa',
      description: 'Descrizione',
      unit: 'U.M.',
      rate: 'Prezzo €',
    });
    expect(headerFingerprint(['  TARIFFA ', 'Unità'])).toBe(headerFingerprint(['tariffa', 'unita']));
  });

  it('does not apply to a file with other headers', () => {
    saveColumnProfile(HEADERS, { code: 'Tariffa' });
    expect(loadColumnProfile(['Codice', 'Descrizione'])).toBeNull();
  });

  it('stores nothing when no column is mapped', () => {
    saveColumnProfile(HEADERS, { code: '', rate: '' });
    expect(loadColumnProfile(HEADERS)).toBeNull();
  });

  it('survives a corrupt store', () => {
    localStorage.setItem('oe_cost_import_column_profiles', '{not json');
    expect(loadColumnProfile(HEADERS)).toBeNull();
    saveColumnProfile(HEADERS, { code: 'Tariffa' });
    expect(loadColumnProfile(HEADERS)).toEqual({ code: 'Tariffa' });
  });
});
