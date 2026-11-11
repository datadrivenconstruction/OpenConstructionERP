// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The design system in tailwind.config.js and index.css (type scale, radius
// ladder, semantic colours, tokens for text and surfaces) only holds if pages
// stop reaching around it. Each count below may go down, never up. When you
// lower one, lower the number here in the same commit.
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

const SRC = resolve(__dirname, '../..');

const RULES: Record<string, { re: RegExp; max: number; fix: string }> = {
  arbitraryTextSize: {
    re: /(?<![\w-])text-\[\d+(?:\.\d+)?(?:px|rem)\]/g,
    max: 58,
    fix: 'use text-2xs (11) / xs (12) / sm (13) / base (14) / lg (16) / xl (18)',
  },
  heavyWeight: {
    re: /(?<![\w-])font-(?:bold|extrabold|black|light|thin|extralight)(?![\w-])/g,
    max: 13,
    fix: 'weights are font-normal, font-medium, font-semibold',
  },
  arbitraryRadius: {
    re: /(?<![\w-])rounded(?:-[trblse]{1,2})?-\[\d+(?:\.\d+)?px\]/g,
    max: 8,
    fix: 'use rounded-sm (6) / lg (8, controls) / xl (12, cards) / full (chips)',
  },
  rawStatusHue: {
    re: /(?<![\w-])(?:text|bg|border|ring)-(?:red|rose|amber|yellow|emerald|green|sky)-\d{2,3}/g,
    max: 729,
    fix: 'use text-semantic-*, bg-semantic-*-bg, border-semantic-*/30',
  },
  rawGray: {
    re: /(?<![\w-])(?:text|bg|border|divide)-(?:gray|slate|zinc|neutral)-\d{2,3}/g,
    max: 283,
    fix: 'use text-content-*, bg-surface-*, border-border(-light)',
  },
};

function files(dir: string, out: string[] = []): string[] {
  for (const e of readdirSync(dir)) {
    if (e === 'locales' || e === '__tests__' || e === 'node_modules') continue;
    const abs = join(dir, e);
    if (statSync(abs).isDirectory()) files(abs, out);
    else if (/\.tsx?$/.test(e) && !/\.(test|spec)\./.test(e) && !e.endsWith('.d.ts')) out.push(abs);
  }
  return out;
}

describe('design system ratchet', () => {
  const sources = files(SRC).map((f) => readFileSync(f, 'utf8'));
  for (const [name, rule] of Object.entries(RULES)) {
    it(`${name} does not grow (${rule.fix})`, () => {
      let n = 0;
      for (const s of sources) n += s.match(rule.re)?.length ?? 0;
      expect(n, `${name}: ${rule.fix}`).toBeLessThanOrEqual(rule.max);
    });
  }
});
