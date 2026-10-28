// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/** Comment composer with naive @username suggestion popover.
 *
 * The suggestion list is supplied by the parent (lifted state) so the
 * composer doesn't need to know how to source the project member
 * directory. When ``suggestions`` is empty the popover never opens —
 * the textarea behaves like a plain field.
 */

import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type ChangeEvent,
  type KeyboardEvent,
} from 'react';
import { useTranslation } from 'react-i18next';
import clsx from 'clsx';
import { Button } from '@/shared/ui/Button';
import { useToastStore } from '@/stores/useToastStore';
import { useCreateFileComment } from './hooks';
import type { FileKind } from './types';

export interface MentionSuggestion {
  /** ``@handle`` minus the leading ``@``. */
  handle: string;
  display_name: string;
}

export interface CommentComposerProps {
  projectId: string;
  fileKind: FileKind;
  fileId: string;
  /** When set, the composer creates a reply; otherwise a top-level comment. */
  parentId?: string | null;
  /** Optional pin anchor — both coordinates required if either is set. */
  pageNumber?: number | null;
  anchorX?: number | null;
  anchorY?: number | null;
  /** Optional project member list for @mention typeahead. */
  suggestions?: MentionSuggestion[];
  /** Called on successful submission. */
  onSubmitted?: () => void;
  onCancel?: () => void;
  className?: string;
}

