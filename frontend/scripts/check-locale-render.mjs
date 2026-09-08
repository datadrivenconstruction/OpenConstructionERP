/**
 * Ask real i18next what a non-English reader actually sees, using the shipped
 * dictionaries rather than a fixture.
 *
 * Why this exists. Principle 2 of this project is "i18n everywhere, zero
 * hardcoded strings" and it is nominally a blocker. Two measurements showed it
 * was gated by nothing at all. In the first, 30,964 `t()` calls across 912
 * files were rewritten into bare literals and the whole suite stayed 91 of 91
 * green, because the harness mock in src/test/setup.ts returns `defaultValue`
 * verbatim and roughly 95 percent of call sites pass one, so the rendered DOM
 * is byte identical whether translation works or not. In the second, every one
 * of the 38,895 German values was corrupted with placeholders preserved and
 * exactly one assertion turned red, in a file nothing runs before merge.
 *
 * The two tests that do raise real i18next, both `i18nStartupLocaleGate` files,
 * deliberately substitute a three key fixture for the dictionary, with a
 * reasoned comment saying so: a 3 MB object literal through the vitest
 * transform stalls the worker. That reasoning is sound for what those tests
 * assert, which is boot ordering. It also means the shipped dictionary is never
 * on the other end of a real `t()` call anywhere in this repo. Formatting is
 * gated, three guards raise real i18next and do pin locale dependent number and
 * date formatting. Translation is not.
 *
 * So this guard does not bring its own idea of what a translation should say.
 * It builds a real i18next instance with the application's own init options,
 * hands it every bundle under src/app/locales, and asks it to render. What it
 * asserts is a property of the answer, never a judgement of the wording:
 *
 *   1. A locale that is offered may not render blank where English renders
 *      text. That is not a quality opinion, it is a reader looking at nothing.
 *
 *   2. A locale that is offered may not come back mostly English. Measured
 *      here, not guessed: see ENGLISH_RENDER_CEILING.
 *
 * Deliberately NOT a translation quality check. Comparing each value against
 * English and judging it would fire on every string that is identical on
 * purpose, and there are thousands of those - "OK", "Email", "BOQ", unit codes,
 * proper nouns, format names. A guard with a large false positive population is
 * suppressed inside a week, and it is worse than no guard because it also looks
 * like coverage. Per string English leaks are already
 * scripts/check_i18n_leak_baseline.py's job, which finds them by uniformity
 * across locales. That fingerprint is blind by construction to one locale going
 * English on its own, which is the case measured above and the case here.
 *
 * What this guard does not cover, stated so nobody builds on more than it
 * gives. It reads dictionaries, so the first measurement is outside it: 30,964
 * `t()` calls rewritten to literals never touches a locale file, and that
 * failure lives at the call site and in the harness mock. It also cannot tell
 * German from non-English nonsense, so a value corrupted into gibberish that is
 * not English still passes. It closes missing translation and English
 * passthrough in the shipped dictionary, and nothing wider.
 *
 * Counting. Nothing here is a written down list of keys or locales. The keys
 * are whatever en.ts declares, the locales are whatever the directory holds
 * intersected with SUPPORTED_LANGUAGES in src/app/i18n.ts, and a regional
 * variant's base is derived from its own code. A number in a comment is a claim
 * nobody re-checks, and this repo has already paid for mirrored lists twice:
 * src/app/i18n-fallbacks.ts is maintained by hand and Kyrgyz, Greek and
 * Ukrainian each shipped invisible to every test that iterates it.
 *
 * Overlays. es-MX, es-CL, es-CO, pt-BR, en-GB and en-US carry only the words that
 * differ from their base, so a key absent from one of them is not missing, it
 * is inherited. This guard never has to encode that rule, because it asks
 * i18next, and i18next expands a two part code into ['es-MX', 'es', 'en'] on
 * its own. Counting an overlay's absent keys as holes once printed 25,280
 * errors against a 1,499 key file. CONTROL B below proves the chain is live
 * rather than assuming it.
 *
 * Placeholders. Text inside {{ }} is code, not prose, and is never treated as
 * translatable content here. It is not touched at all: values are compared and
 * measured whole, and placeholder contracts are
 * scripts/check_i18n_placeholder_parity.py's job.
 *
 * Reading the dictionary. This does not bring its own parser either. It asks
 * the TypeScript compiler, the same reader whose opinion decides whether the
 * application builds, and takes the decoded text of each string literal, which
 * is the byte sequence i18next would receive. A locale file that does not parse,
 * or that holds anything other than plain string properties, is a refusal and
 * not a pass: a reader that silently drops entries would report a green result
 * over missing data.
 *
 * Run:
 *   node scripts/check-locale-render.mjs                 # the shipped tree
 *   node scripts/check-locale-render.mjs --selftest      # prove it can fail
 *   node scripts/check-locale-render.mjs <locale-dir>    # aim it elsewhere
 *
 * Exit 0 clean, 1 a finding, 2 the run itself is not trustworthy.
 */

