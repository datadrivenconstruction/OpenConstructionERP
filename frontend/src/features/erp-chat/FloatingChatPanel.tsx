/**
 * Floating chat panel — sliding side drawer (or full-screen sheet on
 * mobile) that talks to the same backend SSE endpoint as the full-page
 * chat. Reuses the renderer registry so tool results render exactly the
 * same way as on /chat.
 *
 * The panel intentionally owns its own conversation state (mirroring
 * `useChatFullPage`) rather than sharing state with the full-page chat —
 * this way the user can keep a long-running full-page conversation open in
 * one tab and use the floating widget for quick lookups in another without
 * stomping on each other.
 */

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ChangeEvent,
  type KeyboardEvent,
} from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import {
  X,
  ExternalLink,
  History,
  MessageSquarePlus,
  Loader2,
  KeyRound,
  AlertTriangle,
  RotateCw,
  Lock,
  ShieldAlert,
} from 'lucide-react';
import DOMPurify from 'isomorphic-dompurify';
import { useAuthStore } from '@/stores/useAuthStore';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { useThemeStore } from '@/stores/useThemeStore';
import { aiApi, type AISettings } from '@/features/ai/api';
import { useFocusTrap } from '@/shared/hooks/useFocusTrap';
import { uuid } from '@/shared/lib/browser';
import { useFloatingChatStore, useIsMobileViewport } from './useFloatingChat';
import { fetchChatSessions } from './api';
import type { ChatMessage, ChatSession, ToolCallInfo } from './types';

// Reuse the full-page renderer registry so the tool-result cards inside the
// floating panel look identical to /chat. The single shared RENDERER_REGISTRY
// is the source of truth - it maps every backend renderer name (and legacy
// aliases) to a component, so the two surfaces can never drift again.
import { RENDERER_REGISTRY } from './full-page/right/renderers';

import './full-page/chat-tokens.css';

// DOMPurify allow-list mirrors the one in
// ``full-page/left/MessageBubble.tsx`` — see the security audit note
// there. Keeping the config inline (rather than centralising) means a
// future tweak to one chat surface can't silently weaken the other.
const SANITIZE_CONFIG = {
  ALLOWED_TAGS: [
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
    // Pipe-table output (renderPipeTables). Only the inline ``style`` we
    // emit ourselves is used, already on ALLOWED_ATTR.
    'table',
    'thead',
    'tbody',
    'tr',
    'th',
    'td',
  ],
  ALLOWED_ATTR: ['href', 'target', 'rel', 'style'],
  // DOMPurify treats ``target`` / ``rel`` as "additional" attributes that
  // need to be explicitly re-added even when listed in ALLOWED_ATTR;
  // without this the renderer would strip the safe-window hardening
  // from external links.  See full-page/left/MessageBubble.tsx for why
  // ``ALLOWED_URI_REGEXP`` is deliberately omitted (it silently strips
  // ``target`` / ``rel`` under jsdom).  DOMPurify's default URI
  // sanitiser already blocks ``javascript:`` / ``data:`` / ``vbscript:``.
  ADD_ATTR: ['target', 'rel'],
};

const RENDERERS = RENDERER_REGISTRY;

const SOFT_LIMIT = 3000;
const HARD_LIMIT = 4000;

function uid(): string {
  return uuid();
}

// ── Role helpers ───────────────────────────────────────────────────────────
// Mirrors the backend ``Role`` hierarchy: admin > manager > editor > viewer.
// Project-team aliases (``owner`` / ``project_manager``) and the legacy
// ``superuser`` alias also count as manager+. We deliberately err on the
// side of "show the action and let the backend reject it" — the chip
// guard is UX-only; the source of truth lives in
// ``backend/app/modules/erp_chat/tools.py`` ``check_tool_permission``.
const MANAGER_OR_ABOVE_ROLES = new Set([
  'admin',
  'manager',
  'superuser',
  'owner',
  'project_manager',
]);

function isManagerOrAbove(role: string | null | undefined): boolean {
  if (!role) return false;
  return MANAGER_OR_ABOVE_ROLES.has(role.toLowerCase().trim());
}

// Heuristic — does this suggestion chip's text imply a write action?
// Used to lock chips like "Create a draft RFI from the latest clash" for
// non-manager users. Conservative: matches only verbs at the start of the
// sentence to avoid false positives on read-only chips that mention
// "create" in passing (e.g. "Show me what tools can create…").
const WRITE_VERB_PREFIXES = [
  'create ',
  'draft ',
  'add ',
  'insert ',
  'update ',
  'edit ',
  'delete ',
  'remove ',
  'mark ',
  'approve ',
  'reject ',
];

function chipIsWriteAction(text: string): boolean {
  if (!text) return false;
  const lc = text.trim().toLowerCase();
  return WRITE_VERB_PREFIXES.some((v) => lc.startsWith(v));
}

// ── Suggestion prompts ─────────────────────────────────────────────────────
function useDefaultSuggestions(): string[] {
  const { t } = useTranslation();
  return [
    t('chat.panel.sugg_over_budget', { defaultValue: 'What are my over-budget projects?' }),
    t('chat.panel.sugg_top_risks', { defaultValue: 'Show me top open risks' }),
    t('chat.panel.sugg_walls', {
      defaultValue: "Find all walls > 30cm in current project's BIM",
    }),
    t('chat.panel.sugg_validate_boq', { defaultValue: 'Validate the current BOQ' }),
    t('chat.panel.sugg_draft_rfi', {
      defaultValue: 'Create a draft RFI from the latest clash',
    }),
    t('chat.panel.sugg_critical_path', { defaultValue: "What's the schedule critical path?" }),
  ];
}

/**
 * Page-contextual suggestion chips.
 *
 * Inspects the current pathname and returns 3-4 chips tuned to whatever the
 * user is currently looking at. Returns an empty array on routes we don't
 * have a context bundle for — the panel then shows just the 6 generic chips.
 *
 * NOTE: we match on the URL prefix only (no params) so the chips work for
 * both /boq/abc-123 and any future /boq/abc-123/edit-style routes.
 */
