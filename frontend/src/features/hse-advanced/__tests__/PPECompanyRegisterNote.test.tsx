// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The PPE tab shows one company-wide register in every project. The note says
// so, and it has to say so in the reader's language: a key that is missing
// from a locale falls back to the English default without any visible error.
import { existsSync, readdirSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';

import { afterEach, describe, expect, it } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';

import { PPECompanyRegisterNote } from '../PPECompanyRegisterNote';

const KEYS = ['hse_advanced.ppe_company_register', 'hse_advanced.ppe_company_register_desc'];
// Override-only files; en.ts answers for them.
const OVERRIDE_ONLY = new Set(['en-GB.ts', 'en-US.ts']);

function localesDir(): string {
  const candidates = [
    resolve(process.cwd(), 'src/app/locales'),
    resolve(process.cwd(), 'frontend/src/app/locales'),
  ];
  const dir = candidates.find(existsSync);
  if (!dir) throw new Error(`cannot find the locales, looked in ${candidates.join(' and ')}`);
  return dir;
}

/** The value a locale file gives `key`, read as text; locale files are megabytes of literal. */
function valueOf(src: string, key: string): string | undefined {
  const at = src.indexOf(`"${key}":`);
  if (at < 0) return undefined;
  const open = src.indexOf('"', at + key.length + 3);
  const close = src.indexOf('"', open + 1);
  return src.slice(open + 1, close);
}

afterEach(cleanup);

describe('PPECompanyRegisterNote', () => {
  it('tells the reader the PPE list is company-wide', () => {
    render(<PPECompanyRegisterNote />);
    const note = screen.getByTestId('ppe-company-register-note');
    expect(note).toHaveTextContent('Company-wide register');
    expect(note).toHaveTextContent('every project shows this same list');
  });

  it('is translated in every full locale', () => {
    const files = readdirSync(localesDir()).filter((f) => f.endsWith('.ts') && !OVERRIDE_ONLY.has(f));
    expect(files.length).toBeGreaterThan(40);
    const english = readFileSync(resolve(localesDir(), 'en.ts'), 'utf8');
    const problems: string[] = [];
    for (const file of files) {
      const src = file === 'en.ts' ? english : readFileSync(resolve(localesDir(), file), 'utf8');
      for (const key of KEYS) {
        const value = valueOf(src, key);
        if (!value || !value.trim()) problems.push(`${file} ${key}: missing`);
        // Only the English file may carry the English sentence; anywhere else it
        // is a copy that the reader sees in the wrong language.
        else if (file !== 'en.ts' && key.endsWith('_desc') && value === valueOf(english, key))
          problems.push(`${file} ${key}: untranslated`);
      }
    }
    expect(problems).toEqual([]);
  }, 60_000);
});
