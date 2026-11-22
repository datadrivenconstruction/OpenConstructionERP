import { existsSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';

import i18next from 'i18next';
import { describe, expect, it } from 'vitest';

/**
 * Uzbek (uz) is a new locale, built batch by batch rather than all at once:
 * `scripts/i18n_new_locale.py` extracts the full key set, and each batch is
 * hand-translated and assembled back into `uz.ts` as it is finished. Most
 * keys still carry their English source as an interim value while the rest
 * of the corpus is translated - that is expected and not a bug in itself,
 * `check_i18n_leak_baseline.py` tracks it separately. What this file checks
 * is narrower and permanent: the keys that ARE translated actually resolve
 * to Uzbek through the bundle the app builds, not just as text in the file.
 *
 * See `localeKeyResolution.test.ts` for why the file is read as source and
 * evaluated rather than imported (a 3MB object literal times out the vitest
 * transform pipeline) and for the module-nesting bug this pattern also
 * catches: a key written as a sibling of `translation` looks present in the
 * file and is invisible to i18next, which only ever sees `translation`.
 */

/** The object a locale file exports, read the way `i18n.ts` consumes it. */
function loadLocale(code: string): { translation: Record<string, string> } {
  const candidates = [
    resolve(process.cwd(), 'src/app/locales', `${code}.ts`),
    resolve(process.cwd(), 'frontend/src/app/locales', `${code}.ts`),
  ];
  const path = candidates.find(existsSync);
  if (!path) throw new Error(`cannot find ${code}.ts, looked in ${candidates.join(' and ')}`);
  const src = readFileSync(path, 'utf8');
  const start = src.indexOf('{', src.indexOf('const resource'));
  const end = src.lastIndexOf('} as ');
  return new Function(`return ${src.slice(start, end + 1)}`)();
}

/** A bundle built exactly as i18n.ts builds one. */
function bundleFor(code: string, resource: { translation: Record<string, string> }) {
  const instance = i18next.createInstance();
  void instance.init({ lng: code, resources: {}, initAsync: false });
  instance.addResourceBundle(code, 'translation', resource.translation, false, true);
  return instance;
}

/**
 * One key per hand-translated batch (batch_000, batch_001, batch_021, and
 * the delta rounds that caught keys other agents added mid-translation),
 * with the English every call site passes as a defaultValue. A key that
 * fails to resolve falls back to exactly this string, so comparing against
 * it is the same question the screen asks.
 */
const TRANSLATED: Array<[string, string]> = [
  ['modules.catalog.accommodation', 'Accommodation'],
  ['fx.source_unknown', 'unknown source'],
  [
    'formwork.subtitle',
    'Price the moulds concrete is cast into, amortised over the reuses the programme actually delivers',
  ],
  ['teams.member_count', 'Members: {{count}}'],
  ['deadlines.insights.f_owner', 'Owner'],
  ['boq.create_revision', 'Create Revision'],
  ['boq.lock_tooltip', 'Lock prevents edits. Create a revision to make changes to a locked estimate.'],
  ['modules.dev_db_title', 'Database migrations'],
  ['defects_liability.limitation_ends_on', 'Ends'],
  ['field_time.working_time.title', 'Statutory working-time record'],
  ['price_breakdown.line.unit_rate', 'Unit rate'],
  ['onboarding.semantic_model_ready', 'Installed'],
  ['tendering.award_record.record_button', 'Record'],
  ['cases.hive.title', 'Modules this case walks through'],
  // batch_043 / batch_023 / batch_016 (later session)
  ['crm.close_deal', 'Close the deal'],
  ['cvr.cashflow', 'Cashflow forecast'],
  ['clash.matrix_title', 'Clash matrix, discipline x discipline'],
  ['schedule.wbs_code', 'WBS Code'],
  // batch_050 / batch_057 / batch_018 (this session)
  ['propdev.escrow.balance', 'Balance'],
  ['propdev.broker.commission', 'Commission %'],
  ['progress.record_open', 'Record progress'],
  ['contracts.eot_title', 'Extension of time'],
  ['fieldreports.work_performed', 'Work Performed'],
  ['risk.title', 'Risk Analysis (Monte Carlo)'],
];

/** Both CLDR categories `Intl.PluralRules('uz')` reports (one, other). */
const PLURAL_FAMILY: Array<[string, string]> = [
  ['field_time.working_time.excluded_one', '{{count}} corrected timesheet is left out so the same hours are not counted twice.'],
  ['field_time.working_time.excluded_other', '{{count}} corrected timesheets are left out so the same hours are not counted twice.'],
];

describe('uz keeps every key inside translation, with nothing beside it', () => {
  it('resource has exactly one top-level member', () => {
    const resource = loadLocale('uz');
    expect(Object.keys(resource)).toEqual(['translation']);
  });

  it('translation carries the full extracted key set, not a partial one', () => {
    const resource = loadLocale('uz');
    // The corpus grows as other agents add UI strings (each caught by
    // `i18n_new_locale.py delta uz` before assemble) and shrinks only if a
    // feature is removed, so this is a floor rather than an exact count.
    expect(Object.keys(resource.translation).length).toBeGreaterThan(37000);
  });
});

describe('uz resolves its hand-translated keys to Uzbek, not the English default', () => {
  it('every hand-translated batch resolves through the bundle the app builds', () => {
    const instance = bundleFor('uz', loadLocale('uz'));
    for (const [key, english] of TRANSLATED) {
      const value = instance.t(key, { defaultValue: english });
      expect(value, `uz fell back to English for ${key}`).not.toBe(english);
      expect(value.length).toBeGreaterThan(0);
    }
  });

  it('resolves both plural categories uz actually has (one, other)', () => {
    const instance = bundleFor('uz', loadLocale('uz'));
    for (const [key, english] of PLURAL_FAMILY) {
      const value = instance.t(key, { defaultValue: english, count: 1 });
      expect(value, `uz fell back to English for ${key}`).not.toBe(english);
    }
  });
});

/**
 * Uzbek Latin orthography is picky about a single character. The digraph
 * mark (`oʻ`, `gʻ`, U+02BB MODIFIER LETTER TURNED COMMA) and the tutuq
 * belgisi glottal stop in loanwords (`maʼlumot`, U+02BC MODIFIER LETTER
 * APOSTROPHE) are not the same as a plain ASCII apostrophe. A straight
 * quote in an actually-translated value is a typing slip - but most of the
 * corpus is still an untranslated English interim value while the rest of
 * the batches are worked through, and English prose ("doesn't", "founder's
 * note") legitimately carries straight apostrophes, and the odd example
 * value legitimately carries Cyrillic as literal data (a Russian sample
 * label inside a placeholder string, not a translation of the key itself).
 * Comparing against the English source, the same way
 * `check_i18n_leak_baseline.py` does, is what tells apart "not translated
 * yet" from "translated and wrong".
 *
 * One further exception on the apostrophe check: a digit immediately
 * before the mark is never Uzbek grammar, it is the feet/inches prime
 * notation a US-market drawing example writes as `12'-6 3/4"` - en.ts uses
 * the same plain apostrophe there. The exception is the `(?<!\d)` in the
 * `nonDimensionApostrophe` pattern in the first test below, and that pattern
 * is the only place the rule lives. This paragraph used to send the reader to
 * a script named `fix_uz_apostrophes.py` carrying the identical digit guard.
 * No such file is tracked in this repository - `git ls-files | grep -i fix_uz`
 * returns nothing - because the sweep that converted `uz.ts` to U+02BB ran as
 * a one-off that was never committed. A citation to a file a reader cannot
 * open is worse than no citation: it names an authority for the rule that
 * does not exist, and the regex below is the whole of it.
 */
/**
 * Keys whose Uzbek value still carries Cyrillic that did NOT travel with it
 * from the English source.
 *
 * "Translated" alone is too coarse a filter here. Some English values name a
 * localised column header by example (`Beschreibung, Описание, 描述`), and a
 * correct Uzbek translation of such a key keeps those samples verbatim,
 * because they are the strings the user will actually see in a spreadsheet.
 * Comparing whole values misses that: the value differs from English AND its
 * Cyrillic is legitimate. So each Cyrillic run is judged on its own - a run
 * that also appears in the English source is carried data, and only a run
 * that appears nowhere in it is a leftover of the old Cyrillic orthography.
 */
function cyrillicOffenders(
  uzbek: Record<string, string>,
  english: Record<string, string>,
): string[] {
  const cyrillicRun = /[Ѐ-ӿ]+/g;
  return Object.entries(uzbek)
    .filter(([key, value]) => {
      if (value === english[key]) return false;
      const source = english[key] ?? '';
      return (value.match(cyrillicRun) ?? []).some((run) => !source.includes(run));
    })
    .map(([key]) => key);
}

describe('uz stays in Latin script with the correct apostrophe marks', () => {
  it('carries no plain ASCII apostrophe in any actually-translated value, outside imperial dimension notation', () => {
    const resource = loadLocale('uz');
    const english = loadLocale('en').translation;
    const nonDimensionApostrophe = /(?<!\d)'/;
    const offenders = Object.entries(resource.translation).filter(
      ([key, value]) => value !== english[key] && nonDimensionApostrophe.test(value),
    );
    expect(offenders.map(([key]) => key)).toEqual([]);
  });

  it('carries no Cyrillic character in any actually-translated value', () => {
    const resource = loadLocale('uz');
    const english = loadLocale('en').translation;
    expect(cyrillicOffenders(resource.translation, english)).toEqual([]);
  });

  it('the Cyrillic check still catches a leftover, and still spares carried data', () => {
    const english = {
      carried: 'Upload an .xlsx with a "Description" column (or Beschreibung, Описание, 描述).',
      leftover: 'Save',
    };
    const uzbek = {
      // Translated, and the Russian sample column name travels with it because
      // the key's job is to list what the header may be called on disk.
      carried: 'Kamida "Description" ustuni (yoki Beschreibung, Описание, 描述) boʻlgan .xlsx yuklang.',
      // Translated into the old Cyrillic orthography, which is the leftover
      // this check exists to find.
      leftover: 'Сақлаш',
    };
    expect(cyrillicOffenders(uzbek, english)).toEqual(['leftover']);
  });
});

/**
 * `Intl.PluralRules('uz').resolvedOptions().pluralCategories` is exactly
 * `['one', 'other']`. i18next does not fall back between plural forms of
 * the same language - a missing `_one` key falls straight through to the
 * English default, so the two categories this runtime actually asks for
 * are the only ones worth asserting against.
 */
describe('uz plural categories match what the runtime actually resolves', () => {
  it('Intl.PluralRules agrees with the categories this file is translated for', () => {
    const categories = new Intl.PluralRules('uz').resolvedOptions().pluralCategories;
    expect(categories.slice().sort()).toEqual(['one', 'other']);
  });
});
