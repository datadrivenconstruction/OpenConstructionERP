import { useMemo } from 'react';
import type { ChatMessage } from '../../types';
import ToolCallCard from './ToolCallCard';
import StreamingCursor from './StreamingCursor';

function formatTime(d: Date): string {
  const h = d.getHours().toString().padStart(2, '0');
  const m = d.getMinutes().toString().padStart(2, '0');
  return `${h}:${m}`;
}

/**
 * Lightweight markdown-to-HTML renderer.
 *
 * Handles bold, italic, inline code, code blocks, bullet/numbered lists,
 * headings, horizontal rules, and line breaks without pulling in a full
 * markdown library.
 */
function renderMarkdown(text: string): string {
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

export default function MessageBubble({ message, isStreaming }: MessageBubbleProps) {
  const { role, content, toolCalls, ts } = message;
  const renderedHtml = useMemo(() => (content ? renderMarkdown(content) : ''), [content]);

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
        }}
      >
        {formatTime(ts)}
      </span>
    </div>
  );
}
