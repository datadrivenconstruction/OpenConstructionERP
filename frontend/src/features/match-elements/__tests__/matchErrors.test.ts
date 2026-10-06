// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// A failed run shows one readable, translated sentence instead of the
// transport text ("500 Internal server error").

import { describe, it, expect, vi } from 'vitest';
import type { TFunction } from 'i18next';

import { fetchMatchReadiness, MatchApiError } from '../api';
import { describeMatchError } from '../matchErrors';

// Echo the key (and the field list, when one is passed) so each branch is
// asserted by the key it chose; the sentences themselves live in en.ts.
const t = ((key: string, opts?: { fields?: string }) =>
  opts?.fields ? `${key}|${opts.fields}` : key) as unknown as TFunction;

describe('describeMatchError', () => {
  it.each([
    [new MatchApiError('timeout', 'x'), 'match_elements.error.timeout'],
    [new MatchApiError('network', 'Failed to fetch'), 'match_elements.error.network'],
    [new MatchApiError('http', '500 Internal server error', 500, 'Internal server error'), 'match_elements.error.server'],
    [new MatchApiError('http', '502 Bad Gateway', 502, 'Bad Gateway'), 'match_elements.error.server'],
    [new MatchApiError('http', '403 Forbidden', 403, 'Forbidden'), 'match_elements.error.forbidden'],
    [new MatchApiError('http', '401 Not authenticated', 401, 'Not authenticated'), 'match_elements.error.sign_in'],
    [new MatchApiError('http', '404 Not found', 404, 'Not found'), 'match_elements.error.not_found'],
    [new Error('boom'), 'match_elements.error.unknown'],
    ['boom', 'match_elements.error.unknown'],
  ])('maps %s', (err, key) => {
    expect(describeMatchError(err, t)).toBe(key);
  });

  it('reads a 404 while starting a session as a missing project', () => {
    const err = new MatchApiError('http', '404 Project not found', 404, 'Project not found');
    expect(describeMatchError(err, t, 'session')).toBe('match_elements.error.project_not_found');
  });

  it('asks to sign in again on 401 whatever the step', () => {
    const err = new MatchApiError('http', '401 Not authenticated', 401, 'Not authenticated');
    expect(describeMatchError(err, t, 'session')).toBe('match_elements.error.sign_in');
  });

  it('names the fields a 422 rejected instead of the raw validation text', () => {
    const err = new MatchApiError(
      'http',
      '422 body.auto_confirm_threshold: Input should be less than or equal to 1',
      422,
      'body.auto_confirm_threshold: Input should be less than or equal to 1',
      ['auto_confirm_threshold', 'construction_stage'],
    );
    expect(describeMatchError(err, t)).toBe(
      'match_elements.error.invalid_input|auto_confirm_threshold, construction_stage',
    );
  });

  it('has a sentence for a 422 without field names', () => {
    const err = new MatchApiError('http', '422 Unprocessable', 422, 'Unprocessable');
    expect(describeMatchError(err, t)).toBe('match_elements.error.invalid_input_any');
  });

  it('keeps the reason the server gave for another 4xx', () => {
    const err = new MatchApiError('http', '409 Catalogue not published yet', 409, 'Catalogue not published yet');
    expect(describeMatchError(err, t)).toBe('Catalogue not published yet');
  });

  it('keeps the historical message text for callers that show it raw', () => {
    const err = new MatchApiError('http', '500 Internal server error', 500, 'Internal server error');
    expect(err).toBeInstanceOf(Error);
    expect(err.message).toBe('500 Internal server error');
  });
});

describe('MatchApiError from a 422 body', () => {
  it('collects the rejected field names', async () => {
    const body = {
      detail: [
        { loc: ['body', 'auto_confirm_threshold'], msg: 'Input should be less than or equal to 1', type: 'x' },
        { loc: ['query', 'project_id'], msg: 'Field required', type: 'missing' },
      ],
    };
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify(body), { status: 422, headers: { 'Content-Type': 'application/json' } }),
      ),
    );
    try {
      await expect(fetchMatchReadiness('p-1')).rejects.toMatchObject({
        status: 422,
        fields: ['auto_confirm_threshold', 'project_id'],
      });
    } finally {
      vi.unstubAllGlobals();
    }
  });
});
