import { useMemo, useState } from 'react';
import { ThumbsUp, ThumbsDown } from 'lucide-react';
import DOMPurify from 'isomorphic-dompurify';
import type { ChatMessage } from '../../types';
import { submitFeedback } from '../../api';
import ToolCallCard from './ToolCallCard';
import StreamingCursor from './StreamingCursor';

// DOMPurify allow-list for chat markdown output. The hand-rolled
// ``renderMarkdown`` already escapes raw user input and only re-introduces
// a narrow set of tags / attributes (bold, italic, inline + block code,
// anchors, lists, headings, line breaks, horizontal rules). Sanitising
// the final HTML right before ``dangerouslySetInnerHTML`` is a
// defence-in-depth wrapper that closes the XSS-by-edge-case class
// (audit 2026-05-24 #1): even if a future markdown edit accidentally
// passes a ``<script>``, ``onerror`` attribute, or ``javascript:`` URL
// through the regex pipeline, the sanitiser strips it before the DOM
// ever sees it.
// Exported for the chat-xss test suite — keeps the suite in lockstep
// with the actual config used at render time.
export const SAFE_TAGS = [
  'strong',
  'em',
  'code',
  'pre',
  'a',
  'br',
  'p',
  'ul',
  'ol',
  'li',
  'div',
  'span',
  'hr',
  // Pipe-table output (renderPipeTables). These carry no scriptable
  // surface; the only attribute they use is the inline ``style`` we emit
  // ourselves, already on the SAFE_ATTRS list.
  'table',
  'thead',
  'tbody',
  'tr',
  'th',
  'td',
] as const;
export const SAFE_ATTRS = ['href', 'target', 'rel', 'style'] as const;
export const SANITIZE_CONFIG = {
  ALLOWED_TAGS: [...SAFE_TAGS],
  ALLOWED_ATTR: [...SAFE_ATTRS],
  // DOMPurify strips ``target`` and ``rel`` by default even when they
  // appear in ALLOWED_ATTR, because the upstream HTML5 attribute
  // registry treats them as "additional" attributes. ADD_ATTR forces
  // them back onto the safelist so external links keep their
  // ``target="_blank" rel="noopener noreferrer"`` hardening.
  ADD_ATTR: ['target', 'rel'],
  // NOTE: we deliberately do NOT set ``ALLOWED_URI_REGEXP``. DOMPurify's
  // built-in default already filters ``javascript:`` / ``data:`` /
  // ``vbscript:`` / etc. on every URI-bearing attribute, and a custom
  // regex here was observed to silently strip ``target`` / ``rel`` in
  // jsdom (an interaction quirk with the attribute classifier). The
  // scheme allow-list in renderMarkdown is the primary gate; DOMPurify
  // default URI handling is the secondary gate.
};

function formatTime(d: Date): string {
  const h = d.getHours().toString().padStart(2, '0');
  const m = d.getMinutes().toString().padStart(2, '0');
  return `${h}:${m}`;
}

/**
 * Render GitHub-style pipe tables to an HTML ``<table>``.
 *
 * Runs on the already-HTML-escaped string (cell text is inert) and before
 * the inline link/emphasis passes, so ``**bold**``, `` `code` `` and
 * ``[links](…)`` inside cells still get formatted by the later regexes.
 * Lines inside a ``<pre>`` code block are passed through untouched so a
 * table written as example code stays literal. A block is recognised when
 * a header row (``| a | b |``) is immediately followed by a delimiter row
 * of dashes (``|---|---|``); optional colons in the delimiter set per-column
 * alignment. The emitted table is newline-free so the later line-anchored
 * heading/list/rule passes and the final ``\n`` -> ``<br/>`` pass never
 * reach inside it.
 */
