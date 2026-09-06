#!/usr/bin/env node
/* ================================================================
 * check-case-translation-drift.mjs
 *
 * Finds case strings whose English has been rewritten since the
 * locales were translated against it.
 *
 * WHY THIS EXISTS
 *
 * The case pipeline localizes by key. A page's English default lives in
 * the playbook, the translation lives in frontend/src/app/locales/<code>.ts
 * under the same key, and generate-cases.mjs swaps one for the other.
 * That works, and it has exactly one hole: nothing compares the English
 * a translation was made from against the English that is on the page
 * now. Reword a sentence and keep its key, and every locale keeps
 * serving the translation of the sentence you deleted. The key resolves,
 * so the "fallbacks to English (missing locale keys)" report stays
 * silent. Nothing is missing. Something is wrong.
 *
 * This was found by composing three progress-payment pages from a
 * shared spine and then reading the German output: the English title
 * had become "Issue the invoice against the approved figure" while the
 * German still read "Rechnen Sie die genehmigte Zahl ab, nicht Ihre
 * eigene", which is the previous English sentence, faithfully
 * translated, and now describing nothing. Four locales are complete at
 * ~2900 keys, so the blast radius of an unnoticed reword is four
 * published languages per string.
 *
 * HOW IT WORKS
 *
 * A manifest records a hash of the English of every case string at the
 * moment the locales were known to be in step with it. On each run the
 * current English is hashed again and compared. A changed hash means
 * every locale holding that key is now serving a translation of older
 * English and needs a fresh one.
 *
 * The manifest is the record of a promise, so refresh it only when the
 * translations have actually been redone. `--update` is the act of
 * saying "these are translated now", not a way to make the check quiet.
 *
 * What it cannot see: whatever was already stale when the baseline was
 * taken. The first manifest was hashed from the tree as it stood, and a
 * tree records what the English is, not whether the translations were
 * made from it. So a page that was already out of step got recorded as
 * healthy and will never be reported. The count here is a floor on the
 * stale translations in the repo, not a total, and it becomes a real
 * total only for pages whose baseline was set at a moment somebody had
 * actually verified.
 *
 * Usage:
 *   node frontend/scripts/check-case-translation-drift.mjs
 *   node frontend/scripts/check-case-translation-drift.mjs --update
 *   node frontend/scripts/check-case-translation-drift.mjs --slug a,b
 *   node frontend/scripts/check-case-translation-drift.mjs --from-git HEAD
 *
 *   --ratchet         tolerate the keys recorded as owed, fail on any
 *                     other drifted key. This is the blocking form: the
 *                     existing debt does not go green, but nobody adds
 *                     to it silently.
 *   --owe             record the currently drifted keys as owed. Taking
 *                     on debt deliberately, not clearing it.
 *   --from-git <ref>  hash the English as it exists at that git ref
 *                     instead of on disk, to answer "what did my
 *                     working tree just invalidate".
 * ================================================================ */

import { readdirSync, readFileSync, writeFileSync, existsSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { execFileSync } from 'node:child_process';
import { dirname, join, resolve, basename } from 'node:path';
import { fileURLToPath } from 'node:url';

const SCRIPT_DIR = dirname(fileURLToPath(import.meta.url));
const FRONTEND_ROOT = resolve(SCRIPT_DIR, '..');
const REPO_ROOT = resolve(FRONTEND_ROOT, '..');
const DATA_DIR = join(FRONTEND_ROOT, 'src/features/cases/data');
const LOCALE_DIR = join(FRONTEND_ROOT, 'src/app/locales');
const MANIFEST = join(FRONTEND_ROOT, 'src/features/cases/case-en-manifest.json');

const REL_DATA = 'frontend/src/features/cases/data';

/* ---------------------------------------------------------------- */

function parseArgs(argv) {
  const out = { update: false, slugs: null, fromGit: null, quiet: false, ratchet: false, owe: false, force: false };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === '--update') out.update = true;
    else if (a === '--ratchet') out.ratchet = true;
    else if (a === '--owe') out.owe = true;
    else if (a === '--force') out.force = true;
    else if (a === '--quiet') out.quiet = true;
    else if (a === '--slug') out.slugs = new Set(argv[++i].split(','));
    else if (a === '--from-git') out.fromGit = argv[++i];
    else {
      console.error(`check-case-translation-drift: unknown argument ${a}`);
      process.exit(2);
    }
  }
  return out;
}

