// @vitest-environment node
import { describe, expect, it } from 'vitest';
import { isNationalProfile, visibleExportProfiles } from '../api';

const data = { profiles: ['csv', 'ejar', 'json'], countries: { ejar: 'SA' } };

describe('visibleExportProfiles', () => {
  it('shows the national profile when its market is in scope', () => {
    expect(visibleExportProfiles(data, ['SA'])).toEqual(['csv', 'ejar', 'json']);
  });

  it('hides it for other markets and for an unscoped workspace', () => {
    expect(visibleExportProfiles(data, ['DE'])).toEqual(['csv', 'json']);
    expect(visibleExportProfiles(data, undefined)).toEqual(['csv', 'json']);
  });

  it('is empty until the profiles load', () => {
    expect(visibleExportProfiles(undefined, ['SA'])).toEqual([]);
  });

  it('tells a national profile from a generic one', () => {
    expect(isNationalProfile(data, 'ejar')).toBe(true);
    expect(isNationalProfile(data, 'csv')).toBe(false);
  });
});
