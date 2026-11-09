// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Every module page sits in the same shell: AppLayout's <main> gives the outer
// padding, the page root is `space-y-5 animate-fade-in`, and nothing on the root
// adds its own padding, width cap, centring or card skin. A page that does reads
// as a different product (wider, narrower or boxed) next to its neighbours.
//
// The check reads the root element of each `*Page.tsx` component's final
// `return (` and fails on layout classes there. Full-bleed surfaces and screens
// that render outside AppLayout are listed below, each with its reason.
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

const FEATURES = resolve(__dirname, '../../features');

const ALLOWED: Record<string, string> = {
  'bim/BIMPage.tsx': 'full-bleed 3D viewer (-mx-4 sm:-mx-7)',
  'cad-explorer/CadDataExplorerPage.tsx': 'full-bleed CAD data grid and viewer',
  'dwg-takeoff/DwgTakeoffPage.tsx': 'full-bleed drawing canvas',
  'pipelines/PipelinesPage.tsx': 'full-bleed node canvas editor',
  'auth/ForgotPasswordPage.tsx': 'rendered outside AppLayout (public auth screen)',
  'auth/ResetPasswordPage.tsx': 'rendered outside AppLayout (public auth screen)',
  'field/FieldAuthPage.tsx': 'rendered outside AppLayout (field app sign-in)',
  'file-manager/SharePage.tsx': 'rendered outside AppLayout (public share link)',
};

// Root-level padding, width cap, centring or card skin. `pb-*` stays allowed: it
// clears a sticky bottom bar and is not page chrome.
const LAYOUT =
  /(^|\s)(?:[a-z0-9]+:)?-?(?:p|px|py|pt|ps|pe|pl|pr|mx|my|mt)-\S+|(^|\s)(?:[a-z0-9]+:)?max-w-|(^|\s)container(\s|$)|(^|\s)bg-surface-page|(^|\s)rounded-2xl/;

function pageFiles(): string[] {
  const out: string[] = [];
  for (const dir of readdirSync(FEATURES)) {
    const abs = join(FEATURES, dir);
    if (!statSync(abs).isDirectory()) continue;
    for (const f of readdirSync(abs)) if (/Page\.tsx$/.test(f)) out.push(`${dir}/${f}`);
  }
  return out;
}

function rootClass(src: string, name: string): string | null {
  const s = src.split('\r').join('');
  let i = s.search(new RegExp(`export (default )?function ${name}(?![A-Za-z0-9_])`));
  if (i < 0) i = s.search(new RegExp(`(const|function) ${name}(?![A-Za-z0-9_])`));
  if (i < 0) return null;
  const end = s.indexOf('\n}\n', i);
  const body = s.slice(i, end < 0 ? undefined : end);
  const re = /\n {2}return \(\n\s*(<[^]*?>)/g;
  let m: RegExpExecArray | null;
  let last: RegExpExecArray | null = null;
  while ((m = re.exec(body))) last = m;
  if (!last) return null;
  let tag = last[1]!;
  if (tag === '<>') {
    const next = body.slice(last.index + last[0].length).match(/^\s*(<[^]*?>)/);
    if (next) tag = next[1]!;
  }
  return tag.match(/className=\{?[^"'`]*["'`]([^"'`]*)/)?.[1] ?? '';
}

describe('module pages use the shared page shell', () => {
  const files = pageFiles();

  it('finds the page population', () => {
    expect(files.length).toBeGreaterThan(200);
    const resolved = files.filter((f) => {
      const name = f.split('/')[1]!.replace('.tsx', '');
      return rootClass(readFileSync(join(FEATURES, f), 'utf8'), name) !== null;
    });
    expect(resolved.length).toBeGreaterThan(200);
  });

  it('control: the detector flags a padded, capped root', () => {
    const src = 'export function XPage() {\n  return (\n    <div className="mx-auto max-w-6xl space-y-4 p-4">\n    </div>\n  );\n}\n';
    expect(LAYOUT.test(rootClass(src, 'XPage')!)).toBe(true);
    const ok = 'export function XPage() {\n  return (\n    <div className="space-y-5 animate-fade-in pb-16">\n    </div>\n  );\n}\n';
    expect(LAYOUT.test(rootClass(ok, 'XPage')!)).toBe(false);
  });

  it('no page root sets its own padding, width or card skin', () => {
    const offenders = files
      .filter((f) => !(f in ALLOWED))
      .map((f) => {
        const name = f.split('/')[1]!.replace('.tsx', '');
        return [f, rootClass(readFileSync(join(FEATURES, f), 'utf8'), name) ?? ''] as const;
      })
      .filter(([, cls]) => LAYOUT.test(cls))
      .map(([f, cls]) => `${f}: "${cls}"`);
    expect(offenders).toEqual([]);
  });

  it('every allow-listed page still exists', () => {
    for (const f of Object.keys(ALLOWED)) expect(files).toContain(f);
  });
});
