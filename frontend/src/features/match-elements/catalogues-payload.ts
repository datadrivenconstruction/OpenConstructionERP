// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
/**
 * Shape-tolerant unwrapping for the `/api/v1/costs/catalogues-v3/` payload.
 *
 * The endpoint historically shipped two shapes:
 *   • Bare array         → `Catalogue[]` (older queryFn that did `data.catalogues`)
 *   • Wrapped envelope   → `{ catalogues: Catalogue[], server: ServerInfo }`
 *
 * React Query persists cache to sessionStorage. After a fix that switches
 * the queryFn from one shape to the other, an unmodified browser will
 * rehydrate a stale cache entry of the *other* shape — and any consumer
 * that calls `.filter`/`.map` on it crashes the page with
 * `p.data.filter is not a function` (Issue #122, App v2.9.39).
 *
 * This helper accepts either shape and returns a guaranteed array.
 * Anything else (null, undefined, object without `catalogues`) returns
 * `[]` — matching how a fresh fetch would render before data arrived.
 */

export interface CataloguesPayloadCatalogue {
  region: string;
  language: string;
  install_status: string;
  size_mb: number;
  country_iso: string;
}

export type CataloguesPayload =
  | CataloguesPayloadCatalogue[]
  | { catalogues?: CataloguesPayloadCatalogue[] }
  | null
  | undefined;

export function unwrapCataloguesPayload(
  payload: CataloguesPayload,
): CataloguesPayloadCatalogue[] {
  if (Array.isArray(payload)) return payload;
  if (payload && typeof payload === 'object' && 'catalogues' in payload) {
    const inner = (payload as { catalogues?: unknown }).catalogues;
    if (Array.isArray(inner)) return inner as CataloguesPayloadCatalogue[];
  }
  return [];
}
