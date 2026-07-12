import { describe, it, expect } from 'vitest';
import { buildRabCsv } from './rabCsv';
import type { RabLine } from './rabApi';

const FIXTURE_LINES: RabLine[] = [
  {
    kode: 'A.1',
    uraian: 'Pekerjaan Pondasi',
    unit: 'm3',
    quantity: '12.5',
    unit_rate: '1500000',
    total: '18750000',
    price_missing: false,
    kategori: 'Pondasi',
    missing_resources: [],
    curated_resources: [],
  },
  {
    kode: 'B.1',
    uraian: 'Pekerjaan Dinding',
    unit: 'm2',
    quantity: '45',
    unit_rate: null,
    total: null,
    price_missing: true,
    kategori: 'Dinding',
    missing_resources: ['Bata', 'Semen'],
    curated_resources: [],
  },
];

describe('buildRabCsv', () => {
  it('produces semicolon-CSV with header and data rows', () => {
    const csv = buildRabCsv(FIXTURE_LINES);
    const lines = csv.trim().split('\n');

    expect(lines[0]).toBe('kode;uraian;unit;quantity;unit_rate;total;kategori;price_missing');

    // Row 1: priced — exact row, rate/total carried through verbatim.
    expect(lines[1]).toBe('A.1;Pekerjaan Pondasi;m3;12.5;1500000;18750000;Pondasi;false');

    // Row 2: price_missing → adjacent ;; empty cells for rate/total (never "null").
    expect(lines[2]).toBe('B.1;Pekerjaan Dinding;m2;45;;;Dinding;true');
  });
});