function sha(text) {
  return createHash('sha256').update(text, 'utf8').digest('hex').slice(0, 16);
}

/* Pull key -> English out of a playbook source. Every translatable
 * string in a playbook sits next to its key in one of three shapes:
 *   xKey: "cases.a.b",  xDefault: "English"        (title/desc/what/why)
 *   xKey: "cases.a.b",\n    xDefault:\n "English"  (wrapped long ones)
 *   labelKey: "cases.a.b.in.x", label: "English"   (chips)
 * so one pass over the source with both spellings picks them all up. */
function stringsOf(src) {
  const found = {};
  const patterns = [
    /(\w*[Kk]ey):\s*"(cases\.[A-Za-z0-9_.]+)",\s*\n?\s*(?:\w*Default|label):\s*\n?\s*"((?:[^"\\]|\\.)*)"/g,
    /label[Kk]ey:\s*"(cases\.[A-Za-z0-9_.]+)",\s*label:\s*"((?:[^"\\]|\\.)*)"/g,
  ];
  let m;
  patterns[0].lastIndex = 0;
  while ((m = patterns[0].exec(src)) !== null) found[m[2]] = JSON.parse(`"${m[3]}"`);
  patterns[1].lastIndex = 0;
  while ((m = patterns[1].exec(src)) !== null) found[m[1]] = JSON.parse(`"${m[2]}"`);
  return found;
}

function playbookSources(args) {
  const files = readdirSync(DATA_DIR)
    .filter((f) => f.endsWith('.playbook.ts'))
    .sort();
  const out = {};
  for (const f of files) {
    const slug = basename(f, '.playbook.ts');
    if (args.slugs && !args.slugs.has(slug)) continue;
    if (args.fromGit) {
      try {
        out[slug] = execFileSync('git', ['show', `${args.fromGit}:${REL_DATA}/${f}`], {
          cwd: REPO_ROOT,
          encoding: 'utf8',
          maxBuffer: 64 * 1024 * 1024,
        });
      } catch {
        /* a page that does not exist at that ref simply has no baseline */
      }
    } else {
      out[slug] = readFileSync(join(DATA_DIR, f), 'utf8');
    }
  }
  return out;
}

/* Which locales actually carry a given key. A key nobody has translated
 * cannot have gone stale, and counting it as drift would make the number
 * meaningless. */
/* Which languages the product actually offers. A locale file can exist for a
 * language that is not in SUPPORTED_LANGUAGES, in which case nobody can select
 * it and nobody is reading a stale translation in it. Parsed from the `code:`
 * field only: the entries also carry name, flag and country, and scraping
 * every quoted string reports 114 languages instead of 42. */
function offeredLanguages() {
  const src = readFileSync(join(FRONTEND_ROOT, 'src/app/i18n.ts'), 'utf8');
  const start = src.indexOf('export const SUPPORTED_LANGUAGES');
  if (start < 0) return null;
  const end = src.indexOf('\n];', start);
  const block = src.slice(start, end < 0 ? undefined : end);
  const codes = [...block.matchAll(/\bcode:\s*'([A-Za-z-]+)'/g)].map((m) => m[1]);
  return codes.length ? new Set(codes) : null;
}

function localeIndex() {
  const files = readdirSync(LOCALE_DIR).filter((f) => f.endsWith('.ts'));
  const index = new Map();
  for (const f of files) {
    const code = basename(f, '.ts');
    if (code === 'en' || code === 'en-US' || code === 'index' || code === 'types') continue;
    const src = readFileSync(join(LOCALE_DIR, f), 'utf8');
    const re = /"(cases\.[A-Za-z0-9_.]+)":/g;
    let m;
    while ((m = re.exec(src)) !== null) {
      if (!index.has(m[1])) index.set(m[1], []);
      index.get(m[1]).push(code);
    }
  }
  return index;
}

