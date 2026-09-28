// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { useState, useRef, useEffect, useCallback, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import type { TFunction } from 'i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  X,
  Send,
  Check,
  Settings,
  AlertCircle,
  Sparkles,
  Undo2,
  ArrowRight,
  Tag,
} from 'lucide-react';
import {
  boqApi,
  type Position,
  type CopilotAction,
  type CopilotMessage,
  type CopilotResource,
} from './api';
import { ApiError } from '@/shared/lib/api';
import { getNumberLocale } from '@/stores/usePreferencesStore';
import { fmtList } from '@/shared/lib/formatters';

/* ── Props ──────────────────────────────────────────────────────────── */

interface AIPositionCopilotProps {
  boqId: string;
  positionId: string;
  position: Position | null;
  isOpen: boolean;
  onClose: () => void;
  /**
   * Called after a review applied at least one accepted action. ``position``
   * is the server's position after ALL accepted actions of that review; the
   * editor mirrors it into the grid cache + undo stack in one step, so one
   * Ctrl+Z reverts the whole review. The server already persisted the change.
   */
  onReviewApplied: (position: Position) => void;
  /**
   * Layout mode. ``dock`` (default) renders the standalone card with its own
   * rounded shell and top margin. ``inline`` renders to fill a fixed-height
   * AG Grid full-width row injected directly under the position: no top margin,
   * fills the row height, with a left accent rule tying it to the parent
   * position above.
   */
  variant?: 'dock' | 'inline';
}

/* ── Local render model ─────────────────────────────────────────────── */

/**
 * A chat row the dock renders. Mirrors {@link CopilotMessage} but adds a
 * synthetic ``loading`` / ``error`` role used only client-side (never sent or
 * persisted) plus a stable client id for React keys.
 */
interface DockMessage {
  id: string;
  role: 'user' | 'assistant' | 'loading' | 'error';
  content: string;
  actions?: CopilotAction[] | null;
}

/**
 * Confidence at or above which a fresh suggestion starts checked in the review
 * list. Only a preselection: nothing is written until the user applies it.
 * Mirrors ``PRESELECT_THRESHOLD`` in backend ``copilot_service.py``.
 */
const PRESELECT_THRESHOLD = 0.85;

/** Still waiting for a decision (``failed`` stays open so it can be retried). */
function isPending(action: CopilotAction): boolean {
  return action.status === 'needs_review' || action.status === 'failed';
}

/**
 * Per-position input drafts, kept at module scope so a half-typed message
 * survives the component unmounting and remounting - which happens for the
 * ``inline`` variant whenever its grid row is virtualised out of view and back.
 * Keyed by positionId; cleared when the message is sent.
 */
const draftCache = new Map<string, string>();

/* ── Helpers ────────────────────────────────────────────────────────── */

