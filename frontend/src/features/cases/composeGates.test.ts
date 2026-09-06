/* ================================================================
 * composeGates.test.ts
 *
 * Runs the case-composition gates inside vitest, so they block.
 *
 * The gates themselves live in frontend/scripts/test-compose-gates.mjs
 * and are a plain node script, which means they fail only when a person
 * remembers to type the command. That is a check, not a gate. vitest
 * already globs src/**\/*.test.{ts,tsx}, so the cheapest way to make the
 * rules enforceable is to be a test file that runs them.
 *
 * Kept as a thin wrapper rather than a reimplementation. Two copies of
 * the same rules drift apart, and the copy that stops matching is
 * always the one nobody is watching.
 *
 * What is enforced:
 *   - two countries overriding the same spine step fails the build
 *   - two slots a sentence contrasts must not resolve to one value
 *   - composed prose carries no mismatched indefinite article
 *   - the committed playbooks are still what the spine composes
 * ================================================================ */

import { describe, expect, it } from 'vitest';
import { spawnSync } from 'node:child_process';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const FRONTEND_ROOT = resolve(HERE, '../../..');
const GATES = join(FRONTEND_ROOT, 'scripts/test-compose-gates.mjs');

describe('case composition gates', () => {
  it('composes every family and refuses what it says it refuses', () => {
    const run = spawnSync(process.execPath, [GATES], { encoding: 'utf8' });
    const output = `${run.stdout || ''}${run.stderr || ''}`;

    /* The whole report on failure, not just the exit code. A gate that
     * says only "exit 1" makes the next person rerun it by hand to find
     * out what broke, which is the habit this file exists to remove. */
    expect(output, output).toContain('all checks passed');
    expect(run.status, output).toBe(0);
  }, 60_000);
});