export function renderPipeTables(src: string): string {
  const lines = src.split('\n');
  const splitCells = (line: string): string[] => {
    let t = line.trim();
    if (t.startsWith('|')) t = t.slice(1);
    if (t.endsWith('|')) t = t.slice(0, -1);
    // Split on unescaped pipes, then restore escaped ones as literal text.
    return t.split(/(?<!\\)\|/).map((c) => c.replace(/\\\|/g, '|').trim());
  };
  const isDelim = (line: string): boolean => {
    const t = line.trim();
    if (!t.includes('-') || !t.includes('|')) return false;
    return splitCells(line).every((c) => /^:?-{1,}:?$/.test(c));
  };
  const isRow = (line: string): boolean => line.includes('|') && line.trim() !== '';
  const cellStyle = (align: string, head: boolean): string =>
    `border:1px solid var(--chat-text-tertiary,#ccc);padding:4px 8px;text-align:${align || 'left'}` +
    (head ? ';font-weight:700;background:var(--chat-surface-3,rgba(0,0,0,.04))' : '');

  const out: string[] = [];
  let inPre = false;
  let i = 0;
  while (i < lines.length) {
    const line = lines[i] ?? '';
    if (inPre) {
      out.push(line);
      if (line.includes('</pre>')) inPre = false;
      i += 1;
      continue;
    }
    if (line.includes('<pre')) {
      inPre = !line.includes('</pre>');
      out.push(line);
      i += 1;
      continue;
    }
    const next = lines[i + 1] ?? '';
    if (isRow(line) && isDelim(next)) {
      const headers = splitCells(line);
      const aligns = splitCells(next).map((c) => {
        const l = c.startsWith(':');
        const r = c.endsWith(':');
        if (l && r) return 'center';
        if (r) return 'right';
        if (l) return 'left';
        return '';
      });
      const bodyRows: string[][] = [];
      let j = i + 2;
      while (j < lines.length) {
        const rowLine = lines[j] ?? '';
        if (!isRow(rowLine) || rowLine.includes('<pre')) break;
        bodyRows.push(splitCells(rowLine));
        j += 1;
      }
      const cols = headers.length;
      const th = headers
        .map((c, k) => `<th style="${cellStyle(aligns[k] ?? '', true)}">${c}</th>`)
        .join('');
      const body = bodyRows
        .map((cells) => {
          const tds: string[] = [];
          for (let k = 0; k < cols; k += 1) {
            tds.push(`<td style="${cellStyle(aligns[k] ?? '', false)}">${cells[k] ?? ''}</td>`);
          }
          return `<tr>${tds.join('')}</tr>`;
        })
        .join('');
      out.push(
        `<table style="border-collapse:collapse;margin:6px 0;font-size:13px;max-width:100%">` +
          `<thead><tr>${th}</tr></thead><tbody>${body}</tbody></table>`,
      );
      i = j;
      continue;
    }
    out.push(line);
    i += 1;
  }
  return out.join('\n');
}

/**
 * Lightweight markdown-to-HTML renderer.
 *
 * Handles bold, italic, inline code, code blocks, pipe tables, bullet/
 * numbered lists, headings, horizontal rules, and line breaks without
 * pulling in a full markdown library.
 */
