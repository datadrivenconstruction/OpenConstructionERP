// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, it, expect } from 'vitest';
import { importIssueText } from './importIssueText';
import hr from '@/app/locales/hr';

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
});
