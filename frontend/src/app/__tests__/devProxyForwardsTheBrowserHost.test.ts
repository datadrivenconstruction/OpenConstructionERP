// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// On the dev server the map style pointed at the backend's own address, so the
// map's sprites and tiles were fetched cross-origin and failed. The proxy now
// forwards the host the browser used (see vite.proxy-headers.ts).

import { describe, expect, it } from 'vitest';
import { forwardBrowserHost } from '../../../vite.proxy-headers';

function fakeProxyReq(initial: Record<string, string> = {}) {
  const headers: Record<string, string> = { ...initial };
  return {
    headers,
    getHeader: (name: string) => headers[name],
    setHeader: (name: string, value: string) => {
      headers[name] = value;
    },
  };
}

describe('the dev proxy', () => {
  it('forwards the host the browser used', () => {
    const proxyReq = fakeProxyReq();
    forwardBrowserHost(proxyReq, { headers: { host: '127.0.0.1:5173' } });
    expect(proxyReq.headers['x-forwarded-host']).toBe('127.0.0.1:5173');
  });

  it('keeps a host a proxy in front already forwarded', () => {
    const proxyReq = fakeProxyReq({ 'x-forwarded-host': 'erp.example.org' });
    forwardBrowserHost(proxyReq, { headers: { host: '127.0.0.1:5173' } });
    expect(proxyReq.headers['x-forwarded-host']).toBe('erp.example.org');
  });

  it('sets nothing without a host', () => {
    const proxyReq = fakeProxyReq();
    forwardBrowserHost(proxyReq, { headers: {} });
    expect(proxyReq.headers).toEqual({});
  });
});
