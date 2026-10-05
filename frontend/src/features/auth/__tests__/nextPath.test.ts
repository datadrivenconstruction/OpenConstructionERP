// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, expect, it } from 'vitest';

import { safeNextPath } from '../nextPath';

describe('safeNextPath', () => {
  it('honours a valid internal path (with or without the leading ?)', () => {
    expect(safeNextPath('?next=/schedule')).toBe('/schedule');
    expect(safeNextPath('next=/schedule')).toBe('/schedule');
    expect(safeNextPath('?next=/bim/federations')).toBe('/bim/federations');
    expect(safeNextPath('?next=/projects/new')).toBe('/projects/new');
  });

  it('decodes a percent-encoded path', () => {
    expect(safeNextPath('?next=%2Fschedule')).toBe('/schedule');
    expect(safeNextPath('?next=%2Fbim%2Ffederations')).toBe('/bim/federations');
  });

  it('ignores unrelated query params around next', () => {
    expect(safeNextPath('?lang=de&next=/takeoff')).toBe('/takeoff');
    expect(safeNextPath('?next=/reports&project=abc')).toBe('/reports');
  });

  it('falls back to / when next is missing', () => {
    expect(safeNextPath('')).toBe('/');
    expect(safeNextPath('?lang=de')).toBe('/');
    expect(safeNextPath('?next=')).toBe('/');
  });

  it('rejects protocol-relative and external targets (open-redirect guard)', () => {
    expect(safeNextPath('?next=//evil.example.com')).toBe('/');
    expect(safeNextPath('?next=https://evil.example.com')).toBe('/');
    expect(safeNextPath('?next=schedule')).toBe('/'); // not absolute-internal
    expect(safeNextPath('?next=../schedule')).toBe('/');
  });

  it('rejects a backslash authority, which passes a naive slash-prefix check', () => {
    // Each of these starts with exactly one forward slash, so a
    // startsWith('/') plus !startsWith('//') pair accepts all of them, and a
    // browser still resolves every one to http://evil.example.com/. Confirmed
    // against a real URL parser before this guard was written.
    expect(safeNextPath('?next=/\\evil.example.com')).toBe('/');
    expect(safeNextPath('?next=/\\\\evil.example.com')).toBe('/');
    expect(safeNextPath('?next=/\\/evil.example.com')).toBe('/');
    // Percent-encoded, since the value arrives through URLSearchParams decoding.
    expect(safeNextPath('?next=%2F%5Cevil.example.com')).toBe('/');
  });

  it('still accepts an internal path that merely contains a backslash later on', () => {
    // The authority position is what matters. A backslash deeper in the path is
    // an ordinary character and must not cost a legitimate deep link.
    expect(safeNextPath('?next=/files/a%5Cb')).toBe('/files/a\\b');
  });

  it('never bounces back into an auth route', () => {
    expect(safeNextPath('?next=/login')).toBe('/');
    expect(safeNextPath('?next=/register')).toBe('/');
    expect(safeNextPath('?next=/forgot-password')).toBe('/');
    expect(safeNextPath('?next=/reset-password/abc123')).toBe('/');
    // The route the reset email links to: its token must never ride a next=.
    expect(safeNextPath('?next=/auth/reset?token=abc123')).toBe('/');
    expect(safeNextPath('?next=/auth/reset')).toBe('/');
    expect(safeNextPath('?next=/onboarding')).toBe('/');
  });

  it('does not confuse a lookalike route with an auth route', () => {
    // "/registered-drawings" starts with "register" but is not "/register"
    expect(safeNextPath('?next=/registered-drawings')).toBe('/registered-drawings');
    expect(safeNextPath('?next=/logins-history')).toBe('/logins-history');
  });
});
