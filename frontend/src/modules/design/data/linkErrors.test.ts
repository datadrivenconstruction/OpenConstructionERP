import { describe, expect, it } from 'vitest';
import { linkFailure, minutesLeft } from './linkErrors';

const http = (status: number) => Object.assign(new Error('x'), { status });

describe('linkFailure', () => {
  it.each([
    [401, 'err_session', false],
    [403, 'err_forbidden', false],
    [404, 'err_not_found', false],
    [426, 'err_version', false],
    [429, 'err_throttled', true],
    [503, 'err_public_url', true],
    [500, 'err_server', true],
    [422, 'err_other', true],
  ])('status %i -> %s, retry %s', (status, key, retry) => {
    expect(linkFailure(http(status))).toEqual({ key: `design.editor.${key}`, retry });
  });
  it('a fetch failure is a network error; anything else is "other"', () => {
    expect(linkFailure(new TypeError('Failed to fetch')).key).toBe('design.editor.err_network');
    expect(linkFailure('boom').key).toBe('design.editor.err_other');
    expect(linkFailure(null).key).toBe('design.editor.err_other');
  });
});

describe('minutesLeft', () => {
  const now = Date.parse('2026-11-15T10:00:00Z');
  it('rounds to whole minutes, never below one', () => {
    expect(minutesLeft('2026-11-15T10:05:00Z', now)).toBe(5);
    expect(minutesLeft('2026-11-15T10:00:10Z', now)).toBe(1);
    expect(minutesLeft('garbage', now)).toBe(1);
  });
});