export function renderMarkdown(text: string): string {
  // Escape ALL HTML entities first to prevent XSS injection
  let html = text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');

  // Fenced code blocks: ```...```
  html = html.replace(/```(\w*)\n([\s\S]*?)```/g, (_m, _lang, code) => {
    return `<pre style="background:var(--chat-surface-3,rgba(0,0,0,.06));padding:10px 12px;border-radius:8px;overflow-x:auto;font-size:13px;line-height:1.5;font-family:var(--chat-font-mono,monospace);margin:6px 0"><code>${code.trimEnd()}</code></pre>`;
  });

  // Inline code: `code`
  html = html.replace(/`([^`\n]+)`/g, (_m, code) => {
    return `<code style="background:var(--chat-surface-3,rgba(0,0,0,.06));padding:1px 5px;border-radius:4px;font-size:0.9em;font-family:var(--chat-font-mono,monospace)">${code}</code>`;
  });

  // Pipe tables: | a | b | / |---|---| — before the inline link/emphasis and
  // the line-anchored heading/list passes (see renderPipeTables).
  html = renderPipeTables(html);

  // Links: [text](url) — must run before bold so labels containing "**" are
  // still parsed as bold inside the rendered anchor.  External (http/https)
  // opens in a new tab with rel=noopener; internal (starts with `/`)
  // stays in the current app context so auth survives.
  html = html.replace(
    /\[([^\]]+)\]\(([^)\s]+)\)/g,
    (_m, label: string, href: string) => {
      // Allow-list URL schemes to prevent javascript:, data:, vbscript: injection.
      const isExternal = /^https?:\/\//i.test(href);
      const isInternal = href.startsWith('/') || href.startsWith('#');
      const isMailto = /^mailto:/i.test(href);
      if (!isExternal && !isInternal && !isMailto) {
        return `<span style="color:var(--chat-accent,#3b82f6)">${label}</span>`;
      }
      const attrs = isExternal ? ' target="_blank" rel="noopener noreferrer"' : '';
      return `<a href="${href}"${attrs} style="color:var(--chat-accent,#3b82f6);text-decoration:underline;font-weight:500">${label}</a>`;
    },
  );

  // Bold: **text**
  html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');

  // Italic: *text*  (but not inside words with asterisks)
  html = html.replace(/(?<!\w)\*([^*\n]+?)\*(?!\w)/g, '<em>$1</em>');

  // Headings: ### h3, ## h2, # h1
  html = html.replace(
    /^### (.+)$/gm,
    '<div style="font-size:1em;font-weight:700;margin:8px 0 4px">$1</div>',
  );
  html = html.replace(
    /^## (.+)$/gm,
    '<div style="font-size:1.1em;font-weight:700;margin:10px 0 4px">$1</div>',
  );
  html = html.replace(
    /^# (.+)$/gm,
    '<div style="font-size:1.2em;font-weight:700;margin:12px 0 4px">$1</div>',
  );

  // Horizontal rule: --- or ***
  html = html.replace(
    /^(?:---|\*\*\*)$/gm,
    '<hr style="border:none;border-top:1px solid var(--chat-text-tertiary,#ccc);margin:10px 0"/>',
  );

  // Bullet lists: lines starting with "- " or "* "
  html = html.replace(
    /^(?:[*-] .+(?:\n|$))+/gm,
    (block) => {
      const items = block
        .trim()
        .split('\n')
        .map((line) => `<li style="margin:2px 0">${line.replace(/^[*-] /, '')}</li>`)
        .join('');
      return `<ul style="margin:4px 0;padding-left:20px;list-style:disc">${items}</ul>`;
    },
  );

  // Numbered lists: lines starting with "1. ", "2. ", etc.
  html = html.replace(
    /^(?:\d+\. .+(?:\n|$))+/gm,
    (block) => {
      const items = block
        .trim()
        .split('\n')
        .map((line) => `<li style="margin:2px 0">${line.replace(/^\d+\. /, '')}</li>`)
        .join('');
      return `<ol style="margin:4px 0;padding-left:20px;list-style:decimal">${items}</ol>`;
    },
  );

  // Line breaks (preserve newlines that aren't already handled)
  html = html.replace(/\n/g, '<br/>');

  return html;
}

interface MessageBubbleProps {
  message: ChatMessage;
  isStreaming?: boolean;
}

/**
 * T8 thumbs-up / thumbs-down on assistant messages. Optimistically toggles
 * locally, fires `submitFeedback` against the backend, and rolls back on
 * failure so a network error doesn't leave the UI lying.
 */
function FeedbackBar({ messageId }: { messageId: string }) {
  const [rating, setRating] = useState<1 | -1 | 0>(0);
  const [busy, setBusy] = useState(false);

  async function click(next: 1 | -1) {
    if (busy) return;
    const prior = rating;
    // Tap again on the active thumb → no change (we don't support
    // un-rating server-side yet, so just no-op rather than lie).
    if (prior === next) return;
    setBusy(true);
    setRating(next);
    try {
      await submitFeedback(messageId, next);
    } catch {
      setRating(prior);
    } finally {
      setBusy(false);
    }
  }

  const baseStyle: React.CSSProperties = {
    background: 'transparent',
    border: 'none',
    cursor: busy ? 'wait' : 'pointer',
    padding: 2,
    color: 'var(--chat-text-tertiary)',
    display: 'inline-flex',
    alignItems: 'center',
    justifyContent: 'center',
    borderRadius: 4,
    transition: 'color 0.15s ease, background 0.15s ease',
  };
  const activeStyle: React.CSSProperties = {
    ...baseStyle,
    color: 'var(--chat-accent, #3b82f6)',
    background: 'var(--chat-surface-3, rgba(0,0,0,.06))',
  };

  return (
    <span
      style={{
        display: 'inline-flex',
        gap: 4,
        marginLeft: 8,
        verticalAlign: 'middle',
      }}
      title="Was this helpful?"
      aria-label="Feedback on this answer"
    >
      <button
        type="button"
        onClick={() => void click(1)}
        style={rating === 1 ? activeStyle : baseStyle}
        aria-label="Thumbs up"
        aria-pressed={rating === 1}
        disabled={busy}
      >
        <ThumbsUp size={13} />
      </button>
      <button
        type="button"
        onClick={() => void click(-1)}
        style={rating === -1 ? activeStyle : baseStyle}
        aria-label="Thumbs down"
        aria-pressed={rating === -1}
        disabled={busy}
      >
        <ThumbsDown size={13} />
      </button>
    </span>
  );
}

export default function MessageBubble({ message, isStreaming }: MessageBubbleProps) {
  const { id, role, content, toolCalls, ts } = message;
  const renderedHtml = useMemo(
    () => (content ? DOMPurify.sanitize(renderMarkdown(content), SANITIZE_CONFIG) : ''),
    [content],
  );

  if (role === 'system') {
    return (
      <div
        style={{
          textAlign: 'center',
          padding: '6px 0',
          color: 'var(--chat-text-tertiary)',
          fontSize: 12,
          fontFamily: 'var(--chat-font-mono)',
          animation: 'msgIn 0.3s ease-out',
        }}
      >
        {content}
      </div>
    );
  }

  if (role === 'user') {
    return (
      <div
        style={{
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'flex-end',
          padding: '4px 0',
          animation: 'msgIn 0.3s ease-out',
        }}
      >
        <div
          style={{
            background: 'var(--chat-surface-3)',
            color: 'var(--chat-text-primary)',
            padding: '10px 14px',
            borderRadius: '16px 16px 4px 16px',
            maxWidth: '85%',
            fontSize: 14,
            lineHeight: 1.55,
            fontFamily: 'var(--chat-font-body)',
            wordBreak: 'break-word',
            whiteSpace: 'pre-wrap',
          }}
        >
          {content}
        </div>
        <span
          style={{
            fontSize: 11,
            color: 'var(--chat-text-tertiary)',
            fontFamily: 'var(--chat-font-mono)',
            marginTop: 3,
            paddingRight: 2,
          }}
        >
          {formatTime(ts)}
        </span>
      </div>
    );
  }

  // assistant
  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'flex-start',
        padding: '4px 0',
        animation: 'msgIn 0.3s ease-out',
      }}
    >
      <div
        style={{
          borderLeft: '2px solid var(--chat-accent)',
          paddingLeft: 12,
          maxWidth: '92%',
        }}
      >
        {/* Tool call cards */}
        {toolCalls && toolCalls.length > 0 && (
          <div style={{ marginBottom: 6 }}>
            {toolCalls.map((tc) => (
              <ToolCallCard key={tc.id} tool={tc} />
            ))}
          </div>
        )}

        {/* Text content — rendered as lightweight markdown */}
        {(content || isStreaming) && (
          <div
            style={{
              color: 'var(--chat-text-primary)',
              fontSize: 14,
              lineHeight: 1.6,
              fontFamily: 'var(--chat-font-body)',
              wordBreak: 'break-word',
            }}
          >
            {content ? (
              <span dangerouslySetInnerHTML={{ __html: renderedHtml }} />
            ) : null}
            {isStreaming && <StreamingCursor />}
          </div>
        )}
      </div>
      <span
        style={{
          fontSize: 11,
          color: 'var(--chat-text-tertiary)',
          fontFamily: 'var(--chat-font-mono)',
          marginTop: 3,
          paddingLeft: 14,
          display: 'inline-flex',
          alignItems: 'center',
        }}
      >
        {formatTime(ts)}
        {/* Show thumbs only after streaming completes. The bubble id is a
            client-generated UUID during the stream and gets reconciled
            against the backend row when the session is re-fetched; if the
            user thumbs an unreconciled id the backend returns 404 and
            FeedbackBar quietly rolls the optimistic state back. */}
        {!isStreaming && content && id && <FeedbackBar messageId={id} />}
      </span>
    </div>
  );
}
