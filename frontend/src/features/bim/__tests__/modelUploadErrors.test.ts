// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// A refused model upload reads in the user's language: the body-size and rate
// guards answer in fixed English, so their status speaks instead.
import { beforeAll, describe, it, expect } from 'vitest';
import i18next from 'i18next';
import { modelUploadFailure, modelUploadNetworkError } from '../api';
import { ApiError } from '@/shared/lib/api';

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
}

beforeAll(async () => {
  if (!i18next.isInitialized) await i18next.init({ lng: 'en', resources: { en: { translation: {} } } });
});

describe('modelUploadFailure', () => {
  it('replaces the size guard English with the translated status message', async () => {
    const err = await modelUploadFailure(jsonResponse(413, { detail: 'Request body too large' }));
    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(413);
    expect(err.message).not.toBe('Request body too large');
    expect(err.message).toMatch(/too large/i);
  });

  it('replaces the rate guard English with the translated status message', async () => {
    const err = await modelUploadFailure(jsonResponse(429, { detail: 'Too many uploads. Please wait a moment and try again.' }));
    expect(err.status).toBe(429);
    expect(err.message).toMatch(/too many requests/i);
  });

  it('keeps the coded refusal fallback when the build has no text for the code', async () => {
    const err = await modelUploadFailure(
      jsonResponse(400, { detail: { code: 'no_such_code_here', message: 'Uploaded file is empty.', params: {} } }),
    );
    expect(err.message).toBe('Uploaded file is empty.');
  });

  it('falls back to the status when the body is not JSON', async () => {
    const err = await modelUploadFailure(new Response('<html>bad gateway</html>', { status: 502 }));
    expect(err.status).toBe(502);
    expect(err.message).toMatch(/temporarily unavailable/i);
  });
});

describe('modelUploadNetworkError', () => {
  it('says the server could not be reached', () => {
    expect(modelUploadNetworkError().message).toMatch(/cannot connect to server/i);
  });
});
