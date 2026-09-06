#!/usr/bin/env node
/* ================================================================
 * check-case-coverage.mjs
 *
 * Finds case strings that were never translated, and stops that number
 * growing without anyone saying so.
 *
 * WHY THIS EXISTS
 *
 * A playbook under src/features/cases/data names every string it renders
 * by key and carries the English inline as a *Default field, so a key no
 * locale answers renders English in that locale, in that locale only, and
 * nothing looks wrong to the person who added the case. No other gate can
 * see it. check_i18n_orphan_keys.py reads literal t('...') calls, and at
 * these call sites the key is a variable off a data row.
 * check-case-translation-drift.mjs reports a translation whose English
 * moved and deliberately skips a key that was never translated, because
 * a translation that does not exist cannot have gone stale.
 * check_case_playbook_catalogue_locales.py holds the finished languages to
 * the catalogue text, which is the title, the one-line description and
 * the long description. Nobody owned the step text, and that is where the
 * gap lives: measured on 2026-09-06, 220 playbooks name 7037 keys and most
 * offered locales lack about 3000 of them, a number that grew with every
 * new case because nothing could see it grow.
 *
 * HOW IT WORKS
 *
 * Every playbook is read for the keys it names (titleKey, descKey,
 * longDescKey, whatKey, whyKey, labelKey, inputsHintKey, outputsHintKey),
 * every locale file for the cases.* keys it defines, and each offered
 * locale gets a count of what it does not answer. A manifest records
 * those counts, per locale and per playbook, and the check fails when any
 * count is HIGHER than recorded: a key a locale had and lost, or a case
 * that shipped without its strings. Lower is always fine, and --update
 * records the lower numbers. It will not record a higher one, so the
 * manifest is a floor that only moves down, and taking on new debt has to
 * be a hand edit that shows in the diff.
 *
 * Per playbook and not per locale, because a total nets out. A locale that
 * gained 30 keys on one case and lost 30 on another shows the same total,
 * and the case that lost them renders English with nothing to say so. Per
 * key would be exact and is not affordable, roughly 120,000 entries today.
 * A playbook is the unit a translator works in and the unit a case ships
 * in, so it is the grain at which a regression has a name.
 *
 * Regional variants are counted through their base language. es-MX,
 * es-CL, es-CO and pt-BR fall back to es and pt before English
 * (fallbackLng in src/app/i18n.ts), and the chip and orphan guards apply
 * the same rule, so a key those files do not carry renders the base
 * translation and is not a gap. The file-only figure is printed beside it
 * for anyone measuring what the regional file itself holds.
 *
 * en is the source, its English lives in the playbooks and not in en.ts,
 * so it is not counted; en-US is an overlay over en and is not counted
 * either; a locale file that is not in SUPPORTED_LANGUAGES is reported
 * and not gated, because nothing loads it.
 *
 * card_complete is the list of base locales whose catalogue text is
 * complete for every playbook: title, description, and long description
 * where the English has one. --update promotes a locale into it the day
 * it gets there and never takes one out.
 * check_case_playbook_catalogue_locales.py reads that list, so the
 * finished languages are named in one place.
 *
 * What it cannot see: a key whose value is a copy of the English. That
 * renders exactly like a missing one and belongs to
 * check_locale_english_placeholder.py and check-locale-render.mjs.
 * Presence is what is measured here. The gate this extends is described
 * in docs/strategy/I18N_NAMESPACE_GAP_CENSUS.md under "Suggested gates".
 *
 * Usage:
 *   node frontend/scripts/check-case-coverage.mjs
 *   node frontend/scripts/check-case-coverage.mjs --update
 *   node frontend/scripts/check-case-coverage.mjs --selftest
 *
 *   --update              record the current, lower numbers and promote a
 *                         locale that reached full catalogue coverage.
 *                         Refuses to raise a number or demote a locale.
 *   --selftest            prove the check can fail, on data built to fail
 *   --json                print the measurement as JSON instead of a table
 *   --data-dir <dir>      read playbooks from here instead of the tree
 *   --locales-dir <dir>   read locale files from here instead of the tree
 *   --manifest <file>     read and write this manifest instead of the tree's
 *   The overrides exist so a regression can be staged in a scratch copy
 *   and shown to fail without touching the tree.
 * ================================================================ */

