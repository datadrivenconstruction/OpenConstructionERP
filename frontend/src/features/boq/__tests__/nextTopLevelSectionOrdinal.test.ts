// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * A new top-level section must get an ordinal nobody holds. Counting the
 * sections gave ``02`` again after ``01`` of ``01``/``02`` was deleted, and the
 * backend refused it with 409 on every retry.
 */
import { describe, it, expect } from 'vitest';
import { nextTopLevelSectionOrdinal } from '../boqHelpers';

describe('nextTopLevelSectionOrdinal', () => {
  it('starts at 01 on an empty bill', () => {
    expect(nextTopLevelSectionOrdinal([])).toBe('01');
  });

  it('does not reuse 02 after 01 of 01/02 was deleted', () => {
    expect(nextTopLevelSectionOrdinal(['02', '02.10'])).toBe('03');
  });

  it('goes past the highest number when there are gaps', () => {
    expect(nextTopLevelSectionOrdinal(['01', '03', '07', '03.10'])).toBe('08');
  });

  it('ignores empty and non-numeric ordinals but never reuses a taken one', () => {
    expect(nextTopLevelSectionOrdinal(['A', null, undefined, '01'])).toBe('02');
    expect(nextTopLevelSectionOrdinal(['B', '1', '01'])).toBe('02');
  });

  it('keeps counting past 99 without padding loss', () => {
    expect(nextTopLevelSectionOrdinal(['99'])).toBe('100');
  });
});
