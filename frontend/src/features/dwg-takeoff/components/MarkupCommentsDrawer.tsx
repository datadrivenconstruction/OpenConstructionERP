// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * MarkupCommentsDrawer — right-side drawer showing the threaded comments
 * for a single markup. Opens when a markup is selected and the user clicks
 * the "Comments" button in the takeoff toolbar.
 *
 * The drawer talks to the unified markups module's comments endpoints
 * (``/v1/markups/{id}/comments/``). Each comment is flat (no nested
 * replies in v1) — the parent ``Markup`` owns its own thread.
 *
 * This component is intentionally presentation + React-Query only; the
 * parent ``DwgTakeoffPage`` decides when to open it and passes in the
 * selected markup id. When ``markupId`` is null, the drawer renders an
 * empty / closed shell so the caller can keep it permanently mounted
 * without a flash on open.
 */

import { useCallback, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { MessageSquare, Send, Trash2, X, Loader2 } from 'lucide-react';
import { Button } from '@/shared/ui';
import { useToastStore } from '@/stores/useToastStore';
import { useAuthStore } from '@/stores/useAuthStore';
import {
  fetchMarkupComments,
  createMarkupComment,
  deleteMarkupComment,
  type MarkupComment,
} from '@/features/markups/api';
import { getIntlLocale } from '@/shared/lib/formatters';

/** React-Query key used by both the drawer (`[..., markupId]`) and the
 *  badge count hook (`[...]`). Exported so the parent page can invalidate
 *  on its own when needed. */
export const MARKUP_COMMENTS_QUERY_KEY = ['markup-comments'] as const;

interface Props {
  /** Markup whose comments are being viewed. ``null`` keeps the drawer
   *  closed; the caller flips this to open. */
  markupId: string | null;
  /** Called when the user clicks the X button or presses Escape. */
  onClose: () => void;
}

const QUERY_KEY = MARKUP_COMMENTS_QUERY_KEY;

function formatTimestamp(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString(getIntlLocale());
}

export function MarkupCommentsDrawer({ markupId, onClose }: Props): JSX.Element | null {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  // Comments store user_id (email-derived id from the JWT subject); the
  // app's auth store keeps the raw email — fall back to that for the
  // "is this mine?" check.
  const currentUserEmail = useAuthStore((s) => s.userEmail);
  const [draft, setDraft] = useState('');

  const open = markupId !== null;

  const { data, isLoading, error } = useQuery<MarkupComment[]>({
    queryKey: [...QUERY_KEY, markupId],
    queryFn: () => fetchMarkupComments(markupId as string),
    enabled: open,
    staleTime: 30_000,
  });

  const createMut = useMutation({
    mutationFn: (body: string) => createMarkupComment(markupId as string, body),
    onSuccess: () => {
      setDraft('');
      qc.invalidateQueries({ queryKey: [...QUERY_KEY, markupId] });
      // Also bump comment-count badges if the parent caches them.
      qc.invalidateQueries({ queryKey: ['markup-comment-counts'] });
      addToast({
        type: 'success',
        title: t('takeoff.markup.comment_added', { defaultValue: 'Comment added' }),
      });
    },
    onError: (e: Error) => {
      addToast({
        type: 'error',
        title: t('takeoff.markup.comment_failed', {
          defaultValue: 'Could not add comment',
        }),
        message: e.message,
      });
    },
  });

  const deleteMut = useMutation({
    mutationFn: (commentId: string) =>
      deleteMarkupComment(markupId as string, commentId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: [...QUERY_KEY, markupId] });
      qc.invalidateQueries({ queryKey: ['markup-comment-counts'] });
      addToast({
        type: 'success',
        title: t('takeoff.markup.comment_deleted', { defaultValue: 'Comment deleted' }),
      });
    },
    onError: (e: Error) => {
      addToast({
        type: 'error',
        title: t('takeoff.markup.comment_delete_failed', {
          defaultValue: 'Could not delete comment',
        }),
        message: e.message,
      });
    },
  });

  const handleSend = useCallback(() => {
    const body = draft.trim();
    if (!body) return;
    createMut.mutate(body);
  }, [draft, createMut]);

  // Don't unmount when closed — keep the drawer in the tree so React-Query
  // cache survives reopening the same markup. Just hide it.
  if (!open) return null;

  return (
    <aside
      className="fixed inset-y-0 right-0 z-40 flex h-full w-96 max-w-full flex-col border-l border-zinc-200 bg-white shadow-2xl dark:border-zinc-700 dark:bg-zinc-900"
      role="dialog"
      aria-label={t('takeoff.markup.comments_drawer', {
        defaultValue: 'Markup comments',
      })}
    >
      <header className="flex items-center justify-between border-b border-zinc-200 px-4 py-3 dark:border-zinc-700">
        <div className="flex items-center gap-2">
          <MessageSquare className="h-4 w-4 text-zinc-500" />
          <h2 className="text-sm font-semibold">
            {t('takeoff.markup.comments_title', { defaultValue: 'Comments' })}
          </h2>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="rounded p-1 text-zinc-500 hover:bg-zinc-100 dark:hover:bg-zinc-800"
          aria-label={t('takeoff.markup.close', { defaultValue: 'Close' })}
        >
          <X className="h-4 w-4" />
        </button>
      </header>

      <div className="flex-1 overflow-y-auto px-4 py-3">
        {isLoading ? (
          <div className="flex items-center justify-center py-8 text-zinc-500">
            <Loader2 className="h-4 w-4 animate-spin" />
          </div>
        ) : error ? (
          <p className="text-sm text-red-600">
            {t('takeoff.markup.comments_load_failed', {
              defaultValue: 'Could not load comments.',
            })}
          </p>
        ) : !data || data.length === 0 ? (
          <p className="text-sm text-zinc-500">
            {t('takeoff.markup.comments_empty', {
              defaultValue: 'No comments yet - be the first to add one.',
            })}
          </p>
        ) : (
          <ul className="space-y-3">
            {data.map((c) => {
              const isMine = !!currentUserEmail && currentUserEmail === c.user_id;
              return (
                <li
                  key={c.id}
                  className="rounded border border-zinc-200 bg-zinc-50 p-3 dark:border-zinc-700 dark:bg-zinc-800"
                >
                  <div className="mb-1 flex items-center justify-between text-xs text-zinc-500">
                    <span className="font-medium">{c.user_id}</span>
                    <span>{formatTimestamp(c.created_at)}</span>
                  </div>
                  <p className="whitespace-pre-wrap text-sm">{c.body}</p>
                  {isMine ? (
                    <div className="mt-2 flex justify-end">
                      <button
                        type="button"
                        onClick={() => deleteMut.mutate(c.id)}
                        disabled={deleteMut.isPending}
                        className="inline-flex items-center gap-1 text-xs text-zinc-500 hover:text-red-600"
                        aria-label={t('takeoff.markup.comment_delete', {
                          defaultValue: 'Delete comment',
                        })}
                      >
                        <Trash2 className="h-3 w-3" />
                        {t('takeoff.markup.comment_delete', {
                          defaultValue: 'Delete',
                        })}
                      </button>
                    </div>
                  ) : null}
                </li>
              );
            })}
          </ul>
        )}
      </div>

      <footer className="border-t border-zinc-200 px-4 py-3 dark:border-zinc-700">
        <label htmlFor="markup-comment-input" className="sr-only">
          {t('takeoff.markup.comment_placeholder', {
            defaultValue: 'Write a comment...',
          })}
        </label>
        <textarea
          id="markup-comment-input"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder={t('takeoff.markup.comment_placeholder', {
            defaultValue: 'Write a comment...',
          })}
          rows={3}
          className="w-full resize-none rounded border border-zinc-300 px-3 py-2 text-sm focus:border-oe-blue focus:outline-none dark:border-zinc-600 dark:bg-zinc-800"
          onKeyDown={(e) => {
            if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
              e.preventDefault();
              handleSend();
            }
          }}
        />
        <div className="mt-2 flex items-center justify-between">
          <span className="text-xs text-zinc-500">
            {t('takeoff.markup.comment_hint', {
              defaultValue: 'Ctrl/Cmd+Enter to send',
            })}
          </span>
          <Button
            type="button"
            onClick={handleSend}
            disabled={createMut.isPending || draft.trim().length === 0}
            size="sm"
          >
            {createMut.isPending ? (
              <Loader2 className="h-3 w-3 animate-spin" />
            ) : (
              <Send className="h-3 w-3" />
            )}
            <span className="ml-1">
              {t('takeoff.markup.comment_send', { defaultValue: 'Send' })}
            </span>
          </Button>
        </div>
      </footer>
    </aside>
  );
}