import { existsSync, mkdirSync, mkdtempSync, readdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { basename, dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const SCRIPT_DIR = dirname(fileURLToPath(import.meta.url));
const FRONTEND_ROOT = resolve(SCRIPT_DIR, '..');

const DEFAULTS = {
  dataDir: join(FRONTEND_ROOT, 'src/features/cases/data'),
  localesDir: join(FRONTEND_ROOT, 'src/app/locales'),
  i18n: join(FRONTEND_ROOT, 'src/app/i18n.ts'),
  manifest: join(FRONTEND_ROOT, 'src/features/cases/case-coverage-manifest.json'),
};

/* Paths as a reader of the message will type them, from the repo root. */
const REL_DATA = 'frontend/src/features/cases/data';
const REL_LOCALES = 'frontend/src/app/locales';
const REL_MANIFEST = 'frontend/src/features/cases/case-coverage-manifest.json';
const REL_SCRIPT = 'frontend/scripts/check-case-coverage.mjs';

const KEY_FIELDS = ['titleKey', 'descKey', 'longDescKey', 'whatKey', 'whyKey', 'labelKey', 'inputsHintKey', 'outputsHintKey'];
/* \b keeps moduleLabelKey out: that one names a module chip in the nav
 * namespace and check_case_module_chip_locales.py owns it. */
const KEY_REF = new RegExp(`\\b(${KEY_FIELDS.join('|')})\\s*:\\s*"([^"]+)"`, 'g');
const LOCALE_KEY = /^\s*"(cases\.[^"]+)":/gm;

const NOT_COUNTED = new Map([
  ['en', 'the source; the English of a case lives in its playbook, not in en.ts'],
  ['en-US', 'an overlay over en that holds only the words American practice names differently'],
]);

const MANIFEST_NOTE =
  'Number of case keys each offered locale does not answer, per playbook, recorded so that the number ' +
  'can be seen to grow. The check fails when any playbook count in any locale is higher than recorded: ' +
  'a key the locale had and lost, or a case that shipped without its strings. Lower is always fine and ' +
  '--update records it; --update never raises a number and never removes a locale from card_complete, ' +
  'so the debt here only shrinks and any exception has to be a hand edit that shows in the diff. ' +
  'Regional variants (es-MX, es-CL, es-CO, pt-BR) are counted through their base language, the way ' +
  'i18n.ts resolves them. card_complete lists the base locales whose catalogue text (title, description, ' +
  'and long description where the English has one) is complete for every playbook, and ' +
  'scripts/check_case_playbook_catalogue_locales.py holds those locales to it. A locale joins that list ' +
  'when --update finds it complete.';

/* ---------------------------------------------------------------- */

function parseArgs(argv) {
  const out = {
    update: false,
    selftest: false,
    json: false,
    dataDir: DEFAULTS.dataDir,
    localesDir: DEFAULTS.localesDir,
    i18n: DEFAULTS.i18n,
    manifest: DEFAULTS.manifest,
  };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    const value = () => {
      const v = argv[++i];
      if (!v) {
        console.error(`check-case-coverage: ${a} needs a value`);
        process.exit(2);
      }
      return resolve(v);
    };
    if (a === '--update') out.update = true;
    else if (a === '--selftest') out.selftest = true;
    else if (a === '--json') out.json = true;
    else if (a === '--data-dir') out.dataDir = value();
    else if (a === '--locales-dir') out.localesDir = value();
    else if (a === '--manifest') out.manifest = value();
    else {
      console.error(`check-case-coverage: unknown argument ${a}`);
      process.exit(2);
    }
  }
  return out;
}

/* ---------------------------------------------------------------- */

/* Every key a playbook names, plus the three catalogue keys picked out by
 * shape: the top-level title, desc and longdesc are the only keys with
 * exactly two dots, cases.<slug>.<field>, while step keys carry the step
 * id as well. */
