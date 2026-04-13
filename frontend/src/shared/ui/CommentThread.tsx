/**
 * CommentThread -- reusable threaded comments component.
 *
 * Can be embedded in any page (BOQ, Tasks, Meetings, Documents, etc.) by
 * passing `entityType` and `entityId` props.
 *
 * API endpoints:
 *   GET    /api/v1/collaboration/comments?entity_type=X&entity_id=Y
 *   POST   /api/v1/collaboration/comments
 *   PATCH  /api/v1/collaboration/comments/{id}
 *   DELETE /api/v1/collaboration/comments/{id}
 */

import { useState, useRef, useCallback, useEffect, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { MessageSquare, Send, Reply, Pencil, Trash2, X, Check } from 'lucide-react';
import clsx from 'clsx';
import { apiGet, apiPost, apiPatch, apiDelete } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';

// -- Types -------------------------------------------------------------------

interface CommentMention {
  id: string;
  comment_id: string;
  mentioned_user_id: string;
  mention_type: string;
  created_at: string;
}

interface CommentData {
  id: string;
  entity_type: string;
  entity_id: string;
  author_id: string;
  text: string;
  comment_type: string;
  parent_comment_id: string | null;
  edited_at: string | null;
  is_deleted: boolean;
  metadata: Record<string, unknown>;
  mentions: CommentMention[];
  replies: CommentData[];
  created_at: string;
  updated_at: string;
}

interface CommentListResponse {
  items: CommentData[];
  total: number;
}

export interface CommentThreadProps {
  entityType: string;
  entityId: string;
  className?: string;
}

// -- Helpers -----------------------------------------------------------------

function formatTimeAgo(
  dateStr: string,
  t: ReturnType<typeof useTranslation>['t'],
): string {
  const diff = Date.now() - new Date(dateStr).getTime();
  const seconds = Math.floor(diff / 1000);
  if (seconds < 60) return t('comments.just_now', { defaultValue: 'Just now' });
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60)
    return t('time.minutes_ago', { defaultValue: '{{count}}m ago', count: minutes });
  const hours = Math.floor(minutes / 60);
  if (hours < 24)
    return t('time.hours_ago', { defaultValue: '{{count}}h ago', count: hours });
  const days = Math.floor(hours / 24);
  return t('time.days_ago', { defaultValue: '{{count}}d ago', count: days });
}

/** Get the first letter of a user ID for avatar placeholder. */
function avatarLetter(authorId: string): string {
  return (authorId[0] ?? 'U').toUpperCase();
}

/** Deterministic color based on author ID. */
const AVATAR_COLORS = [
  'bg-blue-500',
  'bg-emerald-500',
  'bg-amber-500',
  'bg-violet-500',
  'bg-rose-500',
  'bg-cyan-500',
  'bg-orange-500',
  'bg-indigo-500',
];

function avatarColor(authorId: string): string {
  let hash = 0;
  for (let i = 0; i < authorId.length; i++) {
    hash = ((hash << 5) - hash + authorId.charCodeAt(i)) | 0;
  }
  return AVATAR_COLORS[Math.abs(hash) % AVATAR_COLORS.length]!;
}

/** Highlight @mentions in text. */
function renderTextWithMentions(text: string): React.ReactNode {
  const parts = text.split(/(@\w[\w.]*)/g);
  return parts.map((part, i) =>
    part.startsWith('@') ? (
      <span key={i} className="font-semibold text-oe-blue">
        {part}
      </span>
    ) : (
      <span key={i}>{part}</span>
    ),
  );
}

// -- Single Comment ----------------------------------------------------------

interface CommentItemProps {
  comment: CommentData;
  isReply?: boolean;
  onReply: (commentId: string) => void;
  onEdit: (commentId: string, newText: string) => void;
  onDelete: (commentId: string) => void;
  isNew?: boolean;
  t: ReturnType<typeof useTranslation>['t'];
}

