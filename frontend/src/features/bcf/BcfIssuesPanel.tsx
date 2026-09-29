// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * BcfIssuesPanel - project issue register built on the BCF backend.
 *
 * Lists BCF topics for a project (status, priority, assignee, due date with
 * overdue styling, labels, and a snapshot thumbnail), opens each into a detail
 * drawer with the full snapshot, a comment thread, and inline editing of
 * status / priority / assignee / due date (persisted via PUT). Also imports and
 * exports `.bcfzip` archives.
 *
 * The optional `bridge` prop wires the "Raise issue here" flow to a live 3D/BIM
 * viewer; without it the panel is a pure register (no capture button).
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useHasPermission } from '@/shared/lib/permissionGates';
import {
  AlertTriangle,
  BarChart3,
  Boxes,
  Calendar,
  Crosshair,
  Download,
  ImageOff,
  MessageSquare,
  Plus,
  Presentation,
  Printer,
  Search,
  Send,
  Tag,
  Trash2,
  Upload,
  User,
} from 'lucide-react';
import clsx from 'clsx';

import {
  Badge,
  Button,
  Card,
  EmptyState,
  SideDrawer,
  SkeletonText,
} from '@/shared/ui';
import { DateDisplay } from '@/shared/ui/DateDisplay';
import { apiGet, triggerDownload } from '@/shared/lib/api';
import { toNum } from '@/shared/lib/money';
import { useToastStore } from '@/stores/useToastStore';

import {
  addComment,
  deleteTopic,
  exportBcf,
  fetchViewpointSnapshotBlob,
  getTopic,
  importBcf,
  listTopics,
  updateTopic,
  type BcfComment,
  type BcfVersion,
  type Topic,
  type TopicUpdate,
  type Viewpoint,
} from './api';
import { BcfIssueModal, type BcfMember } from './BcfIssueModal';
import type { BcfViewerBridge, RaiseIssueResult } from './useBcfCapture';
import {
  COMMON_STATUSES,
  PRIORITY_CHOICES,
  isOverdue,
  primaryViewpoint,
  priorityVariant,
  statusVariant,
} from './issueStatus';
import { computeIssueStats } from './issueStats';
import { snapshotPlaceholder } from './snapshotState';
import { buildIssueReportHtml, type IssueReportRow } from './issueReport';
import { ReviewDashboard } from './ReviewDashboard';
import { CoordinationMode } from './CoordinationMode';
import { fmtList, getIntlLocale } from '@/shared/lib/formatters';

/* ── Small helpers ─────────────────────────────────────────────────────── */

/** ISO datetime -> the `YYYY-MM-DD` a `<input type="date">` expects. */
function toDateInput(value: string | null): string {
  if (!value) return '';
  const m = /^(\d{4}-\d{2}-\d{2})/.exec(value);
  return m?.[1] ?? '';
}

/* ── Snapshot (auth-gated blob -> object URL) ──────────────────────────── */

/**
 * The viewpoint thumbnail, fetched with the bearer token a plain `<img src>`
 * could never carry.
 *
 * Exported for the test that pins the three empty states apart. Reading the
 * decision from `snapshotPlaceholder` is the point of the module, and until
 * something asserted that this screen still does, a rewrite could quietly give
 * it a private answer again - which is the exact regression the module exists
 * to prevent, and it would not have failed a single test.
 */
export function BcfSnapshot({
  projectId,
  topicGuid,
  viewpoint,
  className,
  alt,
  withCaption = false,
}: {
  projectId: string;
  topicGuid: string;
  viewpoint: Viewpoint | null;
  className?: string;
  alt: string;
  /** Spell the empty state out in words. Set where the box is tall enough to
   *  hold a line of text; the list thumbnail is not and relies on the title. */
  withCaption?: boolean;
}) {
  const { t } = useTranslation();
  const [url, setUrl] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  const hasSnapshot = Boolean(viewpoint?.has_snapshot);
  const vpGuid = viewpoint?.guid;

  useEffect(() => {
    setFailed(false);
    if (!hasSnapshot || !vpGuid) {
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
        // A thumbnail is best-effort, but the reader still has to be told
        // which kind of nothing they are looking at rather than being left
        // with a skeleton that never resolves.
        if (!cancelled) setFailed(true);
      });
    return () => {
      cancelled = true;
      ctrl.abort();
      if (objUrl) URL.revokeObjectURL(objUrl);
    };
  }, [projectId, topicGuid, vpGuid, hasSnapshot]);

  // Three different nothings, and they used to be drawn as one. Which of them
  // this is comes from `snapshotPlaceholder`, so this screen and the model
  // review dock cannot answer the question differently: they render the same
  // thumbnail from the same data, and the last time the answer lived in each of
  // them separately, a fix to this one left the dock still calling a viewpoint
  // that never carried a PNG a broken picture. The module explains the states.
  //
  // Each names itself in the accessible name and the tooltip, and in the caption
  // wherever the box is tall enough to hold a line of text.
  const placeholder = snapshotPlaceholder(viewpoint, failed);
  if (placeholder !== null) {
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
          'flex flex-col items-center justify-center gap-1 bg-surface-secondary px-2',
          'text-center text-content-quaternary',
          className,
        )}
      >
        {placeholder === 'failed' ? (
          <ImageOff size={18} className="shrink-0" />
        ) : placeholder === 'no_snapshot' ? (
          <Crosshair size={18} className="shrink-0" />
        ) : null}
        {withCaption && <span className="text-2xs leading-tight">{label}</span>}
      </div>
    );
  }
  if (!url) {
    return <div className={clsx('animate-pulse bg-surface-secondary', className)} />;
  }
  return <img src={url} alt={alt} className={clsx('object-cover', className)} />;
}

