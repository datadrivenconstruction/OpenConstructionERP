import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join, resolve, sep } from 'node:path';
import { describe, expect, it } from 'vitest';

// Under the public demo the app lives at /demo, so a literal '/brand/...' in
// source hits the marketing site. Public-folder URLs must go through
// publicAsset() (shared/lib/publicAsset.ts).
const SRC = resolve(__dirname, '../..');
const FOLDERS = 'brand|roles|academy-courses|assets/vendor|assets/people|assets/videos|contributors|pwa';
const LITERAL = new RegExp('(?<!publicAsset\\()[\'"`](/(?:' + FOLDERS + ')/[^\'"`]*)[\'"`]', 'g');
const COMMENT_LINE = /^\s*(\/\/|\*|\/\*)/;
// Files that legitimately hold such literals (service worker route tables).
const ALLOW = new Set(['pwa/staticAssetRoute.ts', 'shared/lib/publicAsset.ts']);

function walk(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) {
      if (['locales', '__tests__', 'test', 'node_modules'].includes(name)) continue;
      walk(p, out);
    } else if (/\.(ts|tsx)$/.test(name) && !/\.test\.|\.spec\.|\.generated\./.test(name)) out.push(p);
  }
  return out;
}

describe('public assets go through publicAsset()', () => {
  it('no source file uses a root-absolute public asset literal', () => {
    const bad: string[] = [];
    for (const f of walk(SRC)) {
      const rel = f.slice(SRC.length + 1).split(sep).join('/');
      if (ALLOW.has(rel)) continue;
      const text = readFileSync(f, 'utf8')
        .split(/\r?\n/)
        .filter((l) => !COMMENT_LINE.test(l))
        .join('\n');
      for (const m of text.matchAll(LITERAL)) bad.push(`${rel}: ${m[1]}`);
    }
    expect(bad).toEqual([]);
  }, 60_000);
});
