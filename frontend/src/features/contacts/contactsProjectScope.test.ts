// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { beforeEach, describe, expect, it, vi } from 'vitest';

const apiGet = vi.hoisted(() => vi.fn());
vi.mock('@/shared/lib/api', async () => {
  const actual = await vi.importActual<typeof import('@/shared/lib/api')>('@/shared/lib/api');
  return { ...actual, apiGet };
});

import { fetchContactStats, fetchContacts } from './api';

describe('contacts narrowed to one project', () => {
  beforeEach(() => apiGet.mockReset().mockResolvedValue({ items: [], total: 0 }));

  it('asks the directory for the open demo project only', async () => {
    await fetchContacts({ limit: 500, project_id: 'p-london' });
    expect(apiGet).toHaveBeenCalledWith('/v1/contacts/?limit=500&project_id=p-london');
  });

  it('asks for every contact without a project', async () => {
    await fetchContacts({ limit: 500 });
    expect(apiGet).toHaveBeenCalledWith('/v1/contacts/?limit=500');
  });

  it('counts the same contacts the list shows', async () => {
    await fetchContactStats('p-london');
    expect(apiGet).toHaveBeenLastCalledWith('/v1/contacts/stats/?project_id=p-london');
    await fetchContactStats(null);
    expect(apiGet).toHaveBeenLastCalledWith('/v1/contacts/stats/');
  });
});
