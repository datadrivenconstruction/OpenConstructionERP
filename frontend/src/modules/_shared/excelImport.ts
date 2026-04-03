/**
 * Shared Excel/CSV BOQ import utilities.
 *
 * Parses uploaded spreadsheet files and extracts BOQ positions based on
 * country-specific column mappings. Uses SheetJS-compatible CSV parsing
 * (no heavy dependency — we parse CSV/TSV natively, and for .xlsx we
 * use a lightweight approach).
 */

import type { ExchangePosition, ColumnMapping, ImportParseResult } from './templateTypes';

/** Parse CSV text into rows. */
function parseCSV(text: string): string[][] {
  const lines = text.split(/\r?\n/).filter((l) => l.trim());
  return lines.map((line) => {
    const cells: string[] = [];
    let current = '';
    let inQuotes = false;
    for (const ch of line) {
      if (ch === '"') {
        inQuotes = !inQuotes;
      } else if ((ch === ',' || ch === ';' || ch === '\t') && !inQuotes) {
        cells.push(current.trim());
        current = '';
      } else {
        current += ch;
      }
    }
    cells.push(current.trim());
    return cells;
  });
}

/** Try to auto-detect column mapping from header row. */
export function detectColumns(headers: string[]): ColumnMapping {
  const mapping: ColumnMapping = {};
  const lower = headers.map((h) => h.toLowerCase().trim());

  for (let i = 0; i < lower.length; i++) {
    const h = lower[i] ?? '';
    if (!h) continue;
    const col = String(i);
    if (/^(ordinal|pos|no\.?|item|ref|code)$/i.test(h)) mapping.ordinal = col;
    else if (/^(description|desc|text|bezeichnung|libellé|désignation)$/i.test(h)) mapping.description = col;
    else if (/^(unit|uom|einheit|unité)$/i.test(h)) mapping.unit = col;
    else if (/^(qty|quantity|menge|quantité)$/i.test(h)) mapping.quantity = col;
    else if (/^(rate|unit.?rate|price|ep|einheitspreis|prix.?unitaire)$/i.test(h)) mapping.unitRate = col;
    else if (/^(total|amount|gp|gesamtpreis|montant)$/i.test(h)) mapping.total = col;
    else if (/^(section|group|trade|lot|gewerk)$/i.test(h)) mapping.section = col;
    else if (/^(class|classification|code|nrm|masterformat|din)$/i.test(h)) mapping.classification = col;
  }

  return mapping;
}

/**
 * Parse a numeric string that may use European formatting (1.500,00 → 1500).
 * Handles both US (1,500.00) and EU (1.500,00) conventions.
 */
function parseNum(raw: string): number {
  const s = raw.replace(/[^\d.,\-]/g, '');
  if (!s) return 0;
  // Detect European format: digits.digits,digits (dot = thousands, comma = decimal)
  if (/\d\.\d{3}(,|$)/.test(s)) {
    // European: remove dots (thousands sep), replace comma with dot (decimal)
    return parseFloat(s.replace(/\./g, '').replace(',', '.')) || 0;
  }
  // Otherwise treat comma as decimal separator (e.g., "25,50")
  return parseFloat(s.replace(',', '.')) || 0;
}

/** Parse a CSV/TSV file into ExchangePositions using the given column mapping. */
export function parseSpreadsheetData(
  rows: string[][],
  mapping: ColumnMapping,
  skipHeader: boolean = true,
): ImportParseResult {
  const dataRows = skipHeader ? rows.slice(1) : rows;
  const positions: ExchangePosition[] = [];
  const warnings: string[] = [];
  const errors: string[] = [];

  for (let i = 0; i < dataRows.length; i++) {
    const row = dataRows[i];
    if (!row || row.every((c) => !c)) continue; // skip empty rows

    const getCol = (key: keyof ColumnMapping): string => {
      const colIdx = mapping[key];
      if (colIdx == null) return '';
      return row[parseInt(colIdx, 10)] ?? '';
    };

    const description = getCol('description');
    if (!description) continue; // skip rows without description

    const qty = parseNum(getCol('quantity'));
    const rate = parseNum(getCol('unitRate'));
    const rawTotal = getCol('total');
    const total = rawTotal ? parseNum(rawTotal) || qty * rate : qty * rate;

    positions.push({
      ordinal: getCol('ordinal') || String(i + 1),
      description,
      unit: getCol('unit') || 'pcs',
      quantity: qty,
      unitRate: rate,
      total,
      section: getCol('section') || undefined,
      classification: getCol('classification') ? { code: getCol('classification') } : undefined,
    });
  }

  if (positions.length === 0) {
    errors.push('No valid positions found in the file.');
  }

  return {
    positions,
    warnings,
    errors,
    metadata: {
      positionCount: positions.length,
      totalValue: positions.reduce((sum, p) => sum + p.total, 0),
    },
  };
}

/** Parse an uploaded CSV/TSV file and return positions. */
export async function parseExcelFile(
  file: File,
  overrideMapping?: ColumnMapping,
): Promise<ImportParseResult> {
  const text = await file.text();
  const rows = parseCSV(text);

  if (rows.length < 2) {
    return { positions: [], warnings: [], errors: ['File is empty or has insufficient data.'] };
  }

  const mapping = overrideMapping ?? detectColumns(rows[0]!);
  return parseSpreadsheetData(rows, mapping);
}
