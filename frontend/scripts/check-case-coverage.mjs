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
 * THE FLOOR IS MEASURED FROM A COMMIT, NEVER FROM THE WORKING TREE
 *
 * The first floor was written from a checkout that also held Russian and
 * Chinese case translations nobody had committed, about 626 lines in each
 * file. It recorded fifteen playbooks as answered in ru and zh while the
 * committed files answered none of them, and the gate then failed every
 * push on main for a regression that had never happened: the tree it
 * measured and the tree it guards were two different things. So --update
 * reads the playbooks, the locale files and SUPPORTED_LANGUAGES out of a
 * commit (HEAD unless --from-git names another) and writes that commit's
 * hash into the manifest as measured_at. What is on disk cannot reach the
 * floor, there is no flag that lets it, and anyone can re-derive the
 * numbers from the hash. The check itself still reads the working tree,
 * because that is what a developer wants to know before committing and
 * because in CI the working tree is the commit; when the two differ it
 * says so and names the files.
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
 *   --update              measure HEAD, record the current, lower numbers
 *                         and promote a locale that reached full catalogue
 *                         coverage. Refuses to raise a number or demote a
 *                         locale. Never reads the working tree.
 *   --from-git <ref>      measure that commit instead of HEAD (--update) or
 *                         instead of the working tree (check, --json)
 *   --selftest            prove the check can fail, on data built to fail,
 *                         and that --update cannot see the working tree
 *   --json                print the measurement as JSON instead of a table
 *   --data-dir <dir>      check only: read playbooks from here
 *   --locales-dir <dir>   check only: read locale files from here
 *   --manifest <file>     read and write this manifest instead of the tree's
 *   The directory overrides exist so a regression can be staged in a
 *   scratch copy and shown to fail without touching the tree. They are
 *   refused with --update, which measures a commit and nothing else.
 * ================================================================ */

import { existsSync, mkdirSync, mkdtempSync, readdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { execFileSync } from 'node:child_process';
import { tmpdir } from 'node:os';
import { basename, dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const SCRIPT_DIR = dirname(fileURLToPath(import.meta.url));
const FRONTEND_ROOT = resolve(SCRIPT_DIR, '..');
const REPO_ROOT = resolve(FRONTEND_ROOT, '..');

/* Paths as git and a reader of the message know them, from the repo root. */
const REL = {
  data: 'frontend/src/features/cases/data',
  locales: 'frontend/src/app/locales',
  i18n: 'frontend/src/app/i18n.ts',
  manifest: 'frontend/src/features/cases/case-coverage-manifest.json',
  script: 'frontend/scripts/check-case-coverage.mjs',
};

const DEFAULTS = {
  dataDir: join(REPO_ROOT, REL.data),
  localesDir: join(REPO_ROOT, REL.locales),
  i18n: join(REPO_ROOT, REL.i18n),
  manifest: join(REPO_ROOT, REL.manifest),
};

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
  'The numbers are measured from the committed blobs at measured_at and never from the working tree: ' +
  'a floor once banked from a dirty checkout recorded translations nobody had committed, and the gate ' +
  'failed every push for a regression that had not happened. ' +
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
    fromGit: null,
    dataDir: DEFAULTS.dataDir,
    localesDir: DEFAULTS.localesDir,
    i18n: DEFAULTS.i18n,
    manifest: DEFAULTS.manifest,
    overrides: false,
  };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    const value = () => {
      const v = argv[++i];
      if (!v) {
        console.error(`check-case-coverage: ${a} needs a value`);
        process.exit(2);
      }
      return v;
    };
    if (a === '--update') out.update = true;
    else if (a === '--selftest') out.selftest = true;
    else if (a === '--json') out.json = true;
    else if (a === '--from-git') out.fromGit = value();
    else if (a === '--data-dir') {
      out.dataDir = resolve(value());
      out.overrides = true;
    } else if (a === '--locales-dir') {
      out.localesDir = resolve(value());
      out.overrides = true;
    } else if (a === '--manifest') out.manifest = resolve(value());
    else {
      console.error(`check-case-coverage: unknown argument ${a}`);
      process.exit(2);
    }
  }
  return out;
}

/* ---------------------------------------------------------------- */
/* Sources. The same three inputs, playbooks, locale files and i18n.ts,
 * read either from directories on disk or from one commit. Everything
 * after this point works on text and does not know where it came from. */