function fmtNum(n: number): string {
  return new Intl.NumberFormat(getNumberLocale(), {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(n);
}

/** Pull a string field off a payload/before bag, tolerating missing keys. */
function asString(bag: Record<string, unknown> | undefined, key: string): string | undefined {
  const v = bag?.[key];
  return typeof v === 'string' ? v : undefined;
}

/** Pull a numeric field off a payload/before bag (coerce decimal strings). */
function asNumber(bag: Record<string, unknown> | undefined, key: string): number | undefined {
  const v = bag?.[key];
  if (typeof v === 'number' && Number.isFinite(v)) return v;
  if (typeof v === 'string' && v.trim() !== '') {
    const n = Number(v);
    if (Number.isFinite(n)) return n;
  }
  return undefined;
}

function asResources(bag: Record<string, unknown> | undefined): CopilotResource[] {
  const v = bag?.resources;
  return Array.isArray(v) ? (v as CopilotResource[]) : [];
}

/* ── Component ──────────────────────────────────────────────────────── */

export function AIPositionCopilot({
  boqId,
  positionId,
  position,
  isOpen,
  onClose,
  onReviewApplied,
  variant = 'dock',
}: AIPositionCopilotProps) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();

  const [messages, setMessages] = useState<DockMessage[]>([]);
  const [inputValue, setInputValue] = useState(() => draftCache.get(positionId) ?? '');
  /** Checked suggestions (key = `${messageId}:${index}`) for "Apply selected". */
  const [selected, setSelected] = useState<Set<string>>(new Set());
  /** Assistant turns whose review request is in flight (their buttons wait). */
  const [reviewingIds, setReviewingIds] = useState<Set<string>>(new Set());
  /** Suggestions applied in this session: only these are on the undo stack. */
  const [undoableKeys, setUndoableKeys] = useState<Set<string>>(new Set());

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  /* ── History (replayed when the dock opens for a position) ─────────── */

  const historyQuery = useQuery({
    queryKey: ['boq-position-copilot', boqId, positionId],
    queryFn: () => boqApi.positionCopilotHistory(positionId),
    enabled: isOpen && !!positionId,
    // The transcript is seeded from this query then driven locally (optimistic
    // sends). Don't refetch on window focus — that would re-seed mid-session
    // and could drop an in-flight turn. Data only changes on a positionId
    // retarget (new query key), which is exactly when we WANT to re-seed.
    refetchOnWindowFocus: false,
    retry: (failCount, error) => {
      if (error instanceof ApiError && error.status === 404) return false;
      return failCount < 2;
    },
  });

  // Seed the local transcript from persisted history, keyed on positionId so a
  // retarget reloads the new row's chat. While the fresh fetch is in flight
  // (data === undefined) we blank the transcript so the previous position's
  // chat never lingers under the new header; once it resolves we replay it.
  // Folding both into ONE effect avoids an ordering race where a separate
  // "clear" effect could blank an already-cached transcript.
  useEffect(() => {
    if (!isOpen) return;
    const hist = historyQuery.data;
    setMessages(
      (hist ?? []).map((m: CopilotMessage) => ({
        id: m.id,
        role: m.role,
        content: m.content,
        actions: m.actions,
      })),
    );
    // Replayed history starts with nothing checked: an old suggestion is only
    // applied when the user picks it again, never by a leftover default.
    setSelected(new Set());
    setReviewingIds(new Set());
    setUndoableKeys(new Set());
  }, [historyQuery.data, isOpen, positionId]);

  // Auto-scroll to the newest row.
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  // Restore the per-position draft when the copilot retargets to another
  // position (the dock variant stays mounted and swaps positionId).
  useEffect(() => {
    setInputValue(draftCache.get(positionId) ?? '');
  }, [positionId]);

  // Focus the input when the dock opens or retargets.
  useEffect(() => {
    if (isOpen) {
      const id = window.setTimeout(() => inputRef.current?.focus(), 150);
      return () => window.clearTimeout(id);
    }
    return undefined;
  }, [isOpen, positionId]);

  /* ── Chat mutation ─────────────────────────────────────────────────── */

  const chatMutation = useMutation({
    mutationFn: (message: string) => boqApi.positionCopilotChat(positionId, message),
    onSuccess: (response) => {
      setMessages((prev) => prev.filter((m) => m.role !== 'loading'));
      const assistant = response.assistant_message;
      const actions = response.actions ?? assistant.actions ?? [];
      const messageId = assistant.id || `assistant-${Date.now()}`;
      setMessages((prev) => [
        ...prev,
        {
          id: messageId,
          role: 'assistant',
          content: assistant.content,
          actions,
        },
      ]);

      // Nothing was written: every suggestion waits for review. Preselect the
      // high-confidence ones of THIS turn so accepting them is one click.
      const preselect = actions
        .map((a, idx) => ({ a, idx }))
        .filter(({ a }) => a.status === 'needs_review' && (a.confidence ?? 0) >= PRESELECT_THRESHOLD)
        .map(({ idx }) => `${messageId}:${idx}`);
      if (preselect.length > 0) {
        setSelected((prev) => new Set([...prev, ...preselect]));
      }

      // Persisted history now diverges from our optimistic transcript — let the
      // next open re-pull it, but don't refetch now (would clobber the just-
      // appended bubble mid-session).
      queryClient.invalidateQueries({
        queryKey: ['boq-position-copilot', boqId, positionId],
        refetchType: 'none',
      });
    },
    onError: (error: unknown) => {
      setMessages((prev) => prev.filter((m) => m.role !== 'loading'));
      let errorText = t('boq.copilot.error', {
        defaultValue: 'The copilot request failed. Please try again.',
      });
      if (error instanceof ApiError) {
        const body = error.body as { detail?: string } | undefined;
        if (body?.detail) errorText = body.detail;
      }
      setMessages((prev) => [
        ...prev,
        { id: `error-${Date.now()}`, role: 'error', content: errorText },
      ]);
    },
  });

  /* ── Review mutation (the user accepts / rejects suggestions) ──────── */

  const reviewMutation = useMutation({
    mutationFn: ({
      messageId,
      accept,
      reject,
    }: {
      messageId: string;
      accept: number[];
      reject: number[];
      /** The turn's actions as shown when the user decided (to spot changes). */
      before: CopilotAction[];
    }) => boqApi.positionCopilotReview(positionId, messageId, accept, reject),
    onSuccess: (response, { messageId, before }) => {
      const after = response.message.actions ?? [];
      // Swap in the server's statuses: applied, dismissed, or failed with a
      // note on the card. A failed one stays open so the user can retry it.
      setMessages((prev) =>
        prev.map((m) => (m.id === messageId ? { ...m, actions: after } : m)),
      );
      const touched = after
        .map((a, idx) => ({ a, idx }))
        .filter(({ a, idx }) => a.status !== before[idx]?.status);
      setSelected((prev) => {
        const next = new Set(prev);
        for (const { a, idx } of touched) {
          if (!isPending(a)) next.delete(`${messageId}:${idx}`);
        }
        return next;
      });
      const newlyApplied = touched.filter(({ a }) => a.status === 'applied');
      if (newlyApplied.length > 0) {
        setUndoableKeys((prev) => {
          const next = new Set(prev);
          for (const { idx } of newlyApplied) next.add(`${messageId}:${idx}`);
          return next;
        });
        onReviewApplied(response.position);
      }
      // The stored thread now carries the new statuses; the next open re-pulls
      // it, but don't refetch now (would clobber the local transcript).
      queryClient.invalidateQueries({
        queryKey: ['boq-position-copilot', boqId, positionId],
        refetchType: 'none',
      });
    },
    onError: (error: unknown) => {
      const detail =
        error instanceof ApiError
          ? error.message
          : t('boq.copilot.apply_failed', { defaultValue: 'Could not apply this change.' });
      setMessages((prev) => [
        ...prev,
        { id: `error-${Date.now()}`, role: 'error', content: detail },
      ]);
    },
    onSettled: (_data, _error, { messageId }) => {
      setReviewingIds((prev) => {
        const next = new Set(prev);
        next.delete(messageId);
        return next;
      });
    },
  });

  /* ── Send ──────────────────────────────────────────────────────────── */

  const send = useCallback(
    (text: string) => {
      const trimmed = text.trim();
      if (!trimmed || chatMutation.isPending) return;
      setMessages((prev) => [
        ...prev,
        { id: `user-${Date.now()}`, role: 'user', content: trimmed },
        { id: 'loading', role: 'loading', content: '' },
      ]);
      setInputValue('');
      draftCache.delete(positionId);
      chatMutation.mutate(trimmed);
    },
    [chatMutation, positionId],
  );

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        send(inputValue);
      }
    },
    [send, inputValue],
  );

  /** Send one review decision for an assistant turn (indices into its actions). */
  const review = useCallback(
    (messageId: string, before: CopilotAction[], accept: number[], reject: number[]) => {
      if (reviewMutation.isPending || (accept.length === 0 && reject.length === 0)) return;
      setReviewingIds((prev) => new Set(prev).add(messageId));
      reviewMutation.mutate({ messageId, accept, reject, before });
    },
    [reviewMutation],
  );

  const toggleSelected = useCallback((key: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }, []);

  const isNoApiKey = useMemo(
    () =>
      messages.some(
        (m) => m.role === 'error' && m.content.includes('No AI API key configured'),
      ),
    [messages],
  );

  const quickPrompts = useMemo(
    () => [
      {
        key: 'improve_description',
        label: t('boq.copilot.qp_improve', { defaultValue: 'Improve description' }),
        prompt: t('boq.copilot.qp_improve_prompt', {
          defaultValue: 'Improve the description of this position.',
        }),
      },
      {
        key: 'find_price',
        label: t('boq.copilot.qp_price', { defaultValue: 'Find a price' }),
        prompt: t('boq.copilot.qp_price_prompt', {
          defaultValue: 'Find and apply a unit rate from the catalogue.',
        }),
      },
      {
        key: 'set_quantity',
        label: t('boq.copilot.qp_quantity', { defaultValue: 'Set quantity' }),
        prompt: t('boq.copilot.qp_quantity_prompt', {
          defaultValue: 'Suggest a quantity and unit for this position.',
        }),
      },
      {
        key: 'add_resources',
        label: t('boq.copilot.qp_resources', {
          defaultValue: 'Add resources from catalog',
        }),
        prompt: t('boq.copilot.qp_resources_prompt', {
          defaultValue: 'Add the matching resources from the catalogue.',
        }),
      },
    ],
    [t],
  );

  if (!isOpen) return null;

  const ordinal = position?.ordinal ?? '';
  const description = position?.description ?? '';

  return (
    <div
      role="region"
      aria-label={t('boq.copilot.title', { defaultValue: 'AI Copilot' })}
      data-testid="boq-ai-copilot"
      className={
        variant === 'inline'
          ? 'h-full flex flex-col overflow-hidden border-l-2 border-oe-blue/60 bg-surface-elevated'
          : 'mt-2 rounded-xl border border-border-light bg-surface-elevated shadow-xs flex flex-col overflow-hidden'
      }
    >
      {/* ── Header ──────────────────────────────────────────────────── */}
      <div className="flex items-center justify-between gap-3 px-4 py-2.5 border-b border-border-light bg-surface-secondary/40">
        <div className="flex min-w-0 items-center gap-2">
          <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-oe-blue-subtle/40">
            <Sparkles size={15} className="text-oe-blue" />
          </div>
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <span className="text-sm font-semibold text-content-primary">
                {t('boq.copilot.title', { defaultValue: 'AI Copilot' })}
              </span>
              {ordinal && (
                <span className="font-mono text-2xs text-content-tertiary">{ordinal}</span>
              )}
            </div>
            {description && (
              <p className="truncate text-2xs text-content-secondary" title={description}>
                {description}
              </p>
            )}
          </div>
        </div>
        <button
          onClick={onClose}
          className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-content-tertiary hover:text-red-600 dark:hover:text-red-400 hover:bg-red-100 dark:hover:bg-red-900/30 transition-colors"
          aria-label={t('common.close', { defaultValue: 'Close' })}
        >
          <X size={16} />
        </button>
      </div>

      {/* ── Messages ────────────────────────────────────────────────── */}
      <div
        className={
          variant === 'inline'
            ? 'flex-1 overflow-y-auto px-4 py-3 space-y-3'
            : 'max-h-[340px] min-h-[160px] flex-1 overflow-y-auto px-4 py-3 space-y-3'
        }
      >
        {messages.length === 0 && !historyQuery.isLoading && (
          <div className="flex flex-col items-center gap-2 py-6 text-center">
            <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-oe-blue-subtle/40">
              <Sparkles size={20} className="text-oe-blue" />
            </div>
            <p className="max-w-[420px] text-xs text-content-secondary">
              {t('boq.copilot.welcome', {
                defaultValue:
                  'I work on this position. Ask me to improve its description, set a quantity, find a unit rate, or add resources - I pull prices and resources from the catalogue.',
              })}
            </p>
          </div>
        )}

        {historyQuery.isLoading && messages.length === 0 && (
          <div className="flex items-center gap-1 py-4">
            <span
              className="h-2 w-2 rounded-full bg-content-tertiary animate-bounce"
              style={{ animationDelay: '0ms' }}
            />
            <span
              className="h-2 w-2 rounded-full bg-content-tertiary animate-bounce"
              style={{ animationDelay: '150ms' }}
            />
            <span
              className="h-2 w-2 rounded-full bg-content-tertiary animate-bounce"
              style={{ animationDelay: '300ms' }}
            />
          </div>
        )}

        {messages.map((msg) => {
          if (msg.role === 'loading') {
            return (
              <div key="loading" className="flex items-start gap-2">
                <div className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-oe-blue-subtle/40">
                  <Sparkles size={12} className="text-oe-blue" />
                </div>
                <div className="mt-0.5 flex items-center gap-1">
                  <span
                    className="h-2 w-2 rounded-full bg-content-tertiary animate-bounce"
                    style={{ animationDelay: '0ms' }}
                  />
                  <span
                    className="h-2 w-2 rounded-full bg-content-tertiary animate-bounce"
                    style={{ animationDelay: '150ms' }}
                  />
                  <span
                    className="h-2 w-2 rounded-full bg-content-tertiary animate-bounce"
                    style={{ animationDelay: '300ms' }}
                  />
                </div>
              </div>
            );
          }

          if (msg.role === 'error') {
            return (
              <div key={msg.id} className="flex items-start gap-2">
                <div className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-semantic-error-bg">
                  <AlertCircle size={12} className="text-semantic-error" />
                </div>
                <div className="flex-1 rounded-lg bg-semantic-error-bg px-3 py-2">
                  <p className="text-xs text-semantic-error">{msg.content}</p>
                  {isNoApiKey && (
                    <a
                      href="/settings"
                      className="mt-2 inline-flex items-center gap-1 text-xs font-medium text-oe-blue hover:underline"
                    >
                      <Settings size={11} />
                      {t('boq.go_to_settings', { defaultValue: 'Go to Settings' })}
                    </a>
                  )}
                </div>
              </div>
            );
          }

          if (msg.role === 'user') {
            return (
              <div key={msg.id} className="flex justify-end">
                <div className="max-w-[85%] rounded-lg bg-oe-blue px-3 py-2">
                  <p className="whitespace-pre-wrap text-xs text-white">{msg.content}</p>
                </div>
              </div>
            );
          }

          // Assistant
          return (
            <div key={msg.id} className="flex items-start gap-2">
              <div className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-oe-blue-subtle/40">
                <Sparkles size={12} className="text-oe-blue" />
              </div>
              <div className="min-w-0 flex-1">
                {msg.content && (
                  <p className="mb-2 whitespace-pre-wrap break-words text-xs leading-relaxed text-content-primary">
                    {msg.content}
                  </p>
                )}
                {msg.actions && msg.actions.length > 0 && (
                  <ReviewList
                    messageId={msg.id}
                    actions={msg.actions}
                    selected={selected}
                    undoableKeys={undoableKeys}
                    busy={reviewingIds.has(msg.id)}
                    onToggle={toggleSelected}
                    onReview={(accept, reject) => review(msg.id, msg.actions ?? [], accept, reject)}
                  />
                )}
              </div>
            </div>
          );
        })}

        <div ref={messagesEndRef} />
      </div>

      {/* ── Quick prompts + input ───────────────────────────────────── */}
      <div className="shrink-0 border-t border-border-light bg-surface-primary px-4 py-2.5">
        <div className="mb-2 flex flex-wrap gap-1.5">
          {quickPrompts.map((qp) => (
            <button
              key={qp.key}
              onClick={() => send(qp.prompt)}
              disabled={chatMutation.isPending}
              className="rounded-full border border-border-light bg-surface-elevated px-2.5 py-1 text-2xs font-medium text-content-secondary hover:border-oe-blue/40 hover:text-oe-blue disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            >
              {qp.label}
            </button>
          ))}
        </div>
        <div className="flex items-center gap-2">
          <input
            ref={inputRef}
            type="text"
            value={inputValue}
            onChange={(e) => {
              setInputValue(e.target.value);
              draftCache.set(positionId, e.target.value);
            }}
            onKeyDown={handleKeyDown}
            placeholder={t('boq.copilot.placeholder', {
              defaultValue: 'Ask the copilot to change this position…',
            })}
            disabled={chatMutation.isPending}
            aria-label={t('boq.copilot.input_label', {
              defaultValue: 'Message the position copilot',
            })}
            className="flex-1 rounded-lg border border-border-light bg-surface-elevated px-3 py-2 text-sm text-content-primary placeholder:text-content-tertiary outline-none focus:ring-2 focus:ring-oe-blue/20 focus:border-oe-blue/40 disabled:opacity-50 transition-all"
          />
          <button
            onClick={() => send(inputValue)}
            disabled={!inputValue.trim() || chatMutation.isPending}
            aria-label={t('common.send', { defaultValue: 'Send' })}
            className="flex h-9 w-9 items-center justify-center rounded-lg bg-oe-blue text-white hover:bg-oe-blue-hover disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          >
            <Send size={16} />
          </button>
        </div>
      </div>
    </div>
  );
}

