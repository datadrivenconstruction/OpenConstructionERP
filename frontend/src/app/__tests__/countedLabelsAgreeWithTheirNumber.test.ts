import { existsSync, readFileSync, readdirSync } from 'node:fs';
import { resolve } from 'node:path';

import i18next from 'i18next';
import { describe, expect, it } from 'vitest';

/**
 * A number and the noun it counts must agree, and only i18next can make them.
 *
 * Two patterns broke that. Some screens printed the number and a separately
 * translated plural label side by side (`{n} {t('...errors_label')}`), which
 * gives "1 contrats" and "1 erreurs" in French and the wrong case for most
 * counts in Russian or Polish. Others passed `count` to a single bare key
 * whose one value was the plural, so i18next had nothing to choose from and
 * printed "1 erreurs trouvées". Both now go through keys with one form per
 * CLDR category of the language.
 *
 * This file checks the result the way a reader sees it: a real i18next
 * instance, the real locale files, and the rendered string for real counts.
 * The locale is evaluated from source rather than imported, for the reason
 * `localeKeyResolution.test.ts` gives.
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

function loadLocale(code: string): Record<string, string> {
  const src = readFileSync(resolve(LOCALES_DIR, `${code}.ts`), 'utf8');
  const start = src.indexOf('{', src.indexOf('const resource'));
  const end = src.lastIndexOf('} as ');
  return (new Function(`return ${src.slice(start, end + 1)}`)() as { translation: Record<string, string> })
    .translation;
}

/** One language on its own, with no English behind it, so a gap shows as the raw key. */
function alone(code: string) {
  const instance = i18next.createInstance();
  void instance.init({
    lng: code,
    fallbackLng: false,
    keySeparator: false,
    nsSeparator: false,
    resources: { [code]: { translation: loadLocale(code) } },
    initAsync: false,
  });
  return instance;
}

const COUNTED = [
  'contracts.register_count',
  'contracts.compliance.passed_count',
  'contracts.compliance.warnings_count',
  'contracts.compliance.errors_count',
  'contracts.completeness_passed_count',
  'contracts.completeness_warnings_count',
  'contracts.completeness_errors_count',
  'contracts.compliance.blocked_desc',
  'contracts.compliance.warnings_desc',
  'contracts.populate_skipped_currency',
  'contracts.populate_skipped_no_progress',
  'contracts.populate_skipped_unlinked',
  'contracts.populate_selected',
  'regional.positions_count',
  'regional.positions_found_count',
  'catalog.selected_count',
  'ai.items_count',
  'assemblies.library.components_count',
  'cases_for_module.steps_count',
  'boq.rs_resources_count',
  'boq.positions_count',
  'bim.requirements.warnings_count',
  'explorer.missingness_columns_count',
  'costs.import_rows_processed_count',
  'catalogues.stat_total_count',
  'match.wizard.elements_count',
  'resources.overlap_count_n',
  'propdev.escrow.transactions_count',
  'propdev.escrow.unreconciled_count',
  'boq.validation_errors',
  'boq.validation_warnings',
  'boq.validation_all_passed',
  'boq.import_preview.errors_title',
  'field_time.validation_errors',
  'field_time.validation_warnings',
  'field_time.validation_passed_count',
  'formwork.validation.errors',
  'formwork.validation.warnings',
  'schedule.quality.errors',
  'projects.health_action_fix_errors',
  'projects.health_next_fix_errors',
  'bug.errors_captured',
  'costs.import_and_more',
  'authority_submission.validation_failed',
  'validation.score_has_warnings',
  'validation.audit_findings_count',
  'bim.errors_count_title',
  'bim.warnings_count_title',
];

// Regional variants resolve through their base language and are left out.
const BASE = readdirSync(LOCALES_DIR)
  .filter((f) => f.endsWith('.ts') && !f.includes('-'))
  .map((f) => f.slice(0, -3));

// Enough numbers to land in every category any of our languages has.
const COUNTS = [0, 1, 2, 3, 5, 11, 21, 22, 100, 1.5];

describe('counted labels agree with their number', () => {
  it('French takes the singular for 0 and 1', () => {
    const fr = alone('fr');
    expect(fr.t('contracts.compliance.errors_count', { count: 0 })).toBe('0 erreur');
    expect(fr.t('contracts.compliance.errors_count', { count: 1 })).toBe('1 erreur');
    expect(fr.t('contracts.compliance.errors_count', { count: 2 })).toBe('2 erreurs');
    expect(fr.t('contracts.register_count', { count: 1 })).toBe('1 contrat');
    expect(fr.t('boq.validation_errors', { count: 1 })).toBe('1 erreur trouvée');
    expect(fr.t('boq.validation_errors', { count: 4 })).toBe('4 erreurs trouvées');
  });

  it('Russian picks the case the number governs', () => {
    const ru = alone('ru');
    expect(ru.t('contracts.compliance.errors_count', { count: 1 })).toBe('1 ошибка');
    expect(ru.t('contracts.compliance.errors_count', { count: 2 })).toBe('2 ошибки');
    expect(ru.t('contracts.compliance.errors_count', { count: 5 })).toBe('5 ошибок');
    expect(ru.t('contracts.compliance.errors_count', { count: 21 })).toBe('21 ошибка');
    expect(ru.t('contracts.register_count', { count: 3 })).toBe('3 контракта');
  });

  it('Polish separates 2-4 from 5 and up', () => {
    const pl = alone('pl');
    expect(pl.t('contracts.compliance.errors_count', { count: 1 })).toBe('1 błąd');
    expect(pl.t('contracts.compliance.errors_count', { count: 3 })).toBe('3 błędy');
    expect(pl.t('contracts.compliance.errors_count', { count: 5 })).toBe('5 błędów');
    expect(pl.t('contracts.compliance.errors_count', { count: 22 })).toBe('22 błędy');
  });

  it('German and English keep singular and plural apart', () => {
    const de = alone('de');
    expect(de.t('contracts.register_count', { count: 1 })).toBe('1 Vertrag');
    expect(de.t('contracts.register_count', { count: 3 })).toBe('3 Verträge');
    const en = alone('en');
    expect(en.t('contracts.compliance.warnings_count', { count: 1 })).toBe('1 warning');
    expect(en.t('contracts.compliance.warnings_count', { count: 7 })).toBe('7 warnings');
  });

  for (const code of BASE) {
    it(`${code}: every counted key answers every count in the language itself`, () => {
      const instance = alone(code);
      const holes: string[] = [];
      for (const key of COUNTED) {
        for (const count of COUNTS) {
          const out = instance.t(key, { count, without: 0 });
          if (out === key) holes.push(`${key} @ ${count}`);
        }
      }
      expect(holes).toEqual([]);
    });
  }

  it('the BOQ grid tooltip no longer borrows the counted summary keys', () => {
    for (const code of ['en', 'fr', 'de']) {
      const instance = alone(code);
      for (const key of ['boq.validation_tooltip_warnings', 'boq.validation_tooltip_errors']) {
        const out = instance.t(key);
        expect(out).not.toBe(key);
        expect(out).not.toContain('{{count}}');
      }
    }
  });
});
