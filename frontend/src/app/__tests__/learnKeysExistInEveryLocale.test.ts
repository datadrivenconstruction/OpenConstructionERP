// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The Academy links add interface strings. A key present only in English
// would show English on every other screen without any gate noticing, so this
// reads each locale file as text (they are too large to import 45 times) and
// asks for the key and for a value that is not the English one.

import { readFileSync, readdirSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

const DIR = resolve(__dirname, '../locales');
// Regional English files hold only their differences from English.
const OVERRIDE_ONLY = new Set(['en-GB.ts', 'en-US.ts']);
const KEYS = [
  'learn.for_this_step',
  'learn.all_courses',
  'nav.courses',
  'learn.page_subtitle',
  'learn.kind.course',
  'learn.kind.lesson',
  'learn.kind.checklist',
  'learn.kind.article',
  'learn.filter.topic',
  'learn.filter.track',
  'learn.filter.this_screen',
  'learn.opens_academy',
  'learn.opens_new_tab',
  'learn.in_language',
  'learn.paid_tooltip',
  'learn.paid_lesson_tooltip',
  'learn.empty_title',
  'settings.learning_tips_title',
  'settings.learning_tips_subtitle',
  'settings.learning_tips_toggle',
  'settings.learning_tips_hidden_count',
  'settings.learning_tips_show_all',
];

function valueOf(text: string, key: string): string | null {
  const needle = `\n    "${key}": `;
  const at = text.indexOf(needle);
  if (at < 0) return null;
  const from = at + needle.length;
  const end = text.indexOf('\n', from);
  return JSON.parse(text.slice(from, end < 0 ? undefined : end).trim().replace(/,$/, '')) as string;
}

describe('the Academy link strings', () => {
  const files = readdirSync(DIR).filter((f) => f.endsWith('.ts') && !OVERRIDE_ONLY.has(f));
  const english = readFileSync(resolve(DIR, 'en.ts'), 'utf8');

  it('exist in English', () => {
    for (const key of KEYS) expect(valueOf(english, key), key).not.toBeNull();
  });

  it('exist, translated and with the same placeholders, in every other locale', () => {
    const missing: string[] = [];
    const copied: string[] = [];
    const placeholders = (s: string) => [...s.matchAll(/\{\{\s*(\w+)/g)].map((m) => m[1]).sort().join();
    for (const file of files.filter((f) => f !== 'en.ts')) {
      const text = readFileSync(resolve(DIR, file), 'utf8');
      for (const key of KEYS) {
        const value = valueOf(text, key);
        const en = valueOf(english, key)!;
        if (value === null) missing.push(`${file} ${key}`);
        else if (placeholders(value) !== placeholders(en)) missing.push(`${file} ${key} placeholders`);
        else if (value === en && !/^(learn\.kind\.checklist|nav\.courses)$/.test(key)) copied.push(`${file} ${key}`);
      }
    }
    expect(missing).toEqual([]);
    // A few words are the same in some languages ("Checklist"), the rest must be translated.
    expect(copied.length).toBeLessThan(20);
  }, 60_000);

  it('say "paid" in no key but the two tooltips', () => {
    const offenders = KEYS.filter((k) => /paid/i.test(valueOf(english, k) ?? '') && !k.startsWith('learn.paid_'));
    expect(offenders).toEqual([]);
  });
});
