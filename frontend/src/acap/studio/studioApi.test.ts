import { describe, it, expect } from 'vitest';
import { ApiError } from '@/shared/lib/api';
import { isVisionNotConfiguredError } from './studioApi';

describe('isVisionNotConfiguredError', () => {
  it('true for key-gated 400 (GOOGLE_API_KEY not set)', () => {
    const err = new ApiError(400, 'Bad Request', {
      detail: { detail: 'Vision service not configured', reason: 'GOOGLE_API_KEY not set' },
    });
    expect(isVisionNotConfiguredError(err)).toBe(true);
  });

  it('false for other 400 body', () => {
    const err = new ApiError(400, 'Bad Request', { detail: 'Some other bad request' });
    expect(isVisionNotConfiguredError(err)).toBe(false);
  });

  it('false for 404', () => {
    const err = new ApiError(404, 'Not Found', { detail: 'No layout' });
    expect(isVisionNotConfiguredError(err)).toBe(false);
  });

  it('false for non-ApiError', () => {
    expect(isVisionNotConfiguredError(new Error('boom'))).toBe(false);
    expect(isVisionNotConfiguredError(null)).toBe(false);
  });
});