function treeSources(opts) {
  const files = (dir, suffix) =>
    readdirSync(dir)
      .filter((f) => f.endsWith(suffix))
      .sort()
      .map((f) => ({ name: f, text: readFileSync(join(dir, f), 'utf8') }));
  return {
    playbooks: files(opts.dataDir, '.playbook.ts'),
    locales: files(opts.localesDir, '.ts'),
    i18n: readFileSync(opts.i18n, 'utf8'),
    origin: 'the working tree',
    sha: null,
  };
}

function git(args, repoRoot, extra = {}) {
  return execFileSync('git', args, { cwd: repoRoot, maxBuffer: 1024 * 1024 * 1024, ...extra });
}

/* One `git cat-file --batch` for every blob rather than a `git show` per
 * file: 264 files at a process each is ten seconds on Windows. Parsed on
 * the byte buffer, because the size in each header is in bytes. */
function catFileBatch(specs, repoRoot) {
  const buf = git(['cat-file', '--batch'], repoRoot, { input: specs.join('\n') + '\n' });
  const out = [];
  let off = 0;
  while (off < buf.length && out.length < specs.length) {
    const nl = buf.indexOf(10, off);
    const header = buf.toString('utf8', off, nl).split(' ');
    if (header[1] === 'missing') {
      out.push(null);
      off = nl + 1;
      continue;
    }
    const size = Number(header[2]);
    out.push(buf.toString('utf8', nl + 1, nl + 1 + size));
    off = nl + 1 + size + 1;
  }
  return out;
}

function gitSources(ref, repoRoot, rel = REL) {
  const sha = git(['rev-parse', '--verify', `${ref}^{commit}`], repoRoot, { encoding: 'utf8' }).trim();
  const list = (dir, suffix) =>
    git(['ls-tree', '-r', '--name-only', sha, '--', dir], repoRoot, { encoding: 'utf8' })
      .split('\n')
      .filter((p) => p.endsWith(suffix) && !p.slice(dir.length + 1).includes('/'))
      .sort();
  const playbookPaths = list(rel.data, '.playbook.ts');
  const localePaths = list(rel.locales, '.ts');
  const blobs = catFileBatch([...playbookPaths, ...localePaths, rel.i18n].map((p) => `${sha}:${p}`), repoRoot);
  const i18n = blobs[blobs.length - 1];
  if (i18n === null) throw new Error(`${rel.i18n} is not in ${ref}`);
  const named = (paths, offset) => paths.map((p, i) => ({ name: basename(p), text: blobs[offset + i] || '' }));
  return {
    playbooks: named(playbookPaths, 0),
    locales: named(localePaths, playbookPaths.length),
    i18n,
    origin: `commit ${sha.slice(0, 9)}${ref === sha ? '' : ` (${ref})`}`,
    sha,
  };
}

/* Which files the check just read differ from HEAD. Informational: the
 * check is about the disk on purpose, this line says when that is not
 * the same thing as the commit. Null when git cannot answer. */
function dirtyPaths(repoRoot, rel = REL) {
  try {
    return git(['status', '--porcelain', '--untracked-files=all', '--', rel.data, rel.locales, rel.i18n], repoRoot, {
      encoding: 'utf8',
    })
      .split('\n')
      .filter(Boolean)
      .map((l) => l.slice(3).trim())
      .sort();
  } catch {
    return null;
  }
}

/* ---------------------------------------------------------------- */

/* Every key a playbook names, plus the three catalogue keys picked out by
 * shape: the top-level title, desc and longdesc are the only keys with
 * exactly two dots, cases.<slug>.<field>, while step keys carry the step
 * id as well. */
function parsePlaybooks(files) {
  const playbooks = [];
  const byField = Object.fromEntries(KEY_FIELDS.map((f) => [f, 0]));
  for (const f of files) {
    const keys = new Set();
    const named = {};
    let m;
    KEY_REF.lastIndex = 0;
    while ((m = KEY_REF.exec(f.text)) !== null) {
      keys.add(m[2]);
      byField[m[1]]++;
      (named[m[1]] ??= []).push(m[2]);
    }
    const top = (field) => (named[field] || []).find((k) => k.split('.').length === 3) || null;
    playbooks.push({
      slug: basename(f.name, '.playbook.ts'),
      file: f.name,
      keys,
      title: top('titleKey'),
      desc: top('descKey'),
      longdesc: top('longDescKey'),
    });
  }
  return { playbooks, byField };
}

