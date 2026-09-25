import { existsSync, readFileSync, readdirSync } from 'node:fs';
import { resolve } from 'node:path';

import { describe, expect, it } from 'vitest';

/**
 * Every pack card, chip and picker names a pack through
 * `modules.pp_name_<slug>`, falling back to the manifest's English
 * `partner_name`. Only 19 of the shipped packs had a key, so a German user
 * read "Germany Construction Pack", and a Croatian one "Croatia Construction
 * Pack", on otherwise translated screens. The file name is from the first
 * round, which fixed the four newest country packs; it now covers them all.
 *
 * The packs are read from `packs/*` the way the registry finds them, so a new
 * pack without a key fails here instead of shipping an English name.
 */

function firstExisting(paths: string[]): string {
  const found = paths.map((p) => resolve(process.cwd(), p)).find(existsSync);
  if (!found) throw new Error(`none of ${paths.join(', ')} exists: run this from frontend or from the repository root`);
  return found;
}

const LOCALES_DIR = firstExisting(['src/app/locales', 'frontend/src/app/locales']);
const PACKS_DIR = firstExisting(['../packs', 'packs']);

const PAIR = /^\s*"((?:[^"\\]|\\.)*)"\s*:\s*"((?:[^"\\]|\\.)*)"\s*,?\s*$/;

function readPairs(file: string): Map<string, string> {
  const out = new Map<string, string>();
  for (const line of readFileSync(resolve(LOCALES_DIR, file), 'utf-8').split(/\r?\n/)) {
    const m = PAIR.exec(line);
    if (m) out.set(m[1]!, m[2]!);
  }
  return out;
}

interface Pack {
  slug: string;
  country: string | null;
}

function shippedPacks(): Pack[] {
  const packs: Pack[] = [];
  for (const dir of readdirSync(PACKS_DIR)) {
    const src = resolve(PACKS_DIR, dir, 'src');
    if (!existsSync(src)) continue;
    for (const mod of readdirSync(src)) {
      const manifest = resolve(src, mod, 'manifest.py');
      if (!existsSync(manifest)) continue; // a deprecated shim re-exports another pack
      const text = readFileSync(manifest, 'utf-8');
      const slug = /slug="([^"]+)"/.exec(text)?.[1];
      if (!slug) continue;
      packs.push({ slug, country: /"country":\s*"([A-Z]{2})"/.exec(text)?.[1] ?? null });
    }
  }
  return packs;
}

// Named after a partner organisation or product rather than a market. A proper
// name reads the same in every language, so these keep the manifest name.
const PROPER_NAMES = new Set(['batimatech-ca', 'bimhessen-de', 'doker-formwork']);

const PACKS = shippedPacks();
const NAMED = PACKS.filter((p) => !PROPER_NAMES.has(p.slug));
const keyOf = (slug: string) => `modules.pp_name_${slug.replace(/-/g, '_')}`;
const BASE_FILES = readdirSync(LOCALES_DIR).filter((f) => f.endsWith('.ts') && !f.includes('-'));
const en = readPairs('en.ts');

describe('every shipped pack is named in the reader language', () => {
  it('finds the packs', () => {
    expect(PACKS.length).toBeGreaterThan(40);
  });

  it('en.ts names every pack that is not a proper name', () => {
    expect(NAMED.filter((p) => !en.has(keyOf(p.slug))).map((p) => p.slug)).toEqual([]);
  });

  for (const file of BASE_FILES.filter((f) => f !== 'en.ts')) {
    it(`${file}: names every pack, and no market pack in English`, () => {
      const pairs = readPairs(file);
      expect(NAMED.filter((p) => !pairs.get(keyOf(p.slug))).map((p) => p.slug)).toEqual([]);
      const english = NAMED.filter(
        (p) => p.country && p.country !== 'XX' && pairs.get(keyOf(p.slug)) === en.get(keyOf(p.slug)),
      );
      expect(english.map((p) => p.slug)).toEqual([]);
    });
  }
});
