// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, expect, it } from 'vitest';
import type { CrsSuggestion, ProjectCrs } from './api';
import {
  changeNeedsTypedConfirm,
  crsChipText,
  crsWarning,
  mergeOptions,
  normaliseQuery,
  preselect,
  typedConfirmMatches,
} from './crsPicker';

const UTM33: CrsSuggestion = {
  epsg: 32633, name: 'WGS 84 / UTM zone 33N', kind: 'projected', unit: 'metre', is_geographic: false,
  reason: 'project_location', confidence: 0.9, pack_country: '',
};
const WGS84: CrsSuggestion = {
  epsg: 4326, name: 'WGS 84', kind: 'geographic', unit: 'degree', is_geographic: true,
  reason: 'geographic', confidence: null, pack_country: '',
};
const CURRENT = {
  project_id: 'p', horizontal_epsg: 32633, horizontal_name: 'WGS 84 / UTM zone 33N', vertical_mode: 'same_as_source',
  vertical_epsg: null, is_local_grid: false, local_origin_e: null, local_origin_n: null, local_rotation_deg: null,
  local_scale_factor: null, source: 'user', detected_confidence: null, confirmed_by: null, confirmed_at: null,
} as ProjectCrs;

describe('CRS picker', () => {
  it('writes the chip the course checks for (lesson 1)', () => {
    expect(crsChipText(CURRENT, 'Local grid')).toBe('EPSG 32633 · WGS 84 / UTM zone 33N');
    expect(crsChipText({ ...CURRENT, is_local_grid: true }, 'Local grid')).toBe('Local grid');
    expect(crsChipText(null, 'Local grid')).toBe('');
  });

  it('warns on lat/lon and on vertical systems, not on UTM', () => {
    expect(crsWarning(WGS84)).toBe('geographic');
    expect(crsWarning({ is_geographic: false, kind: 'vertical' })).toBe('vertical');
    expect(crsWarning(UTM33)).toBeNull();
  });

  it('searches only what was typed', () => {
    expect(normaliseQuery('EPSG:32633')).toBe('32633');
    expect(normaliseQuery(' epsg 25832')).toBe('25832');
    expect(normaliseQuery('3')).toBe('');
  });

  it('keeps suggestions on top and drops duplicates and vertical hits', () => {
    const merged = mergeOptions([UTM33, WGS84], [
      { epsg: 32633, name: 'WGS 84 / UTM zone 33N', kind: 'projected', unit: 'metre', is_geographic: false },
      { epsg: 25833, name: 'ETRS89 / UTM zone 33N', kind: 'projected', unit: 'metre', is_geographic: false },
      { epsg: 5783, name: 'DHHN92 height', kind: 'vertical', unit: 'metre', is_geographic: false },
    ]);
    expect(merged.map((o) => o.epsg)).toEqual([32633, 4326, 25833]);
  });

  it('preselects the location suggestion, never the geographic fallback', () => {
    expect(preselect([UTM33, WGS84], null)).toBe(32633);
    expect(preselect([WGS84], null)).toBeNull();
    expect(preselect([UTM33], 25833)).toBe(25833);
  });

  it('asks for the code typed again only when points would move', () => {
    expect(changeNeedsTypedConfirm(CURRENT, 0, 25833, false)).toBe(false);
    expect(changeNeedsTypedConfirm(CURRENT, 81, 32633, false)).toBe(false);
    expect(changeNeedsTypedConfirm(CURRENT, 81, 25833, false)).toBe(true);
    expect(typedConfirmMatches(' 25833 ', 25833, false)).toBe(true);
    expect(typedConfirmMatches('local', null, true)).toBe(true);
    expect(typedConfirmMatches('32633', 25833, false)).toBe(false);
  });
});
