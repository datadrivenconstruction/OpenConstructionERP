// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Floating chat panel — the AI dock. A side panel on the inline-end edge
 * (right in LTR, left in RTL) that talks to the same backend SSE endpoint as
 * the full-page chat. Reuses the renderer registry so tool results render
 * exactly the same way as on /chat.
 *
 * Two modes, decided by the screen (useDockGeometry in useFloatingChat.ts):
 *   - push: wide screens. The page reflows next to the dock through
 *     `--oe-ai-dock-offset`; not modal, no backdrop, Tab moves freely, and
 *     Escape closes only when focus is inside the dock.
 *   - overlay: everything else. Backdrop, modal, focus kept inside; full
 *     width below 640px.
 * The width is resizable from the handle on the dock's inline-start edge.
 *
 * Escape contract for anything rendered inside the dock: a component that
 * consumes Escape itself (an inline edit form, a menu) must call
 * `preventDefault()` on the event, and the dock then leaves it alone.
 *
 * Under the header a slim row holds two tabs, Chat and Changes (the
 * assistant's ledger, mounted the first time it is opened), and the project
 * the assistant works in. The assistant never writes on its own: its tools
 * return PROPOSALS, rendered as cards with Apply / Edit / Reject, and a tray
 * above the composer counts the ones still waiting while the conversation
 * has any.
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
  useId,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type ChangeEvent,
  type KeyboardEvent,
  type PointerEvent as ReactPointerEvent,
  type ReactNode,
} from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import clsx from 'clsx';
import {
  X,
  ArrowUp,
  Check,
  ChevronDown,
  ChevronRight,
  CircleAlert,
  ExternalLink,
  HelpCircle,
  History,
  MessageSquarePlus,
  Loader2,
  KeyRound,
  AlertTriangle,
  PenLine,
  RotateCw,
  Search,
  ShieldAlert,
  ShieldCheck,
  Sparkles,
} from 'lucide-react';
import DOMPurify from 'isomorphic-dompurify';
import { useAuthStore } from '@/stores/useAuthStore';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { useThemeStore } from '@/stores/useThemeStore';
import { aiApi, type AISettings } from '@/features/ai/api';
import { hasLlmKey } from '@/features/ai-estimator/useAiReadiness';
import { useIsRTL } from '@/shared/hooks/useIsRTL';
import { TruncationNotice } from '@/shared/ui/TruncationNotice';
import { uuid } from '@/shared/lib/browser';
import {
  DOCK_MIN_WIDTH,
  DOCK_RESIZING_ATTR,
  applyDockLayout,
  isAnotherModalOpen,
  isApplePlatform,
  isDockShortcut,
  isEditableElement,
  isFloatingChatHiddenOn,
  useDockFocus,
  useDockGeometry,
  useDockLayoutSync,
  useDockPresence,
  useFloatingChatStore,
  widthFromDrag,
  widthFromKey,
} from './useFloatingChat';
import { fetchChatSessions, fetchSessionMessages } from './api';
import type { ChatMessage, ChatSession, ToolCallInfo } from './types';
import { DockTabsRow, dockTabId, dockTabPanelId, type DockTab } from './DockTabsRow';
import { isProposalTool, toolLabel, toolRefusalText } from './toolLabels';
import { proposalsInTranscript, transcriptFromPersisted } from './transcript';
import { ActionsReviewTray, revealFirstWaitingAction } from './actions/ActionsReviewTray';
import { ChangesView } from './actions/ChangesView';
import { pendingActions, useLiveChatActions } from './actions/useChatActions';
import type { ChatAction } from './actions/types';

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

/** Back to the composer's own two rows once what grew it is sent. */
function resetComposerHeight(el: HTMLTextAreaElement | null): void {
  if (el) el.style.height = '';
}

function lastIndexWhere<T>(items: readonly T[], test: (item: T) => boolean): number {
  for (let i = items.length - 1; i >= 0; i -= 1) {
    if (test(items[i] as T)) return i;
  }
  return -1;
}

// No suggestion is locked by role. Chips that read like a write action used
// to be greyed out below manager, guessed from their first word, because a
// write tool used to write at once. The assistant now only PREPARES a change:
// preparing one touches nothing, and Apply runs the same checks as the
// record's own page (who may apply is decided per record, not per role
// name), so the card itself says when this person cannot apply it and who
// can. A lock here would only hide the feature from people who may still
// prepare a change and hand it to a colleague.

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
    // A question, like the rest of this group: requests to change something
    // live in the "Make a change" group above it.
    t('chat.dock.sugg_open_rfis', {
      defaultValue: 'Which RFIs are still waiting for an answer?',
    }),
    t('chat.panel.sugg_critical_path', { defaultValue: "What's the schedule critical path?" }),
  ];
}

/**
 * Example instructions for the "Make a change" group, tuned to the page.
 *
 * Each one names a change the assistant can prepare (a `propose_*` tool) in
 * the words a site manager would use with a colleague. They are examples to
 * adjust, not commands: picking one fills the composer instead of sending.
 */
