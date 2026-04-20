/**
 * renderTaggedText — renders LLM output as React nodes with:
 *   • severity badges for bracketed tags  ([CRITICAL], [HIGH], [MEDIUM], ...)
 *   • minimal markdown (#/##/### headings, **bold**, *italic*, `code`,
 *     bullet lists with -, *, •, and blank-line paragraphs)
 *
 * Deliberately hand-rolled (no ReactMarkdown dependency) — the advisor output
 * is short and predictable, and we want zero XSS surface: no raw HTML is ever
 * interpreted, we only construct plain React elements.
 */

import React from 'react';

const TAG_STYLES: Record<string, string> = {
  CRITICAL: 'bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300',
  BLOCKER: 'bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300',
  HIGH: 'bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300',
  MEDIUM: 'bg-yellow-100 text-yellow-700 dark:bg-yellow-900/40 dark:text-yellow-300',
  WARNING: 'bg-yellow-100 text-yellow-700 dark:bg-yellow-900/40 dark:text-yellow-300',
  LOW: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300',
  INFO: 'bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300',
};

const TAG_REGEX = /\[(CRITICAL|BLOCKER|HIGH|MEDIUM|WARNING|LOW|INFO)\]/gi;

/** Render one line's inline markup: badges, **bold**, *italic*, `code`. */
function renderInline(text: string, keyPrefix: string): React.ReactNode[] {
  const parts: React.ReactNode[] = [];
  // Single alternation regex so we walk the string once in left-to-right order
  // — badges first, then the markdown pairs. `code` is backtick-delimited,
  // bold **…**, italic *…* (non-greedy, no nesting).
  const pattern = new RegExp(
    TAG_REGEX.source + '|`([^`]+)`|\\*\\*([^*]+)\\*\\*|\\*([^*]+)\\*',
    'gi',
  );
  let last = 0;
  let m: RegExpExecArray | null;
  let i = 0;
  while ((m = pattern.exec(text)) !== null) {
    if (m.index > last) parts.push(text.slice(last, m.index));
    const key = `${keyPrefix}-${i++}`;
    if (m[1]) {
      const tag = m[1].toUpperCase();
      parts.push(
        <span
          key={key}
          className={`inline-flex items-center rounded-md px-1.5 py-0.5 text-2xs font-semibold uppercase tracking-wide ${
            TAG_STYLES[tag] || TAG_STYLES.INFO
          }`}
        >
          {tag}
        </span>,
      );
    } else if (m[2] !== undefined) {
      parts.push(
        <code
          key={key}
          className="rounded bg-surface-tertiary px-1 py-0.5 font-mono text-[11px]"
        >
          {m[2]}
        </code>,
      );
    } else if (m[3] !== undefined) {
      parts.push(<strong key={key} className="font-semibold text-content-primary">{m[3]}</strong>);
    } else if (m[4] !== undefined) {
      parts.push(<em key={key}>{m[4]}</em>);
    }
    last = m.index + m[0].length;
  }
  if (last < text.length) parts.push(text.slice(last));
  return parts;
}

export function renderTaggedText(text: string): React.ReactNode {
  if (!text) return text;

  // Inline fast path — no block-level structure, keep it as a fragment so
  // callers that wrap with <p> or similar don't end up with <div> inside
  // phrasing content (invalid HTML, React hydration warnings, layout shift).
  const hasBlockStructure =
    /\n\s*\n/.test(text) ||
    /(^|\n)\s*#{1,3}\s/.test(text) ||
    /(^|\n)\s*[-*•]\s/.test(text);
  if (!hasBlockStructure) {
    return <>{renderInline(text, 'inline')}</>;
  }

  // Split into block-level groups on blank lines, then render each block
  // as a paragraph / heading / list.
  const lines = text.split(/\r?\n/);
  const blocks: React.ReactNode[] = [];
  let buffer: string[] = [];
  let listBuffer: string[] = [];
  let blockKey = 0;

  const flushList = () => {
    if (listBuffer.length === 0) return;
    const items = listBuffer;
    listBuffer = [];
    blocks.push(
      <ul key={`ul-${blockKey++}`} className="list-disc space-y-0.5 pl-5">
        {items.map((item, i) => (
          <li key={i}>{renderInline(item, `li-${blockKey}-${i}`)}</li>
        ))}
      </ul>,
    );
  };

  const flushParagraph = () => {
    flushList();
    if (buffer.length === 0) return;
    const paragraph = buffer.join(' ');
    buffer = [];
    blocks.push(
      <p key={`p-${blockKey++}`}>
        {renderInline(paragraph, `p-${blockKey}`)}
      </p>,
    );
  };

  for (const rawLine of lines) {
    const line = rawLine.trimEnd();
    if (line.trim() === '') {
      flushParagraph();
      continue;
    }
    const heading = /^(#{1,3})\s+(.*)$/.exec(line);
    if (heading) {
      flushParagraph();
      const level = heading[1]!.length;
      const textPart = heading[2]!;
      const cls =
        level === 1
          ? 'text-base font-semibold text-content-primary mt-2'
          : level === 2
            ? 'text-sm font-semibold text-content-primary mt-2'
            : 'text-xs font-semibold uppercase tracking-wide text-content-secondary mt-2';
      const Tag = (level === 1 ? 'h3' : level === 2 ? 'h4' : 'h5') as
        | 'h3'
        | 'h4'
        | 'h5';
      blocks.push(
        <Tag key={`h-${blockKey++}`} className={cls}>
          {renderInline(textPart, `h-${blockKey}`)}
        </Tag>,
      );
      continue;
    }
    const bullet = /^\s*[-*•]\s+(.*)$/.exec(line);
    if (bullet) {
      flushParagraph();
      listBuffer.push(bullet[1]!);
      continue;
    }
    buffer.push(line);
  }
  flushParagraph();

  return <div className="space-y-2">{blocks}</div>;
}
