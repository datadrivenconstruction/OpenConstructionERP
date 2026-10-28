// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * ActivityDrawer — right-edge slide-over showing the full audit trail
 * for a single document.
 *
 * Backed by ``GET /v1/documents/{id}/activity/?limit=N``, which answers
 * with ``{items, total, offset, limit}``. The drawer asks for the route's
 * maximum and still shows `total`, because a file busy enough to overrun
 * that maximum is exactly the file whose reader needs to be told.
 *
 * UX notes:
 *   - 360px wide right-anchored panel (vs FilePreviewPane's 320px)
 *   - Backdrop scrim, click-outside / Escape to close
 *   - Entries grouped by Today / Yesterday / Earlier with sticky labels
 *   - Each row: action chip, actor identifier, relative time
 *     (absolute on hover via DateDisplay's native title behaviour),
 *     and an action-specific summary line (rename old→new etc.).
 *   - Empty state, error state with retry, loading skeleton.
 *   - All strings flow through ``t(key, { defaultValue })`` so en.ts
 *     is the source-of-truth and missing keys fall back gracefully.
 */

import { useEffect, useMemo, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import {
  Activity,
  AlertCircle,
  Download,
  FileUp,
  Pencil,
  Tag,
  Trash2,
  User,
  X,
  type LucideIcon,
} from 'lucide-react';
import clsx from 'clsx';

import { apiGet, type Page } from '@/shared/lib/api';
import { TruncationNotice } from '@/shared/ui/TruncationNotice';
import { DateDisplay } from '@/shared/ui/DateDisplay';
import { getIntlLocale } from '@/shared/lib/formatters';

// ── Types ────────────────────────────────────────────────────────────

export interface ActivityEvent {
  id: string;
  document_id: string;
  user_id: string | null;
  /** Some backends include a resolved actor email; tolerated when present. */
  actor_email?: string | null;
  action: string;
  meta: Record<string, unknown>;
  created_at: string;
}

interface ActivityDrawerProps {
  /** Document id whose timeline we should fetch. ``null`` keeps the drawer closed. */
  documentId: string | null;
  /** Optional filename — used in the drawer header for context. */
  documentName?: string | null;
  /** Whether the drawer is open. */
  open: boolean;
  /** Fired when the user clicks the backdrop, the close button, or presses Escape. */
  onClose: () => void;
}

// ── Action → icon + chip styling ─────────────────────────────────────

const ACTION_ICON: Record<string, LucideIcon> = {
  uploaded: FileUp,
  renamed: Pencil,
  downloaded: Download,
  deleted: Trash2,
  cde_state_changed: Tag,
};

const ACTION_CHIP: Record<string, string> = {
  uploaded: 'bg-emerald-100 text-emerald-800 dark:bg-emerald-900/30 dark:text-emerald-300',
  renamed: 'bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-300',
  downloaded: 'bg-surface-secondary text-content-secondary',
  deleted: 'bg-rose-100 text-rose-800 dark:bg-rose-900/30 dark:text-rose-300',
  cde_state_changed: 'bg-amber-100 text-amber-800 dark:bg-amber-900/30 dark:text-amber-300',
};

/* The route's maximum page. It belongs in the query key as well as the
   URL: the preview pane reads the same endpoint for the same document at
   a limit of 20, and while the key omitted the limit the two shared one
   cache entry, so whichever mounted first decided what the other saw. */
const DRAWER_ACTIVITY_LIMIT = 100;

// ── Bucketing ────────────────────────────────────────────────────────

type DateBucket = 'today' | 'yesterday' | 'earlier';

/** Bucket an ISO date string into Today / Yesterday / Earlier — same
    pattern as ``NotificationBell.bucketFor`` so the two surfaces feel
    consistent to the user. */
function bucketFor(dateStr: string): DateBucket {
  const created = new Date(dateStr);
  const now = new Date();
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  const startOfYesterday = startOfToday - 24 * 60 * 60 * 1000;
  const t = created.getTime();
  if (t >= startOfToday) return 'today';
  if (t >= startOfYesterday) return 'yesterday';
  return 'earlier';
}

// ── Metadata snippets ────────────────────────────────────────────────

/** Locale-neutral one-line summary for the most common audit actions.
    Returns an empty string when nothing useful can be extracted so the
    UI just shows the chip + actor + timestamp. */
function formatMeta(action: string, meta: Record<string, unknown>): string {
  if (action === 'renamed') {
    const oldName = typeof meta.old === 'string' ? meta.old : '';
    const newName = typeof meta.new === 'string' ? meta.new : '';
    if (oldName && newName) return `${oldName} → ${newName}`;
  }
  if (action === 'cde_state_changed') {
    const oldState = typeof meta.old === 'string' ? meta.old : 'wip';
    const newState = typeof meta.new === 'string' ? meta.new : '';
    if (newState) return `${oldState} → ${newState}`;
  }
  if (action === 'uploaded' || action === 'deleted') {
    const name = typeof meta.name === 'string' ? meta.name : '';
    return name;
  }
  return '';
}

/** Pick the best label for the actor — explicit email wins, otherwise
    the raw id (which is a UUID and not pretty, but at least non-empty). */
function actorLabel(ev: ActivityEvent, fallback: string): string {
  if (ev.actor_email && ev.actor_email.trim()) return ev.actor_email;
  if (ev.user_id && ev.user_id.trim()) return ev.user_id;
  return fallback;
}

// ── Component ────────────────────────────────────────────────────────

export function ActivityDrawer({
  documentId,
  documentName,
  open,
  onClose,
}: ActivityDrawerProps) {
  const { t } = useTranslation();
  const panelRef = useRef<HTMLDivElement>(null);
  const closeBtnRef = useRef<HTMLButtonElement>(null);

  const {
    data,
    isLoading,
    isError,
    refetch,
    isFetching,
  } = useQuery({
    queryKey: ['document-activity', documentId, DRAWER_ACTIVITY_LIMIT],
    // The route answers with a page, and the drawer asks for its maximum.
    // `total` is how many events the document really has, which is the only
    // way a long history can announce itself. Spelled out rather than hidden
    // behind a type alias: the envelope gate reads the call, not the file.
    queryFn: () =>
      apiGet<Page<ActivityEvent>>(`/v1/documents/${documentId}/activity/?limit=${DRAWER_ACTIVITY_LIMIT}`),
    /* Only run when we actually have a document id AND the drawer is
       open. Keeps the React Query cache from filling with stale entries
       when the user merely browses files without opening the drawer. */
    enabled: open && Boolean(documentId),
    staleTime: 15_000,
    retry: false,
  });

  const events: ActivityEvent[] = useMemo(() => data?.items ?? [], [data]);

  /* Group newest-first into Today / Yesterday / Earlier. Bucket order
     is preserved by walking the keys in declaration order. */
  const grouped = useMemo(() => {
    const buckets: Record<DateBucket, ActivityEvent[]> = {
      today: [],
      yesterday: [],
      earlier: [],
    };
    for (const ev of events) buckets[bucketFor(ev.created_at)].push(ev);
    return buckets;
  }, [events]);

  // The document's event count, from the server. On a file with more events
  // than one request carries this is larger than the list below, which is
  // what the notice at the end of the list is there to say.
  const totalCount = data?.total ?? events.length;

  // Escape-to-close.
  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [open, onClose]);

  // Initial focus on the close button so keyboard users land somewhere sane.
  useEffect(() => {
    if (open) closeBtnRef.current?.focus();
  }, [open]);

  const unknownActorLabel = t('files.activity.actor_unknown', {
    defaultValue: 'Unknown user',
  });

  return (
    <>
      {/* Backdrop scrim — fades in/out and intercepts clicks so the
          drawer feels like a real modal layer. ``pointer-events-none``
          when closed lets the underlying preview pane stay interactive. */}
      <div
        aria-hidden="true"
        onClick={onClose}
        className={clsx(
          'fixed inset-0 z-40 bg-black/30 transition-opacity duration-200',
          open ? 'opacity-100 pointer-events-auto' : 'opacity-0 pointer-events-none',
        )}
      />

      {/* Slide-over panel — 360px wide, translates in from the right. */}
      <aside
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="activity-drawer-title"
        data-testid="activity-drawer"
        className={clsx(
          'fixed top-0 right-0 z-50 h-full w-[360px] max-w-[100vw]',
          'border-s border-border-light bg-surface-elevated shadow-xl',
          'transition-transform duration-200 ease-oe',
          'flex flex-col',
          open ? 'translate-x-0' : 'translate-x-full',
        )}
      >
        {/* Header */}
        <div className="flex items-center justify-between gap-2 border-b border-border-light px-4 py-3">
          <div className="min-w-0 flex-1">
            <h2
              id="activity-drawer-title"
              className="flex items-center gap-1.5 text-sm font-semibold text-content-primary"
            >
              <Activity size={14} strokeWidth={2} />
              {t('files.activity.title', { defaultValue: 'Activity' })}
              {totalCount > 0 && (
                <span className="text-2xs font-normal text-content-quaternary tabular-nums">
                  ({totalCount})
                </span>
              )}
            </h2>
            {documentName && (
              <p
                className="mt-0.5 truncate text-2xs text-content-tertiary"
                title={documentName}
              >
                {documentName}
              </p>
            )}
          </div>
          <button
            ref={closeBtnRef}
            type="button"
            onClick={onClose}
            aria-label={t('common.close', { defaultValue: 'Close' })}
            className="flex h-7 w-7 shrink-0 items-center justify-center rounded text-content-tertiary hover:bg-surface-secondary hover:text-content-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/40"
          >
            <X size={14} />
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto">
          {/* When the drawer is closed (or has no document id) the query
              is disabled and ``data`` stays undefined — render nothing
              rather than the empty / loading / error UI which would all
              be inappropriate for an "off-screen, never fired" state. */}
          {!open || !documentId ? null : isLoading ? (
            <ActivitySkeleton />
          ) : isError ? (
            <ActivityErrorState
              onRetry={() => refetch()}
              retrying={isFetching}
            />
          ) : events.length === 0 ? (
            <ActivityEmptyState />
          ) : (
            (['today', 'yesterday', 'earlier'] as const).map((bucket) => {
              const rows = grouped[bucket];
              if (rows.length === 0) return null;
              const bucketLabel = t(`files.activity.bucket.${bucket}`, {
                defaultValue:
                  bucket === 'today'
                    ? 'Today'
                    : bucket === 'yesterday'
                    ? 'Yesterday'
                    : 'Earlier',
              });
              return (
                <section key={bucket} data-testid={`activity-bucket-${bucket}`}>
                  <h3 className="sticky top-0 z-10 border-b border-border-light/60 bg-surface-elevated/95 px-4 py-1.5 text-[10px] font-semibold uppercase tracking-wider text-content-quaternary backdrop-blur">
                    {bucketLabel}
                  </h3>
                  <ol className="divide-y divide-border-light/60">
                    {rows.map((ev) => (
                      <ActivityRow
                        key={ev.id}
                        event={ev}
                        unknownActorLabel={unknownActorLabel}
                      />
                    ))}
                  </ol>
                </section>
              );
            })
          )}
          {/* The drawer asks for the route's maximum and cannot page, so a
              file with a long revision history shows only its recent events. */}
          {data ? <TruncationNotice page={data} className="px-4 py-3" /> : null}
        </div>
      </aside>
    </>
  );
}

// ── Sub-components (kept in-file — drawer-private surface) ────────────

function ActivityRow({
  event,
  unknownActorLabel,
}: {
  event: ActivityEvent;
  unknownActorLabel: string;
}) {
  const { t } = useTranslation();
  const Icon = ACTION_ICON[event.action] ?? Activity;
  const chip = ACTION_CHIP[event.action] ?? 'bg-surface-secondary text-content-secondary';
  const summary = formatMeta(event.action, event.meta ?? {});
  const actor = actorLabel(event, unknownActorLabel);
  const actionLabel = t(`files.activity.action.${event.action}`, {
    defaultValue: event.action.replace(/_/g, ' '),
  });

  // Absolute timestamp for the hover title — the DateDisplay component
  // renders the relative form ("3h ago") but the user often wants the
  // exact moment, surfaced here via a plain HTML title attribute on
  // the wrapping <li>.
  const absolute = (() => {
    try {
      return new Date(event.created_at).toLocaleString(getIntlLocale());
    } catch {
      return event.created_at;
    }
  })();

  return (
    <li
      className="flex items-start gap-2.5 px-4 py-3"
      data-testid="activity-row"
      title={absolute}
    >
      <span className="mt-0.5 inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-surface-secondary text-content-secondary">
        <Icon size={13} strokeWidth={2} />
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-1.5">
          <span
            className={clsx(
              'inline-flex items-center rounded-md px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide',
              chip,
            )}
          >
            {actionLabel}
          </span>
          <DateDisplay
            value={event.created_at}
            format="relative"
            className="text-2xs text-content-quaternary"
          />
        </div>
        {summary && (
          <p className="mt-1 break-words text-[11px] text-content-secondary">
            {summary}
          </p>
        )}
        <p className="mt-0.5 flex items-center gap-1 truncate text-[10px] text-content-quaternary">
          <User size={9} strokeWidth={2} className="shrink-0" />
          <span className="truncate font-mono" title={actor}>
            {actor}
          </span>
        </p>
      </div>
    </li>
  );
}

function ActivitySkeleton() {
  return (
    <div className="space-y-3 p-4" aria-busy="true" data-testid="activity-loading">
      {[0, 1, 2, 3].map((i) => (
        <div key={i} className="flex items-start gap-2.5">
          <div className="h-7 w-7 shrink-0 animate-pulse rounded-md bg-surface-secondary" />
          <div className="flex-1 space-y-1.5">
            <div className="h-3 w-1/3 animate-pulse rounded bg-surface-secondary" />
            <div className="h-2 w-3/4 animate-pulse rounded bg-surface-secondary" />
          </div>
        </div>
      ))}
    </div>
  );
}

function ActivityEmptyState() {
  const { t } = useTranslation();
  return (
    <div
      className="px-6 py-12 text-center"
      data-testid="activity-empty"
    >
      <Activity
        size={24}
        strokeWidth={1.5}
        className="mx-auto mb-2 text-content-quaternary"
      />
      <p className="text-xs font-medium text-content-secondary">
        {t('files.activity.empty_title', { defaultValue: 'No activity yet' })}
      </p>
      <p className="mt-1 text-2xs text-content-tertiary">
        {t('files.activity.empty_hint', {
          defaultValue: 'Uploads, renames, and other changes will show up here.',
        })}
      </p>
    </div>
  );
}

function ActivityErrorState({
  onRetry,
  retrying,
}: {
  onRetry: () => void;
  retrying: boolean;
}) {
  const { t } = useTranslation();
  return (
    <div
      className="px-6 py-12 text-center"
      data-testid="activity-error"
    >
      <AlertCircle
        size={22}
        strokeWidth={1.75}
        className="mx-auto mb-2 text-semantic-error"
      />
      <p className="text-xs font-medium text-content-secondary">
        {t('files.activity.error_title', {
          defaultValue: "Couldn't load activity",
        })}
      </p>
      <p className="mt-1 text-2xs text-content-tertiary">
        {t('files.activity.error_hint', {
          defaultValue: 'Check your connection and try again.',
        })}
      </p>
      <button
        type="button"
        onClick={onRetry}
        disabled={retrying}
        data-testid="activity-retry"
        className="mt-3 inline-flex items-center gap-1 rounded-md border border-border-light px-2.5 py-1 text-2xs font-medium text-content-primary hover:bg-surface-secondary disabled:opacity-50"
      >
        {retrying
          ? t('common.loading', { defaultValue: 'Loading…' })
          : t('common.retry', { defaultValue: 'Try again' })}
      </button>
    </div>
  );
}