function useContextualSuggestions(pathname: string): string[] {
  const { t } = useTranslation();
  return useMemo(() => {
    if (/^\/boq\/[^/]+/.test(pathname)) {
      return [
        t('chat.panel.ctx_boq.validate', { defaultValue: 'Validate this BOQ' }),
        t('chat.panel.ctx_boq.suggest_missing', {
          defaultValue: 'Suggest cost items for missing positions',
        }),
        t('chat.panel.ctx_boq.compare', {
          defaultValue: 'Compare this BOQ against my other projects',
        }),
      ];
    }
    if (/^\/projects\/[^/]+/.test(pathname)) {
      return [
        t('chat.panel.ctx_project.summary', {
          defaultValue: "Summarize this project's status",
        }),
        t('chat.panel.ctx_project.open_risks', {
          defaultValue: "Show me this project's open risks",
        }),
        t('chat.panel.ctx_project.over_budget', {
          defaultValue: 'What are the over-budget areas?',
        }),
      ];
    }
    if (/^\/accommodation\/[^/]+/.test(pathname)) {
      return [
        t('chat.panel.ctx_accommodation.occupancy', {
          defaultValue: 'Show me occupancy trend',
        }),
        t('chat.panel.ctx_accommodation.suggest_room', {
          defaultValue: 'Suggest a room for the next arriving employee',
        }),
        t('chat.panel.ctx_accommodation.bookings_ending', {
          defaultValue: 'List bookings ending this week',
        }),
      ];
    }
    if (/^\/geo(\/|$)/.test(pathname)) {
      return [
        t('chat.panel.ctx_geo.nearby', {
          defaultValue: 'Find projects within 50 km of my current view',
        }),
        t('chat.panel.ctx_geo.clashes', {
          defaultValue: 'Show me clashes on the active project',
        }),
      ];
    }
    if (/^\/bim(\/|$)/.test(pathname)) {
      return [
        t('chat.panel.ctx_bim.unlinked', {
          defaultValue: 'List unlinked elements in this model',
        }),
        t('chat.panel.ctx_bim.compare_revisions', {
          defaultValue: 'Compare quantities between revisions',
        }),
      ];
    }
    return [];
    // We intentionally re-derive whenever pathname or t change. `t` keeps a
    // stable identity per language so this only fires on route change or
    // locale switch.
  }, [pathname, t]);
}

/**
 * Heuristic — does this error message look like an "AI key missing /
 * invalid" problem? If so we surface the "Configure AI" CTA in the error
 * card instead of the plain "Retry" button.
 */
function isApiKeyError(message: string): boolean {
  if (!message) return false;
  const lc = message.toLowerCase();
  return (
    lc.includes('api key') ||
    lc.includes('api_key') ||
    lc.includes('not configured') ||
    lc.includes('no provider') ||
    lc.includes('unauthorized') ||
    lc.includes('401') ||
    lc.includes('invalid key') ||
    lc.includes('missing key')
  );
}

// ── Lightweight markdown (shared subset of MessageBubble) ──────────────────
/**
 * Render GitHub-style pipe tables to an HTML ``<table>``. Mirrors the helper
 * in ``full-page/left/MessageBubble.tsx`` (kept inline per the surface-isolation
 * note above). Operates on the already-escaped string, before the inline
 * link/emphasis passes, and skips lines inside a ``<pre>`` block. The emitted
 * table is newline-free so the final ``\n`` -> ``<br/>`` pass never reaches it.
 */