/* ── Review list (one assistant turn) ───────────────────────────────── */

interface ReviewListProps {
  messageId: string;
  actions: CopilotAction[];
  /** Checked suggestions across the thread (key = `${messageId}:${index}`). */
  selected: Set<string>;
  /** Suggestions applied in this session (their undo is on the Ctrl+Z stack). */
  undoableKeys: Set<string>;
  /** A review request for this turn is in flight: every button waits. */
  busy: boolean;
  onToggle: (key: string) => void;
  /** Accept / reject by index into ``actions``; indices in neither list stay open. */
  onReview: (accept: number[], reject: number[]) => void;
}

/**
 * The suggestions of one assistant turn as a review list. Nothing is written
 * until the user decides: per suggestion Accept / Reject, or, when more than
 * one is open, Accept all / Reject all and Apply selected for the checked ones.
 * High-confidence suggestions of a fresh turn arrive checked.
 */
function ReviewList({
  messageId,
  actions,
  selected,
  undoableKeys,
  busy,
  onToggle,
  onReview,
}: ReviewListProps) {
  const { t } = useTranslation();

  const pendingIdx = actions.map((a, idx) => (isPending(a) ? idx : -1)).filter((idx) => idx >= 0);
  const selectedIdx = pendingIdx.filter((idx) => selected.has(`${messageId}:${idx}`));
  const showBulk = pendingIdx.length > 1;

  return (
    <div className="space-y-2" data-testid="copilot-review-list">
      {pendingIdx.length > 0 && (
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="min-w-0">
            <p className="text-2xs font-semibold uppercase tracking-wide text-content-secondary">
              {t('boq.copilot.review_title', { defaultValue: 'Suggested changes' })}
            </p>
            <p className="text-2xs text-content-tertiary">
              {t('boq.copilot.review_hint', {
                defaultValue: 'Nothing changes until you accept. Confident suggestions are preselected.',
              })}
            </p>
          </div>
          {showBulk && (
            <div className="flex shrink-0 items-center gap-1.5">
              <button
                type="button"
                onClick={() => onReview(pendingIdx, [])}
                disabled={busy}
                className="rounded-md border border-oe-blue/40 px-2 py-0.5 text-2xs font-semibold text-oe-blue hover:bg-oe-blue-subtle/30 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
              >
                {t('boq.copilot.accept_all', { defaultValue: 'Accept all' })}
              </button>
              <button
                type="button"
                onClick={() => onReview([], pendingIdx)}
                disabled={busy}
                className="rounded-md px-2 py-0.5 text-2xs font-medium text-content-secondary hover:bg-surface-secondary disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
              >
                {t('boq.copilot.reject_all', { defaultValue: 'Reject all' })}
              </button>
            </div>
          )}
        </div>
      )}

      {actions.map((action, idx) => {
        const key = `${messageId}:${idx}`;
        return (
          <ActionCard
            key={key}
            action={action}
            showCheckbox={showBulk}
            checked={selected.has(key)}
            undoable={undoableKeys.has(key)}
            busy={busy}
            onToggle={() => onToggle(key)}
            onAccept={() => onReview([idx], [])}
            onReject={() => onReview([], [idx])}
          />
        );
      })}

      {showBulk && (
        <div className="flex items-center justify-end">
          <button
            type="button"
            onClick={() => onReview(selectedIdx, [])}
            disabled={busy || selectedIdx.length === 0}
            className="inline-flex items-center gap-1.5 rounded-md bg-oe-blue px-2.5 py-1 text-2xs font-semibold text-white hover:bg-oe-blue-hover disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          >
            <Check size={11} strokeWidth={3} />
            {busy
              ? t('boq.copilot.applying', { defaultValue: 'Applying…' })
              : t('boq.copilot.apply_selected', { defaultValue: 'Apply selected' })}
            <span className="rounded-full bg-white/20 px-1.5 tabular-nums">{selectedIdx.length}</span>
          </button>
        </div>
      )}
    </div>
  );
}

