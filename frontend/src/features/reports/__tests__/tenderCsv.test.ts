// The tender comparison CSV carries names typed by bidders. Joined raw, a
// comma split a name across columns, a quote broke the row, and a name
// starting with "=" ran as a formula when the file was opened. The status was
// the raw enum and a deviation the server could not compute printed as 0.0%.

import { describe, it, expect } from 'vitest';
import { bidTotalCsvRow, csvCell, tenderStatusLabel } from '../tenderCsv';

const t = (key: string, opts?: Record<string, unknown>) =>
  key === 'tendering.status_submitted' ? 'Eingereicht' : String(opts?.defaultValue ?? key);

describe('csvCell', () => {
  it('quotes a value and doubles inner quotes', () => {
    expect(csvCell('Smith, "Jr" & Co')).toBe('"Smith, ""Jr"" & Co"');
  });

  it.each(['=HYPERLINK("x")', '+1', '@SUM(A1)', '-cmd'])('defuses a formula lead-in in %s', (v) => {
    expect(csvCell(v).startsWith(`"'`)).toBe(true);
  });

  it('keeps a plain negative number as data', () => {
    expect(csvCell('-4.5%')).toBe('"-4.5%"');
  });

  it('writes an empty cell for null', () => {
    expect(csvCell(null)).toBe('""');
  });
});

describe('bidTotalCsvRow', () => {
  const bid = { company_name: '=evil', total: 1100, currency: 'EUR', deviation_pct: 10, status: 'submitted' };

  it('prints the deviation and a translated status', () => {
    expect(bidTotalCsvRow({ ...bid, deviation_known: true }, 1000, t, 'N/A')).toBe(
      `"'=evil","1100.00","EUR","10.0%","Eingereicht"`,
    );
  });

  it('says N/A when the server could not compare the bid', () => {
    const row = bidTotalCsvRow({ ...bid, currency: 'USD', deviation_pct: 0, deviation_known: false }, 1000, t, 'N/A');
    expect(row).toContain('"N/A"');
    expect(row).not.toContain('0.0%');
  });

  it('says N/A for a zero budget even from an older server without the flag', () => {
    expect(bidTotalCsvRow({ ...bid, deviation_pct: 0 }, '0', t, 'N/A')).toContain('"N/A"');
  });
});

describe('tenderStatusLabel', () => {
  it('passes an unknown status through', () => {
    expect(tenderStatusLabel('mystery', t)).toBe('mystery');
  });
});
