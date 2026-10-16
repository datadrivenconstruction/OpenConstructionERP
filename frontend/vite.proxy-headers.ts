// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The dev server proxies /api to the backend with changeOrigin, which rewrites
// Host to the backend's own address. The geo hub builds absolute URLs into the
// map style from the host the caller used (MapLibre's worker has no document
// base), so behind the proxy the style pointed at http://127.0.0.1:8000 while
// the page ran on :5173: every sprite and tile fetch went cross-origin, the
// console filled with CORS errors and the map stayed empty, in the dark theme
// as well. Forwarding the browser's host lets the backend answer with URLs on
// the dev server's origin, which the same proxy then serves.

interface IncomingLike {
  headers: Record<string, string | string[] | undefined>;
}

interface ProxyRequestLike {
  getHeader(name: string): unknown;
  setHeader(name: string, value: string): void;
}

/** Tell the backend which host the browser used, unless a proxy in front already did. */
export function forwardBrowserHost(proxyReq: ProxyRequestLike, req: IncomingLike): void {
  const host = req.headers.host;
  if (typeof host === 'string' && host && !proxyReq.getHeader('x-forwarded-host')) {
    proxyReq.setHeader('x-forwarded-host', host);
  }
}
