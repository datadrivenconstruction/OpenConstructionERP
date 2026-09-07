// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Locale-aware decimal parsing for typed numeric input.
 *
 * A German estimator types `48,60` for forty-eight sixty and `1.234,56` for
 * twelve-hundred-odd; a US one types `48.60` and `1,234.56`. Both must land
 * on the same stored number. A `<input type="number">` cannot do this - the
 * browser silently drops the comma keystroke, so `48,60` becomes `4860`, a
 * value 100x off with no error anywhere. Numeric fields therefore use a TEXT
 * input (`inputMode="decimal"` for the mobile keypad) and run the raw string
 * through `parseDecimalInput` below.
 *
 * This lives in `shared/lib` rather than beside the BOQ grid that first
 * needed it because the same typed string arrives on every costing surface:
 * the CVR cost heads, the withholding-tax gross, an allowance drawdown, a
 * takeoff length. Those used to parse it four different ways - `parseFloat`
 * (silently truncating `1,5` to `1`), a bare `Number` (NaN, then a `|| 0`),
 * `.replace(',', '.')` (right for `48,60`, wrong for `1.234,56` because
 * String.replace with a string pattern only swaps the FIRST match), or no
 * parse at all with the raw string posted to a `Decimal` API field. One
 * grammar for the whole product means a comma typed in the BOQ and a comma
 * typed in the CVR land on the same number.
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

/**
 * Fold the non-ASCII digits and separators OUR OWN formatter can emit.
 *
 * `Intl.NumberFormat` picks the numbering system from the locale, and two of
 * the languages this product ships are not Latin-digit: `bn` renders 1234.56
 * as `১,২৩৪.৫৬` and `fa` as `۱٬۲۳۴٫۵۶`, the latter with U+066B as the decimal
 * point and U+066C as the group separator. A figure copied off the screen and
 * pasted back into a field is a real path (it is why the clipboard parser
 * exists), and without this the parser rejects a number the product itself
 * wrote a moment earlier.
 *
 * Deliberately limited to the systems our formatter can produce - `arab`,
 * `arabext` and `beng` - rather than every Unicode decimal digit. A wider
 * fold would start accepting scripts nothing in this product ever emits, and
 * the point of the strict grammar below is that the accepted set is known.
 * Note that `ar` itself is NOT in this list: it resolves to Latin digits.
 */
function foldNonAsciiDigits(raw: string): string {
  let out = '';
  for (const ch of raw) {
    const c = ch.codePointAt(0) ?? 0;
    if (c >= 0x0660 && c <= 0x0669) out += String.fromCharCode(48 + c - 0x0660);
    else if (c >= 0x06f0 && c <= 0x06f9) out += String.fromCharCode(48 + c - 0x06f0);
    else if (c >= 0x09e6 && c <= 0x09ef) out += String.fromCharCode(48 + c - 0x09e6);
    else if (c === 0x066b) out += '.';
    else if (c === 0x066c) continue;
    else out += ch;
  }
  return out;
}

/**
 * `1,000`-shape: 1-3 lead digits (no leading zero), then `,ddd` groups.
 *
 * The second alternative is the Indian shape: a 3-digit final group preceded
 * by 2-digit groups (`10,00,000`, `47,65,79,722`). It is not decoration. The
 * workspace market decides the grouping (see `marketNumberLocale.ts`, which
 * exists so an Indian bill prints `47,65,79,722.78` rather than
 * `476,579,722.78`), so this is the product formatting an amount one way and
 * then refusing to read it back: a whole-rupee figure copied off the screen
 * parsed as null. Amounts WITH a fraction always worked, because the dot
 * settles which separator is which - so the gap was invisible on every
 * example anyone thought to try.
 */
const COMMA_GROUPED_RE = /^[1-9]\d{0,2}(,\d{3})+$|^[1-9]\d?(,\d{2})+,\d{3}$/;
/** `1.234.567`-shape: dot-thousands is only unambiguous with 2+ groups. */
const DOT_GROUPED_RE = /^[1-9]\d{0,2}(\.\d{3}){2,}$/;

/**
 * Normalise decimal/thousands separators to a canonical dot-decimal string.
 * Returns the normalised string; it may still be non-numeric garbage - the
 * caller decides how strictly to parse it.
 */
export function normalizeDecimalSeparators(raw: string): string {
  let s = foldNonAsciiDigits(raw.trim());
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

/**
 * Normalise a typed decimal for a JSON field the API parses as a `Decimal`.
 *
 * Money crosses the wire as a STRING (`DecimalMoney` on the backend) so that
 * a cent is never lost to a float, which means the value the user typed is
 * often posted verbatim. `48,60` posted verbatim is a 422: Python's
 * `Decimal('48,60')` raises. This returns the dot-decimal spelling of the
 * same amount instead.
 *
 * Deliberately NOT `String(parseDecimalInput(raw))`: that round-trips the
 * amount through a binary float, and re-serialising is exactly the precision
 * loss the string wire format exists to avoid. The normalised string is
 * handed over untouched.
 *
 * Input that does not parse is passed through trimmed rather than replaced
 * by the fallback, so the server still rejects genuine garbage with its own
 * message instead of this helper inventing a number the user never typed.
 */
export function toDecimalPayloadString(raw: string, fallback = '0'): string {
  const trimmed = raw.trim();
  if (trimmed === '') return fallback;
  if (parseDecimalInput(trimmed) === null) return trimmed;
  return normalizeDecimalSeparators(trimmed);
}
