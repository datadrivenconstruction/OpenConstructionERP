// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The assistant's ledger: every change it proposed and what became of it.
 *
 * One row per proposal, grouped by day: what it was, where, its status, and
 * the people involved ("Asked by Anna · approved by Ben · 14:32"). A waiting
 * row can be applied or rejected right there, an applied one undone, and any
 * row expands into the full card with every field. Applied changes are also in
 * the project's own history, linked at the bottom.
 *
 * Data is fetched only while this view is mounted, so a dock that never opens
 * its Changes tab never asks for it. Rows read the shared store, so a change
 * applied in the chat shows as applied here at once.
 */
import { useEffect, useId, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import type { TFunction } from 'i18next';
import { useNavigate } from 'react-router-dom';
import clsx from 'clsx';
import {
  AlertTriangle,
  ArrowUpRight,
  Check,
  ChevronDown,
  History,
  RotateCcw,
  Sparkles,
  Undo2,
  X,
} from 'lucide-react';
import { ActionButton, ActionConfirmDialog } from './ActionControls';
import {
  ActionProposalCard,
  actionOpenUrl,
  actionSubtitle,
  actionTitle,
  openLabelFor,
  undoConfirmMessage,
} from './ActionProposalCard';
import { ActionStatusPill } from './ActionStatusPill';
import { actionIcon } from './actionIcons';
import { describeRequestError } from './actionErrors';
import { dayKey, formatActionTime, formatDayHeading } from './actionFormat';
import {
  useActionPending,
  useActionRequestError,
  useApplyChatAction,
  useChatActionsList,
  useChatActionStore,
  useRejectChatAction,
  useRevertChatAction,
} from './useChatActions';
import type { ActionStatus, ChatAction, ChatActionCounts, ChatActionListFilters } from './types';
import './actions.css';

export interface ChangesViewProps {
  /** The active project, or null when none is selected. */
  projectId: string | null;
  /** Its name, shown on the scope toggle. */
  projectName?: string;
}

export type ChangesFilter = 'proposed' | 'applied' | 'rejected' | 'reverted' | 'failed' | 'all';
export type ChangesScope = 'project' | 'all';

const PAGE_SIZE = 50;
/** The list endpoint returns at most this many rows per request. */
const MAX_ROWS = 200;

/** The list request for a filter and scope. Unset filters are left out. */
export function changesListFilters(
  filter: ChangesFilter,
  scope: ChangesScope,
  projectId: string | null,
  limit: number = PAGE_SIZE,
): ChatActionListFilters {
  const filters: ChatActionListFilters = { limit, offset: 0 };
  if (scope === 'project' && projectId) filters.project_id = projectId;
  if (filter !== 'all') filters.status = filter;
  return filters;
}

function filterLabel(filter: ChangesFilter, t: TFunction): string {
  switch (filter) {
    case 'proposed':
      return String(t('erp_chat.changes.filter.waiting', { defaultValue: 'Waiting' }));
    case 'applied':
      return String(t('erp_chat.changes.filter.applied', { defaultValue: 'Applied' }));
    case 'rejected':
      return String(t('erp_chat.changes.filter.rejected', { defaultValue: 'Rejected' }));
    case 'reverted':
      return String(t('erp_chat.changes.filter.undone', { defaultValue: 'Undone' }));
    case 'failed':
      return String(t('erp_chat.changes.filter.failed', { defaultValue: 'Failed' }));
    default:
      return String(t('erp_chat.changes.filter.all', { defaultValue: 'All' }));
  }
}

function emptyText(filter: ChangesFilter, t: TFunction): { title: string; body: string } {
  switch (filter) {
    case 'proposed':
      return {
        title: String(t('erp_chat.changes.empty.waiting', { defaultValue: 'Nothing is waiting for review' })),
        body: String(
          t('erp_chat.changes.empty.waiting_body', {
            defaultValue: 'New proposals from the assistant appear here until someone applies or rejects them.',
          }),
        ),
      };
    case 'applied':
      return {
        title: String(t('erp_chat.changes.empty.applied', { defaultValue: 'No changes applied yet' })),
        body: String(
          t('erp_chat.changes.empty.applied_body', {
            defaultValue: 'Changes you apply are listed here with who approved them and when.',
          }),
        ),
      };
    case 'rejected':
      return {
        title: String(t('erp_chat.changes.empty.rejected', { defaultValue: 'No rejected proposals' })),
        body: '',
      };
    case 'reverted':
      return {
        title: String(t('erp_chat.changes.empty.undone', { defaultValue: 'No undone changes' })),
        body: '',
      };
    case 'failed':
      return {
        title: String(t('erp_chat.changes.empty.failed', { defaultValue: 'No failed changes' })),
        body: '',
      };
    default:
      return {
        title: String(t('erp_chat.changes.empty.all', { defaultValue: 'No changes yet' })),
        body: String(
          t('erp_chat.changes.empty.all_body', {
            defaultValue:
              'Ask the assistant to add or change something, for example "add a task to check the formwork on level 3 by Friday". The proposal shows up here, and nothing is saved until someone applies it.',
          }),
        ),
      };
  }
}

/** "Asked by Anna · approved by Ben · 14:32" for a row. */
export function actionMetaLine(action: ChatAction, t: TFunction): string {
  const parts: string[] = [];
  const asker = action.requested_by?.name;
  if (asker) parts.push(String(t('erp_chat.changes.asked_by', { defaultValue: 'Asked by {{name}}', name: asker })));
  const decider = action.decided_by?.name;
  if (decider && action.status === 'applied') {
    parts.push(String(t('erp_chat.changes.approved_by', { defaultValue: 'approved by {{name}}', name: decider })));
  } else if (decider && action.status === 'rejected') {
    parts.push(String(t('erp_chat.changes.rejected_by', { defaultValue: 'rejected by {{name}}', name: decider })));
  } else if (action.status === 'reverted') {
    if (decider) {
      parts.push(String(t('erp_chat.changes.approved_by', { defaultValue: 'approved by {{name}}', name: decider })));
    }
    const undoer = action.reverted_by?.name;
    if (undoer) parts.push(String(t('erp_chat.changes.undone_by', { defaultValue: 'undone by {{name}}', name: undoer })));
  }
  const when = formatActionTime(action.reverted_at ?? action.decided_at ?? action.created_at);
  if (when) parts.push(when);
  return parts.join(' · ');
}

// ── Row ─────────────────────────────────────────────────────────────────────

function ChangesRow({ action, showProject }: { action: ChatAction; showProject: boolean }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const bodyId = useId();
  const [expanded, setExpanded] = useState(false);
  const [confirmUndo, setConfirmUndo] = useState(false);
  const pendingOp = useActionPending(action.id);
  const requestError = useActionRequestError(action.id);
  const apply = useApplyChatAction();
  const reject = useRejectChatAction();
  const revert = useRevertChatAction();

  const busy = pendingOp !== null;
  const Icon = actionIcon(action.action_type);
  const title = actionTitle(action, t);
  const subtitle = actionSubtitle(action, showProject);
  const openUrl = actionOpenUrl(action);
  const openLabel = openLabelFor(action, t);
  const canWork = action.status === 'proposed' || action.status === 'failed';

  const onOpen = () => {
    if (!openUrl) return;
    if (openUrl.startsWith('/')) navigate(openUrl);
    else window.open(openUrl, '_blank', 'noopener,noreferrer');
  };

  return (
    <li
      className="oe-act-enter border-b border-[var(--act-border-subtle)] last:border-b-0"
      data-testid="changes-row"
      data-action-id={action.id}
      data-action-status={action.status}
    >
      <div className="flex items-start gap-2.5 px-3 py-2.5">
        <span
          className="mt-0.5 inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-[var(--act-surface)] text-[var(--act-text-2)]"
          aria-hidden="true"
        >
          <Icon size={14} />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex items-start gap-2">
            <button
              type="button"
              aria-expanded={expanded}
              aria-controls={bodyId}
              onClick={() => setExpanded((v) => !v)}
              className="group flex min-w-0 flex-1 items-start gap-1 rounded text-start focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--act-accent)]"
            >
              <span className="min-w-0 text-[13px] font-semibold leading-5 text-[var(--act-text)] group-hover:underline">
                {title}
              </span>
              <ChevronDown
                size={14}
                aria-hidden="true"
                className={clsx(
                  'mt-[3px] shrink-0 text-[var(--act-text-3)] transition-transform motion-reduce:transition-none',
                  expanded && 'rotate-180',
                )}
              />
              <span className="sr-only">
                {expanded
                  ? t('erp_chat.action.hide_details', { defaultValue: 'Hide details' })
                  : t('erp_chat.action.show_details', { defaultValue: 'Show details' })}
              </span>
            </button>
            <ActionStatusPill status={action.status} busyOp={pendingOp} className="shrink-0" />
          </div>
          {subtitle && (
            <p className="mt-0.5 truncate text-xs text-[var(--act-text-2)]" title={subtitle}>
              {subtitle}
            </p>
          )}
          <p className="mt-0.5 text-[11px] text-[var(--act-text-3)]" data-testid="changes-row-meta">
            {actionMetaLine(action, t)}
          </p>

          {!expanded && (
            <div className="mt-2 flex flex-wrap items-center gap-1.5" aria-live="polite">
              {canWork && action.can_apply && (
                <ActionButton
                  tone="primary"
                  onClick={() => apply.mutate(action.id)}
                  busy={pendingOp === 'apply'}
                  busyLabel={String(t('erp_chat.action.busy.apply', { defaultValue: 'Applying…' }))}
                  disabled={busy}
                  icon={action.status === 'failed' ? <RotateCcw size={12} /> : <Check size={12} />}
                  aria-label={
                    action.status === 'failed'
                      ? String(t('erp_chat.changes.retry_named', { defaultValue: 'Retry: {{title}}', title }))
                      : String(t('erp_chat.changes.apply_named', { defaultValue: 'Apply: {{title}}', title }))
                  }
                >
                  {action.status === 'failed'
                    ? t('erp_chat.action.retry', { defaultValue: 'Retry' })
                    : t('erp_chat.action.apply', { defaultValue: 'Apply' })}
                </ActionButton>
              )}
              {canWork && action.can_reject && (
                <ActionButton
                  tone="ghost"
                  onClick={() => reject.mutate({ id: action.id })}
                  busy={pendingOp === 'reject'}
                  busyLabel={String(t('erp_chat.action.busy.reject', { defaultValue: 'Rejecting…' }))}
                  disabled={busy}
                  icon={<X size={12} />}
                  aria-label={String(t('erp_chat.changes.reject_named', { defaultValue: 'Reject: {{title}}', title }))}
                >
                  {t('erp_chat.action.reject', { defaultValue: 'Reject' })}
                </ActionButton>
              )}
              {action.status === 'applied' && action.can_revert && (
                <ActionButton
                  tone="ghost"
                  onClick={() => setConfirmUndo(true)}
                  busy={pendingOp === 'revert'}
                  busyLabel={String(t('erp_chat.action.busy.revert', { defaultValue: 'Undoing…' }))}
                  disabled={busy}
                  icon={<Undo2 size={12} />}
                  aria-label={String(t('erp_chat.changes.undo_named', { defaultValue: 'Undo: {{title}}', title }))}
                >
                  {t('erp_chat.action.undo', { defaultValue: 'Undo' })}
                </ActionButton>
              )}
              {openUrl && action.status === 'applied' && (
                <ActionButton
                  tone="ghost"
                  onClick={onOpen}
                  icon={<ArrowUpRight size={12} className="rtl:-scale-x-100" />}
                  title={openLabel}
                  aria-label={openLabel}
                >
                  {t('erp_chat.action.open', { defaultValue: 'Open' })}
                </ActionButton>
              )}
            </div>
          )}
          {!expanded && requestError && (
            <p role="alert" className="mt-1.5 flex items-start gap-1.5 text-[11px] text-[var(--act-text)]">
              <AlertTriangle size={12} className="mt-px shrink-0 text-[var(--act-warning)]" aria-hidden="true" />
              <span>{describeRequestError(requestError, t)}</span>
            </p>
          )}
        </div>
      </div>
      {expanded && (
        <div id={bodyId} className="px-3 pb-3 ps-[52px]">
          <ActionProposalCard action={action} variant="embedded" />
        </div>
      )}
      <ActionConfirmDialog
        open={confirmUndo}
        title={String(t('erp_chat.action.undo_confirm_title', { defaultValue: 'Undo this change?' }))}
        message={undoConfirmMessage(action, t)}
        confirmLabel={String(t('erp_chat.action.undo_confirm', { defaultValue: 'Undo change' }))}
        cancelLabel={String(t('erp_chat.action.undo_keep', { defaultValue: 'Keep it' }))}
        loading={pendingOp === 'revert'}
        onConfirm={() => revert.mutate({ id: action.id }, { onSettled: () => setConfirmUndo(false) })}
        onCancel={() => setConfirmUndo(false)}
      />
    </li>
  );
}

// ── Skeleton ────────────────────────────────────────────────────────────────

function RowSkeleton() {
  return (
    <li className="flex items-start gap-2.5 border-b border-[var(--act-border-subtle)] px-3 py-3 last:border-b-0" aria-hidden="true">
      <span className="h-7 w-7 shrink-0 animate-pulse rounded-lg bg-[var(--act-surface-2)] motion-reduce:animate-none" />
      <span className="flex-1 space-y-2">
        <span className="block h-3 w-2/3 animate-pulse rounded bg-[var(--act-surface-2)] motion-reduce:animate-none" />
        <span className="block h-2.5 w-1/2 animate-pulse rounded bg-[var(--act-surface-2)] motion-reduce:animate-none" />
        <span className="block h-2.5 w-1/3 animate-pulse rounded bg-[var(--act-surface-2)] motion-reduce:animate-none" />
      </span>
    </li>
  );
}

// ── View ────────────────────────────────────────────────────────────────────

const FILTER_ORDER: readonly ChangesFilter[] = ['proposed', 'applied', 'rejected', 'reverted', 'failed', 'all'];

function countFor(filter: ChangesFilter, counts: ChatActionCounts | undefined): number | null {
  if (!counts) return null;
  if (filter === 'all') return counts.proposed + counts.applied + counts.rejected + counts.reverted + counts.failed;
  return counts[filter as ActionStatus];
}

export function ChangesView({ projectId, projectName }: ChangesViewProps) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const headingId = useId();
  const [filter, setFilter] = useState<ChangesFilter>('all');
  const [scope, setScope] = useState<ChangesScope>(projectId ? 'project' : 'all');
  const [limit, setLimit] = useState(PAGE_SIZE);

  // A different active project starts from its own changes again.
  useEffect(() => {
    setScope(projectId ? 'project' : 'all');
    setLimit(PAGE_SIZE);
  }, [projectId]);

  const effectiveScope: ChangesScope = projectId ? scope : 'all';
  const filters = useMemo(
    () => changesListFilters(filter, effectiveScope, projectId, limit),
    [filter, effectiveScope, projectId, limit],
  );
  const query = useChatActionsList(filters);
  const byId = useChatActionStore((s) => s.byId);

  const counts = query.data?.counts;
  const rows = useMemo(() => (query.data?.items ?? []).map((a) => byId[a.id] ?? a), [query.data, byId]);
  const groups = useMemo(() => {
    const out: { key: string; iso: string; items: ChatAction[] }[] = [];
    for (const row of rows) {
      const key = dayKey(row.created_at);
      const last = out[out.length - 1];
      if (last && last.key === key) last.items.push(row);
      else out.push({ key, iso: row.created_at, items: [row] });
    }
    return out;
  }, [rows]);

  const showProject = effectiveScope === 'all';
  const visibleFilters = FILTER_ORDER.filter(
    (f) => f !== 'failed' || (counts?.failed ?? 0) > 0 || filter === 'failed',
  );
  const total = query.data?.total ?? 0;
  const loadingFirst = query.isPending;
  const refreshing = query.isFetching && !query.isPending;
  const empty = !loadingFirst && !query.isError && rows.length === 0;
  const emptyCopy = emptyText(filter, t);

  const changeFilter = (next: ChangesFilter) => {
    setFilter(next);
    setLimit(PAGE_SIZE);
  };
  const changeScope = (next: ChangesScope) => {
    setScope(next);
    setLimit(PAGE_SIZE);
  };

  return (
    <section
      className="oe-act flex min-h-0 flex-col text-[var(--act-text)]"
      aria-labelledby={headingId}
      data-testid="changes-view"
    >
      <h3 id={headingId} className="sr-only">
        {t('erp_chat.changes.heading', { defaultValue: 'Changes proposed by the assistant' })}
      </h3>

      <div className="space-y-2 border-b border-[var(--act-border-subtle)] px-3 pb-2.5 pt-3">
        <p className="text-xs leading-snug text-[var(--act-text-2)]">
          {t('erp_chat.changes.intro', {
            defaultValue: 'Everything the assistant proposed, and who decided what. Nothing reaches the project until someone applies it.',
          })}
        </p>

        {/* Scope: this project or everything visible to me. */}
        <div
          role="group"
          aria-label={String(t('erp_chat.changes.scope_label', { defaultValue: 'Show changes from' }))}
          className="inline-flex max-w-full rounded-md border border-[var(--act-border)] p-0.5"
        >
          {(['project', 'all'] as const).map((s) => {
            const active = effectiveScope === s;
            const disabled = s === 'project' && !projectId;
            const label =
              s === 'project'
                ? projectId && projectName
                  ? String(t('erp_chat.changes.scope_project_named', { defaultValue: 'This project: {{name}}', name: projectName }))
                  : String(t('erp_chat.changes.scope_project', { defaultValue: 'This project' }))
                : String(t('erp_chat.changes.scope_all', { defaultValue: 'All projects' }));
            return (
              <button
                key={s}
                type="button"
                aria-pressed={active}
                disabled={disabled}
                title={
                  disabled
                    ? String(t('erp_chat.changes.no_project', { defaultValue: 'No project selected' }))
                    : label
                }
                onClick={() => changeScope(s)}
                data-testid={`changes-scope-${s}`}
                className={clsx(
                  'min-w-0 max-w-[240px] truncate rounded px-2 py-0.5 text-xs font-medium transition-colors',
                  'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--act-accent)]',
                  active
                    ? 'bg-[var(--act-accent-subtle)] text-[var(--act-accent)]'
                    : 'text-[var(--act-text-2)] hover:text-[var(--act-text)]',
                  disabled && 'cursor-not-allowed opacity-50',
                )}
              >
                {label}
              </button>
            );
          })}
        </div>

        {/* Status filters with counts. */}
        <div
          role="group"
          aria-label={String(t('erp_chat.changes.filter_label', { defaultValue: 'Filter by status' }))}
          className="flex flex-wrap gap-1.5"
        >
          {visibleFilters.map((f) => {
            const active = filter === f;
            const n = countFor(f, counts);
            return (
              <button
                key={f}
                type="button"
                aria-pressed={active}
                onClick={() => changeFilter(f)}
                data-testid={`changes-filter-${f}`}
                className={clsx(
                  'inline-flex h-6 items-center gap-1.5 rounded-full border px-2.5 text-xs font-medium transition-colors',
                  'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--act-accent)]',
                  active
                    ? 'border-transparent bg-oe-blue text-content-inverse'
                    : 'border-[var(--act-border)] text-[var(--act-text-2)] hover:bg-[var(--act-surface)] hover:text-[var(--act-text)]',
                )}
              >
                <span>{filterLabel(f, t)}</span>
                {n !== null && (
                  <span
                    className={clsx(
                      'tabular-nums',
                      active ? 'opacity-90' : 'text-[var(--act-text-3)]',
                      f === 'proposed' && n > 0 && !active && 'font-semibold text-[var(--act-accent)]',
                      f === 'failed' && n > 0 && !active && 'font-semibold text-[var(--act-error)]',
                    )}
                  >
                    {n}
                  </span>
                )}
              </button>
            );
          })}
        </div>
      </div>

      <div className="min-h-0 flex-1" aria-busy={loadingFirst || refreshing || undefined}>
        {loadingFirst && (
          <>
            <span className="sr-only" role="status">
              {t('erp_chat.changes.loading', { defaultValue: 'Loading changes…' })}
            </span>
            <ul>
              <RowSkeleton />
              <RowSkeleton />
              <RowSkeleton />
            </ul>
          </>
        )}

        {query.isError && !loadingFirst && (
          <div role="alert" className="m-3 flex items-start gap-2 rounded-md bg-semantic-error-bg px-3 py-2.5 text-xs">
            <AlertTriangle size={14} className="mt-px shrink-0 text-[var(--act-error)]" aria-hidden="true" />
            <div className="min-w-0 flex-1">
              <p className="font-semibold">
                {t('erp_chat.changes.load_failed', { defaultValue: 'The changes could not be loaded.' })}
              </p>
              <ActionButton tone="secondary" className="mt-2" onClick={() => void query.refetch()} icon={<RotateCcw size={12} />}>
                {t('erp_chat.changes.try_again', { defaultValue: 'Try again' })}
              </ActionButton>
            </div>
          </div>
        )}

        {empty && (
          <div className="flex flex-col items-center px-6 py-10 text-center" data-testid="changes-empty">
            <span className="mb-3 inline-flex h-10 w-10 items-center justify-center rounded-full bg-[var(--act-accent-subtle)] text-[var(--act-accent)]" aria-hidden="true">
              <Sparkles size={18} />
            </span>
            <p className="text-[13px] font-semibold text-[var(--act-text)]">{emptyCopy.title}</p>
            {emptyCopy.body && (
              <p className="mt-1 max-w-[340px] text-xs leading-relaxed text-[var(--act-text-2)]">{emptyCopy.body}</p>
            )}
          </div>
        )}

        {groups.map((group) => {
          const groupHeadingId = `${headingId}-${group.key}`;
          return (
            <section key={group.key} aria-labelledby={groupHeadingId}>
              <h4
                id={groupHeadingId}
                className="sticky top-0 z-[1] border-b border-[var(--act-border-subtle)] bg-[var(--act-surface)] px-3 py-1 text-[11px] font-semibold uppercase tracking-wide text-[var(--act-text-3)]"
              >
                {formatDayHeading(group.iso, t)}
              </h4>
              <ul>
                {group.items.map((row) => (
                  <ChangesRow key={row.id} action={row} showProject={showProject} />
                ))}
              </ul>
            </section>
          );
        })}

        {rows.length > 0 && total > rows.length && limit < MAX_ROWS && (
          <div className="flex justify-center px-3 py-3">
            <ActionButton
              tone="secondary"
              onClick={() => setLimit((l) => Math.min(l + PAGE_SIZE, MAX_ROWS))}
              busy={refreshing}
              busyLabel={String(t('erp_chat.changes.loading', { defaultValue: 'Loading changes…' }))}
              data-testid="changes-show-more"
            >
              {t('erp_chat.changes.show_more', {
                defaultValue: 'Show more ({{shown}} of {{total}})',
                shown: rows.length,
                total,
              })}
            </ActionButton>
          </div>
        )}

        {rows.length > 0 && total > rows.length && limit >= MAX_ROWS && (
          <p className="px-3 py-3 text-center text-[11px] text-[var(--act-text-3)]" data-testid="changes-capped">
            {t('erp_chat.changes.capped', {
              defaultValue: 'The latest {{shown}} of {{total}} are shown. Filter by status to find older ones.',
              shown: rows.length,
              total,
            })}
          </p>
        )}
      </div>

      {projectId && (
        <footer className="border-t border-[var(--act-border-subtle)] px-3 py-2">
          <button
            type="button"
            onClick={() => navigate(`/projects/${encodeURIComponent(projectId)}/timeline`)}
            className="inline-flex items-center gap-1.5 rounded text-xs font-medium text-[var(--act-accent)] hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--act-accent)]"
            data-testid="changes-full-history"
          >
            <History size={13} aria-hidden="true" />
            {t('erp_chat.changes.full_history', { defaultValue: 'Full project history' })}
          </button>
        </footer>
      )}
      <span className="sr-only" aria-live="polite">
        {!loadingFirst && counts
          ? String(
              t('erp_chat.changes.status_summary', {
                defaultValue: '{{label}}: {{count}}',
                label: filterLabel(filter, t),
                count: countFor(filter, counts) ?? 0,
              }),
            )
          : ''}
      </span>
    </section>
  );
}
