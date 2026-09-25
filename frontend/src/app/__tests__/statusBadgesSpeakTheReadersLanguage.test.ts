import { existsSync, readFileSync, readdirSync } from 'node:fs';
import { resolve } from 'node:path';

import { describe, expect, it } from 'vitest';

/**
 * Status badges across the registers (contracts, claims, submittals, work
 * orders, plots, damage reports, connector runs and the rest) printed the raw
 * backend enum or an English label map in every language, so a French user
 * read "Draft", "Active" and "Paid" on an otherwise French page. Each badge now
 * goes through a key per status value, built from a template such as
 * `contracts.claim_status_${status}`.
 *
 * A template key is only as good as its members: a member missing from a
 * locale falls back to English, which is exactly the bug. So this file holds
 * two rules for the families the badges read. Every member English defines is
 * present in every base locale, and in the languages we check by eye the value
 * is not the English word left in place.
 */

const RESOLVED = ['src/app/locales', 'frontend/src/app/locales']
  .map((p) => resolve(process.cwd(), p))
  .find(existsSync);
if (!RESOLVED) {
  throw new Error(
    'no locale directory at src/app/locales or frontend/src/app/locales: run this from frontend or from the repository root',
  );
}
const LOCALES_DIR = RESOLVED;

const PAIR = /^\s*"((?:[^"\\]|\\.)*)"\s*:\s*"((?:[^"\\]|\\.)*)"\s*,?\s*$/;

function readPairs(file: string): Map<string, string> {
  const out = new Map<string, string>();
  for (const line of readFileSync(resolve(LOCALES_DIR, file), 'utf-8').split(/\r?\n/)) {
    const m = PAIR.exec(line);
    if (m) out.set(m[1]!, m[2]!);
  }
  return out;
}

const FAMILIES = [
  'contracts.status_',
  'contracts.claim_status_',
  'contracts.milestone_status_',
  'projects.status.',
  'submittals.status_',
  'qms.status.',
  'qms.action_status.',
  'bid_management.status_',
  'bid_management.inv_status_',
  'interface_management.status_',
  'interface_management.action_status_',
  'meetings.action_status_',
  'signing.signer_state_',
  'source_data.status_',
  'source_data.checklist_status_',
  'review_authority.remark_status_',
  'authority_submission.status_',
  'files.status.state.',
  'copilot.audit.status.',
  'rulePacks.test_mode_status_',
  'buyer_portal.status.',
  'service.wo_status_',
  'service.contract_status_',
  'service.asset_status_',
  'equipment.damage.severity_',
  'equipment.damage.status_',
  'finance.connectors.log_status_',
  'propdev.plot.status.',
  'propdev.instalment.status.',
  'propdev.selection.status.',
];

// Regional variants (en-GB, es-MX, pt-BR, ...) resolve through their base
// language, so they are not required to carry the members themselves.
const BASE_FILES = readdirSync(LOCALES_DIR).filter(
  (f) => f.endsWith('.ts') && f !== 'en.ts' && !f.includes('-'),
);

const en = readPairs('en.ts');
const members = [...en.keys()].filter((k) => FAMILIES.some((p) => k.startsWith(p)));

describe('status badges are translated', () => {
  it('every family has members in en.ts', () => {
    for (const family of FAMILIES) {
      expect(members.some((k) => k.startsWith(family)), family).toBe(true);
    }
  });

  for (const file of BASE_FILES) {
    it(`${file}: answers every status member`, () => {
      const pairs = readPairs(file);
      expect(members.filter((k) => !pairs.has(k))).toEqual([]);
    });
  }

  for (const file of ['fr.ts', 'de.ts', 'ru.ts', 'es.ts', 'it.ts', 'pl.ts']) {
    it(`${file}: no status member is the English word left in place`, () => {
      const pairs = readPairs(file);
      expect(members.filter((k) => pairs.get(k) === en.get(k))).toEqual([]);
    });
  }
});
