// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * #200 — nine keys whose value was assembled by a JS template literal before
 * i18next ever saw it.
 *
 * `t('gaeb.import_btn', { defaultValue: `Import ${n} positions` })` hands
 * i18next one finished English sentence. There is no variable for a translator
 * to move, so no locale file can put the number where its own grammar puts it,
 * and a language that inflects the noun after a numeral cannot be written at
 * all. The count has to arrive as an interpolation variable and the default has
 * to keep a literal `{{count}}` for the locale files to mirror.
 *
 * This is asserted against the OPTIONS OBJECT, not against rendered output.
 * Rendering cannot tell the two apart: "Import 5 positions" is what you get
 * whether the 5 was substituted by i18next or baked in by the template literal
 * before the call. The source is the only place the difference is visible.
 *
 * Scoped to the four files #200 covers. A tree-wide version is not possible
 * yet — 23 further call sites across 14 other files still build a defaultValue
 * from a template literal, and they need the same treatment before this can be
 * turned on everywhere.
 */
import { readdirSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, it, expect } from 'vitest';

const SRC = resolve(__dirname, '..', '..');

/** Source between the options `{` of a t() call and its matching `}`. */
function optionsBody(text: string, braceIndex: number): string {
  let depth = 0;
  for (let i = braceIndex; i < text.length; i += 1) {
    if (text[i] === '{') depth += 1;
    else if (text[i] === '}') {
      depth -= 1;
      if (depth === 0) return text.slice(braceIndex + 1, i);
    }
  }
  throw new Error(`unbalanced options object at ${braceIndex}`);
}

/** The options object of the first `t('<key>', { ... })` call in `text`. */
function callOptions(text: string, key: string): string {
  const head = new RegExp(`\\bt\\(\\s*['"]${key.replace(/\./g, '\\.')}['"]\\s*,\\s*\\{`);
  const match = head.exec(text);
  if (!match) throw new Error(`no t() call site for ${key}`);
  return optionsBody(text, match.index + match[0].length - 1);
}

const FILES = {
  assemblies: 'features/assemblies/AssembliesPage.tsx',
  gaeb: 'modules/gaeb-exchange/GAEBExchangeModule.tsx',
  setup: 'features/setup/DatabaseSetupPage.tsx',
  portfolio: 'features/portfolio/PortfolioPage.tsx',
} as const;

const source = Object.fromEntries(
  Object.entries(FILES).map(([name, rel]) => [name, readFileSync(resolve(SRC, rel), 'utf8')]),
) as Record<keyof typeof FILES, string>;

/** key, owning file, variables the call must pass, placeholders the default must keep. */
const CASES: Array<[string, keyof typeof FILES, string[], string[]]> = [
  ['assemblies.bulk_deleted', 'assemblies', ['count'], ['{{count}}']],
  ['assemblies.bulk_deleted_partial', 'assemblies', ['ok', 'failed'], ['{{ok}}', '{{failed}}']],
  ['assemblies.bulk_tagged', 'assemblies', ['count'], ['{{count}}']],
  ['assemblies.bulk_tagged_partial', 'assemblies', ['ok', 'failed'], ['{{ok}}', '{{failed}}']],
  ['assemblies.bulk_exported', 'assemblies', ['count'], ['{{count}}']],
  ['gaeb.show_all', 'gaeb', ['count'], ['{{count}}']],
  ['gaeb.import_btn', 'gaeb', ['count'], ['{{count}}']],
  ['gaeb.export_btn', 'gaeb', ['format'], ['{{format}}']],
  ['setup.db_already_loaded', 'setup', ['name'], ['{{name}}']],
  ['setup.db_loaded', 'setup', ['name'], ['{{name}}']],
];

describe('#200 counted and named keys reach i18next as variables', () => {
  for (const [key, file, vars, placeholders] of CASES) {
    it(`${key} passes ${vars.join(', ')} and keeps the placeholder in its default`, () => {
      const options = callOptions(source[file], key);

      // The defect itself: a template literal splices the value in before the
      // call, so the options object carries a `${...}` and no variable at all.
      expect(options, key).not.toContain('${');

      for (const name of vars) {
        // `ok,` and `ok: ok` are the same thing to i18next, so accept both
        // shorthand and explicit rather than pinning one house style.
        expect(options, `${key} must pass ${name}`).toMatch(new RegExp(`\\b${name}\\s*[,:]`));
      }
      for (const placeholder of placeholders) {
        expect(options, `${key} default must keep ${placeholder}`).toContain(placeholder);
      }
    });
  }

  it('gives the counted keys a default the plural forms can be written against', () => {
    // A counted key resolves through its CLDR category, so `{{count}}` has to
    // survive into the default that locale files mirror. English needs a second
    // form only where the noun changes, which here is the positions button.
    const importBtn = callOptions(source.gaeb, 'gaeb.import_btn');
    expect(importBtn).toContain('defaultValue_other');
    expect(importBtn).toContain('Import {{count}} position');
  });
});

/**
 * The other half of #200. Passing `count` to i18next is only useful if the
 * locale file has a form for the category i18next then asks for. Three of these
 * keys shipped to tr, ky and mn with `_other` alone, and at n=1 those users read
 * the English default instead: i18next does NOT fall back to `_other` in the
 * same language, it walks the fallback chain out of the language entirely.
 *
 * Completeness is counted per language, never by comparing locales to each
 * other. ja, ko, th, vi and zh have `other` as their only CLDR category, so a
 * missing `_one` there is the correct answer rather than a gap, and any check
 * that diffs the locale files against a richer one flags all five forever.
 */
const LOCALES = resolve(SRC, 'app', 'locales');

