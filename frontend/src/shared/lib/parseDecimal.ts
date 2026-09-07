// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Locale-aware decimal parsing for typed numeric input.
 *
 * A German estimator types `48,60` for forty-eight sixty and `1.234,56` for
 * twelve-hundred-odd; a US one types `48.60` and `1,234.56`. Both must land
 * on the same stored number. A `<input type="number">` cannot do this - the
 * browser silently drops the comma keystroke, so `48,60` becomes `4860`, a
 * value 100x off with no error anywhere. Every numeric cell editor in the
 * BOQ grid therefore uses a TEXT input and runs the raw string through
 * `parseDecimalInput` below.
 *
 * Separator rules (mirrors `parseClipboardNumber` in BOQGrid.tsx, which the
 * paste path has used and tested for years):
 *   - both `.` and `,` present -> the LAST one is the decimal separator,
 *     the other is a thousands separator (`1.234,56` and `1,234.56` both
 *     parse to 1234.56);
 *   - only `,` present -> decimal comma (`48,60` -> 48.6), EXCEPT grouped
 *     shapes (`1,000` / `1,234,567`: 1-3 lead digits not starting with 0,
 *     then comma-separated triples) which read as thousands separators;
 *   - only `.` present -> decimal dot (`48.60` -> 48.6). A single dot is
 *     ALWAYS decimal (the grid's canonical entry format since day one);
 *     only multi-group shapes (`1.234.567`) are unambiguous dot-thousands
 *     and collapse;
 *   - spaces (incl. NBSP / narrow NBSP) between digits are thousands
 *     separators and are stripped (`1 234,56` -> 1234.56).
 *
 * Unlike the clipboard parser this one is STRICT: input that is not wholly
 * a number after separator normalisation returns `null` instead of a
 * truncated `parseFloat` prefix, so `10abc` can never silently store 10.
 */

/** `1,000`-shape: 1-3 lead digits (no leading zero), then `,ddd` groups. */
const COMMA_GROUPED_RE = /^[1-9]\d{0,2}(,\d{3})+$/;
/** `1.234.567`-shape: dot-thousands is only unambiguous with 2+ groups. */
const DOT_GROUPED_RE = /^[1-9]\d{0,2}(\.\d{3}){2,}$/;

/**
 * Normalise decimal/thousands separators to a canonical dot-decimal string.
 * Returns the normalised string; it may still be non-numeric garbage - the
 * caller decides how strictly to parse it.
 */
export function normalizeDecimalSeparators(raw: string): string {
  let s = raw.trim();
  // Unicode minus (U+2212) to ASCII so a pasted `−5` parses like `-5`.
  s = s.replace(/−/g, '-');
  // Spaces / NBSP / narrow NBSP between digits are thousands separators.
  s = s.replace(/(\d)[ \u00A0\u202F](?=\d)/g, '$1');
  const hasComma = s.includes(',');
  const hasDot = s.includes('.');
  if (hasComma && hasDot) {
    if (s.lastIndexOf(',') > s.lastIndexOf('.')) {
      // 1.234,56 -> dots group thousands, comma is the decimal.
      return s.replace(/\./g, '').replace(',', '.');
    }
    // 1,234.56 -> commas group thousands, dot is the decimal.
    return s.replace(/,/g, '');
  }
  if (hasComma) {
    const unsigned = s.replace(/^[-+]/, '');
    if (COMMA_GROUPED_RE.test(unsigned)) return s.replace(/,/g, '');
    return s.replace(',', '.');
  }
  if (hasDot) {
    const unsigned = s.replace(/^[-+]/, '');
    if (DOT_GROUPED_RE.test(unsigned)) return s.replace(/\./g, '');
    return s;
  }
  return s;
}

/**
 * Parse user-typed numeric text. Strict: returns the number, or `null` when
 * the input is not entirely a number (empty string included).
 */
export function parseDecimalInput(raw: string): number | null {
  const normalized = normalizeDecimalSeparators(raw);
  if (normalized === '') return null;
  // Number() would also accept '0x10' / 'Infinity' / surrounding garbage
  // after our normalisation left it alone - an explicit shape check keeps
  // the accepted grammar to plain decimals with an optional exponent.
  if (!/^[-+]?(\d+(\.\d*)?|\.\d+)([eE][-+]?\d+)?$/.test(normalized)) return null;
  const n = Number(normalized);
  return Number.isFinite(n) ? n : null;
}