function renderPipeTables(src: string): string {
  const lines = src.split('\n');
  const splitCells = (line: string): string[] => {
    let t = line.trim();
    if (t.startsWith('|')) t = t.slice(1);
    if (t.endsWith('|')) t = t.slice(0, -1);
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

function renderMarkdown(text: string): string {
  let html = text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
  html = html.replace(/```(\w*)\n([\s\S]*?)```/g, (_m, _lang, code: string) =>
    `<pre style="background:var(--chat-surface-3,rgba(0,0,0,.06));padding:8px 10px;border-radius:6px;overflow-x:auto;font-size:12px;line-height:1.5;font-family:var(--chat-font-mono,monospace);margin:4px 0"><code>${code.trimEnd()}</code></pre>`,
  );
  html = html.replace(/`([^`\n]+)`/g, (_m, code: string) =>
    `<code style="background:var(--chat-surface-3,rgba(0,0,0,.06));padding:1px 4px;border-radius:3px;font-size:0.9em;font-family:var(--chat-font-mono,monospace)">${code}</code>`,
  );
  html = renderPipeTables(html);
  html = html.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, (_m, label: string, href: string) => {
    const isExternal = /^https?:\/\//i.test(href);
    const isInternal = href.startsWith('/') || href.startsWith('#');
    const isMailto = /^mailto:/i.test(href);
    if (!isExternal && !isInternal && !isMailto) {
      return `<span style="color:var(--chat-accent,#3b82f6)">${label}</span>`;
    }
    const attrs = isExternal ? ' target="_blank" rel="noopener noreferrer"' : '';
    return `<a href="${href}"${attrs} style="color:var(--chat-accent,#3b82f6);text-decoration:underline;font-weight:500">${label}</a>`;
  });
  html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
  html = html.replace(/(?<!\w)\*([^*\n]+?)\*(?!\w)/g, '<em>$1</em>');
  html = html.replace(/\n/g, '<br/>');
  return html;
}

// ── Tool call card (compact variant for the panel) ─────────────────────────
function ToolCallEntry({ tool }: { tool: ToolCallInfo }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(true);
  const renderer = tool.result?.renderer;
  const RendererComp = renderer ? RENDERERS[renderer] : null;
  const data = tool.result?.data;
  const summary = tool.result?.summary;

  const statusLabel =
    tool.status === 'running'
      ? t('chat.panel.tool_running', {
          defaultValue: 'Running {{name}}...',
          name: tool.name,
        })
      : tool.status === 'error'
      ? t('chat.panel.tool_failed', {
          defaultValue: 'Tool {{name}} failed',
          name: tool.name,
        })
      : tool.name;

  return (
    <div
      style={{
        margin: '6px 0',
        border: '1px solid var(--chat-border-subtle)',
        borderRadius: 8,
        background: 'var(--chat-surface-2)',
        overflow: 'hidden',
      }}
    >
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        style={{
          width: '100%',
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          padding: '6px 10px',
          background: 'transparent',
          border: 'none',
          cursor: 'pointer',
          fontSize: 12,
          fontFamily: 'var(--chat-font-body)',
          color: 'var(--chat-text-secondary)',
          textAlign: 'left',
        }}
        aria-expanded={open}
      >
        {tool.status === 'running' && (
          <Loader2 size={12} className="animate-spin" style={{ color: 'var(--chat-tool-running)' }} />
        )}
        <span
          style={{
            color:
              tool.status === 'error'
                ? 'var(--chat-tool-error)'
                : tool.status === 'done'
                ? 'var(--chat-tool-done)'
                : 'var(--chat-text-secondary)',
            fontWeight: 500,
          }}
        >
          {statusLabel}
        </span>
        {summary && (
          <span
            style={{
              color: 'var(--chat-text-tertiary)',
              fontSize: 11,
              marginLeft: 'auto',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
              maxWidth: 160,
            }}
            title={summary}
          >
            {summary}
          </span>
        )}
      </button>
      {open && RendererComp && data !== undefined && (
        <div style={{ padding: 8, borderTop: '1px solid var(--chat-border-subtle)' }}>
          <RendererComp data={data} />
        </div>
      )}
    </div>
  );
}

// ── Empty-state suggestion chips ───────────────────────────────────────────
function SuggestionChip({
  text,
  onPick,
  testIdSuffix,
  locked = false,
}: {
  text: string;
  onPick: (text: string) => void;
  testIdSuffix: string;
  /** Write action that the current user cannot perform. We still render the
   *  chip so users discover the feature, but lock the click and surface the
   *  manager-required tooltip. */
  locked?: boolean;
}) {
  const { t } = useTranslation();
  const lockedTooltip = t('chat.error.manager_required', {
    defaultValue: 'Requires manager permission',
  });
  return (
    <button
      key={text}
      type="button"
      onClick={() => {
        if (locked) return;
        onPick(text);
      }}
      aria-disabled={locked || undefined}
      title={locked ? lockedTooltip : undefined}
      data-testid={`floating-chat-suggestion-${testIdSuffix}`}
      data-locked={locked || undefined}
      style={{
        textAlign: 'left',
        padding: '8px 12px',
        fontSize: 13,
        fontFamily: 'var(--chat-font-body)',
        background: 'var(--chat-surface-2)',
        border: '1px solid var(--chat-border-subtle)',
        borderRadius: 8,
        color: locked ? 'var(--chat-text-tertiary)' : 'var(--chat-text-primary)',
        cursor: locked ? 'not-allowed' : 'pointer',
        opacity: locked ? 0.75 : 1,
        display: 'flex',
        alignItems: 'center',
        gap: 6,
        transition: 'border-color 0.15s, background 0.15s',
      }}
      onMouseEnter={(e) => {
        if (locked) return;
        (e.currentTarget as HTMLButtonElement).style.borderColor = 'var(--chat-accent)';
      }}
      onMouseLeave={(e) => {
        if (locked) return;
        (e.currentTarget as HTMLButtonElement).style.borderColor =
          'var(--chat-border-subtle)';
      }}
    >
      {locked && (
        <Lock
          size={11}
          strokeWidth={1.85}
          aria-hidden
          style={{ color: 'var(--chat-text-tertiary)', flexShrink: 0 }}
        />
      )}
      <span style={{ flex: 1, minWidth: 0 }}>{text}</span>
    </button>
  );
}

function EmptyState({
  onPick,
  pathname,
  canWrite,
}: {
  onPick: (text: string) => void;
  pathname: string;
  /** Caller's role permits write tools. When false, chips that look like
   *  write actions render with a lock icon + tooltip instead of being
   *  clickable. */
  canWrite: boolean;
}) {
  const { t } = useTranslation();
  const suggestions = useDefaultSuggestions();
  const contextualSuggestions = useContextualSuggestions(pathname);
  const hasContextual = contextualSuggestions.length > 0;

  return (
    <div style={{ padding: '16px 14px' }}>
      <div
        style={{
          fontSize: 13,
          color: 'var(--chat-text-secondary)',
          lineHeight: 1.55,
          marginBottom: 12,
        }}
      >
        {t('chat.panel.empty_state', {
          defaultValue:
            'Ask anything about your projects - BOQs, validation, clashes, costs - or run an action like "create RFI for clash 32".',
        })}
      </div>

      {hasContextual && (
        <>
          <div
            style={{
              fontSize: 11,
              fontWeight: 600,
              color: 'var(--chat-text-tertiary)',
              textTransform: 'uppercase',
              letterSpacing: 0.5,
              marginBottom: 6,
            }}
            data-testid="floating-chat-contextual-label"
          >
            {t('chat.panel.contextual_label', {
              defaultValue: 'For this page',
            })}
          </div>
          <div
            style={{ display: 'flex', flexDirection: 'column', gap: 6, marginBottom: 12 }}
            data-testid="floating-chat-contextual-chips"
          >
            {contextualSuggestions.map((s, i) => (
              <SuggestionChip
                key={s}
                text={s}
                onPick={onPick}
                testIdSuffix={`ctx-${i}`}
                locked={!canWrite && chipIsWriteAction(s)}
              />
            ))}
          </div>
          <div
            style={{
              height: 1,
              background: 'var(--chat-border-subtle)',
              margin: '0 0 12px',
            }}
            aria-hidden
          />
          <div
            style={{
              fontSize: 11,
              fontWeight: 600,
              color: 'var(--chat-text-tertiary)',
              textTransform: 'uppercase',
              letterSpacing: 0.5,
              marginBottom: 6,
            }}
          >
            {t('chat.panel.generic_label', { defaultValue: 'Anywhere' })}
          </div>
        </>
      )}

      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        {suggestions.map((s, i) => (
          <SuggestionChip
            key={s}
            text={s}
            onPick={onPick}
            testIdSuffix={`generic-${i}`}
            locked={!canWrite && chipIsWriteAction(s)}
          />
        ))}
      </div>
    </div>
  );
}

// ── No-AI-configured onboarding banner ─────────────────────────────────────
function NoAIBanner({
  onConfigure,
  onSkip,
}: {
  onConfigure: () => void;
  onSkip: () => void;
}) {
  const { t } = useTranslation();
  const containerRef = useRef<HTMLDivElement>(null);

  // Focus the banner when it appears so screen readers announce it and so
  // keyboard users can tab directly into the CTAs.
  useEffect(() => {
    containerRef.current?.focus();
  }, []);

  return (
    <div
      ref={containerRef}
      role="alert"
      aria-live="polite"
      tabIndex={-1}
      data-testid="floating-chat-no-ai-banner"
      style={{
        margin: '10px 12px 0',
        padding: 12,
        background: 'var(--chat-surface-2)',
        border: '1px solid var(--chat-border)',
        borderRadius: 'var(--chat-radius)',
        outline: 'none',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'flex-start', gap: 10 }}>
        <div
          style={{
            width: 28,
            height: 28,
            borderRadius: 6,
            background: 'var(--chat-accent)',
            color: '#fff',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            flexShrink: 0,
          }}
          aria-hidden
        >
          <KeyRound size={15} strokeWidth={1.85} />
        </div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div
            style={{
              fontWeight: 600,
              fontSize: 13,
              color: 'var(--chat-text-primary)',
              marginBottom: 2,
            }}
          >
            {t('chat.panel.no_ai_banner.title', {
              defaultValue: 'AI provider key required',
            })}
          </div>
          <div
            style={{
              fontSize: 12,
              color: 'var(--chat-text-secondary)',
              lineHeight: 1.5,
            }}
          >
            {t('chat.panel.no_ai_banner.body', {
              defaultValue:
                'Add your AI provider key in Settings → AI to enable chat.',
            })}
          </div>
        </div>
      </div>
      <div
        style={{
          display: 'flex',
          gap: 8,
          marginTop: 10,
          flexWrap: 'wrap',
          justifyContent: 'flex-end',
        }}
      >
        <button
          type="button"
          onClick={onSkip}
          data-testid="floating-chat-no-ai-skip"
          style={{
            padding: '6px 12px',
            fontSize: 12,
            fontWeight: 500,
            background: 'transparent',
            color: 'var(--chat-text-secondary)',
            border: '1px solid var(--chat-border)',
            borderRadius: 'var(--chat-radius)',
            cursor: 'pointer',
          }}
        >
          {t('chat.panel.no_ai_banner.cta_skip', { defaultValue: 'Not now' })}
        </button>
        <button
          type="button"
          onClick={onConfigure}
          data-testid="floating-chat-no-ai-configure"
          style={{
            padding: '6px 14px',
            fontSize: 12,
            fontWeight: 600,
            background: 'var(--chat-accent)',
            color: '#fff',
            border: 'none',
            borderRadius: 'var(--chat-radius)',
            cursor: 'pointer',
          }}
        >
          {t('chat.panel.no_ai_banner.cta_configure', { defaultValue: 'Configure AI' })}
        </button>
      </div>
    </div>
  );
}

// ── Friendly error card (replaces inline error plain-text) ─────────────────
function ErrorCard({
  message,
  i18nKey,
  onConfigure,
  onRetry,
}: {
  message: string;
  /** When set, render the localized message for this key (non-retryable —
   *  used for permission-denied errors that would just fail on retry). */
  i18nKey?: string;
  onConfigure: () => void;
  onRetry: () => void;
}) {
  const { t } = useTranslation();
  const apiKey = isApiKeyError(message);
  // ``managerRequired`` is mutually exclusive with ``apiKey`` — it skips
  // both the Configure CTA AND the Retry CTA in favour of a static
  // explanatory variant.
  const managerRequired = i18nKey === 'chat.error.manager_required';
  const humanized = managerRequired
    ? t('chat.error.manager_required', {
        defaultValue:
          'This action requires manager-or-higher permission on this project. '
          + 'Ask a project manager or admin to perform it for you.',
      })
    : apiKey
    ? t('chat.panel.error_card.api_key', {
        defaultValue:
          'Add your AI provider key in Settings → AI to enable chat.',
      })
    : message;

  return (
    <div
      role="alert"
      data-testid="floating-chat-error-card"
      style={{
        margin: '4px 0',
        padding: 12,
        background: 'var(--chat-surface-2)',
        border: '1px solid var(--chat-tool-error, #ef4444)',
        borderRadius: 'var(--chat-radius)',
        display: 'flex',
        flexDirection: 'column',
        gap: 8,
      }}
    >
      <div style={{ display: 'flex', gap: 8, alignItems: 'flex-start' }}>
        {managerRequired ? (
          <ShieldAlert
            size={16}
            strokeWidth={1.85}
            style={{ color: 'var(--chat-tool-error, #ef4444)', flexShrink: 0, marginTop: 1 }}
            aria-hidden
          />
        ) : (
          <AlertTriangle
            size={16}
            strokeWidth={1.85}
            style={{ color: 'var(--chat-tool-error, #ef4444)', flexShrink: 0, marginTop: 1 }}
            aria-hidden
          />
        )}
        <div
          style={{
            fontSize: 13,
            color: 'var(--chat-text-primary)',
            lineHeight: 1.5,
            wordBreak: 'break-word',
            flex: 1,
            minWidth: 0,
          }}
          data-testid={
            managerRequired ? 'floating-chat-error-manager-required' : undefined
          }
        >
          {humanized}
        </div>
      </div>
      <div
        style={{
          display: 'flex',
          gap: 6,
          justifyContent: 'flex-end',
          flexWrap: 'wrap',
        }}
      >
        {managerRequired ? null : apiKey ? (
          <button
            type="button"
            onClick={onConfigure}
            data-testid="floating-chat-error-configure"
            style={{
              padding: '5px 12px',
              fontSize: 12,
              fontWeight: 600,
              background: 'var(--chat-accent)',
              color: '#fff',
              border: 'none',
              borderRadius: 'var(--chat-radius)',
              cursor: 'pointer',
              display: 'inline-flex',
              alignItems: 'center',
              gap: 5,
            }}
          >
            <KeyRound size={12} />
            {t('chat.panel.no_ai_banner.cta_configure', { defaultValue: 'Open Settings' })}
          </button>
        ) : (
          <button
            type="button"
            onClick={onRetry}
            data-testid="floating-chat-error-retry"
            style={{
              padding: '5px 12px',
              fontSize: 12,
              fontWeight: 600,
              background: 'var(--chat-accent)',
              color: '#fff',
              border: 'none',
              borderRadius: 'var(--chat-radius)',
              cursor: 'pointer',
              display: 'inline-flex',
              alignItems: 'center',
              gap: 5,
            }}
          >
            <RotateCw size={12} />
            {t('chat.panel.error_card.retry', { defaultValue: 'Retry' })}
          </button>
        )}
      </div>
    </div>
  );
}

// ── Sessions dropdown ──────────────────────────────────────────────────────
function SessionsMenu({
  open,
  onClose,
  onPick,
  onNew,
}: {
  open: boolean;
  onClose: () => void;
  onPick: (id: string) => void;
  onNew: () => void;
}) {
  const { t } = useTranslation();
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setLoading(true);
    fetchChatSessions()
      .then((res) => {
        if (cancelled) return;
        setSessions(res.items.slice(0, 10));
      })
      .catch(() => {
        if (cancelled) return;
        setSessions([]);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [open]);

  if (!open) return null;

  return (
    <div
      role="menu"
      aria-label={t('chat.panel.sessions_title', { defaultValue: 'Recent sessions' })}
      style={{
        position: 'absolute',
        top: 'calc(100% + 4px)',
        right: 8,
        width: 260,
        maxHeight: 320,
        overflowY: 'auto',
        background: 'var(--chat-bg)',
        border: '1px solid var(--chat-border)',
        borderRadius: 8,
        boxShadow: '0 10px 24px rgba(0,0,0,0.15)',
        zIndex: 10,
      }}
    >
      <button
        type="button"
        onClick={() => {
          onNew();
          onClose();
        }}
        style={{
          width: '100%',
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          padding: '8px 12px',
          background: 'transparent',
          border: 'none',
          borderBottom: '1px solid var(--chat-border-subtle)',
          cursor: 'pointer',
          fontSize: 13,
          color: 'var(--chat-text-primary)',
          textAlign: 'left',
        }}
      >
        <MessageSquarePlus size={14} />
        {t('chat.panel.new_session', { defaultValue: 'New conversation' })}
      </button>
      <div
        style={{
          fontSize: 11,
          fontWeight: 600,
          color: 'var(--chat-text-tertiary)',
          padding: '8px 12px 4px',
          textTransform: 'uppercase',
          letterSpacing: 0.5,
        }}
      >
        {t('chat.panel.sessions_title', { defaultValue: 'Recent sessions' })}
      </div>
      {loading && (
        <div style={{ padding: '8px 12px', fontSize: 12, color: 'var(--chat-text-tertiary)' }}>
          {t('common.loading', { defaultValue: 'Loading...' })}
        </div>
      )}
      {!loading && sessions.length === 0 && (
        <div style={{ padding: '8px 12px', fontSize: 12, color: 'var(--chat-text-tertiary)' }}>
          {t('chat.panel.no_sessions', { defaultValue: 'No previous sessions yet.' })}
        </div>
      )}
      {sessions.map((s) => (
        <button
          key={s.id}
          type="button"
          onClick={() => {
            onPick(s.id);
            onClose();
          }}
          style={{
            width: '100%',
            display: 'block',
            padding: '6px 12px',
            background: 'transparent',
            border: 'none',
            cursor: 'pointer',
            fontSize: 12,
            color: 'var(--chat-text-primary)',
            textAlign: 'left',
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
          }}
          onMouseEnter={(e) => {
            (e.currentTarget as HTMLButtonElement).style.background = 'var(--chat-surface-2)';
          }}
          onMouseLeave={(e) => {
            (e.currentTarget as HTMLButtonElement).style.background = 'transparent';
          }}
          title={s.title}
        >
          {s.title || t('chat.panel.untitled', { defaultValue: '(untitled)' })}
        </button>
      ))}
    </div>
  );
}

// ── Main panel ─────────────────────────────────────────────────────────────
export function FloatingChatPanel() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const location = useLocation();
  const isOpen = useFloatingChatStore((s) => s.isOpen);
  const close = useFloatingChatStore((s) => s.close);
  const activeSessionId = useFloatingChatStore((s) => s.activeSessionId);
  const setActiveSession = useFloatingChatStore((s) => s.setActiveSession);
  const bumpUnread = useFloatingChatStore((s) => s.bumpUnread);
  const onboardingBannerDismissed = useFloatingChatStore(
    (s) => s.onboardingBannerDismissed,
  );
  const dismissOnboardingBanner = useFloatingChatStore(
    (s) => s.dismissOnboardingBanner,
  );
  const isMobile = useIsMobileViewport(640);
  const resolvedTheme = useThemeStore((s) => s.resolved);
  const activeProjectId = useProjectContextStore((s) => s.activeProjectId);
  // Role is decoded from the JWT on login (useAuthStore). Drives the
  // chip-lock UX — backend always re-checks via ``check_tool_permission``.
  const userRole = useAuthStore((s) => s.userRole);
  const canWrite = isManagerOrAbove(userRole);

  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const [aiConfigured, setAiConfigured] = useState<boolean | null>(null);
  const [value, setValue] = useState('');
  const [sessionsOpen, setSessionsOpen] = useState(false);
  const [title, setTitle] = useState<string>(
    t('chat.panel.title_default', { defaultValue: 'AI assistant' }),
  );

  const abortRef = useRef<AbortController | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Trap focus inside the panel while it is open so Tab navigation cannot
  // escape into the rest of the page (a11y requirement).
  useFocusTrap(containerRef, isOpen);

  // ESC closes the panel.
  useEffect(() => {
    if (!isOpen) return;
    const onKey = (e: globalThis.KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.stopPropagation();
        close();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [isOpen, close]);

  // Focus the textarea right after the panel opens.
  useEffect(() => {
    if (!isOpen) return;
    const id = window.setTimeout(() => textareaRef.current?.focus(), 80);
    return () => window.clearTimeout(id);
  }, [isOpen]);

  // Auto-scroll on new messages.
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: isStreaming ? 'auto' : 'smooth' });
  }, [messages, isStreaming]);

  // Probe AI configuration (so we can show the onboarding card instead of
  // hitting the API with a 500).
  //
  // Re-fetches on every panel open AND on the `oe:ai-settings-updated`
  // window event so that the banner disappears immediately after the user
  // saves a key — no panel-close-and-reopen dance needed.
  const refreshAiConfigured = useCallback(() => {
    let cancelled = false;
    aiApi
      .getSettings()
      .then((settings: AISettings) => {
        if (cancelled) return;
        const hasKey =
          settings.anthropic_api_key_set ||
          settings.openai_api_key_set ||
          settings.gemini_api_key_set ||
          settings.openrouter_api_key_set ||
          settings.mistral_api_key_set ||
          settings.groq_api_key_set ||
          settings.deepseek_api_key_set ||
          settings.cohere_api_key_set;
        setAiConfigured(hasKey);
      })
      .catch(() => {
        if (!cancelled) setAiConfigured(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!isOpen) return;
    const cleanup = refreshAiConfigured();
    return cleanup;
  }, [isOpen, refreshAiConfigured]);

  useEffect(() => {
    const handler = (): void => {
      refreshAiConfigured();
    };
    window.addEventListener('oe:ai-settings-updated', handler);
    return () => window.removeEventListener('oe:ai-settings-updated', handler);
  }, [refreshAiConfigured]);

  const sendMessage = useCallback(
    (text: string) => {
      const trimmed = text.trim();
      if (!trimmed || isStreaming) return;
      if (trimmed.length > HARD_LIMIT) return;

      if (aiConfigured === false) {
        const userMsg: ChatMessage = {
          id: uid(),
          role: 'user',
          content: trimmed,
          ts: new Date(),
        };
        const onboardingMsg: ChatMessage = {
          id: uid(),
          role: 'assistant',
          content: '',
          ts: new Date(),
          errorText: t('chat.panel.error_card.api_key', {
            defaultValue:
              'AI provider needs a key - configure it in Settings to keep chatting.',
          }),
          lastUserPrompt: trimmed,
        };
        setMessages((prev) => [...prev, userMsg, onboardingMsg]);
        setValue('');
        return;
      }

      const userMsg: ChatMessage = {
        id: uid(),
        role: 'user',
        content: trimmed,
        ts: new Date(),
      };
      const aiMsg: ChatMessage = {
        id: uid(),
        role: 'assistant',
        content: '',
        toolCalls: [],
        ts: new Date(),
        lastUserPrompt: trimmed,
      };

      setMessages((prev) => [...prev, userMsg, aiMsg]);
      setValue('');
      setIsStreaming(true);

      const aiMsgId = aiMsg.id;
      const token = useAuthStore.getState().accessToken;
      const controller = new AbortController();
      abortRef.current = controller;

      (async () => {
        try {
          const response = await fetch('/api/v1/erp_chat/stream/', {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
              ...(token ? { Authorization: `Bearer ${token}` } : {}),
            },
            body: JSON.stringify({
              message: trimmed,
              session_id: activeSessionId,
              project_id: activeProjectId,
            }),
            signal: controller.signal,
          });

          if (!response.ok) {
            const errText = await response.text().catch(() => 'Unknown error');
            // Try to surface a useful message — JSON {detail} from FastAPI,
            // else raw body. If the body contains "api key" the ErrorCard
            // automatically swaps to the "Configure AI" CTA.
            let humanized = errText;
            try {
              const parsed = JSON.parse(errText);
              if (parsed && typeof parsed === 'object' && parsed.detail) {
                humanized = String(parsed.detail);
              }
            } catch {
              // Plain-text body — keep as-is.
            }
            const finalMsg = `${response.status} - ${humanized}`;
            setMessages((prev) =>
              prev.map((m) =>
                m.id === aiMsgId ? { ...m, errorText: finalMsg } : m,
              ),
            );
            // If a 401/403 surfaced, the user's key is likely stale or
            // missing — re-probe so the next interaction shows the banner.
            if (response.status === 401 || response.status === 403) {
              refreshAiConfigured();
            }
            if (!useFloatingChatStore.getState().isOpen) bumpUnread();
            setIsStreaming(false);
            return;
          }

          const reader = response.body?.getReader();
          if (!reader) {
            setIsStreaming(false);
            return;
          }

          const decoder = new TextDecoder();
          let buffer = '';
          let currentEvent = '';

          while (true) {
            const { done, value: chunk } = await reader.read();
            if (done) break;

            buffer += decoder.decode(chunk, { stream: true });
            const lines = buffer.split('\n');
            buffer = lines.pop() ?? '';

            for (const rawLine of lines) {
              const line = rawLine.replace(/\r$/, '');
              if (line.trim() === '') {
                currentEvent = '';
                continue;
              }
              if (line.startsWith('event:')) {
                currentEvent = line.slice(6).trim();
                continue;
              }
              if (!line.startsWith('data:')) continue;

              const jsonStr = line.slice(5).trim();
              if (!jsonStr || jsonStr === '[DONE]') continue;

              let payload: Record<string, unknown>;
              try {
                payload = JSON.parse(jsonStr) as Record<string, unknown>;
              } catch {
                continue;
              }

              switch (currentEvent) {
                case 'session_id': {
                  const sid = payload.session_id as string | undefined;
                  if (sid) setActiveSession(sid);
                  break;
                }
                case 'text': {
                  const content = payload.content as string | undefined;
                  if (content) {
                    setMessages((prev) =>
                      prev.map((m) =>
                        m.id === aiMsgId ? { ...m, content: m.content + content } : m,
                      ),
                    );
                  }
                  break;
                }
                case 'tool_start': {
                  const toolName = (payload.tool as string | undefined) ?? 'unknown';
                  const toolCall: ToolCallInfo = {
                    id: uid(),
                    name: toolName,
                    status: 'running',
                    input: payload.args as Record<string, unknown> | undefined,
                    startedAt: Date.now(),
                  };
                  setMessages((prev) =>
                    prev.map((m) =>
                      m.id === aiMsgId
                        ? { ...m, toolCalls: [...(m.toolCalls ?? []), toolCall] }
                        : m,
                    ),
                  );
                  break;
                }
                case 'tool_result': {
                  const result = payload.result as ToolCallInfo['result'] | undefined;
                  const isErrorResult = result?.renderer === 'error';
                  // The backend's permission-denied card carries a
                  // machine-readable ``i18n_key`` in ``data`` — pluck it
                  // out so the ErrorCard can render the localized message
                  // and switch to the non-retryable variant.
                  const errorData =
                    isErrorResult && result?.data && typeof result.data === 'object'
                      ? (result.data as Record<string, unknown>)
                      : null;
                  const errorI18nKey =
                    typeof errorData?.i18n_key === 'string'
                      ? (errorData.i18n_key as string)
                      : undefined;
                  setMessages((prev) =>
                    prev.map((m) => {
                      if (m.id !== aiMsgId) return m;
                      let matched = false;
                      const toolCalls = (m.toolCalls ?? [])
                        .slice()
                        .reverse()
                        .map((tc) => {
                          if (!matched && tc.status === 'running') {
                            matched = true;
                            return {
                              ...tc,
                              status: (isErrorResult ? 'error' : 'done') as
                                | 'error'
                                | 'done',
                              result,
                              durationMs: Date.now() - tc.startedAt,
                            };
                          }
                          return tc;
                        })
                        .reverse();
                      const next: typeof m = { ...m, toolCalls };
                      if (isErrorResult && !m.errorText) {
                        // Promote the error renderer's summary or data
                        // string into a friendly card.
                        const errMsg =
                          (result?.summary as string | undefined) ??
                          (typeof result?.data === 'string'
                            ? (result.data as string)
                            : typeof errorData?.message === 'string'
                            ? (errorData.message as string)
                            : 'Tool returned an error');
                        next.errorText = errMsg;
                        if (errorI18nKey) next.errorI18nKey = errorI18nKey;
                      }
                      return next;
                    }),
                  );
                  break;
                }
                case 'error': {
                  const errMsg = (payload.message as string | undefined) ?? 'Unknown error';
                  setMessages((prev) =>
                    prev.map((m) =>
                      m.id === aiMsgId
                        ? {
                            ...m,
                            errorText: errMsg,
                            toolCalls: (m.toolCalls ?? []).map((tc) =>
                              tc.status === 'running'
                                ? {
                                    ...tc,
                                    status: 'error' as const,
                                    durationMs: Date.now() - tc.startedAt,
                                  }
                                : tc,
                            ),
                          }
                        : m,
                    ),
                  );
                  if (isApiKeyError(errMsg)) refreshAiConfigured();
                  break;
                }
                case 'done': {
                  break;
                }
              }
            }
          }
        } catch (err: unknown) {
          if (err instanceof DOMException && err.name === 'AbortError') {
            // user aborted — silent
          } else {
            const errorMsg = err instanceof Error ? err.message : 'Connection failed';
            setMessages((prev) =>
              prev.map((m) =>
                m.id === aiMsgId ? { ...m, errorText: errorMsg } : m,
              ),
            );
          }
        } finally {
          setIsStreaming(false);
          abortRef.current = null;
          if (!useFloatingChatStore.getState().isOpen) bumpUnread();
        }
      })();
    },
    [
      isStreaming,
      activeSessionId,
      activeProjectId,
      aiConfigured,
      bumpUnread,
      setActiveSession,
      refreshAiConfigured,
      t,
    ],
  );

  const handleConfigureAI = useCallback(() => {
    close();
    navigate('/settings?tab=ai');
  }, [close, navigate]);

  const handleRetryFromError = useCallback(
    (failedMessageId: string, prompt: string) => {
      // Drop the failed assistant message (and its preceding user echo if it
      // matches the prompt) so the retry doesn't pile up duplicates.
      setMessages((prev) => {
        const failedIdx = prev.findIndex((m) => m.id === failedMessageId);
        if (failedIdx === -1) return prev;
        const prior = failedIdx > 0 ? prev[failedIdx - 1] : undefined;
        const dropFrom =
          prior && prior.role === 'user' && prior.content === prompt
            ? failedIdx - 1
            : failedIdx;
        return prev.slice(0, dropFrom);
      });
      sendMessage(prompt);
    },
    [sendMessage],
  );

  const handleChange = useCallback((e: ChangeEvent<HTMLTextAreaElement>) => {
    setValue(e.target.value);
    const el = e.target;
    el.style.height = 'auto';
    el.style.height = Math.min(el.scrollHeight, 160) + 'px';
  }, []);

  const handleKeyDown = useCallback(
    (e: KeyboardEvent<HTMLTextAreaElement>) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendMessage(value);
      }
    },
    [value, sendMessage],
  );

  const newSession = useCallback(() => {
    if (abortRef.current) abortRef.current.abort();
    setMessages([]);
    setIsStreaming(false);
    setActiveSession(null);
    setTitle(t('chat.panel.title_default', { defaultValue: 'AI assistant' }));
  }, [setActiveSession, t]);

  const pickSession = useCallback(
    (id: string) => {
      // We don't pre-load past messages here (keeps the widget light) — the
      // backend resumes context server-side via session_id. The user will see
      // their next reply in the context of that session.
      if (abortRef.current) abortRef.current.abort();
      setMessages([]);
      setIsStreaming(false);
      setActiveSession(id);
    },
    [setActiveSession],
  );

  const charCount = value.length;
  const overSoft = charCount > SOFT_LIMIT;
  const overHard = charCount > HARD_LIMIT;
  const canSend = value.trim().length > 0 && !isStreaming && !overHard;

  const widthClass = isMobile ? 'w-full' : 'w-[400px]';
  const heightClass = isMobile ? 'h-full' : 'h-full max-h-screen';

  const panelTitle = useMemo(() => title, [title]);

  if (!isOpen) return null;

  return (
    <>
      {/* Mobile backdrop — desktop has no backdrop so the user can still see /
          interact with the page next to the chat. */}
      {isMobile && (
        <div
          aria-hidden
          className="fixed inset-0 z-50 bg-black/40 backdrop-blur-sm animate-fade-in"
          onClick={close}
        />
      )}
      <div
        ref={containerRef}
        role="dialog"
        aria-modal={isMobile ? 'true' : 'false'}
        aria-label={panelTitle}
        data-testid="floating-chat-panel"
        data-chat-theme={resolvedTheme}
        tabIndex={-1}
        className={[
          'fixed z-50',
          'top-0 right-0',
          widthClass,
          heightClass,
          'flex flex-col',
          'shadow-2xl border-l border-border-light',
          'animate-slide-in-right',
        ].join(' ')}
        style={{
          background: 'var(--chat-bg)',
          color: 'var(--chat-text-primary)',
        }}
      >
        {/* Header */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 8,
            padding: '10px 12px',
            borderBottom: '1px solid var(--chat-border)',
            background: 'var(--chat-surface-1)',
            position: 'relative',
          }}
        >
          <input
            value={panelTitle}
            onChange={(e) => setTitle(e.target.value)}
            aria-label={t('chat.panel.title_edit', { defaultValue: 'Conversation title' })}
            style={{
              flex: 1,
              fontSize: 13,
              fontWeight: 600,
              background: 'transparent',
              border: 'none',
              outline: 'none',
              color: 'var(--chat-text-primary)',
              padding: 0,
            }}
          />
          <button
            type="button"
            onClick={() => setSessionsOpen((v) => !v)}
            aria-label={t('chat.panel.sessions_title', { defaultValue: 'Recent sessions' })}
            title={t('chat.panel.sessions_title', { defaultValue: 'Recent sessions' })}
            style={{
              padding: 6,
              background: 'transparent',
              border: 'none',
              cursor: 'pointer',
              color: 'var(--chat-text-secondary)',
              borderRadius: 4,
            }}
            data-testid="floating-chat-sessions-toggle"
          >
            <History size={15} />
          </button>
          <button
            type="button"
            onClick={() => {
              close();
              navigate('/chat');
            }}
            aria-label={t('chat.panel.open_full', { defaultValue: 'Open full page' })}
            title={t('chat.panel.open_full', { defaultValue: 'Open full page' })}
            style={{
              padding: 6,
              background: 'transparent',
              border: 'none',
              cursor: 'pointer',
              color: 'var(--chat-text-secondary)',
              borderRadius: 4,
            }}
            data-testid="floating-chat-open-full"
          >
            <ExternalLink size={15} />
          </button>
          <button
            type="button"
            onClick={close}
            aria-label={t('common.close', { defaultValue: 'Close' })}
            style={{
              padding: 6,
              background: 'transparent',
              border: 'none',
              cursor: 'pointer',
              color: 'var(--chat-text-secondary)',
              borderRadius: 4,
            }}
            data-testid="floating-chat-close"
          >
            <X size={16} />
          </button>
          <SessionsMenu
            open={sessionsOpen}
            onClose={() => setSessionsOpen(false)}
            onPick={pickSession}
            onNew={newSession}
          />
        </div>

        {/* Body — aria-live=polite so screen readers announce streaming
            assistant text + tool results as they arrive */}
        <div
          ref={scrollRef}
          role="log"
          aria-live="polite"
          aria-relevant="additions text"
          aria-label={t('chat.panel.transcript_aria', {
            defaultValue: 'Conversation transcript',
          })}
          style={{
            flex: 1,
            overflowY: 'auto',
            padding: messages.length === 0 ? 0 : '12px 12px 4px',
            display: 'flex',
            flexDirection: 'column',
            gap: 6,
          }}
        >
          {messages.length === 0 ? (
            <EmptyState
              onPick={sendMessage}
              pathname={location.pathname}
              canWrite={canWrite}
            />
          ) : (
            <>
              {messages.map((msg) => (
                <MessageRow
                  key={msg.id}
                  msg={msg}
                  onConfigureAI={handleConfigureAI}
                  onRetry={handleRetryFromError}
                />
              ))}
              {isStreaming && (
                <div
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 6,
                    fontSize: 12,
                    color: 'var(--chat-text-tertiary)',
                    padding: '4px 4px 8px',
                  }}
                >
                  <span className="floating-chat-dots" aria-hidden>
                    <span />
                    <span />
                    <span />
                  </span>
                  {t('chat.panel.streaming', { defaultValue: 'Thinking...' })}
                </div>
              )}
              <div ref={bottomRef} />
            </>
          )}
        </div>

        {/* Proactive "no AI configured" onboarding banner — visible above the
            input until the user either configures a key (event-driven re-fetch
            clears it) or hits Skip for this browser session. */}
        {aiConfigured === false && !onboardingBannerDismissed && (
          <NoAIBanner
            onConfigure={handleConfigureAI}
            onSkip={dismissOnboardingBanner}
          />
        )}

        {/* Input */}
        <div
          style={{
            borderTop: '1px solid var(--chat-border-subtle)',
            padding: '10px 12px 12px',
            background: 'var(--chat-surface-1)',
          }}
        >
          <textarea
            ref={textareaRef}
            value={value}
            onChange={handleChange}
            onKeyDown={handleKeyDown}
            disabled={isStreaming}
            data-testid="floating-chat-input"
            placeholder={t('chat.panel.input_placeholder', {
              defaultValue: 'Ask anything about your projects, BOQs, costs, clashes...',
            })}
            rows={1}
            style={{
              width: '100%',
              resize: 'none',
              padding: '8px 10px',
              fontSize: 13,
              fontFamily: 'var(--chat-font-body)',
              color: 'var(--chat-text-primary)',
              background: 'var(--chat-surface-2)',
              border: `1px solid ${
                overHard
                  ? 'var(--chat-tool-error, #ef4444)'
                  : overSoft
                  ? '#f59e0b'
                  : 'var(--chat-border)'
              }`,
              borderRadius: 'var(--chat-radius)',
              outline: 'none',
              lineHeight: 1.5,
              maxHeight: 160,
              overflow: 'auto',
            }}
          />
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              marginTop: 6,
              fontSize: 11,
              // Promote to --chat-text-secondary for WCAG AA contrast on
              // a near-white surface (the input bar is --chat-surface-1).
              color: 'var(--chat-text-secondary)',
              fontFamily: 'var(--chat-font-mono)',
            }}
          >
            <span>
              {t('chat.kbd_hint', { defaultValue: 'Enter to send · Shift+Enter for newline' })}
            </span>
            <span
              style={{
                color: overHard
                  ? 'var(--chat-tool-error, #ef4444)'
                  : overSoft
                  ? '#b45309' // darker amber for WCAG AA against light surface
                  : 'var(--chat-text-secondary)',
              }}
            >
              {overHard
                ? t('chat.panel.token_over', { defaultValue: 'Too long - please shorten' })
                : overSoft
                ? t('chat.panel.token_warn', { defaultValue: 'Long message' })
                : `${charCount}/${HARD_LIMIT}`}
            </span>
          </div>
          <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 8 }}>
            <button
              type="button"
              onClick={() => sendMessage(value)}
              disabled={!canSend}
              data-testid="floating-chat-send"
              aria-label={t('chat.panel.send', { defaultValue: 'Send' })}
              style={{
                padding: '6px 16px',
                fontSize: 13,
                fontWeight: 600,
                fontFamily: 'var(--chat-font-body)',
                color: canSend ? '#ffffff' : 'var(--chat-text-tertiary)',
                background: canSend ? 'var(--chat-accent)' : 'var(--chat-surface-3)',
                border: 'none',
                borderRadius: 'var(--chat-radius)',
                cursor: canSend ? 'pointer' : 'not-allowed',
                transition: 'background 0.15s',
              }}
            >
              {t('chat.panel.send', { defaultValue: 'Send' })}
            </button>
          </div>
        </div>

        {/* Local styles — kept inline so the component is fully self-contained
            and doesn't need a CSS import that vite has to look up. */}
        <style>{`
          @keyframes floatingChatDot {
            0%, 80%, 100% { opacity: 0.2; transform: scale(0.8); }
            40%           { opacity: 1;   transform: scale(1); }
          }
          .floating-chat-dots {
            display: inline-flex;
            gap: 3px;
            align-items: center;
          }
          .floating-chat-dots > span {
            width: 5px;
            height: 5px;
            border-radius: 50%;
            background: var(--chat-accent);
            animation: floatingChatDot 1.2s infinite ease-in-out both;
          }
          .floating-chat-dots > span:nth-child(2) { animation-delay: 0.15s; }
          .floating-chat-dots > span:nth-child(3) { animation-delay: 0.3s; }
          @keyframes slide-in-right {
            from { transform: translateX(100%); opacity: 0.5; }
            to   { transform: translateX(0);   opacity: 1;   }
          }
          .animate-slide-in-right {
            /* Material standard easing - 220ms slide for the floating chat panel */
            animation: slide-in-right 220ms cubic-bezier(0.4, 0, 0.2, 1);
          }
          @keyframes fade-in {
            from { opacity: 0; }
            to   { opacity: 1; }
          }
          .animate-fade-in {
            animation: fade-in 150ms cubic-bezier(0.4, 0, 0.2, 1);
          }
        `}</style>
      </div>
    </>
  );
}

// ── Individual message row ─────────────────────────────────────────────────
function MessageRow({
  msg,
  onConfigureAI,
  onRetry,
}: {
  msg: ChatMessage;
  onConfigureAI: () => void;
  onRetry: (msgId: string, prompt: string) => void;
}) {
  const html = useMemo(
    () =>
      msg.content ? DOMPurify.sanitize(renderMarkdown(msg.content), SANITIZE_CONFIG) : '',
    [msg.content],
  );

  if (msg.role === 'user') {
    return (
      <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
        <div
          style={{
            background: 'var(--chat-surface-3)',
            color: 'var(--chat-text-primary)',
            padding: '8px 12px',
            borderRadius: '14px 14px 4px 14px',
            maxWidth: '85%',
            fontSize: 13,
            lineHeight: 1.55,
            wordBreak: 'break-word',
            whiteSpace: 'pre-wrap',
          }}
        >
          {msg.content}
        </div>
      </div>
    );
  }

  if (msg.role === 'system') {
    return (
      <div
        style={{
          textAlign: 'center',
          fontSize: 11,
          color: 'var(--chat-text-tertiary)',
          fontFamily: 'var(--chat-font-mono)',
          padding: '2px 0',
        }}
      >
        {msg.content}
      </div>
    );
  }

  return (
    <div
      style={{
        borderLeft: '2px solid var(--chat-accent)',
        paddingLeft: 10,
        maxWidth: '92%',
      }}
    >
      {msg.toolCalls && msg.toolCalls.length > 0 && (
        <div style={{ marginBottom: 4 }}>
          {msg.toolCalls.map((tc) => (
            <ToolCallEntry key={tc.id} tool={tc} />
          ))}
        </div>
      )}
      {html && (
        <div
          style={{
            color: 'var(--chat-text-primary)',
            fontSize: 13,
            lineHeight: 1.6,
            wordBreak: 'break-word',
          }}
          dangerouslySetInnerHTML={{ __html: html }}
        />
      )}
      {msg.errorText && (
        <ErrorCard
          message={msg.errorText}
          i18nKey={msg.errorI18nKey}
          onConfigure={onConfigureAI}
          onRetry={() => {
            if (msg.lastUserPrompt) onRetry(msg.id, msg.lastUserPrompt);
          }}
        />
      )}
    </div>
  );
}

// Helper re-export so the AppLayout import is a single line.
export default FloatingChatPanel;