/* ── Action card ────────────────────────────────────────────────────── */

interface ActionCardProps {
  action: CopilotAction;
  /** Show the selection checkbox (only when the turn has several open items). */
  showCheckbox: boolean;
  checked: boolean;
  /** Applied in this session, so Ctrl+Z reverts it. */
  undoable: boolean;
  /** A review request for this turn is in flight. */
  busy: boolean;
  onToggle: () => void;
  onAccept: () => void;
  onReject: () => void;
}

function ActionCard({
  action,
  showCheckbox,
  checked,
  undoable,
  busy,
  onToggle,
  onAccept,
  onReject,
}: ActionCardProps) {
  const { t } = useTranslation();

  // ``auto_applied`` only exists in threads stored before 18.1.
  const autoApplied = action.status === 'auto_applied';
  const isApplied = autoApplied || action.status === 'applied';
  const isFailed = action.status === 'failed';
  const isDismissed = action.status === 'dismissed';
  const pending = isPending(action);

  const confidencePct = Math.round((action.confidence ?? 0) * 100);

  const { title, before, after } = describeAction(action, t);
  const sourceCode = action.source?.code;
  const sourceDesc = action.source?.description;

  return (
    <div
      data-testid="copilot-action-card"
      className={`rounded-lg border px-3 py-2.5 ${
        isFailed
          ? 'border-semantic-error/40 bg-semantic-error-bg/40'
          : isApplied
            ? 'border-emerald-300 bg-emerald-50 dark:border-emerald-800/60 dark:bg-emerald-900/15'
            : isDismissed
              ? 'border-border-light bg-surface-secondary/40 opacity-70'
              : 'border-border-light bg-surface-primary'
      }`}
    >
      {/* Top row: checkbox + title + confidence */}
      <div className="mb-1.5 flex items-center justify-between gap-2">
        <label className="flex min-w-0 items-center gap-2">
          {showCheckbox && pending && (
            <input
              type="checkbox"
              checked={checked}
              onChange={onToggle}
              disabled={busy}
              aria-label={t('boq.copilot.select_change', { defaultValue: 'Select this change' })}
              className="h-3.5 w-3.5 shrink-0 accent-oe-blue"
            />
          )}
          <span className="truncate text-2xs font-semibold uppercase tracking-wide text-content-tertiary">
            {title}
          </span>
        </label>
        <span
          className={`shrink-0 rounded-full px-1.5 py-0.5 text-2xs font-semibold tabular-nums ${
            (action.confidence ?? 0) >= PRESELECT_THRESHOLD
              ? 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-300'
              : 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300'
          }`}
          title={t('boq.copilot.confidence', { defaultValue: 'Confidence' })}
        >
          {confidencePct}%
        </span>
      </div>

      {/* Diff: before -> after */}
      <div className="flex flex-wrap items-center gap-1.5 text-xs text-content-primary">
        {before != null && before !== '' && (
          <span className="rounded bg-surface-secondary px-1.5 py-0.5 text-content-tertiary line-through">
            {before}
          </span>
        )}
        <ArrowRight size={12} className="text-content-tertiary" />
        <span className="rounded bg-oe-blue-subtle/30 px-1.5 py-0.5 font-medium text-content-primary">
          {after}
        </span>
      </div>

      {/* Catalog source */}
      {(sourceCode || sourceDesc) && (
        <div className="mt-1.5 flex items-center gap-1 text-2xs text-content-tertiary">
          <Tag size={10} />
          {sourceCode && <span className="font-mono">{sourceCode}</span>}
          {sourceDesc && <span className="truncate">{sourceDesc}</span>}
        </div>
      )}

      {/* Why the last attempt did not land (kept open for a retry). */}
      {isFailed && (
        <div className="mt-1.5 flex items-start gap-1 text-2xs text-semantic-error">
          <AlertCircle size={11} className="mt-px shrink-0" />
          <span>
            {action.error || t('boq.copilot.failed', { defaultValue: 'Could not be applied' })}
          </span>
        </div>
      )}

      {/* Footer: status / decision */}
      <div className="mt-2 flex items-center gap-2">
        {isApplied && (
          <span className="inline-flex items-center gap-1 text-2xs font-medium text-emerald-600 dark:text-emerald-400">
            <Check size={12} strokeWidth={3} />
            {autoApplied
              ? t('boq.copilot.auto_applied', { defaultValue: 'Auto-applied' })
              : t('boq.copilot.applied', { defaultValue: 'Applied' })}
          </span>
        )}
        {undoable && (
          <span className="inline-flex items-center gap-1 text-2xs text-content-tertiary">
            <Undo2 size={11} />
            {t('boq.copilot.undo_hint', { defaultValue: 'Press Ctrl+Z to undo' })}
          </span>
        )}
        {pending && (
          <>
            <button
              type="button"
              onClick={onAccept}
              disabled={busy}
              className="inline-flex items-center gap-1 rounded-md bg-oe-blue px-2.5 py-1 text-2xs font-semibold text-white hover:bg-oe-blue-hover disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            >
              <Check size={11} strokeWidth={3} />
              {t('boq.copilot.accept', { defaultValue: 'Accept' })}
            </button>
            <button
              type="button"
              onClick={onReject}
              disabled={busy}
              className="inline-flex items-center gap-1 rounded-md px-2.5 py-1 text-2xs font-medium text-content-secondary hover:bg-surface-secondary disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            >
              <X size={11} />
              {t('boq.copilot.reject', { defaultValue: 'Reject' })}
            </button>
          </>
        )}
        {isDismissed && (
          <span className="text-2xs text-content-tertiary">
            {t('boq.copilot.dismissed', { defaultValue: 'Dismissed' })}
          </span>
        )}
      </div>
    </div>
  );
}

