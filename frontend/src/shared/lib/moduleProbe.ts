/**
 * Backend module-loaded probe.
 *
 * Some pages call endpoints from optional backend modules (oe_takeoff,
 * oe_dwg_takeoff, etc). When a user disables a module via Modules → Toggle,
 * those routes 404 and the browser logs the failed request to the network
 * panel even when our JS swallows the error. The probe lets callers gate
 * the request on the loaded state.
 *
 * Cached for the lifetime of the SPA session — module load state only
 * changes via process restart, so a stale-positive surfaces the same 404
 * the consumer would have seen anyway.
 */

import { apiGet } from './api';

interface BackendModule {
  name: string;
  loaded: boolean;
}

let cached: Promise<Record<string, boolean>> | null = null;

function fetchLoadedMap(): Promise<Record<string, boolean>> {
  if (cached !== null) return cached;
  cached = apiGet<BackendModule[]>('/v1/modules/')
    .then((mods) => {
      const map: Record<string, boolean> = {};
      for (const m of mods) map[m.name] = Boolean(m.loaded);
      return map;
    })
    .catch(() => ({} as Record<string, boolean>));
  return cached;
}

/**
 * Resolve to true when the named backend module is loaded on this server,
 * false when it is disabled. On any probe error returns true (fail-open) —
 * the caller's existing error handling catches the actual 404 if we got
 * the state wrong.
 *
 * @example
 *   if (!(await isModuleLoaded('oe_takeoff'))) return EMPTY;
 *   return apiGet<...>('/v1/takeoff/converters/');
 */
export async function isModuleLoaded(moduleName: string): Promise<boolean> {
  const map = await fetchLoadedMap();
  // No entry means we couldn't reach the probe; assume loaded so the
  // caller does its real request and surfaces the real error.
  return map[moduleName] ?? true;
}

/**
 * Reset the module-loaded cache. For tests + the rare case where a module
 * is enabled at runtime without a page reload (Modules page after a toggle).
 */
export function _resetModuleProbeCache(): void {
  cached = null;
}