/** The six counted keys #200 touched, not a census. #208 is the tree-wide version. */
const COUNTED_KEYS = [
  'assemblies.bulk_deleted',
  'assemblies.bulk_tagged',
  'assemblies.bulk_exported',
  'assemblies.selected_count',
  'gaeb.show_all',
  'gaeb.import_btn',
];

/** Every locale the app ships, taken from the directory rather than a list. */
const localeFiles = readdirSync(LOCALES)
  .filter((name) => name.endsWith('.ts') && name !== 'index.ts')
  .map((name) => [name.slice(0, -3), readFileSync(resolve(LOCALES, name), 'utf8')] as const);

/**
 * The registry the app actually ships, read out of the source. Importing
 * `app/i18n` boots i18next with the whole English resource and the worker never
 * returns, so only the literal is parsed - the same approach CountryFlag.test
 * takes, and for the same reason.
 */
const declaredCodes = [
  ...readFileSync(resolve(SRC, 'app', 'i18n.ts'), 'utf8').matchAll(/\{\s*code:\s*'([^']+)'/g),
].map(([, code]) => code);

describe('#200 counted keys carry every plural form their own language uses', () => {
  it('reads every locale file the app declares', () => {
    // A glob that quietly matches nothing would make every assertion below pass,
    // so the count has to be asserted - but against the registry rather than
    // against a number typed here. A literal goes stale the day a locale is
    // added: this read 29 while the app shipped 37, and the eight new files
    // were being checked by every assertion below while this one line called
    // them absent.
    expect(declaredCodes.length).toBeGreaterThan(25);
    // Mongolian is on disk but deliberately not in SUPPORTED_LANGUAGES: five
    // invented roots passed every gate, so the language is withheld until the
    // file is retranslated. The file stays covered by every assertion below;
    // only the registry comparison must expect its absence.
    //
    // Hungarian joined it on 2026-09-04: `extract` seeds every batch with the
    // English source text as a placeholder, and `assemble`'s own checks (key
    // present, no cross-batch duplicate) cannot tell a translated batch from
    // one where that placeholder was never replaced. As of the date above,
    // 30,746 of the file's 41,903 values are still byte-identical to their
    // English source - measured by direct comparison, not estimated. `hu.ts`
    // stays covered by every assertion below, including the plural-form loop;
    // only the registry comparison must expect its absence, same as mn.
    const undeclaredOnPurpose = ['mn', 'hu'];
    expect([...localeFiles.map(([code]) => code)].filter((code) => !undeclaredOnPurpose.includes(code)).sort())
      .toEqual([...declaredCodes].sort());
  });

  it('gets the plural categories it expects out of this runtime', () => {
    // The expected set is computed by the same ICU the assertions run against,
    // so a runtime with older CLDR data would drop categories from BOTH sides
    // and the loop below would pass while checking less. `many` for es, es-MX,
    // fr, it and pt is the recent addition and the one at risk: on an older ICU
    // those five resolve to one/other and the 25 forms just written stop being
    // checked at all. Pin the shape so that shift is loud.
    const withMany = localeFiles
      .map(([locale]) => locale)
      .filter((locale) => new Intl.PluralRules(locale).resolvedOptions().pluralCategories.includes('many'));
    expect(withMany).toContain('es');
    expect(withMany).toContain('fr');

    // `id` belongs here on its own merits and was missed when this list was
    // first written: Indonesian marks number lexically rather than on the noun,
    // so CLDR gives it `other` alone, exactly as it does for the CJK languages
    // beside it. Leaving it out made this assertion fail from the day it was
    // written, and nothing reported that, because no frontend test ran in a
    // blocking lane until 14.4.0.
    const otherOnly = localeFiles
      .map(([locale]) => locale)
      .filter((locale) => new Intl.PluralRules(locale).resolvedOptions().pluralCategories.length === 1);
    expect(otherOnly.sort()).toEqual(['id', 'ja', 'ko', 'th', 'vi', 'zh']);
  });

  for (const [locale, text] of localeFiles) {
    const categories = new Intl.PluralRules(locale).resolvedOptions().pluralCategories;
    // A regional code may leave a form to its own base language. i18next
    // resolves `en-US` through ['en-US', 'en'], and `en-US.ts` is deliberately
    // an overlay of the words American English says differently rather than a
    // locale in its own right, so requiring every plural form of it asks it to
    // stop being an overlay. The failure this checks for is a counted key with
    // no form the reader's own language uses, and the base language answers in
    // that same language; falling back ACROSS languages is a different defect
    // and other suites catch it.
    const dash = locale.indexOf('-');
    const base = dash > 0 ? locale.slice(0, dash) : null;
    const inherited = base ? (localeFiles.find(([code]) => code === base)?.[1] ?? '') : '';

    it(`${locale} has ${categories.join(', ')} for each counted key`, () => {
      for (const key of COUNTED_KEYS) {
        for (const category of categories) {
          const form = `"${key}_${category}"`;
          const carried = text.includes(form) || inherited.includes(form);
          expect(carried, `${locale} is missing ${form}`).toBe(true);
        }
      }
    });
  }
});

describe('#200 the blank actions column got a real name', () => {
  it('no longer calls portfolio.xl_actions anywhere', () => {
    // The old key was a single space: a column heading that says nothing, which
    // is an accessibility gap rather than a styling choice.
    for (const text of Object.values(source)) {
      expect(text).not.toContain('portfolio.xl_actions');
    }
  });

  it('names the column and hides it visually', () => {
    const options = callOptions(source.portfolio, 'portfolio.col_actions');
    expect(options).toContain('Actions');
    // The name is only an improvement if it stays out of the visual table head.
    const at = source.portfolio.indexOf("t('portfolio.col_actions'");
    expect(source.portfolio.slice(Math.max(0, at - 200), at)).toContain('sr-only');
  });
});
