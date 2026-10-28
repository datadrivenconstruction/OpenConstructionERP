// DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Optional BCF source loader for the Unified Issue Hub.
//
// The BCF (BIM Collaboration Format) module is being built in parallel and its
// `api.ts` may not exist yet. A static or literal dynamic import of a missing
// module fails the TypeScript build, so this file discovers `../bcf/api.ts`
// through Vite's `import.meta.glob`, which resolves to an empty map (and no
// build error) when the file is absent and lights up automatically once it
// lands. The `cases` feature uses the same pattern, so it is proven safe in
// this repo's Vite build and vitest. No user-facing strings live here on
// purpose, keeping the glob well away from the i18n extraction tooling.

// Discover the BCF api module without a hard dependency on it. Zero matches
// yields `{}` at build time; one match yields a lazy loader.
const bcfModules = import.meta.glob('../bcf/api.ts');
const bcfLoader = bcfModules['../bcf/api.ts'] ?? null;

/** True when a BCF api module is present in the build. */
export const bcfSourceAvailable: boolean = bcfLoader !== null;

type TopicsFn = (projectId: string) => Promise<unknown>;

/**
 * Probe a loaded module for a topics-list function under the export names the
 * BCF module is most likely to use. Returns null when none is found so the hub
 * degrades to the other sources instead of erroring.
 */
function resolveTopicsFn(mod: Record<string, unknown>): TopicsFn | null {
  const directNames = ['fetchBcfTopics', 'fetchTopics', 'listTopics', 'listBcfTopics'];
  for (const name of directNames) {
    const candidate = mod[name];
    if (typeof candidate === 'function') return candidate as TopicsFn;
  }
  // Object-namespaced form, e.g. `bcfApi.listTopics(projectId)`.
  const api = mod.bcfApi;
  if (api && typeof api === 'object') {
    const apiObj = api as Record<string, unknown>;
    for (const name of ['listTopics', 'topics', 'fetchTopics']) {
      const candidate = apiObj[name];
      if (typeof candidate === 'function') return candidate as TopicsFn;
    }
  }
  return null;
}

/** Coerce a list-or-envelope response into a plain array of raw topics. */
function toArray(res: unknown): unknown[] {
  if (Array.isArray(res)) return res;
  if (res && typeof res === 'object') {
    const items = (res as Record<string, unknown>).items;
    if (Array.isArray(items)) return items;
  }
  return [];
}

/**
 * Fetch BCF topics for a project when the module is available, else resolve to
 * an empty list. Never throws for an absent module or a missing export: those
 * are "no BCF source", not an error the user should see. A genuine network
 * failure from the module's own fetch does propagate, so the hook can surface
 * it as a per-source warning.
 */
export async function fetchBcfTopicsSafe(projectId: string): Promise<unknown[]> {
  if (!bcfLoader || !projectId) return [];
  let mod: Record<string, unknown>;
  try {
    mod = (await bcfLoader()) as Record<string, unknown>;
  } catch {
    // Module could not be loaded at runtime; treat as no BCF source.
    return [];
  }
  const fn = resolveTopicsFn(mod);
  if (!fn) return [];
  const res = await fn(projectId);
  return toArray(res);
}
