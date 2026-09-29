// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// fullInstallPackStream - how the streamed pack install reports a failure of
// the whole request, as opposed to a failed step inside it.
//
// It used to throw `new Error(responseText)`, so a 403 reached the dialog as a
// string of JSON and a stream cut by a proxy returned as if it had finished.

import { describe, it, expect, vi, afterEach } from 'vitest';

import type { TFunction } from 'i18next';

import {
  fullInstallPackStream,
  packInstallFailureTitle,
  PackInstallError,
  type StreamInstallEvent,
} from '../partnerPacksApi';
import { useAuthStore } from '@/stores/useAuthStore';

function sseResponse(frames: string[], init: ResponseInit = { status: 200 }): Response {
  const encoder = new TextEncoder();
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const f of frames) controller.enqueue(encoder.encode(f));
      controller.close();
    },
  });
  return new Response(body, init);
}

function frame(event: string, data: unknown): string {
  return `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;
}

const realRefresh = useAuthStore.getState().refreshAccessToken;

afterEach(() => {
  vi.unstubAllGlobals();
  useAuthStore.setState({ refreshAccessToken: realRefresh });
});

describe('packInstallFailureTitle', () => {
  it('gives the onboarding toast a translatable headline instead of the English message', () => {
    const t = vi.fn((key: string, opts?: { defaultValue?: string }) => `${key}|${opts?.defaultValue}`);
    const title = packInstallFailureTitle(t as unknown as TFunction, 'incomplete');
    expect(t).toHaveBeenCalledWith('modules.pp_fail_incomplete_title', expect.anything());
    expect(title).toBe('modules.pp_fail_incomplete_title|The connection dropped during the installation');
  });
});

describe('fullInstallPackStream and an expired access token', () => {
  const okStream = () =>
    sseResponse([frame('start', { slug: 'x', total: 0, steps: [] }), frame('done', { slug: 'x', ok: true, steps: [] })]);
  const unauthorized = () => new Response(JSON.stringify({ detail: 'Token expired' }), { status: 401 });
  const authHeader = (call: unknown) =>
    ((call as [string, RequestInit])[1].headers as Record<string, string>).Authorization;

  it('refreshes once and replays, so an expired token is not a lost session', async () => {
    const refresh = vi.fn(async () => 'fresh-token');
    useAuthStore.setState({ refreshAccessToken: refresh });
    const fetchMock = vi.fn().mockResolvedValueOnce(unauthorized()).mockResolvedValueOnce(okStream());
    vi.stubGlobal('fetch', fetchMock);

    const events: StreamInstallEvent[] = [];
    await fullInstallPackStream('x', (ev) => events.push(ev));

    expect(refresh).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(authHeader(fetchMock.mock.calls[1])).toBe('Bearer fresh-token');
    expect(events.map((e) => e.type)).toEqual(['start', 'done']);
  });

  it('a refresh that fails reports the session as ended', async () => {
    useAuthStore.setState({ refreshAccessToken: vi.fn(async () => null) });
    const fetchMock = vi.fn().mockResolvedValueOnce(unauthorized());
    vi.stubGlobal('fetch', fetchMock);

    const e = (await fullInstallPackStream('x', () => {}).catch((x: unknown) => x)) as PackInstallError;
    expect(e.kind).toBe('unauthenticated');
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('a 401 that survives the refresh is not retried again', async () => {
    useAuthStore.setState({ refreshAccessToken: vi.fn(async () => 'fresh-token') });
    const fetchMock = vi.fn().mockResolvedValueOnce(unauthorized()).mockResolvedValueOnce(unauthorized());
    vi.stubGlobal('fetch', fetchMock);

    const e = (await fullInstallPackStream('x', () => {}).catch((x: unknown) => x)) as PackInstallError;
    expect(e.kind).toBe('unauthenticated');
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it('a 403 is not a token problem and does not refresh', async () => {
    const refresh = vi.fn(async () => 'fresh-token');
    useAuthStore.setState({ refreshAccessToken: refresh });
    vi.stubGlobal('fetch', vi.fn(async () => new Response('{}', { status: 403 })));

    const e = (await fullInstallPackStream('x', () => {}).catch((x: unknown) => x)) as PackInstallError;
    expect(e.kind).toBe('forbidden');
    expect(refresh).not.toHaveBeenCalled();
  });
});

describe('fullInstallPackStream failures', () => {
  it('a 403 rejects as forbidden with the server detail, not raw JSON', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response(JSON.stringify({ detail: "Role 'admin' required" }), { status: 403 })),
    );
    const err = await fullInstallPackStream('germany-de', () => {}).catch((e: unknown) => e);
    expect(err).toBeInstanceOf(PackInstallError);
    const e = err as PackInstallError;
    expect(e.kind).toBe('forbidden');
    expect(e.status).toBe(403);
    expect(e.detail).toBe("Role 'admin' required");
    expect(e.message).not.toContain('{');
  });

  it('an HTML error page from a proxy leaves no detail', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('<html>502 Bad Gateway</html>', { status: 502 })));
    const e = (await fullInstallPackStream('x', () => {}).catch((x: unknown) => x)) as PackInstallError;
    expect(e.kind).toBe('server');
    expect(e.detail).toBeNull();
  });

  it('a fetch that never reaches the server rejects as network', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        throw new TypeError('Failed to fetch');
      }),
    );
    const e = (await fullInstallPackStream('x', () => {}).catch((x: unknown) => x)) as PackInstallError;
    expect(e.kind).toBe('network');
  });

  it('a stream that ends without done rejects as incomplete', async () => {
    const events: StreamInstallEvent[] = [];
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        sseResponse([
          frame('start', { slug: 'x', total: 1, steps: [{ step: 'apply_pack', label_key: 'k', label: 'l' }] }),
          frame('step_start', { step: 'apply_pack', index: 0, total: 1 }),
        ]),
      ),
    );
    const e = (await fullInstallPackStream('x', (ev) => events.push(ev)).catch(
      (x: unknown) => x,
    )) as PackInstallError;
    expect(e.kind).toBe('incomplete');
    expect(events.map((ev) => ev.type)).toEqual(['start', 'step_start']);
  });

  it('a complete stream resolves and sends the chosen bases and retry steps', async () => {
    const fetchMock = vi.fn(async () =>
      sseResponse([frame('start', { slug: 'x', total: 0, steps: [] }), frame('done', { slug: 'x', ok: true, steps: [] })]),
    );
    vi.stubGlobal('fetch', fetchMock);
    await fullInstallPackStream('x', () => {}, { costRegions: ['cwicr-de-berlin'], onlySteps: ['cost_db'] });
    const body = JSON.parse((fetchMock.mock.calls[0] as unknown as [string, RequestInit])[1].body as string);
    expect(body.cost_regions).toEqual(['cwicr-de-berlin']);
    expect(body.only_steps).toEqual(['cost_db']);
  });

  it('asks for the resource catalogue only when the caller does', async () => {
    const fetchMock = vi.fn(async () =>
      sseResponse([frame('start', { slug: 'x', total: 0, steps: [] }), frame('done', { slug: 'x', ok: true, steps: [] })]),
    );
    vi.stubGlobal('fetch', fetchMock);
    // Onboarding and the cases strip pass no option: the catalogue step must
    // not run for them, a failed download would fail their install unseen.
    await fullInstallPackStream('x', () => {}, { demoCount: 2 });
    await fullInstallPackStream('x', () => {}, { installCatalog: true });
    const bodies = fetchMock.mock.calls.map((c) =>
      JSON.parse((c as unknown as [string, RequestInit])[1].body as string),
    );
    expect(bodies[0].install_catalog).toBe(false);
    expect(bodies[1].install_catalog).toBe(true);
  });
});