import { readFileSync, readdirSync, existsSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import ts from 'typescript';
import i18next from 'i18next';

const here = dirname(fileURLToPath(import.meta.url));

// The share of en.ts a locale may render in English before this fails.
//
// Measured on the committed tree on 2026-08-26, over all 35,411 keys en.ts
// declares, resolved through real i18next with the application's fallback
// chain, so a key the locale does not answer counts as English because that is
// literally what the reader gets. The 39 offered non-English locales spanned
// 1.76 percent (uk) to 6.00 percent (nl), a band of about three to one, with
// the median near 3.3.
//
// The ceiling sits at 15 rather than just above 6 on purpose. This is a
// wholesale failure detector: a locale shipped as a copy of en.ts scores 100,
// a locale reverted or never translated scores near it, and Mongolian and Uzbek
// are both on disk today in states like that. Per string drift is a different
// question with a different guard, and setting this near the observed maximum
// would turn an ordinary wave of new English keys landing ahead of translation
// into a red gate, which is how a guard gets switched off. A locale has to more
// than double its English content to trip this.
//
// Tighten it against a fresh measurement, never against a guess. The table is
// printed on every run precisely so the evidence to tighten it is always to
// hand.
const ENGLISH_RENDER_CEILING = 0.15;

const DEFAULT_LOCALE_DIR = join(here, '..', 'src', 'app', 'locales');
const I18N_TS = join(here, '..', 'src', 'app', 'i18n.ts');
const BASELINE_PATH = join(here, 'locale-render-baseline.json');

/** Refuse rather than report a green result over a run that proves nothing. */
function refuse(message) {
  console.error(`REFUSING: ${message}`);
  process.exit(2);
}

// ---------------------------------------------------------------------------
// Reading the inputs
// ---------------------------------------------------------------------------

/**
 * Every `"key": "value"` pair the locale's translation object declares, with
 * values decoded by the compiler exactly as the bundler would decode them.
 */
function readLocale(path) {
  const text = readFileSync(path, 'utf8');
  const sf = ts.createSourceFile(path, text, ts.ScriptTarget.ESNext, true, ts.ScriptKind.TS);
  const diagnostics = sf.parseDiagnostics ?? [];
  if (diagnostics.length > 0) {
    // scripts/check-locales-parse.mjs is the guard that reports this properly
    // and it runs first in the same job. Reaching it here means that one did
    // not run, so this is a refusal and not a finding.
    throw new Error('does not parse');
  }

  let found = null;
  const walk = (node) => {
    if (found) return;
    const isTranslationProp =
      ts.isPropertyAssignment(node) &&
      (ts.isStringLiteral(node.name) || ts.isIdentifier(node.name)) &&
      node.name.text === 'translation' &&
      ts.isObjectLiteralExpression(node.initializer);
    if (isTranslationProp) {
      const dict = Object.create(null);
      for (const prop of node.initializer.properties) {
        if (!ts.isPropertyAssignment(prop)) {
          throw new Error('translation object holds something other than a plain property');
        }
        const name = prop.name;
        if (!ts.isStringLiteral(name) && !ts.isIdentifier(name)) {
          throw new Error('translation object holds a computed key');
        }
        const value = prop.initializer;
        if (!ts.isStringLiteral(value) && !ts.isNoSubstitutionTemplateLiteral(value)) {
          throw new Error(`value for "${name.text}" is not a plain string`);
        }
        dict[name.text] = value.text;
      }
      found = dict;
      return;
    }
    ts.forEachChild(node, walk);
  };
  walk(sf);
  if (!found) throw new Error('declares no translation object');
  return found;
}

/**
 * The locale codes the language picker actually offers.
 *
 * Each line is cut at its first `//` before matching, because a locale can
 * leave the list two ways and both have to read as absent: mn's entry was
 * deleted, uz's was commented out in place and the literal text `code: 'uz'`
 * is still sitting in the file. This is the same rule
 * scripts/check_i18n_orphan_keys.py applies, for the same reason.
 */
function readSupportedLanguages(path) {
  const text = readFileSync(path, 'utf8');
  const start = text.indexOf('SUPPORTED_LANGUAGES');
  const end = start >= 0 ? text.indexOf('\n];', start) : -1;
  if (end < 0) return [];
  const active = text
    .slice(start, end)
    .split('\n')
    .map((line) => line.split('//')[0])
    .join('\n');
  return [...active.matchAll(/code:\s*'([A-Za-z0-9-]+)'/g)].map((m) => m[1]);
}

/**
 * The language file a regional variant resolves through, if there is one.
 *
 * Derived from the code rather than mirrored from the fallbackLng map in
 * i18n.ts, because i18next expands a two part code before it ever consults
 * that map, and because a mirrored table is a second copy of a decision and
 * the copy is the one that goes stale.
 */
function baseOf(code, present) {
  if (!code.includes('-')) return null;
  const base = code.split('-')[0];
  return present.has(base) ? base : null;
}

// ---------------------------------------------------------------------------
// The analysis, shared by the real run and the self test
// ---------------------------------------------------------------------------

/**
 * Build a real i18next instance over `dicts` and report what each offered
 * locale renders. `dicts` maps a locale code to its flat translation object.
 */
async function analyse(dicts, supported) {
  const present = new Set(Object.keys(dicts));
  if (!present.has('en')) refuse('there is no en bundle, so there is no source of keys');

  const instance = i18next.createInstance();
  await instance.init({
    // The application's own options. keySeparator and nsSeparator are off
    // because every key is a flat string with literal dots; leaving them on
    // makes i18next walk a nested path that does not exist and answer nothing,
    // which would make this guard report the entire tree as broken.
    initAsync: false,
    lng: 'en',
    fallbackLng: 'en',
    keySeparator: false,
    nsSeparator: false,
    interpolation: { escapeValue: false },
    resources: Object.fromEntries(
      Object.entries(dicts).map(([code, dict]) => [code, { translation: dict }]),
    ),
  });

  const enKeys = Object.keys(dicts.en);
  if (enKeys.length === 0) refuse('the en bundle parsed to no keys');
  const renderEn = instance.getFixedT('en');
  const english = new Map(enKeys.map((k) => [k, renderEn(k)]));

  // English and its own overlays render English by design, so they are not
  // asked to render anything else. Derived, not listed: anything whose base is
  // en belongs here the day it is added.
  const englishFamily = new Set(['en', ...[...present].filter((c) => baseOf(c, present) === 'en')]);

  const offered = supported.filter((code) => present.has(code));
  const rows = [];
  const blanks = [];
  for (const code of offered) {
    const render = instance.getFixedT(code);
    let rendersEnglish = 0;
    let blank = 0;
    for (const key of enKeys) {
      const value = render(key);
      // A blank cell is counted as blank and not also weighed as English. The
      // denominator stays the whole of en.ts either way, so a locale's English
      // share is very slightly understated by however many cells are blank.
      // That is 8 at the most today and it only matters if a locale went blank
      // at scale, which the blank finding says loudly and first.
      if (typeof value === 'string' && value.trim() === '' && english.get(key).trim() !== '') {
        blank += 1;
        blanks.push({ key, locale: code });
        continue;
      }
      if (value === english.get(key)) rendersEnglish += 1;
    }
    rows.push({
      code,
      base: baseOf(code, present),
      englishFamily: englishFamily.has(code),
      rendersEnglish,
      blank,
      share: rendersEnglish / enKeys.length,
    });
  }
  return { instance, enKeys, english, rows, blanks, offered, englishFamily, present };
}

/**
 * Prove the chain is live before trusting a single count.
 *
 * Everything above rests on i18next resolving through the fallback chain the
 * application configures. If it were not, a key answered by English would look
 * like a key answered by German and every "renders its own language" result
 * would be English reported as German: a correct looking number produced by the
 * wrong mechanism. So the chain is measured, on this tree, every run.
 */
function controls({ instance, dicts, present, offered, englishFamily }) {
  const enKeys = Object.keys(dicts.en);
  const failures = [];

  // Both controls take the FIRST candidate that can actually be measured,
  // rather than the first candidate and then complaining if it happens not to
  // offer one. A locale that has been filled in until it declares every key en
  // declares is ordinary, finished work, and it must not turn the lane red for
  // being finished. The controls only speak up when no locale on the tree can
  // answer, which really is a run that proves nothing.

  // CONTROL A: a key only en declares must render English under a plain locale.
  let measuredA = false;
  for (const code of offered) {
    if (englishFamily.has(code) || baseOf(code, present)) continue;
    const owned = new Set(Object.keys(dicts[code]));
    const enOnly = enKeys.find((k) => !owned.has(k) && dicts.en[k].trim() !== '');
    if (!enOnly) continue;
    measuredA = true;
    const got = instance.getFixedT(code)(enOnly);
    if (got !== dicts.en[enOnly]) {
      failures.push(
        `CONTROL A: "${enOnly}" is in en and not in ${code}, so ${code} must render the English ` +
          `value. It rendered ${JSON.stringify(got)}. The English fallback is not wired, so ` +
          `every count in this run is measuring something other than what it says.`,
      );
    }
    break;
  }

  // CONTROL B: an overlay must inherit from its base, not from English. This is
  // the rule that, got wrong, reports thousands of gaps that are not gaps.
  let overlays = 0;
  let measuredB = false;
  for (const code of offered) {
    const b = baseOf(code, present);
    if (!b || b === 'en') continue;
    overlays += 1;
    const owned = new Set(Object.keys(dicts[code]));
    const baseOnly = Object.keys(dicts[b]).find(
      (k) => !owned.has(k) && dicts[b][k] !== dicts.en[k] && dicts[b][k].trim() !== '',
    );
    if (!baseOnly) continue;
    measuredB = true;
    const got = instance.getFixedT(code)(baseOnly);
    if (got !== dicts[b][baseOnly]) {
      failures.push(
        `CONTROL B: "${baseOnly}" is in ${b} and not in the ${code} overlay, so ${code} must ` +
          `render the ${b} value ${JSON.stringify(dicts[b][baseOnly])}. It rendered ` +
          `${JSON.stringify(got)}. Overlay inheritance is not wired and this run would report ` +
          `inherited keys as holes.`,
      );
    }
    break;
  }

  if (!measuredA) {
    failures.push(
      'CONTROL A: no offered locale leaves a key to the English fallback, so the fallback chain ' +
        'could not be measured on this tree and no count below can be trusted.',
    );
  }
  if (overlays > 0 && !measuredB) {
    failures.push(
      `CONTROL B: ${overlays} regional overlay(s) are offered and not one of them leaves a key ` +
        `to its base, so overlay inheritance could not be measured on this tree.`,
    );
  }

  return failures;
}

// ---------------------------------------------------------------------------
// Baseline: declared debt, key to the SET of locales, may only shrink
// ---------------------------------------------------------------------------

function readBaseline() {
  if (!existsSync(BASELINE_PATH)) return {};
  const parsed = JSON.parse(readFileSync(BASELINE_PATH, 'utf8'));
  const out = {};
  for (const [key, entry] of Object.entries(parsed)) {
    if (key.startsWith('_')) continue;
    if (!Array.isArray(entry?.locales)) refuse(`baseline entry "${key}" has no locales array`);
    if (!entry.reason) refuse(`baseline entry "${key}" has no reason`);
    out[key] = new Set(entry.locales);
  }
  return out;
}

// ---------------------------------------------------------------------------
// Self test: prove the detectors can fail, without touching a locale file
// ---------------------------------------------------------------------------

async function selftest() {
  // Thirty keys rather than a handful, because the ratio is what is being
  // tested and a four key fixture cannot express a ten percent one.
  const N = 30;
  const en = {};
  const translated = {};
  for (let i = 0; i < N; i += 1) {
    en[`probe.k${i}`] = `English ${i}`;
    translated[`probe.k${i}`] = `Deutsch ${i}`;
  }
  // Two values identical to English on purpose, the way a unit code or a
  // standard's name is identical in every language. A guard that called those
  // a defect is the guard this one refuses to be, so the fixture carries them.
  translated['probe.k5'] = en['probe.k5'];
  translated['probe.k6'] = en['probe.k6'];
  // One key the translated locale does not declare at all, so it renders
  // through the English fallback. That is what CONTROL A reads.
  delete translated[`probe.k${N - 1}`];

  const dicts = {
    en,
    // A locale doing its job: 3 of 30 read English, 10 percent, inside the band
    // the shipped tree actually sits in.
    good: translated,
    // Shipped as a copy of English. The case this guard exists for.
    copied: { ...en },
    // Translated, but one value is empty, so its reader sees nothing.
    blanked: { ...translated, 'probe.k3': '' },
    // An overlay carrying one word and inheriting the rest from `good`.
    'good-XX': { 'probe.k1': 'Ausgeben' },
  };
  const supported = ['en', 'good', 'copied', 'blanked', 'good-XX'];
  const result = await analyse(dicts, supported);
  const row = (c) => result.rows.find((r) => r.code === c);
  const pct = (c) => `${(row(c).share * 100).toFixed(1)}%`;

  const checks = [];
  const assert = (name, ok, detail) => checks.push({ name, ok, detail });

  assert(
    'a translated locale is clean',
    row('good').blank === 0 && row('good').share < ENGLISH_RENDER_CEILING,
    `blank=${row('good').blank} share=${pct('good')}`,
  );
  assert(
    'two words identical to English on purpose are not a finding',
    row('good').share > 0,
    `share=${pct('good')}, from probe.k5, probe.k6 and one unanswered key`,
  );
  assert('a locale shipped as a copy of English is caught', row('copied').share === 1, `share=${pct('copied')}`);
  assert(
    'a blanked value is caught and named with its locale',
    row('blanked').blank === 1 &&
      result.blanks.some((b) => b.locale === 'blanked' && b.key === 'probe.k3'),
    `blank=${row('blanked').blank}`,
  );
  assert(
    'an overlay inherits from its base and is not reported as a hole',
    row('good-XX').blank === 0 && row('good-XX').share === row('good').share,
    `overlay ${pct('good-XX')} equals base ${pct('good')}`,
  );

  const sound = controls({ ...result, dicts });
  assert('the chain controls pass over a wired instance', sound.length === 0, `${sound.length} finding(s)`);

  // And the controls themselves must be able to fail, or they are decoration.
  // Same dictionaries, one option changed: with no fallback language, a key
  // only en declares can no longer be answered under `good`, so CONTROL A has
  // to say so. If this comes back quiet, every "the chain is live" result
  // above is a fact about nothing.
  const unwired = i18next.createInstance();
  await unwired.init({
    initAsync: false,
    lng: 'en',
    fallbackLng: false,
    keySeparator: false,
    nsSeparator: false,
    interpolation: { escapeValue: false },
    resources: Object.fromEntries(
      Object.entries(dicts).map(([code, dict]) => [code, { translation: dict }]),
    ),
  });
  const broken = controls({ ...result, instance: unwired, dicts });
  assert(
    'the chain controls fire when the chain is cut',
    broken.some((f) => f.startsWith('CONTROL A')),
    broken.length === 0 ? 'controls stayed quiet over an unwired instance' : broken[0].slice(0, 60),
  );

  let failed = 0;
  for (const c of checks) {
    console.log(`${c.ok ? 'ok  ' : 'FAIL'}  ${c.name}  (${c.detail})`);
    if (!c.ok) failed += 1;
  }
  if (failed > 0) {
    console.error(
      `\n${failed} of ${checks.length} self tests failed. This guard cannot see its own defects, ` +
        `so a green run of it proves nothing.`,
    );
    process.exit(1);
  }
  console.log(
    `\n${checks.length} self tests pass. The detectors fire on a locale copied from English and ` +
      `on a blanked value, stay quiet on a translated locale, on an overlay and on words that ` +
      `are identical to English on purpose, and the chain controls fire when the chain is cut.`,
  );
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------

const args = process.argv.slice(2);
if (args.includes('--selftest')) {
  await selftest();
  process.exit(0);
}

const localeDir = args[0] ?? DEFAULT_LOCALE_DIR;

const files = readdirSync(localeDir)
  .filter((f) => f.endsWith('.ts') && !f.endsWith('.test.ts') && !f.endsWith('.d.ts'))
  .sort();
if (files.length === 0) refuse(`found no locale files in ${localeDir}, which is a fact about this run`);

const dicts = {};
for (const file of files) {
  const code = file.slice(0, -3);
  if (code === 'index' || code === 'types') continue;
  try {
    dicts[code] = readLocale(join(localeDir, file));
  } catch (err) {
    refuse(`${file} could not be read as a dictionary: ${err.message}`);
  }
}

const supported = readSupportedLanguages(I18N_TS);
if (supported.length === 0) refuse(`could not read SUPPORTED_LANGUAGES from ${I18N_TS}`);
const missingFiles = supported.filter((code) => !(code in dicts));
if (missingFiles.length > 0) {
  refuse(`offered but absent from ${localeDir}: ${missingFiles.join(', ')}`);
}

const result = await analyse(dicts, supported);

const controlFailures = controls({ ...result, dicts });
if (controlFailures.length > 0) {
  for (const f of controlFailures) console.error(f);
  process.exit(2);
}

// --- report -----------------------------------------------------------------

const sorted = [...result.rows].sort((a, b) => b.share - a.share);
console.log(
  `Real i18next over ${Object.keys(dicts).length} shipped bundles in ${localeDir}, ` +
    `${result.enKeys.length.toLocaleString('en-US')} keys from en.ts, ` +
    `${result.offered.length} of them offered to a reader.\n`,
);
console.log('locale   base   renders English   share    blank');
for (const r of sorted) {
  console.log(
    `${r.code.padEnd(8)} ${(r.base ?? '-').padEnd(6)} ${String(r.rendersEnglish).padStart(15)}   ` +
      `${(r.share * 100).toFixed(2).padStart(6)}%  ${String(r.blank).padStart(6)}` +
      `${r.englishFamily ? '   (English by design)' : ''}`,
  );
}

const notOffered = Object.keys(dicts).filter((c) => !supported.includes(c));
if (notOffered.length > 0) {
  console.log(`\nOn disk but not offered, so not enforced here: ${notOffered.sort().join(', ')}.`);
}

let failed = false;

// --- finding 1: a reader looking at nothing ---------------------------------

const baseline = readBaseline();
const nowBlank = new Map();
for (const { key, locale } of result.blanks) {
  if (!nowBlank.has(key)) nowBlank.set(key, new Set());
  nowBlank.get(key).add(locale);
}

const undeclared = [];
for (const [key, locales] of nowBlank) {
  const declared = baseline[key] ?? new Set();
  const fresh = [...locales].filter((l) => !declared.has(l)).sort();
  if (fresh.length > 0) undeclared.push({ key, locales: fresh });
}
const repaired = [];
for (const [key, locales] of Object.entries(baseline)) {
  const still = nowBlank.get(key) ?? new Set();
  const gone = [...locales].filter((l) => !still.has(l)).sort();
  if (gone.length > 0) repaired.push({ key, locales: gone });
}

if (undeclared.length > 0) {
  failed = true;
  const cells = undeclared.reduce((n, u) => n + u.locales.length, 0);
  console.error(
    `\n${cells} cell(s) render blank where English renders text, and are not declared debt.\n` +
      `A reader of that language is looking at an empty control.`,
  );
  for (const u of undeclared.slice(0, 40)) {
    console.error(`  ${u.key}  ->  ${u.locales.join(', ')}`);
  }
  if (undeclared.length > 40) console.error(`  and ${undeclared.length - 40} more keys`);
  console.error(
    `\nFix the value, or declare it in ${BASELINE_PATH} with a reason. The baseline is a set of ` +
      `locales per key, never a count: a count cannot tell a repaired cell from a new one.`,
  );
} else if (nowBlank.size > 0) {
  const cells = [...nowBlank.values()].reduce((n, s) => n + s.size, 0);
  console.log(`\n${cells} blank cell(s) across ${nowBlank.size} key(s), all declared debt.`);
} else {
  console.log('\nNo offered locale renders blank where English renders text.');
}

if (repaired.length > 0) {
  // Reported loudly, deliberately not a failure. The baseline may only shrink,
  // and slack left in it is where the next defect hides, so this has to be said
  // on every run. But several sessions edit these files at the same time, and a
  // guard that turns red because somebody repaired a string is a guard that
  // gets switched off within a week. Growth fails, shrinkage is announced. That
  // is the same rule scripts/check_i18n_leak_baseline.py applies to the file it
  // owns, and this is the same shape of file.
  console.log(
    `\n${repaired.length} baseline entr(y/ies) name a locale that is no longer blank. Trim them ` +
      `in the change that repaired the value:`,
  );
  for (const r of repaired) console.log(`  ${r.key}  ->  remove ${r.locales.join(', ')}`);
}

// --- finding 2: a locale that does not render its own language --------------

const tooEnglish = sorted.filter((r) => !r.englishFamily && r.share > ENGLISH_RENDER_CEILING);
if (tooEnglish.length > 0) {
  failed = true;
  console.error(
    `\n${tooEnglish.length} offered locale(s) render more than ` +
      `${(ENGLISH_RENDER_CEILING * 100).toFixed(0)}% of en.ts in English.`,
  );
  for (const r of tooEnglish) {
    console.error(
      `  ${r.code}: ${r.rendersEnglish.toLocaleString('en-US')} of ` +
        `${result.enKeys.length.toLocaleString('en-US')} keys (${(r.share * 100).toFixed(2)}%)`,
    );
  }
  console.error(
    `\nEither the bundle is not being translated, or it is not reaching i18next. Both read the ` +
      `same to someone using the product: they picked their language and got English.`,
  );
} else {
  const worst = sorted.find((r) => !r.englishFamily);
  console.log(
    `Every offered locale renders its own language: worst is ${worst.code} at ` +
      `${(worst.share * 100).toFixed(2)}%, ceiling ${(ENGLISH_RENDER_CEILING * 100).toFixed(0)}%.`,
  );
}

process.exit(failed ? 1 : 0);
