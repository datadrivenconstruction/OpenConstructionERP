// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * "3 changes are waiting for your review" - pinned above the composer while
 * the current conversation has proposals nobody has decided on yet.
 *
 * Review hands control back to the dock (it scrolls to the first waiting
 * card). Apply all asks once, listing what will be written, and then applies
 * each proposal on its own: one that fails does not stop the others, and the
 * card of the failed one says why.
 *
 * The outer component reads only the shared store and its props, and renders
 * nothing when nothing is waiting, so the dock can mount it unconditionally
 * without a React Query provider being involved until there is work to do.
 */
import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { CheckCheck, Eye, Inbox } from 'lucide-react';
import { fmtList } from '@/shared/lib/formatters';
import { useToastStore } from '@/stores/useToastStore';
import { ActionButton, ActionConfirmDialog } from './ActionControls';
import { actionTitle } from './ActionProposalCard';
import { useApplyChatActionsBatch, useLiveChatActions } from './useChatActions';
import type { ChatAction } from './types';
import './actions.css';

export interface ActionsReviewTrayProps {
  /** Proposals of the current conversation (any status; only waiting ones count). */
  actions: ChatAction[];
  /** Bring the first waiting proposal into view. */
  onReview: () => void;
}

/** Titles listed in the Apply-all confirmation before "and N more". */
const LISTED_TITLES = 5;

/**
 * For the tray's Review button: scroll the first waiting proposal card of the
 * transcript into view and move focus to it, so a screen reader announces its
 * title. Searches `root` (pass the dock's message list) or the whole document.
 * Only transcript cards match (they alone carry the `erp-chat-action-<id>`
 * anchor), never the same proposal expanded in a Changes row. Returns false
 * when no waiting card is rendered, for example while the conversation loads.
 */
export function revealFirstWaitingAction(root: ParentNode = document): boolean {
  const card = root.querySelector<HTMLElement>('[id^="erp-chat-action-"][data-action-status="proposed"]');
  if (!card) return false;
  const reduceMotion =
    typeof window.matchMedia === 'function' && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  // jsdom and some embedded browsers have no scrollIntoView.
  if (typeof card.scrollIntoView === 'function') {
    card.scrollIntoView({ behavior: reduceMotion ? 'auto' : 'smooth', block: 'center' });
  }
  card.focus({ preventScroll: true });
  return true;
}

export function ActionsReviewTray({ actions, onReview }: ActionsReviewTrayProps) {
  const live = useLiveChatActions(actions);
  const waiting = useMemo(() => live.filter((a) => a.status === 'proposed'), [live]);
  if (waiting.length === 0) return null;
  return <ReviewTrayBar waiting={waiting} onReview={onReview} />;
}