/* ── Comment thread ────────────────────────────────────────────────────── */

function BcfCommentThread({
  projectId,
  topic,
  memberName,
  onPosted,
}: {
  projectId: string;
  topic: Topic;
  memberName: (id: string | null) => string;
  onPosted: () => void;
}) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const [text, setText] = useState('');

  const postMut = useMutation({
    mutationFn: (comment: string) => addComment(projectId, topic.guid, { comment }),
    onSuccess: () => {
      setText('');
      onPosted();
    },
    onError: (err: Error) =>
      addToast({
        type: 'error',
        title: t('bcf.comment_failed', { defaultValue: 'Failed to post comment' }),
        message: err.message,
      }),
  });

  const handlePost = useCallback(() => {
    const trimmed = text.trim();
    if (trimmed) postMut.mutate(trimmed);
  }, [text, postMut]);

  const sorted = useMemo<BcfComment[]>(
    () =>
      [...topic.comments].sort((a, b) => {
        const ta = a.date ? new Date(a.date).getTime() : 0;
        const tb = b.date ? new Date(b.date).getTime() : 0;
        return tb - ta;
      }),
    [topic.comments],
  );

  return (
    <div>
      <div className="mb-2 flex items-center gap-2">
        <MessageSquare size={14} className="text-content-tertiary" />
        <span className="text-xs font-semibold uppercase tracking-wider text-content-tertiary">
          {t('bcf.comments', { defaultValue: 'Comments' })}
        </span>
        {topic.comments.length > 0 && (
          <span className="flex h-4.5 min-w-[18px] items-center justify-center rounded-full bg-surface-secondary px-1 text-2xs font-medium text-content-secondary">
            {topic.comments.length}
          </span>
        )}
      </div>

      <div className="mb-3 flex gap-2">
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
              e.preventDefault();
              handlePost();
            }
          }}
          rows={2}
          placeholder={t('bcf.comment_placeholder', { defaultValue: 'Add a comment...' })}
          className="flex-1 resize-none rounded-lg border border-border-medium bg-surface-primary px-3 py-2 text-xs text-content-primary placeholder:text-content-quaternary focus:border-oe-blue focus:outline-none focus:ring-1 focus:ring-oe-blue/30"
        />
        <button
          type="button"
          onClick={handlePost}
          disabled={!text.trim() || postMut.isPending}
          className={clsx(
            'flex h-9 w-9 shrink-0 items-center justify-center rounded-lg transition-all',
            text.trim()
              ? 'bg-oe-blue text-white hover:bg-oe-blue-hover'
              : 'cursor-not-allowed bg-surface-secondary text-content-quaternary',
          )}
          title={t('bcf.post_comment', { defaultValue: 'Post comment' })}
          aria-label={t('bcf.post_comment', { defaultValue: 'Post comment' })}
        >
          <Send size={14} />
        </button>
      </div>

      {sorted.length === 0 ? (
        <p className="py-4 text-center text-xs text-content-tertiary">
          {t('bcf.no_comments', { defaultValue: 'No comments yet. Start the discussion.' })}
        </p>
      ) : (
        <ul className="divide-y divide-border-light">
          {sorted.map((c) => (
            <li key={c.guid} className="py-2.5">
              <div className="mb-0.5 flex items-center gap-2">
                <span className="text-xs font-semibold text-content-primary">
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
              <p className="whitespace-pre-wrap break-words text-xs leading-relaxed text-content-secondary">
                {c.comment}
              </p>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/* ── Field label helper ────────────────────────────────────────────────── */

function FieldLabel({ icon: Icon, children }: { icon: React.ElementType; children: React.ReactNode }) {
  return (
    <div className="mb-1 flex items-center gap-1 text-2xs font-semibold uppercase tracking-wider text-content-quaternary">
      <Icon size={12} className="shrink-0" />
      {children}
    </div>
  );
}

const fieldInputCls =
  'h-9 w-full rounded-lg border border-border bg-surface-primary px-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue disabled:opacity-50';

/* ── Detail drawer ─────────────────────────────────────────────────────── */

function BcfTopicDetail({
  projectId,
  topicGuid,
  seed,
  members,
  memberName,
  onClose,
  onChanged,
  onOpenViewpoint,
}: {
  projectId: string;
  topicGuid: string;
  seed?: Topic;
  members: BcfMember[];
  memberName: (id: string | null) => string;
  onClose: () => void;
  onChanged: () => void;
  onOpenViewpoint?: (topic: Topic, vp: Viewpoint) => void;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);

  const { data: topic } = useQuery({
    queryKey: ['bcf', 'topic', projectId, topicGuid],
    queryFn: () => getTopic(projectId, topicGuid),
    initialData: seed,
    enabled: Boolean(topicGuid),
  });

  const refresh = useCallback(() => {
    qc.invalidateQueries({ queryKey: ['bcf', 'topic', projectId, topicGuid] });
    onChanged();
  }, [qc, projectId, topicGuid, onChanged]);

  const updateMut = useMutation({
    mutationFn: (patch: TopicUpdate) => updateTopic(projectId, topicGuid, patch),
    onSuccess: () => refresh(),
    onError: (err: Error) =>
      addToast({
        type: 'error',
        title: t('bcf.update_failed', { defaultValue: 'Failed to update issue' }),
        message: err.message,
      }),
  });

  const deleteMut = useMutation({
    mutationFn: () => deleteTopic(projectId, topicGuid),
    onSuccess: () => {
      addToast({ type: 'success', title: t('bcf.issue_deleted', { defaultValue: 'Issue deleted' }) });
      onChanged();
      onClose();
    },
    onError: (err: Error) =>
      addToast({
        type: 'error',
        title: t('bcf.delete_failed', { defaultValue: 'Failed to delete issue' }),
        message: err.message,
      }),
  });

  // Assignee is edited as free text when no member list resolves it.
  const [assigneeDraft, setAssigneeDraft] = useState('');
  useEffect(() => {
    setAssigneeDraft(topic?.assigned_to ?? '');
  }, [topic?.assigned_to]);

  if (!topic) {
    return (
      <SideDrawer open onClose={onClose} title={t('bcf.issue', { defaultValue: 'Issue' })}>
        <div className="p-5">
          <SkeletonText lines={4} />
        </div>
      </SideDrawer>
    );
  }

  const vp = primaryViewpoint(topic);
  const overdue = isOverdue(topic);
  const busy = updateMut.isPending;
  const statusOptions = Array.from(new Set([...COMMON_STATUSES, topic.topic_status])).filter(Boolean);
  const priorityOptions = Array.from(
    new Set([...PRIORITY_CHOICES, topic.priority ?? '']),
  );

  return (
    <SideDrawer
      open
      onClose={onClose}
      busy={deleteMut.isPending}
      widthClass="max-w-2xl"
      title={topic.title}
      subtitle={
        <span className="flex items-center gap-1.5">
          <Badge variant={statusVariant(topic.topic_status)} size="sm">
            {topic.topic_status}
          </Badge>
          {topic.priority && (
            <Badge variant={priorityVariant(topic.priority)} size="sm">
              {topic.priority}
            </Badge>
          )}
        </span>
      }
      headerActions={
        <div className="flex items-center gap-1.5">
          {vp && onOpenViewpoint && (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => onOpenViewpoint(topic, vp)}
              icon={<Crosshair size={14} />}
              title={t('bcf.zoom_to_issue', { defaultValue: 'Zoom to issue' })}
            >
              {t('bcf.zoom_to_issue', { defaultValue: 'Zoom to issue' })}
            </Button>
          )}
          <Button
            variant="ghost"
            size="sm"
            onClick={() => deleteMut.mutate()}
            disabled={deleteMut.isPending}
            icon={<Trash2 size={14} />}
            title={t('bcf.delete_issue', { defaultValue: 'Delete issue' })}
          >
            {t('common.delete', { defaultValue: 'Delete' })}
          </Button>
        </div>
      }
    >
      <div className="space-y-6 p-5">
        {/* Snapshot */}
        <div className="overflow-hidden rounded-xl border border-border-light bg-surface-secondary">
          {vp ? (
            <BcfSnapshot
              projectId={projectId}
              topicGuid={topic.guid}
              viewpoint={vp}
              alt={t('bcf.snapshot_alt', { defaultValue: 'Captured view snapshot' })}
              className="h-56 w-full"
              withCaption
            />
          ) : (
            <div className="flex h-32 flex-col items-center justify-center gap-1.5 text-content-quaternary">
              <ImageOff size={22} />
              <span className="text-2xs">
                {t('bcf.no_view', { defaultValue: 'No saved view for this issue.' })}
              </span>
            </div>
          )}
        </div>

        {/* Editable fields */}
        <section className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div>
            <FieldLabel icon={Boxes}>{t('bcf.field_status', { defaultValue: 'Status' })}</FieldLabel>
            <select
              value={topic.topic_status}
              disabled={busy}
              onChange={(e) => updateMut.mutate({ topic_status: e.target.value })}
              className={fieldInputCls}
              data-testid="bcf-status-select"
            >
              {statusOptions.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </div>

          <div>
            <FieldLabel icon={AlertTriangle}>
              {t('bcf.field_priority', { defaultValue: 'Priority' })}
            </FieldLabel>
            <select
              value={topic.priority ?? ''}
              disabled={busy}
              onChange={(e) => updateMut.mutate({ priority: e.target.value || null })}
              className={fieldInputCls}
            >
              {priorityOptions.map((p) => (
                <option key={p || 'none'} value={p}>
                  {p || t('bcf.priority_none', { defaultValue: 'No priority' })}
                </option>
              ))}
            </select>
          </div>

          <div>
            <FieldLabel icon={User}>
              {t('bcf.field_assigned_to', { defaultValue: 'Assigned to' })}
            </FieldLabel>
            {members.length > 0 ? (
              <select
                value={topic.assigned_to ?? ''}
                disabled={busy}
                onChange={(e) => updateMut.mutate({ assigned_to: e.target.value || null })}
                className={fieldInputCls}
              >
                <option value="">{t('bcf.unassigned', { defaultValue: 'Unassigned' })}</option>
                {/* Keep an imported assignee that is not in the member list. */}
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
                  if (next !== (topic.assigned_to ?? '')) {
                    updateMut.mutate({ assigned_to: next || null });
                  }
                }}
                placeholder={t('bcf.assignee_placeholder', { defaultValue: 'Name or email' })}
                className={fieldInputCls}
              />
            )}
          </div>

          <div>
            <FieldLabel icon={Calendar}>
              {t('bcf.field_due_date', { defaultValue: 'Due date' })}
            </FieldLabel>
            <input
              type="date"
              value={toDateInput(topic.due_date)}
              disabled={busy}
              onChange={(e) => updateMut.mutate({ due_date: e.target.value || null })}
              className={clsx(fieldInputCls, overdue && 'border-semantic-error text-semantic-error')}
            />
            {overdue && (
              <p className="mt-1 flex items-center gap-1 text-2xs font-medium text-semantic-error">
                <AlertTriangle size={11} />
                {t('bcf.overdue', { defaultValue: 'Overdue' })}
              </p>
            )}
          </div>
        </section>

        {/* Description */}
        {topic.description?.trim() && (
          <section>
            <FieldLabel icon={MessageSquare}>
              {t('bcf.field_description', { defaultValue: 'Description' })}
            </FieldLabel>
            <p className="whitespace-pre-wrap text-sm text-content-secondary">{topic.description}</p>
          </section>
        )}

        {/* Labels */}
        {topic.labels.length > 0 && (
          <section>
            <FieldLabel icon={Tag}>{t('bcf.field_labels', { defaultValue: 'Labels' })}</FieldLabel>
            <div className="flex flex-wrap gap-1.5">
              {topic.labels.map((label) => (
                <Badge key={label} variant="neutral" size="sm">
                  {label}
                </Badge>
              ))}
            </div>
          </section>
        )}

        {/* Selection summary */}
        {vp && vp.element_stable_ids.length > 0 && (
          <section>
            <FieldLabel icon={Boxes}>
              {t('bcf.linked_elements', { defaultValue: 'Linked elements' })}
            </FieldLabel>
            <p className="text-sm text-content-secondary">
              {t('bcf.selection_count', {
                defaultValue: '{{count}} element(s) selected',
                count: vp.element_stable_ids.length,
              })}
            </p>
          </section>
        )}

        {/* Comments */}
        <section className="border-t border-border-light pt-4">
          <BcfCommentThread
            projectId={projectId}
            topic={topic}
            memberName={memberName}
            onPosted={refresh}
          />
        </section>
      </div>
    </SideDrawer>
  );
}

/* ── Row ───────────────────────────────────────────────────────────────── */

function BcfTopicRow({
  projectId,
  topic,
  memberName,
  onOpen,
  onOpenViewpoint,
}: {
  projectId: string;
  topic: Topic;
  memberName: (id: string | null) => string;
  onOpen: (topic: Topic) => void;
  onOpenViewpoint?: (topic: Topic, vp: Viewpoint) => void;
}) {
  const { t } = useTranslation();
  const vp = primaryViewpoint(topic);
  const overdue = isOverdue(topic);

  return (
    <Card
      padding="none"
      hoverable
      role="button"
      tabIndex={0}
      onClick={() => onOpen(topic)}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          onOpen(topic);
        }
      }}
      className={clsx(
        'flex cursor-pointer items-stretch gap-3 overflow-hidden',
        'focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/40',
      )}
    >
      <BcfSnapshot
        projectId={projectId}
        topicGuid={topic.guid}
        viewpoint={vp}
        alt={t('bcf.snapshot_alt', { defaultValue: 'Captured view snapshot' })}
        className="h-24 w-32 shrink-0"
      />
      <div className="min-w-0 flex-1 py-2.5 pr-3">
        <div className="flex items-start justify-between gap-2">
          <h4 className="truncate text-sm font-semibold text-content-primary">{topic.title}</h4>
          <div className="flex shrink-0 items-center gap-1.5">
            {vp && onOpenViewpoint && (
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  onOpenViewpoint(topic, vp);
                }}
                className="flex h-6 w-6 items-center justify-center rounded-md text-content-tertiary transition-colors hover:bg-oe-blue-subtle/40 hover:text-oe-blue"
                title={t('bcf.zoom_to_issue', { defaultValue: 'Zoom to issue' })}
                aria-label={t('bcf.zoom_to_issue', { defaultValue: 'Zoom to issue' })}
              >
                <Crosshair size={13} />
              </button>
            )}
            <Badge variant={statusVariant(topic.topic_status)} size="sm">
              {topic.topic_status}
            </Badge>
            {topic.priority && (
              <Badge variant={priorityVariant(topic.priority)} size="sm">
                {topic.priority}
              </Badge>
            )}
          </div>
        </div>

        {topic.description && (
          <p className="mt-0.5 line-clamp-1 text-xs text-content-tertiary">{topic.description}</p>
        )}

        {topic.labels.length > 0 && (
          <div className="mt-1.5 flex flex-wrap gap-1">
            {topic.labels.slice(0, 4).map((label) => (
              <Badge key={label} variant="neutral" size="sm">
                {label}
              </Badge>
            ))}
            {topic.labels.length > 4 && (
              <span className="text-2xs text-content-quaternary">
                +{topic.labels.length - 4}
              </span>
            )}
          </div>
        )}

        <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-2xs text-content-tertiary">
          <span className="inline-flex items-center gap-1">
            <User size={11} className="shrink-0" />
            {topic.assigned_to ? (
              memberName(topic.assigned_to)
            ) : (
              <span className="text-content-quaternary">
                {t('bcf.unassigned', { defaultValue: 'Unassigned' })}
              </span>
            )}
          </span>
          {topic.due_date && (
            <span
              className={clsx(
                'inline-flex items-center gap-1',
                overdue && 'font-medium text-semantic-error',
              )}
            >
              {overdue ? <AlertTriangle size={11} /> : <Calendar size={11} />}
              <DateDisplay value={topic.due_date} format="date" />
            </span>
          )}
          {topic.comments.length > 0 && (
            <span className="inline-flex items-center gap-1">
              <MessageSquare size={11} className="shrink-0" />
              {topic.comments.length}
            </span>
          )}
        </div>
      </div>
    </Card>
  );
}

