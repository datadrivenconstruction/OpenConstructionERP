// The ERP design system (core designSystemRatchet.test.ts) with zero allowance for this module, plus its page canon:
// the top bar names the page, so no page shows its own title.
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';

const RULES: Record<string, { re: RegExp; fix: string }> = {
  arbitraryTextSize: { re: /(?<![\w-])text-\[\d+(?:\.\d+)?(?:px|rem)\]/g, fix: 'text-2xs / xs / sm / base / lg / xl' },
  heavyWeight: { re: /(?<![\w-])font-(?:bold|extrabold|black|light|thin|extralight)(?![\w-])/g, fix: 'font-normal / medium / semibold' },
  arbitraryRadius: { re: /(?<![\w-])rounded(?:-[trblse]{1,2})?-\[\d+(?:\.\d+)?px\]/g, fix: 'rounded-sm / lg / xl / full' },
  rawStatusHue: { re: /(?<![\w-])(?:text|bg|border|ring)-(?:red|rose|amber|yellow|emerald|green|sky)-\d{2,3}/g, fix: 'semantic-* tokens' },
  rawGray: { re: /(?<![\w-])(?:text|bg|border|divide)-(?:gray|slate|zinc|neutral)-\d{2,3}/g, fix: 'content-* / surface-* / border' },
  visiblePageTitle: { re: /<h1 className="(?!sr-only)[^"]*text-(?:lg|xl|2xl)/g, fix: 'PageHeader srTitle; the top bar shows the name' },
};

function files(dir: string, out: string[] = []): string[] {
  for (const e of readdirSync(dir)) {
    const abs = join(dir, e);
    if (statSync(abs).isDirectory()) files(abs, out);
    else if (/\.tsx?$/.test(e) && !/\.(test|spec)\./.test(e) && !e.startsWith('i18n')) out.push(abs);
  }
  return out;
}

describe('design module follows the ERP design system', () => {
  const src = files(__dirname).map((f) => [f, readFileSync(f, 'utf8')] as const);
  for (const [name, rule] of Object.entries(RULES)) {
    it(`${name} (${rule.fix})`, () => {
      const hits = src.flatMap(([f, s]) => (s.match(rule.re) ?? []).map((m) => `${f.slice(__dirname.length + 1)}: ${m}`));
      expect(hits).toEqual([]);
    });
  }
});
