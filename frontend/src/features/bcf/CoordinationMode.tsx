// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * CoordinationMode - a guided walk-through of the open issues for a
 * coordination meeting. It steps through the open backlog one issue at a time,
 * flies the 3D scene to each issue's saved viewpoint, and lets the chair change
 * the status and drop a quick note without leaving the model. Arrow keys page
 * through the agenda; it floats over the viewer so the model stays in view.
 *
 * The agenda order is snapshotted when the meeting opens so it stays stable as
 * statuses change during the review; each item still shows its live status.
 */

import { useCallback, useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { ChevronLeft, ChevronRight, ClipboardCheck, Presentation, Send, X } from 'lucide-react';

import { Badge, Button } from '@/shared/ui';
import { useToastStore } from '@/stores/useToastStore';

import { addComment, updateTopic, type Topic, type Viewpoint } from './api';
import { COMMON_STATUSES, isDone, primaryViewpoint, statusVariant } from './issueStatus';

/** One thing settled about one issue while the meeting was running. */
export interface CoordinationDecision {
  guid: string;
  title: string;
  statusFrom?: string | null;
  statusTo?: string | null;
  note?: string | null;
}

export function CoordinationMode({
  projectId,
  topics,
  agenda: agendaOverride,
  onOpenViewpoint,
  onChanged,
  onDecision,
  onFinish,
  onClose,
}: {
  projectId: string;
  topics: Topic[];
  /** Run this exact list instead of "every open topic". The Model Review page
   *  passes the issues the reviewer has filtered to, so the walk covers what
   *  is on screen rather than a second, invisible selection. */
  agenda?: Topic[];
  onOpenViewpoint: (topic: Topic, vp: Viewpoint) => void;
  onChanged: () => void;
  /** Report a status change or a note so the host can write up the session. */
  onDecision?: (decision: CoordinationDecision) => void;
  /** When given, the bar offers a "Finish" action that ends the session. */
  onFinish?: () => void;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);

  // Snapshot the agenda once, so changing a status mid-meeting never
  // reshuffles the running order under the chair. Without an explicit agenda
  // the running order is every open topic, which is what the register's own
  // coordination button means.
  const [agendaGuids] = useState<string[]>(() =>
    (agendaOverride ?? topics.filter((topic) => !isDone(topic.topic_status))).map(
      (topic) => topic.guid,
    ),
  );
  const byGuid = useMemo(() => {
    const map = new Map<string, Topic>();
    for (const topic of topics) map.set(topic.guid, topic);
    return map;
  }, [topics]);
  const agenda = useMemo(
    () => agendaGuids.map((g) => byGuid.get(g)).filter((v): v is Topic => Boolean(v)),
    [agendaGuids, byGuid],
  );

  const [index, setIndex] = useState(0);
  const clampedIndex = Math.min(index, Math.max(0, agenda.length - 1));
  const current = agenda[clampedIndex] ?? null;

  const [note, setNote] = useState('');

  const go = useCallback(
    (delta: number) => {
      setIndex((i) => {
        const next = i + delta;
        if (next < 0) return 0;
        if (next > agenda.length - 1) return agenda.length - 1;
        return next;
      });
      setNote('');
    },
    [agenda.length],
  );

  // Fly to the current issue's viewpoint whenever the step changes.
  const currentGuid = current?.guid;
  useEffect(() => {
    if (!current) return;
    const vp = primaryViewpoint(current);
    if (vp) onOpenViewpoint(current, vp);
    // Only re-run when the focused issue changes, not on every parent re-render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentGuid]);

  // Arrow keys page the agenda; Escape closes. Ignore while typing in a field.
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement | null;
      const typing =
        el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.tagName === 'SELECT');
      if (e.key === 'Escape') {
        onClose();
        return;
      }
      if (typing) return;
      if (e.key === 'ArrowRight') {
        e.preventDefault();
        go(1);
      } else if (e.key === 'ArrowLeft') {
        e.preventDefault();
        go(-1);
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [go, onClose]);

  const refresh = useCallback(() => {
    qc.invalidateQueries({ queryKey: ['bcf', 'topics', projectId] });
    onChanged();
  }, [qc, projectId, onChanged]);

  const statusMut = useMutation({
    mutationFn: (vars: { guid: string; title: string; from: string; status: string }) =>
      updateTopic(projectId, vars.guid, { topic_status: vars.status }),
    onSuccess: (_data, vars) => {
      refresh();
      if (vars.status !== vars.from) {
        onDecision?.({
          guid: vars.guid,
          title: vars.title,
          statusFrom: vars.from,
          statusTo: vars.status,
        });
      }
    },
    onError: (err: Error) =>
      addToast({
        type: 'error',
        title: t('bcf.update_failed', { defaultValue: 'Failed to update issue' }),
        message: err.message,
      }),
  });

  const noteMut = useMutation({
    mutationFn: (vars: { guid: string; title: string; comment: string }) =>
      addComment(projectId, vars.guid, { comment: vars.comment }),
    onSuccess: (_data, vars) => {
      setNote('');
      refresh();
      onDecision?.({ guid: vars.guid, title: vars.title, note: vars.comment });
    },
    onError: (err: Error) =>
      addToast({
        type: 'error',
        title: t('bcf.comment_failed', { defaultValue: 'Failed to post comment' }),
        message: err.message,
      }),
  });

  const postNote = useCallback(() => {
    const trimmed = note.trim();
    if (trimmed && current) {
      noteMut.mutate({ guid: current.guid, title: current.title, comment: trimmed });
    }
  }, [note, current, noteMut]);

  const statusOptions = current
    ? Array.from(new Set([...COMMON_STATUSES, current.topic_status])).filter(Boolean)
    : COMMON_STATUSES;

  return (
    <div className="fixed bottom-4 left-1/2 z-40 w-[min(680px,92vw)] -translate-x-1/2">
      <div className="rounded-2xl border border-border-medium bg-surface-elevated p-3 shadow-2xl shadow-black/20">
        {/* Title row */}
        <div className="mb-2 flex items-center gap-2">
          <Presentation size={16} className="shrink-0 text-oe-blue" />
          <span className="text-xs font-semibold uppercase tracking-wider text-content-secondary">
            {t('bcf.coordination_mode', { defaultValue: 'Coordination mode' })}
          </span>
          {agenda.length > 0 && (
            <span className="text-xs text-content-tertiary tabular-nums">
              {t('bcf.coordination_progress', {
                defaultValue: '{{current}} of {{total}}',
                current: clampedIndex + 1,
                total: agenda.length,
              })}
            </span>
          )}
          <div className="ms-auto flex items-center gap-1.5">
            {onFinish && (
              <Button variant="secondary" size="sm" onClick={onFinish} icon={<ClipboardCheck size={14} />}>
                {t('bim.review_finish', { defaultValue: 'Finish review' })}
              </Button>
            )}
            <button
              type="button"
              onClick={onClose}
              className="flex h-7 w-7 items-center justify-center rounded-lg text-content-tertiary hover:bg-surface-secondary"
              aria-label={t('common.close', { defaultValue: 'Close' })}
            >
              <X size={16} />
            </button>
          </div>
        </div>

        {current ? (
          <div className="flex flex-col gap-2.5">
            {/* Current issue */}
            <div className="flex items-start gap-2">
              <div className="min-w-0 flex-1">
                <h4 className="truncate text-sm font-semibold text-content-primary">
                  {current.title}
                </h4>
                {current.description && (
                  <p className="mt-0.5 line-clamp-1 text-xs text-content-tertiary">
                    {current.description}
                  </p>
                )}
              </div>
              <Badge variant={statusVariant(current.topic_status)} size="sm">
                {current.topic_status}
              </Badge>
            </div>

            {/* Controls */}
            <div className="flex flex-wrap items-center gap-2">
              <div className="flex items-center gap-1">
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => go(-1)}
                  disabled={clampedIndex === 0}
                  icon={<ChevronLeft size={16} />}
                  aria-label={t('bcf.coordination_prev', { defaultValue: 'Previous issue' })}
                />
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => go(1)}
                  disabled={clampedIndex >= agenda.length - 1}
                  icon={<ChevronRight size={16} />}
                  aria-label={t('bcf.coordination_next', { defaultValue: 'Next issue' })}
                />
              </div>
              <select
                value={current.topic_status}
                disabled={statusMut.isPending}
                onChange={(e) =>
                  statusMut.mutate({
                    guid: current.guid,
                    title: current.title,
                    from: current.topic_status,
                    status: e.target.value,
                  })
                }
                className="h-8 rounded-lg border border-border bg-surface-primary px-2 text-xs focus:border-oe-blue focus:outline-none focus:ring-2 focus:ring-oe-blue/30"
                aria-label={t('bcf.field_status', { defaultValue: 'Status' })}
              >
                {statusOptions.map((s) => (
                  <option key={s} value={s}>
                    {s}
                  </option>
                ))}
              </select>
              <div className="flex min-w-[180px] flex-1 items-center gap-1.5">
                <input
                  value={note}
                  onChange={(e) => setNote(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') {
                      e.preventDefault();
                      postNote();
                    }
                  }}
                  placeholder={t('bcf.coordination_note', { defaultValue: 'Add a note...' })}
                  className="h-8 flex-1 rounded-lg border border-border bg-surface-primary px-2.5 text-xs text-content-primary placeholder:text-content-quaternary focus:border-oe-blue focus:outline-none focus:ring-1 focus:ring-oe-blue/30"
                />
                <button
                  type="button"
                  onClick={postNote}
                  disabled={!note.trim() || noteMut.isPending}
                  className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-oe-blue text-white transition-colors hover:bg-oe-blue-hover disabled:cursor-not-allowed disabled:bg-surface-secondary disabled:text-content-quaternary"
                  title={t('bcf.post_comment', { defaultValue: 'Post comment' })}
                  aria-label={t('bcf.post_comment', { defaultValue: 'Post comment' })}
                >
                  <Send size={13} />
                </button>
              </div>
            </div>
          </div>
        ) : (
          <p className="py-3 text-center text-sm text-content-tertiary">
            {t('bcf.coordination_empty', {
              defaultValue: 'No open issues to review. Every issue is closed.',
            })}
          </p>
        )}
      </div>
    </div>
  );
}
