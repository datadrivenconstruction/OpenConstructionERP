// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * A change the assistant prepared, waiting for a person to decide.
 *
 * The card is the one place where the AI's work meets the project, so it says
 * plainly what will be written (field by field, old -> new for edits), how sure
 * the assistant is and why, and that nothing happens until someone clicks
 * Apply. After the decision it keeps the receipt: who applied or rejected it
 * and when, a link to the record it produced, and Undo where that is safe.
 *
 * States: proposed, applying (a request in flight), applied, rejected,
 * reverted ("Undone"), failed. Every button has a busy state, and the shared
 * store refuses a second request on the same action while one is in flight,
 * from this card or from the same row in the Changes tab.
 */
import { useEffect, useId, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import type { TFunction } from 'i18next';
import { useNavigate } from 'react-router-dom';
import clsx from 'clsx';
import {
  AlertTriangle,
  ArrowUpRight,
  Check,
  CheckCircle2,
  ChevronDown,
  Info,
  Pencil,
  RotateCcw,
  Undo2,
  X,
  XCircle,
} from 'lucide-react';
import { ConfidenceBadge } from '@/shared/ui/ConfidenceBadge';
import { ActionButton, ActionConfirmDialog } from './ActionControls';
import { ActionEditForm } from './ActionEditForm';
import { ActionFieldTable } from './ActionFieldTable';
import { ActionStatusPill } from './ActionStatusPill';
import { actionIcon } from './actionIcons';
import { describeFailure, describeRequestError, fieldErrorText } from './actionErrors';
import { formatActionTime } from './actionFormat';
import {
  clearActionRequestError,
  useActionPending,
  useActionRequestError,
  useApplyChatAction,
  useChatActionDetail,
  useChatActionView,
  usePatchChatAction,
  useRejectChatAction,
  useRevertChatAction,
} from './useChatActions';
import { isChatAction, isTerminalStatus, normalizeChatAction, type ActionStatus, type ChatAction } from './types';
import './actions.css';

export interface ActionProposalCardProps {
  /** The action as last received. A newer copy in the shared store wins. */
  action: ChatAction;
  /**
   * `card` (default): self-contained card for the chat transcript.
   * `embedded`: body only, for a Changes row that already shows the header.
   */
  variant?: 'card' | 'embedded';
  /**
   * Re-read the action from the server when the given copy may be stale (a
   * transcript reloaded from history). A copy younger than 15 s is trusted.
   */
  refreshOnMount?: boolean;
  className?: string;
}

// ── Helpers shared with the Changes rows ────────────────────────────────────

/** The action's title in the reader's language. */
export function actionTitle(action: ChatAction, t: TFunction): string {
  return action.title_key ? String(t(action.title_key, { defaultValue: action.title })) : action.title;
}

/** Subtitle line: the record's own text, then the project when asked for. */
export function actionSubtitle(action: ChatAction, withProject: boolean): string {
  const parts = [action.subtitle, withProject ? action.project_name : null].filter(
    (p): p is string => typeof p === 'string' && p.length > 0,
  );
  return parts.join(' · ');
}

/** Where "Open" goes: the produced record, else the record being changed. */
export function actionOpenUrl(action: ChatAction): string | null {
  return action.result?.url ?? action.target?.url ?? null;
}

/** Accessible name of the Open button: "Open Position 03.012" when the record has a label. */
export function openLabelFor(action: ChatAction, t: TFunction): string {
  const label = action.result?.label ?? action.target?.label ?? null;
  return label
    ? String(t('erp_chat.action.open_label', { defaultValue: 'Open {{label}}', label }))
    : String(t('erp_chat.action.open', { defaultValue: 'Open' }));
}

/** "Applied by Anna · 14:32" and its siblings, for a decided action. */
export function decisionLine(action: ChatAction, t: TFunction): string | null {
  const name = (who: { name: string | null } | null) => who?.name ?? null;
  switch (action.status) {
    case 'applied': {
      const time = formatActionTime(action.decided_at);
      const by = name(action.decided_by);
      return by
        ? String(t('erp_chat.action.applied_by', { defaultValue: 'Applied by {{name}} · {{time}}', name: by, time }))
        : String(t('erp_chat.action.applied_at', { defaultValue: 'Applied · {{time}}', time }));
    }
    case 'rejected': {
      const time = formatActionTime(action.decided_at);
      const by = name(action.decided_by);
      return by
        ? String(t('erp_chat.action.rejected_by', { defaultValue: 'Rejected by {{name}} · {{time}}', name: by, time }))
        : String(t('erp_chat.action.rejected_at', { defaultValue: 'Rejected · {{time}}', time }));
    }
    case 'reverted': {
      const time = formatActionTime(action.reverted_at);
      const by = name(action.reverted_by);
      return by
        ? String(t('erp_chat.action.reverted_by', { defaultValue: 'Undone by {{name}} · {{time}}', name: by, time }))
        : String(t('erp_chat.action.reverted_at', { defaultValue: 'Undone · {{time}}', time }));
    }
    default:
      return null;
  }
}

/** Body of the Undo confirmation, with the side-effect hint when there is one. */
export function undoConfirmMessage(action: ChatAction, t: TFunction): string {
  const base = String(
    t('erp_chat.action.undo_confirm_body', {
      defaultValue:
        'The record goes back to how it was before this change was applied. The undo is recorded in the project history too.',
    }),
  );
  if (!action.revert_hint_key) return action.revert_hint ? `${base} ${action.revert_hint}` : base;
  const hint = String(
    t(action.revert_hint_key, {
      defaultValue: action.revert_hint ?? 'Some effects of this change cannot be taken back automatically.',
    }),
  );
  return `${base} ${hint}`;
}

/** Why a waiting change cannot be applied by this person. */
export function blockedReason(action: ChatAction, t: TFunction): string {
  const fallback =
    action.blocked_reason ??
    String(
      t('erp_chat.action.cannot_apply', {
        defaultValue:
          'You cannot apply this change in this project. Someone with edit rights on it can review it in the Changes tab.',
      }),
    );
  return action.blocked_reason_key ? String(t(action.blocked_reason_key, { defaultValue: fallback })) : fallback;
}

// ── The card ────────────────────────────────────────────────────────────────

const STRIPE: Record<ActionStatus, string> = {
  proposed: 'border-s-[var(--act-accent)]',
  applied: 'border-s-[var(--act-success)]',
  failed: 'border-s-[var(--act-error)]',
  rejected: 'border-s-[var(--act-border)]',
  reverted: 'border-s-[var(--act-border)]',
};

export function ActionProposalCard({
  action: snapshot,
  variant = 'card',
  refreshOnMount = false,
  className,
}: ActionProposalCardProps) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const titleId = useId();
  const whyId = useId();
  const detailsId = useId();

  const action = useChatActionView(snapshot);
  useChatActionDetail(snapshot.id, {
    enabled: refreshOnMount && !isTerminalStatus(snapshot.status),
    initialData: refreshOnMount ? snapshot : undefined,
  });

  const pendingOp = useActionPending(action.id);
  const requestError = useActionRequestError(action.id);
  const applyMutation = useApplyChatAction();
  const rejectMutation = useRejectChatAction();
  const patchMutation = usePatchChatAction();
  const revertMutation = useRevertChatAction();

  const [editing, setEditing] = useState(false);
  const [whyOpen, setWhyOpen] = useState(false);
  const [detailsOpen, setDetailsOpen] = useState(false);
  const [confirmUndo, setConfirmUndo] = useState(false);
  const editButtonRef = useRef<HTMLButtonElement>(null);

  // A short glow when the status changes under the reader's eyes.
  const [settled, setSettled] = useState(false);
  const lastStatus = useRef(action.status);
  useEffect(() => {
    if (lastStatus.current === action.status) return;
    lastStatus.current = action.status;
    setSettled(true);
    const timer = setTimeout(() => setSettled(false), 900);
    return () => clearTimeout(timer);
  }, [action.status]);

  const busy = pendingOp !== null;
  const status = action.status;
  const canWork = status === 'proposed' || status === 'failed';
  const editableFields = useMemo(
    () => action.fields.filter((f) => f.editable && f.kind !== 'ref'),
    [action.fields],
  );
  const canEdit = canWork && action.can_edit && editableFields.length > 0;
  const isEditing = editing && canEdit;
  const collapsible = status === 'rejected' || status === 'reverted';
  const showFields = !collapsible || detailsOpen;
  const openUrl = actionOpenUrl(action);
  const Icon = actionIcon(action.action_type);
  const title = actionTitle(action, t);
  const subtitle = actionSubtitle(action, true);
  const decided = decisionLine(action, t);

  const closeEditor = () => {
    setEditing(false);
    // Give focus back to where the person started.
    setTimeout(() => editButtonRef.current?.focus(), 0);
  };

  const onApply = () => applyMutation.mutate(action.id);
  const onReject = () => rejectMutation.mutate({ id: action.id });
  const onSave = (payload: Record<string, unknown>) =>
    patchMutation.mutate(
      { id: action.id, payload },
      {
        onSuccess: (result) => {
          if (result) closeEditor();
        },
      },
    );
  const onUndoConfirmed = () =>
    revertMutation.mutate({ id: action.id }, { onSettled: () => setConfirmUndo(false) });
  const onOpen = () => {
    if (!openUrl) return;
    if (openUrl.startsWith('/')) navigate(openUrl);
    else window.open(openUrl, '_blank', 'noopener,noreferrer');
  };

  const openLabel = openLabelFor(action, t);
  const requestErrorText = requestError ? describeRequestError(requestError, t) : null;
  const saveFieldErrors = useMemo(
    () =>
      requestError?.op === 'save'
        ? Object.fromEntries(Object.entries(requestError.fieldErrors).map(([k, v]) => [k, fieldErrorText(v, t)]))
        : {},
    [requestError, t],
  );

  const header = variant === 'card' && (
    <header className="flex items-start gap-2.5">
      <span
        className="mt-0.5 inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-[var(--act-accent-subtle)] text-[var(--act-accent)]"
        aria-hidden="true"
      >
        <Icon size={15} />
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <h4 id={titleId} className="min-w-0 text-[13px] font-semibold leading-5 text-[var(--act-text)]">
            {title}
          </h4>
          <ActionStatusPill status={status} busyOp={pendingOp} className="ms-auto" />
        </div>
        {subtitle && <p className="mt-0.5 truncate text-xs text-[var(--act-text-2)]" title={subtitle}>{subtitle}</p>}
      </div>
    </header>
  );

  return (
    <article
      // Only the transcript card carries the anchor id: the same action can
      // be open in the Changes tab at the same time.
      id={variant === 'card' ? `erp-chat-action-${action.id}` : undefined}
      // Focusable from script, so "Review" can move the reader to the card.
      tabIndex={-1}
      aria-labelledby={variant === 'card' ? titleId : undefined}
      aria-label={variant === 'embedded' ? title : undefined}
      aria-busy={busy || undefined}
      data-testid="action-proposal-card"
      data-action-id={action.id}
      data-action-status={status}
      className={clsx(
        'oe-act text-[var(--act-text)] focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--act-accent)]',
        variant === 'card' &&
          clsx(
            'oe-act-enter my-1.5 rounded-[var(--act-radius)] border border-s-[3px] border-[var(--act-border-subtle)] bg-[var(--act-bg)] p-3 shadow-xs',
            STRIPE[status],
          ),
        settled && 'oe-act-settle',
        className,
      )}
    >
      {header}

      <div className={clsx('space-y-2.5', variant === 'card' && 'mt-2.5')}>
        {action.summary && (
          <p className="text-[13px] leading-snug text-[var(--act-text-2)]">{action.summary}</p>
        )}

        {collapsible && (
          <button
            type="button"
            aria-expanded={detailsOpen}
            aria-controls={detailsId}
            onClick={() => setDetailsOpen((v) => !v)}
            className="inline-flex items-center gap-1 rounded text-xs font-medium text-[var(--act-text-2)] hover:text-[var(--act-text)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--act-accent)]"
          >
            <ChevronDown
              size={13}
              aria-hidden="true"
              className={clsx('transition-transform motion-reduce:transition-none', detailsOpen && 'rotate-180')}
            />
            {detailsOpen
              ? t('erp_chat.action.hide_details', { defaultValue: 'Hide details' })
              : t('erp_chat.action.show_details', { defaultValue: 'Show details' })}
          </button>
        )}

        {isEditing ? (
          <ActionEditForm
            action={action}
            busy={pendingOp === 'save'}
            serverFieldErrors={saveFieldErrors}
            onSubmit={onSave}
            onCancel={closeEditor}
          />
        ) : (
          showFields && (
            <div id={detailsId} className={clsx(collapsible && 'opacity-80')}>
              <ActionFieldTable fields={action.fields} notes={action.notes} />
            </div>
          )
        )}

        {(action.confidence !== null || action.rationale || action.edited) && showFields && !isEditing && (
          <div className="flex flex-wrap items-center gap-2">
            {action.confidence !== null && <ConfidenceBadge score={action.confidence} showScore />}
            {action.edited && (
              <span
                className="inline-flex h-5 items-center gap-1 rounded-full bg-[var(--act-surface-2)] px-1.5 text-[11px] font-medium text-[var(--act-text-2)]"
                title={String(
                  t('erp_chat.action.edited_hint', {
                    defaultValue: 'A person changed the values the assistant proposed.',
                  }),
                )}
              >
                <Pencil size={10} aria-hidden="true" />
                {t('erp_chat.action.edited', { defaultValue: 'Edited by a person' })}
              </span>
            )}
            {action.rationale && (
              <button
                type="button"
                aria-expanded={whyOpen}
                aria-controls={whyId}
                onClick={() => setWhyOpen((v) => !v)}
                className="inline-flex items-center gap-1 rounded text-xs font-medium text-[var(--act-accent)] hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--act-accent)]"
              >
                <Info size={12} aria-hidden="true" />
                {t('erp_chat.action.why', { defaultValue: 'Why?' })}
              </button>
            )}
          </div>
        )}
        {action.rationale && whyOpen && showFields && !isEditing && (
          <p
            id={whyId}
            className="rounded-md bg-[var(--act-surface)] px-2.5 py-2 text-xs leading-relaxed text-[var(--act-text-2)]"
          >
            {action.rationale}
          </p>
        )}

        {/* Outcome and actions. Announced when they change. */}
        <div aria-live="polite" className="space-y-2">
          {status === 'failed' && (
            <div
              role="alert"
              className="flex gap-2 rounded-md bg-semantic-error-bg px-2.5 py-2 text-xs text-[var(--act-text)]"
            >
              <AlertTriangle size={14} className="mt-px shrink-0 text-[var(--act-error)]" aria-hidden="true" />
              <div className="min-w-0">
                <p className="font-semibold">
                  {t('erp_chat.action.failed_title', { defaultValue: 'This change could not be applied' })}
                </p>
                <p className="mt-0.5 text-[var(--act-text-2)]">{describeFailure(action, t)}</p>
              </div>
            </div>
          )}

          {requestErrorText && (
            <div
              role="alert"
              className="flex items-start gap-2 rounded-md bg-semantic-warning-bg px-2.5 py-2 text-xs text-[var(--act-text)]"
              data-testid="action-request-error"
            >
              <AlertTriangle size={14} className="mt-px shrink-0 text-[var(--act-warning)]" aria-hidden="true" />
              <p className="min-w-0 flex-1">{requestErrorText}</p>
              <button
                type="button"
                onClick={() => clearActionRequestError(action.id)}
                className="shrink-0 rounded p-0.5 text-[var(--act-text-3)] hover:text-[var(--act-text)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--act-accent)]"
                aria-label={String(t('erp_chat.action.dismiss', { defaultValue: 'Dismiss message' }))}
              >
                <X size={12} aria-hidden="true" />
              </button>
            </div>
          )}

          {decided && (
            <p className="flex flex-wrap items-center gap-1.5 text-xs text-[var(--act-text-2)]" data-testid="action-decision">
              {status === 'applied' && (
                <CheckCircle2 size={14} className="shrink-0 text-[var(--act-success)]" aria-hidden="true" />
              )}
              {status === 'rejected' && (
                <XCircle size={14} className="shrink-0 text-[var(--act-text-3)]" aria-hidden="true" />
              )}
              {status === 'reverted' && (
                <Undo2 size={14} className="shrink-0 text-[var(--act-text-3)]" aria-hidden="true" />
              )}
              <span>{decided}</span>
            </p>
          )}
          {status === 'rejected' && action.decision_note && (
            <p className="border-s-2 border-[var(--act-border)] ps-2 text-xs italic text-[var(--act-text-2)]">
              {action.decision_note}
            </p>
          )}
          {status === 'reverted' && action.revert_note && (
            <p className="border-s-2 border-[var(--act-border)] ps-2 text-xs italic text-[var(--act-text-2)]">
              {action.revert_note}
            </p>
          )}

          {canWork && !isEditing && (
            <>
              <div className="flex flex-wrap items-center gap-2">
                {action.can_apply && (
                  <ActionButton
                    tone="primary"
                    onClick={onApply}
                    busy={pendingOp === 'apply'}
                    busyLabel={String(t('erp_chat.action.busy.apply', { defaultValue: 'Applying…' }))}
                    disabled={busy}
                    icon={status === 'failed' ? <RotateCcw size={13} /> : <Check size={13} />}
                    data-testid="action-apply"
                  >
                    {status === 'failed'
                      ? t('erp_chat.action.retry', { defaultValue: 'Retry' })
                      : t('erp_chat.action.apply', { defaultValue: 'Apply' })}
                  </ActionButton>
                )}
                {canEdit && (
                  <ActionButton
                    ref={editButtonRef}
                    tone="secondary"
                    onClick={() => setEditing(true)}
                    disabled={busy}
                    icon={<Pencil size={12} />}
                    data-testid="action-edit"
                  >
                    {t('erp_chat.action.edit', { defaultValue: 'Edit' })}
                  </ActionButton>
                )}
                {action.can_reject && (
                  <ActionButton
                    tone="ghost"
                    onClick={onReject}
                    busy={pendingOp === 'reject'}
                    busyLabel={String(t('erp_chat.action.busy.reject', { defaultValue: 'Rejecting…' }))}
                    disabled={busy}
                    icon={<X size={13} />}
                    data-testid="action-reject"
                  >
                    {t('erp_chat.action.reject', { defaultValue: 'Reject' })}
                  </ActionButton>
                )}
              </div>
              {action.can_apply ? (
                status === 'proposed' && (
                  <p className="text-[11px] text-[var(--act-text-3)]">
                    {t('erp_chat.action.not_saved_yet', {
                      defaultValue: 'Nothing is saved until you click Apply. Every applied change is logged.',
                    })}
                  </p>
                )
              ) : (
                <p className="text-[11px] text-[var(--act-text-2)]" data-testid="action-blocked-reason">
                  {blockedReason(action, t)}
                </p>
              )}
            </>
          )}

          {status === 'applied' && (openUrl || action.can_revert) && (
            <div className="flex flex-wrap items-center gap-2">
              {openUrl && (
                <ActionButton
                  tone="secondary"
                  onClick={onOpen}
                  icon={<ArrowUpRight size={13} className="rtl:-scale-x-100" />}
                  data-testid="action-open"
                  title={openLabel}
                  aria-label={openLabel}
                >
                  {t('erp_chat.action.open', { defaultValue: 'Open' })}
                </ActionButton>
              )}
              {action.can_revert && (
                <ActionButton
                  tone="ghost"
                  onClick={() => setConfirmUndo(true)}
                  busy={pendingOp === 'revert'}
                  busyLabel={String(t('erp_chat.action.busy.revert', { defaultValue: 'Undoing…' }))}
                  disabled={busy}
                  icon={<Undo2 size={13} />}
                  data-testid="action-undo"
                >
                  {t('erp_chat.action.undo', { defaultValue: 'Undo' })}
                </ActionButton>
              )}
            </div>
          )}
        </div>
      </div>

      <ActionConfirmDialog
        open={confirmUndo}
        title={String(t('erp_chat.action.undo_confirm_title', { defaultValue: 'Undo this change?' }))}
        message={undoConfirmMessage(action, t)}
        confirmLabel={String(t('erp_chat.action.undo_confirm', { defaultValue: 'Undo change' }))}
        cancelLabel={String(t('erp_chat.action.undo_keep', { defaultValue: 'Keep it' }))}
        loading={pendingOp === 'revert'}
        onConfirm={onUndoConfirmed}
        onCancel={() => setConfirmUndo(false)}
      />
    </article>
  );
}

/**
 * Registry adapter: chat renderers receive `{ data: unknown }`. A payload that
 * is not a proposal says so instead of rendering nothing.
 */
export function ActionProposalRenderer({ data }: { data: unknown }) {
  const { t } = useTranslation();
  const snapshot = useMemo(() => (isChatAction(data) ? normalizeChatAction(data) : null), [data]);
  if (!snapshot) {
    return (
      <p className="oe-act px-3 py-2 text-xs text-[var(--act-text-3)]">
        {t('erp_chat.action.unreadable', { defaultValue: 'This proposed change could not be shown.' })}
      </p>
    );
  }
  return <ActionProposalCard action={snapshot} refreshOnMount />;
}

export default ActionProposalRenderer;
