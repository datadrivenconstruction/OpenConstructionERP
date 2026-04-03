/**
 * CommentDrawer — Slide-out panel for viewing and adding comments on a BOQ position.
 *
 * Comments are stored as an array in `position.metadata.comments`:
 *   [{ id, text, author, created_at }]
 *
 * Backward-compatible: if only legacy `metadata.comment` (string) exists,
 * it's displayed as the first entry.
 */

import { useState, useRef, useEffect, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { X, Send, MessageSquare, Trash2, Clock } from 'lucide-react';

/* ── Types ───────────────────────────────────────────────────────────── */

export interface CommentEntry {
  id: string;
  text: string;
  author: string;
  created_at: string; // ISO string
}

export interface CommentDrawerProps {
  positionId: string;
  positionOrdinal: string;
  positionDescription: string;
  /** Full metadata of the position — we read comments from here. */
  metadata: Record<string, unknown>;
  currentUserEmail: string;
  onSave: (positionId: string, updatedComments: CommentEntry[]) => void;
  onClose: () => void;
}

/* ── Helpers ──────────────────────────────────────────────────────────── */

function generateId(): string {
  return `c_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 6)}`;
}

function formatRelativeTime(isoString: string, t: (k: string, o?: Record<string, string | number>) => string): string {
  const date = new Date(isoString);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffMin = Math.floor(diffMs / 60_000);
  const diffH = Math.floor(diffMs / 3_600_000);
  const diffD = Math.floor(diffMs / 86_400_000);

  if (diffMin < 1) return t('comments.just_now', { defaultValue: 'just now' });
  if (diffMin < 60) return t('comments.minutes_ago', { defaultValue: '{{count}}m ago', count: diffMin });
  if (diffH < 24) return t('comments.hours_ago', { defaultValue: '{{count}}h ago', count: diffH });
  if (diffD < 7) return t('comments.days_ago', { defaultValue: '{{count}}d ago', count: diffD });
  return date.toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' });
}

/** Read comments from position metadata, handling both legacy string and new array formats. */
export function readComments(metadata: Record<string, unknown>): CommentEntry[] {
  // New format: metadata.comments = CommentEntry[]
  if (Array.isArray(metadata.comments)) {
    return metadata.comments as CommentEntry[];
  }

  // Legacy format: metadata.comment = string
  const legacy = (metadata.comment ?? metadata.notes) as string | undefined;
  if (legacy && typeof legacy === 'string' && legacy.trim()) {
    return [{
      id: 'legacy_0',
      text: legacy,
      author: '',
      created_at: metadata.comment_updated_at as string ?? new Date().toISOString(),
    }];
  }

  return [];
}

/** Count comments for indicator badge. */
export function countComments(metadata: Record<string, unknown> | undefined): number {
  if (!metadata) return 0;
  if (Array.isArray(metadata.comments)) return (metadata.comments as CommentEntry[]).length;
  const legacy = (metadata.comment ?? metadata.notes) as string | undefined;
  return legacy && typeof legacy === 'string' && legacy.trim() ? 1 : 0;
}

/* ── Component ───────────────────────────────────────────────────────── */

export function CommentDrawer({
  positionId,
  positionOrdinal,
  positionDescription,
  metadata,
  currentUserEmail,
  onSave,
  onClose,
}: CommentDrawerProps) {
  const { t } = useTranslation();
  const [inputText, setInputText] = useState('');
  const scrollRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  const comments = useMemo(() => readComments(metadata), [metadata]);

  // Scroll to bottom when comments change
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [comments.length]);

  // Auto-focus input
  useEffect(() => {
    setTimeout(() => inputRef.current?.focus(), 100);
  }, []);

  const handleSubmit = () => {
    const text = inputText.trim();
    if (!text) return;

    const newComment: CommentEntry = {
      id: generateId(),
      text,
      author: currentUserEmail || 'anonymous',
      created_at: new Date().toISOString(),
    };

    onSave(positionId, [...comments, newComment]);
    setInputText('');
  };

  const handleDelete = (commentId: string) => {
    onSave(positionId, comments.filter((c) => c.id !== commentId));
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
    if (e.key === 'Escape') {
      onClose();
    }
  };

  const authorInitial = (email: string) =>
    email ? email.charAt(0).toUpperCase() : '?';

  const authorDisplay = (email: string) => {
    if (!email) return t('comments.unknown_author', { defaultValue: 'Unknown' });
    // Show part before @
    const at = email.indexOf('@');
    return at > 0 ? email.slice(0, at) : email;
  };

  return (
    <div className="fixed inset-0 z-50 flex justify-end" onClick={onClose}>
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/20 backdrop-blur-[2px]" />

      {/* Drawer panel */}
      <div
        role="dialog"
        aria-modal="true"
        aria-label={t('comments.title', { defaultValue: 'Comments' })}
        className="relative w-full max-w-md bg-surface-elevated border-l border-border-light shadow-2xl
                    flex flex-col animate-slide-in-right"
        onClick={(e) => e.stopPropagation()}
      >
        {/* ── Header ─────────────────────────────────────────────────── */}
        <div className="flex items-start gap-3 px-5 py-4 border-b border-border-light shrink-0">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-amber-100 text-amber-600 dark:bg-amber-900/30 dark:text-amber-400 shrink-0">
            <MessageSquare size={17} />
          </div>
          <div className="flex-1 min-w-0">
            <h2 className="text-sm font-semibold text-content-primary">
              {t('comments.title', { defaultValue: 'Comments' })}
            </h2>
            <p className="text-xs text-content-tertiary truncate mt-0.5">
              <span className="font-mono">{positionOrdinal}</span>
              {positionDescription && <> — {positionDescription}</>}
            </p>
          </div>
          <button
            onClick={onClose}
            aria-label={t('common.close', { defaultValue: 'Close' })}
            className="flex h-8 w-8 items-center justify-center rounded-lg text-content-tertiary hover:bg-surface-secondary hover:text-content-primary transition-colors shrink-0"
          >
            <X size={16} />
          </button>
        </div>

        {/* ── Comments thread ────────────────────────────────────────── */}
        <div ref={scrollRef} className="flex-1 overflow-y-auto px-5 py-4 space-y-3">
          {comments.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12 text-center">
              <MessageSquare size={28} className="text-content-quaternary mb-3" />
              <p className="text-sm text-content-secondary">
                {t('comments.no_comments', { defaultValue: 'No comments yet' })}
              </p>
              <p className="text-xs text-content-tertiary mt-1">
                {t('comments.no_comments_hint', { defaultValue: 'Add notes, assumptions, or references for this position' })}
              </p>
            </div>
          ) : (
            comments.map((comment) => {
              const isOwn = comment.author === currentUserEmail;
              return (
                <div
                  key={comment.id}
                  className="group rounded-xl p-3 bg-surface-secondary/50 hover:bg-surface-secondary transition-colors"
                >
                  {/* Author row */}
                  <div className="flex items-center gap-2 mb-1.5">
                    <span
                      className={`flex h-5 w-5 items-center justify-center rounded-full text-[10px] font-bold text-white shrink-0 ${
                        isOwn ? 'bg-oe-blue' : 'bg-content-tertiary'
                      }`}
                    >
                      {authorInitial(comment.author)}
                    </span>
                    <span className="text-xs font-medium text-content-primary">
                      {authorDisplay(comment.author)}
                    </span>
                    <span className="flex items-center gap-0.5 text-[10px] text-content-quaternary ml-auto">
                      <Clock size={9} />
                      {formatRelativeTime(comment.created_at, t)}
                    </span>
                    {/* Delete button (own comments only) */}
                    {isOwn && (
                      <button
                        onClick={() => handleDelete(comment.id)}
                        className="flex h-5 w-5 items-center justify-center rounded text-content-quaternary
                                   hover:text-semantic-error hover:bg-semantic-error-bg
                                   opacity-0 group-hover:opacity-100 transition-all shrink-0"
                        aria-label={t('comments.delete', { defaultValue: 'Delete comment' })}
                        title={t('comments.delete', { defaultValue: 'Delete comment' })}
                      >
                        <Trash2 size={11} />
                      </button>
                    )}
                  </div>
                  {/* Text */}
                  <p className="text-xs text-content-secondary leading-relaxed whitespace-pre-wrap break-words pl-7">
                    {comment.text}
                  </p>
                </div>
              );
            })
          )}
        </div>

        {/* ── Input ──────────────────────────────────────────────────── */}
        <div className="shrink-0 border-t border-border-light px-5 py-3 bg-surface-primary/50">
          <div className="flex items-end gap-2">
            <textarea
              ref={inputRef}
              value={inputText}
              onChange={(e) => setInputText(e.target.value)}
              onKeyDown={handleKeyDown}
              rows={2}
              aria-label={t('comments.input_placeholder', { defaultValue: 'Write a comment... (Enter to send)' })}
              placeholder={t('comments.input_placeholder', { defaultValue: 'Write a comment... (Enter to send)' })}
              className="flex-1 rounded-lg border border-border-light bg-surface-primary px-3 py-2
                         text-xs text-content-primary placeholder:text-content-quaternary
                         focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue
                         resize-none"
            />
            <button
              onClick={handleSubmit}
              disabled={!inputText.trim()}
              className="flex h-8 w-8 items-center justify-center rounded-lg
                         bg-oe-blue text-white
                         hover:bg-oe-blue-hover
                         disabled:opacity-30 disabled:cursor-not-allowed
                         transition-all shrink-0"
              aria-label={t('comments.send', { defaultValue: 'Send' })}
              title={t('comments.send', { defaultValue: 'Send' })}
            >
              <Send size={14} />
            </button>
          </div>
          <p className="text-[10px] text-content-quaternary mt-1.5">
            {t('comments.shortcut_hint', { defaultValue: 'Enter to send · Shift+Enter for new line · Esc to close' })}
          </p>
        </div>
      </div>
    </div>
  );
}
