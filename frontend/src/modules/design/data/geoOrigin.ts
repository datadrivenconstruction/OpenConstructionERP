// Design module (ERP side of the design editor link).
/** A geo-hub URL with the page's origin, so it goes through the same host as the page. */
export function sameOrigin(url: string, origin = globalThis.location?.origin ?? ''): string {
  const m = /^https?:\/\/[^/]+(\/api\/v1\/geo-hub\/.*)$/.exec(url);
  return m && origin ? `${origin}${m[1]}` : url;
}
