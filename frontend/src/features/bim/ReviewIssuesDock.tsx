// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * ReviewIssuesDock - the issue side of the Model Review page.
 *
 * This is deliberately NOT the project issue register (`BcfIssuesPanel`, the
 * /bcf page). The register is a wide, project-wide surface that has to work
 * with no model and no viewer: import an archive, triage, print, export
 * everything. Squeezed into a 380px dock next to a 3D view, most of its
 * toolbar is noise and the things a review actually needs are missing.
 *
 * What a coordinator does in a review, and what this dock therefore does:
 *
 *   1. see what is open, late, unassigned, and what belongs to the model on
 *      screen - as filter chips carrying their own counts,
 *   2. walk the list issue by issue, with the camera following each one,
 *   3. settle an issue in place: status, assignee, due date, a note,
 *   4. raise a new issue from what is on screen,
 *   5. hand the walked set over as a `.bcfzip`.
 *
 * The dock has two modes in the same column: the list, and one issue's detail
 * with previous / next. Detail replaces the list rather than opening a drawer,
 * because a drawer would cover the model the reviewer is talking about.
 *
 * Data comes from the page (one topics query feeds the header counts, this
 * dock and the guided walk, so the three can never disagree); edits are the
 * dock's own mutations and report back through `onDecision` so the session
 * minutes can name what was agreed.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation } from '@tanstack/react-query';
import {
  AlertTriangle,
  ArrowLeft,
  Boxes,
  Calendar,
  ChevronLeft,
  ChevronRight,
  Crosshair,
  Download,
  ExternalLink,
  ImageOff,
  MessageSquare,
  Plus,
  Printer,
  Search,
  Send,
  Tag,
  User,
  X,
} from 'lucide-react';
import clsx from 'clsx';

import { Badge, Button, EmptyState, SkeletonText } from '@/shared/ui';
import { DateDisplay } from '@/shared/ui/DateDisplay';
import { useToastStore } from '@/stores/useToastStore';

import {
  addComment,
  fetchViewpointSnapshotBlob,
  updateTopic,
  type Topic,
  type TopicUpdate,
  type Viewpoint,
} from '@/features/bcf/api';
import type { BcfMember } from '@/features/bcf';
import {
  COMMON_STATUSES,
  PRIORITY_CHOICES,
  isDone,
  isOverdue,
  primaryViewpoint,
  priorityVariant,
  statusVariant,
} from '@/features/bcf/issueStatus';
import { snapshotPlaceholder } from '@/features/bcf/snapshotState';

import type { ReviewDecision } from './reviewMinutes';
import {
  EMPTY_REVIEW_FILTER,
  UNASSIGNED,
  collectReviewLabels,
  isFilterActive,
  type ReviewCounts,
  type ReviewFilter,
  type ReviewSort,
} from './reviewFilters';

/* ── Small helpers ─────────────────────────────────────────────────────── */

/** ISO datetime -> the `YYYY-MM-DD` an `<input type="date">` expects. */
function toDateInput(value: string | null): string {
  if (!value) return '';
  const m = /^(\d{4}-\d{2}-\d{2})/.exec(value);
  return m?.[1] ?? '';
}

const controlCls =
  'h-8 rounded-lg border border-border bg-surface-primary px-2 text-xs text-content-primary ' +
  'focus:border-oe-blue focus:outline-none focus:ring-1 focus:ring-oe-blue/30 disabled:opacity-50';

/* ── Saved-view thumbnail ──────────────────────────────────────────────── */

/**
 * The PNG a viewpoint was saved with, fetched with the bearer token the plain
 * `<img src>` could never carry.
 *
 * A viewpoint legitimately has a camera and no image (an issue raised outside a
 * viewer, or an archive that shipped markup only), so the empty state names
 * itself instead of showing a broken-image glyph - here the camera is still
 * restorable, which is what the button next to it is for.
 *
 * Which empty state that is comes from `snapshotPlaceholder`, the same call the
 * project issue register makes. The two screens draw this thumbnail from the
 * same data but were written apart, and when the register learned to tell the
 * three states apart this one did not, so it went on drawing a viewpoint that
 * never carried a PNG as a broken picture and telling a reader whose snapshot
 * had failed to load that none was ever taken. Reading the decision from one
 * module is what stops them drifting again; the glyphs are only the symptom.
 *
 * Exported for the test that pins those states apart.
 */