function useDoSuggestions(pathname: string): string[] {
  const { t } = useTranslation();
  return useMemo(() => {
    const task = t('chat.dock.do.task', {
      defaultValue: 'Create a task: check the formwork on level 3 by Friday',
    });
    const risk = t('chat.dock.do.risk', {
      defaultValue: 'Log a risk: the steel delivery may slip by two weeks',
    });
    const rfi = t('chat.dock.do.rfi', {
      defaultValue: 'Raise an RFI: which fire rating applies to the stair doors?',
    });
    if (/^\/boq\/[^/]+/.test(pathname)) {
      return [
        t('chat.dock.do.boq_add', {
          defaultValue: 'Add a position: 25 m³ of C30/37 concrete for the ground slab',
        }),
        t('chat.dock.do.boq_quantity', {
          defaultValue: 'Set the quantity of the formwork position to 140 m²',
        }),
      ];
    }
    if (/^\/schedule(\/|$)/.test(pathname)) {
      return [
        t('chat.dock.do.schedule_progress', {
          defaultValue: 'Set the progress of the foundations activity to 60%',
        }),
        task,
      ];
    }
    if (/^\/(projects\/[^/]+\/)?tasks(\/|$)/.test(pathname)) return [task];
    if (/^\/(projects\/[^/]+\/)?rfi(\/|$)/.test(pathname)) return [rfi];
    if (/^\/risks(\/|$)/.test(pathname)) return [risk];
    if (/^\/punchlist(\/|$)/.test(pathname)) {
      return [
        t('chat.dock.do.punch', {
          defaultValue: 'Add a punch item: cracked tile in bathroom 2.04',
        }),
      ];
    }
    if (/^\/projects\/[^/]+/.test(pathname)) return [task, risk, rfi];
    return [task, risk];
  }, [pathname, t]);
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

// ── Tool calls ─────────────────────────────────────────────────────────────
/**
 * One tool call of an assistant turn.
 *
 * A prepared change is the answer, so it renders as its card with no row
 * around it. A lookup is supporting detail: one quiet line ("Looked up: BOQ
 * positions") that opens onto what was found, closed by default so the answer
 * stays in view. A change the assistant could not prepare says so, with the
 * reason, and calmly: the assistant reads the same reason and usually asks for
 * what it needs, so it is not a failure of the chat.
 */
function ToolCallEntry({ tool }: { tool: ToolCallInfo }) {
  const { t } = useTranslation();
  const bodyId = useId();
  const renderer = tool.result?.renderer;
  const RendererComp = renderer ? RENDERERS[renderer] : undefined;
  const data = tool.result?.data;
  const summary = tool.result?.summary;
  // The retired direct-write tool, still in older conversations. Its card is
  // the record it created, worth seeing without a click.
  const legacyWrite = tool.name === 'create_boq_item';
  const [open, setOpen] = useState(legacyWrite);

  if (renderer === 'action_proposal' && RendererComp && data !== undefined) {
    return (
      <div className="my-2">
        <RendererComp data={data} />
      </div>
    );
  }

  const change = legacyWrite || isProposalTool(tool.name);
  const running = tool.status === 'running';
  const failed = tool.status === 'error';
  const label = toolLabel(tool.name, t);
  let text: string;
  if (change) {
    text = running
      ? t('erp_chat.tool.preparing', { defaultValue: 'Preparing a change: {{label}}…', label })
      : failed
        ? t('erp_chat.tool.not_prepared', {
            defaultValue: 'Change not prepared: {{label}}',
            // The retired tool's label names its outcome ("created"), which a
            // failure must not repeat.
            label: legacyWrite ? toolLabel('propose_add_boq_position', t) : label,
          })
        : label;
  } else {
    text = running
      ? t('erp_chat.tool.looking_up', { defaultValue: 'Looking up: {{label}}…', label })
      : failed
        ? t('erp_chat.tool.lookup_failed', { defaultValue: 'Could not look up: {{label}}', label })
        : t('erp_chat.tool.looked_up', { defaultValue: 'Looked up: {{label}}', label });
  }
  // Why a change was not prepared, in the server's words, localized when the
  // server named a key.
  const reason = change && failed ? toolRefusalText(data, t) : null;
  const expandable = !running && !failed && !!RendererComp && data !== undefined;
  const Icon = running ? Loader2 : failed ? CircleAlert : change ? Check : Search;

  const head = (
    <>
      <Icon
        size={13}
        aria-hidden
        className={clsx(
          'mt-px shrink-0',
          running && 'animate-spin text-[color:var(--chat-tool-running)]',
          failed && 'text-[color:var(--chat-tool-error)]',
          !running && !failed && 'text-[color:var(--chat-text-secondary)]',
        )}
      />
      <span className="min-w-0 truncate font-medium">{text}</span>
      {expandable && summary && (
        <span
          className="min-w-0 flex-1 truncate text-[color:var(--chat-text-secondary)] opacity-90"
          title={summary}
        >
          · {summary}
        </span>
      )}
      {expandable && (
        <span className="ms-auto shrink-0">
          {open ? (
            <ChevronDown size={13} aria-hidden />
          ) : (
            <ChevronRight size={13} aria-hidden className="rtl:rotate-180" />
          )}
        </span>
      )}
    </>
  );

  return (
    <div
      className={clsx(
        'my-1 rounded-lg text-[12px] text-[color:var(--chat-text-secondary)]',
        reason && 'border border-[color:var(--chat-border-subtle)] bg-[color:var(--chat-surface-1)]',
      )}
      data-testid="floating-chat-tool"
      data-tool={tool.name}
      data-tool-status={tool.status}
    >
      {expandable ? (
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          aria-expanded={open}
          aria-controls={open ? bodyId : undefined}
          className="flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-start transition-colors hover:bg-[color:var(--chat-surface-2)] hover:text-[color:var(--chat-text-primary)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue"
        >
          {head}
        </button>
      ) : (
        <div className="flex items-center gap-2 px-2 py-1.5">{head}</div>
      )}
      {reason && (
        <p className="px-2 pb-2 ps-[29px] leading-snug text-[color:var(--chat-text-primary)]">{reason}</p>
      )}
      {expandable && open && RendererComp && (
        <div
          id={bodyId}
          className="mt-1 rounded-lg border border-[color:var(--chat-border-subtle)] bg-[color:var(--chat-surface-2)] p-2"
        >
          <RendererComp data={data} />
        </div>
      )}
    </div>
  );
}

// ── Empty state ────────────────────────────────────────────────────────────
function SuggestionChip({
  text,
  onPick,
  testIdSuffix,
  kind,
  describedBy,
}: {
  text: string;
  onPick: (text: string) => void;
  testIdSuffix: string;
  /** `do` is an example instruction to adjust, `ask` a question to send. */
  kind: 'do' | 'ask';
  describedBy?: string;
}) {
  const Icon = kind === 'do' ? PenLine : HelpCircle;
  return (
    <button
      type="button"
      onClick={() => onPick(text)}
      aria-describedby={describedBy}
      data-testid={`floating-chat-suggestion-${testIdSuffix}`}
      className={clsx(
        'flex w-full items-start gap-2 rounded-lg border px-3 text-start leading-snug transition-colors',
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue',
        'border-[color:var(--chat-border-subtle)] text-[color:var(--chat-text-primary)] hover:border-oe-blue',
        kind === 'do'
          ? 'bg-[color:var(--chat-bg)] py-2 text-sm shadow-xs'
          : 'bg-[color:var(--chat-surface-2)] py-1.5 text-sm',
      )}
    >
      <Icon
        size={kind === 'do' ? 14 : 13}
        aria-hidden
        className={clsx(
          'mt-px shrink-0',
          kind === 'do' ? 'text-oe-blue' : 'text-[color:var(--chat-text-secondary)]',
        )}
      />
      <span className="min-w-0 flex-1">{text}</span>
    </button>
  );
}

function GroupHeading({ id, icon, children }: { id: string; icon: ReactNode; children: ReactNode }) {
  return (
    <h3
      id={id}
      className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-[color:var(--chat-text-secondary)]"
    >
      {icon}
      {children}
    </h3>
  );
}

/**
 * What a first-time user sees: what the assistant does in one sentence, the
 * three steps of every change, and two groups of starting points. "Make a
 * change" holds example instructions for this page, which fill the composer
 * to be adjusted (a real site has its own levels and dates). "Ask a question"
 * holds questions, which are sent at once.
 */
function EmptyState({
  pathname,
  onAsk,
  onDraft,
}: {
  pathname: string;
  /** Send a question as it is. */
  onAsk: (text: string) => void;
  /** Put an example instruction into the composer. */
  onDraft: (text: string) => void;
}) {
  const { t } = useTranslation();
  const doHeadingId = useId();
  const doHintId = useId();
  const askHeadingId = useId();
  const suggestions = useDefaultSuggestions();
  const contextualSuggestions = useContextualSuggestions(pathname);
  const doSuggestions = useDoSuggestions(pathname);
  const hasContextual = contextualSuggestions.length > 0;
  const steps = [
    t('chat.dock.step_ask', { defaultValue: 'Ask' }),
    t('chat.dock.step_review', { defaultValue: 'Review' }),
    t('chat.dock.step_apply', { defaultValue: 'Apply' }),
  ];

  return (
    <div className="px-4 pb-4 pt-5" data-testid="floating-chat-empty">
      <p className="text-[15px] font-semibold leading-snug text-[color:var(--chat-text-primary)]">
        {t('chat.dock.empty_title', {
          defaultValue: 'Tell me what to do. I prepare the changes, you approve them.',
        })}
      </p>

      <ol
        aria-label={t('chat.dock.steps_label', { defaultValue: 'How it works' })}
        className="mt-3 flex flex-wrap items-center gap-x-1.5 gap-y-1"
        data-testid="floating-chat-steps"
      >
        {steps.map((step, i) => (
          <li key={i} className="flex items-center gap-1.5">
            <span className="inline-flex h-6 items-center gap-1.5 rounded-full bg-[color:var(--chat-surface-2)] pe-2.5 ps-1 text-[12px] font-medium text-[color:var(--chat-text-primary)]">
              <span
                aria-hidden
                className="inline-flex h-4 w-4 items-center justify-center rounded-full bg-oe-blue text-[10px] font-semibold leading-none text-content-inverse"
              >
                {i + 1}
              </span>
              {step}
            </span>
            {i < steps.length - 1 && (
              <ChevronRight
                size={12}
                aria-hidden
                className="shrink-0 text-[color:var(--chat-text-secondary)] rtl:rotate-180"
              />
            )}
          </li>
        ))}
      </ol>
      <p className="mt-2 flex items-center gap-1.5 text-[12px] text-[color:var(--chat-text-secondary)]">
        <ShieldCheck size={13} aria-hidden className="shrink-0" />
        {t('chat.dock.steps_note', { defaultValue: 'Every change is logged in the project history.' })}
      </p>

      <section aria-labelledby={doHeadingId} className="mt-5">
        <GroupHeading id={doHeadingId} icon={<PenLine size={12} aria-hidden />}>
          {t('chat.dock.group_do', { defaultValue: 'Make a change' })}
        </GroupHeading>
        <p id={doHintId} className="mt-0.5 text-[12px] text-[color:var(--chat-text-secondary)]">
          {t('chat.dock.group_do_hint', {
            defaultValue: 'Pick an example and adjust it before you send it.',
          })}
        </p>
        <div className="mt-2 flex flex-col gap-2" data-testid="floating-chat-do-chips">
          {doSuggestions.map((s, i) => (
            <SuggestionChip
              key={s}
              text={s}
              kind="do"
              onPick={onDraft}
              describedBy={doHintId}
              testIdSuffix={`do-${i}`}
            />
          ))}
        </div>
      </section>

      <section aria-labelledby={askHeadingId} className="mt-5">
        <GroupHeading id={askHeadingId} icon={<HelpCircle size={12} aria-hidden />}>
          {t('chat.dock.group_ask', { defaultValue: 'Ask a question' })}
        </GroupHeading>
        {/* The page's own questions come first, above the ones that work
            anywhere (the order is pinned by e2e/floating-chat-onboarding). */}
        {hasContextual && (
          <>
            <p
              className="mt-2 text-[12px] font-medium text-[color:var(--chat-text-secondary)]"
              data-testid="floating-chat-contextual-label"
            >
              {t('chat.panel.contextual_label', { defaultValue: 'For this page' })}
            </p>
            <div className="mt-1.5 flex flex-col gap-1.5" data-testid="floating-chat-contextual-chips">
              {contextualSuggestions.map((s, i) => (
                <SuggestionChip key={s} text={s} kind="ask" onPick={onAsk} testIdSuffix={`ctx-${i}`} />
              ))}
            </div>
            <p className="mt-3 text-[12px] font-medium text-[color:var(--chat-text-secondary)]">
              {t('chat.panel.generic_label', { defaultValue: 'Anywhere' })}
            </p>
          </>
        )}
        <div className="mt-1.5 flex flex-col gap-1.5">
          {suggestions.map((s, i) => (
            <SuggestionChip key={s} text={s} kind="ask" onPick={onAsk} testIdSuffix={`generic-${i}`} />
          ))}
        </div>
      </section>
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

// ── A past conversation being read back ────────────────────────────────────
function HistoryLoading() {
  const { t } = useTranslation();
  return (
    <div
      role="status"
      className="flex items-center justify-center gap-2 px-4 py-10 text-[12px] text-[color:var(--chat-text-secondary)]"
      data-testid="floating-chat-history-loading"
    >
      <Loader2 size={14} aria-hidden className="animate-spin" />
      {t('chat.dock.history_loading', { defaultValue: 'Loading the conversation…' })}
    </div>
  );
}

function HistoryError({ onRetry, onNew }: { onRetry: () => void; onNew: () => void }) {
  const { t } = useTranslation();
  return (
    <div
      role="alert"
      className="m-1 flex items-start gap-2.5 rounded-lg border border-[color:var(--chat-border)] bg-[color:var(--chat-surface-1)] px-3 py-3"
      data-testid="floating-chat-history-error"
    >
      <AlertTriangle size={16} aria-hidden className="mt-px shrink-0 text-[color:var(--chat-tool-error)]" />
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium text-[color:var(--chat-text-primary)]">
          {t('chat.dock.history_failed', { defaultValue: 'This conversation could not be loaded.' })}
        </p>
        <div className="mt-2.5 flex flex-wrap gap-2">
          <button
            type="button"
            onClick={onRetry}
            data-testid="floating-chat-history-retry"
            className="inline-flex h-8 items-center gap-1.5 rounded-md bg-oe-blue px-3 text-[12px] font-semibold text-content-inverse transition-opacity hover:opacity-90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue focus-visible:ring-offset-2"
          >
            <RotateCw size={12} aria-hidden />
            {t('chat.dock.history_retry', { defaultValue: 'Try again' })}
          </button>
          <button
            type="button"
            onClick={onNew}
            className="inline-flex h-8 items-center gap-1.5 rounded-md border border-[color:var(--chat-border)] px-3 text-[12px] font-medium text-[color:var(--chat-text-primary)] transition-colors hover:bg-[color:var(--chat-surface-2)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue"
          >
            <MessageSquarePlus size={12} aria-hidden />
            {t('chat.dock.history_new', { defaultValue: 'Start a new chat' })}
          </button>
        </div>
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
  activeId,
}: {
  open: boolean;
  onClose: () => void;
  onPick: (id: string, title: string) => void;
  onNew: () => void;
  /** The conversation on screen, marked in the list. */
  activeId: string | null;
}) {
  const { t } = useTranslation();
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  // Cut twice over: the route hands back 20 sessions and this menu keeps 10.
  // Both cuts are invisible without the server's own count.
  const [sessionsTotal, setSessionsTotal] = useState(0);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setLoading(true);
    fetchChatSessions()
      .then((res) => {
        if (cancelled) return;
        setSessions(res.items.slice(0, 10));
        setSessionsTotal(res.total ?? res.items.length);
      })
      .catch(() => {
        if (cancelled) return;
        setSessions([]);
        setSessionsTotal(0);
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
        // Logical, so the menu hangs under the header buttons in RTL too.
        insetInlineEnd: 8,
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
      {sessions.map((s) => {
        const current = s.id === activeId;
        return (
          <button
            key={s.id}
            type="button"
            onClick={() => {
              onPick(s.id, s.title);
              onClose();
            }}
            aria-current={current ? 'true' : undefined}
            data-testid={`floating-chat-session-${s.id}`}
            style={{
              width: '100%',
              display: 'block',
              padding: '6px 12px',
              background: 'transparent',
              border: 'none',
              cursor: 'pointer',
              fontSize: 12,
              fontWeight: current ? 600 : 400,
              color: 'var(--chat-text-primary)',
              textAlign: 'start',
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
        );
      })}
      {!loading && sessions.length > 0 && (
        <div style={{ padding: '4px 12px 8px' }}>
          <TruncationNotice page={{ items: sessions, total: sessionsTotal }} />
        </div>
      )}
    </div>
  );
}

// ── Dock chrome ────────────────────────────────────────────────────────────

/** DOM id of the dock, the target of the resize handle's aria-controls. */
const DOCK_ELEMENT_ID = 'oe-ai-dock';

function DockHeaderButton({
  onClick,
  label,
  testId,
  expanded,
  children,
}: {
  onClick: () => void;
  label: string;
  testId: string;
  /** Set for a button that opens a menu; omitted otherwise. */
  expanded?: boolean;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={label}
      title={label}
      aria-expanded={expanded}
      aria-haspopup={expanded === undefined ? undefined : 'menu'}
      data-testid={testId}
      className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-md text-[color:var(--chat-text-secondary)] transition-colors hover:bg-[color:var(--chat-surface-2)] hover:text-[color:var(--chat-text-primary)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue"
    >
      {children}
    </button>
  );
}

/**
 * The resize handle on the dock's inline-start edge: a 6px hit zone whose
 * grip shows on hover and on keyboard focus.
 *
 * Pointer: drag with pointer capture, throttled to one update per animation
 * frame, previewed straight into the DOM (`onPreview`) and committed to the
 * store once on release. While dragging, `html[data-ai-dock-resizing]` turns
 * off the page's padding transition so the page follows the cursor.
 * Keyboard: Left/Right move 16px (the arrow towards the page widens, so they
 * swap in RTL), Home/End jump to the narrowest/widest. Double-click resets.
 */
function DockResizeHandle({
  width,
  maxWidth,
  controlsId,
  onPreview,
}: {
  width: number;
  maxWidth: number;
  controlsId: string;
  onPreview: (width: number) => void;
}) {
  const { t } = useTranslation();
  const isRTL = useIsRTL();
  const setWidth = useFloatingChatStore((s) => s.setWidth);
  const resetWidth = useFloatingChatStore((s) => s.resetWidth);
  const [dragging, setDragging] = useState(false);
  const dragRef = useRef<{
    pointerId: number;
    startX: number;
    startWidth: number;
    latestX: number;
    frame: number | null;
  } | null>(null);

  const widthForDrag = useCallback(
    (drag: { startX: number; startWidth: number; latestX: number }) =>
      widthFromDrag({
        startWidth: drag.startWidth,
        startX: drag.startX,
        currentX: drag.latestX,
        rtl: isRTL,
        maxWidth,
      }),
    [isRTL, maxWidth],
  );

  const finishDrag = useCallback(() => {
    const drag = dragRef.current;
    if (!drag) return;
    dragRef.current = null;
    if (drag.frame !== null) window.cancelAnimationFrame(drag.frame);
    const finalWidth = widthForDrag(drag);
    // Preview first: if the final width equals the stored one the store
    // does not change and React does not re-render, so the DOM must already
    // hold it rather than the last throttled frame.
    onPreview(finalWidth);
    document.documentElement.removeAttribute(DOCK_RESIZING_ATTR);
    setDragging(false);
    setWidth(finalWidth);
  }, [widthForDrag, onPreview, setWidth]);

  // A handle that unmounts mid-drag (the dock closed) must not leave the
  // page stuck in resize mode with its transitions off.
  useEffect(
    () => () => {
      const drag = dragRef.current;
      if (drag && drag.frame !== null) window.cancelAnimationFrame(drag.frame);
      dragRef.current = null;
      document.documentElement.removeAttribute(DOCK_RESIZING_ATTR);
    },
    [],
  );

  const onPointerDown = (e: ReactPointerEvent<HTMLDivElement>) => {
    if (e.button !== 0) return;
    e.preventDefault();
    try {
      e.currentTarget.setPointerCapture(e.pointerId);
    } catch {
      // Not every environment supports capture; the drag still works while
      // the pointer stays over the handle.
    }
    dragRef.current = {
      pointerId: e.pointerId,
      startX: e.clientX,
      startWidth: width,
      latestX: e.clientX,
      frame: null,
    };
    document.documentElement.setAttribute(DOCK_RESIZING_ATTR, '');
    setDragging(true);
  };

  const onPointerMove = (e: ReactPointerEvent<HTMLDivElement>) => {
    const drag = dragRef.current;
    if (!drag || e.pointerId !== drag.pointerId) return;
    drag.latestX = e.clientX;
    if (drag.frame !== null) return;
    drag.frame = window.requestAnimationFrame(() => {
      const current = dragRef.current;
      if (!current) return;
      current.frame = null;
      onPreview(widthForDrag(current));
    });
  };

  const onPointerEnd = (e: ReactPointerEvent<HTMLDivElement>) => {
    const drag = dragRef.current;
    if (!drag || e.pointerId !== drag.pointerId) return;
    finishDrag();
  };

  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    const next = widthFromKey(e.key, { width, maxWidth, rtl: isRTL });
    if (next === null) return;
    e.preventDefault();
    e.stopPropagation();
    setWidth(next);
  };

  return (
    <div
      role="separator"
      aria-orientation="vertical"
      aria-valuenow={width}
      aria-valuemin={DOCK_MIN_WIDTH}
      aria-valuemax={maxWidth}
      aria-controls={controlsId}
      aria-label={t('chat.dock.resize_label', { defaultValue: 'Resize the assistant panel' })}
      title={t('chat.dock.resize_hint', {
        defaultValue: 'Drag to resize. Double-click to reset the width.',
      })}
      tabIndex={0}
      data-testid="floating-chat-resize-handle"
      data-dragging={dragging ? 'true' : undefined}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerEnd}
      onPointerCancel={onPointerEnd}
      onLostPointerCapture={onPointerEnd}
      onDoubleClick={resetWidth}
      onKeyDown={onKeyDown}
      className="group absolute inset-y-0 start-0 z-10 w-[6px] cursor-col-resize touch-none select-none focus-visible:outline-none"
    >
      {/* Edge line: faint on hover, solid while dragging or focused. */}
      <span
        aria-hidden
        className="pointer-events-none absolute inset-y-0 start-0 w-[2px] bg-oe-blue opacity-0 transition-opacity duration-fast group-hover:opacity-50 group-focus-visible:opacity-100 group-data-[dragging=true]:opacity-100"
      />
      {/* Grip: the "you can pull this" affordance. */}
      <span
        aria-hidden
        className="pointer-events-none absolute start-[1px] top-1/2 h-9 w-[4px] -translate-y-1/2 rounded-full bg-[color:var(--chat-text-tertiary)] opacity-0 transition-opacity duration-fast group-hover:opacity-70 group-focus-visible:bg-oe-blue group-focus-visible:opacity-100 group-data-[dragging=true]:bg-oe-blue group-data-[dragging=true]:opacity-100"
      />
    </div>
  );
}

// ── Main panel ─────────────────────────────────────────────────────────────
export function FloatingChatPanel() {
  const { t, i18n } = useTranslation();
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
  const pendingPrompt = useFloatingChatStore((s) => s.pendingPrompt);
  const clearPendingPrompt = useFloatingChatStore((s) => s.clearPendingPrompt);
  const openDock = useFloatingChatStore((s) => s.open);
  // The full-page chat (/chat) is the same conversation surface, so the dock
  // stays closed there. `isOpen` is left alone: leave /chat and the dock is
  // back exactly as it was.
  const suppressed = isFloatingChatHiddenOn(location.pathname);
  const dockOpen = isOpen && !suppressed;
  const geometry = useDockGeometry();
  const overlay = geometry.mode === 'overlay';
  const presence = useDockPresence(dockOpen);
  useDockLayoutSync({
    open: dockOpen,
    mode: geometry.mode,
    width: geometry.width,
    fullWidth: geometry.fullWidth,
  });
  const resolvedTheme = useThemeStore((s) => s.resolved);
  const activeProjectId = useProjectContextStore((s) => s.activeProjectId);
  const activeProjectName = useProjectContextStore((s) => s.activeProjectName);
  const setConversationActionIds = useFloatingChatStore((s) => s.setConversationActionIds);

  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [activeTab, setActiveTab] = useState<DockTab>('chat');
  // The Changes tab asks the server for its list, so it mounts the first time
  // it is opened, not with the dock, and then stays mounted (hidden) so its
  // filters and scroll position survive a look back at the chat.
  const [changesMounted, setChangesMounted] = useState(false);
  // A past conversation being read back from the server.
  const [historyLoad, setHistoryLoad] = useState<
    { status: 'idle' } | { status: 'loading' | 'error'; sessionId: string; title: string }
  >({ status: 'idle' });
  const [isStreaming, setIsStreaming] = useState(false);
  const [aiConfigured, setAiConfigured] = useState<boolean | null>(null);
  const [value, setValue] = useState('');
  const [sessionsOpen, setSessionsOpen] = useState(false);
  // `null` means "the user has not named this conversation", NOT "no title".
  // The displayed name is derived from `t()` during render (see `panelTitle`),
  // so it follows a language change. Seeding the state with `t(...)` instead
  // baked the language in at mount: a `useState` initialiser runs on the first
  // render and never again, so the dialog's `aria-label` kept announcing the
  // panel in whatever language it happened to open in while every visible
  // string around it translated. Nothing on screen showed the mismatch.
  const [title, setTitle] = useState<string | null>(null);

  const abortRef = useRef<AbortController | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  // Scroll memory. A hidden tab panel, like a closed dock, drops its layout
  // and with it the scroll position, so both lists keep theirs here. The
  // transcript follows new messages while the reader is at its end and stays
  // put when they scrolled up to read.
  const stickToBottomRef = useRef(true);
  const transcriptScrollTopRef = useRef(0);
  const changesScrollTopRef = useRef(0);
  const changesListRef = useRef<HTMLDivElement | null>(null);
  const transcriptObserverRef = useRef<ResizeObserver | null>(null);
  // Only the latest history request may fill the transcript.
  const historySeqRef = useRef(0);

  // Push mode is not modal: Tab moves freely between the page and the dock.
  // Overlay mode keeps focus inside. Either way focus returns to where it
  // was when the dock closes, if it was still inside the dock.
  useDockFocus(containerRef, { open: dockOpen, modal: overlay });

  // Read by handlers registered once (the open focus, Alt+A) without making
  // them re-register, and re-run, on every tab switch.
  const activeTabRef = useRef<DockTab>(activeTab);
  useLayoutEffect(() => {
    activeTabRef.current = activeTab;
  }, [activeTab]);

  // Where focus lands when the user enters the dock: the composer on the
  // Chat tab, the selected tab on the Changes tab (a hidden composer cannot
  // take focus, and the tab is where the Changes view starts).
  const focusDockEntry = useCallback(() => {
    const composer = textareaRef.current;
    const tab = activeTabRef.current;
    if (tab === 'chat' && composer && !composer.disabled) {
      composer.focus();
      return;
    }
    const tabButton = document.getElementById(dockTabId(tab));
    if (tabButton) tabButton.focus();
    else containerRef.current?.focus();
  }, []);

  const selectTab = useCallback((tab: DockTab) => {
    setActiveTab(tab);
    if (tab === 'changes') setChangesMounted(true);
  }, []);

  // The proposals of this conversation, as the transcript delivered them.
  // Same array while none arrives or changes, so the store sync below and the
  // tray do not redo their work on every streamed word.
  const proposalsRef = useRef<ChatAction[]>([]);
  const conversationProposals = useMemo(() => {
    const next = proposalsInTranscript(messages);
    const prev = proposalsRef.current;
    if (next.length === prev.length && next.every((a, i) => a === prev[i])) return prev;
    proposalsRef.current = next;
    return next;
  }, [messages]);
  // Their current status: the shared store follows every Apply, Reject and
  // Undo, wherever it was pressed. This also puts the proposals into the
  // store, which is what the round button counts from, so the panel keeps
  // doing it while closed (it stays mounted, it only renders nothing).
  const liveProposals = useLiveChatActions(conversationProposals);
  const waitingProposals = useMemo(() => pendingActions(liveProposals), [liveProposals]);
  useEffect(() => {
    setConversationActionIds(conversationProposals.map((a) => a.id));
  }, [conversationProposals, setConversationActionIds]);

  // The exit ends on the dock's OWN animationend, not one bubbling up from a
  // message or a spinner inside it. A native listener rather than React's
  // onAnimationEnd, which some engines route through a vendor-prefixed name.
  const { closing: dockClosing, finishExit } = presence;
  useEffect(() => {
    const container = containerRef.current;
    if (!dockClosing || !container) return;
    const onEnd = (e: AnimationEvent) => {
      if (e.target === container) finishExit();
    };
    container.addEventListener('animationend', onEnd);
    return () => container.removeEventListener('animationend', onEnd);
  }, [dockClosing, finishExit]);

  // While it slides out nothing in the dock may take focus (Tab would land
  // in a panel that is leaving). `inert` does that in the browser; the
  // aria-hidden in the markup keeps it out of the accessibility tree where
  // `inert` is missing. Set here because React 18 has no `inert` prop.
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    if (dockClosing) container.setAttribute('inert', '');
    else container.removeAttribute('inert');
  }, [dockClosing]);

  // Escape closes the dock only when focus is inside it: in push mode the
  // user may be pressing Escape in the page to cancel a grid edit or a menu.
  // In overlay mode focus sits inside anyway; <body> (after a click on a
  // non-focusable spot) counts as inside too. An open sessions menu closes
  // first. A component inside the dock that consumes Escape itself calls
  // preventDefault(), and the dock then leaves the key alone.
  useEffect(() => {
    if (!dockOpen) return;
    const onKey = (e: globalThis.KeyboardEvent) => {
      if (e.key !== 'Escape' || e.defaultPrevented) return;
      const container = containerRef.current;
      const active = document.activeElement;
      const focusInDock = !!container && !!active && container.contains(active);
      const focusNowhere = !active || active === document.body;
      if (!focusInDock && !(overlay && focusNowhere)) return;
      e.stopPropagation();
      if (sessionsOpen) {
        setSessionsOpen(false);
        return;
      }
      close();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [dockOpen, overlay, sessionsOpen, close]);

  // Alt+A (Option+A on a Mac): open the dock; when it is open and focus is
  // in the page, move focus into it (the composer, or the selected tab on the
  // Changes tab); when focus is already in the dock, close it. Silent on /chat and while another modal is open, so it
  // never pulls focus out from under a dialog. Capture phase, so viewers
  // with single-letter keys (walk mode binds A) never see the chord.
  useEffect(() => {
    if (suppressed) return;
    const onKey = (e: globalThis.KeyboardEvent) => {
      const active = document.activeElement;
      const matches = isDockShortcut(e, {
        applePlatform: isApplePlatform(),
        typingInField: isEditableElement(active),
      });
      if (!matches) return;
      const container = containerRef.current;
      if (isAnotherModalOpen(container)) return;
      e.preventDefault();
      e.stopPropagation();
      const state = useFloatingChatStore.getState();
      if (!state.isOpen) {
        openDock();
        return;
      }
      if (container && active && container.contains(active)) {
        close();
        return;
      }
      focusDockEntry();
    };
    window.addEventListener('keydown', onKey, true);
    return () => window.removeEventListener('keydown', onKey, true);
  }, [suppressed, openDock, close, focusDockEntry]);

  // Focus the composer (or the selected tab) right after the panel opens.
  useEffect(() => {
    if (!isOpen) return;
    const id = window.setTimeout(focusDockEntry, 80);
    return () => window.clearTimeout(id);
  }, [isOpen, focusDockEntry]);

  // Consume a staged prompt (e.g. from the BIM viewer's "Ask AI about this
  // element" button): prefill the composer, grow it to fit and place the
  // caret at the end so the user can review, tweak and hit Enter. We do NOT
  // auto-send, matching the human-confirmed AI stance. Fires when the panel
  // is already open too (dep on `pendingPrompt`), not only on first open.
  useEffect(() => {
    if (!isOpen || !pendingPrompt) return;
    setActiveTab('chat');
    setValue(pendingPrompt);
    clearPendingPrompt();
    const id = window.requestAnimationFrame(() => {
      const el = textareaRef.current;
      if (!el) return;
      el.style.height = 'auto';
      el.style.height = Math.min(el.scrollHeight, 160) + 'px';
      el.focus();
      const end = el.value.length;
      el.setSelectionRange(end, end);
    });
    return () => window.cancelAnimationFrame(id);
  }, [isOpen, pendingPrompt, clearPendingPrompt]);

  // The transcript. A callback ref, because the element comes and goes with
  // the dock. The observer keeps the end in view while the reader is there
  // and something changes the room the messages have: the review tray
  // appearing above the composer, the composer growing, a card expanding.
  const setTranscriptEl = useCallback((el: HTMLDivElement | null) => {
    scrollRef.current = el;
    transcriptObserverRef.current?.disconnect();
    transcriptObserverRef.current = null;
    if (!el || typeof ResizeObserver === 'undefined') return;
    const observer = new ResizeObserver(() => {
      if (stickToBottomRef.current) el.scrollTop = el.scrollHeight;
    });
    observer.observe(el);
    if (el.firstElementChild) observer.observe(el.firstElementChild);
    transcriptObserverRef.current = observer;
  }, []);

  const onTranscriptScroll = useCallback(() => {
    const el = scrollRef.current;
    // A hidden panel reports no size; it has not been scrolled.
    if (!el || el.clientHeight === 0) return;
    stickToBottomRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 32;
    transcriptScrollTopRef.current = el.scrollTop;
  }, []);

  // The Changes list, handed to ChangesView; its scroll is saved as it happens.
  const onChangesScroll = useCallback((e: Event) => {
    const el = e.currentTarget as HTMLDivElement;
    if (el.clientHeight > 0) changesScrollTopRef.current = el.scrollTop;
  }, []);
  const setChangesListEl = useCallback(
    (el: HTMLDivElement | null) => {
      changesListRef.current?.removeEventListener('scroll', onChangesScroll);
      changesListRef.current = el;
      el?.addEventListener('scroll', onChangesScroll, { passive: true });
    },
    [onChangesScroll],
  );

  // New messages: follow them while the reader is at the end. Before paint,
  // so the transcript never flashes at the old position.
  useLayoutEffect(() => {
    const el = scrollRef.current;
    if (el && stickToBottomRef.current) el.scrollTop = el.scrollHeight;
  }, [messages, isStreaming, historyLoad.status]);

  // Back on a tab, or back in a reopened dock: where the reader left it.
  useLayoutEffect(() => {
    if (!presence.rendered) return;
    if (activeTab === 'chat') {
      const el = scrollRef.current;
      if (!el) return;
      el.scrollTop = stickToBottomRef.current ? el.scrollHeight : transcriptScrollTopRef.current;
    } else if (changesListRef.current) {
      changesListRef.current.scrollTop = changesScrollTopRef.current;
    }
  }, [activeTab, presence.rendered]);

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
        // Prefer the backend's authoritative readiness flag (counts local
        // Ollama / vLLM via base_url, which carry no api_key). Fall back to the
        // shared local-aware helper for older payloads without the flag.
        const ready =
          typeof settings.ai_ready === 'boolean' ? settings.ai_ready : hasLlmKey(settings);
        setAiConfigured(ready);
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
      // A conversation being read back would overwrite the new turn.
      if (historyLoad.status === 'loading') return;
      // Whoever sends wants to see the answer, wherever they had scrolled.
      stickToBottomRef.current = true;

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
        resetComposerHeight(textareaRef.current);
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
      resetComposerHeight(textareaRef.current);
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
              // The reply follows the interface language, and the assistant
              // knows which page the user is looking at when they say "this".
              locale: i18n.language,
              client_context: {
                route: location.pathname,
                project_id: activeProjectId ?? null,
              },
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
                  const resultTool = typeof payload.tool === 'string' ? payload.tool : null;
                  const isErrorResult = result?.renderer === 'error';
                  const status: ToolCallInfo['status'] = isErrorResult ? 'error' : 'done';
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
                      const calls = m.toolCalls ?? [];
                      // Tools run one after another, so the result belongs to
                      // the latest running call, of the same tool when the
                      // event names it.
                      let index = resultTool
                        ? lastIndexWhere(calls, (tc) => tc.status === 'running' && tc.name === resultTool)
                        : -1;
                      if (index === -1) index = lastIndexWhere(calls, (tc) => tc.status === 'running');
                      const toolCalls =
                        index === -1
                          ? // A result without its start still shows, a proposal above all.
                            [
                              ...calls,
                              { id: uid(), name: resultTool ?? 'tool', status, result, startedAt: Date.now() },
                            ]
                          : calls.map((tc, i) =>
                              i === index
                                ? { ...tc, status, result, durationMs: Date.now() - tc.startedAt }
                                : tc,
                            );
                      const toolName = resultTool ?? (index === -1 ? null : calls[index]?.name ?? null);
                      const next: typeof m = { ...m, toolCalls };
                      // A refused proposal (missing or invalid details) is
                      // addressed to the model, which reads the reason and
                      // asks the user; its own row says what happened. Only
                      // other tool errors become the message's error card.
                      const refusedProposal = !!toolName && isProposalTool(toolName);
                      if (isErrorResult && !m.errorText && !refusedProposal) {
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
      historyLoad.status,
      activeSessionId,
      activeProjectId,
      location.pathname,
      aiConfigured,
      bumpUnread,
      setActiveSession,
      refreshAiConfigured,
      t,
      i18n,
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
    historySeqRef.current += 1;
    setHistoryLoad({ status: 'idle' });
    setMessages([]);
    setIsStreaming(false);
    setActiveSession(null);
    setActiveTab('chat');
    stickToBottomRef.current = true;
    // Back to the unnamed state, which renders as the default in whatever
    // language is active when it is read.
    setTitle(null);
  }, [setActiveSession]);

  // What the person sees is what the assistant is told. After a reload the
  // store still names the last conversation, but its transcript is not on
  // screen, so continuing it would feed the model turns nobody can see. The
  // next message starts a new conversation; the old one stays in the history.
  useEffect(() => {
    if (useFloatingChatStore.getState().activeSessionId) setActiveSession(null);
  }, [setActiveSession]);

  // A past conversation, read back from the server when the user picks it:
  // its messages, what the assistant looked up, and its proposals as cards
  // that re-read their current status. Only on an explicit pick; the dock
  // never fetches history on its own.
  const pickSession = useCallback(
    (id: string, sessionTitle: string) => {
      if (abortRef.current) abortRef.current.abort();
      const seq = (historySeqRef.current += 1);
      setMessages([]);
      setIsStreaming(false);
      setActiveSession(id);
      setTitle(sessionTitle.trim() ? sessionTitle : null);
      setActiveTab('chat');
      stickToBottomRef.current = true;
      setHistoryLoad({ status: 'loading', sessionId: id, title: sessionTitle });
      // Through a resolved promise, so a call that throws before it returns
      // one lands in the error state like a failed request.
      Promise.resolve()
        .then(() => fetchSessionMessages(id))
        .then((rows) => {
          if (seq !== historySeqRef.current) return;
          setMessages(transcriptFromPersisted(rows));
          setHistoryLoad({ status: 'idle' });
        })
        .catch(() => {
          if (seq !== historySeqRef.current) return;
          setHistoryLoad({ status: 'error', sessionId: id, title: sessionTitle });
        });
    },
    [setActiveSession],
  );

  const openProject = useCallback(() => {
    const target = activeProjectId ? `/projects/${encodeURIComponent(activeProjectId)}` : '/projects';
    // The overlay covers the page, so it steps aside for the project.
    if (overlay) close();
    navigate(target);
  }, [activeProjectId, overlay, close, navigate]);

  // The same for every other way out of the overlay to a page: a card's Open,
  // a result's link. The page behind an overlay cannot be used, so a change of
  // page while it is open came from inside it, and the reader wants to see
  // where it led. Only the path counts: a page that rewrites its own query
  // string does not close the dock. /chat is left out: the dock is only
  // hidden there (see `suppressed`) and comes back as it was.
  const lastPathRef = useRef(location.pathname);
  useEffect(() => {
    if (lastPathRef.current === location.pathname) return;
    lastPathRef.current = location.pathname;
    if (overlay && isOpen && !suppressed) close();
  }, [location.pathname, overlay, isOpen, suppressed, close]);

  const charCount = value.length;
  const overSoft = charCount > SOFT_LIMIT;
  const overHard = charCount > HARD_LIMIT;
  const historyLoading = historyLoad.status === 'loading';
  const canSend = value.trim().length > 0 && !isStreaming && !overHard && !historyLoading;

  // An example instruction from the empty state: into the composer, caret at
  // the end, to be adjusted and sent by the user.
  const draftInstruction = useCallback((text: string) => {
    setValue(text);
    window.requestAnimationFrame(() => {
      const el = textareaRef.current;
      if (!el) return;
      el.style.height = 'auto';
      el.style.height = Math.min(el.scrollHeight, 160) + 'px';
      el.focus();
      const end = el.value.length;
      el.setSelectionRange(end, end);
    });
  }, []);

  // The tray's Review: scroll to the first waiting card and focus it. The
  // transcript stops following new messages, the reader is looking up.
  const reviewWaiting = useCallback(() => {
    stickToBottomRef.current = false;
    revealFirstWaitingAction(scrollRef.current ?? document);
  }, []);

  const composerNoteId = useId();
  const composerKeysId = useId();
  // The count matters only once a message gets long.
  const showCounter = charCount >= HARD_LIMIT / 2;

  // Resize preview: while the handle is dragged the width goes straight to
  // the DOM (the dock's own width, the widget offset and, in push mode, the
  // page offset), so a long conversation is not re-rendered on every
  // animation frame. The store
  // gets the final width once, on release, and React then renders the same
  // value it finds.
  const previewWidth = useCallback(
    (next: number) => {
      const container = containerRef.current;
      if (container) container.style.width = `${next}px`;
      applyDockLayout(document.documentElement, {
        open: true,
        mode: geometry.mode,
        width: next,
        fullWidth: geometry.fullWidth,
      });
    },
    [geometry.mode, geometry.fullWidth],
  );

  // Derived, not stored, so a language change re-reads it. `t` is in the
  // dependency list on purpose, not as padding: it is the only input to this
  // memo that changes when the language does - `title` is state the user
  // controls. A conversation the user renamed keeps their words; only the
  // unnamed default translates.
  // Both properties are pinned in __tests__/attributesFollowTheLanguage.test.tsx,
  // which switches language after mount and re-reads the attribute.
  const panelTitle = useMemo(
    () => title ?? t('chat.panel.title_default', { defaultValue: 'AI assistant' }),
    [title, t],
  );

  if (!presence.rendered) return null;

  // `open` while shown, `closing` while it animates out (index.css keys the
  // slide and the fade on it). Mounted either way, so the conversation state
  // above survives a close.
  const dockState = presence.closing ? 'closing' : 'open';

  return (
    <>
      {/* Overlay mode only: the dock is modal there, the backdrop says so and
          a click on it closes. Push mode has none, the page stays usable. */}
      {overlay && (
        <div
          aria-hidden
          data-testid="floating-chat-backdrop"
          data-state={dockState}
          className="oe-ai-dock-backdrop fixed inset-0 z-50 bg-black/40 backdrop-blur-sm"
          onClick={presence.closing ? undefined : close}
        />
      )}
      <div
        ref={containerRef}
        id={DOCK_ELEMENT_ID}
        role="dialog"
        aria-modal={overlay ? 'true' : 'false'}
        aria-label={panelTitle}
        aria-hidden={presence.closing ? true : undefined}
        data-testid="floating-chat-panel"
        data-chat-theme={resolvedTheme}
        data-dock-mode={geometry.mode}
        data-state={dockState}
        tabIndex={-1}
        className={[
          'oe-ai-dock fixed inset-y-0 end-0',
          'flex flex-col',
          'border-s border-border-light',
          // Push: below modals and drawers (z-50), part of the layout, a
          // faint shadow is enough. Overlay: above the page, like a drawer.
          overlay ? 'z-50 shadow-2xl' : 'z-40 shadow-[0_0_24px_rgba(15,23,42,0.08)]',
          presence.closing ? 'pointer-events-none' : '',
          'focus:outline-none',
        ].join(' ')}
        style={{
          width: geometry.fullWidth ? '100%' : `${geometry.width}px`,
          maxWidth: '100vw',
          background: 'var(--chat-bg)',
          color: 'var(--chat-text-primary)',
        }}
      >
        {/* Header. Same height as the app header, so the two bottom lines
            meet in one line across the screen. The title input stays the
            FIRST input[aria-label] in the dialog (a test depends on it). */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 4,
            height: 'var(--oe-header-height, 52px)',
            flexShrink: 0,
            paddingInline: '12px 8px',
            borderBottom: '1px solid var(--chat-border)',
            background: 'var(--chat-surface-1)',
            position: 'relative',
          }}
        >
          <span
            aria-hidden
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              justifyContent: 'center',
              flexShrink: 0,
              width: 28,
              height: 28,
              marginInlineEnd: 6,
              borderRadius: 8,
              color: '#ffffff',
              background:
                'linear-gradient(135deg, var(--oe-blue, #2563eb) 0%, var(--oe-blue-dark, #1d4ed8) 100%)',
            }}
          >
            <Sparkles size={15} strokeWidth={2} />
          </span>
          <input
            value={panelTitle}
            onChange={(e) => setTitle(e.target.value)}
            aria-label={t('chat.panel.title_edit', { defaultValue: 'Conversation title' })}
            title={t('chat.panel.title_edit', { defaultValue: 'Conversation title' })}
            className="min-w-0 flex-1 truncate rounded-md border-none bg-transparent px-1.5 py-1 text-[13.5px] font-semibold outline-none transition-colors hover:bg-[color:var(--chat-surface-2)] focus:bg-[color:var(--chat-surface-2)] focus-visible:ring-2 focus-visible:ring-oe-blue"
            style={{ color: 'var(--chat-text-primary)' }}
          />
          <DockHeaderButton
            onClick={newSession}
            label={t('chat.panel.new_session', { defaultValue: 'New conversation' })}
            testId="floating-chat-new"
          >
            <MessageSquarePlus size={16} />
          </DockHeaderButton>
          <DockHeaderButton
            onClick={() => setSessionsOpen((v) => !v)}
            label={t('chat.panel.sessions_title', { defaultValue: 'Recent sessions' })}
            testId="floating-chat-sessions-toggle"
            expanded={sessionsOpen}
          >
            <History size={16} />
          </DockHeaderButton>
          <DockHeaderButton
            onClick={() => {
              close();
              navigate('/chat');
            }}
            label={t('chat.panel.open_full', { defaultValue: 'Open full page' })}
            testId="floating-chat-open-full"
          >
            <ExternalLink size={16} />
          </DockHeaderButton>
          <DockHeaderButton
            onClick={close}
            label={t('common.close', { defaultValue: 'Close' })}
            testId="floating-chat-close"
          >
            <X size={17} />
          </DockHeaderButton>
          <SessionsMenu
            open={sessionsOpen}
            onClose={() => setSessionsOpen(false)}
            onPick={pickSession}
            onNew={newSession}
            activeId={activeSessionId}
          />
        </div>

        <DockTabsRow
          active={activeTab}
          onSelect={selectTab}
          waitingCount={waitingProposals.length}
          projectId={activeProjectId}
          projectName={activeProjectName}
          onOpenProject={openProject}
        />

        {/* Chat tab: the conversation, the tray of changes waiting for a
            decision, and the composer. The inactive panel is `hidden` (so it
            leaves the focus order and the accessibility tree) but stays
            mounted with everything in it. */}
        <div
          role="tabpanel"
          id={dockTabPanelId('chat')}
          aria-labelledby={dockTabId('chat')}
          hidden={activeTab !== 'chat'}
          className={activeTab === 'chat' ? 'flex min-h-0 flex-1 flex-col' : undefined}
          data-testid="floating-chat-chat-panel"
        >
          {/* aria-live=polite so screen readers announce streaming assistant
              text and tool results as they arrive. */}
          <div
            ref={setTranscriptEl}
            onScroll={onTranscriptScroll}
            role="log"
            aria-live="polite"
            aria-relevant="additions text"
            aria-busy={historyLoading || undefined}
            aria-label={t('chat.panel.transcript_aria', {
              defaultValue: 'Conversation transcript',
            })}
            className="min-h-0 flex-1 overflow-y-auto overscroll-contain"
            data-testid="floating-chat-transcript"
          >
            <div
              className={
                messages.length === 0 && historyLoad.status === 'idle'
                  ? undefined
                  : 'flex flex-col gap-1.5 px-3 pb-2 pt-3'
              }
            >
              {historyLoad.status === 'loading' ? (
                <HistoryLoading />
              ) : historyLoad.status === 'error' ? (
                <HistoryError
                  onRetry={() => pickSession(historyLoad.sessionId, historyLoad.title)}
                  onNew={newSession}
                />
              ) : messages.length === 0 ? (
                <EmptyState pathname={location.pathname} onAsk={sendMessage} onDraft={draftInstruction} />
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
                        color: 'var(--chat-text-secondary)',
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
                </>
              )}
            </div>
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

          {/* Pinned above the composer while this conversation has changes
              nobody has decided on. The transcript keeps its end in view when
              the tray takes its room. */}
          {waitingProposals.length > 0 && (
            <div className="shrink-0 px-3 pb-2 pt-1">
              <ActionsReviewTray actions={conversationProposals} onReview={reviewWaiting} />
            </div>
          )}

          {/* Composer */}
          <div className="shrink-0 border-t border-[color:var(--chat-border-subtle)] bg-[color:var(--chat-surface-1)] px-3 pb-2.5 pt-2.5">
            <div className="flex items-end gap-2">
              <textarea
                ref={textareaRef}
                value={value}
                onChange={handleChange}
                onKeyDown={handleKeyDown}
                disabled={isStreaming || historyLoading}
                data-testid="floating-chat-input"
                aria-label={t('chat.dock.composer_label', { defaultValue: 'Message to the assistant' })}
                aria-describedby={`${composerNoteId} ${composerKeysId}`}
                placeholder={t('chat.dock.composer_placeholder', {
                  defaultValue: 'Tell me what to do, e.g. "Create a task: check the formwork on level 3 by Friday"',
                })}
                rows={2}
                className={clsx(
                  'max-h-40 min-w-0 flex-1 resize-none overflow-auto rounded-lg border bg-[color:var(--chat-bg)] px-2.5 py-2 text-sm text-[color:var(--chat-text-primary)] outline-none transition-colors',
                  'placeholder:text-[color:var(--chat-text-secondary)] focus:border-oe-blue focus-visible:ring-2 focus-visible:ring-oe-blue/30',
                  'disabled:cursor-not-allowed disabled:opacity-70',
                  overHard
                    ? 'border-semantic-error'
                    : overSoft
                      ? 'border-semantic-warning'
                      : 'border-[color:var(--chat-border)]',
                )}
                style={{ fontFamily: 'var(--chat-font-body)' }}
              />
              <button
                type="button"
                onClick={() => sendMessage(value)}
                disabled={!canSend}
                data-testid="floating-chat-send"
                aria-label={t('chat.panel.send', { defaultValue: 'Send' })}
                title={t('chat.kbd_hint', { defaultValue: 'Enter to send · Shift+Enter for newline' })}
                className={clsx(
                  'inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-lg transition-colors',
                  'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue focus-visible:ring-offset-2',
                  canSend
                    ? 'bg-oe-blue text-content-inverse hover:bg-oe-blue-hover'
                    : 'cursor-not-allowed border border-[color:var(--chat-border)] bg-[color:var(--chat-surface-2)] text-[color:var(--chat-text-secondary)]',
                )}
              >
                <ArrowUp size={16} strokeWidth={2.25} aria-hidden />
              </button>
            </div>
            <div className="mt-1.5 flex items-center gap-1.5 text-[12px] leading-4 text-[color:var(--chat-text-secondary)]">
              <ShieldCheck size={13} aria-hidden className="shrink-0" />
              <span id={composerNoteId} className="min-w-0 flex-1">
                {t('chat.dock.composer_note', {
                  defaultValue: 'Changes are only saved after you approve them.',
                })}
              </span>
              {showCounter && (
                <span
                  className={clsx(
                    'shrink-0 tabular-nums',
                    overHard && 'font-medium text-semantic-error',
                    !overHard && overSoft && 'font-medium text-semantic-warning',
                  )}
                  data-testid="floating-chat-counter"
                >
                  {overHard
                    ? t('chat.panel.token_over', { defaultValue: 'Too long - please shorten' })
                    : overSoft
                      ? t('chat.panel.token_warn', { defaultValue: 'Long message' })
                      : `${charCount}/${HARD_LIMIT}`}
                </span>
              )}
            </div>
            <span id={composerKeysId} className="sr-only">
              {t('chat.kbd_hint', { defaultValue: 'Enter to send · Shift+Enter for newline' })}
            </span>
          </div>
        </div>

        {/* Changes tab: the assistant's ledger. Mounted the first time the tab
            is opened (it fetches its list), then kept. */}
        <div
          role="tabpanel"
          id={dockTabPanelId('changes')}
          aria-labelledby={dockTabId('changes')}
          hidden={activeTab !== 'changes'}
          className={activeTab === 'changes' ? 'flex min-h-0 flex-1 flex-col' : undefined}
          data-testid="floating-chat-changes-panel"
        >
          {changesMounted && (
            <ChangesView
              projectId={activeProjectId}
              projectName={activeProjectName || undefined}
              className="min-h-0 flex-1"
              listRef={setChangesListEl}
            />
          )}
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
        `}</style>
        {/* The dock's own slide and fade live in index.css under
            .oe-ai-dock / .oe-ai-dock-backdrop. They used to be redefined
            here as .animate-slide-in-right / .animate-fade-in, which are
            GLOBAL Tailwind classes: while this panel was mounted, every
            drawer and toast in the app that uses them was restyled too. */}

        {/* Resize handle, last in the DOM so it is the last Tab stop rather
            than the first; absolutely placed on the inline-start edge, INSIDE
            the dock's box so nothing that clips the dock can clip it. Not
            offered when the dock covers the whole screen. */}
        {!geometry.fullWidth && !presence.closing && (
          <DockResizeHandle
            width={geometry.width}
            maxWidth={geometry.maxWidth}
            controlsId={DOCK_ELEMENT_ID}
            onPreview={previewWidth}
          />
        )}
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
            // Logical corners: the tail sits at the bottom inline-end corner,
            // on the right in LTR and on the left in RTL.
            borderStartStartRadius: 14,
            borderStartEndRadius: 14,
            borderEndEndRadius: 4,
            borderEndStartRadius: 14,
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
          color: 'var(--chat-text-secondary)',
          fontFamily: 'var(--chat-font-mono)',
          padding: '2px 0',
        }}
      >
        {msg.content}
      </div>
    );
  }

  // Full width: a proposal card needs the room for its field table. The
  // accent rule is on the inline-start side, so it follows RTL.
  return (
    <div
      style={{
        borderInlineStart: '2px solid var(--chat-accent)',
        paddingInlineStart: 10,
        minWidth: 0,
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