function CommentItem({
  comment,
  isReply = false,
  onReply,
  onEdit,
  onDelete,
  isNew = false,
  t,
}: CommentItemProps) {
  const [editing, setEditing] = useState(false);
  const [editText, setEditText] = useState(comment.text);
  const editRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (editing && editRef.current) {
      editRef.current.focus();
      editRef.current.setSelectionRange(editText.length, editText.length);
    }
  }, [editing, editText.length]);

  const handleSaveEdit = useCallback(() => {
    const trimmed = editText.trim();
    if (trimmed && trimmed !== comment.text) {
      onEdit(comment.id, trimmed);
    }
    setEditing(false);
  }, [editText, comment.id, comment.text, onEdit]);

  const handleCancelEdit = useCallback(() => {
    setEditText(comment.text);
    setEditing(false);
  }, [comment.text]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
        e.preventDefault();
        handleSaveEdit();
      }
      if (e.key === 'Escape') {
        handleCancelEdit();
      }
    },
    [handleSaveEdit, handleCancelEdit],
  );

  if (comment.is_deleted) {
    return (
      <div
        className={clsx(
          'flex items-start gap-2.5 py-2',
          isReply && 'ml-8 pl-3 border-l-2 border-border-light',
        )}
      >
        <p className="text-xs text-content-quaternary italic">
          {t('comments.deleted', { defaultValue: 'This comment was deleted.' })}
        </p>
      </div>
    );
  }

  return (
    <div
      className={clsx(
        'group flex items-start gap-2.5 py-2.5',
        isReply && 'ml-8 pl-3 border-l-2 border-border-light',
        isNew && 'bg-oe-blue-subtle/30 rounded-lg px-2 -mx-2',
      )}
    >
      {/* Avatar */}
      <div
        className={clsx(
          'flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-[11px] font-bold text-white',
          avatarColor(comment.author_id),
        )}
        title={comment.author_id}
      >
        {avatarLetter(comment.author_id)}
      </div>

      {/* Body */}
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="text-xs font-semibold text-content-primary truncate max-w-[120px]">
            {comment.author_id.slice(0, 8)}
          </span>
          <span className="text-2xs text-content-quaternary">
            {formatTimeAgo(comment.created_at, t)}
          </span>
          {comment.edited_at && (
            <span className="text-2xs text-content-quaternary italic">
              {t('comments.edited', { defaultValue: '(edited)' })}
            </span>
          )}
        </div>

        {editing ? (
          <div className="mt-1">
            <textarea
              ref={editRef}
              value={editText}
              onChange={(e) => setEditText(e.target.value)}
              onKeyDown={handleKeyDown}
              className="w-full rounded-lg border border-border-medium bg-surface-primary px-2.5 py-1.5 text-xs text-content-primary placeholder:text-content-quaternary focus:border-oe-blue focus:outline-none focus:ring-1 focus:ring-oe-blue/30 resize-none"
              rows={2}
            />
            <div className="flex gap-1.5 mt-1">
              <button
                onClick={handleSaveEdit}
                className="flex items-center gap-1 rounded px-2 py-0.5 text-2xs font-medium text-white bg-oe-blue hover:bg-oe-blue-hover transition-colors"
              >
                <Check size={10} />
                {t('common.save', { defaultValue: 'Save' })}
              </button>
              <button
                onClick={handleCancelEdit}
                className="flex items-center gap-1 rounded px-2 py-0.5 text-2xs font-medium text-content-secondary hover:text-content-primary transition-colors"
              >
                <X size={10} />
                {t('common.cancel', { defaultValue: 'Cancel' })}
              </button>
            </div>
          </div>
        ) : (
          <p className="mt-0.5 text-xs text-content-secondary leading-relaxed whitespace-pre-wrap break-words">
            {renderTextWithMentions(comment.text)}
          </p>
        )}

        {/* Actions */}
        {!editing && (
          <div className="flex items-center gap-2 mt-1 opacity-0 group-hover:opacity-100 transition-opacity">
            {!isReply && (
              <button
                onClick={() => onReply(comment.id)}
                className="flex items-center gap-1 text-2xs text-content-tertiary hover:text-oe-blue transition-colors"
              >
                <Reply size={10} />
                {t('comments.reply', { defaultValue: 'Reply' })}
              </button>
            )}
            <button
              onClick={() => {
                setEditText(comment.text);
                setEditing(true);
              }}
              className="flex items-center gap-1 text-2xs text-content-tertiary hover:text-oe-blue transition-colors"
            >
              <Pencil size={10} />
              {t('comments.edit', { defaultValue: 'Edit' })}
            </button>
            <button
              onClick={() => onDelete(comment.id)}
              className="flex items-center gap-1 text-2xs text-content-tertiary hover:text-semantic-error transition-colors"
            >
              <Trash2 size={10} />
              {t('comments.delete', { defaultValue: 'Delete' })}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

// -- Main Component ----------------------------------------------------------

export function CommentThread({ entityType, entityId, className }: CommentThreadProps) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);

  const [newText, setNewText] = useState('');
  const [replyToId, setReplyToId] = useState<string | null>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  const queryKey = useMemo(
    () => ['comments', entityType, entityId],
    [entityType, entityId],
  );

  // -- Fetch comments --------------------------------------------------------

  const { data, isLoading } = useQuery({
    queryKey,
    queryFn: () =>
      apiGet<CommentListResponse>(
        `/v1/collaboration/comments?entity_type=${encodeURIComponent(entityType)}&entity_id=${encodeURIComponent(entityId)}`,
      ),
    staleTime: 15_000,
    refetchInterval: 30_000,
    retry: false,
  });

  const comments = data?.items ?? [];
  const total = data?.total ?? 0;

  // Sort newest first
  const sortedComments = useMemo(
    () =>
      [...comments].sort(
        (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime(),
      ),
    [comments],
  );

  // -- Mutations -------------------------------------------------------------

  const createMutation = useMutation({
    mutationFn: (body: {
      entity_type: string;
      entity_id: string;
      text: string;
      parent_comment_id?: string;
    }) => apiPost<CommentData>('/v1/collaboration/comments/', body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey });
      setNewText('');
      setReplyToId(null);
    },
    onError: (err: Error) => {
      addToast({ type: 'error', title: t('comments.create_failed', { defaultValue: 'Failed to post comment' }), message: err.message });
    },
  });

  const editMutation = useMutation({
    mutationFn: ({ id, text }: { id: string; text: string }) =>
      apiPatch<CommentData>(`/v1/collaboration/comments/${id}`, { text }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey });
    },
    onError: (err: Error) => {
      addToast({ type: 'error', title: t('comments.edit_failed', { defaultValue: 'Failed to edit comment' }), message: err.message });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => apiDelete(`/v1/collaboration/comments/${id}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey });
    },
    onError: (err: Error) => {
      addToast({ type: 'error', title: t('comments.delete_failed', { defaultValue: 'Failed to delete comment' }), message: err.message });
    },
  });

  // -- Handlers --------------------------------------------------------------

  const handlePost = useCallback(() => {
    const trimmed = newText.trim();
    if (!trimmed) return;

    createMutation.mutate({
      entity_type: entityType,
      entity_id: entityId,
      text: trimmed,
      ...(replyToId ? { parent_comment_id: replyToId } : {}),
    });
  }, [newText, entityType, entityId, replyToId, createMutation]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
        e.preventDefault();
        handlePost();
      }
      if (e.key === 'Escape' && replyToId) {
        setReplyToId(null);
      }
    },
    [handlePost, replyToId],
  );

  const handleReply = useCallback((commentId: string) => {
    setReplyToId(commentId);
    inputRef.current?.focus();
  }, []);

  const handleEdit = useCallback(
    (commentId: string, newTextVal: string) => {
      editMutation.mutate({ id: commentId, text: newTextVal });
    },
    [editMutation],
  );

  const handleDelete = useCallback(
    (commentId: string) => {
      deleteMutation.mutate(commentId);
    },
    [deleteMutation],
  );

  const handleCancelReply = useCallback(() => {
    setReplyToId(null);
  }, []);

  // Focus input when replyToId changes
  useEffect(() => {
    if (replyToId) {
      inputRef.current?.focus();
    }
  }, [replyToId]);

  // -- Render ----------------------------------------------------------------

  return (
    <div className={clsx('flex flex-col', className)}>
      {/* Header */}
      <div className="flex items-center gap-2 mb-3">
        <MessageSquare size={14} className="text-content-tertiary" />
        <span className="text-xs font-semibold text-content-primary">
          {t('comments.title', { defaultValue: 'Comments' })}
        </span>
        {total > 0 && (
          <span className="flex h-4.5 min-w-[18px] items-center justify-center rounded-full bg-surface-secondary px-1 text-2xs font-medium text-content-secondary">
            {total}
          </span>
        )}
      </div>

      {/* Input area */}
      <div className="mb-3">
        {replyToId && (
          <div className="flex items-center gap-1.5 mb-1.5 px-1">
            <Reply size={10} className="text-oe-blue" />
            <span className="text-2xs text-oe-blue font-medium">
              {t('comments.replying_to', { defaultValue: 'Replying to comment' })}
            </span>
            <button
              onClick={handleCancelReply}
              className="ml-auto text-content-tertiary hover:text-content-primary transition-colors"
              aria-label={t('common.cancel', { defaultValue: 'Cancel' })}
            >
              <X size={12} />
            </button>
          </div>
        )}
        <div className="flex gap-2">
          <textarea
            ref={inputRef}
            value={newText}
            onChange={(e) => setNewText(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={t('comments.placeholder', {
              defaultValue: 'Write a comment...',
            })}
            className="flex-1 rounded-lg border border-border-medium bg-surface-primary px-3 py-2 text-xs text-content-primary placeholder:text-content-quaternary focus:border-oe-blue focus:outline-none focus:ring-1 focus:ring-oe-blue/30 resize-none"
            rows={2}
          />
          <button
            onClick={handlePost}
            disabled={!newText.trim() || createMutation.isPending}
            className={clsx(
              'flex h-9 w-9 shrink-0 items-center justify-center rounded-lg transition-all',
              newText.trim()
                ? 'bg-oe-blue text-white hover:bg-oe-blue-hover'
                : 'bg-surface-secondary text-content-quaternary cursor-not-allowed',
            )}
            title={t('comments.post', { defaultValue: 'Post' })}
            aria-label={t('comments.post', { defaultValue: 'Post' })}
          >
            <Send size={14} />
          </button>
        </div>
        <p className="mt-1 text-2xs text-content-quaternary px-1">
          {t('comments.shortcut_hint', {
            defaultValue: 'Press Ctrl+Enter to post',
          })}
        </p>
      </div>

      {/* Comments list */}
      {isLoading ? (
        <div className="space-y-3">
          {[1, 2, 3].map((i) => (
            <div key={i} className="flex items-start gap-2.5 animate-pulse">
              <div className="h-7 w-7 rounded-full bg-surface-secondary" />
              <div className="flex-1 space-y-1.5">
                <div className="h-3 w-24 rounded bg-surface-secondary" />
                <div className="h-3 w-full rounded bg-surface-secondary" />
              </div>
            </div>
          ))}
        </div>
      ) : sortedComments.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-8 text-center">
          <MessageSquare size={28} className="mb-2 text-content-quaternary" />
          <p className="text-xs text-content-tertiary">
            {t('comments.empty', {
              defaultValue: 'No comments yet. Start the discussion.',
            })}
          </p>
        </div>
      ) : (
        <div className="divide-y divide-border-light">
          {sortedComments.map((comment) => (
            <div key={comment.id}>
              <CommentItem
                comment={comment}
                onReply={handleReply}
                onEdit={handleEdit}
                onDelete={handleDelete}
                t={t}
              />
              {/* Nested replies (1 level deep) */}
              {comment.replies.length > 0 && (
                <div>
                  {comment.replies.map((reply) => (
                    <CommentItem
                      key={reply.id}
                      comment={reply}
                      isReply
                      onReply={handleReply}
                      onEdit={handleEdit}
                      onDelete={handleDelete}
                      t={t}
                    />
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