function ReviewTrayBar({ waiting, onReview }: { waiting: ChatAction[]; onReview: () => void }) {
  const { t } = useTranslation();
  const batch = useApplyChatActionsBatch();
  const [confirmOpen, setConfirmOpen] = useState(false);
  const applicable = useMemo(() => waiting.filter((a) => a.can_apply), [waiting]);
  const skipped = waiting.length - applicable.length;

  const confirmMessage = useMemo(() => {
    const titles = applicable.slice(0, LISTED_TITLES).map((a) => actionTitle(a, t));
    const more = applicable.length - titles.length;
    if (more > 0) {
      titles.push(
        String(t('erp_chat.tray.more_items', { count: more, defaultValue: '{{count}} more', defaultValue_other: '{{count}} more' })),
      );
    }
    const body = String(
      t('erp_chat.tray.confirm_body', {
        defaultValue: 'These will be written to the project and recorded in its history: {{list}}.',
        list: fmtList(titles),
      }),
    );
    if (skipped === 0) return body;
    const note = String(
      t('erp_chat.tray.confirm_skipped', {
        count: skipped,
        defaultValue: '{{count}} change you cannot apply stays waiting.',
        defaultValue_other: '{{count}} changes you cannot apply stay waiting.',
      }),
    );
    return `${body} ${note}`;
  }, [applicable, skipped, t]);

  // mutateAsync, not mutate with callbacks: applying empties the tray, the
  // tray unmounts, and per-call callbacks of an unmounted observer never run.
  // The promise does, so the summary toast is not lost with the tray.
  const applyAll = async () => {
    const ids = applicable.map((a) => a.id);
    const addToast = useToastStore.getState().addToast;
    try {
      const items = await batch.mutateAsync(ids);
      const applied = items.filter((a) => ids.includes(a.id) && a.status === 'applied').length;
      if (applied > 0 && applied === ids.length) {
        addToast({
          type: 'success',
          title: String(
            t('erp_chat.tray.applied_toast', {
              count: applied,
              defaultValue: '{{count}} change applied',
              defaultValue_other: '{{count}} changes applied',
            }),
          ),
          message: String(
            t('erp_chat.tray.applied_toast_body', {
              defaultValue: 'Each one is recorded in the project history.',
            }),
          ),
        });
      } else if (ids.length > 0) {
        addToast({
          type: 'warning',
          title: String(
            t('erp_chat.tray.partial_toast', {
              defaultValue: '{{applied}} of {{total}} changes applied',
              applied,
              total: ids.length,
            }),
          ),
          message: String(
            t('erp_chat.tray.partial_toast_body', {
              defaultValue: 'The others could not be applied. Their cards say why.',
            }),
          ),
        });
      }
    } catch {
      addToast({
        type: 'error',
        title: String(t('erp_chat.tray.failed_toast', { defaultValue: 'The changes could not be applied' })),
        message: String(
          t('erp_chat.tray.failed_toast_body', {
            defaultValue: 'Nothing was changed. Try again, or apply them one by one.',
          }),
        ),
      });
    } finally {
      setConfirmOpen(false);
    }
  };

  const count = waiting.length;
  return (
    <div
      role="region"
      aria-label={String(t('erp_chat.tray.label', { defaultValue: 'Changes waiting for review' }))}
      className="oe-act oe-act-enter flex flex-wrap items-center gap-x-3 gap-y-2 rounded-[var(--act-radius)] border border-[var(--act-border-subtle)] bg-[var(--act-accent-subtle)] px-3 py-2"
      data-testid="actions-review-tray"
    >
      <p className="flex min-w-0 flex-1 items-center gap-2 text-[13px] font-medium text-[var(--act-text)]" aria-live="polite">
        <Inbox size={15} className="shrink-0 text-[var(--act-accent)]" aria-hidden="true" />
        <span data-testid="actions-review-tray-count">
          {t('erp_chat.tray.waiting', {
            count,
            defaultValue: '{{count}} change is waiting for your review',
            defaultValue_other: '{{count}} changes are waiting for your review',
          })}
        </span>
      </p>
      <div className="flex shrink-0 items-center gap-2">
        <ActionButton tone="secondary" onClick={onReview} icon={<Eye size={13} />} data-testid="actions-review-tray-review">
          {t('erp_chat.tray.review', { defaultValue: 'Review' })}
        </ActionButton>
        {applicable.length > 0 && (
          <ActionButton
            tone="primary"
            onClick={() => setConfirmOpen(true)}
            busy={batch.isPending}
            busyLabel={String(t('erp_chat.action.busy.apply', { defaultValue: 'Applying…' }))}
            icon={<CheckCheck size={13} />}
            data-testid="actions-review-tray-apply-all"
          >
            {applicable.length === 1
              ? t('erp_chat.action.apply', { defaultValue: 'Apply' })
              : t('erp_chat.tray.apply_all', { defaultValue: 'Apply all' })}
          </ActionButton>
        )}
      </div>
      <ActionConfirmDialog
        open={confirmOpen}
        title={String(
          t('erp_chat.tray.confirm_title', {
            count: applicable.length,
            defaultValue: 'Apply {{count}} change?',
            defaultValue_other: 'Apply {{count}} changes?',
          }),
        )}
        message={confirmMessage}
        confirmLabel={
          applicable.length === 1
            ? String(t('erp_chat.action.apply', { defaultValue: 'Apply' }))
            : String(t('erp_chat.tray.apply_all', { defaultValue: 'Apply all' }))
        }
        cancelLabel={String(t('erp_chat.tray.confirm_cancel', { defaultValue: 'Not now' }))}
        loading={batch.isPending}
        onConfirm={() => void applyAll()}
        onCancel={() => setConfirmOpen(false)}
      />
    </div>
  );
}