export function CommentComposer({
  projectId,
  fileKind,
  fileId,
  parentId = null,
  pageNumber = null,
  anchorX = null,
  anchorY = null,
  suggestions = [],
  onSubmitted,
  onCancel,
  className,
}: CommentComposerProps) {
  const { t } = useTranslation();
  const [body, setBody] = useState('');
  const [popoverOpen, setPopoverOpen] = useState(false);
  const [popoverQuery, setPopoverQuery] = useState('');
  const [highlight, setHighlight] = useState(0);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const addToast = useToastStore((s) => s.addToast);
  const createMut = useCreateFileComment({
    projectId,
    kind: fileKind,
    fileId,
  });

  // Detect ``@token`` directly before the caret to drive the popover.
  const updateMentionState = useCallback((value: string, caret: number) => {
    const upToCaret = value.slice(0, caret);
    const m = /(?:^|\s)@(\w{0,32})$/.exec(upToCaret);
    if (m) {
      setPopoverOpen(true);
      setPopoverQuery((m[1] ?? '').toLowerCase());
      setHighlight(0);
    } else {
      setPopoverOpen(false);
      setPopoverQuery('');
    }
  }, []);

  const handleChange = useCallback(
    (e: ChangeEvent<HTMLTextAreaElement>) => {
      const value = e.target.value;
      setBody(value);
      const caret = e.target.selectionStart ?? value.length;
      updateMentionState(value, caret);
    },
    [updateMentionState],
  );

  const filtered =
    popoverQuery.length === 0
      ? suggestions.slice(0, 6)
      : suggestions
          .filter(
            (s) =>
              s.handle.toLowerCase().startsWith(popoverQuery) ||
              s.display_name.toLowerCase().includes(popoverQuery),
          )
          .slice(0, 6);

  const insertSuggestion = useCallback(
    (suggestion: MentionSuggestion) => {
      const ta = textareaRef.current;
      if (!ta) return;
      const caret = ta.selectionStart ?? body.length;
      const before = body.slice(0, caret);
      const after = body.slice(caret);
      const replaced = before.replace(
        /(?:^|(?<=\s))@(\w{0,32})$/,
        `@${suggestion.handle} `,
      );
      const newBody = replaced + after;
      setBody(newBody);
      setPopoverOpen(false);
      setPopoverQuery('');
      // Restore focus + caret position to just after the inserted handle.
      requestAnimationFrame(() => {
        const newCaret = replaced.length;
        ta.focus();
        ta.setSelectionRange(newCaret, newCaret);
      });
    },
    [body],
  );

  const handleKeyDown = useCallback(
    (e: KeyboardEvent<HTMLTextAreaElement>) => {
      if (popoverOpen && filtered.length > 0) {
        if (e.key === 'ArrowDown') {
          e.preventDefault();
          setHighlight((h) => (h + 1) % filtered.length);
          return;
        }
        if (e.key === 'ArrowUp') {
          e.preventDefault();
          setHighlight((h) => (h - 1 + filtered.length) % filtered.length);
          return;
        }
        if (e.key === 'Enter' || e.key === 'Tab') {
          e.preventDefault();
          const pick = filtered[highlight];
          if (pick) insertSuggestion(pick);
          return;
        }
        if (e.key === 'Escape') {
          e.preventDefault();
          setPopoverOpen(false);
          return;
        }
      }
      if (e.key === 'Escape' && onCancel) {
        e.preventDefault();
        onCancel();
      }
    },
    [popoverOpen, filtered, highlight, insertSuggestion, onCancel],
  );

  const submit = useCallback(() => {
    const trimmed = body.trim();
    if (!trimmed || createMut.isPending) return;
    createMut.mutate(
      {
        project_id: projectId,
        file_kind: fileKind,
        file_id: fileId,
        parent_id: parentId,
        body: trimmed,
        page_number: pageNumber,
        anchor_x: anchorX,
        anchor_y: anchorY,
      },
      {
        onSuccess: () => {
          setBody('');
          setPopoverOpen(false);
          onSubmitted?.();
        },
        onError: (err) => {
          addToast({
            type: 'error',
            title: t('comments.submit_failed', {
              defaultValue: 'Could not post comment',
            }),
            message: err instanceof Error ? err.message : undefined,
          });
        },
      },
    );
  }, [
    body,
    createMut,
    projectId,
    fileKind,
    fileId,
    parentId,
    pageNumber,
    anchorX,
    anchorY,
    onSubmitted,
    addToast,
    t,
  ]);

  // Close the popover when the user clicks away — clicking inside the
  // popover (handled by insertSuggestion) takes precedence because the
  // pointer-down listener runs before the textarea blur.
  useEffect(() => {
    if (!popoverOpen) return;
    const onPointerDown = (e: PointerEvent): void => {
      const ta = textareaRef.current;
      if (!ta) return;
      if (ta.contains(e.target as Node)) return;
      const popover = document.getElementById('mention-popover');
      if (popover && popover.contains(e.target as Node)) return;
      setPopoverOpen(false);
    };
    document.addEventListener('pointerdown', onPointerDown);
    return () => document.removeEventListener('pointerdown', onPointerDown);
  }, [popoverOpen]);

  return (
    <div className={clsx('relative flex flex-col gap-2', className)}>
      <textarea
        ref={textareaRef}
        value={body}
        onChange={handleChange}
        onKeyDown={handleKeyDown}
        placeholder={
          parentId
            ? t('comments.placeholder_reply', {
                defaultValue: 'Write a reply…',
              })
            : t('comments.placeholder', {
                defaultValue: 'Add a comment…',
              })
        }
        rows={2}
        maxLength={10_000}
        className="w-full resize-y rounded-lg border border-border bg-surface-primary px-3 py-2 text-sm text-content-primary placeholder:text-content-tertiary focus:border-oe-blue focus:outline-none focus:ring-2 focus:ring-oe-blue/30"
        data-testid="comment-composer-textarea"
      />
      <div className="flex justify-end gap-2">
        {onCancel && (
          <Button variant="ghost" size="sm" onClick={onCancel} type="button">
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
        )}
        <Button
          variant="primary"
          size="sm"
          onClick={submit}
          type="button"
          loading={createMut.isPending}
          disabled={body.trim().length === 0 || createMut.isPending}
          data-testid="comment-composer-submit"
        >
          {parentId
            ? t('comments.post_reply', { defaultValue: 'Reply' })
            : t('comments.post', { defaultValue: 'Post' })}
        </Button>
      </div>
      {popoverOpen && filtered.length > 0 && (
        <div
          id="mention-popover"
          role="listbox"
          aria-label={t('comments.mentions', { defaultValue: 'Mentions' })}
          className="absolute left-0 top-full z-20 mt-1 w-64 rounded-lg border border-border bg-surface-primary shadow-lg"
        >
          {filtered.map((s, idx) => (
            <button
              key={s.handle}
              type="button"
              onClick={() => insertSuggestion(s)}
              onMouseEnter={() => setHighlight(idx)}
              className={clsx(
                'flex w-full items-center gap-2 px-3 py-1.5 text-left text-sm',
                idx === highlight
                  ? 'bg-oe-blue/10 text-oe-blue'
                  : 'text-content-primary hover:bg-surface-secondary',
              )}
              data-testid={`mention-suggestion-${s.handle}`}
            >
              <span className="font-mono text-xs">@{s.handle}</span>
              <span className="truncate text-xs text-content-tertiary">
                {s.display_name}
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
