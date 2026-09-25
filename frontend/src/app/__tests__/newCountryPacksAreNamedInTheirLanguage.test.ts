import { existsSync, readFileSync, readdirSync } from 'node:fs';
import { resolve } from 'node:path';

import { describe, expect, it } from 'vitest';

/**
 * Every pack card, chip and picker names a pack through
 * `modules.pp_name_<slug>`, falling back to the manifest's English
 * `partner_name`. The Croatia, Romania, Greece and Ukraine packs shipped with
 * no key, so a Croatian user saw "Croatia Construction Pack" on a Croatian
 * screen, and the same in every other language. The names now live in every
 * base locale, and in each country's own language the name is not English.
 */

const RESOLVED = ['src/app/locales', 'frontend/src/app/locales']
  .map((p) => resolve(process.cwd(), p))
  .find(existsSync);
if (!RESOLVED) {
  throw new Error(
    'no locale directory at src/app/locales or frontend/src/app/locales: run this from frontend or from the repository root',
  );
}
const LOCALES_DIR = RESOLVED;

const PAIR = /^\s*"((?:[^"\\]|\\.)*)"\s*:\s*"((?:[^"\\]|\\.)*)"\s*,?\s*$/;

function readPairs(file: string): Map<string, string> {
  const out = new Map<string, string>();
  for (const line of readFileSync(resolve(LOCALES_DIR, file), 'utf-8').split(/\r?\n/)) {
    const m = PAIR.exec(line);
    if (m) out.set(m[1]!, m[2]!);
  }
  return out;
}

const PACKS: Record<string, string> = {
  croatia_hr: 'hr',
  romania_ro: 'ro',
  greece_gr: 'el',
  ukraine_ua: 'uk',
};

const BASE_FILES = readdirSync(LOCALES_DIR).filter((f) => f.endsWith('.ts') && !f.includes('-'));
const en = readPairs('en.ts');

describe('the new country packs are named in the reader language', () => {
  for (const file of BASE_FILES) {
    it(`${file}: names all four packs`, () => {
      const pairs = readPairs(file);
      const missing = Object.keys(PACKS).filter((slug) => !pairs.get(`modules.pp_name_${slug}`));
      expect(missing).toEqual([]);
    });
  }

  for (const [slug, lang] of Object.entries(PACKS)) {
    it(`${lang}.ts: the ${slug} pack is not named in English`, () => {
      const key = `modules.pp_name_${slug}`;
      expect(readPairs(`${lang}.ts`).get(key)).not.toBe(en.get(key));
    });
  }
});
