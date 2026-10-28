// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Markdown - a small, dependency-free Markdown renderer tuned for in-app
 * documentation pages: a real heading hierarchy with anchor ids (so #hash
 * deep-links work), paragraphs, fenced code blocks with a language label,
 * GitHub-style pipe tables, ordered/unordered lists, blockquotes and inline
 * code / bold / italic / links.
 *
 * It deliberately does NOT pull a markdown library into the bundle. It reuses
 * the same escape-then-sanitize safety model as the chat renderer: every block
 * is HTML-escaped at the source, only a narrow set of tags is re-introduced,
 * and the final string is run through DOMPurify before it ever reaches the DOM.
 *
 * Scope: it supports the constructs our authored docs use, not the full
 * CommonMark grammar. Author docs with the supported subset above.
 */
import { useMemo } from 'react';
import DOMPurify from 'isomorphic-dompurify';

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

/** Slug for a heading anchor: lowercase, alphanumerics joined by hyphens. */
function slugify(s: string): string {
  return s
    .toLowerCase()
    .replace(/`/g, '')
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/(^-|-$)/g, '');
}

/**
 * Inline pass for already-block-extracted text. Escapes HTML first, then a
 * narrow set of inline constructs. Link URL schemes are allow-listed so a
 * `javascript:` / `data:` URL can never become a live anchor.
 */
function inline(src: string): string {
  let s = escapeHtml(src);
  // Inline code: `code`
  s = s.replace(
    /`([^`\n]+)`/g,
    (_m, c: string) =>
      `<code class="rounded bg-surface-secondary px-1.5 py-0.5 text-[0.85em] font-mono text-oe-blue">${c}</code>`,
  );
  // Links: [text](url)
  s = s.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, (_m, label: string, href: string) => {
    const external = /^https?:\/\//i.test(href);
    const internal = href.startsWith('/') || href.startsWith('#');
    const mail = /^mailto:/i.test(href);
    if (!external && !internal && !mail) return label;
    const attrs = external ? ' target="_blank" rel="noopener noreferrer"' : '';
    return `<a href="${href}"${attrs} class="text-oe-blue underline underline-offset-2 hover:opacity-80">${label}</a>`;
  });
  // Bold then italic (bold first so ** is not eaten by the * pass).
  s = s.replace(/\*\*([^*]+?)\*\*/g, '<strong class="font-semibold text-content-primary">$1</strong>');
  s = s.replace(/(?<!\w)\*([^*\n]+?)\*(?!\w)/g, '<em>$1</em>');
  return s;
}

function splitCells(line: string): string[] {
  let t = line.trim();
  if (t.startsWith('|')) t = t.slice(1);
  if (t.endsWith('|')) t = t.slice(0, -1);
  return t.split(/(?<!\\)\|/).map((c) => c.replace(/\\\|/g, '|').trim());
}

function isTableRow(line: string): boolean {
  return line.includes('|') && line.trim() !== '';
}

function isTableDelim(line: string): boolean {
  const t = line.trim();
  if (!t.includes('-') || !t.includes('|')) return false;
  return splitCells(line).every((c) => /^:?-{1,}:?$/.test(c));
}

function alignClass(a: string): string {
  if (a === 'center') return 'text-center';
  if (a === 'right') return 'text-right';
  return 'text-left';
}

function consumeTable(lines: string[], start: number): { html: string; next: number } {
  const headers = splitCells(lines[start] ?? '');
  const aligns = splitCells(lines[start + 1] ?? '').map((c) => {
    const l = c.startsWith(':');
    const r = c.endsWith(':');
    if (l && r) return 'center';
    if (r) return 'right';
    return 'left';
  });
  const bodyRows: string[][] = [];
  let j = start + 2;
  while (j < lines.length && isTableRow(lines[j] ?? '') && !isTableDelim(lines[j] ?? '')) {
    bodyRows.push(splitCells(lines[j] ?? ''));
    j += 1;
  }
  const cols = headers.length;
  const th = headers
    .map(
      (c, k) =>
        `<th class="border border-border-light bg-surface-secondary/60 px-3 py-2 font-semibold text-content-primary ${alignClass(aligns[k] ?? 'left')}">${inline(c)}</th>`,
    )
    .join('');
  const body = bodyRows
    .map((cells) => {
      const tds: string[] = [];
      for (let k = 0; k < cols; k += 1) {
        tds.push(
          `<td class="border border-border-light px-3 py-2 align-top ${alignClass(aligns[k] ?? 'left')}">${inline(cells[k] ?? '')}</td>`,
        );
      }
      return `<tr>${tds.join('')}</tr>`;
    })
    .join('');
  return {
    html:
      `<div class="my-4 overflow-x-auto"><table class="w-full border-collapse text-sm text-content-secondary">` +
      `<thead><tr>${th}</tr></thead><tbody>${body}</tbody></table></div>`,
    next: j,
  };
}

const HEADING_CLASS: Record<number, string> = {
  1: 'text-2xl font-bold mt-2 mb-3',
  2: 'text-xl font-semibold mt-8 mb-3 pb-1.5 border-b border-border-light',
  3: 'text-base font-semibold mt-6 mb-2',
  4: 'text-sm font-semibold uppercase tracking-wide text-content-tertiary mt-4 mb-1',
};

/** Render a documentation Markdown string to sanitized HTML. */
export function renderDocMarkdown(md: string): string {
  const lines = md.replace(/\r\n/g, '\n').replace(/\r/g, '\n').split('\n');
  const out: string[] = [];
  let para: string[] = [];

  const flushPara = (): void => {
    if (para.length) {
      out.push(`<p class="my-3 leading-relaxed text-content-secondary">${inline(para.join(' '))}</p>`);
      para = [];
    }
  };

  let i = 0;
  while (i < lines.length) {
    const line = lines[i] ?? '';

    // Fenced code block: ```lang ... ```
    const fence = line.match(/^```(\w*)\s*$/);
    if (fence) {
      flushPara();
      const lang = fence[1] ?? '';
      const buf: string[] = [];
      i += 1;
      while (i < lines.length && !/^```\s*$/.test(lines[i] ?? '')) {
        buf.push(lines[i] ?? '');
        i += 1;
      }
      i += 1; // skip the closing fence
      const code = escapeHtml(buf.join('\n'));
      const label = lang
        ? `<span class="absolute right-2 top-2 text-[9px] uppercase tracking-wider text-gray-400">${escapeHtml(lang)}</span>`
        : '';
      out.push(
        `<pre class="relative my-4 overflow-x-auto rounded-lg border border-border-light bg-gray-900 dark:bg-gray-950 p-4 pt-5 text-[12px] leading-relaxed font-mono text-gray-100">${label}<code class="whitespace-pre">${code}</code></pre>`,
      );
      continue;
    }

    // Heading: # .. ####
    const h = line.match(/^(#{1,4})\s+(.*)$/);
    if (h) {
      flushPara();
      const level = (h[1] ?? '#').length;
      const text = (h[2] ?? '').trim();
      out.push(
        `<h${level} id="${slugify(text)}" class="scroll-mt-24 text-content-primary ${HEADING_CLASS[level] ?? ''}">${inline(text)}</h${level}>`,
      );
      i += 1;
      continue;
    }

    // Horizontal rule
    if (/^(?:-{3,}|\*{3,})\s*$/.test(line)) {
      flushPara();
      out.push('<hr class="my-6 border-t border-border-light" />');
      i += 1;
      continue;
    }

    // Blockquote (callout): > ...
    if (/^>\s?/.test(line)) {
      flushPara();
      const buf: string[] = [];
      while (i < lines.length && /^>\s?/.test(lines[i] ?? '')) {
        buf.push((lines[i] ?? '').replace(/^>\s?/, ''));
        i += 1;
      }
      out.push(
        `<blockquote class="my-4 rounded-r-lg border-l-4 border-oe-blue/40 bg-surface-secondary/40 px-4 py-2.5 text-sm text-content-secondary">${inline(buf.join(' '))}</blockquote>`,
      );
      continue;
    }

    // GitHub-style pipe table
    if (isTableRow(line) && isTableDelim(lines[i + 1] ?? '')) {
      flushPara();
      const t = consumeTable(lines, i);
      out.push(t.html);
      i = t.next;
      continue;
    }

    // Unordered list
    if (/^\s*[-*]\s+/.test(line)) {
      flushPara();
      const buf: string[] = [];
      while (i < lines.length && /^\s*[-*]\s+/.test(lines[i] ?? '')) {
        buf.push((lines[i] ?? '').replace(/^\s*[-*]\s+/, ''));
        i += 1;
      }
      const items = buf.map((it) => `<li class="my-1">${inline(it)}</li>`).join('');
      out.push(`<ul class="my-3 list-disc space-y-1 pl-6 text-content-secondary">${items}</ul>`);
      continue;
    }

    // Ordered list
    if (/^\s*\d+\.\s+/.test(line)) {
      flushPara();
      const buf: string[] = [];
      while (i < lines.length && /^\s*\d+\.\s+/.test(lines[i] ?? '')) {
        buf.push((lines[i] ?? '').replace(/^\s*\d+\.\s+/, ''));
        i += 1;
      }
      const items = buf.map((it) => `<li class="my-1">${inline(it)}</li>`).join('');
      out.push(`<ol class="my-3 list-decimal space-y-1 pl-6 text-content-secondary">${items}</ol>`);
      continue;
    }

    // Blank line -> paragraph break
    if (line.trim() === '') {
      flushPara();
      i += 1;
      continue;
    }

    // Plain text -> accumulate into the current paragraph
    para.push(line.trim());
    i += 1;
  }
  flushPara();

  return DOMPurify.sanitize(out.join('\n'), {
    ALLOWED_TAGS: [
      'h1', 'h2', 'h3', 'h4', 'p', 'ul', 'ol', 'li', 'pre', 'code', 'strong', 'em',
      'a', 'blockquote', 'hr', 'table', 'thead', 'tbody', 'tr', 'th', 'td', 'span', 'br',
    ],
    ALLOWED_ATTR: ['id', 'class', 'href', 'target', 'rel'],
    ADD_ATTR: ['target', 'rel'],
  });
}

export interface MarkdownProps {
  /** The Markdown source to render. */
  source: string;
  /** Optional wrapper class. */
  className?: string;
}

/** Render a documentation Markdown string as styled, sanitized HTML. */
export function Markdown({ source, className }: MarkdownProps) {
  const html = useMemo(() => renderDocMarkdown(source), [source]);
  // html is sanitized by renderDocMarkdown (DOMPurify) before it reaches here.
  return <div className={className} dangerouslySetInnerHTML={{ __html: html }} />;
}
