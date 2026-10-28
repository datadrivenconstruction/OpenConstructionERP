// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * What makes one company profile different from the other twenty-one.
 *
 * The picker showed each profile's name, its sentence and a module count, and
 * a reader comparing two of them had three numbers and no way to learn what
 * the difference was made of. "General Contractor, 38 modules" and
 * "Construction Manager, 33 modules" are nearly the same set - measured, they
 * share twenty-eight - and the five that differ are the entire reason to pick
 * one over the other.
 *
 * Two questions, answered separately because they are asked at different
 * moments. Before choosing: what is this profile for, which is answered by the
 * modules few other profiles carry. While choosing: what happens to my
 * workspace, which is answered by the delta against the profile in force.
 *
 * Core modules are removed from every answer. Several presets re-list a core
 * key inside their own `enabled_modules` - `general_contractor` names `costs`,
 * `catalog` and `assemblies` - and a screen that subtracted one preset from
 * another without dropping those would report Projects or the cost database as
 * lost when nothing can lose them. The core list comes from the backend
 * (`GET /v1/users/onboarding-presets/core/`) rather than a copy here, because
 * a second copy is a second thing to keep in step.
 */

/** The part of a preset this module reads. */
export interface ProfileFacts {
  key: string;
  enabled_modules: string[];
}

/** What a profile turns on, and what of that is particular to it. */
export interface ProfileShape {
  /** Functional modules it enables, core removed, in the preset's own order. */
  modules: string[];
  /** Modules no other profile enables. */
  onlyHere: string[];
  /** Modules at most `rareLimit` other profiles enable. Includes `onlyHere`. */
  rare: string[];
}

/** What changes when the workspace moves from one profile to another. */
export interface ProfileDelta {
  /** Modules the target turns on that the source had off. */
  gained: string[];
  /** Modules the target turns off that the source had on. */
  lost: string[];
  /** Modules both have on. */
  kept: string[];
}

const DEFAULT_RARE_LIMIT = 3;

/**
 * Profiles whose module set contains every other profile's.
 *
 * `full_enterprise` is one, and it has to be left out of the "does anyone else
 * carry this" count or the answer is always yes and nothing is ever rare.
 * Detected by containment rather than by name: a deployment that adds a second
 * catch-all profile would otherwise silently flatten every signature, and the
 * failure would look like a design choice rather than a bug.
 */
function catchAllKeys(sets: Map<string, Set<string>>): Set<string> {
  const out = new Set<string>();
  for (const [key, own] of sets) {
    let containsAll = true;
    for (const [other, theirs] of sets) {
      if (other === key) continue;
      for (const module of theirs) {
        if (!own.has(module)) {
          containsAll = false;
          break;
        }
      }
      if (!containsAll) break;
    }
    if (containsAll && sets.size > 1) out.add(key);
  }
  return out;
}

/**
 * The shape of every profile in `profiles`, keyed by profile key.
 *
 * `rareLimit` is how many other profiles may also carry a module before it
 * stops being worth naming. Three is the default because the twenty-two
 * shipped profiles produce between zero and five such modules each at that
 * threshold, which fits on a card; at five the list runs past a dozen for the
 * broad profiles and stops distinguishing anything.
 */
export function profileShapes(
  profiles: readonly ProfileFacts[],
  coreModules: readonly string[],
  options: { rareLimit?: number } = {},
): Map<string, ProfileShape> {
  const rareLimit = options.rareLimit ?? DEFAULT_RARE_LIMIT;
  const core = new Set(coreModules);

  const own = new Map<string, string[]>();
  const sets = new Map<string, Set<string>>();
  for (const profile of profiles) {
    const modules = profile.enabled_modules.filter(
      (m, i, all) => !core.has(m) && all.indexOf(m) === i,
    );
    own.set(profile.key, modules);
    sets.set(profile.key, new Set(modules));
  }

  const catchAll = catchAllKeys(sets);
  const carriers = new Map<string, number>();
  for (const [key, set] of sets) {
    if (catchAll.has(key)) continue;
    for (const module of set) carriers.set(module, (carriers.get(module) ?? 0) + 1);
  }

  const shapes = new Map<string, ProfileShape>();
  for (const [key, modules] of own) {
    // A catch-all profile is not distinguished by any single module - it is
    // distinguished by holding all of them - so it gets an empty signature
    // rather than a list of every module that happens to be rare elsewhere.
    const others = (module: string) => (carriers.get(module) ?? 0) - (catchAll.has(key) ? 0 : 1);
    const rare = catchAll.has(key) ? [] : modules.filter((m) => others(m) <= rareLimit);
    const onlyHere = catchAll.has(key) ? [] : modules.filter((m) => others(m) === 0);
    shapes.set(key, { modules, onlyHere, rare });
  }
  return shapes;
}

/**
 * What switching from `from` to `to` does, core removed from every list.
 *
 * `from` is null on an account that has never picked a profile. Everything the
 * target carries is then gained and nothing is lost, which is the truth: the
 * workspace starts from whatever the module toggles happen to hold, and the
 * honest thing to show is the target's own set rather than a diff against a
 * baseline we would have to invent.
 */
export function profileDelta(
  from: ProfileFacts | null | undefined,
  to: ProfileFacts,
  coreModules: readonly string[],
): ProfileDelta {
  const core = new Set(coreModules);
  const strip = (modules: string[]) =>
    modules.filter((m, i, all) => !core.has(m) && all.indexOf(m) === i);

  const target = strip(to.enabled_modules);
  if (!from) return { gained: target, lost: [], kept: [] };

  const source = strip(from.enabled_modules);
  const has = new Set(source);
  const wanted = new Set(target);
  return {
    gained: target.filter((m) => !has.has(m)),
    lost: source.filter((m) => !wanted.has(m)),
    kept: target.filter((m) => has.has(m)),
  };
}
