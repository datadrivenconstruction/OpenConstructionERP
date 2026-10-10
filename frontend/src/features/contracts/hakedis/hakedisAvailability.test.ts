// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// When the certificate is asked for at all.
//
// The server answers 404 for a contract without a certificate layout. The two
// screens that show a certificate used to find that out by asking, on every
// progress claim and every subcontract agreement of every country. They now
// skip the question where the answer is already on the page, and these tests
// pin the two things that matter about that: a Turkish project, and a contract
// that brings its own layout anywhere, are asked about exactly as before, and
// nothing unknown is ever read as "no".

import { describe, expect, it } from 'vitest';

import { agreementMayHaveHakedis, claimMayHaveHakedis } from './hakedisQueries';

const TURKISH = { is_hakedis_eligible: true };
const ELSEWHERE = { is_hakedis_eligible: false };
const PLAIN = { terms: {} };

describe('claimMayHaveHakedis', () => {
  it('asks for a project in a country that has a layout, whatever the contract says', () => {
    expect(claimMayHaveHakedis(TURKISH, PLAIN, false)).toBe(true);
    expect(claimMayHaveHakedis(TURKISH, { terms: { hakedis: { enabled: false } } }, false)).toBe(true);
  });

  it('does not ask where neither the country nor the contract gives a layout', () => {
    expect(claimMayHaveHakedis(ELSEWHERE, PLAIN, false)).toBe(false);
    expect(claimMayHaveHakedis(ELSEWHERE, { terms: { payment_terms: 'net 30' } }, false)).toBe(false);
    // A certificate block that names neither a preset nor lines configures nothing.
    expect(claimMayHaveHakedis(ELSEWHERE, { terms: { hakedis: { signatures: [] } } }, false)).toBe(false);
    expect(claimMayHaveHakedis(ELSEWHERE, { terms: { hakedis: 'TR' } }, false)).toBe(false);
  });

  it('asks where the contract brings its own layout in any country', () => {
    expect(claimMayHaveHakedis(ELSEWHERE, { terms: { hakedis: { preset: 'TR_PRIVATE' } } }, false)).toBe(true);
    expect(claimMayHaveHakedis(ELSEWHERE, { terms: { hakedis: { lines: [{ key: 'works' }] } } }, false)).toBe(true);
  });

  it('waits while the project or the contract is still loading', () => {
    expect(claimMayHaveHakedis(undefined, PLAIN, false)).toBe(false);
    expect(claimMayHaveHakedis(TURKISH, undefined, false)).toBe(false);
    expect(claimMayHaveHakedis(undefined, undefined, false)).toBe(false);
  });

  it('asks as before when a lookup failed or the server sends no flag', () => {
    expect(claimMayHaveHakedis(undefined, undefined, true)).toBe(true);
    expect(claimMayHaveHakedis(ELSEWHERE, undefined, true)).toBe(true);
    expect(claimMayHaveHakedis({}, PLAIN, false)).toBe(true);
  });
});

describe('agreementMayHaveHakedis', () => {
  it('takes the answer the agreement carries', () => {
    expect(agreementMayHaveHakedis({ hakedis_available: true })).toBe(true);
    expect(agreementMayHaveHakedis({ hakedis_available: false })).toBe(false);
  });

  it('asks when there is no answer to take', () => {
    expect(agreementMayHaveHakedis(undefined)).toBe(true);
    expect(agreementMayHaveHakedis({})).toBe(true);
    expect(agreementMayHaveHakedis({ hakedis_available: null })).toBe(true);
  });
});