function readPlaybooks(dataDir) {
  const files = readdirSync(dataDir)
    .filter((f) => f.endsWith('.playbook.ts'))
    .sort();
  const playbooks = [];
  const byField = Object.fromEntries(KEY_FIELDS.map((f) => [f, 0]));
  for (const f of files) {
    const src = readFileSync(join(dataDir, f), 'utf8');
    const keys = new Set();
    const named = {};
    let m;
    KEY_REF.lastIndex = 0;
    while ((m = KEY_REF.exec(src)) !== null) {
      keys.add(m[2]);
      byField[m[1]]++;
      (named[m[1]] ??= []).push(m[2]);
    }
    const top = (field) => (named[field] || []).find((k) => k.split('.').length === 3) || null;
    playbooks.push({
      slug: basename(f, '.playbook.ts'),
      file: f,
      keys,
      title: top('titleKey'),
      desc: top('descKey'),
      longdesc: top('longDescKey'),
    });
  }
  return { playbooks, byField };
}

function readLocales(localesDir) {
  const out = new Map();
  const files = readdirSync(localesDir)
    .filter((f) => f.endsWith('.ts'))
    .sort();
  for (const f of files) {
    const code = basename(f, '.ts');
    if (code === 'index' || code === 'types') continue;
    const src = readFileSync(join(localesDir, f), 'utf8');
    const have = new Set();
    let m;
    LOCALE_KEY.lastIndex = 0;
    while ((m = LOCALE_KEY.exec(src)) !== null) have.add(m[1]);
    out.set(code, have);
  }
  return out;
}

/* Which languages the product offers. Parsed from the `code:` field of
 * SUPPORTED_LANGUAGES only: the entries also carry name, flag and country,
 * and scraping every quoted string reports 114 languages instead of 42.
 * Null when the block cannot be found, and the caller stops on null: a
 * fallback to "every file on disk" would gate the locales this tree says
 * not to touch. */
function offeredLanguages(i18nPath) {
  const src = readFileSync(i18nPath, 'utf8');
  const start = src.indexOf('export const SUPPORTED_LANGUAGES');
  if (start < 0) return null;
  const end = src.indexOf('\n];', start);
  const block = src.slice(start, end < 0 ? undefined : end);
  const codes = [...block.matchAll(/\bcode:\s*'([A-Za-z-]+)'/g)].map((m) => m[1]);
  return codes.length ? codes : null;
}

/* One locale's view of every playbook. `answers` is the set of keys a
 * reader of that locale gets, which for a regional variant includes its
 * base language. */
function measure(playbooks, answers) {
  const gaps = {};
  const catalogue = [];
  let missing = 0;
  let titles = 0;
  let descs = 0;
  let cards = 0;
  let longdescs = 0;
  let complete = 0;
  for (const p of playbooks) {
    const lost = [...p.keys].filter((k) => !answers.has(k)).sort();
    if (lost.length) {
      gaps[p.slug] = lost;
      missing += lost.length;
    } else {
      complete++;
    }
    const hasTitle = Boolean(p.title && answers.has(p.title));
    const hasDesc = Boolean(p.desc && answers.has(p.desc));
    const hasLong = Boolean(p.longdesc && answers.has(p.longdesc));
    if (hasTitle) titles++;
    if (hasDesc) descs++;
    if (hasTitle && hasDesc) cards++;
    if (hasLong) longdescs++;
    /* Catalogue text is owed only where the English has it: 82 playbooks
     * carry no longDescKey at all, which is a gap in the English copy and
     * not in any translation. */
    for (const key of [p.title, p.desc, p.longdesc]) {
      if (key && !answers.has(key)) catalogue.push({ key, slug: p.slug, file: p.file });
    }
  }
  return { gaps, catalogue, missing, titles, descs, cards, longdescs, complete };
}