/* ---------------------------------------------------------------- */

function main() {
  const args = parseArgs(process.argv.slice(2));
  const sources = playbookSources(args);

  const current = {};
  for (const src of Object.values(sources)) {
    for (const [key, english] of Object.entries(stringsOf(src))) current[key] = sha(english);
  }

  if (args.update) {
    const prior = existsSync(MANIFEST) ? JSON.parse(readFileSync(MANIFEST, 'utf8')) : { keys: {} };

    /* An owed key is a key whose translations are known NOT to have been
     * redone. Refreshing its hash records the opposite, the ratchet goes
     * green, and nothing anywhere says the debt was dropped. Easy to do by
     * accident: someone baselining their own new pages runs --update
     * unscoped and takes every other page's debt with it. */
    const owed = new Set((prior.owed || {}).keys || []);
    const wouldClear = Object.keys(current).filter((k) => owed.has(k) && prior.keys[k] !== current[k]);
    if (wouldClear.length && !args.force) {
      console.error('');
      console.error(`  --update would refresh ${wouldClear.length} key(s) recorded as OWED.`);
      console.error('  That records "these are translated now" about translations that have');
      console.error('  not been redone, and the drift ratchet would go green on its own.');
      console.error('');
      for (const k of wouldClear.slice(0, 8)) console.error(`    ${k}`);
      if (wouldClear.length > 8) console.error(`    ... and ${wouldClear.length - 8} more`);
      console.error('');
      console.error('  If you are baselining your OWN new pages, scope it and this goes away:');
      console.error('    --update --slug <your-slug>[,<another>]');
      console.error('');
      console.error('  If the translations really were redone, say so explicitly with --force,');
      console.error('  and drop the repaid keys from the owed list with --owe.');
      console.error('');
      process.exit(2);
    }

    const merged = { ...prior.keys, ...current };
    writeFileSync(
      MANIFEST,
      JSON.stringify(
        {
          owed: prior.owed,
          note:
            'Hash of the English of every case string, recorded so that a later reword can be seen. ' +
            'A key whose hash has moved is a key every locale holding it is serving stale for. ' +
            'Refresh this only when those translations have actually been redone. ' +
            'This is a starting line and not a certificate: the first baseline was taken from the ' +
            'tree as it stood, which records what the English was and not whether anyone had ' +
            'translated that version of it. A page already out of step when it was baselined was ' +
            'recorded as healthy and stays invisible here, so what this check reports is a floor.',
          updated: new Date().toISOString().slice(0, 10),
          keys: merged,
        },
        null,
        2
      ) + '\n',
      'utf8'
    );
    console.log(`case-en-manifest: ${Object.keys(merged).length} keys recorded`);
    return;
  }

  if (!existsSync(MANIFEST)) {
    console.error('check-case-translation-drift: no manifest yet. Create one with --update');
    console.error('  (do that only from a tree whose translations are known to be in step)');
    process.exit(2);
  }

  const manifest = JSON.parse(readFileSync(MANIFEST, 'utf8')).keys;
  const translated = localeIndex();

  const drifted = [];
  let untranslated = 0;
  for (const [key, hash] of Object.entries(current)) {
    if (!(key in manifest)) continue;
    if (manifest[key] === hash) continue;
    const locales = translated.get(key) || [];
    if (!locales.length) {
      untranslated++;
      continue;
    }
    drifted.push({ key, locales });
  }

  if (!drifted.length) {
    console.log(`case translation drift: none (${Object.keys(current).length} English strings checked)`);
    if (untranslated) console.log(`  ${untranslated} reworded string(s) are not translated anywhere yet, so nothing went stale`);
    return;
  }

  const offered = offeredLanguages();
  const isOffered = (code) => !offered || offered.has(code);

  const affected = new Set();
  const affectedOffered = new Set();
  let restrings = 0;
  let restringsOffered = 0;
  for (const d of drifted) {
    for (const l of d.locales) {
      affected.add(l);
      restrings++;
      if (isOffered(l)) {
        affectedOffered.add(l);
        restringsOffered++;
      }
    }
  }
  const unofferedHit = [...affected].filter((l) => !isOffered(l)).sort();

  /* Write down what is owed, so the check can block a NEW reword today
   * without pretending the existing debt is paid. */
  if (args.owe) {
    const prior = JSON.parse(readFileSync(MANIFEST, 'utf8'));
    prior.owed = {
      note:
        'Keys whose English was rewritten and whose translations have not been redone yet. ' +
        'These are tolerated by --ratchet and reported on every run. A drifted key that is NOT ' +
        'listed here fails the build. Remove a key from this list when its translations are ' +
        'actually redone, and refresh its hash with --update at the same time. This list only ' +
        'ever shrinks.',
      recorded: new Date().toISOString().slice(0, 10),
      keys: drifted.map((d) => d.key).sort(),
    };
    writeFileSync(MANIFEST, JSON.stringify(prior, null, 2) + '\n', 'utf8');
    console.log(`case-en-manifest: ${drifted.length} key(s) recorded as owed`);
    return;
  }

  /* The ratchet. An owed key is a debt somebody already knows about. Anything
   * else is a reword made today, and that is the thing nothing else catches. */
  if (args.ratchet) {
    const owed = new Set((JSON.parse(readFileSync(MANIFEST, 'utf8')).owed || {}).keys || []);
    const fresh = drifted.filter((d) => !owed.has(d.key));
    const repaid = [...owed].filter((k) => !drifted.some((d) => d.key === k));
    console.log(
      `case translation drift: ${drifted.length} drifted, ${owed.size} of them already owed` +
        (repaid.length ? `, ${repaid.length} repaid` : '')
    );
    if (!fresh.length) {
      if (repaid.length) console.log('  repaid keys can be dropped from the owed list with --owe');
      return;
    }
    console.error('');
    console.error('  ================================================================');
    console.error('  NEW STALE TRANSLATIONS. English was rewritten under an existing key.');
    console.error('  ================================================================');
    console.error('');
    console.error(`    newly reworded : ${fresh.length}`);
    console.error(`    already owed   : ${owed.size} (not counted against you)`);
    console.error('');
    for (const d of fresh.slice(0, 20)) console.error(`    ${d.key}  [${d.locales.length} locale(s)]`);
    console.error('');
    console.error('  These keys resolve, so nothing else reports them and the pages');
    console.error('  publish looking correct in every language while carrying a');
    console.error('  translation of a sentence that no longer exists.');
    console.error('');
    console.error('  Retranslate them and record it with --update, or if you are');
    console.error('  deliberately taking on the debt, add them with --owe and say so.');
    console.error('');
    process.exit(1);
  }

  console.error('');
  console.error('  ================================================================');
  console.error('  STALE TRANSLATIONS. English was rewritten under an existing key.');
  console.error('  ================================================================');
  console.error('');
  console.error(`    English strings reworded : ${drifted.length}`);
  console.error(`    offered languages hit    : ${affectedOffered.size} (${[...affectedOffered].sort().join(' ')})`);
  console.error(`    translations to redo     : ${restringsOffered} in languages a reader can select`);
  if (unofferedHit.length) {
    console.error(`    plus                     : ${restrings - restringsOffered} in ${unofferedHit.join(', ')}, ` +
      `which have locale files but are not in SUPPORTED_LANGUAGES`);
    console.error(`    total                    : ${restrings}`);
  }
  console.error('');
  if (!args.quiet) {
    for (const d of drifted.slice(0, 40)) {
      console.error(`    ${d.key}  [${d.locales.length} locale(s)]`);
    }
    if (drifted.length > 40) console.error(`    ... and ${drifted.length - 40} more`);
    console.error('');
  }
  console.error('  These keys resolve, so the localizer reports nothing and the');
  console.error('  pages publish looking correct in every language. What they');
  console.error('  carry is a faithful translation of a sentence that no longer');
  console.error('  exists in English.');
  console.error('');
  console.error('  Retranslate them, then record that with --update.');
  console.error('');
  process.exit(1);
}

main();
