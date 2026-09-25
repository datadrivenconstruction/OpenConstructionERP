import { existsSync, readFileSync, readdirSync } from 'node:fs';
import { resolve } from 'node:path';

import { describe, expect, it } from 'vitest';

/**
 * Every module explainer ends with two link rows: `<module>.flow_pulls`
 * ("Pulls from:", the modules upstream of this one) and `<module>.flow_feeds`
 * ("Feeds:", the modules downstream). The English is a verb in both, and the
 * direction is the whole content of the label.
 *
 * Translated one key at a time, the fifteen copies of "Feeds:" drifted apart,
 * and several landed on the opposite direction: French "Se nourrit de" (is fed
 * by), Estonian "Sisendid" (inputs), Chinese "来自" (comes from), Filipino
 * "Kumukuha mula sa" (takes from), or on the noun "feeds" as in animal fodder.
 * A reader following the row walked the flow backwards. The fix gave each
 * locale one wording per direction, so the rule this file holds is simple:
 * within a locale, every flow_feeds says the same thing, every flow_pulls says
 * the same thing, and the two are never the same text.
 *
 * `field.flow_feeds` ("Feeds the office:") is a different sentence and is
 * excluded.
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

const FILES = readdirSync(LOCALES_DIR).filter((f) => f.endsWith('.ts') && !f.startsWith('en'));

describe('module flow rows keep their direction', () => {
  it('finds the locale files', () => {
    expect(FILES.length).toBeGreaterThan(30);
  });

  for (const file of FILES) {
    it(`${file}: one wording per direction, and the two differ`, () => {
      const pairs = readPairs(file);
      const feeds = new Set<string>();
      const pulls = new Set<string>();
      for (const [key, value] of pairs) {
        if (key.endsWith('.flow_feeds') && key !== 'field.flow_feeds') feeds.add(value);
        if (key.endsWith('.flow_pulls')) pulls.add(value);
      }
      expect([...feeds], 'every flow_feeds reads the same').toHaveLength(feeds.size ? 1 : 0);
      expect([...pulls], 'every flow_pulls reads the same').toHaveLength(pulls.size ? 1 : 0);
      if (feeds.size && pulls.size) {
        expect([...feeds][0]).not.toBe([...pulls][0]);
      }
    });
  }
});

describe('French contract vocabulary', () => {
  const fr = readPairs('fr.ts');

  it('says the contract feeds the next module rather than being fed by it', () => {
    expect(fr.get('contracts.flow_feeds')).toBe('Alimente :');
    expect(fr.get('contracts.flow_pulls')).toBe('Tire de :');
  });

  it('names a progress claim "situation de travaux", never "demande d\'acompte"', () => {
    const offenders = [...fr].filter(([, v]) => /demandes? d'acompte/i.test(v)).map(([k]) => k);
    expect(offenders).toEqual([]);
  });

  it('labels retention amounts with the noun "Retenue"', () => {
    const keys = [
      'contracts.held',
      'procurement.retainage_held',
      'procurement.retainage_withheld',
      'finance.claimInvoice.retained',
      'finance.payment.retained',
      'finance.payment.withholding',
      'finance.retention_held_to_date',
      'finance.retention_col_held',
      'cvr.rollup_retention',
    ];
    for (const key of keys) {
      expect(fr.get(key), key).toMatch(/^Retenue\b/);
    }
    // Retention withheld from a payment is not a tax withholding.
    expect(fr.get('finance.payment.withholding')).not.toMatch(/à la source/);
  });
});
