#!/usr/bin/env node
/* ================================================================
 * test-compose-gates.mjs
 *
 * Checks that compose-case-layers.mjs actually refuses the thing it
 * says it refuses.
 *
 * Two rules are under test.
 *
 * The first: a step override is a spine bug. One country
 * overriding a step is a country genuinely being different, and that is
 * allowed. Two countries overriding the SAME step is the spine sentence
 * being written too narrowly, and the repair is to widen it with a slot
 * rather than to keep adding copies. So the second case fails the build.
 *
 * This needs a fixture because the real family does not trip it: ES and
 * DE override nothing, which is the state we want and also the state in
 * which the gate is never exercised. A gate nobody has watched fire is
 * a gate you are trusting rather than one you have checked.
 *
 * Both directions are tested. A gate that only ever says no is as
 * useless as one that only ever says yes, so f98 (one override) must
 * pass for the same reason f99 (two overrides on one step) must fail.
 *
 * The second: two placeholders that a sentence contrasts must not resolve
 * to the same value. This one is not hypothetical. It shipped on the
 * neutral page and f97 is that page reduced to a fixture.
 *
 * Usage:
 *   node frontend/scripts/test-compose-gates.mjs
 * ================================================================ */

import { spawnSync } from 'node:child_process';
import { dirname, join, resolve } from 'node:path';
import { mkdtempSync, rmSync, readdirSync, readFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { fileURLToPath } from 'node:url';

const SCRIPT_DIR = dirname(fileURLToPath(import.meta.url));
const FRONTEND_ROOT = resolve(SCRIPT_DIR, '..');
const COMPOSER = join(SCRIPT_DIR, 'compose-case-layers.mjs');
const FIXTURES = join(FRONTEND_ROOT, 'src/features/cases/intl/__fixtures__');
const DATA = join(FRONTEND_ROOT, 'src/features/cases/data');

let failures = 0;

function check(label, condition, detail) {
  if (condition) {
    console.log(`  ok    ${label}`);
  } else {
    console.log(`  FAIL  ${label}`);
    if (detail) console.log(`        ${detail}`);
    failures++;
  }
}

function compose(family, outDir) {
  const res = spawnSync(
    process.execPath,
    [COMPOSER, '--family', family, '--intl-dir', FIXTURES, '--data-dir', outDir, '--dry-run'],
    { encoding: 'utf8' }
  );
  return { code: res.status, out: `${res.stdout || ''}${res.stderr || ''}` };
}

const scratch = mkdtempSync(join(tmpdir(), 'compose-gates-'));
try {
  console.log('compose-case-layers gates\n');

  /* ---- two countries override the same step: must fail ---- */
  const bad = compose('f99-two-overrides', scratch);
  check('two overrides on one step fails the build', bad.code !== 0, `exit was ${bad.code}`);
  check('the failure names the first country', /\bAA\b/.test(bad.out));
  check('the failure names the second country', /\bBB\b/.test(bad.out));
  check('the failure names the step', /\btwo\b/.test(bad.out));
  check('the failure says what to do about it', /widen/i.test(bad.out));

  /* ---- one country overrides, the other does not: must pass ----
   * The gate has to be capable of saying yes, or it is not measuring
   * the thing it claims to measure. */
  const good = compose('f98-one-override', scratch);
  check('a single override still composes', good.code === 0, `exit was ${good.code}\n${good.out}`);

  /* ---- two slots in one sentence resolving to one value: must fail ----
   * A different failure from an override, and the one that actually shipped.
   * The neutral progress-payment page called both the valuation and the
   * payment document an "interim application", so a spine sentence about two
   * documents composed to "raise the interim application against the approved
   * interim application". A hand-written page never says this because a person
   * reads it; a composed page says it because nobody reads every composition. */
  const collapse = compose('f97-slot-collapse', scratch);
  check('two slots resolving to one value fails the build', collapse.code !== 0, `exit was ${collapse.code}`);
  check('the collapse names the country', /\bAA\b/.test(collapse.out));
  check('the collapse names both slots', /payDoc/.test(collapse.out) && /valuationDoc/.test(collapse.out));
  check('the collapse shows the sentence it produced', /against the approved interim application/.test(collapse.out));
  check(
    'a layer with distinct values for those slots still composes',
    !/\bBB\b/.test(collapse.out),
    'BB has distinct slot values and must not be reported'
  );

  /* ---- the real family composes and shares most of its prose ---- */
  const real = spawnSync(process.execPath, [COMPOSER, '--family', 'f01-progress-payment', '--dry-run'], {
    encoding: 'utf8',
  });
  const realOut = `${real.stdout || ''}${real.stderr || ''}`;
  check('f01 composes', real.status === 0, realOut);
  check('f01 orphans no locale key', /orphaned 0/.test(realOut), realOut);
  const shared = [...realOut.matchAll(/(\d+) shared \/ (\d+) national/g)].reduce(
    (a, m) => ({ s: a.s + +m[1], n: a.n + +m[2] }),
    { s: 0, n: 0 }
  );
  check(
    'f01 shares most of its prose',
    shared.s > 0 && shared.s > shared.n * 3,
    `${shared.s} shared / ${shared.n} national`
  );
  console.log(`\n  f01 prose fields: ${shared.s} shared, ${shared.n} national`);
  /* ---- the composed English is well formed ----
   * A spine sentence is written against the country the author had in mind
   * and then filled with values from countries they never saw, so "A
   * {valuationDoc}" comes out as "A interim valuation". The composer fixes
   * the article; this is what notices if it stops. */
  const AN_OK = /^(hour|honest|honor|honour|heir)/i;
  const A_OK = /^(uni|use|usu|util|euro|ubiquit|one|once)/i;
  const badArticles = [];
  let scanned = 0;
  let pages = 0;
  for (const f of readdirSync(DATA).filter((n) => n.endsWith('.playbook.ts'))) {
    const src = readFileSync(join(DATA, f), 'utf8');
    /* Composed pages only. A hand-written page had a reader; this rule cannot
     * tell "Class A and" from an article and should not try. Found by the
     * marker, so the population grows as families are composed. */
    if (!src.includes('GENERATED. Do not edit this file by hand')) continue;
    pages++;
    /* Plain lowercase words only, for the same reason the composer restricts
     * itself to them: "an RFI" and "an fx" are correct and an initialism is
     * not something a vowel test can rule on. */
    for (const m of src.matchAll(/\b([Aa])(n?) ([a-z][a-z-]*)\b/g)) {
      const word = m[3];
      const vowel = /^[aeiou]/.test(word);
      const needsAn = (vowel && !A_OK.test(word)) || AN_OK.test(word);
      if (needsAn !== (m[2] === 'n')) badArticles.push(`${f}: "${m[0]}"`);
      scanned++;
    }
  }
  check(
    `no composed page carries a mismatched indefinite article (${scanned} articles across ${pages} composed page(s))`,
    badArticles.length === 0,
    badArticles.slice(0, 8).join('\n        ')
  );

  check('the article check actually had pages to look at', pages > 0, 'no playbook carried the generated marker');

  /* ---- the shipped playbooks still match the spine ---- */
  const drift = spawnSync(process.execPath, [COMPOSER, '--family', 'f01-progress-payment', '--check'], {
    encoding: 'utf8',
  });
  check(
    'the shipped playbooks match what the spine composes',
    drift.status === 0,
    `${drift.stdout || ''}${drift.stderr || ''}`
  );
} finally {
  rmSync(scratch, { recursive: true, force: true });
}

console.log('');
if (failures) {
  console.error(`${failures} check(s) failed`);
  process.exit(1);
}
console.log('all checks passed');