function parseLocales(files) {
  const out = new Map();
  for (const f of files) {
    const code = basename(f.name, '.ts');
    if (code === 'index' || code === 'types') continue;
    const have = new Set();
    let m;
    LOCALE_KEY.lastIndex = 0;
    while ((m = LOCALE_KEY.exec(f.text)) !== null) have.add(m[1]);
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
function offeredLanguages(src) {
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

function analyse(sources) {
  const offered = offeredLanguages(sources.i18n);
  if (!offered) throw new Error(`could not read SUPPORTED_LANGUAGES out of i18n.ts from ${sources.origin}`);
  const { playbooks, byField } = parsePlaybooks(sources.playbooks);
  const files = parseLocales(sources.locales);
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
    origin: sources.origin,
    sha: sources.sha,
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

  /* A floor with no provenance was not written by --update from a commit,
   * and the one way that happens is the way that already went wrong: a
   * file measured over a working tree and staged by hand. */
  if (!/^[0-9a-f]{40}$/.test(manifest.measured_at || '')) failures.push({ kind: 'provenance', reason: 'carries no measured_at commit' });

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
    measured_at: analysis.sha,
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
    `case coverage, measured from ${analysis.origin}: ${analysis.playbooks.length} playbooks name ` +
      `${analysis.references} keys (${fields}); ${analysis.files} locale files, ${analysis.counted.length} counted`
  );
  for (const s of analysis.skipped) console.log(`  not counted: ${s.code}, ${s.why}`);
}

function printDirty(dirty) {
  if (!dirty || !dirty.length) return;
  const shown = dirty.slice(0, 6).map((p) => basename(p));
  console.log(
    `  the working tree differs from HEAD in ${dirty.length} of the files read (${shown.join(', ')}` +
      `${dirty.length > shown.length ? ', ...' : ''}): this verdict is about the disk; --update reads the commit and cannot see them`
  );
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
      console.error(`    ${slug}  (${REL.data}/${slug}.playbook.ts)`);
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
    for (const c of p.catalogue.slice(0, 12)) console.error(`        ${c.key}  (${REL.data}/${c.file})`);
    if (p.catalogue.length > 12) console.error(`        ... and ${p.catalogue.length - 12} more`);
    console.error('');
  }
  for (const p of problems.filter((x) => x.kind === 'unrecorded')) {
    console.error(`    ${p.code} is offered in SUPPORTED_LANGUAGES and has no baseline in ${REL.manifest}.`);
    console.error(`      Record one: node ${REL.script} --update`);
    console.error('');
  }
  for (const p of problems.filter((x) => x.kind === 'nofile')) {
    console.error(`    ${p.code} is offered in SUPPORTED_LANGUAGES and has no file under ${REL.locales}.`);
    console.error('');
  }
  for (const p of problems.filter((x) => x.kind === 'provenance')) {
    console.error(`    ${REL.manifest} ${p.reason}, so its numbers were not measured by --update`);
    console.error('      from a commit in this history and describe no tree this gate guards.');
    console.error(`      Regenerate it from HEAD: node ${REL.script} --update`);
    console.error('');
  }
}

function printHowToFix() {
  console.error('  A key a playbook names and a locale does not answer renders English to');
  console.error('  every reader of that locale, and nothing on screen says so.');
  console.error('');
  console.error(`  Add the missing keys to ${REL.locales}/<code>.ts, translated from the`);
  console.error(`  *Default English beside each key in ${REL.data}/<slug>.playbook.ts.`);
  console.error('  A locale may only ever answer more. When it does, commit the translations,');
  console.error('  then record the lower numbers from that commit and commit the manifest:');
  console.error(`    node ${REL.script} --update`);
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
    measured_from: analysis.origin,
    measured_at: analysis.sha,
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
  if (args.update && args.overrides) {
    console.error('check-case-coverage: --update measures a commit; --data-dir and --locales-dir are for the check only');
    return 2;
  }

  let analysis;
  try {
    const sources = args.update || args.fromGit ? gitSources(args.fromGit || 'HEAD', REPO_ROOT) : treeSources(args);
    analysis = analyse(sources);
  } catch (err) {
    console.error(`check-case-coverage: ${err.message.split('\n')[0]}`);
    return 2;
  }
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
      console.error(`  hand in ${REL.manifest} so the decision is visible in the diff.`);
      console.error('');
      return 2;
    }
    writeManifest(args.manifest, next);
    const gaps = Object.values(next.locales).reduce((n, l) => n + Object.keys(l.gaps).length, 0);
    console.log(
      `case-coverage-manifest: measured at ${next.measured_at.slice(0, 9)}, ${Object.keys(next.locales).length} locale(s) recorded, ` +
        `${gaps} playbook gap(s), card_complete: ${next.card_complete.join(' ') || 'none'}`
    );
    if (promoted.length) console.log(`  promoted to card_complete: ${promoted.join(' ')}`);
    if (firstSeen.length) console.log(`  recorded for the first time: ${firstSeen.join(' ')}`);
    if (dropped.length) console.log(`  dropped, no longer offered or in the commit: ${dropped.join(' ')}`);
    return 0;
  }

  if (!manifest) {
    console.error(`check-case-coverage: no manifest at ${REL.manifest}. Create one with --update`);
    console.error('  (that records HEAD as it stands, which is a floor and not a certificate)');
    return 2;
  }

  if (!args.fromGit && !args.overrides) printDirty(dirtyPaths(REPO_ROOT));
  printTable(analysis, manifest);
  const { failures, tighten } = evaluate(analysis, manifest);
  /* The commit the floor names has to be in this history, or its numbers
   * describe a tree nobody can check out. Only decidable when the object
   * is here: a shallow CI checkout may not carry it, and that is not the
   * manifest's fault, so an unknown commit is noted and not failed. */
  if (manifest.measured_at && !failures.some((f) => f.kind === 'provenance')) {
    const known = (() => {
      try {
        git(['cat-file', '-e', `${manifest.measured_at}^{commit}`], REPO_ROOT, { stdio: 'ignore' });
        return true;
      } catch {
        return false;
      }
    })();
    if (!known) console.log(`  measured_at ${manifest.measured_at.slice(0, 9)} is not in this checkout, so its place in the history was not checked`);
    else {
      try {
        git(['merge-base', '--is-ancestor', manifest.measured_at, 'HEAD'], REPO_ROOT, { stdio: 'ignore' });
      } catch {
        failures.push({ kind: 'provenance', reason: `was measured at ${manifest.measured_at.slice(0, 9)}, which is not an ancestor of HEAD` });
      }
    }
  }

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
 * --update refusing to raise a number. The last case builds a real git
 * repository, changes a locale file on disk, and proves the commit-based
 * reading does not see it: that is the floor's whole guarantee. */
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
    const i18nOf = (codes) => `export const SUPPORTED_LANGUAGES = [\n${codes.map((c) => `  { code: '${c}', name: '${c}' },`).join('\n')}\n];\n`;
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
    const i18n = join(tmp, 'i18n.ts');
    writeFileSync(i18n, i18nOf(offered), 'utf8');
    const opts = { dataDir: data, localesDir: locs, i18n };
    const current = () => analyse(treeSources(opts));

    /* 1. A baseline from a tree, and the same tree against it, is green. */
    const a0 = current();
    const base = buildManifest(a0, null);
    /* Steps 1 to 6 drive the ratchet over directories, which have no commit
     * to name, so the manifest they produce carries no sha. A real one always
     * does: --update reads a commit and nothing else. Stamp one the way
     * --update would, visibly not a real hash so nobody goes looking for it,
     * and leave the provenance rule itself to steps 7 and 8, which build a
     * repository and check the sha they measured. */
    base.manifest.measured_at = '0'.repeat(40);
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
    r = evaluate(current(), base.manifest);
    const lost = r.failures.find((f) => f.kind === 'regressed' && f.code === 'xx' && f.slug === 'a');
    if (!lost || !lost.keys.includes('cases.a.step.one.what')) return fail('a lost step key was not reported by locale, playbook and key');
    if (r.failures.length !== 1) return fail(`one lost key should be one failure, got ${r.failures.length}`);
    /* ... and --update will not record it. */
    if (!buildManifest(current(), base.manifest).refused.length) return fail('--update recorded a raised number');
    write('xx', full);

    /* 3. Catalogue text lost under a stale-high floor is still caught. */
    const stale = JSON.parse(JSON.stringify(base.manifest));
    stale.locales.yy.gaps.a = 99;
    write('yy', full.filter((k) => k !== 'cases.a.step.one.why' && k !== 'cases.a.title'));
    r = evaluate(current(), stale);
    if (r.failures.some((f) => f.kind === 'regressed')) return fail('a stale-high floor should not have reported a ratchet regression');
    const cat = r.failures.find((f) => f.kind === 'catalogue' && f.code === 'yy');
    if (!cat || !cat.catalogue.some((c) => c.key === 'cases.a.title')) return fail('a lost title in a card_complete locale was not reported');
    write('yy', full.filter((k) => k !== 'cases.a.step.one.why'));

    /* 4. A case shipped without its strings regresses every counted locale. */
    writeFileSync(join(data, 'c.playbook.ts'), playbook('c', false), 'utf8');
    r = evaluate(current(), base.manifest);
    const hit = r.failures.filter((f) => f.kind === 'regressed' && f.slug === 'c').map((f) => f.code);
    if (hit.sort().join(' ') !== 'xx yy zz zz-XX') return fail(`a new case without strings should regress every counted locale, got: ${hit.join(' ')}`);
    rmSync(join(data, 'c.playbook.ts'));

    /* 5. A regional variant loses what its base loses, and nothing else. */
    write('zz', full.filter((k) => k !== 'cases.b.desc'));
    r = evaluate(current(), base.manifest);
    const regional = r.failures.filter((f) => f.kind === 'regressed').map((f) => f.code);
    if (regional.sort().join(' ') !== 'zz zz-XX') return fail(`a base losing a key should regress it and its variant, got: ${regional.join(' ')}`);
    if (!r.failures.some((f) => f.kind === 'catalogue' && f.code === 'zz')) return fail('a lost desc in a card_complete base was not reported');
    if (r.failures.some((f) => f.kind === 'catalogue' && f.code === 'zz-XX')) return fail('a regional variant must not be held to card_complete');
    write('zz', full);

    /* 6. Restored, the tree is green again, and an offered locale with no
     *    baseline is named. */
    r = evaluate(current(), base.manifest);
    if (r.failures.length) return fail('the restored tree is not green');
    writeFileSync(i18n, i18nOf([...offered, 'mm']), 'utf8');
    r = evaluate(current(), base.manifest);
    if (!r.failures.some((f) => f.kind === 'unrecorded' && f.code === 'mm')) return fail('an offered locale without a baseline was not reported');

    /* 7. The floor is read from the commit and cannot see the working tree.
     *    A real repository, the fixtures committed, then a locale file on
     *    disk loses a key: the tree reading owes it, the commit reading does
     *    not, and the commit reading names the hash it measured. */
    const repo = join(tmp, 'repo');
    const rData = join(repo, REL.data);
    const rLocs = join(repo, REL.locales);
    mkdirSync(rData, { recursive: true });
    mkdirSync(rLocs, { recursive: true });
    writeFileSync(join(rData, 'a.playbook.ts'), playbook('a', true), 'utf8');
    writeFileSync(join(rLocs, 'xx.ts'), locale(allKeys('a', true)), 'utf8');
    writeFileSync(join(rLocs, 'en.ts'), locale([]), 'utf8');
    writeFileSync(join(repo, REL.i18n), i18nOf(['en', 'xx']), 'utf8');
    const g = (...a) => git(['-c', 'user.name=selftest', '-c', 'user.email=selftest@localhost', '-c', 'commit.gpgsign=false', ...a], repo, { encoding: 'utf8' });
    g('init', '-q');
    g('add', '--', 'frontend');
    g('commit', '-q', '-m', 'fixtures');
    writeFileSync(join(rLocs, 'xx.ts'), locale(allKeys('a', true).filter((k) => k !== 'cases.a.step.one.why')), 'utf8');
    const disk = analyse(treeSources({ dataDir: rData, localesDir: rLocs, i18n: join(repo, REL.i18n) }));
    const commit = analyse(gitSources('HEAD', repo));
    if (disk.counted[0].gate.missing !== 1) return fail('the working tree reading should owe the key just removed from disk');
    if (commit.counted[0].gate.missing !== 0) return fail('the commit reading saw a change that exists only on disk');
    if (!/^[0-9a-f]{40}$/.test(commit.sha || '')) return fail('the commit reading did not record the hash it measured');
    const floor = buildManifest(commit, null).manifest;
    if (floor.measured_at !== commit.sha || floor.locales.xx.missing !== 0) return fail('the floor did not record the commit it was measured from');

    /* 8. A floor with no measured_at is refused: that is the shape a file
     *    measured over a working tree and staged by hand has. */
    if (evaluate(commit, floor).failures.length) return fail('a floor measured from the commit it is checked against is not green');
    const orphan = { ...floor };
    delete orphan.measured_at;
    if (!evaluate(commit, orphan).failures.some((f) => f.kind === 'provenance')) return fail('a floor without measured_at was accepted');
  } finally {
    rmSync(tmp, { recursive: true, force: true });
  }
  console.log(
    'selftest ok: the check fails on a lost key, a case without strings, lost catalogue text, a regional variant behind its base, ' +
      'an unrecorded locale and a floor with no measured_at; --update refuses to raise a number and reads the commit, not the disk'
  );
  return 0;
}

/* ---------------------------------------------------------------- */

const args = parseArgs(process.argv.slice(2));
process.exit(args.selftest ? selftest() : run(args));
