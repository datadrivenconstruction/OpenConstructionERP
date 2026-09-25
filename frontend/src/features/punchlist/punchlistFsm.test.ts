// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, expect, it } from 'vitest';

import { punchNextMoves } from './punchlistFsm';

describe('punch lifecycle offered in the UI', () => {
  it('does not offer verification straight from In Progress', () => {
    // Four-eyes verification needs a recorded resolver, so an item in
    // progress has to be marked resolved before anybody can verify it.
    expect(punchNextMoves('in_progress').forward).toEqual(['resolved']);
  });

  it('offers verification only once the item is resolved', () => {
    expect(punchNextMoves('resolved').forward).toEqual(['verified']);
    expect(punchNextMoves('verified').forward).toEqual(['closed']);
  });
});