/* ── Main panel ────────────────────────────────────────────────────────── */

export interface BcfIssuesPanelProps {
  projectId: string;
  /** Stamped onto issues raised from the viewer, and a hint for filtering. */
  bimModelId?: string | null;
  /** Wire the "Raise issue here" capture flow to a live viewer. Optional. */
  bridge?: BcfViewerBridge;
  /** Fly the viewer to an issue's saved viewpoint. Enables the "Zoom to
   *  issue" affordances and coordination mode's guided walk-through. */
  onOpenViewpoint?: (topic: Topic, vp: Viewpoint) => void;
  className?: string;
}

interface RawUser {
  id: string;
  email: string;
  full_name?: string | null;
  is_active?: boolean;
}

export function BcfIssuesPanel({
  projectId,
  bimModelId,
  bridge,
  onOpenViewpoint,
  className,
}: BcfIssuesPanelProps) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [openTopic, setOpenTopic] = useState<Topic | null>(null);
  const [showCapture, setShowCapture] = useState(false);
  const [showDashboard, setShowDashboard] = useState(false);
  const [showCoordination, setShowCoordination] = useState(false);
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [exportVersion, setExportVersion] = useState<BcfVersion>('2.1');

  const topicsQuery = useQuery({
    queryKey: ['bcf', 'topics', projectId],
    queryFn: () => listTopics(projectId),
    enabled: Boolean(projectId),
  });
  const topics = useMemo(() => topicsQuery.data ?? [], [topicsQuery.data]);

  // Resolve user ids to names (assignees + comment authors). Reuses the shared
  // ['users-search'] cache, so the queryFn must store the SAME raw-row shape
  // other consumers (e.g. CommentThread) cache under this key; the BcfMember
  // mapping happens in a memo below. A failure degrades to showing the raw id.
  const canListUsers = useHasPermission('users.list');
  const { data: rawUsers = [] } = useQuery({
    queryKey: ['users-search'],
    queryFn: async () => {
      const res = await apiGet<RawUser[] | { items: RawUser[] }>(
        '/v1/users/?limit=100&is_active=true',
      );
      return Array.isArray(res) ? res : res.items ?? [];
    },
    staleTime: 60_000,
    retry: false,
    enabled: canListUsers,
  });

  const members = useMemo<BcfMember[]>(
    () =>
      rawUsers.map((u) => ({
        id: u.id,
        name: (u.full_name ?? '').trim() || u.email,
      })),
    [rawUsers],
  );

  const memberById = useMemo(() => {
    const map = new Map<string, string>();
    for (const m of members) map.set(m.id, m.name);
    return map;
  }, [members]);

  const memberName = useCallback(
    (id: string | null): string => {
      if (!id) return t('bcf.unassigned', { defaultValue: 'Unassigned' });
      return memberById.get(id) ?? id;
    },
    [memberById, t],
  );

  const invalidateTopics = useCallback(() => {
    qc.invalidateQueries({ queryKey: ['bcf', 'topics', projectId] });
  }, [qc, projectId]);

  const exportMut = useMutation({
    mutationFn: () => exportBcf(projectId, exportVersion),
    onSuccess: ({ blob, filename }) => {
      triggerDownload(blob, filename);
      addToast({ type: 'success', title: t('bcf.exported', { defaultValue: 'BCF exported' }) });
    },
    onError: (err: Error) =>
      addToast({
        type: 'error',
        title: t('bcf.export_failed', { defaultValue: 'Export failed' }),
        message: err.message,
      }),
  });

  const importMut = useMutation({
    mutationFn: (file: File) => importBcf(projectId, file),
    onSuccess: (report) => {
      invalidateTopics();
      const type =
        report.status === 'errors' ? 'error' : report.status === 'warnings' ? 'warning' : 'success';
      // Coerce the numeric wire counts before they reach the template.
      const message = fmtList([
        t('bcf.import_topics', {
          defaultValue: '{{count}} imported',
          count: toNum(report.topics_imported),
        }),
        t('bcf.import_updated', {
          defaultValue: '{{count}} updated',
          count: toNum(report.topics_updated),
        }),
        t('bcf.import_comments', {
          defaultValue: '{{count}} comments',
          count: toNum(report.comments_imported),
        }),
        t('bcf.import_viewpoints', {
          defaultValue: '{{count}} viewpoints',
          count: toNum(report.viewpoints_imported),
        }),
      ]);
      addToast({
        type,
        title: t('bcf.import_done', { defaultValue: 'BCF import finished' }),
        message,
      });
    },
    onError: (err: Error) =>
      addToast({
        type: 'error',
        title: t('bcf.import_failed', { defaultValue: 'Import failed' }),
        message: err.message,
      }),
  });

  const handleImportFile = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    // Reset so re-selecting the same file still fires onChange.
    e.target.value = '';
    if (file) importMut.mutate(file);
  };

  const handleCreated = useCallback(
    (result: RaiseIssueResult) => {
      invalidateTopics();
      setOpenTopic(result.topic);
    },
    [invalidateTopics],
  );

  // Client-side search + status filter over the loaded list.
  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return topics.filter((topic) => {
      if (statusFilter && topic.topic_status !== statusFilter) return false;
      if (!q) return true;
      return (
        topic.title.toLowerCase().includes(q) ||
        (topic.description ?? '').toLowerCase().includes(q) ||
        (topic.assigned_to ?? '').toLowerCase().includes(q) ||
        topic.labels.some((l) => l.toLowerCase().includes(q))
      );
    });
  }, [topics, search, statusFilter]);

  const statusFilterOptions = useMemo(
    () => Array.from(new Set(topics.map((topic) => topic.topic_status))).filter(Boolean),
    [topics],
  );

  // Open the current (filtered) issue list as a clean, printable report in a
  // new tab, mirroring the BIM filter-report print flow.
  const handlePrintReport = useCallback(() => {
    const stats = computeIssueStats(topics);
    const rows: IssueReportRow[] = filtered.map((topic) => ({
      index: topic.index,
      title: topic.title,
      status: topic.topic_status,
      priority: topic.priority ?? '',
      assignee: topic.assigned_to ? memberName(topic.assigned_to) : '',
      due: toDateInput(topic.due_date) || null,
      comments: topic.comments.length,
      description: topic.description,
    }));
    const html = buildIssueReportHtml({
      title: t('bcf.report_title', { defaultValue: 'Coordination issue report' }),
      scopeLabel: t('bcf.report_scope', {
        defaultValue: '{{count}} issue(s)',
        count: filtered.length,
      }),
      generatedOn: new Date().toLocaleString(getIntlLocale()),
      stats,
      rows,
      labels: {
        summary: t('bcf.dashboard_summary', { defaultValue: 'Summary' }),
        total: t('bcf.report_total', { defaultValue: 'Total issues' }),
        open: t('bcf.dashboard_open', { defaultValue: 'Open' }),
        closed: t('bcf.report_closed', { defaultValue: 'Closed' }),
        overdue: t('bcf.dashboard_overdue', { defaultValue: 'Overdue' }),
        unassigned: t('bcf.report_unassigned', { defaultValue: 'Unassigned (open)' }),
        issues: t('bcf.report_issues', { defaultValue: 'Issues' }),
        colNum: '#',
        colTitle: t('bcf.report_col_issue', { defaultValue: 'Issue' }),
        colStatus: t('bcf.field_status', { defaultValue: 'Status' }),
        colPriority: t('bcf.field_priority', { defaultValue: 'Priority' }),
        colAssignee: t('bcf.field_assigned_to', { defaultValue: 'Assigned to' }),
        colDue: t('bcf.field_due_date', { defaultValue: 'Due date' }),
        colComments: t('bcf.comments', { defaultValue: 'Comments' }),
        none: '-',
      },
    });
    const w = window.open('', '_blank');
    if (!w) {
      addToast({
        type: 'warning',
        title: t('bcf.report_popup_blocked', {
          defaultValue: 'Allow pop-ups to print the report',
        }),
      });
      return;
    }
    w.document.write(html);
    w.document.close();
    w.focus();
    w.print();
  }, [topics, filtered, memberName, t, addToast]);

  return (
    <div className={clsx('space-y-4', className)}>
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <Boxes size={18} className="text-content-tertiary" />
          <h3 className="text-base font-semibold text-content-primary">
            {t('bcf.title', { defaultValue: 'Issues (BCF)' })}
          </h3>
          <span className="flex h-5 min-w-[20px] items-center justify-center rounded-full bg-surface-secondary px-1.5 text-2xs font-medium text-content-secondary">
            {topics.length}
          </span>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <input
            ref={fileInputRef}
            type="file"
            accept=".bcfzip,application/zip,application/octet-stream"
            onChange={handleImportFile}
            className="hidden"
            data-testid="bcf-import-input"
          />
          {topics.length > 0 && (
            <div className="flex items-center gap-0.5">
              <button
                type="button"
                onClick={() => setShowDashboard((v) => !v)}
                aria-pressed={showDashboard}
                title={t('bcf.overview', { defaultValue: 'Overview' })}
                aria-label={t('bcf.overview', { defaultValue: 'Overview' })}
                className={clsx(
                  'flex h-8 w-8 items-center justify-center rounded-lg border transition-colors',
                  showDashboard
                    ? 'border-oe-blue/40 bg-oe-blue-subtle/40 text-oe-blue'
                    : 'border-border-light text-content-secondary hover:bg-surface-secondary',
                )}
              >
                <BarChart3 size={15} />
              </button>
              {onOpenViewpoint && (
                <button
                  type="button"
                  onClick={() => setShowCoordination(true)}
                  title={t('bcf.coordination_mode', { defaultValue: 'Coordination mode' })}
                  aria-label={t('bcf.coordination_mode', { defaultValue: 'Coordination mode' })}
                  className="flex h-8 w-8 items-center justify-center rounded-lg border border-border-light text-content-secondary transition-colors hover:bg-surface-secondary"
                >
                  <Presentation size={15} />
                </button>
              )}
              <button
                type="button"
                onClick={handlePrintReport}
                title={t('bcf.print_report', { defaultValue: 'Print report' })}
                aria-label={t('bcf.print_report', { defaultValue: 'Print report' })}
                className="flex h-8 w-8 items-center justify-center rounded-lg border border-border-light text-content-secondary transition-colors hover:bg-surface-secondary"
              >
                <Printer size={15} />
              </button>
            </div>
          )}
          <Button
            variant="ghost"
            size="sm"
            onClick={() => fileInputRef.current?.click()}
            loading={importMut.isPending}
            icon={<Upload size={14} />}
          >
            {t('bcf.import', { defaultValue: 'Import .bcfzip' })}
          </Button>
          <div className="flex items-center gap-1.5">
            <select
              value={exportVersion}
              onChange={(e) => setExportVersion(e.target.value as BcfVersion)}
              className="h-7 rounded-md border border-border bg-surface-primary px-1.5 text-xs focus:outline-none focus:ring-2 focus:ring-oe-blue/30"
              aria-label={t('bcf.export_version', { defaultValue: 'BCF version' })}
              title={t('bcf.export_version', { defaultValue: 'BCF version' })}
            >
              <option value="2.1">BCF 2.1</option>
              <option value="3.0">BCF 3.0</option>
            </select>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => exportMut.mutate()}
              loading={exportMut.isPending}
              disabled={topics.length === 0}
              icon={<Download size={14} />}
            >
              {t('bcf.export', { defaultValue: 'Export .bcfzip' })}
            </Button>
          </div>
          {bridge && (
            <Button
              variant="primary"
              size="sm"
              onClick={() => setShowCapture(true)}
              icon={<Plus size={14} />}
              data-testid="bcf-raise-issue"
            >
              {t('bcf.raise_issue', { defaultValue: 'Raise issue here' })}
            </Button>
          )}
        </div>
      </div>

      {/* Overview dashboard (toggle) */}
      {showDashboard && topics.length > 0 && (
        <ReviewDashboard topics={topics} memberName={memberName} />
      )}

      {/* Toolbar */}
      {topics.length > 0 && (
        <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
          <div className="relative max-w-sm flex-1">
            <Search
              size={15}
              className="absolute start-3 top-1/2 -translate-y-1/2 text-content-tertiary"
            />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder={t('bcf.search', { defaultValue: 'Search title, labels, assignee...' })}
              aria-label={t('bcf.search', { defaultValue: 'Search title, labels, assignee...' })}
              className="h-9 w-full rounded-lg border border-border bg-surface-primary ps-9 pe-3 text-sm focus:border-oe-blue focus:outline-none focus:ring-2 focus:ring-oe-blue/30"
            />
          </div>
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className="h-9 rounded-lg border border-border bg-surface-primary px-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30"
            aria-label={t('bcf.filter_status', { defaultValue: 'Filter by status' })}
          >
            <option value="">{t('bcf.all_statuses', { defaultValue: 'All statuses' })}</option>
            {statusFilterOptions.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </div>
      )}

      {/* List */}
      {topicsQuery.isLoading ? (
        <div className="space-y-3">
          {[0, 1, 2].map((i) => (
            <Card key={i} padding="sm">
              <SkeletonText lines={3} />
            </Card>
          ))}
        </div>
      ) : topicsQuery.isError ? (
        <Card padding="lg">
          <p className="text-center text-sm text-semantic-error">
            {t('bcf.load_failed', { defaultValue: 'Could not load issues. Please try again.' })}
          </p>
        </Card>
      ) : topics.length === 0 ? (
        <EmptyState
          icon={<Boxes size={24} />}
          title={t('bcf.empty_title', { defaultValue: 'No issues yet' })}
          description={
            bridge
              ? t('bcf.empty_desc_viewer', {
                  defaultValue:
                    'Select something in the model and raise an issue, or import a .bcfzip from another tool.',
                })
              : t('bcf.empty_desc', {
                  defaultValue: 'Import a .bcfzip from another tool to get started.',
                })
          }
          action={
            bridge
              ? {
                  label: t('bcf.raise_issue', { defaultValue: 'Raise issue here' }),
                  onClick: () => setShowCapture(true),
                }
              : undefined
          }
        />
      ) : filtered.length === 0 ? (
        <p className="py-8 text-center text-sm text-content-tertiary">
          {t('bcf.no_match', { defaultValue: 'No issues match your search.' })}
        </p>
      ) : (
        <div className="space-y-3" data-testid="bcf-topic-list">
          {filtered.map((topic) => (
            <BcfTopicRow
              key={topic.guid}
              projectId={projectId}
              topic={topic}
              memberName={memberName}
              onOpen={setOpenTopic}
              onOpenViewpoint={onOpenViewpoint}
            />
          ))}
        </div>
      )}

      {/* Detail drawer */}
      {openTopic && (
        <BcfTopicDetail
          projectId={projectId}
          topicGuid={openTopic.guid}
          seed={openTopic}
          members={members}
          memberName={memberName}
          onClose={() => setOpenTopic(null)}
          onChanged={invalidateTopics}
          onOpenViewpoint={onOpenViewpoint}
        />
      )}

      {/* Capture modal */}
      {bridge && (
        <BcfIssueModal
          open={showCapture}
          onClose={() => setShowCapture(false)}
          projectId={projectId}
          bridge={bridge}
          bimModelId={bimModelId}
          assignees={members}
          onCreated={handleCreated}
        />
      )}

      {/* Coordination meeting mode */}
      {showCoordination && onOpenViewpoint && (
        <CoordinationMode
          projectId={projectId}
          topics={topics}
          onOpenViewpoint={onOpenViewpoint}
          onChanged={invalidateTopics}
          onClose={() => setShowCoordination(false)}
        />
      )}
    </div>
  );
}
