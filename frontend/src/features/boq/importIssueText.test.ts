// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, it, expect } from 'vitest';
import { importIssueText } from './importIssueText';
import hr from '@/app/locales/hr';
import hu from '@/app/locales/hu';
import en from '@/app/locales/en';

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

describe('importIssueText for a column mapping the import could not use', () => {
  it('names the sheet and the reason in the reader language', () => {
    const text = importIssueText(
      {
        code: 'column_mapping_not_applied',
        reason: 'different_header',
        sheet: 'Villamos',
        message: 'Sheet Villamos: The column mapping was not used on this sheet: its header differs from the first one.',
      },
      tFrom(hu.translation),
    );
    expect(text).toContain('Villamos');
    expect(text).toContain(hu.translation['boq.import_issue.mapping_different_header']);
    expect(text).not.toContain('was not used');
  });

  it('words each reason differently', () => {
    const texts = ['profile', 'format', 'different_header'].map((reason) =>
      importIssueText({ code: 'column_mapping_not_applied', reason }, tFrom({})),
    );
    expect(new Set(texts).size).toBe(3);
  });

  describe('XPWE notes', () => {
    const t = tFrom(en.translation);

    it('names the bill item by its ordinal and words the numbers in the reader locale', () => {
      const text = importIssueText(
        {
          code: 'xpwe_quantity_mismatch',
          ordinal: '1.1.1',
          computed: 49.11,
          declared: 50,
          message: 'Item 1.1.1: the measurement rows add up to 49.11, the file states 50. ...',
        },
        t,
        (value) => value.toFixed(2).replace('.', ','),
      );
      expect(text).toBe(
        'Item 1.1.1: The measurement rows add up to 49,11, the file states 50,00. The measured quantity was imported',
      );
    });

    it('has an en.ts wording for every code the importer sends', () => {
      const codes = [
        'xpwe_quantity_mismatch',
        'xpwe_see_item_flattened',
        'xpwe_see_item_unresolved',
        'xpwe_expression_unreadable',
        'xpwe_price_unreadable',
        'xpwe_description_truncated',
        'xpwe_encoding_fallback',
        'xpwe_no_bill_items',
        'xpwe_more_warnings',
        'xpwe_price_item_missing',
        'xpwe_signs_cancel',
      ];
      for (const code of codes) {
        expect(en.translation[`boq.import_issue.${code}`], code).toBeTruthy();
        const text = importIssueText(
          { code, ordinal: '2.1', ref: '7', value: 12, computed: 1, declared: 2, text: '2x', count: 3, encoding: 'cp1252', message: 'SERVER' },
          t,
        );
        expect(text, code).not.toContain('SERVER');
      }
    });

    it('says how many lines went into the deductions line and how much they take off', () => {
      expect(en.translation['boq.import_issue.xpwe_deductions_moved_one']).toBeTruthy();
      expect(en.translation['boq.import_issue.xpwe_deductions_moved_other']).toBeTruthy();
      const text = importIssueText(
        { code: 'xpwe_deductions_moved', count: 2, amount: -236.3, message: 'SERVER' },
        t,
        (value) => value.toFixed(2),
      );
      expect(text).toContain('2 items');
      expect(text).toContain('236.30');
      expect(text).not.toContain('-236.30');
      expect(text).not.toContain('SERVER');
    });

    it('leaves a whole-file note without an item prefix', () => {
      expect(importIssueText({ code: 'xpwe_encoding_fallback', encoding: 'cp1252' }, t)).toBe(
        'The file is not UTF-8 and was read as cp1252',
      );
    });

    it('keeps the ordinal of another importer out of its message', () => {
      expect(importIssueText({ ordinal: '01.02', error: 'Quantity out of range: -1' }, t)).toBe('Quantity out of range: -1');
    });
  });
});