function analyse(opts) {
  const { playbooks, byField } = readPlaybooks(opts.dataDir);
  const files = readLocales(opts.localesDir);
  const offered = opts.offered;
  const references = new Set();
  for (const p of playbooks) for (const k of p.keys) references.add(k);

  const counted = [];
  const skipped = [];
  for (const [code, have] of files) {
    if (NOT_COUNTED.has(code)) {
      skipped.push({ code, why: NOT_COUNTED.get(code) });
      continue;
    }
    if (!offered.includes(code)) {
      skipped.push({ code, why: 'on disk but not in SUPPORTED_LANGUAGES, so nothing loads it' });
      continue;
    }
    const base = code.includes('-') ? code.split('-')[0] : null;
    const baseHave = base && files.has(base) && offered.includes(base) ? files.get(base) : null;
    const file = measure(playbooks, have);
    const gate = baseHave ? measure(playbooks, new Set([...have, ...baseHave])) : file;
    counted.push({ code, base: baseHave ? base : null, file, gate });
  }
  const missingFiles = offered.filter((c) => !files.has(c) && !NOT_COUNTED.has(c)).sort();
  return {
    playbooks,
    byField,
    references: references.size,
    files: files.size,
    counted,
    skipped,
    missingFiles,
    withLongdesc: playbooks.filter((p) => p.longdesc).length,
  };
}

/* ---------------------------------------------------------------- */

function evaluate(analysis, manifest) {
  const failures = [];
  const tighten = new Set();
  const recorded = manifest.locales || {};
  const cardComplete = new Set(manifest.card_complete || []);

  for (const e of analysis.counted) {
    const rec = recorded[e.code];
    if (!rec) {
      failures.push({ kind: 'unrecorded', code: e.code });
      continue;
    }
    const was = rec.gaps || {};
    for (const [slug, keys] of Object.entries(e.gate.gaps)) {
      const before = was[slug] ?? 0;
      if (keys.length > before) failures.push({ kind: 'regressed', code: e.code, base: e.base, slug, keys, recorded: before });
      else if (keys.length < before) tighten.add(e.code);
    }
    for (const slug of Object.keys(was)) if (!(slug in e.gate.gaps)) tighten.add(e.code);
    if (cardComplete.has(e.code) && e.gate.catalogue.length) {
      failures.push({ kind: 'catalogue', code: e.code, catalogue: e.gate.catalogue });
    }
  }
  for (const code of analysis.missingFiles) failures.push({ kind: 'nofile', code });
  return { failures, tighten: [...tighten].sort() };
}

function buildManifest(analysis, prior) {
  const refused = [];
  const priorLocales = (prior && prior.locales) || {};
  const priorComplete = new Set((prior && prior.card_complete) || []);
  const locales = {};
  const cardComplete = new Set();
  const firstSeen = [];

  for (const e of analysis.counted) {
    const rec = priorLocales[e.code];
    if (rec) {
      const was = rec.gaps || {};
      for (const [slug, keys] of Object.entries(e.gate.gaps)) {
        const before = was[slug] ?? 0;
        if (keys.length > before) refused.push({ kind: 'regressed', code: e.code, base: e.base, slug, keys, recorded: before });
      }
    } else {
      firstSeen.push(e.code);
    }
    if (priorComplete.has(e.code) && e.gate.catalogue.length) {
      refused.push({ kind: 'catalogue', code: e.code, catalogue: e.gate.catalogue });
    }
    const gaps = Object.fromEntries(
      Object.entries(e.gate.gaps)
        .sort(([a], [b]) => (a < b ? -1 : 1))
        .map(([slug, keys]) => [slug, keys.length])
    );
    locales[e.code] = { cards: e.gate.cards, missing: e.gate.missing, gaps };
    if (!e.base && !e.gate.catalogue.length) cardComplete.add(e.code);
  }

  const promoted = [...cardComplete].filter((c) => !priorComplete.has(c)).sort();
  const dropped = Object.keys(priorLocales)
    .filter((c) => !(c in locales))
    .sort();
  const manifest = {
    note: MANIFEST_NOTE,
    updated: new Date().toISOString().slice(0, 10),
    playbooks: analysis.playbooks.length,
    references: analysis.references,
    card_complete: [...cardComplete].sort(),
    locales: Object.fromEntries(Object.entries(locales).sort(([a], [b]) => (a < b ? -1 : 1))),
  };
  return { manifest, refused, promoted, dropped, firstSeen };
}

