// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, expect, it } from 'vitest';
import { pendingStrike } from './StrikeReadyChip';

describe('pendingStrike', () => {
  it('returns only a pending suggestion', () => {
    expect(pendingStrike({ strike_suggestion: { status: 'pending', strength_mpa: 15.4 } })?.strength_mpa).toBe(15.4);
    expect(pendingStrike({ strike_suggestion: { status: 'accepted' } })).toBeNull();
    expect(pendingStrike({ strike_suggestion: 'x' })).toBeNull();
    expect(pendingStrike(null)).toBeNull();
    expect(pendingStrike({})).toBeNull();
  });
});
