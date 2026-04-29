/**
 * Static reference extraction for BOQ formulas.
 *
 * For dependency-graph construction we don't need a full parse — only the
 * names that the formula reads. A tokeniser sweep is plenty: extract
 * every `pos("X")`, `section("Y")`, and `$VAR` literal it sees.
 *
 * Because this is static (we never evaluate), it works even on cyclic
 * formulas — that's the whole point: we use these references to build
 * the SCC graph and decide which positions are in cycles.
 */

export interface FormulaReferences {
  /** Ordinals referenced via `pos("...")`. */
  positionOrdinals: Set<string>;
  /** Section names referenced via `section("...")`. */
  sectionNames: Set<string>;
  /** Variable names (without the `$` prefix), upper-cased. */
  variables: Set<string>;
}

/**
 * Extract every static reference from the formula source.
 * Tokeniser-only — never throws on syntactically broken input.
 */
export function extractReferences(input: string): FormulaReferences {
  const refs: FormulaReferences = {
    positionOrdinals: new Set(),
    sectionNames: new Set(),
    variables: new Set(),
  };
  const trimmed = input.trim();
  if (!trimmed) return refs;
  const body = trimmed.startsWith('=') ? trimmed.slice(1) : trimmed;

  let i = 0;
  const n = body.length;

  while (i < n) {
    const ch = body[i]!;
    // Skip strings entirely (we'll re-enter for pos("X") via the lookbehind)
    if (ch === '"' || ch === "'") {
      const quote = ch;
      i++;
      while (i < n && body[i] !== quote) {
        if (body[i] === '\\' && i + 1 < n) {
          i += 2;
          continue;
        }
        i++;
      }
      if (i < n) i++; // closing quote
      continue;
    }
    // $VAR
    if (ch === '$' && i + 1 < n && /[A-Za-z_]/.test(body[i + 1]!)) {
      i++;
      let name = '';
      while (i < n && /[A-Za-z0-9_]/.test(body[i]!)) {
        name += body[i]!;
        i++;
      }
      refs.variables.add(name.toUpperCase());
      continue;
    }
    // pos("…") / section("…") / col("…")
    if (/[a-zA-Z_]/.test(ch)) {
      let ident = '';
      const start = i;
      while (i < n && /[a-zA-Z0-9_]/.test(body[i]!)) {
        ident += body[i]!;
        i++;
      }
      // Skip whitespace
      let j = i;
      while (j < n && /\s/.test(body[j]!)) j++;
      const lc = ident.toLowerCase();
      if (body[j] === '(' && (lc === 'pos' || lc === 'section')) {
        // Find first string-literal arg
        j++; // skip (
        while (j < n && /\s/.test(body[j]!)) j++;
        if (body[j] === '"' || body[j] === "'") {
          const quote = body[j]!;
          j++;
          let str = '';
          while (j < n && body[j] !== quote) {
            if (body[j] === '\\' && j + 1 < n) {
              str += body[j + 1];
              j += 2;
              continue;
            }
            str += body[j]!;
            j++;
          }
          if (lc === 'pos') refs.positionOrdinals.add(str);
          else refs.sectionNames.add(str);
          // Don't skip ahead — let the main loop continue from `i` (after
          // the identifier). The string will then be skipped by the
          // string-literal branch above.
        }
      }
      // Reset to scan onward — but make sure we advanced.
      if (i === start) i++;
      continue;
    }
    i++;
  }

  return refs;
}
