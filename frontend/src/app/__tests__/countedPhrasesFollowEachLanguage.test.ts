// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { existsSync, readFileSync, readdirSync, statSync } from 'node:fs';
import { join, relative, resolve, sep } from 'node:path';

import i18next from 'i18next';
import { describe, expect, it } from 'vitest';

/**
 * A count and the words around it are chosen together, by i18next, from the
 * reader's own language.
 *
 * These phrases used to pick their noun in JavaScript. Some asked
 * `n === 1 ? t('x.item') : t('x.items')`, which hands every language exactly
 * the two shapes English has: Russian then printed "5 позиции" and Polish
 * "5 pozycje", because the language needs a third shape for five and the branch
 * could never reach it. Others built English outright, `${n} night${...'s'}`,
 * and showed it in every language. Each now passes `count` to one key that
 * carries a form per CLDR category of the language, so i18next asks
 * `Intl.PluralRules` and gets "5 позиций", "5 pozycji", and at twenty one the
 * Russian singular again.
 *
 * The check runs a real i18next instance over the real locale files, one
 * language at a time with no English behind it, so a missing form shows up as
 * the raw key instead of quietly borrowing the English sentence.
 */

const RESOLVED = ['src/app/locales', 'frontend/src/app/locales']
  .map((p) => resolve(process.cwd(), p))
  .find(existsSync);
if (!RESOLVED) {
  throw new Error('no locale directory at src/app/locales or frontend/src/app/locales');
}
const LOCALES_DIR = RESOLVED;
const SRC_DIR = resolve(LOCALES_DIR, '..', '..');

function loadLocale(code: string): Record<string, string> {
  const src = readFileSync(resolve(LOCALES_DIR, `${code}.ts`), 'utf8');
  const start = src.indexOf('{', src.indexOf('const resource'));
  const end = src.lastIndexOf('} as ');
  return (new Function(`return ${src.slice(start, end + 1)}`)() as { translation: Record<string, string> })
    .translation;
}

function alone(code: string) {
  const instance = i18next.createInstance();
  void instance.init({
    lng: code,
    fallbackLng: false,
    keySeparator: false,
    nsSeparator: false,
    resources: { [code]: { translation: loadLocale(code) } },
    initAsync: false,
  });
  return instance;
}

/** Every key this change moved from a JavaScript branch to i18next. */
const CONVERTED = [
  'boq.item_count',
  'boq.bim_qty_elements_count',
  'catalog.resources_selected',
  'catalog.component_count',
  'changeorders.impact_boq_ambiguous_count',
  'changeorders.impact_boq_none_count',
  'changeorders.impact_boq_add_count',
  'costs.region_count',
  'costs.variant_option_count',
  'costs.variant_group_total',
  'bim.selection_count',
  'files.permissions.restricted_members',
  'files.share.download_count',
  'accommodation.calendar.nights_count',
  'ai.cad_types_count',
  'erp_chat.search.matches_count',
  'erp_chat.validation.critical_count',
  'erp_chat.validation.error_count',
  'erp_chat.validation.warning_count',
  'erp_chat.validation.info_count',
  'offline.synced_changes',
  'offline.failed_changes',
  'eac.logic_block.conditions_count',
];

/** The two-form keys the branches used to name. None may come back. */
const RETIRED = [
  'boq.item',
  'boq.items',
  'catalog.resource',
  'catalog.selected',
  'catalog.component',
  'catalog.components',
  'changeorders.impact_position',
  'changeorders.impact_positions',
  'changeorders.impact_boq_ambiguous',
  'changeorders.impact_boq_none',
  'changeorders.impact_boq_add',
  'costs.region_singular',
  'costs.region_plural',
  'costs.variant_count_one',
  'costs.variant_count_n',
  'costs.variant_group_count_one',
  'costs.variant_group_count_n',
  'bim.sel_one',
  'bim.sel_n',
  'files.permissions.lock_tooltip',
  'files.permissions.lock_tooltip_plural',
  'files.share.downloads',
  'files.share.downloads_plural',
];

const LOCALE_CODES = readdirSync(LOCALES_DIR)
  .filter((f) => f.endsWith('.ts') && f !== 'index.ts')
  .map((f) => f.slice(0, -3));

// Regional variants resolve through their base language and are left out.
const BASE = LOCALE_CODES.filter((code) => !code.includes('-'));

// Enough numbers to land in every category any of our languages has,
// including Arabic zero and two and the fractional `other` of the Slavic set.
const COUNTS = [0, 1, 2, 3, 5, 11, 21, 22, 100, 1.5];

const ru = alone('ru');
const pl = alone('pl');

function forms(instance: ReturnType<typeof alone>, key: string, counts: number[], extra = {}) {
  return counts.map((count) => instance.t(key, { count, ...extra }));
}

