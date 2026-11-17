import { existsSync, readFileSync, readdirSync } from 'node:fs';
import { resolve } from 'node:path';

import { describe, expect, it } from 'vitest';

/**
 * The contacts filter lists every contact type by its translated name. When
 * two types share one word in a language (French had "Client" for both the
 * CRM customer and the construction client), the strip shows the same chip
 * twice and nobody can tell which is which (#564).
 */

const LOCALES_DIR = ['src/app/locales', 'frontend/src/app/locales']
  .map((p) => resolve(process.cwd(), p))
  .find(existsSync);

/** Mirrors CONTACT_TYPES in features/contacts/ContactsPage.tsx. */
const TYPES = [
  'customer',
  'lead',
  'client',
  'contractor',
  'subcontractor',
  'supplier',
  'consultant',
  'authority',
  'internal',
];

function labels(code: string): Record<string, string> {
  const text = readFileSync(resolve(LOCALES_DIR as string, `${code}.ts`), 'utf8');
  const out: Record<string, string> = {};
  for (const type of TYPES) {
    const match = text.match(new RegExp(`"contacts\\.type_${type}":\\s*(["'])((?:\\\\.|(?!\\1).)*)\\1`));
    if (match?.[2] !== undefined) out[type] = match[2];
  }
  return out;
}

describe('contact types read differently in every locale', () => {
  const codes = readdirSync(LOCALES_DIR as string)
    .filter((f) => f.endsWith('.ts') && f !== 'index.ts')
    .map((f) => f.slice(0, -3))
    .sort();

  it('finds the locale files', () => {
    expect(codes.length).toBeGreaterThan(30);
  });

  for (const code of codes) {
    it(`${code} gives each contact type its own name`, () => {
      const seen = new Map<string, string>();
      const clashes: string[] = [];
      for (const [type, label] of Object.entries(labels(code))) {
        const norm = label.trim().toLocaleLowerCase();
        const other = seen.get(norm);
        if (other) clashes.push(`${other} and ${type} are both "${label}"`);
        else seen.set(norm, type);
      }
      expect(clashes, code).toEqual([]);
    });
  }
});