export function SavedViewThumb({
  projectId,
  topicGuid,
  viewpoint,
  alt,
  className,
}: {
  projectId: string;
  topicGuid: string;
  viewpoint: Viewpoint;
  alt: string;
  className?: string;
}) {
  const { t } = useTranslation();
  const [url, setUrl] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  const hasSnapshot = Boolean(viewpoint.has_snapshot);
  const vpGuid = viewpoint.guid;

  useEffect(() => {
    setFailed(false);
    if (!hasSnapshot) {
      setUrl(null);
      return;
    }
    let objUrl: string | null = null;
    let cancelled = false;
    const ctrl = new AbortController();
    fetchViewpointSnapshotBlob(projectId, topicGuid, vpGuid, ctrl.signal)
      .then((blob) => {
        if (cancelled) return;
        objUrl = URL.createObjectURL(blob);
        setUrl(objUrl);
      })
      .catch(() => {
        if (!cancelled) setFailed(true);
      });
    return () => {
      cancelled = true;
      ctrl.abort();
      if (objUrl) URL.revokeObjectURL(objUrl);
    };
  }, [projectId, topicGuid, vpGuid, hasSnapshot]);

  const placeholder = snapshotPlaceholder(viewpoint, failed);
  if (placeholder !== null) {
    // Only a snapshot that exists and would not load earns the failure glyph. A
    // viewpoint carrying no PNG gets the crosshair, which says what is there - a
    // camera to fly to - rather than what is not.
    const label =
      placeholder === 'failed'
        ? t('bcf.snapshot_failed', { defaultValue: 'Snapshot could not be loaded.' })
        : placeholder === 'no_snapshot'
          ? t('bcf.no_snapshot', { defaultValue: 'No snapshot captured from this view.' })
          : t('bcf.viewpoint_none', { defaultValue: 'No viewpoint on this issue.' });
    return (
      <div
        role="img"
        aria-label={label}
        title={label}
        data-snapshot-state={placeholder}
        className={clsx(
          'flex flex-col items-center justify-center gap-1 bg-surface-secondary px-2 text-center',
          'text-2xs leading-tight text-content-quaternary',
          className,
        )}
      >
        {placeholder === 'failed' ? (
          <ImageOff size={16} className="shrink-0" />
        ) : placeholder === 'no_snapshot' ? (
          <Crosshair size={16} className="shrink-0" />
        ) : null}
        <span>{label}</span>
      </div>
    );
  }
  if (!url) return <div className={clsx('animate-pulse bg-surface-secondary', className)} />;
  return <img src={url} alt={alt} className={clsx('object-cover', className)} />;
}

/* ── Filter chip ───────────────────────────────────────────────────────── */

function FilterChip({
  active,
  label,
  count,
  tone = 'default',
  onClick,
}: {
  active: boolean;
  label: string;
  count?: number;
  tone?: 'default' | 'warning' | 'error';
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={clsx(
        'inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-2xs font-medium transition-colors',
        active
          ? 'border-oe-blue/50 bg-oe-blue-subtle/50 text-oe-blue'
          : 'border-border-light text-content-secondary hover:bg-surface-secondary',
      )}
    >
      {label}
      {count !== undefined && (
        <span
          className={clsx(
            'tabular-nums',
            !active && tone === 'error' && 'font-semibold text-semantic-error',
            !active && tone === 'warning' && 'font-semibold text-semantic-warning',
            (active || tone === 'default') && 'text-current',
          )}
        >
          {count}
        </span>
      )}
    </button>
  );
}

/* ── List row ──────────────────────────────────────────────────────────── */

function ReviewRow({
  topic,
  active,
  memberName,
  onOpen,
  onZoom,
}: {
  topic: Topic;
  active: boolean;
  memberName: (id: string | null) => string;
  onOpen: () => void;
  onZoom?: () => void;
}) {
  const { t } = useTranslation();
  const overdue = isOverdue(topic);
  const done = isDone(topic.topic_status);

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={onOpen}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          onOpen();
        }
      }}
      className={clsx(
        'cursor-pointer rounded-lg border px-2.5 py-2 transition-colors',
        'focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/40',
        active
          ? 'border-oe-blue/50 bg-oe-blue-subtle/30'
          : 'border-border-light bg-surface-primary hover:bg-surface-secondary',
        done && 'opacity-70',
      )}
    >
      <div className="flex items-start gap-2">
        <div className="min-w-0 flex-1">
          <p className="truncate text-xs font-semibold text-content-primary">{topic.title}</p>
          <div className="mt-1 flex flex-wrap items-center gap-x-2.5 gap-y-1 text-2xs text-content-tertiary">
            <Badge variant={statusVariant(topic.topic_status)} size="sm">
              {topic.topic_status}
            </Badge>
            {topic.priority && (
              <Badge variant={priorityVariant(topic.priority)} size="sm">
                {topic.priority}
              </Badge>
            )}
            <span className="inline-flex items-center gap-1">
              <User size={10} className="shrink-0" />
              <span className="max-w-[90px] truncate">
                {topic.assigned_to ? (
                  memberName(topic.assigned_to)
                ) : (
                  <span className="text-content-quaternary">
                    {t('bcf.unassigned', { defaultValue: 'Unassigned' })}
                  </span>
                )}
              </span>
            </span>
            {topic.due_date && (
              <span
                className={clsx(
                  'inline-flex items-center gap-1',
                  overdue && 'font-medium text-semantic-error',
                )}
              >
                {overdue ? <AlertTriangle size={10} /> : <Calendar size={10} />}
                <DateDisplay value={topic.due_date} format="date" />
              </span>
            )}
            {topic.comments.length > 0 && (
              <span className="inline-flex items-center gap-1">
                <MessageSquare size={10} className="shrink-0" />
                {topic.comments.length}
              </span>
            )}
          </div>
        </div>
        {onZoom && (
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              onZoom();
            }}
            className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-content-tertiary transition-colors hover:bg-oe-blue-subtle/40 hover:text-oe-blue"
            title={t('bcf.zoom_to_issue', { defaultValue: 'Zoom to issue' })}
            aria-label={t('bcf.zoom_to_issue', { defaultValue: 'Zoom to issue' })}
          >
            <Crosshair size={12} />
          </button>
        )}
      </div>
    </div>
  );
}