describe('counted phrases follow each language, not the English branch', () => {
  it('Russian takes a third form for five and the singular again at twenty one', () => {
    expect(forms(ru, 'boq.item_count', [1, 2, 5, 21])).toEqual([
      '1 позиция',
      '2 позиции',
      '5 позиций',
      '21 позиция',
    ]);
    expect(forms(ru, 'catalog.resources_selected', [1, 2, 5, 21])).toEqual([
      'Выбран 1 ресурс',
      'Выбрано 2 ресурса',
      'Выбрано 5 ресурсов',
      'Выбран 21 ресурс',
    ]);
    expect(forms(ru, 'accommodation.calendar.nights_count', [1, 2, 5, 21])).toEqual([
      '1 ночь',
      '2 ночи',
      '5 ночей',
      '21 ночь',
    ]);
    expect(forms(ru, 'offline.failed_changes', [1, 2, 5, 21])).toEqual([
      'Не удалось синхронизировать 1 изменение',
      'Не удалось синхронизировать 2 изменения',
      'Не удалось синхронизировать 5 изменений',
      'Не удалось синхронизировать 21 изменение',
    ]);
    // The case the sentence governs, not the nominative: "with N positions".
    expect(forms(ru, 'changeorders.impact_boq_add_count', [1, 2, 5, 21], { boq: 'Доп. работы' })).toEqual([
      'Будет добавлен 1 новый раздел с 1 позицией в Доп. работы.',
      'Будет добавлен 1 новый раздел с 2 позициями в Доп. работы.',
      'Будет добавлен 1 новый раздел с 5 позициями в Доп. работы.',
      'Будет добавлен 1 новый раздел с 21 позицией в Доп. работы.',
    ]);
  });

  it('Polish separates 2-4 from 5 and up, and 21 is not singular', () => {
    expect(forms(pl, 'boq.item_count', [1, 2, 5, 21, 22])).toEqual([
      '1 pozycja',
      '2 pozycje',
      '5 pozycji',
      '21 pozycji',
      '22 pozycje',
    ]);
    expect(forms(pl, 'catalog.resources_selected', [1, 2, 5, 21])).toEqual([
      'Zaznaczono 1 zasób',
      'Zaznaczono 2 zasoby',
      'Zaznaczono 5 zasobów',
      'Zaznaczono 21 zasobów',
    ]);
    expect(forms(pl, 'accommodation.calendar.nights_count', [1, 2, 5, 21])).toEqual([
      '1 noc',
      '2 noce',
      '5 nocy',
      '21 nocy',
    ]);
    expect(forms(pl, 'files.share.download_count', [1, 2, 5, 21])).toEqual([
      '1 pobranie',
      '2 pobrania',
      '5 pobrań',
      '21 pobrań',
    ]);
  });

  it('English keeps singular and plural apart', () => {
    const en = alone('en');
    expect(forms(en, 'boq.item_count', [1, 2])).toEqual(['1 item', '2 items']);
    expect(forms(en, 'accommodation.calendar.nights_count', [1, 3])).toEqual(['1 night', '3 nights']);
    expect(forms(en, 'erp_chat.validation.error_count', [1, 4])).toEqual(['1 error', '4 errors']);
  });

  for (const code of BASE) {
    it(`${code}: every converted key answers every count in the language itself`, () => {
      const instance = alone(code);
      const holes: string[] = [];
      for (const key of CONVERTED) {
        for (const count of COUNTS) {
          const out = instance.t(key, { count, boq: 'B' });
          if (out === key || out.includes('{{')) holes.push(`${key} @ ${count}: ${out}`);
        }
      }
      expect(holes).toEqual([]);
    });
  }

  // Evaluates every locale file, regional variants included: about 13 s on
  // an idle Windows machine and past the default 15 s next to a parallel run.
  it('no locale file still carries a retired two-form key', () => {
    const leftovers: string[] = [];
    for (const code of LOCALE_CODES) {
      const table = loadLocale(code);
      for (const key of RETIRED) if (key in table) leftovers.push(`${code}: ${key}`);
    }
    expect(leftovers).toEqual([]);
  }, 60_000);
});

/**
 * English plural endings glued on in JavaScript: `item${n !== 1 ? 's' : ''}`,
 * `n === 1 ? 'night' : 'nights'`. Each one shows English in every language and
 * the wrong shape in every language with more than two forms.
 */
const GLUED_SUFFIX = /\?\s*'(?:s|es|ren)'\s*:\s*''|\?\s*''\s*:\s*'(?:s|es|ren)'/;
const WORD_PAIR = /===\s*1\s*\?\s*'([a-z][a-z ]*)'\s*:\s*'\1(?:s|es)'/;

/**
 * Known debt, each with the reason it is not a one-key fix. The whole summary
 * line in the clash group action dialog is assembled in English ("12 clashes
 * -> punch item, high priority, 82% confidence"), so translating the noun alone
 * would leave a sentence that is still English around it.
 */
const KNOWN = new Set(['features/clash/clashGroupAction.ts']);

function walk(dir: string, out: string[] = []): string[] {
  for (const entry of readdirSync(dir)) {
    if (entry === 'node_modules' || entry === 'dist' || entry === 'locales') continue;
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) {
      walk(full, out);
      continue;
    }
    if (!/\.tsx?$/.test(entry) || /\.(test|spec|stories)\.tsx?$/.test(entry) || entry.endsWith('.d.ts')) continue;
    out.push(full);
  }
  return out;
}

describe('no English plural ending is glued on in JavaScript', () => {
  const files = walk(SRC_DIR);

  it('scanned the source tree, so an empty verdict means something', () => {
    expect(files.length).toBeGreaterThan(500);
  });

  it('the patterns still recognise the shapes they exist to catch', () => {
    expect(GLUED_SUFFIX.test("({n} element{n !== 1 ? 's' : ''})")).toBe(true);
    expect(GLUED_SUFFIX.test("`${n} child${n === 1 ? '' : 'ren'}`")).toBe(true);
    expect(WORD_PAIR.test("nights === 1 ? 'night' : 'nights'")).toBe(true);
    expect(WORD_PAIR.test("phase === 1 ? 'a' : 'b'")).toBe(false);
  });

  it('finds none outside the recorded debt', () => {
    const found: string[] = [];
    for (const file of files) {
      const rel = relative(SRC_DIR, file).split(sep).join('/');
      if (KNOWN.has(rel)) continue;
      const lines = readFileSync(file, 'utf8').split('\n');
      lines.forEach((line, i) => {
        if (GLUED_SUFFIX.test(line) || WORD_PAIR.test(line)) found.push(`${rel}:${i + 1}  ${line.trim()}`);
      });
    }
    expect(found).toEqual([]);
  });
});
