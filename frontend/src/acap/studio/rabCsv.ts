import type { RabLine } from './rabApi';

const HEADER = 'kode;uraian;unit;quantity;unit_rate;total;kategori;price_missing';

function csvCell(value: unknown): string {
  if (value === null || value === undefined) return '';
  const s = String(value);
  const needsQuoting = s.includes(';') || s.includes('"') || s.includes('\n');
  return needsQuoting ? '"' + s.replace(/"/g, '""') + '"' : s;
}

export function buildRabCsv(lines: RabLine[]): string {
  const rows = [HEADER];
  for (const line of lines) {
    rows.push([
      csvCell(line.kode),
      csvCell(line.uraian),
      csvCell(line.unit),
      csvCell(line.quantity),
      csvCell(line.unit_rate),
      csvCell(line.total),
      csvCell(line.kategori),
      csvCell(line.price_missing),
    ].join(';'));
  }
  return rows.join('\n') + '\n';
}
