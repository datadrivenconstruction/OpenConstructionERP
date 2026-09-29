// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Linking BIM elements to a task or a schedule activity PATCHes
// /bim-links/, with the slash. The client sent /bim-links, and since the
// application does not redirect slashes every link from the viewer answered 404.

import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('@/shared/lib/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/shared/lib/api')>()),
  apiPatch: vi.fn(() => Promise.resolve({})),
}));

import { apiPatch } from '@/shared/lib/api';
import { updateActivityBIMLinks, updateTaskBIMLinks } from './api';

beforeEach(() => {
  vi.clearAllMocks();
});

describe('BIM link routes', () => {
  it('patches a task under /bim-links/', async () => {
    await updateTaskBIMLinks('t-1', ['e-1']);
    expect(apiPatch).toHaveBeenCalledWith('/v1/tasks/t-1/bim-links/', { bim_element_ids: ['e-1'] });
  });

  it('patches a schedule activity under /bim-links/', async () => {
    await updateActivityBIMLinks('a-1', ['e-1']);
    expect(apiPatch).toHaveBeenCalledWith('/v1/schedule/activities/a-1/bim-links/', {
      bim_element_ids: ['e-1'],
    });
  });
});
