// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
import { RETIRED_STATIC_ASSETS_CACHES } from './staticAssetRoute';

/**
 * Delete the service worker caches that earlier builds filled with entries
 * that must not be served again (see ``staticAssetRoute``).
 *
 * Runs on every start rather than once behind a flag. Deleting a cache that
 * is not there is a cheap no-op, and an old service worker still controlling
 * another tab can recreate the old cache until the new one takes over, so a
 * single pass could leave it behind. Never throws: a browser without Cache
 * Storage, a private window or a storage error just leaves things as they
 * were.
 */
export async function retireStaleCaches(
  storage: Pick<CacheStorage, 'delete'> | undefined = typeof caches === 'undefined' ? undefined : caches,
): Promise<string[]> {
  if (!storage) return [];
  const deleted: string[] = [];
  for (const name of RETIRED_STATIC_ASSETS_CACHES) {
    try {
      if (await storage.delete(name)) deleted.push(name);
    } catch {
      // Storage unavailable or blocked: nothing to recover here.
    }
  }
  return deleted;
}
