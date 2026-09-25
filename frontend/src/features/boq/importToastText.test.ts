// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, it, expect } from 'vitest';
import { importToastText } from './importToastText';
import en from '@/app/locales/en';
import hr from '@/app/locales/hr';
import de from '@/app/locales/de';

/** A `t` that reads one locale's flat table and interpolates like i18next. */
function tFrom(table: Record<string, string>) {
  return (key: string, opts?: Record<string, unknown>) => {
    const template = table[key] ?? String(opts?.defaultValue ?? key);
    return template.replace(/{{(\w+)}}/g, (_, name: string) => String(opts?.[name] ?? ''));
  };
}

const croatianSample = {
  imported: 42,
  total_items: 49,
  method: 'direct',
  errors: [],
  warnings: [
    { code: 'summary_row_skipped' },
    { code: 'summary_row_skipped' },
    { code: 'summary_row_skipped' },
    { code: 'unit_normalised' },
  ],
};

describe('importToastText', () => {
  it('reads in the reader language and counts the left-out total lines', () => {
    const toast = importToastText(croatianSample, false, tFrom(hr.translation));
    expect(toast.title).toBe('Uvezene stavke: 42 od 49 (izravno)');
    expect(toast.message).toBe('Izostavljeni retci ukupnog iznosa, poreza ili rekapitulacije: 3');
  });

  it('has no English left in a translated locale', () => {
    const toast = importToastText({ ...croatianSample, errors: [{}, {}] }, false, tFrom(de.translation));
    expect(toast.title).toBe('Importierte Positionen: 42 von 49 (direkt)');
    expect(toast.message).toBe('Ausgelassene Summen-, Steuer- oder Zusammenstellungszeilen: 3 · Fehler: 2');
  });

  it('says nothing under the title when nothing was left out and nothing failed', () => {
    const toast = importToastText({ imported: 5, total_items: 5, method: 'direct', errors: [] }, false, tFrom(en.translation));
    expect(toast.title).toBe('Items imported: 5 of 5 (direct)');
    expect(toast.message).toBeUndefined();
  });

  it('words a GAEB import with its sections and currency and derives the total', () => {
    const toast = importToastText(
      { imported: 10, skipped: 2, errors: [], source_format: 'gaeb', sections: [{}, {}], currency: 'EUR' },
      true,
      tFrom(en.translation),
    );
    expect(toast.title).toBe('Items imported: 10 of 12 (GAEB XML, sections: 2, EUR)');
  });

  it('names the model of an AI import, and falls back to the translated AI label', () => {
    const t = tFrom(hr.translation);
    expect(importToastText({ imported: 1, errors: [], method: 'ai', model_used: 'm1' }, false, t).title).toContain('(UI: m1)');
    expect(importToastText({ imported: 1, errors: [], method: 'ai', model_used: null }, false, t).title).toContain('(UI)');
  });
});