/* ---------------------------------------------------------------- */

function printPopulation(analysis) {
  const fields = KEY_FIELDS.map((f) => `${f} ${analysis.byField[f]}`).join(', ');
  console.log(
    `case coverage: ${analysis.playbooks.length} playbooks name ${analysis.references} keys (${fields}); ` +
      `${analysis.files} locale files, ${analysis.counted.length} counted`
  );
  for (const s of analysis.skipped) console.log(`  not counted: ${s.code}, ${s.why}`);
}

function printTable(analysis, manifest) {
  const n = analysis.playbooks.length;
  const recorded = (manifest && manifest.locales) || {};
  const cardComplete = new Set((manifest && manifest.card_complete) || []);
  console.log('');
  console.log(
    `  ${'locale'.padEnd(6)} ${'title'.padStart(7)} ${'desc'.padStart(7)} ${'longdesc'.padStart(8)} ` +
      `${'complete'.padStart(8)} ${'missing'.padStart(9)} ${'recorded'.padStart(8)}`
  );
  for (const e of analysis.counted) {
    const g = e.gate;
    const rec = recorded[e.code];
    const flags = [];
    if (cardComplete.has(e.code)) flags.push('card_complete');
    if (e.base) {
      flags.push(
        `through ${e.base}; the file alone: ${e.file.titles} title, ${e.file.descs} desc, ` +
          `${e.file.longdescs} longdesc, ${e.file.complete} complete, ${e.file.missing} missing`
      );
    }
    console.log(
      `  ${e.code.padEnd(6)} ${`${g.titles}/${n}`.padStart(7)} ${`${g.descs}/${n}`.padStart(7)} ` +
        `${`${g.longdescs}/${analysis.withLongdesc}`.padStart(8)} ${`${g.complete}/${n}`.padStart(8)} ` +
        `${String(g.missing).padStart(9)} ${(rec ? String(rec.missing) : '-').padStart(8)}` +
        (flags.length ? `   ${flags.join('; ')}` : '')
    );
  }
  console.log('');
}

function printProblems(problems, verb) {
  const regressed = problems.filter((p) => p.kind === 'regressed');
  const bySlug = new Map();
  for (const r of regressed) (bySlug.get(r.slug) || bySlug.set(r.slug, []).get(r.slug)).push(r);

  if (regressed.length) {
    console.error(`    ${verb}: ${new Set(regressed.map((r) => r.code)).size} locale(s), ${bySlug.size} playbook(s)`);
    console.error('');
    let shown = 0;
    for (const [slug, list] of bySlug) {
      console.error(`    ${slug}  (${REL_DATA}/${slug}.playbook.ts)`);
      for (const r of list) {
        if (shown++ >= 40) continue;
        const where = r.base ? `${r.code} and its base ${r.base}` : r.code;
        console.error(`      ${where}: ${r.keys.length} missing, ${r.recorded} recorded`);
        for (const k of r.keys.slice(0, 12)) console.error(`        ${k}`);
        if (r.keys.length > 12) console.error(`        ... and ${r.keys.length - 12} more`);
      }
      if (shown > 40) console.error(`      ... and ${shown - 40} more locale(s) for this playbook`);
      console.error('');
    }
  }
  for (const p of problems.filter((x) => x.kind === 'catalogue')) {
    console.error(`    ${p.code} is listed as card_complete and is missing catalogue text:`);
    for (const c of p.catalogue.slice(0, 12)) console.error(`        ${c.key}  (${REL_DATA}/${c.file})`);
    if (p.catalogue.length > 12) console.error(`        ... and ${p.catalogue.length - 12} more`);
    console.error('');
  }
  for (const p of problems.filter((x) => x.kind === 'unrecorded')) {
    console.error(`    ${p.code} is offered in SUPPORTED_LANGUAGES and has no baseline in ${REL_MANIFEST}.`);
    console.error(`      Record one: node ${REL_SCRIPT} --update`);
    console.error('');
  }
  for (const p of problems.filter((x) => x.kind === 'nofile')) {
    console.error(`    ${p.code} is offered in SUPPORTED_LANGUAGES and has no file under ${REL_LOCALES}.`);
    console.error('');
  }
}

