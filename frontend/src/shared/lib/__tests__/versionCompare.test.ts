// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Release numbers are compared as numbers. The dismiss keys for the update
// card and the What's new card hold text that a person or a script wrote,
// and the card itself prints "v18.0.0", so the reader has to accept the
// shapes that text actually arrives in.
//
// Run:  npx vitest run src/shared/lib/__tests__/versionCompare.test.ts
import { describe, expect, it } from 'vitest';

import { compareVersions, isNewerFeatureRelease, parseVersion } from '../version';

describe('parseVersion', () => {
  it.each([
    ['18.0.0', [18, 0, 0]],
    ['v18.0.0', [18, 0, 0]],
    ['V18.0.0', [18, 0, 0]],
    ['  18.0.0 ', [18, 0, 0]],
    ['"18.0.0"', [18, 0, 0]],
    ['18.0', [18, 0]],
    ['5.3.0rc1', [5, 3, 0]],
  ])('reads %j', (text, parts) => {
    expect(parseVersion(text)).toEqual(parts);
  });

  it.each([null, undefined, '', 'yes', 'true', 'vv'])('reads %j as no version', (text) => {
    expect(parseVersion(text)).toBeNull();
  });
});

describe('compareVersions', () => {
  it('orders 5.2.10 above 5.2.9, which a string compare gets backwards', () => {
    expect(compareVersions([5, 2, 10], [5, 2, 9])).toBeGreaterThan(0);
  });

  it('treats 18.0 and 18.0.0 as the same release', () => {
    expect(compareVersions([18, 0], [18, 0, 0])).toBe(0);
  });

  it('orders a newer major above an older one', () => {
    expect(compareVersions([17, 8, 3], [18, 0, 0])).toBeLessThan(0);
  });
});

describe('isNewerFeatureRelease', () => {
  it('counts a first visit as new', () => {
    expect(isNewerFeatureRelease('18.0.0', null)).toBe(true);
  });

  it('counts a newer minor as new', () => {
    expect(isNewerFeatureRelease('18.1.0', '18.0.0')).toBe(true);
  });

  it('does not count a patch release as new', () => {
    expect(isNewerFeatureRelease('18.0.2', '18.0.0')).toBe(false);
  });

  it('does not count the acknowledged release, whatever its spelling', () => {
    expect(isNewerFeatureRelease('18.0.0', 'v18.0.0')).toBe(false);
    expect(isNewerFeatureRelease('18.0.0', '18.0')).toBe(false);
  });

  it('does not count an older release than the acknowledged one', () => {
    expect(isNewerFeatureRelease('17.9.0', '18.0.0')).toBe(false);
  });

  it('never counts an unreadable current version', () => {
    expect(isNewerFeatureRelease('', null)).toBe(false);
  });
});
