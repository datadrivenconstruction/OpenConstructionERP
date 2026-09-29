// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The quality gates of a requirement set are served at /{set_id}/gates/. The
// client asked for /gates, which the application does not redirect, so the
// gate panel read a 404 as "no gates".

import { describe, it, expect, vi } from 'vitest';

vi.mock('@/shared/lib/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/shared/lib/api')>()),
  apiGet: vi.fn(() => Promise.resolve([])),
}));

import { apiGet } from '@/shared/lib/api';
import { fetchGates } from './api';

describe('requirement set gates', () => {
  it('reads the gates under /gates/', async () => {
    await fetchGates('s-1');
    expect(apiGet).toHaveBeenCalledWith('/v1/requirements/s-1/gates/');
  });
});
