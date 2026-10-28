// DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Query-term highlighting for search results. Frontend-only and safe: the
// query is escaped before it enters the RegExp, and every match is rendered as
// a real React <mark> span (no dangerouslySetInnerHTML), so user input can
// never inject markup or break the pattern.

import { Fragment, type ReactElement } from 'react';

/** Terms shorter than this are noise for highlighting (matches the backend). */
const MIN_TERM_LEN = 2;

/** Escape a string so it is treated as a literal inside a RegExp. */
function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

/**
 * Distinct, lowercased query terms of length >= {@link MIN_TERM_LEN}, longest
 * first so a broader term wins over a nested shorter one. Mirrors the backend
 * tokeniser closely enough for visual highlighting.
 */
export function buildHighlightTerms(text: string): string[] {
  const seen = new Set<string>();
  for (const raw of text.toLowerCase().split(/\s+/)) {
    const token = raw.trim();
    if (token.length >= MIN_TERM_LEN) seen.add(token);
  }
  return [...seen].sort((a, b) => b.length - a.length);
}

/**
 * Render `text` with every occurrence of any of `terms` wrapped in a highlight
 * mark. Case-insensitive. Segments are built by walking matchAll, so overlaps
 * and repeats are handled without the stateful-RegExp.test pitfalls.
 */
export function HighlightedText({
  text,
  terms,
  className,
}: {
  text: string;
  terms: string[];
  className?: string;
}): ReactElement {
  if (!text || terms.length === 0) return <>{text}</>;

  const pattern = new RegExp(`(${terms.map(escapeRegExp).join('|')})`, 'gi');
  const markClass = className ?? 'rounded-sm bg-oe-blue/20 px-0.5 font-medium text-content-primary';

  const nodes: ReactElement[] = [];
  let last = 0;
  let key = 0;
  for (const match of text.matchAll(pattern)) {
    const matchText = match[0];
    if (matchText === undefined || matchText === '') continue;
    const start = match.index ?? last;
    if (start > last) {
      nodes.push(<Fragment key={key++}>{text.slice(last, start)}</Fragment>);
    }
    nodes.push(
      <mark key={key++} className={markClass}>
        {matchText}
      </mark>,
    );
    last = start + matchText.length;
  }
  if (last < text.length) {
    nodes.push(<Fragment key={key++}>{text.slice(last)}</Fragment>);
  }
  return <>{nodes}</>;
}
