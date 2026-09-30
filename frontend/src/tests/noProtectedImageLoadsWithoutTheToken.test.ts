// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
/**
 * No stored image or file is loaded by the browser without the bearer token.
 *
 * The API authenticates with an ``Authorization: Bearer`` header only; there
 * is no cookie and no query token. Everything that makes the browser request
 * a URL by itself - ``<img src>``, ``<video>``/``<iframe>`` ``src``, a CSS
 * ``url(...)``, ``window.open``, three.js ``TextureLoader`` - sends no such
 * header, so a protected route answers 401 and the user sees a broken image
 * or an error tab. That was the report: "images do not show and do not open".
 *
 * The one mechanism for these is ``AuthImage`` / ``useAuthedObjectUrl``
 * (``shared/ui/AuthImage.tsx``), or a fetch-then-blob helper such as
 * ``downloadWithAuth``. This scan fails on any browser-loaded URL built from
 * an API path or from a stored file/thumbnail URL field, outside those.
 *
 * Run: npx vitest run src/tests/noProtectedImageLoadsWithoutTheToken.test.ts
 */

import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join, relative, resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

const SRC = resolve(__dirname, '..');

/**
 * Files the scan knowingly skips, each with the reason.
 */
const ALLOWED: Record<string, string> = {
  // Merged into the file manager and no longer routed or imported, see the
  // note beside its former route in app/App.tsx. Left for a later cleanup.
  'features/documents/DocumentsPage.tsx': 'unreachable: nothing imports it',
};

/** An expression that names a protected URL. */
const PROTECTED =
  /\/api\/|\b(thumbnail|thumb|file|photo|image|download|preview|snapshot)_url\b|DownloadUrl\(|\bthumbnailUrl\b|\bfileUrl\b/;

/** Places where the browser fetches a URL on its own, without our headers. */
const SINKS: { name: string; re: RegExp }[] = [
  { name: '<img src>', re: /<img\b[^>]*?\bsrc=\{([^}]*)\}/g },
  { name: '<video|audio|iframe|source src>', re: /<(?:video|audio|iframe|source)\b[^>]*?\bsrc=\{([^}]*)\}/g },
  { name: 'CSS url()', re: /url\(\$\{([^}]*)\}\)/g },
  { name: 'window.open', re: /window\.open\(\s*([^,)]+)/g },
  { name: 'TextureLoader.load', re: /(?:loader|TextureLoader\(\))\.load\(\s*([^,)]+)/g },
];

function walk(dir: string, out: string[]) {
  for (const name of readdirSync(dir)) {
    if (name === 'node_modules' || name === 'locales' || name === '__tests__' || name === 'tests') continue;
    const full = join(dir, name);
    if (statSync(full).isDirectory()) walk(full, out);
    else if (/\.tsx?$/.test(name) && !/\.test\.tsx?$/.test(name)) out.push(full);
  }
}

/** Comments name the defect in prose ("a bare <img> would 401"); only code counts. */
function stripComments(text: string): string {
  return text
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/\{\s*\/\*[\s\S]*?\*\/\s*\}/g, '')
    .replace(/(^|[^:'"`])\/\/.*$/gm, '$1');
}

const files: string[] = [];
walk(SRC, files);
const sources = files.map((full) => ({
  rel: relative(SRC, full).replace(/\\/g, '/'),
  code: stripComments(readFileSync(full, 'utf-8')),
}));

describe('protected images and files are never loaded without the token', () => {
  it('scanned the source tree', () => {
    expect(sources.length).toBeGreaterThan(500);
    expect(sources.some((s) => s.rel === 'shared/ui/AuthImage.tsx')).toBe(true);
  });

  it('finds the defect it guards against', () => {
    // A scan that cannot see the original bug proves nothing by passing.
    const sample = stripComments('<img\n  src={row.thumbnail_url}\n  alt=""\n/>');
    expect(SINKS[0]!.re.test(sample)).toBe(true);
    SINKS[0]!.re.lastIndex = 0;
    expect(PROTECTED.test('row.thumbnail_url')).toBe(true);
    expect(PROTECTED.test('`/api/v1/documents/${id}/download`')).toBe(true);
    expect(PROTECTED.test('objectUrl')).toBe(false);
  });

  it('no browser-loaded URL points at a protected route', () => {
    const offenders: string[] = [];
    for (const { rel, code } of sources) {
      if (rel in ALLOWED) continue;
      for (const { name, re } of SINKS) {
        for (const match of code.matchAll(re)) {
          const expr = match[1]!.trim();
          if (PROTECTED.test(expr)) offenders.push(`${rel}: ${name} ${expr}`);
        }
      }
    }
    expect(
      offenders,
      'route these through AuthImage / useAuthedObjectUrl (shared/ui/AuthImage.tsx) or downloadWithAuth: ' +
        'the browser sends no Authorization header for them, so they 401',
    ).toEqual([]);
  });

  it('every allowlisted file still exists', () => {
    for (const rel of Object.keys(ALLOWED)) {
      expect(sources.some((s) => s.rel === rel), `${rel} is allowlisted but gone; drop it from ALLOWED`).toBe(true);
    }
  });
});