function printHowToFix() {
  console.error('  A key a playbook names and a locale does not answer renders English to');
  console.error('  every reader of that locale, and nothing on screen says so.');
  console.error('');
  console.error(`  Add the missing keys to ${REL_LOCALES}/<code>.ts, translated from the`);
  console.error(`  *Default English beside each key in ${REL_DATA}/<slug>.playbook.ts.`);
  console.error('  A locale may only ever answer more. When it does, record the lower');
  console.error('  numbers and commit the manifest with the translations:');
  console.error(`    node ${REL_SCRIPT} --update`);
  console.error('');
}

/* ---------------------------------------------------------------- */

function readManifest(path) {
  if (!existsSync(path)) return null;
  return JSON.parse(readFileSync(path, 'utf8'));
}

function writeManifest(path, manifest) {
  writeFileSync(path, JSON.stringify(manifest, null, 2) + '\n', 'utf8');
}

function toJson(analysis, manifest) {
  const locales = {};
  for (const e of analysis.counted) {
    const strip = (m) => ({
      titles: m.titles,
      descs: m.descs,
      cards: m.cards,
      longdescs: m.longdescs,
      complete: m.complete,
      missing: m.missing,
      catalogue_complete: m.catalogue.length === 0,
    });
    locales[e.code] = { base: e.base, file: strip(e.file), gate: strip(e.gate) };
  }
  return {
    playbooks: analysis.playbooks.length,
    references: analysis.references,
    by_field: analysis.byField,
    with_longdesc: analysis.withLongdesc,
    locale_files: analysis.files,
    counted: analysis.counted.length,
    not_counted: analysis.skipped,
    card_complete: (manifest && manifest.card_complete) || [],
    locales,
  };
}

function run(args) {
  const offered = offeredLanguages(args.i18n);
  if (!offered) {
    console.error(`check-case-coverage: could not read SUPPORTED_LANGUAGES from ${args.i18n}`);
    return 2;
  }
  const analysis = analyse({ ...args, offered });
  const manifest = readManifest(args.manifest);

  if (args.json) {
    console.log(JSON.stringify(toJson(analysis, manifest), null, 2));
    return 0;
  }

  printPopulation(analysis);

  if (args.update) {
    const { manifest: next, refused, promoted, dropped, firstSeen } = buildManifest(analysis, manifest);
    printTable(analysis, next);
    if (refused.length) {
      console.error('');
      console.error('  ================================================================');
      console.error('  --update REFUSED. It would record a locale answering fewer keys than');
      console.error('  it did, and this manifest only ever moves the other way.');
      console.error('  ================================================================');
      console.error('');
      printProblems(refused, 'would raise');
      printHowToFix();
      console.error('  If a case really must ship ahead of its strings, raise the number by');
      console.error(`  hand in ${REL_MANIFEST} so the decision is visible in the diff.`);
      console.error('');
      return 2;
    }
    writeManifest(args.manifest, next);
    const gaps = Object.values(next.locales).reduce((n, l) => n + Object.keys(l.gaps).length, 0);
    console.log(
      `case-coverage-manifest: ${Object.keys(next.locales).length} locale(s) recorded, ${gaps} playbook gap(s), ` +
        `card_complete: ${next.card_complete.join(' ') || 'none'}`
    );
    if (promoted.length) console.log(`  promoted to card_complete: ${promoted.join(' ')}`);
    if (firstSeen.length) console.log(`  recorded for the first time: ${firstSeen.join(' ')}`);
    if (dropped.length) console.log(`  dropped, no longer offered or on disk: ${dropped.join(' ')}`);
    return 0;
  }

  if (!manifest) {
    console.error(`check-case-coverage: no manifest at ${REL_MANIFEST}. Create one with --update`);
    console.error('  (that records the tree as it stands, which is a floor and not a certificate)');
    return 2;
  }

  printTable(analysis, manifest);
  const { failures, tighten } = evaluate(analysis, manifest);

  if (!failures.length) {
    console.log(
      `case coverage: no locale answers fewer case keys than recorded ` +
        `(${analysis.counted.length} locales, ${analysis.playbooks.length} playbooks, ${analysis.references} keys)`
    );
    if (tighten.length) {
      console.log(`  ${tighten.length} locale(s) now answer more than recorded (${tighten.join(' ')}): ` + `tighten the floor with --update`);
    }
    return 0;
  }

  console.error('');
  console.error('  ================================================================');
  console.error('  CASE COVERAGE REGRESSED. A locale answers fewer case keys than it did.');
  console.error('  ================================================================');
  console.error('');
  printProblems(failures, 'regressed');
  printHowToFix();
  return 1;
}

