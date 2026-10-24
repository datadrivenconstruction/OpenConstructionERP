// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Fuzzy matching for the action palette, in whatever language the UI speaks.
 *
 * Text is folded the same way on both sides: lower-cased with the UI locale
 * (Turkish dotted I), NFKD with combining marks dropped ("Schätzung" matches
 * "schatzung"), dotless i folded to i. Scripts without spaces (CJK, Thai)
 * still match as substrings.
 */

export function foldText(text: string, locale?: string): string {
  let out: string;
  try {
    out = text.toLocaleLowerCase(locale || undefined);
  } catch {
    out = text.toLowerCase();
  }
  // Dotless i folds to i so a Turkish name matches when typed on any keyboard.
  out = out.normalize('NFKD').replace(/\p{M}+/gu, '').replace(/ı/g, 'i');
  return out.replace(/\s+/g, ' ').trim();
}

const WORD_BREAK = /[\s\-_/.,:;()>]/;

/**
 * Score one folded query token against one folded target, 0..1.
 * Substring beats subsequence; a hit at a word start beats one inside a word.
 */
function tokenScore(token: string, target: string): number {
  if (!token) return 1;
  const at = target.indexOf(token);
  if (at >= 0) {
    const wordStart = at === 0 || WORD_BREAK.test(target[at - 1] ?? '');
    return (wordStart ? 0.95 : 0.8) - Math.min(at, 40) * 0.002;
  }
  // Subsequence: every char in order, gaps cost.
  let ti = 0;
  let gaps = 0;
  let starts = 0;
  let prev = -1;
  for (const ch of token) {
    const found = target.indexOf(ch, ti);
    if (found < 0) return 0;
    if (prev >= 0 && found !== prev + 1) gaps += 1;
    if (found === 0 || WORD_BREAK.test(target[found - 1] ?? '')) starts += 1;
    prev = found;
    ti = found + 1;
  }
  if (token.length < 2) return 0;
  const score = 0.65 - (gaps / token.length) * 0.35 + Math.min(starts, 3) * 0.04;
  return Math.max(0, Math.min(0.7, score));
}

/**
 * How well `query` matches any of `targets` (title, synonyms, English title),
 * 0..1. Every query word must match somewhere; the score is their mean.
 */
export function fuzzyScore(query: string, targets: readonly string[], locale?: string): number {
  const q = foldText(query, locale);
  if (!q) return 1;
  const folded = targets.map((t) => foldText(t, locale)).filter(Boolean);
  if (folded.length === 0) return 0;
  const whole = folded.join(' | ');
  const tokens = q.split(' ');
  let sum = 0;
  for (const tok of tokens) {
    let best = 0;
    for (const target of folded) best = Math.max(best, tokenScore(tok, target));
    if (best === 0) best = tokenScore(tok, whole) * 0.9;
    if (best === 0) return 0;
    sum += best;
  }
  const exact = folded.some((t) => t === q) ? 0.05 : 0;
  return Math.min(1, sum / tokens.length + exact);
}

/** Lowest score shown in the palette; below it the row is noise. */
export const MIN_SCORE = 0.3;

export interface ProjectQuery {
  /** Text before `>`, naming a project ("project Berlin"). */
  project: string;
  /** Text after `>`, naming an action ("quantities"). */
  action: string;
}

/** Split "project Berlin > quantities" into its two halves; null without a `>`. */
export function splitProjectQuery(query: string): ProjectQuery | null {
  const at = query.indexOf('>');
  if (at < 0) return null;
  return { project: query.slice(0, at).trim(), action: query.slice(at + 1).trim() };
}

/**
 * Best project for the left half of a project query. The leading word may be
 * the word "project" in any language, so a miss retries without it.
 */
export function matchProject<T extends { name: string }>(
  text: string,
  projects: readonly T[],
  locale?: string,
): T | null {
  const attempt = (q: string): T | null => {
    let best: T | null = null;
    let bestScore = MIN_SCORE;
    for (const p of projects) {
      const s = fuzzyScore(q, [p.name], locale);
      if (s > bestScore) {
        best = p;
        bestScore = s;
      }
    }
    return best;
  };
  const trimmed = text.trim();
  if (!trimmed) return null;
  return attempt(trimmed) ?? (trimmed.includes(' ') ? attempt(trimmed.slice(trimmed.indexOf(' ') + 1)) : null);
}