/* ── Detail ────────────────────────────────────────────────────────────── */

function ReviewIssueDetail({
  projectId,
  topic,
  position,
  total,
  members,
  memberName,
  canZoom,
  onBack,
  onPrev,
  onNext,
  onZoom,
  onEdit,
  onComment,
  busy,
}: {
  projectId: string;
  topic: Topic;
  position: number;
  total: number;
  members: BcfMember[];
  memberName: (id: string | null) => string;
  canZoom: boolean;
  onBack: () => void;
  onPrev?: () => void;
  onNext?: () => void;
  onZoom: () => void;
  onEdit: (patch: TopicUpdate) => void;
  onComment: (text: string) => void;
  busy: boolean;
}) {
  const { t } = useTranslation();
  const [note, setNote] = useState('');
  const [assigneeDraft, setAssigneeDraft] = useState(topic.assigned_to ?? '');

  useEffect(() => {
    setNote('');
    setAssigneeDraft(topic.assigned_to ?? '');
  }, [topic.guid, topic.assigned_to]);

  const vp = primaryViewpoint(topic);
  const overdue = isOverdue(topic);
  const statusOptions = Array.from(new Set([...COMMON_STATUSES, topic.topic_status])).filter(Boolean);
  const priorityOptions = Array.from(new Set([...PRIORITY_CHOICES, topic.priority ?? '']));
  const sortedComments = [...topic.comments].sort((a, b) => {
    const ta = a.date ? new Date(a.date).getTime() : 0;
    const tb = b.date ? new Date(b.date).getTime() : 0;
    return tb - ta;
  });

  return (
    <div className="flex h-full min-h-0 flex-col">
      {/* Navigation strip: back + position + prev/next */}
      <div className="flex items-center gap-1 border-b border-border-light px-2 py-1.5">
        <button
          type="button"
          onClick={onBack}
          className="inline-flex items-center gap-1 rounded-md px-1.5 py-1 text-2xs font-medium text-content-secondary hover:bg-surface-secondary"
        >
          <ArrowLeft size={13} />
          {t('bim.review_back_to_list', { defaultValue: 'All issues' })}
        </button>
        <span className="ms-auto text-2xs tabular-nums text-content-tertiary">
          {position > 0
            ? t('bim.review_position', {
                defaultValue: '{{current}} of {{total}}',
                current: position,
                total,
              })
            : t('bim.review_outside_filter', {
                defaultValue: 'Outside the current filter',
              })}
        </span>
        <button
          type="button"
          onClick={onPrev}
          disabled={!onPrev}
          className="flex h-6 w-6 items-center justify-center rounded-md text-content-secondary hover:bg-surface-secondary disabled:opacity-30"
          title={t('bcf.coordination_prev', { defaultValue: 'Previous issue' })}
          aria-label={t('bcf.coordination_prev', { defaultValue: 'Previous issue' })}
        >
          <ChevronLeft size={15} />
        </button>
        <button
          type="button"
          onClick={onNext}
          disabled={!onNext}
          className="flex h-6 w-6 items-center justify-center rounded-md text-content-secondary hover:bg-surface-secondary disabled:opacity-30"
          title={t('bcf.coordination_next', { defaultValue: 'Next issue' })}
          aria-label={t('bcf.coordination_next', { defaultValue: 'Next issue' })}
        >
          <ChevronRight size={15} />
        </button>
      </div>

      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto p-3">
        {/* Title + badges */}
        <div>
          <h4 className="text-sm font-semibold leading-snug text-content-primary">{topic.title}</h4>
          <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
            <Badge variant={statusVariant(topic.topic_status)} size="sm">
              {topic.topic_status}
            </Badge>
            {topic.priority && (
              <Badge variant={priorityVariant(topic.priority)} size="sm">
                {topic.priority}
              </Badge>
            )}
            {overdue && (
              <span className="inline-flex items-center gap-1 text-2xs font-medium text-semantic-error">
                <AlertTriangle size={11} />
                {t('bcf.overdue', { defaultValue: 'Overdue' })}
              </span>
            )}
          </div>
        </div>

        {/* Saved view: the frame the issue was raised in, plus the camera. */}
        {vp ? (
          <div className="overflow-hidden rounded-lg border border-border-light">
            <SavedViewThumb
              projectId={projectId}
              topicGuid={topic.guid}
              viewpoint={vp}
              alt={t('bcf.snapshot_alt', { defaultValue: 'Captured view snapshot' })}
              className="h-28 w-full"
            />
            <button
              type="button"
              onClick={onZoom}
              disabled={!canZoom}
              className="flex w-full items-center justify-center gap-1.5 border-t border-border-light bg-surface-primary py-1.5 text-2xs font-medium text-oe-blue transition-colors hover:bg-oe-blue-subtle/30 disabled:cursor-not-allowed disabled:text-content-quaternary"
              title={
                canZoom
                  ? t('bcf.zoom_to_issue', { defaultValue: 'Zoom to issue' })
                  : t('bim.review_zoom_needs_model', {
                      defaultValue: 'Load the model to fly to this saved view.',
                    })
              }
            >
              <Crosshair size={12} />
              {t('bcf.zoom_to_issue', { defaultValue: 'Zoom to issue' })}
            </button>
          </div>
        ) : (
          <p className="rounded-lg border border-border-light bg-surface-secondary/40 px-2.5 py-2 text-2xs text-content-tertiary">
            {t('bcf.no_view', { defaultValue: 'No saved view for this issue.' })}
          </p>
        )}

        {/* The four fields a review settles */}
        <div className="grid grid-cols-2 gap-2">
          <label className="col-span-1 block">
            <span className="mb-0.5 block text-2xs font-semibold uppercase tracking-wider text-content-quaternary">
              {t('bcf.field_status', { defaultValue: 'Status' })}
            </span>
            <select
              value={topic.topic_status}
              disabled={busy}
              onChange={(e) => onEdit({ topic_status: e.target.value })}
              className={clsx(controlCls, 'w-full')}
              data-testid="review-status-select"
            >
              {statusOptions.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </label>

          <label className="col-span-1 block">
            <span className="mb-0.5 block text-2xs font-semibold uppercase tracking-wider text-content-quaternary">
              {t('bcf.field_priority', { defaultValue: 'Priority' })}
            </span>
            <select
              value={topic.priority ?? ''}
              disabled={busy}
              onChange={(e) => onEdit({ priority: e.target.value || null })}
              className={clsx(controlCls, 'w-full')}
            >
              {priorityOptions.map((p) => (
                <option key={p || 'none'} value={p}>
                  {p || t('bcf.priority_none', { defaultValue: 'No priority' })}
                </option>
              ))}
            </select>
          </label>

          <label className="col-span-1 block">
            <span className="mb-0.5 block text-2xs font-semibold uppercase tracking-wider text-content-quaternary">
              {t('bcf.field_assigned_to', { defaultValue: 'Assigned to' })}
            </span>
            {members.length > 0 ? (
              <select
                value={topic.assigned_to ?? ''}
                disabled={busy}
                onChange={(e) => onEdit({ assigned_to: e.target.value || null })}
                className={clsx(controlCls, 'w-full')}
              >
                <option value="">{t('bcf.unassigned', { defaultValue: 'Unassigned' })}</option>
                {topic.assigned_to && !members.some((m) => m.id === topic.assigned_to) && (
                  <option value={topic.assigned_to}>{topic.assigned_to}</option>
                )}
                {members.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.name}
                  </option>
                ))}
              </select>
            ) : (
              <input
                value={assigneeDraft}
                disabled={busy}
                onChange={(e) => setAssigneeDraft(e.target.value)}
                onBlur={() => {
                  const next = assigneeDraft.trim();
                  if (next !== (topic.assigned_to ?? '')) onEdit({ assigned_to: next || null });
                }}
                placeholder={t('bcf.assignee_placeholder', { defaultValue: 'Name or email' })}
                className={clsx(controlCls, 'w-full')}
              />
            )}
          </label>

          <label className="col-span-1 block">
            <span className="mb-0.5 block text-2xs font-semibold uppercase tracking-wider text-content-quaternary">
              {t('bcf.field_due_date', { defaultValue: 'Due date' })}
            </span>
            <input
              type="date"
              value={toDateInput(topic.due_date)}
              disabled={busy}
              onChange={(e) => onEdit({ due_date: e.target.value || null })}
              className={clsx(
                controlCls,
                'w-full',
                overdue && 'border-semantic-error text-semantic-error',
              )}
            />
          </label>
        </div>

        {topic.description?.trim() && (
          <p className="whitespace-pre-wrap text-xs leading-relaxed text-content-secondary">
            {topic.description}
          </p>
        )}

        {topic.labels.length > 0 && (
          <div className="flex flex-wrap items-center gap-1">
            <Tag size={11} className="text-content-quaternary" />
            {topic.labels.map((label) => (
              <Badge key={label} variant="neutral" size="sm">
                {label}
              </Badge>
            ))}
          </div>
        )}

        {vp && vp.element_stable_ids.length > 0 && (
          <p className="flex items-center gap-1.5 text-2xs text-content-tertiary">
            <Boxes size={11} className="shrink-0" />
            {t('bcf.selection_count', {
              defaultValue: '{{count}} element(s) selected',
              count: vp.element_stable_ids.length,
            })}
          </p>
        )}

        {/* Discussion */}
        <div className="border-t border-border-light pt-2.5">
          <div className="mb-1.5 flex items-center gap-1.5">
            <MessageSquare size={12} className="text-content-tertiary" />
            <span className="text-2xs font-semibold uppercase tracking-wider text-content-tertiary">
              {t('bcf.comments', { defaultValue: 'Comments' })}
            </span>
            {topic.comments.length > 0 && (
              <span className="text-2xs tabular-nums text-content-quaternary">
                {topic.comments.length}
              </span>
            )}
          </div>
          <div className="mb-2 flex gap-1.5">
            <input
              value={note}
              onChange={(e) => setNote(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && note.trim()) {
                  e.preventDefault();
                  onComment(note.trim());
                  setNote('');
                }
              }}
              placeholder={t('bcf.coordination_note', { defaultValue: 'Add a note...' })}
              className={clsx(controlCls, 'flex-1')}
            />
            <button
              type="button"
              onClick={() => {
                if (note.trim()) {
                  onComment(note.trim());
                  setNote('');
                }
              }}
              disabled={!note.trim() || busy}
              className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-oe-blue text-white transition-colors hover:bg-oe-blue-hover disabled:cursor-not-allowed disabled:bg-surface-secondary disabled:text-content-quaternary"
              title={t('bcf.post_comment', { defaultValue: 'Post comment' })}
              aria-label={t('bcf.post_comment', { defaultValue: 'Post comment' })}
            >
              <Send size={13} />
            </button>
          </div>
          {sortedComments.length === 0 ? (
            <p className="py-2 text-center text-2xs text-content-tertiary">
              {t('bcf.no_comments', { defaultValue: 'No comments yet. Start the discussion.' })}
            </p>
          ) : (
            <ul className="divide-y divide-border-light">
              {sortedComments.map((c) => (
                <li key={c.guid} className="py-2">
                  <div className="mb-0.5 flex items-center gap-1.5">
                    <span className="text-2xs font-semibold text-content-primary">
                      {memberName(c.author)}
                    </span>
                    {c.date && (
                      <DateDisplay
                        value={c.date}
                        format="relative"
                        className="text-2xs text-content-quaternary"
                      />
                    )}
                  </div>
                  <p className="whitespace-pre-wrap break-words text-2xs leading-relaxed text-content-secondary">
                    {c.comment}
                  </p>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}

/* ── Dock ──────────────────────────────────────────────────────────────── */

export interface ReviewIssuesDockProps {
  projectId: string;
  /** Active model, used by the "This model" scope chip. */
  modelId: string | null;
  /** Every topic of the project (the page owns the query). */
  topics: Topic[];
  /** The filtered + sorted slice the reviewer is looking at. */
  visible: Topic[];
  counts: ReviewCounts;
  filter: ReviewFilter;
  onFilterChange: (next: ReviewFilter) => void;
  sort: ReviewSort;
  onSortChange: (next: ReviewSort) => void;
  isLoading: boolean;
  isError: boolean;
  members: BcfMember[];
  memberName: (id: string | null) => string;
  /** Guid of the issue open in detail mode, or null for the list. */
  selectedGuid: string | null;
  onSelect: (guid: string | null) => void;
  /** Fly the viewer to an issue's saved viewpoint. */
  onZoom: (topic: Topic) => void;
  /** True once the 3D scene can actually be flown. */
  viewerReady: boolean;
  /** Open the "Raise issue here" dialog (only when a viewer is live). */
  onRaiseIssue?: () => void;
  /** Refetch the topic list after an edit. */
  onRefresh: () => void;
  /** Report a status change or note so the session minutes can name it. */
  onDecision: (decision: ReviewDecision) => void;
  /** Hand the visible set over as a `.bcfzip`. */
  onExport: () => void;
  /** Print the visible set as a report. */
  onPrint: () => void;
  /** Leave for the project-wide issue register (import, project export, triage). */
  onOpenRegister: () => void;
  exporting?: boolean;
}

export function ReviewIssuesDock({
  projectId,
  modelId,
  topics,
  visible,
  counts,
  filter,
  onFilterChange,
  sort,
  onSortChange,
  isLoading,
  isError,
  members,
  memberName,
  selectedGuid,
  onSelect,
  onZoom,
  viewerReady,
  onRaiseIssue,
  onRefresh,
  onDecision,
  onExport,
  onPrint,
  onOpenRegister,
  exporting,
}: ReviewIssuesDockProps) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const [showFilters, setShowFilters] = useState(false);

  // Resolve the open issue against the WHOLE list, not the filtered slice:
  // closing an issue while "Open" is on would otherwise drop it out from under
  // the reviewer mid-sentence. Its position in the walk comes from the slice,
  // and is simply absent once it no longer belongs there.
  const selected = useMemo(
    () => topics.find((topic) => topic.guid === selectedGuid) ?? null,
    [topics, selectedGuid],
  );
  const selectedIndex = selected ? visible.findIndex((tp) => tp.guid === selected.guid) : -1;

  // Keep the last opened issue in view when the reviewer comes back to the list.
  const rowRefs = useRef<Map<string, HTMLDivElement | null>>(new Map());
  const lastOpenedRef = useRef<string | null>(null);
  useEffect(() => {
    if (selectedGuid) {
      lastOpenedRef.current = selectedGuid;
      return;
    }
    if (lastOpenedRef.current) {
      rowRefs.current.get(lastOpenedRef.current)?.scrollIntoView({ block: 'nearest' });
    }
  }, [selectedGuid]);

  const patch = (next: Partial<ReviewFilter>) => onFilterChange({ ...filter, ...next });

  const updateMut = useMutation({
    mutationFn: (vars: { topic: Topic; patch: TopicUpdate }) =>
      updateTopic(projectId, vars.topic.guid, vars.patch),
    onSuccess: (_data, vars) => {
      onRefresh();
      if (vars.patch.topic_status && vars.patch.topic_status !== vars.topic.topic_status) {
        onDecision({
          guid: vars.topic.guid,
          title: vars.topic.title,
          statusFrom: vars.topic.topic_status,
          statusTo: vars.patch.topic_status,
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

  const commentMut = useMutation({
    mutationFn: (vars: { topic: Topic; text: string }) =>
      addComment(projectId, vars.topic.guid, { comment: vars.text }),
    onSuccess: (_data, vars) => {
      onRefresh();
      onDecision({ guid: vars.topic.guid, title: vars.topic.title, note: vars.text });
    },
    onError: (err: Error) =>
      addToast({
        type: 'error',
        title: t('bcf.comment_failed', { defaultValue: 'Failed to post comment' }),
        message: err.message,
      }),
  });

  const step = useCallback(
    (delta: number) => {
      if (selectedIndex < 0) return;
      const next = visible[selectedIndex + delta];
      if (next) onSelect(next.guid);
    },
    [selectedIndex, visible, onSelect],
  );

  const busy = updateMut.isPending || commentMut.isPending;
  const filtering = isFilterActive(filter);
  const statusOptions = useMemo(
    () => Array.from(new Set(topics.map((topic) => topic.topic_status))).filter(Boolean).sort(),
    [topics],
  );
  const priorityOptions = useMemo(
    () =>
      Array.from(new Set(topics.map((topic) => topic.priority ?? '')))
        .filter(Boolean)
        .sort(),
    [topics],
  );
  const labelOptions = useMemo(() => collectReviewLabels(topics), [topics]);

  return (
    <div className="flex h-full min-h-0 flex-col">
      {/* Header */}
      <div className="flex items-center gap-1.5 border-b border-border-light px-3 py-2">
        <Boxes size={15} className="shrink-0 text-oe-blue" />
        <h3 className="text-sm font-semibold text-content-primary">
          {t('bim.issues', { defaultValue: 'Issues' })}
        </h3>
        <span className="rounded-full bg-surface-secondary px-1.5 text-2xs font-medium tabular-nums text-content-secondary">
          {visible.length}
          {visible.length !== counts.total && (
            <span className="text-content-quaternary">/{counts.total}</span>
          )}
        </span>
        <div className="flex-1" />
        <button
          type="button"
          onClick={onExport}
          disabled={visible.length === 0 || exporting}
          className="flex h-7 w-7 items-center justify-center rounded-lg border border-border-light text-content-secondary transition-colors hover:bg-surface-secondary disabled:opacity-40"
          title={t('bim.review_export_visible', {
            defaultValue: 'Export these issues as .bcfzip',
          })}
          aria-label={t('bim.review_export_visible', {
            defaultValue: 'Export these issues as .bcfzip',
          })}
        >
          <Download size={13} />
        </button>
        <button
          type="button"
          onClick={onPrint}
          disabled={visible.length === 0}
          className="flex h-7 w-7 items-center justify-center rounded-lg border border-border-light text-content-secondary transition-colors hover:bg-surface-secondary disabled:opacity-40"
          title={t('bcf.print_report', { defaultValue: 'Print report' })}
          aria-label={t('bcf.print_report', { defaultValue: 'Print report' })}
        >
          <Printer size={13} />
        </button>
        <button
          type="button"
          onClick={onOpenRegister}
          className="flex h-7 w-7 items-center justify-center rounded-lg border border-border-light text-content-secondary transition-colors hover:bg-surface-secondary"
          title={t('bim.review_open_register', { defaultValue: 'Open the full issue register' })}
          aria-label={t('bim.review_open_register', { defaultValue: 'Open the full issue register' })}
        >
          <ExternalLink size={13} />
        </button>
      </div>

      {selected ? (
        <ReviewIssueDetail
          projectId={projectId}
          topic={selected}
          position={selectedIndex + 1}
          total={visible.length}
          members={members}
          memberName={memberName}
          canZoom={viewerReady && Boolean(primaryViewpoint(selected))}
          onBack={() => onSelect(null)}
          onPrev={selectedIndex > 0 ? () => step(-1) : undefined}
          onNext={
            selectedIndex >= 0 && selectedIndex < visible.length - 1 ? () => step(1) : undefined
          }
          onZoom={() => onZoom(selected)}
          onEdit={(p) => updateMut.mutate({ topic: selected, patch: p })}
          onComment={(text) => commentMut.mutate({ topic: selected, text })}
          busy={busy}
        />
      ) : (
        <>
          {/* Search + scope chips */}
          <div className="space-y-2 border-b border-border-light px-3 py-2">
            <div className="relative">
              <Search
                size={13}
                className="pointer-events-none absolute start-2.5 top-1/2 -translate-y-1/2 text-content-tertiary"
              />
              <input
                value={filter.search}
                onChange={(e) => patch({ search: e.target.value })}
                placeholder={t('bcf.search', { defaultValue: 'Search title, labels, assignee...' })}
                aria-label={t('bcf.search', { defaultValue: 'Search title, labels, assignee...' })}
                className={clsx(controlCls, 'w-full ps-7')}
              />
              {filter.search && (
                <button
                  type="button"
                  onClick={() => patch({ search: '' })}
                  className="absolute end-1.5 top-1/2 flex h-5 w-5 -translate-y-1/2 items-center justify-center rounded text-content-tertiary hover:bg-surface-secondary"
                  aria-label={t('common.clear', { defaultValue: 'Clear' })}
                >
                  <X size={12} />
                </button>
              )}
            </div>

            <div className="flex flex-wrap items-center gap-1">
              <FilterChip
                active={filter.onlyOpen}
                label={t('bcf.dashboard_open', { defaultValue: 'Open' })}
                count={counts.open}
                onClick={() => patch({ onlyOpen: !filter.onlyOpen })}
              />
              <FilterChip
                active={filter.onlyOverdue}
                label={t('bcf.dashboard_overdue', { defaultValue: 'Overdue' })}
                count={counts.overdue}
                tone="error"
                onClick={() => patch({ onlyOverdue: !filter.onlyOverdue })}
              />
              <FilterChip
                active={filter.assignee === UNASSIGNED}
                label={t('bcf.dashboard_unassigned', { defaultValue: 'Unassigned' })}
                count={counts.unassignedOpen}
                tone="warning"
                onClick={() =>
                  patch({ assignee: filter.assignee === UNASSIGNED ? '' : UNASSIGNED })
                }
              />
              {/* Scoping to the model is opt-in and shows what it costs: an
                  issue raised outside a model belongs to no model at all. */}
              {modelId && (
                <FilterChip
                  active={filter.scope === 'model'}
                  label={t('bim.review_scope_model', { defaultValue: 'This model' })}
                  count={counts.openOnModel}
                  onClick={() => patch({ scope: filter.scope === 'model' ? 'all' : 'model' })}
                />
              )}
              <button
                type="button"
                onClick={() => setShowFilters((v) => !v)}
                aria-pressed={showFilters}
                className="ms-auto rounded-md px-1.5 py-0.5 text-2xs font-medium text-content-secondary hover:bg-surface-secondary"
              >
                {showFilters
                  ? t('bim.review_fewer_filters', { defaultValue: 'Less' })
                  : t('bim.review_more_filters', { defaultValue: 'More' })}
              </button>
            </div>

            {showFilters && (
              <div className="grid grid-cols-2 gap-1.5">
                <select
                  value={filter.status}
                  onChange={(e) => patch({ status: e.target.value })}
                  className={clsx(controlCls, 'w-full')}
                  aria-label={t('bcf.filter_status', { defaultValue: 'Filter by status' })}
                >
                  <option value="">{t('bcf.all_statuses', { defaultValue: 'All statuses' })}</option>
                  {statusOptions.map((s) => (
                    <option key={s} value={s}>
                      {s}
                    </option>
                  ))}
                </select>
                {/* Discipline is a label in this product - see collectReviewLabels.
                    Nothing labelled means no control rather than an empty one. */}
                {labelOptions.length > 0 && (
                  <select
                    value={filter.label}
                    onChange={(e) => patch({ label: e.target.value })}
                    className={clsx(controlCls, 'w-full')}
                    aria-label={t('bim.review_filter_discipline', {
                      defaultValue: 'Filter by discipline',
                    })}
                  >
                    <option value="">
                      {t('bim.review_all_disciplines', { defaultValue: 'All disciplines' })}
                    </option>
                    {labelOptions.map((l) => (
                      <option key={l} value={l}>
                        {l}
                      </option>
                    ))}
                  </select>
                )}
                <select
                  value={filter.priority}
                  onChange={(e) => patch({ priority: e.target.value })}
                  className={clsx(controlCls, 'w-full')}
                  aria-label={t('bim.review_filter_priority', {
                    defaultValue: 'Filter by priority',
                  })}
                >
                  <option value="">
                    {t('bim.review_all_priorities', { defaultValue: 'All priorities' })}
                  </option>
                  {priorityOptions.map((p) => (
                    <option key={p} value={p}>
                      {p}
                    </option>
                  ))}
                </select>
                <select
                  value={filter.assignee}
                  onChange={(e) => patch({ assignee: e.target.value })}
                  className={clsx(controlCls, 'w-full')}
                  aria-label={t('bim.review_filter_assignee', {
                    defaultValue: 'Filter by assignee',
                  })}
                >
                  <option value="">
                    {t('bim.review_all_assignees', { defaultValue: 'Anyone' })}
                  </option>
                  <option value={UNASSIGNED}>
                    {t('bcf.unassigned', { defaultValue: 'Unassigned' })}
                  </option>
                  {members.map((m) => (
                    <option key={m.id} value={m.id}>
                      {m.name}
                    </option>
                  ))}
                </select>
                <select
                  value={sort}
                  onChange={(e) => onSortChange(e.target.value as ReviewSort)}
                  className={clsx(controlCls, 'w-full')}
                  aria-label={t('bim.review_sort', { defaultValue: 'Sort issues' })}
                >
                  <option value="newest">
                    {t('bim.review_sort_newest', { defaultValue: 'Newest first' })}
                  </option>
                  <option value="due">
                    {t('bim.review_sort_due', { defaultValue: 'Due date' })}
                  </option>
                  <option value="priority">
                    {t('bim.review_sort_priority', { defaultValue: 'Priority' })}
                  </option>
                </select>
              </div>
            )}
          </div>

          {/* List */}
          <div className="min-h-0 flex-1 overflow-y-auto p-2">
            {isLoading ? (
              <div className="space-y-2">
                {[0, 1, 2].map((i) => (
                  <div key={i} className="rounded-lg border border-border-light p-2">
                    <SkeletonText lines={2} />
                  </div>
                ))}
              </div>
            ) : isError ? (
              <p className="px-2 py-6 text-center text-xs text-semantic-error">
                {t('bcf.load_failed', { defaultValue: 'Could not load issues. Please try again.' })}
              </p>
            ) : counts.total === 0 ? (
              <EmptyState
                icon={<Boxes size={20} />}
                title={t('bcf.empty_title', { defaultValue: 'No issues yet' })}
                description={
                  onRaiseIssue
                    ? t('bcf.empty_desc_viewer', {
                        defaultValue:
                          'Select something in the model and raise an issue, or import a .bcfzip from another tool.',
                      })
                    : t('bcf.empty_desc', {
                        defaultValue: 'Import a .bcfzip from another tool to get started.',
                      })
                }
                action={
                  onRaiseIssue
                    ? {
                        label: t('bcf.raise_issue', { defaultValue: 'Raise issue here' }),
                        onClick: onRaiseIssue,
                      }
                    : undefined
                }
              />
            ) : visible.length === 0 ? (
              <div className="px-2 py-6 text-center">
                <p className="text-xs text-content-tertiary">
                  {t('bim.review_no_match', {
                    defaultValue: 'No issue matches these filters.',
                  })}
                </p>
                {filtering && (
                  <button
                    type="button"
                    // The neutral filter by name, not by hand: a literal here
                    // silently stops clearing whatever field is added next.
                    onClick={() => onFilterChange(EMPTY_REVIEW_FILTER)}
                    className="mt-2 rounded-md px-2 py-1 text-2xs font-medium text-oe-blue hover:bg-oe-blue-subtle/40"
                  >
                    {t('bim.review_clear_filters', { defaultValue: 'Clear filters' })}
                  </button>
                )}
              </div>
            ) : (
              <div className="space-y-1.5" data-testid="review-issue-list">
                {visible.map((topic) => (
                  <div
                    key={topic.guid}
                    ref={(el) => {
                      rowRefs.current.set(topic.guid, el);
                    }}
                  >
                    <ReviewRow
                      topic={topic}
                      active={topic.guid === selectedGuid}
                      memberName={memberName}
                      onOpen={() => onSelect(topic.guid)}
                      onZoom={
                        viewerReady && primaryViewpoint(topic) ? () => onZoom(topic) : undefined
                      }
                    />
                  </div>
                ))}
              </div>
            )}
          </div>
        </>
      )}

      {/* Raise issue - the one action that only exists because a model is on
          screen, so it sits at the bottom where it is always reachable. */}
      {onRaiseIssue && (
        <div className="border-t border-border-light p-2">
          <Button
            variant="primary"
            size="sm"
            className="w-full"
            onClick={onRaiseIssue}
            icon={<Plus size={14} />}
            data-testid="review-raise-issue"
          >
            {t('bcf.raise_issue', { defaultValue: 'Raise issue here' })}
          </Button>
        </div>
      )}
    </div>
  );
}

export default ReviewIssuesDock;
