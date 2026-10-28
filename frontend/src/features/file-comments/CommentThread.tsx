// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/** Threaded comment view for a single file.
 *
 * Renders the response from ``GET /api/v1/file-comments/`` as a
 * recursive tree. Each node carries a Reply + Resolve affordance; the
 * resolve toggle only appears on top-level threads (replies inherit
 * the resolve state of their parent in practice).
 *
 * @mentions are highlighted inline by splitting the body around the
 * ``@(\\w{2,64})`` regex and rendering each captured handle as a
 * pill. A simple markdown-lite pass converts ``**bold**``, ``*italic*``
 * and back-tick code spans — no external lib so the bundle stays
 * tight.
 */

import { useCallback, useMemo, useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import clsx from 'clsx';
import { Button } from '@/shared/ui/Button';
import { EmptyState } from '@/shared/ui/EmptyState';
import { SkeletonText } from '@/shared/ui/Skeleton';
import {
  useDeleteFileComment,
  useFileCommentThreads,
  useUpdateFileComment,
} from './hooks';
import { CommentComposer } from './CommentComposer';
import { StaleVersionPill } from '@/features/file-versions/StaleVersionPill';
import type {
  FileCommentThread as ThreadNode,
  FileKind,
} from './types';
import { getIntlLocale } from '@/shared/lib/formatters';

// ── Body renderer (markdown-lite + @mentions) ──────────────────────────

const MENTION_RE = /(@\w{2,64})/g;
const BOLD_RE = /\*\*([^*]+)\*\*/g;
const ITALIC_RE = /(?<!\*)\*([^*]+)\*(?!\*)/g;
const CODE_RE = /`([^`]+)`/g;

function tokenizeBody(body: string): ReactNode[] {
  // Pass 1 — split on @mentions. Each non-mention segment is then
  // run through the markdown-lite passes.
  const parts = body.split(MENTION_RE);
  return parts.map((segment, idx) => {
    if (idx % 2 === 1) {
      // Captured mention.
      return (
        <span
          key={`m-${idx}`}
          className="rounded bg-oe-blue/10 px-1 py-0.5 font-medium text-oe-blue"
        >
          {segment}
        </span>
      );
    }
    return <MdLite key={`t-${idx}`} text={segment} />;
  });
}

function MdLite({ text }: { text: string }) {
  if (!text) return null;
  // Replace code first to avoid bold/italic stomping inside backticks.
  // Tokens build into an alternating array of plain strings and ReactNode
  // pieces. Each pass replaces in place, preserving order.
  type Node = string | ReactNode;
  let nodes: Node[] = [text];

  const applyPattern = (
    re: RegExp,
    wrap: (inner: string, key: string) => ReactNode,
  ): void => {
    const out: Node[] = [];
    nodes.forEach((node, ni) => {
      if (typeof node !== 'string') {
        out.push(node);
        return;
      }
      let lastIndex = 0;
      let match: RegExpExecArray | null;
      const reLocal = new RegExp(re.source, re.flags);
      while ((match = reLocal.exec(node)) !== null) {
        if (match.index > lastIndex) {
          out.push(node.slice(lastIndex, match.index));
        }
        out.push(wrap(match[1] ?? '', `n${ni}-${match.index}`));
        lastIndex = match.index + match[0].length;
      }
      if (lastIndex < node.length) {
        out.push(node.slice(lastIndex));
      }
    });
    nodes = out;
  };

  applyPattern(CODE_RE, (inner, key) => (
    <code
      key={key}
      className="rounded bg-surface-secondary px-1 py-0.5 font-mono text-xs"
    >
      {inner}
    </code>
  ));
  applyPattern(BOLD_RE, (inner, key) => (
    <strong key={key} className="font-semibold">
      {inner}
    </strong>
  ));
  applyPattern(ITALIC_RE, (inner, key) => (
    <em key={key} className="italic">
      {inner}
    </em>
  ));

  return <>{nodes}</>;
}

// ── Relative time ──────────────────────────────────────────────────────

function relativeTime(iso: string, now: Date = new Date()): string {
  const then = new Date(iso);
  const diff = (now.getTime() - then.getTime()) / 1000;
  if (Number.isNaN(diff)) return iso;
  if (diff < 60) return 'just now';
  if (diff < 3600) {
    const m = Math.floor(diff / 60);
    return `${m}m ago`;
  }
  if (diff < 86400) {
    const h = Math.floor(diff / 3600);
    return `${h}h ago`;
  }
  if (diff < 86400 * 30) {
    const d = Math.floor(diff / 86400);
    return `${d}d ago`;
  }
  return then.toLocaleDateString(getIntlLocale());
}

// ── Avatar ─────────────────────────────────────────────────────────────

/** Display label for a comment author: the server-resolved name, with a
 *  short-id fallback for legacy payloads that predate the enrichment. */
function authorLabel(authorName: string | null, authorId: string): string {
  const name = (authorName ?? '').trim();
  return name || authorId.slice(0, 8);
}

function initials(label: string): string {
  // Two-letter monogram from the resolved label: first letters of the
  // first two words (e.g. "Alice Smith" -> "AS"), else the first two
  // characters of a single token.
  const words = label.trim().split(/\s+/).filter(Boolean);
  if (words.length >= 2) {
    const a = words[0]?.[0] ?? '';
    const b = words[1]?.[0] ?? '';
    return (a + b).toUpperCase() || '??';
  }
  return label.replace(/[^a-z0-9]/gi, '').slice(0, 2).toUpperCase() || '??';
}

function Avatar({ label, size = 28 }: { label: string; size?: number }) {
  return (
    <div
      style={{ width: size, height: size }}
      className="flex shrink-0 items-center justify-center rounded-full bg-oe-blue/15 text-[10px] font-semibold text-oe-blue"
      title={label}
      aria-hidden="true"
    >
      {initials(label)}
    </div>
  );
}

// ── Single node ────────────────────────────────────────────────────────

interface CommentNodeProps {
  node: ThreadNode;
  depth: number;
  projectId: string;
  fileKind: FileKind;
  fileId: string;
  currentUserId: string | null;
  canResolve: boolean;
  onReplyClick: (parentId: string) => void;
  onResolveToggle: (commentId: string, resolved: boolean) => void;
  onDelete: (commentId: string) => void;
}

function CommentNode({
  node,
  depth,
  projectId,
  fileKind,
  fileId,
  currentUserId,
  canResolve,
  onReplyClick,
  onResolveToggle,
  onDelete,
}: CommentNodeProps) {
  const { t } = useTranslation();
  const isTombstone = node.body === '[deleted]';
  const isAuthor = currentUserId !== null && node.author_id === currentUserId;
  const indent = Math.min(depth, 4) * 16;
  const showResolveToggle = canResolve && depth === 0 && !isTombstone;
  const displayName = authorLabel(node.author_name, node.author_id);

  const body = useMemo(() => {
    if (isTombstone) {
      return (
        <span className="italic text-content-tertiary">
          {t('comments.deleted', { defaultValue: 'Comment deleted' })}
        </span>
      );
    }
    return tokenizeBody(node.body);
  }, [isTombstone, node.body, t]);

  return (
    <div
      style={{ marginLeft: indent }}
      className={clsx(
        'group flex gap-3 py-2',
        node.resolved && !isTombstone && 'opacity-60',
      )}
      data-testid={`comment-node-${node.id}`}
    >
      <Avatar label={displayName} />
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2 text-xs text-content-tertiary">
          <span
            className="max-w-[180px] truncate font-medium text-content-secondary"
            title={displayName}
          >
            {displayName}
          </span>
          <span>·</span>
          <span>{relativeTime(node.created_at)}</span>
          {node.resolved && (
            <span className="rounded bg-semantic-success/10 px-1.5 py-0.5 text-[10px] font-medium text-semantic-success">
              {t('comments.resolved_chip', { defaultValue: 'Resolved' })}
            </span>
          )}
          {node.page_number !== null && (
            <span className="rounded bg-surface-secondary px-1.5 py-0.5 text-[10px]">
              {t('comments.page_chip', {
                defaultValue: 'p.{{n}}',
                n: node.page_number,
              })}
            </span>
          )}
          {/* Epic C — warn when this comment was authored against a
              revision that has since been superseded. Renders nothing
              for the usual case (pin === chain head) and for legacy
              pre-Epic-C rows, which carry a NULL pin. */}
          <StaleVersionPill
            fileId={fileId}
            kind={fileKind}
            pinnedVersionId={node.file_version_id}
          />
        </div>
        <div className="mt-1 break-words text-sm text-content-primary">
          {body}
        </div>
        <div className="mt-1.5 flex gap-2 opacity-0 transition-opacity group-hover:opacity-100">
          {!isTombstone && (
            <button
              type="button"
              onClick={() => onReplyClick(node.id)}
              className="text-xs font-medium text-content-secondary hover:text-content-primary"
              data-testid={`comment-reply-${node.id}`}
            >
              {t('comments.reply', { defaultValue: 'Reply' })}
            </button>
          )}
          {showResolveToggle && (
            <button
              type="button"
              onClick={() => onResolveToggle(node.id, !node.resolved)}
              className="text-xs font-medium text-content-secondary hover:text-content-primary"
              data-testid={`comment-resolve-${node.id}`}
            >
              {node.resolved
                ? t('comments.reopen', { defaultValue: 'Reopen' })
                : t('comments.resolve', { defaultValue: 'Resolve' })}
            </button>
          )}
          {isAuthor && !isTombstone && (
            <button
              type="button"
              onClick={() => onDelete(node.id)}
              className="text-xs font-medium text-semantic-error hover:opacity-80"
              data-testid={`comment-delete-${node.id}`}
            >
              {t('comments.delete', { defaultValue: 'Delete' })}
            </button>
          )}
        </div>

        {node.replies.length > 0 && (
          <div className="mt-1">
            {node.replies.map((r) => (
              <CommentNode
                key={r.id}
                node={r}
                depth={depth + 1}
                projectId={projectId}
                fileKind={fileKind}
                fileId={fileId}
                currentUserId={currentUserId}
                canResolve={canResolve}
                onReplyClick={onReplyClick}
                onResolveToggle={onResolveToggle}
                onDelete={onDelete}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

// ── Public component ───────────────────────────────────────────────────

export interface CommentThreadProps {
  projectId: string;
  fileKind: FileKind;
  fileId: string;
  currentUserId: string | null;
  /** Whether the current user holds ``file_comments.resolve``. */
  canResolve?: boolean;
  /** Renders compactly inside the file preview pane (no border / smaller font). */
  dense?: boolean;
  className?: string;
}

export function CommentThread({
  projectId,
  fileKind,
  fileId,
  currentUserId,
  canResolve = false,
  dense = false,
  className,
}: CommentThreadProps) {
  const { t } = useTranslation();
  const [includeResolved, setIncludeResolved] = useState(false);
  const [replyToId, setReplyToId] = useState<string | null>(null);

  const args = { projectId, kind: fileKind, fileId, includeResolved };
  const { data, isLoading, isError } = useFileCommentThreads(args);
  const updateMut = useUpdateFileComment(args);
  const deleteMut = useDeleteFileComment(args);

  const handleResolveToggle = useCallback(
    (commentId: string, resolved: boolean) => {
      updateMut.mutate({ commentId, payload: { resolved } });
    },
    [updateMut],
  );
  const handleDelete = useCallback(
    (commentId: string) => {
      deleteMut.mutate(commentId);
    },
    [deleteMut],
  );
  const handleReplyClick = useCallback((parentId: string) => {
    setReplyToId(parentId);
  }, []);
  const handleReplyCancel = useCallback(() => setReplyToId(null), []);

  if (isLoading) {
    return (
      <div className={clsx('p-3', className)}>
        <SkeletonText lines={4} />
      </div>
    );
  }
  if (isError) {
    return (
      <div className={clsx('p-3 text-sm text-semantic-error', className)}>
        {t('comments.load_error', {
          defaultValue: 'Could not load comments.',
        })}
      </div>
    );
  }
  const threads = data?.threads ?? [];
  const total = data?.total ?? 0;

  return (
    <div
      className={clsx(
        'flex flex-col gap-2',
        !dense && 'rounded-lg border border-border bg-surface-primary p-3',
        className,
      )}
      data-testid="comment-thread"
    >
      <div className="flex items-center justify-between">
        <span className="text-xs font-medium uppercase tracking-wide text-content-tertiary">
          {t('comments.heading', {
            defaultValue: 'Comments ({{count}})',
            count: total,
          })}
        </span>
        <label className="flex items-center gap-1.5 text-xs text-content-secondary">
          <input
            type="checkbox"
            checked={includeResolved}
            onChange={(e) => setIncludeResolved(e.target.checked)}
            className="h-3 w-3"
            data-testid="comment-include-resolved"
          />
          {t('comments.show_resolved', { defaultValue: 'Show resolved' })}
        </label>
      </div>

      {threads.length === 0 ? (
        <EmptyState
          title={t('comments.empty_title', {
            defaultValue: 'No comments yet',
          })}
          description={t('comments.empty_desc', {
            defaultValue: 'Start the discussion below.',
          })}
        />
      ) : (
        <div className="divide-y divide-border">
          {threads.map((thread) => (
            <CommentNode
              key={thread.id}
              node={thread}
              depth={0}
              projectId={projectId}
              fileKind={fileKind}
              fileId={fileId}
              currentUserId={currentUserId}
              canResolve={canResolve}
              onReplyClick={handleReplyClick}
              onResolveToggle={handleResolveToggle}
              onDelete={handleDelete}
            />
          ))}
        </div>
      )}

      <div className="pt-2">
        <CommentComposer
          projectId={projectId}
          fileKind={fileKind}
          fileId={fileId}
          parentId={replyToId}
          onSubmitted={handleReplyCancel}
          onCancel={replyToId ? handleReplyCancel : undefined}
        />
        {replyToId && (
          <div className="mt-1 flex items-center justify-between text-xs text-content-tertiary">
            <span>
              {t('comments.replying_to', { defaultValue: 'Replying to thread' })}
            </span>
            <Button
              variant="ghost"
              size="sm"
              onClick={handleReplyCancel}
              data-testid="comment-reply-cancel"
            >
              {t('common.cancel', { defaultValue: 'Cancel' })}
            </Button>
          </div>
        )}
      </div>
    </div>
  );
}
