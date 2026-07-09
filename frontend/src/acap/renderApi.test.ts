import { describe, it, expect } from 'vitest';
import { ApiError } from '@/shared/lib/api';
import { isNotConfiguredError } from './renderApi';

describe('isNotConfiguredError', () => {
  it('is true for the key-gated 400 (GEMINIGEN_API_KEY not set)', () => {
    const err = new ApiError(400, 'Bad Request', {
      detail: { detail: 'Render service not configured', reason: 'GEMINIGEN_API_KEY not set' },
    });
    expect(isNotConfiguredError(err)).toBe(true);
  });

  it('is false for a different 400 body', () => {
    const err = new ApiError(400, 'Bad Request', { detail: 'Some other bad request' });
    expect(isNotConfiguredError(err)).toBe(false);
  });

  it('is false for a 404', () => {
    const err = new ApiError(404, 'Not Found', { detail: 'No layout for this project' });
    expect(isNotConfiguredError(err)).toBe(false);
  });

  it('is false for a non-ApiError', () => {
    expect(isNotConfiguredError(new Error('boom'))).toBe(false);
    expect(isNotConfiguredError(null)).toBe(false);
  });
});
