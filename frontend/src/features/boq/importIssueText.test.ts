// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, it, expect } from 'vitest';
import { importIssueText } from './importIssueText';
import hr from '@/app/locales/hr';
import hu from '@/app/locales/hu';

/** A `t` that reads one locale's flat table and interpolates like i18next. */
function tFrom(table: Record<string, string>) {
  return (key: string, opts?: Record<string, unknown>) => {
    const template = table[key] ?? String(opts?.defaultValue ?? key);
    return template.replace(/{{(\w+)}}/g, (_, name: string) => String(opts?.[name] ?? ''));
  };
}

describe('importIssueText', () => {
  it('words a skipped total line in the reader language, with the row once', () => {
    const text = importIssueText(
      {
        row: 58,
        code: 'summary_row_skipped',
        label: 'UKUPNO (bez PDV-a)',
        message: "'UKUPNO (bez PDV-a)' reads as a subtotal line and was not imported as a position.",
      },
      tFrom(hr.translation),
    );
    expect(text).toBe('Red 58: UKUPNO (bez PDV-a): redak ukupnog iznosa, poreza ili rekapitulacije, nije uvezen kao stavka');
    expect(text).not.toContain('reads as');
  });

  it('keeps the server message for any other issue', () => {
    const text = importIssueText({ row: 4, message: 'Quantity is zero' }, tFrom({}));
    expect(text).toBe('Row 4: Quantity is zero');
  });

  it('reads a parse error, which the importer words under `error`', () => {
    expect(importIssueText({ row: 9, error: 'Invalid quantity at row 9' }, tFrom({}))).toBe(
      'Row 9: Invalid quantity at row 9',
    );
  });

  it('prints no row prefix when the issue has no row', () => {
    expect(importIssueText({ message: 'Unit rate is zero' }, tFrom({}))).toBe('Unit rate is zero');
  });

  it('names the sheet with the row when a workbook was read across sheets', () => {
    const text = importIssueText(
      {
        row: 12,
        sheet: 'Épületgépészet',
        code: 'summary_row_skipped',
        label: 'Épületgépészet összesen:',
        message: "'Épületgépészet összesen:' reads as a subtotal line and was not imported as a position.",
      },
      tFrom(hu.translation),
    );
    expect(text).toBe(
      'Épületgépészet munkalap, 12. sor: Épületgépészet összesen:: összeg-, adó- vagy összesítő sor, tételként nem lett importálva',
    );
  });

  it('says in Hungarian which sheet was not read and why', () => {
    const t = tFrom(hu.translation);
    const english = "Sheet 'Főösszesítő' was not read: its header names no description with a quantity, unit or rate.";
    expect(
      importIssueText({ code: 'sheet_not_read', sheet: 'Főösszesítő', reason: 'no_item_header', message: english }, t),
    ).toBe(
      'A(z) Főösszesítő munkalap nem lett beolvasva: nincs olyan fejléce, amely tételszöveget és mennyiséget, mértékegységet vagy egységárat nevez meg',
    );
    expect(importIssueText({ code: 'sheet_not_read', sheet: 'Segéd', reason: 'hidden' }, t)).toBe(
      'A(z) Segéd munkalap nem lett beolvasva: rejtett',
    );
    expect(
      importIssueText({ code: 'sheet_not_read', sheet: 'Építészet (2)', reason: 'duplicate', of: 'Építészet' }, t),
    ).toBe('A(z) Építészet (2) munkalap nem lett beolvasva: a(z) Építészet munkalap tételeit ismétli');
  });

  it('reports a number read with dot thousands with the text as typed and the value it became', () => {
    const text = importIssueText(
      { row: 3, code: 'dot_read_as_thousands', text: '12.500', value: 12500, message: 'x' },
      tFrom(hu.translation),
      (v) => v.toLocaleString('hu-HU'),
    );
    expect(text).toBe('3. sor: A(z) 12.500 értéket 12 500 számként olvastuk be: a pont itt ezres elválasztó');
  });

  it('lists the headings it could not read when the header names no bill columns', () => {
    const text = importIssueText(
      {
        code: 'header_not_recognised',
        sheet: 'Költségvetés',
        missing: ['description'],
        unrecognised: ['Sor', 'Munka', 'Darab'],
        error: 'The header row does not name a description column.',
      },
      tFrom(hu.translation),
    );
    expect(text).toBe(
      'Költségvetés munkalap: A fejlécsorban nincs tételszöveg-oszlop. Fel nem ismert oszlopfejlécek: Sor, Munka, Darab',
    );
  });

  it('falls back to English wording for a language without the keys', () => {
    const text = importIssueText(
      { code: 'header_not_recognised', missing: ['description', 'quantity_or_rate'], unrecognised: [] },
      tFrom({}),
    );
    expect(text).toBe('The header row names no description column and no quantity, unit or rate column');
  });
});
