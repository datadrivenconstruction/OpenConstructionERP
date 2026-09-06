/* ================================================================
 * caseTranslationDrift.test.ts
 *
 * Blocks the hole where English is reworded under an existing key and
 * every locale keeps serving a translation of the deleted sentence.
 *
 * WHY NOTHING ELSE CATCHES IT
 *
 * The case pipeline localizes by key. Reword the English and keep the
 * key, and the key still resolves, so the localizer's "fallbacks to
 * English" report stays silent: nothing fell back, nothing is missing.
 * The page publishes looking correct in every language while saying
 * something the English no longer says. Found by composing three
 * progress-payment pages from a shared spine and reading the German:
 * English had become "Measure the period bill item by bill item" while
 * German still served "Die bisher erbrachte Leistung aufmessen", the
 * previous sentence, translated faithfully, describing nothing.
 *
 * WHY IT IS A RATCHET AND NOT A PLAIN GATE
 *
 * 53 strings are genuinely drifted right now and owed roughly 1126
 * retranslations. A plain gate would go red today and stay red until
 * that work lands, which makes it something people learn to ignore.
 * Baselining it quiet with --update would be worse: that records "these
 * are translated now" about translations nobody has done.
 *
 * So the owed keys are listed explicitly in the manifest and tolerated,
 * and any OTHER drifted key fails. Somebody rewording English under an
 * existing key today is stopped today, which is the actual hole. The
 * list is keys rather than a count, so repaying one key while breaking
 * another does not net out to silence. When the debt reaches zero this
 * and a plain gate are the same thing.
 * ================================================================ */

import { describe, expect, it } from 'vitest';
import { spawnSync } from 'node:child_process';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const FRONTEND_ROOT = resolve(HERE, '../../..');
const CHECK = join(FRONTEND_ROOT, 'scripts/check-case-translation-drift.mjs');

describe('case translation drift', () => {
  it('no English string was reworded under a key without redoing its translations', () => {
    const run = spawnSync(process.execPath, [CHECK, '--ratchet'], { encoding: 'utf8' });
    const output = `${run.stdout || ''}${run.stderr || ''}`;

    /* The whole report, not the exit code alone: it names the keys and how
     * many locales each one leaves stranded, which is what the next person
     * needs in order to act. */
    expect(output, output).not.toContain('NEW STALE TRANSLATIONS');
    expect(run.status, output).toBe(0);
  }, 60_000);
});