/* ---------------------------------------------------------------- */

/* The check must be able to fail, so prove it on data built to fail. A
 * gate only ever seen passing is indistinguishable from one that cannot
 * fail at all. Every branch that can turn the tree red is driven here:
 * a lost key, a case shipped without strings, catalogue text lost under a
 * stale-high floor, a regional variant losing what its base lost, and
 * --update refusing to raise a number. */
function selftest() {
  const tmp = mkdtempSync(join(tmpdir(), 'case-coverage-'));
  const fail = (msg) => {
    console.error(`selftest FAILED: ${msg}`);
    return 1;
  };
  try {
    const data = join(tmp, 'data');
    const locs = join(tmp, 'locales');
    mkdirSync(data);
    mkdirSync(locs);
    const playbook = (slug, withLong) =>
      `titleKey: "cases.${slug}.title",\ndescKey: "cases.${slug}.desc",\n` +
      (withLong ? `longDescKey: "cases.${slug}.longdesc",\n` : '') +
      `steps: [{ labelKey: "cases.${slug}.step.one.in.x", label: "x",\n` +
      `titleKey: "cases.${slug}.step.one.title", whatKey: "cases.${slug}.step.one.what",\n` +
      `whyKey: "cases.${slug}.step.one.why", moduleLabelKey: "nav.other" }]\n`;
    const allKeys = (slug, withLong) => [
      `cases.${slug}.title`,
      `cases.${slug}.desc`,
      ...(withLong ? [`cases.${slug}.longdesc`] : []),
      `cases.${slug}.step.one.in.x`,
      `cases.${slug}.step.one.title`,
      `cases.${slug}.step.one.what`,
      `cases.${slug}.step.one.why`,
    ];
    const locale = (keys) => `const resource = {\n  "translation": {\n${keys.map((k) => `    "${k}": "v",`).join('\n')}\n  },\n};\n`;
    const write = (name, keys) => writeFileSync(join(locs, `${name}.ts`), locale(keys), 'utf8');

    writeFileSync(join(data, 'a.playbook.ts'), playbook('a', true), 'utf8');
    writeFileSync(join(data, 'b.playbook.ts'), playbook('b', false), 'utf8');
    const full = [...allKeys('a', true), ...allKeys('b', false)];
    write('xx', full);
    write('yy', full.filter((k) => k !== 'cases.a.step.one.why'));
    write('zz', full);
    write('zz-XX', []);
    write('en', []);
    write('mm', []);
    const offered = ['en', 'xx', 'yy', 'zz', 'zz-XX'];
    const opts = { dataDir: data, localesDir: locs, offered };

    /* 1. A baseline from a tree, and the same tree against it, is green. */
    const a0 = analyse(opts);
    const base = buildManifest(a0, null);
    if (base.refused.length) return fail('a first baseline was refused');
    if (base.manifest.card_complete.join(' ') !== 'xx yy zz') {
      return fail(`card_complete should be the three base locales with complete catalogue text, got: ${base.manifest.card_complete.join(' ')}`);
    }
    if (a0.counted.some((e) => e.code === 'mm' || e.code === 'en')) return fail('a locale that is not offered, or en, was counted');
    if (base.manifest.locales.yy.gaps.a !== 1) return fail('yy should owe one key on a');
    if (base.manifest.locales['zz-XX'].missing !== 0) return fail('an empty regional file over a complete base should owe nothing');
    let r = evaluate(a0, base.manifest);
    if (r.failures.length) return fail(`green tree evaluated red: ${JSON.stringify(r.failures[0])}`);

    /* 2. A key a locale had and lost. */
    write('xx', full.filter((k) => k !== 'cases.a.step.one.what'));
    r = evaluate(analyse(opts), base.manifest);
    const lost = r.failures.find((f) => f.kind === 'regressed' && f.code === 'xx' && f.slug === 'a');
    if (!lost || !lost.keys.includes('cases.a.step.one.what')) return fail('a lost step key was not reported by locale, playbook and key');
    if (r.failures.length !== 1) return fail(`one lost key should be one failure, got ${r.failures.length}`);
    /* ... and --update will not record it. */
    if (!buildManifest(analyse(opts), base.manifest).refused.length) return fail('--update recorded a raised number');
    write('xx', full);

    /* 3. Catalogue text lost under a stale-high floor is still caught. */
    const stale = JSON.parse(JSON.stringify(base.manifest));
    stale.locales.yy.gaps.a = 99;
    write('yy', full.filter((k) => k !== 'cases.a.step.one.why' && k !== 'cases.a.title'));
    r = evaluate(analyse(opts), stale);
    if (r.failures.some((f) => f.kind === 'regressed')) return fail('a stale-high floor should not have reported a ratchet regression');
    const cat = r.failures.find((f) => f.kind === 'catalogue' && f.code === 'yy');
    if (!cat || !cat.catalogue.some((c) => c.key === 'cases.a.title')) return fail('a lost title in a card_complete locale was not reported');
    write('yy', full.filter((k) => k !== 'cases.a.step.one.why'));

    /* 4. A case shipped without its strings regresses every counted locale. */
    writeFileSync(join(data, 'c.playbook.ts'), playbook('c', false), 'utf8');
    r = evaluate(analyse(opts), base.manifest);
    const hit = r.failures.filter((f) => f.kind === 'regressed' && f.slug === 'c').map((f) => f.code);
    if (hit.sort().join(' ') !== 'xx yy zz zz-XX') return fail(`a new case without strings should regress every counted locale, got: ${hit.join(' ')}`);
    rmSync(join(data, 'c.playbook.ts'));

    /* 5. A regional variant loses what its base loses, and nothing else. */
    write('zz', full.filter((k) => k !== 'cases.b.desc'));
    r = evaluate(analyse(opts), base.manifest);
    const regional = r.failures.filter((f) => f.kind === 'regressed').map((f) => f.code);
    if (regional.sort().join(' ') !== 'zz zz-XX') return fail(`a base losing a key should regress it and its variant, got: ${regional.join(' ')}`);
    if (!r.failures.some((f) => f.kind === 'catalogue' && f.code === 'zz')) return fail('a lost desc in a card_complete base was not reported');
    if (r.failures.some((f) => f.kind === 'catalogue' && f.code === 'zz-XX')) return fail('a regional variant must not be held to card_complete');
    write('zz', full);

    /* 6. Restored, the tree is green again, and an offered locale with no
     *    baseline is named. */
    r = evaluate(analyse(opts), base.manifest);
    if (r.failures.length) return fail('the restored tree is not green');
    r = evaluate(analyse({ ...opts, offered: [...offered, 'mm'] }), base.manifest);
    if (!r.failures.some((f) => f.kind === 'unrecorded' && f.code === 'mm')) return fail('an offered locale without a baseline was not reported');
  } finally {
    rmSync(tmp, { recursive: true, force: true });
  }
  console.log('selftest ok: the check fails on a lost key, a case without strings, lost catalogue text, a regional variant behind its base, and an unrecorded locale, and --update refuses to raise a number');
  return 0;
}

/* ---------------------------------------------------------------- */

const args = parseArgs(process.argv.slice(2));
process.exit(args.selftest ? selftest() : run(args));
