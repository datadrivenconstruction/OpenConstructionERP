// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction

/** Render a snippet with every case-insensitive match of `query` wrapped in <mark>.
 *
 * Splits on the FIRST occurrence's regex so multi-word queries are
 * treated as a single phrase (matches the backend's substring search
 * exactly). The regex literal is built with `escapeRegExp` so user
 * input cannot inject metacharacters.
 */

import { useMemo } from 'react';

interface SnippetHighlightProps {
  text: string;
  query: string;
  className?: string | undefined;
}

/** Escape every regex metacharacter so the user's literal string is matched as-is. */
export function escapeRegExp(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

export function SnippetHighlight({ text, query, className }: SnippetHighlightProps) {
  const parts = useMemo(() => splitOnMatches(text, query), [text, query]);
  return (
    <span className={className}>
      {parts.map((part, i) =>
        part.match ? (
          <mark
            key={i}
            className="rounded-sm bg-oe-blue/15 text-content-primary px-0.5 font-medium"
          >
            {part.text}
          </mark>
        ) : (
          <span key={i}>{part.text}</span>
        ),
      )}
    </span>
  );
}

interface Segment {
  text: string;
  match: boolean;
}

/** Split `text` into a list of alternating match / non-match segments.
 *
 * Empty queries return a single non-match segment containing the whole
 * text — keeps the renderer trivial.
 */
export function splitOnMatches(text: string, query: string): Segment[] {
  if (!query.trim()) return [{ text, match: false }];
  const escaped = escapeRegExp(query.trim());
  const re = new RegExp(`(${escaped})`, 'gi');
  const segments = text.split(re);
  const out: Segment[] = [];
  const needleLower = query.trim().toLowerCase();
  for (const seg of segments) {
    if (!seg) continue;
    if (seg.toLowerCase() === needleLower) {
      out.push({ text: seg, match: true });
    } else {
      out.push({ text: seg, match: false });
    }
  }
  return out;
}