/* ── Action description (title + before/after diff strings) ─────────── */

function describeAction(
  action: CopilotAction,
  t: TFunction,
): { title: string; before: string | null; after: string } {
  const { payload, before } = action;

  switch (action.action_type) {
    case 'update_description': {
      return {
        title: t('boq.copilot.act_description', { defaultValue: 'Description' }),
        before: asString(before, 'description') ?? null,
        after:
          asString(payload, 'description') ??
          t('boq.copilot.no_change', { defaultValue: '(no change)' }),
      };
    }
    case 'set_quantity': {
      const beforeQ = asNumber(before, 'quantity');
      const afterQ = asNumber(payload, 'quantity');
      const unit = asString(payload, 'unit') ?? asString(before, 'unit') ?? '';
      return {
        title: t('boq.copilot.act_quantity', { defaultValue: 'Quantity' }),
        before: beforeQ != null ? `${fmtNum(beforeQ)} ${unit}`.trim() : null,
        after:
          afterQ != null
            ? `${fmtNum(afterQ)} ${unit}`.trim()
            : t('boq.copilot.no_change', { defaultValue: '(no change)' }),
      };
    }
    case 'set_unit_rate': {
      const beforeR = asNumber(before, 'unit_rate');
      const afterR = asNumber(payload, 'unit_rate');
      const currency = asString(payload, 'currency') ?? asString(before, 'currency') ?? '';
      return {
        title: t('boq.copilot.act_unit_rate', { defaultValue: 'Unit rate' }),
        before: beforeR != null ? `${fmtNum(beforeR)} ${currency}`.trim() : null,
        after:
          afterR != null
            ? `${fmtNum(afterR)} ${currency}`.trim()
            : t('boq.copilot.no_change', { defaultValue: '(no change)' }),
      };
    }
    case 'add_resources': {
      const resources = asResources(payload);
      const names = fmtList(resources
        .map((r) => r.name)
        .filter(Boolean)
        .slice(0, 3));
      const extra = resources.length > 3 ? ` +${resources.length - 3}` : '';
      return {
        title: t('boq.copilot.act_resources', { defaultValue: 'Add resources' }),
        before: null,
        after:
          (names ? `${names}${extra}` : '') ||
          t('boq.copilot.n_resources', {
            defaultValue: '{{count}} resources',
            count: resources.length,
          }),
      };
    }
    default:
      return {
        title: t('boq.copilot.act_change', { defaultValue: 'Change' }),
        before: null,
        after: t('boq.copilot.no_change', { defaultValue: '(no change)' }),
      };
  }
}
