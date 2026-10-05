// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The payment-plan route answers 404 to a caller with no grant on the
// project, so that it never confirms the project exists. For the client's
// card that is "nothing to show", and must not surface as a load failure;
// every other refusal still does.

import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest';
import {
  PORTAL_SESSION_KEY,
  PortalHttpError,
  listProjectPaymentPlans,
} from '../api';

function respond(status: number, body: unknown) {
  return vi.fn().mockResolvedValue({
    ok: status >= 200 && status < 300,
    status,
    json: () => Promise.resolve(body),
  });
}

beforeEach(() => {
  sessionStorage.setItem(PORTAL_SESSION_KEY, 'tok');
});

afterEach(() => {
  sessionStorage.clear();
  vi.unstubAllGlobals();
});

describe('listProjectPaymentPlans', () => {
  it('reads a 404 as no plan to show', async () => {
    vi.stubGlobal('fetch', respond(404, { detail: 'Project not found' }));
    await expect(listProjectPaymentPlans('p-1')).resolves.toEqual({ items: [] });
  });

  it('still fails on any other refusal, with its status', async () => {
    vi.stubGlobal('fetch', respond(500, { detail: 'boom' }));
    const err = await listProjectPaymentPlans('p-1').catch((e: unknown) => e);
    expect(err).toBeInstanceOf(PortalHttpError);
    expect((err as PortalHttpError).status).toBe(500);
    expect((err as Error).message).toBe('boom');
  });

  it('passes the plans through as the server sent them', async () => {
    const body = { items: [{ contract_id: 'ct-1', lines: [] }] };
    const fetchMock = respond(200, body);
    vi.stubGlobal('fetch', fetchMock);
    await expect(listProjectPaymentPlans('p 1')).resolves.toEqual(body);
    expect(fetchMock.mock.calls[0]![0]).toBe('/api/v1/portal/projects/p%201/payment-plan');
  });
});
